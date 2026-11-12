"""插入/移除动作与代理分数（第7.5节）.

代理分数：
  Ĉ = c_km·L_T/1000 + w_s·(L_T/v_T + 50n_G + 30n_P + 30n_R + 20n_U) + c_depot·E_air_no_wait
仅用于候选排序；最终接受一律使用完整评价。

候选目录采用"稳定 ID 轮转 + 邻近展开"的保守实现：每票每次最多检查固定数量的
（放飞访问, 回收访问）组合，顺序由真实几何决定；未检出的组合由下一轮游标继续展开。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import PhysicalConfig
from .data import Instance
from .plan import Plan


@dataclass
class AirCandidate:
    kind: str                  # "NEW" | "EXTEND"
    truck: str
    launch_vid: int | None
    mode: str
    lam: float
    rec_vid: int
    sid: int | None = None
    pos: int = 0
    proxy: float = 0.0
    energy: float = 0.0
    drone: str | None = None


@dataclass
class GroundCandidate:
    truck: str
    pos: int
    join_vid: int | None
    proxy: float = 0.0


# ---------------------------------------------------------------------------
# 移除
# ---------------------------------------------------------------------------
def parcel_delivery(plan: Plan, parcel: str) -> tuple[str, int] | None:
    for v in plan.visits.values():
        if parcel in v.ground:
            return ("G", v.vid)
    for s in plan.sorties.values():
        if parcel in s.air:
            return ("AIR", s.sid)
    return None


def remove_parcel(plan: Plan, parcel: str, freed: list[str] | None = None) -> list[str]:
    """移除一票的指派；返回因依赖闭包一起被释放的包裹."""
    freed = freed if freed is not None else []
    loc = parcel_delivery(plan, parcel)
    if loc is None:
        return freed
    kind, ref = loc
    if kind == "G":
        v = plan.visits.get(ref)
        if v is not None and parcel in v.ground:
            v.ground.remove(parcel)
        freed.append(parcel)
        if v is not None:
            _maybe_remove_visit(plan, v.vid)
    else:
        s = plan.sorties.get(ref)
        if s is not None and s.started:
            return freed
        if s is not None and parcel in s.air:
            s.air.remove(parcel)
        freed.append(parcel)
        if s is not None and not s.air and not s.handover:
            plan.remove_sortie(s.sid)
    return freed


def _maybe_remove_visit(plan: Plan, vid: int) -> None:
    v = plan.visits.get(vid)
    if v is None or v.ground:
        return
    for s in plan.sorties.values():
        if s.launch_vid == vid or s.rec_vid == vid:
            return
    plan.remove_visit(vid)


def remove_sortie_closure(plan: Plan, sid: int, freed: list[str]) -> list[str]:
    s = plan.sorties.get(sid)
    if s is None:
        return freed
    freed.extend(s.air)
    freed.extend(s.handover)
    plan.remove_sortie(sid)
    return freed


# ---------------------------------------------------------------------------
# 无人机航次链
# ---------------------------------------------------------------------------
def drone_chain(plan: Plan, drone: str) -> list[tuple[int, int, int]]:
    out = []
    for sid in plan.drone_sorties.get(drone, []):
        s = plan.sorties[sid]
        li = -1
        if s.launch_vid is not None:
            v = plan.visits[s.launch_vid]
            li = plan.routes[v.truck].index(v.vid)
        rv = plan.visits[s.rec_vid]
        ri = plan.routes[rv.truck].index(rv.vid)
        out.append((sid, li, ri))
    return out


def sortie_slot_free(plan: Plan, drone: str, launch_idx: int, rec_idx: int) -> bool:
    for sid, li, ri in drone_chain(plan, drone):
        if not (rec_idx < li or launch_idx > ri):
            return False
    return True


def drone_of_truck(plan: Plan, truck: str) -> str:
    from .config import home_drones
    return home_drones(truck)[0]


def drone_carriers(plan: Plan, state=None) -> dict[str, str]:
    """每架无人机的当前实际承运车：最后航次的回收车；空中残段用其 rec；
    无航次时用快照承运车；名义阶段回退为出厂对应关系。"""
    out: dict[str, str] = {}
    from .config import all_drones, home_truck
    for d in all_drones():
        sids = plan.drone_sorties.get(d, [])
        if sids:
            last = plan.sorties[sids[-1]]
            if last.rec_vid in plan.visits:
                out[d] = plan.visits[last.rec_vid].truck
                continue
        if state is not None and d in getattr(state, "drone_carrier", {}):
            out[d] = state.drone_carrier[d]
            continue
        out[d] = home_truck(d)
    return out


def drones_on_truck(plan: Plan, truck: str, state=None) -> list[str]:
    car = drone_carriers(plan, state)
    return sorted([d for d, t in car.items() if t == truck])


# ---------------------------------------------------------------------------
# 代理分数
# ---------------------------------------------------------------------------
def air_energy(inst: Instance, phys: PhysicalConfig, p0: tuple[float, float],
               parcels: list[str], rec: tuple[float, float]) -> float:
    mass = sum(inst.parcel_mass[p] for p in parcels)
    cur = p0
    e = phys.hover_energy_kwh(phys.launch_s, mass)
    for p in parcels:
        c = inst.customer(inst.parcel_to_customer[p])
        pos = (c.x, c.y)
        e += phys.fly_energy_kwh(math.hypot(pos[0] - cur[0], pos[1] - cur[1]), mass)
        e += phys.hover_energy_kwh(phys.air_service_s, mass)
        mass -= inst.parcel_mass[p]
        cur = pos
    e += phys.fly_energy_kwh(math.hypot(rec[0] - cur[0], rec[1] - cur[1]), mass)
    e += phys.hover_energy_kwh(phys.recovery_s, mass)
    return e


def _pos(inst: Instance, plan: Plan, vid: int) -> tuple[float, float]:
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


# ---------------------------------------------------------------------------
# 地面插入候选
# ---------------------------------------------------------------------------
def allowed_truck(state, parcel: str) -> str | None:
    """恢复阶段：票的保管车唯一决定它可由哪辆车地送/装载；DEPOT 可自由分配."""
    if state is None:
        return None
    h = (getattr(state, "parcel_holder", {}) or {}).get(parcel, "DEPOT")
    if h.startswith("TRUCK:"):
        return h.split(":", 1)[1]
    if h == "DEPOT":
        return None
    return "__FIXED__"


def ground_candidates(plan: Plan, inst: Instance, phys: PhysicalConfig, parcel: str,
                      min_pos: dict[str, int] | None = None,
                      state=None) -> list[GroundCandidate]:
    cust = inst.parcel_to_customer[parcel]
    c = inst.customer(cust)
    cpos = (c.x, c.y)
    depot = (inst.depot_x, inst.depot_y)
    out: list[GroundCandidate] = []
    w = phys.wage_per_s
    allow = allowed_truck(state, parcel)
    if allow == "__FIXED__":
        return []
    for truck, route in plan.routes.items():
        if allow is not None and truck != allow:
            continue
        low = (min_pos or {}).get(truck, 0)
        joined = False
        for vid in route:
            if plan.visits[vid].customer == cust:
                out.append(GroundCandidate(truck, 0, vid, proxy=w * phys.ground_service_s))
                joined = True
                break
        for i in range(low, len(route) + 1):
            prev = depot if i == 0 else _pos(inst, plan, route[i - 1])
            nxt = depot if i == len(route) else _pos(inst, plan, route[i])
            delta = (math.hypot(prev[0] - cpos[0], prev[1] - cpos[1])
                     + math.hypot(cpos[0] - nxt[0], cpos[1] - nxt[1])
                     - math.hypot(prev[0] - nxt[0], prev[1] - nxt[1]))
            # 第二轮修复3：绕行不仅有里程费，还有司机行驶时间的工资（约占绕行成本的一半），
            # 原代理漏掉了这一项，会系统性低估地送成本、偏向"放回地面"。
            proxy = (phys.c_km * delta / 1000.0 + w * delta / phys.truck_speed_m_s
                     + w * phys.ground_service_s)
            out.append(GroundCandidate(truck, i, None, proxy=proxy))
    out.sort(key=lambda x: (x.proxy, x.truck, x.pos))
    return out


def apply_ground(plan: Plan, inst: Instance, parcel: str, cand: GroundCandidate) -> bool:
    cust = inst.parcel_to_customer[parcel]
    if cand.join_vid is not None:
        v = plan.visits.get(cand.join_vid)
        if v is None:
            return False
        v.ground.append(parcel)
        return True
    plan.add_visit(cand.truck, cust, pos=cand.pos, ground=[parcel])
    return True


# ---------------------------------------------------------------------------
# 空中插入候选
# ---------------------------------------------------------------------------
def sortie_start(inst: Instance, plan: Plan, s) -> tuple[float, float]:
    if s.launch_vid is None:
        return (inst.depot_x, inst.depot_y)
    if s.mode == "STOP":
        return _pos(inst, plan, s.launch_vid)
    v = plan.visits[s.launch_vid]
    route = plan.routes[v.truck]
    idx = route.index(v.vid)
    p = _pos(inst, plan, v.vid)
    if idx + 1 < len(route):
        q = _pos(inst, plan, route[idx + 1])
        return (p[0] + (q[0] - p[0]) * s.lam, p[1] + (q[1] - p[1]) * s.lam)
    return p


def route_times(plan: Plan, inst: Instance, phys: PhysicalConfig, truck: str):
    """估计某车路线上各访问的到达/离开时刻（相对出库，仅用于代理分，不用于可行性）."""
    route = plan.routes.get(truck, [])
    depot = (inst.depot_x, inst.depot_y)
    v = phys.truck_speed_m_s
    arr, dep = [], []
    t, pos = 0.0, depot
    n_launch: dict[int, int] = {}
    n_rec: dict[int, int] = {}
    for s in plan.sorties.values():
        if s.launch_vid is not None:
            n_launch[s.launch_vid] = n_launch.get(s.launch_vid, 0) + 1
        n_rec[s.rec_vid] = n_rec.get(s.rec_vid, 0) + 1
    for vid in route:
        c = inst.customer(plan.visits[vid].customer)
        t += math.hypot(c.x - pos[0], c.y - pos[1]) / v
        arr.append(t)
        t += (phys.ground_service_s * len(plan.visits[vid].ground)
              + phys.prepare_s * n_launch.get(vid, 0)
              + (phys.recovery_s + phys.handover_s) * n_rec.get(vid, 0))
        dep.append(t)
        pos = (c.x, c.y)
    return arr, dep


def air_time(inst: Instance, phys: PhysicalConfig, p0, parcels: list[str], rec) -> float:
    cur, t = p0, phys.launch_s
    for p in parcels:
        c = inst.customer(inst.parcel_to_customer[p])
        t += math.hypot(c.x - cur[0], c.y - cur[1]) / phys.drone_speed_m_s + phys.air_service_s
        cur = (c.x, c.y)
    t += math.hypot(rec[0] - cur[0], rec[1] - cur[1]) / phys.drone_speed_m_s
    return t


def sync_cost(phys: PhysicalConfig, t_air: float, t_truck: float, mass_kg: float = 3.0) -> float:
    """无人机飞行时间与卡车到接机点时间不同步的代价：卡车等机（工资）或无人机悬停等车（电费）."""
    if t_air >= t_truck:
        return phys.wage_per_s * (t_air - t_truck)
    return phys.cost_depot_kwh * phys.hover_power(mass_kg) * (t_truck - t_air) / 3600.0


def air_candidates(plan: Plan, inst: Instance, phys: PhysicalConfig, parcel: str,
                   max_new: int = 10, near_visits: int = 6,
                   forbid_air: set[str] | None = None,
                   state=None, min_pos: dict[str, int] | None = None) -> list[AirCandidate]:
    if forbid_air and parcel in forbid_air:
        return []
    allow = allowed_truck(state, parcel)
    if allow == "__FIXED__":
        return []
    cust = inst.parcel_to_customer[parcel]
    c = inst.customer(cust)
    cpos = (c.x, c.y)
    out: list[AirCandidate] = []
    w = phys.wage_per_s
    cdep = phys.cost_depot_kwh
    rt_cache: dict[str, tuple[list[float], list[float]]] = {}

    def _rt(truck_: str):
        if truck_ not in rt_cache:
            rt_cache[truck_] = route_times(plan, inst, phys, truck_)
        return rt_cache[truck_]

    def _t_truck(truck_: str, launch_vid_, rec_vid_) -> float | None:
        r_ = plan.routes.get(truck_, [])
        if launch_vid_ not in r_ or rec_vid_ not in r_:
            return None
        arr_, dep_ = _rt(truck_)
        return max(0.0, arr_[r_.index(rec_vid_)] - dep_[r_.index(launch_vid_)])
    # 1) 并入已有航次（只能并入该票保管车上的航次）
    for s in plan.sorties.values():
        if s.started or s.launch_vid is None:
            continue
        if allow is not None and s.truck != allow:
            continue
        m = sum(inst.parcel_mass[p] for p in s.air) + inst.parcel_mass[parcel]
        if m > phys.drone_payload_limit_kg + 1e-9:
            continue
        try:
            base = air_energy(inst, phys, sortie_start(inst, plan, s), s.air, _rec_pos(inst, plan, s))
        except KeyError:
            continue
        best = None
        for pos in range(len(s.air) + 1):
            new_air = list(s.air)
            new_air.insert(pos, parcel)
            e = air_energy(inst, phys, sortie_start(inst, plan, s), new_air, _rec_pos(inst, plan, s))
            if best is None or e < best[0]:
                best = (e, pos)
        if best is not None and best[0] <= phys.e_cap - phys.e_min:
            sync_delta = 0.0
            tt = _t_truck(s.truck or "", s.launch_vid, s.rec_vid)
            if tt is not None:
                new_air = list(s.air)
                new_air.insert(best[1], parcel)
                sp, rp = sortie_start(inst, plan, s), _rec_pos(inst, plan, s)
                sync_delta = (sync_cost(phys, air_time(inst, phys, sp, new_air, rp), tt)
                              - sync_cost(phys, air_time(inst, phys, sp, list(s.air), rp), tt))
            out.append(AirCandidate("EXTEND", s.truck or "", s.launch_vid, s.mode, s.lam, s.rec_vid,
                                    sid=s.sid, pos=best[1],
                                    proxy=cdep * (best[0] - base) + sync_delta,
                                    energy=best[0], drone=s.drone))
    # 2) 新建航次：按"回收访问离客户最近"展开
    for truck, route in plan.routes.items():
        if allow is not None and truck != allow:
            continue
        if len(route) < 1:
            continue
        cand = []
        n = len(route)
        for b in range(n):
            cand.append((b, route[b]))
        # 选择离客户最近的 near_visits 个访问作为回收锚点
        cand.sort(key=lambda x: (math.hypot(_pos(inst, plan, x[1])[0] - cpos[0],
                                            _pos(inst, plan, x[1])[1] - cpos[1]), x[1]))
        drones = drones_on_truck(plan, truck, state)
        if not drones:
            continue
        low = (min_pos or {}).get(truck, 0)
        for b, rvid in cand[:near_visits]:
            if b < low:
                continue
            for a in set(range(max(low, b - 4), b)):
                drone = next((d for d in drones if sortie_slot_free(plan, d, a, b)), None)
                if drone is None:
                    continue
                lpos = _pos(inst, plan, route[a])
                rpos = _pos(inst, plan, rvid)
                e = air_energy(inst, phys, lpos, [parcel], rpos)
                if e > phys.e_cap - phys.e_min:
                    continue
                proxy = w * (phys.prepare_s + phys.recovery_s) + cdep * e
                tt = _t_truck(truck, route[a], rvid)
                if tt is not None:
                    proxy += sync_cost(phys, air_time(inst, phys, lpos, [parcel], rpos), tt,
                                       inst.parcel_mass[parcel])
                out.append(AirCandidate("NEW", truck, route[a], "ARC", 0.5, rvid, proxy=proxy,
                                        energy=e, drone=drone))
                out.append(AirCandidate("NEW", truck, route[a], "STOP", 0.0, rvid,
                                        proxy=proxy + 1e-6, energy=e, drone=drone))
    out.sort(key=lambda x: (x.proxy, x.truck or "", x.rec_vid, x.sid or 0))
    seen = set()
    picked = []
    for cand_ in out:
        key = (cand_.truck, cand_.rec_vid, cand_.mode, cand_.sid)
        if key in seen:
            continue
        seen.add(key)
        picked.append(cand_)
        if len(picked) >= max_new:
            break
    return picked


def _rec_pos(inst: Instance, plan: Plan, s) -> tuple[float, float]:
    return _pos(inst, plan, s.rec_vid)


def apply_air(plan: Plan, inst: Instance, parcel: str, cand: AirCandidate) -> bool:
    if cand.kind == "EXTEND":
        s = plan.sorties.get(cand.sid)
        if s is None:
            return False
        s.air.insert(min(cand.pos, len(s.air)), parcel)
        return True
    if cand.rec_vid not in plan.visits:
        return False
    if cand.launch_vid is not None and cand.launch_vid not in plan.visits:
        return False
    drone = cand.drone or drone_of_truck(plan, cand.truck)
    car = drone_carriers(plan)
    if car.get(drone) != cand.truck:
        return False
    plan.add_sortie(drone, cand.truck, cand.launch_vid, cand.mode,
                    cand.lam, [parcel], cand.rec_vid)
    return True


# ---------------------------------------------------------------------------
# 修复
# ---------------------------------------------------------------------------
def repair_greedy(plan: Plan, inst: Instance, phys: PhysicalConfig, pool: list[str],
                  rng=None, max_ops: int = 200,
                  forbid_air: set[str] | None = None,
                  min_pos: dict[str, int] | None = None,
                  state=None) -> tuple[Plan, list[str]]:
    """R1：按代理增量从小到大应用；每票先算最优候选，后续插入后仅做结构复核."""
    remaining = list(pool)
    offers: dict[str, tuple[float, str, object]] = {}
    for p in remaining:
        offers[p] = _best_offer(plan, inst, phys, p, forbid_air, min_pos, state)
    applied = 0
    while offers and applied < max_ops:
        p = min(offers, key=lambda x: (offers[x][0] if offers[x] else float("inf"), x))
        offer = offers.pop(p)
        if offer is None:
            continue
        _, kind, cand = offer
        ok = apply_ground(plan, inst, p, cand) if kind == "G" else apply_air(plan, inst, p, cand)
        if ok:
            remaining.remove(p)
            applied += 1
        else:
            # 结构失效后重算一次
            offer2 = _best_offer(plan, inst, phys, p, forbid_air, min_pos, state)
            if offer2 is not None:
                _, kind2, cand2 = offer2
                ok2 = apply_ground(plan, inst, p, cand2) if kind2 == "G" else apply_air(plan, inst, p, cand2)
                if ok2:
                    remaining.remove(p)
                    applied += 1
    return plan, remaining


def _best_offer(plan: Plan, inst: Instance, phys: PhysicalConfig, p: str,
                forbid_air: set[str] | None = None,
                min_pos: dict[str, int] | None = None, state=None):
    cands: list[tuple[float, str, object]] = []
    gc = ground_candidates(plan, inst, phys, p, min_pos, state)
    if gc:
        cands.append((gc[0].proxy, "G", gc[0]))
    ac = air_candidates(plan, inst, phys, p, forbid_air=forbid_air, state=state, min_pos=min_pos)
    if ac:
        cands.append((ac[0].proxy, "A", ac[0]))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]))
    return cands[0]


def repair_regret2(plan: Plan, inst: Instance, phys: PhysicalConfig, pool: list[str],
                   rng=None, max_ops: int = 200,
                   forbid_air: set[str] | None = None,
                   min_pos: dict[str, int] | None = None,
                   state=None) -> tuple[Plan, list[str]]:
    """R2：regret-2；只有单一候选的订单优先."""
    remaining = list(pool)
    offers: dict[str, list[tuple[float, str, object]]] = {}
    for p in remaining:
        lst: list[tuple[float, str, object]] = []
        for c in ground_candidates(plan, inst, phys, p, min_pos, state):
            lst.append((c.proxy, "G", c))
        for c in air_candidates(plan, inst, phys, p, forbid_air=forbid_air, state=state,
                                min_pos=min_pos):
            lst.append((c.proxy, "A", c))
        offers[p] = sorted(lst, key=lambda x: x[0])
    applied = 0
    while offers and applied < max_ops:
        single = [(v[0][0], p) for p, v in offers.items() if len(v) == 1]
        if single:
            single.sort()
            p = single[0][1]
        else:
            scored = []
            for p, v in offers.items():
                if len(v) >= 2:
                    scored.append((-(v[1][0] - v[0][0]), v[0][0], p))
                else:
                    scored.append((0.0, float("inf"), p))
            scored.sort()
            p = scored[0][2]
        v = offers.pop(p)
        if not v:
            continue
        _, kind, cand = v[0]
        ok = apply_ground(plan, inst, p, cand) if kind == "G" else apply_air(plan, inst, p, cand)
        if ok:
            remaining.remove(p)
            applied += 1
        else:
            b = _best_offer(plan, inst, phys, p, forbid_air, min_pos, state)
            if b is not None:
                _, kind2, cand2 = b
                ok2 = apply_ground(plan, inst, p, cand2) if kind2 == "G" else apply_air(plan, inst, p, cand2)
                if ok2:
                    remaining.remove(p)
                    applied += 1
    return plan, remaining


def repair_air_first(plan: Plan, inst: Instance, phys: PhysicalConfig, pool: list[str],
                     rng=None, max_ops: int = 200,
                     forbid_air: set[str] | None = None,
                     min_pos: dict[str, int] | None = None,
                     state=None) -> tuple[Plan, list[str]]:
    """第二轮新增 R3：能空送的票优先空送（取空送代理最优），不能空送的才地送.
    接受与否仍由完整评价的真实成本决定，所以不会因此偏向任何一方；它只是让搜索更常尝试空送邻域。"""
    remaining = list(pool)
    order = []
    for p in remaining:
        ac = air_candidates(plan, inst, phys, p, forbid_air=forbid_air, state=state, min_pos=min_pos)
        gc = ground_candidates(plan, inst, phys, p, min_pos, state)
        order.append((ac[0].proxy if ac else float("inf"), p))
    order.sort()
    applied = 0
    for _, p in order:
        if applied >= max_ops:
            break
        done = False
        ac = air_candidates(plan, inst, phys, p, forbid_air=forbid_air, state=state, min_pos=min_pos)
        if ac and apply_air(plan, inst, p, ac[0]):
            done = True
        if not done:
            gc = ground_candidates(plan, inst, phys, p, min_pos, state)
            if gc and apply_ground(plan, inst, p, gc[0]):
                done = True
        if done:
            remaining.remove(p)
            applied += 1
    return plan, remaining


def repair_ground_only(plan: Plan, inst: Instance, phys: PhysicalConfig, pool: list[str],
                       min_pos: dict[str, int] | None = None,
                       state=None) -> tuple[Plan, list[str]]:
    """兜底修复：全部按当前代理最优地面位置插入（结构上总能安置）."""
    remaining = list(pool)
    for p in list(pool):
        gc = ground_candidates(plan, inst, phys, p, min_pos, state)
        if not gc:
            continue
        if apply_ground(plan, inst, p, gc[0]):
            remaining.remove(p)
    return plan, remaining


def repair_ground_append(plan: Plan, inst: Instance, phys: PhysicalConfig, pool: list[str],
                         min_pos: dict[str, int] | None = None,
                         state=None) -> tuple[Plan, list[str]]:
    """兜底修复：把包裹追加到路线末端，不推迟任何既有访问（保护在飞回收承诺）."""
    remaining = list(pool)
    depot = (inst.depot_x, inst.depot_y)
    for p in list(pool):
        cust = inst.parcel_to_customer[p]
        c = inst.customer(cust)
        cpos = (c.x, c.y)
        allow = allowed_truck(state, p)
        if allow == "__FIXED__":
            continue
        best = None
        for truck, route in plan.routes.items():
            if allow is not None and truck != allow:
                continue
            last = depot if not route else _pos(inst, plan, route[-1])
            d = (math.hypot(last[0] - cpos[0], last[1] - cpos[1])
                 + math.hypot(cpos[0] - depot[0], cpos[1] - depot[1])
                 - math.hypot(last[0] - depot[0], last[1] - depot[1]))
            if best is None or d < best[0]:
                best = (d, truck)
        plan.add_visit(best[1], cust, ground=[p])
        remaining.remove(p)
    return plan, remaining
