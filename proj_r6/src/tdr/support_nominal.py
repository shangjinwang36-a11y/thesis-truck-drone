"""第 9 轮：给接机车插入会合访问，并给 S 一个同车版本。

名义跨车以前只能落在对方路线上已经存在的客户。恢复阶段却可以插入支援访问。
失败后用得上的会合点，失败前进不了计划。这里在评价之前插入一个空地送的会合访问：

- X：插在另一辆车上，回收点改到这个新访问，航次变成跨车。
- S：只插在放飞车上、放飞访问之后，回收点仍在同一辆车，不会产生跨车。

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


def propose_support_rendezvous(plan, ctx, n: int, tried: set, allow_cross: bool):
    """返回至多 n 个已插入会合访问的计划。S 的 allow_cross 为假，回收车不变。"""
    inst, phys = ctx.inst, ctx.phys
    stats = getattr(ctx, "live_stats", None)
    ranked = []
    for s in _tails(plan):
        launch = plan.visits[s.launch_vid].truck
        air_customers = {inst.parcel_to_customer[p] for p in s.air if p in inst.parcel_to_customer}
        end = inst.customer(inst.parcel_to_customer[s.air[-1]])
        endpos = (end.x, end.y)
        sp = sortie_start(inst, plan, s)
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
                if energy > phys.e_cap - phys.e_min + phys.energy_tol:
                    _funnel(stats, "energy", allow_cross)
                    continue
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
    out = []
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
    return out


def try_support_rendezvous(plan, ctx, budget, stats):
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    if not hasattr(ctx, "support_tried"):
        ctx.support_tried = set()
    allow = bool(getattr(ctx.state, "nominal_cross", False))
    best_p, best_ev = None, None
    for _, cand in propose_support_rendezvous(plan, ctx, ctx.alg.cross_n, ctx.support_tried, allow):
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
