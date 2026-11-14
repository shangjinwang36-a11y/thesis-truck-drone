"""第 9 轮：给接机车插入会合访问，并给 S 一个同车版本。

名义跨车以前只能落在对方路线上已经存在的客户。恢复阶段却可以插入支援访问。
失败后用得上的会合点，失败前进不了计划。这里在评价之前插入一个空地送的会合访问：

- X：插在另一辆车上，回收点改到这个新访问，航次变成跨车。
- S：只插在放飞车上、放飞访问之后，回收点仍在同一辆车，不会产生跨车。

第 10 轮在 X 上另加一条几何：放飞点改到更靠近首票的同车访问，回程改到接机车弧上更近的客户。
整段仍然超过电量时，只飞能量允许的前缀，剩下的票放回地面。电池、0.075 kWh 和 90 秒都不改。
S 不读这个开关。

会合客户不能是这条航次正在空送的客户，否则稳健检查会把那票改回地面。
每次调用最多评价 cross_n 个候选，计入同一份名义预算。
"""
from __future__ import annotations

import math

from .moves import air_energy, sortie_start


def _funnel(stats, tag: str, cross: bool = False) -> None:
    if stats is None:
        return
    stats.aud("FUNNEL_SUPPORT", tag)
    if cross:
        stats.aud("FUNNEL_CROSS", tag)


def _customers_on(plan, truck: str) -> set[str]:
    return {plan.visits[vid].customer for vid in plan.routes.get(truck, [])}


def _min_detour(plan, inst, truck: str, customer: str, min_pos: int) -> tuple[float, int] | None:
    route = plan.routes.get(truck, [])
    if min_pos > len(route):
        return None
    depot = (inst.depot_x, inst.depot_y)
    c = inst.customer(customer)
    cpos = (c.x, c.y)
    best = None
    for i in range(min_pos, len(route) + 1):
        prev = depot if i == 0 else _pos(inst, plan, route[i - 1])
        nxt = depot if i == len(route) else _pos(inst, plan, route[i])
        det = (math.hypot(prev[0] - cpos[0], prev[1] - cpos[1])
               + math.hypot(cpos[0] - nxt[0], cpos[1] - nxt[1])
               - math.hypot(prev[0] - nxt[0], prev[1] - nxt[1]))
        if best is None or det < best[0]:
            best = (det, i)
    return best


def _pos(inst, plan, vid: int) -> tuple[float, float]:
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


def _tails(plan):
    for sids in plan.drone_sorties.values():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or not s.air or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        if plan.visits[s.launch_vid].truck != plan.visits[s.rec_vid].truck:
            continue
        yield s


def _segment_distance(point, start, end) -> tuple[float, float]:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length < 1e-12:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def _route_arcs(plan, inst, truck: str):
    route = plan.routes.get(truck, [])
    depot = (inst.depot_x, inst.depot_y)
    points = [depot] + [_pos(inst, plan, vid) for vid in route] + [depot]
    vids = [None] + list(route) + [None]
    return [(points[i], points[i + 1], vids[i], vids[i + 1]) for i in range(len(points) - 1)]


def rendezvous_candidates(plan, inst, truck: str, target, air_customers: set[str],
                          n_arcs: int = 4, cap: int = 10) -> list[str]:
    """目标客户附近、接机车 2–4 条最近弧上的合法停靠客户。最多 10 个，不生成弧外的任意坐标。"""
    arcs = _route_arcs(plan, inst, truck)
    ranked = []
    for arc in arcs:
        dist, _ = _segment_distance(target, arc[0], arc[1])
        ranked.append((dist, arc))
    ranked.sort(key=lambda item: item[0])
    take = ranked[:max(2, min(n_arcs, len(ranked)))] if len(ranked) >= 2 else ranked
    chosen: list[str] = []

    def add(customer: str | None) -> None:
        if not customer or customer in air_customers or customer in chosen:
            return
        if len(chosen) >= cap:
            return
        chosen.append(customer)

    for _, arc in take:
        for vid in (arc[2], arc[3]):
            if vid is not None:
                add(plan.visits[vid].customer)
        near = []
        for cust in inst.customers:
            if cust.customer_id in air_customers:
                continue
            dist, t = _segment_distance((cust.x, cust.y), arc[0], arc[1])
            if 0.05 < t < 0.95:
                near.append((dist, cust.customer_id))
        near.sort()
        for _, customer in near[:2]:
            add(customer)
    return chosen


_SLACK_EDGES = (-0.40, -0.30, -0.20, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.20, 0.40)


def _slack_bin(slack: float) -> str:
    """区间标签。左端包含。正数是还能飞的余量，负数是超了多少。"""
    prev = None
    for edge in _SLACK_EDGES:
        if slack < edge:
            if prev is None:
                return f"<{edge:.2f}"
            return f"{prev:.2f}:{edge:.2f}"
        prev = edge
    return f">={_SLACK_EDGES[-1]:.2f}"


def _note_slack(stats, energy: float, limit: float) -> None:
    """记下回程电量离上限还差多少。只加计数，不改变接受与否。"""
    if stats is None:
        return
    slack = float(limit) - float(energy)
    stats.aud("ENERGY_SLACK", "n")
    stats.aud("ENERGY_SLACK", _slack_bin(slack))
    if slack < -1e-9:
        stats.aud("ENERGY_SLACK", "fail")


def energy_feasible_rendezvous(plan, inst, phys, sortie, sp, limit: float, stats, cap: int = 10) -> dict[str, list[str]]:
    """沿接机车全部弧由近到远，只留下整段飞得到的客户。电量上限仍是 e_cap − e_min。"""
    air_customers = {inst.parcel_to_customer[p] for p in sortie.air if p in inst.parcel_to_customer}
    end = inst.customer(inst.parcel_to_customer[sortie.air[-1]])
    target = (end.x, end.y)
    launch = plan.visits[sortie.launch_vid].truck
    held: list[tuple[float, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for truck, route in plan.routes.items():
        if truck == launch or not route:
            continue
        arcs = _route_arcs(plan, inst, truck)
        ranked = []
        for arc in arcs:
            dist, _ = _segment_distance(target, arc[0], arc[1])
            ranked.append((dist, arc))
        ranked.sort(key=lambda item: item[0])
        for _, arc in ranked:
            customers: list[str] = []
            for vid in (arc[2], arc[3]):
                if vid is not None:
                    customers.append(plan.visits[vid].customer)
            near = []
            for cust in inst.customers:
                if cust.customer_id in air_customers:
                    continue
                dist, t = _segment_distance((cust.x, cust.y), arc[0], arc[1])
                if 0.05 < t < 0.95:
                    near.append((dist, cust.customer_id))
            near.sort()
            for _, customer in near[:2]:
                customers.append(customer)
            for customer in customers:
                key = (truck, customer)
                if not customer or customer in air_customers or key in seen:
                    continue
                seen.add(key)
                c = inst.customer(customer)
                try:
                    energy = air_energy(inst, phys, sp, list(sortie.air), (c.x, c.y))
                except KeyError:
                    continue
                _note_slack(stats, energy, limit)
                if energy <= limit + 1e-12:
                    held.append((energy, truck, customer))
    held.sort()
    out: dict[str, list[str]] = {}
    n = 0
    for _, truck, customer in held:
        bucket = out.setdefault(truck, [])
        if customer in bucket:
            continue
        bucket.append(customer)
        n += 1
        if n >= cap:
            break
    return out


def _window(route: list[int], vid: int) -> list[int]:
    if vid not in route:
        return [vid]
    i = route.index(vid)
    lo = max(0, i - 1)
    hi = min(len(route), lo + 4)
    lo = max(0, hi - 4)
    if hi - lo < 2 and len(route) >= 2:
        lo = max(0, i - 1)
        hi = min(len(route), i + 1)
    return route[lo:hi]


def joint_near_seeds(plan, inst, allow_cross: bool) -> list[str]:
    """X 在两辆最近的车各取会合点周围 2–4 站；S 只在同一辆车上取相邻的 2–4 站。"""
    best = None
    vids: set[int] = set()
    if allow_cross:
        rows = []
        for truck, route in plan.routes.items():
            for vid in route:
                rows.append((truck, vid, _pos(inst, plan, vid)))
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a[0] == b[0]:
                    continue
                dist = math.hypot(a[2][0] - b[2][0], a[2][1] - b[2][1])
                if best is None or dist < best[0]:
                    best = (dist, a[1], b[1])
        if best is None:
            return []
        vids = set()
        for vid in (best[1], best[2]):
            truck = plan.visits[vid].truck
            vids.update(_window(plan.routes.get(truck, []), vid))
    else:
        for truck, route in plan.routes.items():
            for i in range(len(route) - 1):
                a, b = _pos(inst, plan, route[i]), _pos(inst, plan, route[i + 1])
                dist = math.hypot(a[0] - b[0], a[1] - b[1])
                if best is None or dist < best[0]:
                    best = (dist, route[i], route[i + 1])
        if best is None:
            return []
        truck = plan.visits[best[1]].truck
        vids = set(_window(plan.routes.get(truck, []), best[1]))
        vids.update(_window(plan.routes.get(truck, []), best[2]))
    seeds: list[str] = []
    for vid in vids:
        seeds.extend(plan.visits[vid].ground)
        for s in plan.sorties.values():
            if s.started:
                continue
            if s.launch_vid == vid or s.rec_vid == vid:
                seeds.extend(s.air)
    out: list[str] = []
    for p in seeds:
        if p not in out:
            out.append(p)
    return out


def _launch_choices(plan, inst, sortie) -> list[int]:
    """同车、且不早于上一航次回收的放飞访问。优先靠近第一票，最多 3 个，始终保留当前放飞点。"""
    vid0 = sortie.launch_vid
    if vid0 not in plan.visits:
        return []
    truck = plan.visits[vid0].truck
    route = plan.routes.get(truck, [])
    if vid0 not in route:
        return [vid0]
    low = 0
    chain = plan.drone_sorties.get(sortie.drone, [])
    if sortie.sid in chain:
        k = chain.index(sortie.sid)
        if k > 0:
            prev = plan.sorties[chain[k - 1]]
            pv = plan.visits.get(prev.rec_vid)
            if pv is None or pv.truck != truck or prev.rec_vid not in route:
                return [vid0]
            low = route.index(prev.rec_vid)
            if route.index(vid0) < low:
                return [vid0]
    first = inst.customer(inst.parcel_to_customer[sortie.air[0]])
    target = (first.x, first.y)
    ranked = []
    for i in range(low, len(route)):
        vid = route[i]
        pos = _pos(inst, plan, vid)
        ranked.append((math.hypot(pos[0] - target[0], pos[1] - target[1]), vid))
    ranked.sort()
    chosen: list[int] = []
    for _, vid in ranked:
        if vid not in chosen:
            chosen.append(vid)
        if len(chosen) >= 3:
            break
    if vid0 not in chosen:
        chosen.append(vid0)
    return chosen


def _covered(plan) -> list[str]:
    got = [p for v in plan.visits.values() for p in v.ground]
    for sortie in plan.sorties.values():
        got.extend(sortie.air)
        got.extend(sortie.handover)
    return sorted(got)


def _suffix_floor(plan, launch_vid: int) -> int:
    """新访问插在放飞弧的下一站之后，避免改掉 ARC 插值的起点。"""
    visit = plan.visits.get(launch_vid)
    if visit is None:
        return 0
    route = plan.routes.get(visit.truck, [])
    if launch_vid not in route:
        return 0
    return min(len(route), route.index(launch_vid) + 2)


def _place_suffix(plan, inst, launch_truck: str, launch_vid: int, rec_vid: int, parcels: list[str]) -> bool:
    """拆下来的票回到地面。接机车上、回收点之后已有的客户优先，否则放回放飞车。"""
    if not parcels:
        return True
    rec = plan.visits.get(rec_vid)
    if rec is None:
        return False
    rec_route = plan.routes.get(rec.truck, [])
    rec_i = rec_route.index(rec_vid) if rec_vid in rec_route else 0
    floor = _suffix_floor(plan, launch_vid)
    for parcel in parcels:
        cust = inst.parcel_to_customer[parcel]
        placed = False
        for i, vid in enumerate(rec_route):
            if i >= rec_i and plan.visits[vid].customer == cust:
                if parcel not in plan.visits[vid].ground:
                    plan.visits[vid].ground.append(parcel)
                placed = True
                break
        if placed:
            continue
        route = plan.routes.get(launch_truck, [])
        for vid in route:
            if plan.visits[vid].customer == cust and parcel not in plan.visits[vid].ground:
                plan.visits[vid].ground.append(parcel)
                placed = True
                break
        if placed:
            continue
        det = _min_detour(plan, inst, launch_truck, cust, floor)
        if det is None:
            return False
        plan.add_visit(launch_truck, cust, pos=det[1], ground=[parcel])
    return True


def _apply_short_return(plan, inst, phys, sid: int, launch_vid: int, prefix: list[str],
                        suffix: list[str], truck: str, customer: str):
    """把一条同车航次改成更短回程的跨车航次。电量仍按 e_cap − e_min，不放宽电池。"""
    from .evaluate import has_wait_cycle
    before = _covered(plan)
    cand = plan.clone()
    so = cand.sorties[sid]
    launch_truck = so.truck
    old = so.rec_vid
    route = cand.routes.get(truck, [])
    existing = next((vid for vid in route if cand.visits[vid].customer == customer), None)
    if existing is not None:
        so.rec_vid = existing
    else:
        spot = _min_detour(cand, inst, truck, customer, 0)
        if spot is None:
            return None
        visit = cand.add_visit(truck, customer, pos=spot[1], ground=[])
        so.rec_vid = visit.vid
    so.launch_vid = launch_vid
    so.air = list(prefix)
    if not _place_suffix(cand, inst, launch_truck, launch_vid, so.rec_vid, suffix):
        return None
    ov = cand.visits.get(old)
    if ov is not None and not ov.ground and not any(
            o.sid != sid and (o.launch_vid == old or o.rec_vid == old) for o in cand.sorties.values()):
        cand.remove_visit(old)
    if so.rec_vid not in cand.visits or has_wait_cycle(cand):
        return None
    if _covered(cand) != before:
        return None
    if any(inst.parcel_to_customer[p] == cand.visits[so.rec_vid].customer for p in so.air):
        return None
    try:
        energy = air_energy(inst, phys, sortie_start(inst, cand, so), list(so.air),
                            _pos(inst, cand, so.rec_vid))
    except KeyError:
        return None
    if energy > phys.e_cap - phys.e_min + phys.energy_tol:
        return None
    return cand


def _short_return_plans(plan, ctx, n: int, tried: set, skip_sids: set | None = None):
    """X 专用。回程更短、放飞点更近，或把飞不动的后段拆回地面。

    skip_sids 里的航次已经有一条能量可行的整段会合，这里不再改它。
    """
    inst, phys = ctx.inst, ctx.phys
    stats = getattr(ctx, "live_stats", None)
    specs = []
    limit = phys.e_cap - phys.e_min + phys.energy_tol
    skip = skip_sids or set()
    for sortie in _tails(plan):
        if sortie.sid in skip:
            continue
        launch_truck = plan.visits[sortie.launch_vid].truck
        launches = _launch_choices(plan, inst, sortie)
        found_k = None
        held = []
        for k in range(len(sortie.air), 0, -1):
            prefix = list(sortie.air[:k])
            suffix = list(sortie.air[k:])
            end = inst.customer(inst.parcel_to_customer[prefix[-1]])
            endpos = (end.x, end.y)
            air_customers = {inst.parcel_to_customer[p] for p in prefix}
            for truck in plan.routes:
                if truck == launch_truck:
                    continue
                near = rendezvous_candidates(plan, inst, truck, endpos, air_customers)
                near.sort(key=lambda cid: math.hypot(inst.customer(cid).x - endpos[0],
                                                      inst.customer(cid).y - endpos[1]))
                for customer in near[:4]:
                    rec = inst.customer(customer)
                    ret = math.hypot(rec.x - endpos[0], rec.y - endpos[1])
                    for launch_vid in launches:
                        key = (sortie.sid, truck, customer, launch_vid, k)
                        if key in tried:
                            continue
                        ghost = sortie.clone()
                        ghost.launch_vid = launch_vid
                        try:
                            energy = air_energy(inst, phys, sortie_start(inst, plan, ghost),
                                                prefix, (rec.x, rec.y))
                        except KeyError:
                            _funnel(stats, "generated", True)
                            _funnel(stats, "energy", True)
                            continue
                        _funnel(stats, "generated", True)
                        _note_slack(stats, energy, limit)
                        if energy > limit:
                            _funnel(stats, "energy", True)
                            continue
                        # 放飞点和航段都没变的，交给原来的会合算子，这里不重复占评价。
                        if launch_vid == sortie.launch_vid and k == len(sortie.air):
                            found_k = k
                            continue
                        held.append((ret, -k, energy, sortie.sid, launch_vid, prefix, suffix,
                                     truck, customer))
                        found_k = k
            if found_k is not None:
                break
        held.sort()
        specs.extend(held[:6])
    specs.sort()
    out = []
    for ret, neg_k, energy, sid, launch_vid, prefix, suffix, truck, customer in specs:
        if len(out) >= n:
            break
        tried.add((sid, truck, customer, launch_vid, -neg_k))
        cand = _apply_short_return(plan, inst, phys, sid, launch_vid, prefix, suffix, truck, customer)
        if cand is None:
            _funnel(stats, "schedule", True)
            continue
        out.append(("SUPPORT_RENDEZVOUS", cand))
    return out


def propose_support_rendezvous(plan, ctx, n: int, tried: set, allow_cross: bool):
    """返回至多 n 个已插入会合访问的计划。S 的 allow_cross 为假，回收车不变。"""
    inst, phys = ctx.inst, ctx.phys
    stats = getattr(ctx, "live_stats", None)
    out = []
    placed: set[int] = set()
    seen: set[int] = set()
    passed: set[int] = set()
    ranked = []
    for s in _tails(plan):
        seen.add(s.sid)
        launch = plan.visits[s.launch_vid].truck
        air_customers = {inst.parcel_to_customer[p] for p in s.air if p in inst.parcel_to_customer}
        end = inst.customer(inst.parcel_to_customer[s.air[-1]])
        endpos = (end.x, end.y)
        sp = sortie_start(inst, plan, s)
        limit = phys.e_cap - phys.e_min + phys.energy_tol
        use_energy = allow_cross and bool(getattr(getattr(ctx, "alg", None), "x_energy_rendezvous", False))
        screened = energy_feasible_rendezvous(plan, inst, phys, s, sp, limit, stats) if use_energy else None
        trucks = [t for t in plan.routes if (t != launch if allow_cross else t == launch)]
        for truck in trucks:
            route = plan.routes.get(truck, [])
            min_pos = 0
            if truck == launch:
                if s.launch_vid not in route:
                    continue
                min_pos = route.index(s.launch_vid) + 1
                if min_pos > len(route):
                    continue
            owned = _customers_on(plan, truck)
            if screened is not None:
                near_ids = list(screened.get(truck, []))
            else:
                near_ids = rendezvous_candidates(plan, inst, truck, endpos, air_customers)
            for customer_id in near_ids:
                c = inst.customer(customer_id)
                key = (s.sid, truck, c.customer_id)
                if key in tried:
                    continue
                _funnel(stats, "generated", allow_cross)
                try:
                    energy = air_energy(inst, phys, sp, list(s.air), (c.x, c.y))
                except KeyError:
                    _funnel(stats, "energy", allow_cross)
                    continue
                if allow_cross and not use_energy:
                    _note_slack(stats, energy, limit)
                if energy > limit:
                    _funnel(stats, "energy", allow_cross)
                    continue
                passed.add(s.sid)
                existing = None
                if c.customer_id in owned:
                    existing = next((vid for vid in route[min_pos:]
                                     if plan.visits[vid].customer == c.customer_id), None)
                    if existing is None:
                        _funnel(stats, "schedule", allow_cross)
                        continue
                    detour = 0.0
                else:
                    det = _min_detour(plan, inst, truck, c.customer_id, min_pos)
                    if det is None:
                        _funnel(stats, "schedule", allow_cross)
                        continue
                    detour = det[0]
                flight = math.hypot(c.x - endpos[0], c.y - endpos[1])
                wait = abs(flight / phys.drone_speed_m_s - detour / phys.truck_speed_m_s)
                score = (phys.c_km * detour / 1000.0
                         + phys.wage_per_s * detour / phys.truck_speed_m_s
                         + phys.cost_depot_kwh * energy
                         + phys.wage_per_s * wait)
                ranked.append((score, s.sid, truck, c.customer_id, min_pos, existing))
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    from .evaluate import has_wait_cycle
    for _, sid, truck, customer, min_pos, existing in ranked:
        if len(out) >= n:
            break
        tried.add((sid, truck, customer))
        cand = plan.clone()
        so = cand.sorties[sid]
        if existing is not None and existing in cand.visits:
            old = so.rec_vid
            so.rec_vid = existing
        else:
            spot = _min_detour(cand, inst, truck, customer, min_pos)
            if spot is None:
                _funnel(stats, "schedule", allow_cross)
                continue
            visit = cand.add_visit(truck, customer, pos=spot[1], ground=[])
            old = so.rec_vid
            so.rec_vid = visit.vid
        ov = cand.visits.get(old)
        if ov is not None and not ov.ground and not any(
                o.sid != sid and (o.launch_vid == old or o.rec_vid == old) for o in cand.sorties.values()):
            cand.remove_visit(old)
        if has_wait_cycle(cand):
            _funnel(stats, "schedule", allow_cross)
            continue
        out.append(("SUPPORT_RENDEZVOUS", cand))
        placed.add(sid)
    # 整段飞不到任何一辆接机车的航次，用最后一格试更短的回程或拆段。
    # 前几格仍是原来的会合，评价次数也不增加。城市案例没有这种航次时，候选列表不变。
    blocked = seen - passed
    if (allow_cross and blocked and n > 0
            and bool(getattr(getattr(ctx, "alg", None), "x_short_return", False))):
        geo = _short_return_plans(plan, ctx, 1, tried, seen - blocked)
        if geo:
            if len(out) < n:
                out.extend(geo)
            elif len(out) == n:
                out[-1] = geo[0]
    return out


def propose_energy_retarget(plan, ctx):
    """跨车航次离电量上限不到 0.05 kWh 时，改到更早的访问或另一辆车已有的访问。

    没有这么紧的航次就返回 None，调用方不消耗评价。电池上限仍是 e_cap − e_min。
    只改回收点，票不变。新点必须严格更省电，并且仍在上限以内。
    """
    if not bool(getattr(getattr(ctx, "state", None), "nominal_cross", False)):
        return None
    if not bool(getattr(getattr(ctx, "alg", None), "x_energy_retarget", False)):
        return None
    from .evaluate import has_wait_cycle, is_cross_sortie
    inst, phys = ctx.inst, ctx.phys
    limit = phys.e_cap - phys.e_min + phys.energy_tol
    best = None
    best_energy = None
    for sortie in list(plan.sorties.values()):
        if not sortie.air or not is_cross_sortie(plan, sortie):
            continue
        rec = plan.visits.get(sortie.rec_vid)
        launch_visit = plan.visits.get(sortie.launch_vid)
        if rec is None or launch_visit is None:
            continue
        sp = sortie_start(inst, plan, sortie)
        try:
            current = air_energy(inst, phys, sp, list(sortie.air), _pos(inst, plan, rec.vid))
        except KeyError:
            continue
        if current < limit - 0.05:
            continue
        launch = launch_visit.truck
        vids: list[int] = []
        route = plan.routes.get(rec.truck, [])
        if rec.vid in route:
            vids.extend(route[:route.index(rec.vid)])
        for truck, other in plan.routes.items():
            if truck == rec.truck or truck == launch:
                continue
            vids.extend(other)
        for vid in vids:
            if vid == sortie.launch_vid or vid == sortie.rec_vid:
                continue
            try:
                energy = air_energy(inst, phys, sp, list(sortie.air), _pos(inst, plan, vid))
            except KeyError:
                continue
            if energy > limit + 1e-12 or energy >= current - 1e-9:
                continue
            cand = plan.clone()
            so = cand.sorties[sortie.sid]
            old = so.rec_vid
            so.rec_vid = vid
            ov = cand.visits.get(old)
            if ov is not None and not ov.ground and not any(
                    o.sid != so.sid and (o.launch_vid == old or o.rec_vid == old)
                    for o in cand.sorties.values()):
                cand.remove_visit(old)
            if has_wait_cycle(cand):
                continue
            if list(so.air) != list(sortie.air):
                continue
            if best_energy is None or energy < best_energy - 1e-12:
                best, best_energy = cand, energy
    return best


def try_energy_retarget(plan, ctx, budget, stats):
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    cand = propose_energy_retarget(plan, ctx)
    if cand is None or budget.evals_left() <= 0:
        return None, None
    ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "ENERGY_RETARGET", stats, budget)
    if ev is None or not ev.feasible:
        return None, None
    if not _within_makespan_cap(ev, ctx) or not _nominal_cross_intact(cand, ev, ctx):
        return None, None
    stats.aud("ENERGY_RETARGET", "feasible")
    return cand, ev


def try_support_rendezvous(plan, ctx, budget, stats):
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    if not hasattr(ctx, "support_tried"):
        ctx.support_tried = set()
    allow = bool(getattr(ctx.state, "nominal_cross", False))
    best_p, best_ev = None, None
    n_prop = 1 if getattr(ctx.alg, "v13_rules", False) else ctx.alg.cross_n
    for _, cand in propose_support_rendezvous(plan, ctx, n_prop, ctx.support_tried, allow):
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "SUPPORT_RENDEZVOUS", stats, budget)
        if ev is None:
            break
        stats.aud("SUPPORT_RENDEZVOUS", "calls")
        if not ev.feasible:
            stats.aud("SUPPORT_RENDEZVOUS", "infeasible")
            _funnel(stats, "schedule", allow)
            continue
        stats.aud("SUPPORT_RENDEZVOUS", "feasible")
        if not _within_makespan_cap(ev, ctx):
            _funnel(stats, "cap", allow)
            continue
        if not _nominal_cross_intact(cand, ev, ctx):
            _funnel(stats, "margin", allow)
            continue
        if best_ev is None or (ev.cost is not None and (best_ev.cost is None or ev.cost < best_ev.cost)):
            best_p, best_ev = cand, ev
    return best_p, best_ev


def matched_handoff(plan, ctx):
    """把若干航次同时改派到不同的（车，访问）上。边权是飞行加等待的代理，一次匹配。"""
    from .evaluate import has_wait_cycle
    inst, phys = ctx.inst, ctx.phys
    tails = list(_tails(plan))[:4]
    if not tails:
        return None
    options: dict[int, list[tuple[int, float]]] = {}
    vids: list[int] = []
    for sortie in tails:
        launch = plan.visits[sortie.launch_vid].truck
        end = inst.customer(inst.parcel_to_customer[sortie.air[-1]])
        start = sortie_start(inst, plan, sortie)
        for truck, route in plan.routes.items():
            if truck == launch:
                continue
            for vid in route:
                try:
                    energy = air_energy(inst, phys, start, list(sortie.air), _pos(inst, plan, vid))
                except KeyError:
                    continue
                if energy > phys.e_cap - phys.e_min + phys.energy_tol:
                    continue
                flight = math.hypot(_pos(inst, plan, vid)[0] - end.x, _pos(inst, plan, vid)[1] - end.y)
                weight = phys.cost_depot_kwh * energy + phys.wage_per_s * flight / phys.drone_speed_m_s
                options.setdefault(sortie.sid, []).append((vid, weight))
                if vid not in vids:
                    vids.append(vid)
    sids = [sid for sid in options if options[sid]]
    if not sids:
        return None
    vids = vids[:8]
    if len(sids) == 1:
        vid, _ = min(options[sids[0]], key=lambda item: (item[1], item[0]))
        chosen = [(sids[0], vid)]
    else:
        from scipy.optimize import linear_sum_assignment
        big = 1e6
        matrix = []
        for sid in sids:
            weights = {vid: weight for vid, weight in options[sid]}
            matrix.append([weights.get(vid, big) for vid in vids])
        rows, cols = linear_sum_assignment(matrix)
        chosen = []
        used = set()
        for row, col in zip(rows, cols):
            if matrix[row][col] >= big or vids[col] in used:
                continue
            used.add(vids[col])
            chosen.append((sids[row], vids[col]))
    if not chosen:
        return None
    cand = plan.clone()
    for sid, vid in chosen:
        if vid not in cand.visits or sid not in cand.sorties:
            return None
        cand.sorties[sid].rec_vid = vid
    if has_wait_cycle(cand):
        return None
    return cand


def try_pair_handoff(plan, ctx, budget, stats):
    """一次把多架无人机匹配到不同的接机位置。只在 X 的名义阶段调用。"""
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    from .cross_nominal import propose_exchange
    if not getattr(ctx.state, "nominal_cross", False):
        return None, None
    tried = getattr(ctx, "handoff_tried", None)
    if tried is None:
        tried = set()
        ctx.handoff_tried = tried
    best_p, best_ev = None, None
    matched = matched_handoff(plan, ctx)
    proposed = [("PAIR_MATCH", matched)] if matched is not None else []
    if not proposed:
        proposed = propose_exchange(plan, ctx, 1, tried)
    stats.aud("FUNNEL_HANDOFF", "generated" if proposed else "empty")
    if proposed:
        stats.aud("FUNNEL_CROSS", "generated", len(proposed))
    for _, cand in proposed:
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "PAIR_HANDOFF", stats, budget)
        if ev is None:
            break
        if not ev.feasible:
            stats.aud("FUNNEL_HANDOFF", "schedule")
            stats.aud("FUNNEL_CROSS", "schedule")
            continue
        if not _within_makespan_cap(ev, ctx):
            stats.aud("FUNNEL_HANDOFF", "cap")
            stats.aud("FUNNEL_CROSS", "cap")
            continue
        if not _nominal_cross_intact(cand, ev, ctx):
            stats.aud("FUNNEL_HANDOFF", "margin")
            stats.aud("FUNNEL_CROSS", "margin")
            continue
        best_p, best_ev = cand, ev
    return best_p, best_ev
