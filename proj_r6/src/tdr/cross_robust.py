"""名义跨车航次的按条稳健性检查与修复。

只作用于 X 的名义方案。S 没有跨车航次，修复不会改它。
一条航次不合格就只改这一条，不把整份名义换成 S。

四条检查都读最终时刻表：

- 回收结束余电 ≥ E_min + 0.05·E_cap（light 配置下 0.075 kWh）
- 这笔余电还要够再空载悬停 slack 秒，吸收失败带来的会合推迟
- 客机落地后直到该车收工，在车机体数 ≤ 机位数 − 1
- 接机车路线上的客户留在卡车上，不进这条跨车航次
"""
from __future__ import annotations

from .config import PhysicalConfig
from .data import Instance
from .evaluate import evaluate_plan, has_wait_cycle, is_cross_sortie
from .plan import Plan
from .schedule import Timeline, initial_state


def reserve_kwh(phys: PhysicalConfig) -> float:
    """5% 裕度：E_min + 0.05·E_cap。"""
    return phys.e_min + 0.05 * phys.e_cap


def slack_floor_kwh(phys: PhysicalConfig, slack_s: float) -> float:
    """回收结束电量至少还能再空载悬停 slack 秒，并且仍不低于 E_min。"""
    if slack_s <= 0:
        return phys.e_min
    return phys.e_min + phys.hover_energy_kwh(slack_s, 0.0)


def recovery_energy(tl: Timeline, drone: str, sid: int) -> float | None:
    """回收结束电量。下标与 _cross_energy_ok 相同。"""
    stages = tl.drone_stages.get(drone, [])
    energies = tl.drone_energy.get(drone, [])
    for i, st in enumerate(stages):
        if st.kind == "R" and not st.landed and st.sid == sid and i + 1 < len(energies):
            return float(energies[i + 1])
    return None


def _intervals_on(plan: Plan, phys: PhysicalConfig, tl: Timeline, truck: str) -> list[tuple[float, float]]:
    """一辆车上的在车区间，构造和 truck_slot_check 一致。名义初态机体在出厂车。"""
    intervals: list[tuple[float, float]] = []
    for i in range(phys.drone_count):
        did = f"d{i + 1}"
        on_start = 0.0 if phys.home_truck(did) == truck else None
        for sid in plan.drone_sorties.get(did, []):
            s = plan.sorties[sid]
            rec_here = s.rec_vid in plan.visits and plan.visits[s.rec_vid].truck == truck
            if s.started:
                on_start = None
                if rec_here:
                    rt = tl.rec_times.get(sid)
                    if rt is not None:
                        on_start = rt[1]
                continue
            if s.truck == truck:
                lt = tl.launch_times.get(sid)
                if lt is not None:
                    start = on_start if on_start is not None else lt[0]
                    intervals.append((start, lt[1]))
            on_start = None
            if rec_here:
                rt = tl.rec_times.get(sid)
                if rt is not None:
                    on_start = rt[1]
        if on_start is not None:
            intervals.append((on_start, tl.truck_finish.get(truck, on_start)))
    for s in plan.sorties.values():
        rv = plan.visits.get(s.rec_vid)
        if rv is not None and rv.truck == truck:
            rt = tl.rec_times.get(s.sid)
            if rt and rt[1] > rt[0] + 1e-9:
                intervals.append((rt[0], rt[1]))
    return intervals


def max_occupancy(plan: Plan, phys: PhysicalConfig, tl: Timeline, truck: str,
                  t0: float, t1: float) -> int:
    """[t0, t1] 上同时在车的机体数。同刻先释放再占用。"""
    events: list[tuple[float, int]] = []
    for a, b in _intervals_on(plan, phys, tl, truck):
        if b - a <= 1e-9:
            continue
        if b < t0 - 1e-9 or a > t1 + 1e-9:
            continue
        events.append((max(a, t0), 1))
        events.append((min(b, t1), -1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = 0
    peak = 0
    for _, delta in events:
        cur += delta
        if cur > peak:
            peak = cur
    return peak


def _customers_on(plan: Plan, truck: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for vid in plan.routes.get(truck, []):
        v = plan.visits[vid]
        out.setdefault(v.customer, vid)
    return out


def cross_robust_violations(plan: Plan, inst: Instance, phys: PhysicalConfig, tl: Timeline,
                            slack_s: float) -> dict[int, list[str]]:
    """每条不合格的跨车航次 → 原因标签。同车航次不查。"""
    need_margin = reserve_kwh(phys)
    need_slack = slack_floor_kwh(phys, slack_s)
    out: dict[int, list[str]] = {}
    for s in plan.sorties.values():
        if not is_cross_sortie(plan, s):
            continue
        tags: list[str] = []
        rec = plan.visits[s.rec_vid]
        owned = _customers_on(plan, rec.truck)
        for p in s.air:
            cust = inst.parcel_to_customer.get(p)
            if cust in owned:
                tags.append(f"GROUND:{p}@{rec.truck}")
        e = recovery_energy(tl, s.drone, s.sid)
        if e is None:
            tags.append("NO_RECOVERY_ENERGY")
        else:
            if e < need_margin - phys.energy_tol:
                tags.append(f"MARGIN:{e:.6f}<{need_margin:.6f}")
            if e < need_slack - phys.energy_tol:
                tags.append(f"SLACK:{e:.6f}<{need_slack:.6f}")
        rt = tl.rec_times.get(s.sid)
        if rt is None:
            tags.append("NO_REC_TIME")
        else:
            t_end = tl.truck_finish.get(rec.truck, rt[1])
            peak = max_occupancy(plan, phys, tl, rec.truck, rt[1], t_end)
            if peak >= phys.truck_drone_slots:
                tags.append(f"SLOT:{rec.truck}:{peak}>={phys.truck_drone_slots}")
        if tags:
            out[s.sid] = tags
    return out


def strip_receiver_parcels(plan: Plan, inst: Instance, sid: int) -> int:
    """把接机车自己的客户从这条航次拿回该车的访问。返回挪走的票数。"""
    s = plan.sorties.get(sid)
    if s is None or s.rec_vid not in plan.visits:
        return 0
    owned = _customers_on(plan, plan.visits[s.rec_vid].truck)
    kept: list[str] = []
    moved = 0
    for p in list(s.air):
        cust = inst.parcel_to_customer.get(p)
        vid = owned.get(cust) if cust else None
        if vid is None:
            kept.append(p)
            continue
        ground = plan.visits[vid].ground
        if p not in ground:
            ground.append(p)
        moved += 1
    s.air = kept
    return moved


def _next_launch_matches(plan: Plan, sid: int, truck: str) -> bool:
    s = plan.sorties[sid]
    chain = plan.drone_sorties.get(s.drone, [])
    idx = chain.index(sid)
    if idx + 1 >= len(chain):
        return True
    nxt = plan.sorties[chain[idx + 1]]
    if nxt.launch_vid not in plan.visits:
        return False
    return plan.visits[nxt.launch_vid].truck == truck


def retarget_same_truck(plan: Plan, inst: Instance, phys: PhysicalConfig, sid: int,
                        slack_s: float) -> bool:
    """把这一条的回收点改回放飞车路线上更晚的访问。改完必须可行，且不再是跨车。"""
    s = plan.sorties.get(sid)
    if s is None or s.launch_vid not in plan.visits:
        return False
    launch = plan.visits[s.launch_vid].truck
    route = plan.routes.get(launch, [])
    if s.launch_vid not in route:
        return False
    if not _next_launch_matches(plan, sid, launch):
        return False
    later = route[route.index(s.launch_vid) + 1:]
    if not later:
        return False
    old_rec, old_truck = s.rec_vid, s.truck
    best: tuple[float, int] | None = None
    state = initial_state(inst, phys)
    for vid in later:
        s.rec_vid = vid
        s.truck = launch
        if has_wait_cycle(plan):
            continue
        ev = evaluate_plan(plan, inst, phys, state, None, "UNCROSS")
        if not ev.feasible or ev.timeline is None:
            continue
        if is_cross_sortie(plan, s):
            continue
        if sid in cross_robust_violations(plan, inst, phys, ev.timeline, slack_s):
            continue
        cost = ev.cost if ev.cost is not None else float("inf")
        if best is None or cost < best[0]:
            best = (cost, vid)
    if best is None:
        s.rec_vid, s.truck = old_rec, old_truck
        return False
    s.rec_vid = best[1]
    s.truck = launch
    return True


def dissolve_sortie(plan: Plan, inst: Instance, sid: int) -> None:
    """拆掉这一条：票回到已有访问，没有访问就加在放飞车末尾。"""
    s = plan.sorties.get(sid)
    if s is None:
        return
    launch = None
    if s.launch_vid in plan.visits:
        launch = plan.visits[s.launch_vid].truck
    elif s.truck:
        launch = s.truck
    for p in list(s.air):
        cust = inst.parcel_to_customer[p]
        placed = None
        for v in plan.visits.values():
            if v.customer != cust:
                continue
            if launch is not None and v.truck == launch:
                placed = v
                break
            if placed is None:
                placed = v
        if placed is None and launch is not None:
            placed = plan.add_visit(launch, cust, ground=[p])
        elif placed is not None and p not in placed.ground:
            placed.ground.append(p)
    plan.remove_sortie(sid)


def repair_nominal_cross(plan: Plan, inst: Instance, phys: PhysicalConfig,
                         slack_s: float) -> tuple[Plan, list[str]]:
    """按航次修到没有不合格的跨车，或者跨车被改回同车 / 拆成地面。"""
    plan = plan.clone()
    actions: list[str] = []
    state = initial_state(inst, phys)
    guard = len(plan.sorties) + 4
    for _ in range(max(1, guard)):
        cross_ids = [s.sid for s in plan.sorties.values() if is_cross_sortie(plan, s)]
        ev = evaluate_plan(plan, inst, phys, state, None, "CROSS_REPAIR")
        if ev.feasible and ev.timeline is not None:
            viol = cross_robust_violations(plan, inst, phys, ev.timeline, slack_s)
            if not viol:
                break
            sid = sorted(viol)[0]
            tags = viol[sid]
        else:
            if not cross_ids:
                actions.append("infeasible_without_cross")
                break
            sid = sorted(cross_ids)[0]
            tags = ["INFEASIBLE"]
        if any(t.startswith("GROUND") for t in tags):
            moved = strip_receiver_parcels(plan, inst, sid)
            actions.append(f"strip:{sid}:{moved}")
            s = plan.sorties.get(sid)
            if s is not None and not s.air:
                plan.remove_sortie(sid)
                actions.append(f"remove_empty:{sid}")
            elif moved == 0:
                if retarget_same_truck(plan, inst, phys, sid, slack_s):
                    actions.append(f"uncross:{sid}")
                else:
                    dissolve_sortie(plan, inst, sid)
                    actions.append(f"dissolve:{sid}")
            continue
        if retarget_same_truck(plan, inst, phys, sid, slack_s):
            actions.append(f"uncross:{sid}")
            continue
        dissolve_sortie(plan, inst, sid)
        actions.append(f"dissolve:{sid}")
    ev = evaluate_plan(plan, inst, phys, state, None, "CROSS_REPAIR")
    if ev.feasible and ev.timeline is not None:
        left = cross_robust_violations(plan, inst, phys, ev.timeline, slack_s)
        for sid in sorted(left):
            dissolve_sortie(plan, inst, sid)
            actions.append(f"dissolve:{sid}")
    return plan, actions
