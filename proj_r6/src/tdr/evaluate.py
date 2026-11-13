"""统一评价入口：结构校验 + 调度 + 充电LP + 资源核验 + 真实成本."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import PhysicalConfig, home_truck
from .data import Instance
from .plan import Plan
from .schedule import StartState, Timeline, allocate_charging, schedule_plan, stage_energy

@dataclass
class Evaluation:
    status: str = "FEASIBLE"
    feasible: bool = False
    cost: float | None = None
    z: float | None = None
    timeline: Timeline | None = None
    violations: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    reason: str = ""

    def key(self) -> tuple:
        if not self.feasible:
            return (float("inf"), float("inf"))
        return (self.cost or float("inf"), self.z or float("inf"))


def is_cross_sortie(plan: Plan, s) -> bool:
    """第六轮：放飞车 ≠ 回收车 的（非空中残段）航次."""
    if s.started or s.launch_vid is None or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
        return False
    return plan.visits[s.launch_vid].truck != plan.visits[s.rec_vid].truck


def has_wait_cycle(plan: Plan) -> bool:
    """第六轮：名义跨车航次的等待成环（死锁）检测.

    事件图：A(v)到达→D(v)离开→A(下一访问)；放飞 Ls(s)：A(放飞访问)→Ls（STOP 另有 Ls→D(放飞访问)）；
    无人机可用：前一航次的回收 R(prev)→Ls(s)；回收：Ls(s)→R(s)，A(回收访问)→R(s)，R(s)→D(回收访问)；
    同一访问内先回收后放飞：R(本访问回收)→Ls(本访问放飞)。
    有环 = 互相等待，调度器的固定点迭代必然发散（时刻线性增长）。无环时调度器收敛。"""
    adj: dict[tuple, list[tuple]] = {}

    def e(u, v):
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, [])
    for t, route in plan.routes.items():
        for i, vid in enumerate(route):
            e(("A", vid), ("D", vid))
            if i + 1 < len(route):
                e(("D", vid), ("A", route[i + 1]))
    for s in plan.sorties.values():
        if s.rec_vid not in plan.visits:
            continue
        rs = ("R", s.sid)
        if s.launch_vid is not None and s.launch_vid in plan.visits and not s.started:
            ls = ("L", s.sid)
            e(("A", s.launch_vid), ls)
            if s.mode == "STOP":
                e(ls, ("D", s.launch_vid))
            e(ls, rs)
        e(("A", s.rec_vid), rs)
        e(rs, ("D", s.rec_vid))
    # 同一访问内的先后：回收(R) → 地送(G) → 准备/放飞(P/L)；故本访问的回收先于本访问的放飞
    recs_at: dict[int, list[int]] = {}
    for s in plan.sorties.values():
        if s.rec_vid in plan.visits:
            recs_at.setdefault(s.rec_vid, []).append(s.sid)
    for s in plan.sorties.values():
        if s.launch_vid is not None and s.launch_vid in plan.visits and not s.started:
            for rsid in recs_at.get(s.launch_vid, []):
                if rsid != s.sid:
                    e(("R", rsid), ("L", s.sid))
    for d, sids in plan.drone_sorties.items():
        for a, b in zip(sids, sids[1:]):
            sb = plan.sorties.get(b)
            if sb is not None and not sb.started and sb.launch_vid is not None:
                e(("R", a), ("L", b))
    color: dict[tuple, int] = {}
    for root in adj:
        if color.get(root):
            continue
        stack = [(root, iter(adj[root]))]
        color[root] = 1
        while stack:
            node, it = stack[-1]
            for nx in it:
                c = color.get(nx, 0)
                if c == 1:
                    return True
                if c == 0:
                    color[nx] = 1
                    stack.append((nx, iter(adj[nx])))
                    break
            else:
                color[node] = 2
                stack.pop()
    return False


def truck_slot_check(plan: Plan, inst: Instance, phys: PhysicalConfig, tl: Timeline,
                     state: StartState) -> list[str]:
    """每车机位连续账本：R 开始预留 → R 结束在车 → P/READY 在车 → L 结束释放 → … → 最终入库.

    第六轮：回收结束后到下一次放飞(或返库)之间，无人机仍占用回收车的机位
    （名义跨车回收后，回收车上的机数可能超过机位数）。"""
    errs: list[str] = []
    for k in [f"t{i+1}" for i in range(phys.truck_count)]:
        intervals: list[tuple[float, float, str]] = []
        for d in [f"d{i+1}" for i in range(phys.drone_count)]:
            st = state.drone_start.get(d)
            on_start = state.t0 if (st is not None and st.kind == "ON_TRUCK" and st.truck == k) else None
            for sid in plan.drone_sorties.get(d, []):
                s = plan.sorties[sid]
                rec_here = s.rec_vid in plan.visits and plan.visits[s.rec_vid].truck == k
                if s.started:
                    # 空中残段：只有当其回收车就是本车时，回收结束才在本车占位
                    on_start = None
                    if rec_here:
                        rt = tl.rec_times.get(sid)
                        if rt is not None:
                            on_start = rt[1]
                    continue
                if s.truck == k:
                    lt = tl.launch_times.get(sid)
                    if lt is not None:
                        start = on_start if on_start is not None else lt[0]
                        intervals.append((start, lt[1], f"{d}:on{sid}"))
                on_start = None
                if rec_here:
                    rt = tl.rec_times.get(sid)
                    if rt is not None:
                        on_start = rt[1]
            if on_start is not None:
                intervals.append((on_start, tl.truck_finish.get(k, on_start), f"{d}:final"))
        for s in plan.sorties.values():
            rv = plan.visits.get(s.rec_vid)
            if rv is not None and rv.truck == k:
                rt = tl.rec_times.get(s.sid)
                if rt and rt[1] > rt[0] + 1e-9:
                    intervals.append((rt[0], rt[1], f"{s.drone}:R{s.sid}"))
        events: list[tuple[float, int]] = []
        for a, b, tag in intervals:
            if b - a <= 1e-9:
                continue
            events.append((a, 1))
            events.append((b, -1))
        # 同刻先释放再占用，避免把"回收结束释放预留 + 同刻在车"误判为超容
        events.sort(key=lambda x: (x[0], x[1]))
        cur = 0
        for t, delta in events:
            cur += delta
            if cur > phys.truck_drone_slots:
                errs.append(f"SLOT_OVER:{k}@{t:.1f}={cur}")
                break
    return errs


def channel_check(plan: Plan, phys: PhysicalConfig, tl: Timeline) -> list[str]:
    errs: list[str] = []
    for k in [f"t{i+1}" for i in range(phys.truck_count)]:
        intervals: list[tuple[float, float]] = []
        for s in plan.sorties.values():
            lt = tl.launch_times.get(s.sid)
            if lt and not s.started:
                truck = s.truck
                if truck is None and s.launch_vid is not None:
                    truck = plan.visits[s.launch_vid].truck
                if truck == k:
                    intervals.append((lt[0], lt[1]))
            rt = tl.rec_times.get(s.sid)
            if rt:
                rv = plan.visits.get(s.rec_vid)
                if rv is not None and rv.truck == k:
                    intervals.append((rt[0], rt[1]))
        intervals.sort()
        for (a1, b1), (a2, b2) in zip(intervals, intervals[1:]):
            if a2 < b1 - 1e-6:
                errs.append(f"CHANNEL_OVERLAP:{k}@{a2:.1f}")
    return errs



def _structure_initial_carrier(state: StartState, plan: Plan) -> dict[str, str] | None:
    """截断后结构校验用的起始承运车.

    AIRBORNE 的 DroneStart.truck 恒为 None，旧逻辑 ``st.truck or home_truck(d)`` 会退回
    出厂车。若残段的回收访问已不在后缀里、或机体链上未开始航次排在残段前面，就会把
    后续航次（尤其是跨车后从回收车放飞的航次）误判为“放飞车与起始承运车不符”。
    优先用 state.drone_carrier；空中残段再用该残段回收车；出厂车仅作最后兜底。
    """
    if state.t0 <= 0:
        return None
    out: dict[str, str] = {}
    for d, st in state.drone_start.items():
        if st.kind == "ON_TRUCK" and st.truck:
            out[d] = st.truck
            continue
        rec_truck = None
        for sid in plan.drone_sorties.get(d, []):
            s = plan.sorties.get(sid)
            if s is not None and s.started and s.rec_vid in plan.visits:
                rec_truck = plan.visits[s.rec_vid].truck
                break
        out[d] = rec_truck or state.drone_carrier.get(d) or st.truck or home_truck(d)
    return out


def evaluate_plan(plan: Plan, inst: Instance, phys: PhysicalConfig,
                  state: StartState | None = None, H: float | None = None,
                  reason: str = "", check_structure: bool = True,
                  budget=None, allow_wait_repair: bool = True) -> Evaluation:
    from .schedule import initial_state

    state = state or initial_state(inst, phys)
    ev = Evaluation(reason=reason)
    if budget is not None and not budget.take():
        ev.status = "BUDGET_EXHAUSTED"
        return ev
    if check_structure:
        errs = plan.validate_structure(inst, phys,
                                       initial_carrier=_structure_initial_carrier(state, plan),
                                       holders=state.parcel_holder or None)
        if errs:
            ev.status = "INVALID_STRUCTURE"
            ev.violations = errs[:20]
            return ev
    # 货物完整性
    delivered = set(state.delivered)
    for v in plan.visits.values():
        delivered.update(v.ground)
    for s in plan.sorties.values():
        delivered.update(s.air)
    missing = [c.parcel_id for c in inst.customers if c.parcel_id not in delivered]
    if missing:
        ev.status = "INCOMPLETE"
        ev.violations = [f"未安排交付: {len(missing)} 票, 例如 {missing[:5]}"]
        return ev
    phys.set_active()
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()) and has_wait_cycle(plan):
        ev.status = "INFEASIBLE_RESOURCE"
        ev.violations = ["CROSS_WAIT_CYCLE"]
        return ev
    tl = schedule_plan(plan, inst, phys, state)
    if not tl.converged and any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        ev.status = "INFEASIBLE_RESOURCE"
        ev.violations = ["SCHEDULE_NOT_CONVERGED(cross-truck cycle)"]
        ev.timeline = tl
        return ev
    ok, msg, q = allocate_charging(tl, phys, state)
    waits: dict[int, float] = {}
    if not ok and allow_wait_repair and not phys.swap_mode:
        # 联合时序—充电修复：在合法客户停靠点延长等待，形成所需充电窗口
        for _ in range(8):
            add = _plan_energy_waits(tl, plan, phys, state, waits)
            if not add:
                break
            for vid, delta in add.items():
                waits[vid] = waits.get(vid, 0.0) + delta
            tl = schedule_plan(plan, inst, phys, state, waits=waits)
            ok, msg, q = allocate_charging(tl, phys, state)
            if ok:
                break
    if not ok:
        ev.status = "ENERGY_INFEASIBLE"
        ev.violations = [msg]
        ev.timeline = tl
        return ev
    if tl.custody_violations:
        ev.status = "INVALID_CUSTODY"
        ev.violations = tl.custody_violations[:20]
        ev.timeline = tl
        return ev
    viol = []
    viol += truck_slot_check(plan, inst, phys, tl, state)
    viol += channel_check(plan, phys, tl)
    # 终端：每个出飞机体最后必须在车上；返库时刻与 H
    for k, f in tl.truck_finish.items():
        if H is not None and f > H + 1e-6 and not phys.soft_h:
            viol.append(f"H_EXCEEDED:{k}@{f:.1f}>{H:.1f}")
    # 回收余电
    for d, stages in tl.drone_stages.items():
        e = tl.drone_energy.get(d, [])
        for i, st in enumerate(stages):
            if st.kind == "R" and not st.landed:
                if i + 1 < len(e) and e[i + 1] < phys.e_min - phys.energy_tol:
                    viol.append(f"E_MIN_AT_R:{d}@{st.start:.1f}")
    if viol:
        ev.status = "INFEASIBLE_RESOURCE"
        ev.violations = viol[:20]
        ev.timeline = tl
        return ev
    # 成本
    D = state.prefix_distance_m + sum(tl.truck_distance_m.values())
    Qac = state.prefix_ac_kwh + tl.q_total
    sumF = sum(tl.truck_finish.values())
    depot_refill = sum(phys.e_cap - tl.e_return.get(d, phys.e_cap)
                       for d in [f"d{i+1}" for i in range(phys.drone_count)])
    # 换电配置：已换下电池的待补电量(此前各段 + 本段)也由仓库补电
    depot_refill += state.prefix_refill_kwh + tl.swap_refill_kwh
    c_km = phys.c_km * D / 1000.0
    c_driver = phys.wage_per_s * sumF
    overtime_s = (sum(max(0.0, f - H) for f in tl.truck_finish.values())
                  if (phys.soft_h and H is not None) else 0.0)
    c_overtime = phys.wage_per_s * (phys.overtime_mult - 1.0) * overtime_s
    Qnet = phys.slot_efficiency * Qac
    c_veh = phys.cost_vehicle_kwh * Qnet
    c_dep = phys.cost_depot_kwh * depot_refill
    ev.cost_breakdown = {
        "truck_km": D / 1000.0, "c_km": c_km, "driver_s": sumF, "c_driver": c_driver,
        "ac_kwh": Qac, "net_kwh": Qnet, "c_vehicle": c_veh,
        "depot_refill_kwh": depot_refill, "c_depot": c_dep,
        "swaps": float(sum(tl.swap_count_by_truck.values())),
    }
    ev.cost = c_km + c_driver + c_veh + c_dep + c_overtime
    ev.cost_breakdown["overtime_s"] = overtime_s
    ev.cost_breakdown["c_overtime"] = c_overtime
    # z：实际出库机体最晚随车入库时刻
    dispatched = set(state.dispatched) if state.dispatched else set()
    for s in plan.sorties.values():
        dispatched.add(s.drone)
    tret = []
    for d in dispatched:
        carrier = final_carrier(plan, d, state, phys)
        tret.append(tl.truck_finish.get(carrier, 0.0))
    ev.z = max(tret) if tret else 0.0
    ev.feasible = True
    ev.status = "FEASIBLE"
    ev.timeline = tl
    ev.counts = {"drones_dispatched": len(dispatched), "truck_finish": dict(tl.truck_finish),
                 "lp_calls": tl.lp_calls}
    return ev


def final_carrier(plan: Plan, drone: str, state: StartState, phys: PhysicalConfig) -> str:
    sids = plan.drone_sorties.get(drone, [])
    if sids:
        return plan.visits[plan.sorties[sids[-1]].rec_vid].truck
    if drone in state.drone_carrier:
        return state.drone_carrier[drone]
    st = state.drone_start.get(drone)
    if st is not None and st.truck:
        return st.truck
    return home_truck(drone)



def _plan_energy_waits(tl: Timeline, plan: Plan, phys: PhysicalConfig, state: StartState,
                       waits: dict[int, float]) -> dict[int, float]:
    """为能量缺口选择合法的停靠等待：在缺口航次之前的承运车停靠访问上延长等待."""
    add: dict[int, float] = {}
    for d, deficit in (tl.deficits or {}).items():
        if deficit <= 1e-9:
            continue
        stages = tl.drone_stages.get(d, [])
        # 找到出现缺口的位置：第一处 R 余电不足或负电量的阶段
        # 注意：LP 失败时 tl.drone_energy 为空，必须用快照余电重算
        bad_idx = None
        e = state.drone_energy.get(d, phys.e_cap)
        for i, st in enumerate(stages):
            e -= stage_energy(st, phys)
            req = phys.e_min if (st.kind == "R" and not st.landed) else 0.0
            if e - req < -phys.energy_tol:
                bad_idx = i
                break
        if bad_idx is None:
            bad_idx = len(stages) - 1
        # 在缺口之前的所有充电阶段中，选最早可延长的停靠（越早充电，越能救后续航段）
        best = None
        for i in range(0, bad_idx):
            st = stages[i]
            if st.kind in ("ON_TRUCK", "READY") and st.truck:
                route = plan.routes.get(st.truck, [])
                vids = [(tl.visit_dep.get(vid, 0.0), vid) for vid in route
                        if tl.visit_dep.get(vid, 0.0) >= st.end - 1e-6]
                if vids:
                    dep, vid = min(vids)
                    if best is None or dep < best[2]:
                        best = (vid, dep - st.end, dep)
        if best is None:
            continue
        vid = best[0]
        need_s = deficit * 3600.0 / (phys.slot_efficiency * phys.slot_ac_kw)
        # 规范 fixed_wait_cap_s=null：不设固定等待上限（有限电量、真实到场、后续任务与 H 共同约束）；
        # 旧版 3600 s 上限只作为 energy_wait_cap_s 的敏感性选项保留
        cap = phys.energy_wait_cap_s
        room = float("inf") if cap is None else max(0.0, cap - waits.get(vid, 0.0))
        delta = min(need_s + 1.0, room)
        if delta > 1e-6:
            add[vid] = delta
    return add
