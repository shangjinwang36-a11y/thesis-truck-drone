"""固定结构下的前向调度、充电 LP、能量链与完整成本评价.

对应规范：第6章（能量/充电/成本）、第7.15节（固定结构时序充电 LP）。

设计说明
--------
* 时序：固定点迭代（卡车→无人机→卡车），所有时刻只增不减，取最早可行时刻。
  这是"参考构序 + 前向传播"的确定性实现，用于替代规范中的三阶段 LP。
* 充电：按"同一机、同一实际承运车、连续具备充电资格"的阶段建立线性规划，
  目标最小化车载交流输出总量（等价于最小化电费，因为
  c_vehicle − eta_slot·c_depot > 0）。约束：逐阶段端点电量、回收余电下限、
  电池上限、单槽 2 kW、整车 4 kW、每车 4 kWh 交流预算。
* 独立核验器从计划与时刻重新累计，见 verify.py。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import linprog

from .config import PhysicalConfig, home_truck
from .data import Instance
from .plan import Plan, Sortie

EPS = 1e-9


# ---------------------------------------------------------------------------
# 起始状态
# ---------------------------------------------------------------------------
@dataclass
class DroneStart:
    kind: str                       # "ON_TRUCK" | "AIRBORNE"
    truck: str | None = None
    ready_time: float = 0.0
    pos: tuple[float, float] | None = None
    energy: float = 0.0
    aboard: list[str] = field(default_factory=list)
    service_parcel: str | None = None   # 第三轮：截断时正在服务（悬停交付）的包裹
    service_done_s: float = 0.0         # 第三轮：该服务截断前已进行的秒数（残段只补完剩余部分）


@dataclass
class StartState:
    t0: float = 0.0
    truck_start_pos: dict[str, tuple[float, float]] = field(default_factory=dict)
    truck_start_time: dict[str, float] = field(default_factory=dict)
    truck_first_travel_s: dict[str, float] = field(default_factory=dict)
    truck_ready_time: dict[str, float] = field(default_factory=dict)
    truck_ac: dict[str, float] = field(default_factory=dict)
    truck_onboard: dict[str, list[str]] = field(default_factory=dict)
    truck_fixed_first: dict[str, bool] = field(default_factory=dict)
    truck_min_insert: dict[str, int] = field(default_factory=dict)
    truck_done: dict[str, float] = field(default_factory=dict)
    parcel_holder: dict[str, str] = field(default_factory=dict)
    drone_start: dict[str, DroneStart] = field(default_factory=dict)
    delivered: set[str] = field(default_factory=set)
    prefix_distance_m: float = 0.0
    prefix_ac_kwh: float = 0.0
    prefix_refill_kwh: float = 0.0      # 换电配置：此前各段已换下电池的待回库补电量(kWh)
    drone_energy: dict[str, float] = field(default_factory=dict)
    dispatched: set[str] = field(default_factory=set)
    drone_carrier: dict[str, str] = field(default_factory=dict)
    note: str = ""
    nominal_cross: bool = False     # 第六轮：X 的名义规划允许跨车航次（仅名义阶段使用）
    # 第四轮：仅 X 恢复把已知失败概率和残差空送集合放在状态上，供修复代理计价。S 保持 0 / None。
    x_failure_p: float = 0.0
    air_ceiling: set[str] | None = None


def initial_state(inst: Instance, phys: PhysicalConfig) -> StartState:
    phys.set_active()
    st = StartState(t0=0.0)
    depot = (inst.depot_x, inst.depot_y)
    for k in range(phys.truck_count):
        t = f"t{k+1}"
        st.truck_start_pos[t] = depot
        st.truck_start_time[t] = 0.0
        st.truck_first_travel_s[t] = 0.0
        st.truck_ready_time[t] = 0.0
        # 换电配置：truck_ac 记"剩余满电备用电池块数"；充电配置：剩余交流预算 kWh
        st.truck_ac[t] = float(phys.spare_batteries) if phys.swap_mode else phys.truck_initial_ac_kwh
        st.truck_onboard[t] = []
    for d in range(phys.drone_count):
        did = f"d{d+1}"
        st.drone_start[did] = DroneStart("ON_TRUCK", phys.home_truck(did), 0.0, depot, phys.e_cap)
        st.drone_energy[did] = phys.e_cap
    return st


# ---------------------------------------------------------------------------
# 时刻表
# ---------------------------------------------------------------------------
@dataclass
class ActionRec:
    kind: str
    actor: str
    start: float
    end: float
    ref: str = ""
    mass: float = 0.0
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class DroneStage:
    kind: str
    start: float
    end: float
    truck: str | None = None
    mass: float = 0.0
    parcel: str | None = None
    sid: int | None = None
    dist: float = 0.0
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    svc_done0: float = 0.0          # 第三轮：续飞残段的空中服务已完成时长（该 SERVICE 阶段只剩余下的部分）
    resumed: bool = False           # 第三轮：True=接续被截断的服务，不是新的到场(不产生新的到场观察)
    landed: bool = False            # v6：降落等待阶段(WAIT/R)：零能耗，R 免备用电量


@dataclass
class Timeline:
    t0: float
    visit_arr: dict[int, float] = field(default_factory=dict)
    visit_dep: dict[int, float] = field(default_factory=dict)
    truck_finish: dict[str, float] = field(default_factory=dict)
    truck_distance_m: dict[str, float] = field(default_factory=dict)
    actions: list[ActionRec] = field(default_factory=list)
    drone_stages: dict[str, list[DroneStage]] = field(default_factory=dict)
    drone_energy: dict[str, list[float]] = field(default_factory=dict)
    launch_times: dict[int, tuple[float, float, tuple[float, float]]] = field(default_factory=dict)
    rec_times: dict[int, tuple[float, float]] = field(default_factory=dict)
    energy_ok: bool = True
    energy_msg: str = ""
    q_total: float = 0.0
    q_by_truck: dict[str, float] = field(default_factory=dict)
    q_by_stage: dict[str, float] = field(default_factory=dict)
    e_return: dict[str, float] = field(default_factory=dict)
    wait_by_sortie: dict[int, float] = field(default_factory=dict)
    custody_violations: list[str] = field(default_factory=list)
    waits: dict[int, float] = field(default_factory=dict)
    deficits: dict[str, float] = field(default_factory=dict)
    lp_calls: int = 0
    drone_arrival: dict[int, float] = field(default_factory=dict)
    drone_available: dict[int, float] = field(default_factory=dict)
    drone_ready_before: dict[int, float] = field(default_factory=dict)
    iterations: int = 0
    converged: bool = True                              # 第六轮：固定点是否收敛（跨车名义航次可能成环）
    swaps: set = field(default_factory=set)             # 需要换电的航次 sid（换电配置）
    swap_msg: str = ""                                  # 非空：换电后仍无法满足能量
    swap_refill_kwh: float = 0.0                        # 本段内换下电池的补电量
    swap_count_by_truck: dict = field(default_factory=dict)


def _dist(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _pos_along(p: tuple[float, float], q: tuple[float, float], lam: float) -> tuple[float, float]:
    return (p[0] + (q[0] - p[0]) * lam, p[1] + (q[1] - p[1]) * lam)


def _launch_geometry(plan: Plan, inst: Instance, s: Sortie) -> tuple[tuple[float, float], tuple[float, float], float]:
    """返回 (弧起点, 弧终点, 弧长)；仓库/驻车模式返回同一点."""
    if s.launch_vid is None:
        p = (inst.depot_x, inst.depot_y)
        route = plan.routes.get(s.truck or "", [])
        if not route:
            return p, p, 0.0
        c = inst.customer(plan.visits[route[0]].customer)
        return p, (c.x, c.y), _dist(p, (c.x, c.y))
    v = plan.visits[s.launch_vid]
    truck_route = plan.routes[v.truck]
    idx = truck_route.index(v.vid)
    c0 = inst.customer(v.customer)
    p = (c0.x, c0.y)
    if s.mode == "ARC" and idx + 1 < len(truck_route):
        c1 = inst.customer(plan.visits[truck_route[idx + 1]].customer)
        q = (c1.x, c1.y)
        return p, q, _dist(p, q)
    return p, p, 0.0


# ---------------------------------------------------------------------------
# 调度主函数
# ---------------------------------------------------------------------------
def schedule_plan(plan: Plan, inst: Instance, phys: PhysicalConfig,
                  state: StartState | None = None, max_iter: int = 14,
                  waits: dict[int, float] | None = None) -> Timeline:
    state = state or initial_state(inst, phys)
    waits = waits or {}
    trucks = [f"t{k+1}" for k in range(phys.truck_count)]
    drones = [f"d{k+1}" for k in range(phys.drone_count)]
    recoveries_at: dict[int, list[Sortie]] = {}
    launches_at: dict[int, list[Sortie]] = {}
    depot_launches: dict[str, list[Sortie]] = {}
    for s in plan.sorties.values():
        recoveries_at.setdefault(s.rec_vid, []).append(s)
        if s.launch_vid is None:
            if not s.started:
                depot_launches.setdefault(s.truck or "", []).append(s)
        elif not s.started:
            launches_at.setdefault(s.launch_vid, []).append(s)
    for lst in recoveries_at.values():
        lst.sort(key=lambda x: (x.rec_priority, x.drone, x.sid))
    for lst in launches_at.values():
        lst.sort(key=lambda x: (x.launch_priority, x.sid))
    for lst in depot_launches.values():
        lst.sort(key=lambda x: (x.launch_priority, x.sid))

    drone_arr: dict[int, float] = {}
    prev_avail: dict[str, float] = {}
    prev_key = None
    tl = Timeline(t0=state.t0)
    swaps: set[int] = set()
    swap_msg = ""
    max_iter = max_iter + (8 if phys.swap_mode else 0)
    for it in range(max_iter):
        tl = Timeline(t0=state.t0)
        _schedule_trucks(plan, inst, phys, state, tl, trucks, drone_arr,
                         recoveries_at, launches_at, depot_launches, prev_avail, waits, swaps)
        tl.waits = dict(waits)
        _schedule_drones(plan, inst, phys, state, tl, drones)
        if phys.swap_mode:
            new_swaps, swap_msg = _swap_pass(tl, plan, phys, state, swaps)
            if new_swaps != swaps:
                swaps = new_swaps
                prev_key = None
                drone_arr = {sid: tl.drone_arrival.get(sid, tl.rec_times[sid][0]) for sid in tl.rec_times}
                prev_avail = dict(tl.drone_ready_before)
                continue
        tl.swaps = set(swaps)
        tl.swap_msg = swap_msg
        key = _timeline_key(tl)
        if prev_key is not None and key == prev_key:
            tl.iterations = it + 1
            tl.converged = True
            break
        prev_key = key
        drone_arr = {sid: tl.drone_arrival.get(sid, tl.rec_times[sid][0]) for sid in tl.rec_times}
        prev_avail = dict(tl.drone_ready_before)
        tl.iterations = it + 1
    else:
        tl.iterations = max_iter
        tl.converged = False
    _compute_distances(plan, inst, state, tl, trucks)
    return tl


def _timeline_key(tl: Timeline) -> tuple:
    vals = [round(tl.visit_arr[v], 6) for v in sorted(tl.visit_arr)]
    vals += [round(tl.visit_dep[v], 6) for v in sorted(tl.visit_dep)]
    vals += [round(tl.rec_times[s][0], 6) for s in sorted(tl.rec_times)]
    vals += [round(tl.truck_finish[k], 6) for k in sorted(tl.truck_finish)]
    return tuple(vals)


def _schedule_trucks(plan: Plan, inst: Instance, phys: PhysicalConfig, state: StartState,
                     tl: Timeline, trucks: list[str], drone_arr: dict[int, float],
                     recoveries_at: dict[int, list[Sortie]], launches_at: dict[int, list[Sortie]],
                     depot_launches: dict[str, list[Sortie]],
                     prev_avail: dict[str, float] | None = None,
                     waits: dict[int, float] | None = None,
                     swaps: set[int] | None = None) -> None:
    prev_avail = prev_avail or {}
    swaps = swaps or set()
    waits = waits or {}
    local_avail: dict[tuple, float] = {}   # 第六轮：按（车，机）记录，避免跨车回收的可用时刻泄漏到别车的放飞
    # 货物保管：truck_inv / depot_pool
    holder = state.parcel_holder or {}
    truck_inv: dict[str, set[str]] = {k: set() for k in trucks}
    depot_pool: set[str] = set()
    for p, h in holder.items():
        if h.startswith("TRUCK:"):
            truck_inv.setdefault(h.split(":", 1)[1], set()).add(p)
        elif h == "DEPOT":
            depot_pool.add(p)
    nominal_initial = not holder
    vt = phys.truck_speed_m_s
    depot = (inst.depot_x, inst.depot_y)
    for truck in trucks:
        route = plan.routes.get(truck, [])
        start_time = state.truck_start_time.get(truck, 0.0)
        start_pos = state.truck_start_pos.get(truck, depot)
        first_travel = state.truck_first_travel_s.get(truck, 0.0)
        ready = max(start_time, state.truck_ready_time.get(truck, 0.0))
        channel_free = max(start_time, ready)
        if not route and truck not in depot_launches:
            if truck in state.truck_done:
                # 快照前已返库：保留真实到库时刻（不虚构新的回库行驶）
                tl.truck_finish[truck] = state.truck_done[truck]
                continue
            if state.t0 > 0:
                depot_leg = _dist(start_pos, depot)
                depart = max(start_time, state.truck_ready_time.get(truck, start_time))
                arrive = depart + depot_leg / vt
                tl.actions.append(ActionRec("DRIVE", truck, depart, arrive, "DEPOT",
                                            info={"from": start_pos, "to": depot, "dist": depot_leg}))
                tl.truck_finish[truck] = arrive
            else:
                tl.truck_finish[truck] = 0.0
            continue
        depart_depot = ready
        prep_end: dict[int, float] = {}
        for s in depot_launches.get(truck, []):
            t0 = max(depart_depot, local_avail.get((truck, s.drone), 0.0), prev_avail.get(s.sid, 0.0))
            if s.sid in swaps:
                tl.actions.append(ActionRec("W", truck, t0, t0 + phys.swap_s, f"S{s.sid}",
                                            info={"drone": s.drone, "depot": True}))
                t0 += phys.swap_s
            prep_end[s.sid] = t0 + phys.prepare_s
            tl.actions.append(ActionRec("P", truck, t0, t0 + phys.prepare_s, f"S{s.sid}",
                                        info={"drone": s.drone, "depot": True}))
            depart_depot = prep_end[s.sid]
        # 仓库放飞：L 在首段弧上
        for s in depot_launches.get(truck, []):
            p, q, D = _launch_geometry(plan, inst, s)
            lam = min(1.0, max(0.0, s.lam))
            l_end = depart_depot + lam * D / vt
            l_start = l_end - phys.launch_s
            if l_start < prep_end[s.sid] - EPS:
                depart_depot += prep_end[s.sid] - l_start
                l_end = depart_depot + lam * D / vt
                l_start = l_end - phys.launch_s
            if l_start < channel_free - EPS:
                depart_depot += channel_free - l_start
                l_end = depart_depot + lam * D / vt
                l_start = l_end - phys.launch_s
            pos = _pos_along(p, q, lam)
            tl.launch_times[s.sid] = (l_start, l_end, pos)
            tl.actions.append(ActionRec("L", s.drone, l_start, l_end, f"S{s.sid}",
                                        info={"truck": truck, "pos": pos, "mode": "ARC"}))
            channel_free = max(channel_free, l_end)
        t_prev = depart_depot
        pos_prev = start_pos if state.t0 > 0 else depot
        for i, vid in enumerate(route):
            v = plan.visits[vid]
            c = inst.customer(v.customer)
            cpos = (c.x, c.y)
            if i == 0:
                # 新后缀第一段：从真实快照坐标到目标访问按几何重算（不可撤销段的位置已在
                # 截断时按真实进度插值），保证 dist = v_T × 时长
                leg_dist = _dist(start_pos, cpos)
                travel = leg_dist / vt
            else:
                leg_dist = _dist(pos_prev, cpos)
                travel = leg_dist / vt
            t_arr = t_prev + travel
            ready = max(t_arr, t_prev)
            tl.visit_arr[vid] = t_arr
            tl.actions.append(ActionRec("DRIVE", truck, t_prev, t_arr, v.customer,
                                        info={"from": pos_prev, "to": cpos, "dist": leg_dist}))
            for s in recoveries_at.get(vid, []):
                arr = drone_arr.get(s.sid, t_arr)
                r_start = max(ready, t_arr, arr, channel_free)
                r_end = r_start + phys.recovery_s
                if s.handover:
                    u_end = r_end + phys.handover_s
                else:
                    u_end = r_end
                ready = u_end
                channel_free = r_end
                local_avail[(truck, s.drone)] = u_end
                tl.rec_times[s.sid] = (r_start, r_end)
                tl.drone_available[s.sid] = u_end
                tl.wait_by_sortie[s.sid] = max(0.0, r_start - arr)
                tl.actions.append(ActionRec("R", truck, r_start, r_end, f"S{s.sid}",
                                            info={"drone": s.drone, "customer": v.customer,
                                                  "truck_wait": max(0.0, r_start - t_arr),
                                                  "drone_wait": max(0.0, r_start - arr)}))
                if s.handover:
                    tl.actions.append(ActionRec("U", truck, r_end, u_end, f"S{s.sid}",
                                                info={"drone": s.drone, "parcels": list(s.handover)}))
                    for p in s.handover:
                        truck_inv[truck].add(p)
            wait_add = waits.get(vid, 0.0)
            if wait_add > 0:
                ready += wait_add
            for p in v.ground:
                h = holder.get(p, "DEPOT")
                if not nominal_initial and not ((p in truck_inv[truck]) or h == "DEPOT"):
                    tl.custody_violations.append(f"G_CUSTODY:{p}@{v.customer} holder={h} truck={truck}")
                if p in inst.parcel_to_customer and inst.parcel_to_customer[p] != v.customer:
                    tl.custody_violations.append(f"G_WRONG_CUSTOMER:{p}@{v.customer}")
                truck_inv[truck].discard(p)
                depot_pool.discard(p)
                tl.actions.append(ActionRec("G", truck, ready, ready + phys.ground_service_s, p,
                                            info={"customer": v.customer}))
                ready += phys.ground_service_s
            for s in launches_at.get(vid, []):
                p_start = max(ready, local_avail.get((truck, s.drone), 0.0), prev_avail.get(s.sid, 0.0))
                if s.sid in swaps:
                    # 换电：司机人工动作，卡车停靠时进行，位于 P 之前，与 G/P/R/U 串行
                    tl.actions.append(ActionRec("W", truck, p_start, p_start + phys.swap_s, f"S{s.sid}",
                                                info={"drone": s.drone, "customer": v.customer}))
                    p_start += phys.swap_s
                p_end = p_start + phys.prepare_s
                for p in s.payload_ids:
                    h = holder.get(p, "DEPOT")
                    if not nominal_initial and not ((p in truck_inv[truck]) or h == "DEPOT"):
                        tl.custody_violations.append(f"P_CUSTODY:{p}@{v.customer} holder={h} truck={truck}")
                    truck_inv[truck].discard(p)
                    depot_pool.discard(p)
                tl.actions.append(ActionRec("P", truck, p_start, p_end, f"S{s.sid}",
                                            info={"drone": s.drone}))
                ready = p_end
            t_dep = ready
            for s in launches_at.get(vid, []):
                p, q, D = _launch_geometry(plan, inst, s)
                lam = min(1.0, max(0.0, s.lam))
                if s.mode == "STOP":
                    lam, D = 0.0, 0.0
                l_end = t_dep + lam * D / vt
                l_start = l_end - phys.launch_s
                p_end = next((a.end for a in tl.actions
                              if a.kind == "P" and a.ref == f"S{s.sid}"), t_dep)
                if l_start < p_end - EPS:
                    t_dep += p_end - l_start
                    l_end = t_dep + lam * D / vt
                    l_start = l_end - phys.launch_s
                    p_end = next(a.end for a in tl.actions if a.kind == "P" and a.ref == f"S{s.sid}")
                    if l_start < p_end - EPS:
                        t_dep += p_end - l_start
                        l_end = t_dep + lam * D / vt
                        l_start = l_end - phys.launch_s
                if l_start < channel_free - EPS:
                    t_dep += channel_free - l_start
                    l_end = t_dep + lam * D / vt
                    l_start = l_end - phys.launch_s
                pos = _pos_along(p, q, lam) if s.mode == "ARC" else p
                tl.launch_times[s.sid] = (l_start, l_end, pos)
                channel_free = max(channel_free, l_end)
                tl.actions.append(ActionRec("L", s.drone, l_start, l_end, f"S{s.sid}",
                                            info={"truck": truck, "pos": pos, "mode": s.mode}))
            tl.visit_dep[vid] = t_dep
            t_prev = t_dep
            pos_prev = cpos
        if route:
            last = plan.visits[route[-1]]
            cl = inst.customer(last.customer)
            arrive_depot = t_prev + _dist((cl.x, cl.y), depot) / vt
            tl.actions.append(ActionRec("DRIVE", truck, t_prev, arrive_depot, "DEPOT",
                                        info={"from": (cl.x, cl.y), "to": depot,
                                              "dist": _dist((cl.x, cl.y), depot)}))
        else:
            arrive_depot = depart_depot
        tl.truck_finish[truck] = arrive_depot


def _schedule_drones(plan: Plan, inst: Instance, phys: PhysicalConfig, state: StartState,
                     tl: Timeline, drones: list[str]) -> None:
    vd = phys.drone_speed_m_s
    depot = (inst.depot_x, inst.depot_y)
    for d in drones:
        sids = plan.drone_sorties.get(d, [])
        st = state.drone_start.get(d)
        stages: list[DroneStage] = []
        cur_pos = st.pos if st else depot
        cur_time = st.ready_time if st else 0.0
        on_truck = st.truck if st else None
        if st is not None and st.kind == "ON_TRUCK":
            stages.append(DroneStage("ON_TRUCK", max(st.ready_time, state.t0), max(st.ready_time, state.t0),
                                     truck=on_truck))
        elif st is None:
            stages.append(DroneStage("ON_TRUCK", 0.0, 0.0, truck=home_truck(d)))
            on_truck = home_truck(d)
        for sid in sids:
            s = plan.sorties[sid]
            tl.drone_ready_before[sid] = cur_time
            if not s.started:
                if on_truck is None:
                    cur_time = max(cur_time, tl.t0)
                l_start, l_end, lpos = tl.launch_times.get(sid, (cur_time, cur_time, cur_pos))
                p_act = next((a for a in tl.actions if a.kind == "P" and a.ref == f"S{sid}"), None)
                p_start = p_act.start if p_act else l_start - phys.prepare_s
                p_end = p_act.end if p_act else l_start
                ready_start = cur_time
                w_act = next((a for a in tl.actions if a.kind == "W" and a.ref == f"S{sid}"), None)
                if on_truck is not None:
                    if w_act is not None:
                        if w_act.start > ready_start + 1e-9:
                            stages.append(DroneStage("ON_TRUCK", ready_start, w_act.start, truck=on_truck))
                        stages.append(DroneStage("SWAP", w_act.start, w_act.end, truck=on_truck, sid=sid))
                        ready_start = w_act.end
                    if p_start > ready_start + 1e-9:
                        stages.append(DroneStage("ON_TRUCK", ready_start, p_start, truck=on_truck))
                    stages.append(DroneStage("P", p_start, p_end, truck=on_truck, sid=sid))
                    if l_start > p_end + 1e-9:
                        stages.append(DroneStage("READY", p_end, l_start, truck=on_truck, sid=sid))
                mass = sum(inst.parcel_mass[p] for p in s.payload_ids)
                stages.append(DroneStage("L", l_start, l_end, truck=on_truck, mass=mass, sid=sid,
                                         x0=lpos[0], y0=lpos[1], x1=lpos[0], y1=lpos[1]))
                cur_pos = lpos
                cur_time = l_end
            else:
                cur_pos = s.start_pos or cur_pos
                cur_time = s.start_time
            aboard = list(s.air) + list(s.handover)
            mass_now = sum(inst.parcel_mass[p] for p in aboard)
            resume_p = resume_done = None
            if s.started and st is not None and st.kind == "AIRBORNE" and st.service_parcel \
                    and st.service_done_s > 1e-9 and s.air and s.air[0] == st.service_parcel:
                resume_p, resume_done = st.service_parcel, st.service_done_s
            for p in s.air:
                cid = inst.parcel_to_customer[p]
                c = inst.customer(cid)
                dpos = (c.x, c.y)
                leg = _dist(cur_pos, dpos)
                t_arr = cur_time + leg / vd
                stages.append(DroneStage("CRUISE", cur_time, t_arr, mass=mass_now, parcel=p,
                                         sid=sid, dist=leg, x0=cur_pos[0], y0=cur_pos[1],
                                         x1=dpos[0], y1=dpos[1]))
                if p == resume_p:
                    # 第三轮：被截断的服务只补完剩余时长（原先整段重做，多算时间和一次服务能耗）
                    svc_end = t_arr + max(0.0, phys.air_service_s - resume_done)
                    stages.append(DroneStage("SERVICE", t_arr, svc_end, mass=mass_now, parcel=p, sid=sid,
                                             svc_done0=resume_done, resumed=True))
                    resume_p = None
                else:
                    svc_end = t_arr + phys.air_service_s
                    stages.append(DroneStage("SERVICE", t_arr, svc_end, mass=mass_now, parcel=p, sid=sid))
                mass_now -= inst.parcel_mass[p]
                cur_time = svc_end
                cur_pos = dpos
            rv = plan.visits[s.rec_vid]
            rc = inst.customer(rv.customer)
            rpos = (rc.x, rc.y)
            leg = _dist(cur_pos, rpos)
            t_arr = cur_time + leg / vd
            if leg > 1e-9:
                stages.append(DroneStage("CRUISE", cur_time, t_arr, mass=mass_now, sid=sid,
                                         dist=leg, x0=cur_pos[0], y0=cur_pos[1],
                                         x1=rpos[0], y1=rpos[1]))
            tl.drone_arrival[sid] = t_arr
            r_start, r_end = tl.rec_times.get(sid, (t_arr, t_arr + phys.recovery_s))
            if r_start > t_arr + 1e-9:
                stages.append(DroneStage("WAIT", t_arr, r_start, mass=mass_now, sid=sid, landed=s.landed))
                tl.wait_by_sortie[sid] = r_start - t_arr
            stages.append(DroneStage("R", max(r_start, t_arr), max(r_start, t_arr) + phys.recovery_s,
                                     mass=mass_now, sid=sid, landed=s.landed))
            end = max(r_start, t_arr) + phys.recovery_s
            if s.handover:
                stages.append(DroneStage("U", end, end + phys.handover_s, sid=sid))
                end += phys.handover_s
            tl.drone_available[sid] = end
            cur_time = end
            on_truck = rv.truck
            cur_pos = rpos
            stages.append(DroneStage("ON_TRUCK", cur_time, cur_time, truck=on_truck))
        final_truck = on_truck or (st.truck if st else home_truck(d))
        f = tl.truck_finish.get(final_truck, 0.0)
        if stages and stages[-1].kind == "ON_TRUCK":
            stages[-1].end = max(stages[-1].start, f)
        else:
            start = stages[-1].end if stages else 0.0
            stages.append(DroneStage("ON_TRUCK", start, max(start, f), truck=final_truck))
        tl.drone_stages[d] = stages


def _compute_distances(plan: Plan, inst: Instance, state: StartState, tl: Timeline,
                       trucks: list[str]) -> None:
    depot = (inst.depot_x, inst.depot_y)
    for truck in trucks:
        route = plan.routes.get(truck, [])
        d0 = 0.0
        if not route and state.t0 > 0 and tl.truck_finish.get(truck, 0.0) > 0:
            d0 += _dist(state.truck_start_pos.get(truck, depot), depot)
        if route:
            first = plan.visits[route[0]]
            c = inst.customer(first.customer)
            if state.t0 > 0:
                d0 += _dist(state.truck_start_pos.get(truck, depot), (c.x, c.y))
            else:
                d0 += _dist(depot, (c.x, c.y))
            for a, b in zip(route, route[1:]):
                ca = inst.customer(plan.visits[a].customer)
                cb = inst.customer(plan.visits[b].customer)
                d0 += _dist((ca.x, ca.y), (cb.x, cb.y))
            cl = inst.customer(plan.visits[route[-1]].customer)
            d0 += _dist((cl.x, cl.y), depot)
        tl.truck_distance_m[truck] = d0


# ---------------------------------------------------------------------------
# 能量
# ---------------------------------------------------------------------------
def stage_energy(stage: DroneStage, phys: PhysicalConfig) -> float:
    if stage.kind in ("ON_TRUCK", "READY", "P", "U", "DONE", "SWAP"):
        return 0.0
    if stage.kind == "L":
        return phys.hover_energy_kwh(phys.launch_s, stage.mass)
    if stage.landed and stage.kind in ("WAIT", "R"):
        return 0.0
    if stage.kind == "R":
        return phys.hover_energy_kwh(phys.recovery_s, stage.mass)
    if stage.kind == "CRUISE":
        return phys.fly_energy_kwh(stage.dist, stage.mass)
    if stage.kind in ("SERVICE", "WAIT"):
        return phys.hover_energy_kwh(stage.end - stage.start, stage.mass)
    return 0.0


def _start_energy(state: StartState, d: str, phys: PhysicalConfig) -> float:
    if state.t0 > 0 or d in state.drone_energy:
        return state.drone_energy.get(d, phys.e_cap)
    st = state.drone_start.get(d)
    return st.energy if st else phys.e_cap


def _swap_pass(tl: Timeline, plan: Plan, phys: PhysicalConfig, state: StartState,
               swaps: set[int]) -> tuple[set[int], str]:
    """换电配置：按当前时刻表逐机推演电量，在首个能量违约的航次放飞前加一次换电（惰性换电）.

    违约 = R 结束余电 < E_min 或电量 < 0。该航次已换电仍违约，或违约发生在已起飞的空中残段，
    则无法靠换电修复，返回非空信息（评价判不可行）。"""
    new = set(swaps)
    msg = ""
    for d, stages in tl.drone_stages.items():
        e = _start_energy(state, d, phys)
        for st in stages:
            if st.kind == "SWAP":
                e = phys.e_cap
                continue
            e -= stage_energy(st, phys)
            req = phys.e_min if (st.kind == "R" and not st.landed) else 0.0
            if e < req - phys.energy_tol:
                sid = st.sid
                s = plan.sorties.get(sid) if sid is not None else None
                if s is None or s.started or sid in swaps:
                    msg = f"SWAP_CANNOT_FIX:{d}@{st.start:.1f}:e={e:.6f}<{req:.6f}"
                else:
                    new.add(sid)
                break
    return new, msg


def allocate_swaps(tl: Timeline, phys: PhysicalConfig, state: StartState):
    """换电配置下的"能量分配"：沿阶段推演电量（SWAP 后恢复满电），核对备用电池数。"""
    drones = list(tl.drone_stages.keys())
    if tl.swap_msg:
        tl.energy_ok = False
        tl.energy_msg = tl.swap_msg
        tl.deficits = {}
        for d in drones:
            tl.e_return[d] = float("nan")
        return False, tl.energy_msg, {}
    refill = 0.0
    tl.swap_count_by_truck = {}
    for d in drones:
        e = _start_energy(state, d, phys)
        energies = [e]
        for st in tl.drone_stages[d]:
            if st.kind == "SWAP":
                refill += phys.e_cap - e
                e = phys.e_cap
                tl.swap_count_by_truck[st.truck] = tl.swap_count_by_truck.get(st.truck, 0) + 1
            else:
                e -= stage_energy(st, phys)
            energies.append(e)
        tl.drone_energy[d] = energies
        tl.e_return[d] = energies[-1]
    tl.swap_refill_kwh = refill
    tl.q_total = 0.0
    tl.q_by_truck = {k: 0.0 for k in state.truck_ac}
    for k, n in tl.swap_count_by_truck.items():
        if n > state.truck_ac.get(k, phys.spare_batteries) + 1e-9:
            tl.energy_ok = False
            tl.energy_msg = f"SWAP_SPARES:{k}:{n}>{state.truck_ac.get(k, phys.spare_batteries):.0f}"
            tl.deficits = {}
            return False, tl.energy_msg, {}
    ok = all(tl.e_return.get(d, 0.0) >= -phys.energy_tol for d in drones)
    tl.energy_ok = ok
    tl.energy_msg = "" if ok else "NEGATIVE_RETURN"
    return ok, tl.energy_msg, {}


def allocate_charging(tl: Timeline, phys: PhysicalConfig, state: StartState):
    """分阶段充电 LP；返回 (可行, 信息, q字典)."""
    if phys.swap_mode:
        return allocate_swaps(tl, phys, state)
    drones = list(tl.drone_stages.keys())
    charge_stages: dict[str, list[tuple[int, float, float, str]]] = {}
    for d in drones:
        lst = []
        for idx, st in enumerate(tl.drone_stages[d]):
            if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                lst.append((idx, st.start, st.end - st.start, st.truck))
        charge_stages[d] = lst
    var_index: dict[tuple[str, int], int] = {}
    vars_meta: list[tuple[str, float, str]] = []
    for d in drones:
        for j, (idx, start, dur, truck) in enumerate(charge_stages[d]):
            var_index[(d, j)] = len(vars_meta)
            vars_meta.append((truck, dur, d))
    nvar = len(vars_meta)
    if nvar == 0:
        ok, msg = _check_energy_without_charge(tl, phys, state)
        tl.energy_ok = ok
        tl.energy_msg = msg
        for d in drones:
            tl.e_return[d] = _return_energy(tl, d, phys, state)
        return ok, msg, {}
    A_rows: list[np.ndarray] = []
    b_rows: list[float] = []
    bounds = [(0.0, phys.slot_ac_kw * dur / 3600.0) for (_, dur, _) in vars_meta]
    for d in drones:
        stages = tl.drone_stages[d]
        e0 = _start_energy(state, d, phys)
        consumed = 0.0
        charge_seen = 0
        for st in stages:
            if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                j = charge_seen
                charge_seen += 1
                row = np.zeros(nvar)
                for jj in range(j + 1):
                    row[var_index[(d, jj)]] = phys.slot_efficiency
                A_rows.append(row)
                b_rows.append(phys.e_cap + consumed - e0)
            else:
                consumed += stage_energy(st, phys)
                req = phys.e_min if (st.kind == "R" and not st.landed) else 0.0
                row = np.zeros(nvar)
                for jj in range(charge_seen):
                    row[var_index[(d, jj)]] = -phys.slot_efficiency
                A_rows.append(row)
                b_rows.append(-(req + consumed - e0))
    for k in state.truck_ac:
        row = np.zeros(nvar)
        got = False
        for i, (truck, dur, d) in enumerate(vars_meta):
            if truck == k:
                row[i] = 1.0
                got = True
        if got:
            A_rows.append(row)
            b_rows.append(state.truck_ac[k])
    tl.lp_calls += 1
    res = linprog(np.ones(nvar), A_ub=np.array(A_rows), b_ub=np.array(b_rows), bounds=bounds,
                  method="highs",
                  options={"presolve": True, "disp": False, "primal_feasibility_tolerance": 1e-7,
                           "dual_feasibility_tolerance": 1e-7, "ipm_optimality_tolerance": 1e-8})
    if not res.success:
        diag = []
        tl.deficits = {}
        for d in drones:
            e = _start_energy(state, d, phys)
            need = 0.0
            worst = 0.0
            for st in tl.drone_stages[d]:
                en = stage_energy(st, phys)
                need += en
                e -= en
                req = phys.e_min if (st.kind == "R" and not st.landed) else 0.0
                worst = min(worst, e - req)
            tl.deficits[d] = max(0.0, -worst)
            diag.append(f"{d}:e0={e:.2f},need={need:.2f},worst={worst:.2f}")
        diag.append("ac=" + ",".join(f"{k}:{v:.2f}" for k, v in state.truck_ac.items()))
        tl.energy_ok = False
        tl.energy_msg = f"CHARGE_LP_{res.status}:{res.message}|" + ";".join(diag)
        for d in drones:
            tl.e_return[d] = float("nan")
        return False, tl.energy_msg, {}
    q = {f"{d}#{j}": float(res.x[var_index[(d, j)]]) for d in drones
         for j in range(len(charge_stages[d]))}
    tl.q_total = float(res.x.sum())
    tl.q_by_stage = q
    tl.q_by_truck = {k: 0.0 for k in state.truck_ac}
    for i, (truck, dur, d) in enumerate(vars_meta):
        tl.q_by_truck[truck] = tl.q_by_truck.get(truck, 0.0) + float(res.x[i])
    for d in drones:
        stages = tl.drone_stages[d]
        e0 = _start_energy(state, d, phys)
        energies = [e0]
        e = e0
        j = 0
        for st in stages:
            if st.kind in ("ON_TRUCK", "READY") and st.end - st.start > 1e-9 and st.truck:
                e += phys.slot_efficiency * q[f"{d}#{j}"]
                j += 1
            else:
                e -= stage_energy(st, phys)
            energies.append(e)
        tl.drone_energy[d] = energies
        tl.e_return[d] = energies[-1]
    ok = True
    for d in drones:
        if tl.e_return.get(d, 0.0) < -phys.energy_tol:
            ok = False
    tl.energy_ok = ok
    tl.energy_msg = "" if ok else "NEGATIVE_RETURN"
    return ok, tl.energy_msg, q


def _check_energy_without_charge(tl: Timeline, phys: PhysicalConfig, state: StartState):
    for d, stages in tl.drone_stages.items():
        e = _start_energy(state, d, phys)
        for st in stages:
            e -= stage_energy(st, phys)
            if st.kind == "R" and not st.landed and e < phys.e_min - phys.energy_tol:
                return False, f"E_MIN_VIOLATION:{d}@{st.start:.1f}"
            if e < -phys.energy_tol:
                return False, f"NEGATIVE_ENERGY:{d}@{st.start:.1f}"
    return True, ""


def _return_energy(tl: Timeline, d: str, phys: PhysicalConfig) -> float:
    stages = tl.drone_stages.get(d, [])
    return tl.drone_energy.get(d, [phys.e_cap])[-1] if d in tl.drone_energy else phys.e_cap
