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


def _funnel(stats, tag: str) -> None:
    if stats is not None:
        stats.aud("FUNNEL_SUPPORT", tag)


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


def joint_near_seeds(plan, inst, allow_cross: bool) -> list[str]:
    """X 取两辆最近的车各一站；S 取同一辆车上最近的相邻两站。"""
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
        vids = {best[1], best[2]}
    else:
        for truck, route in plan.routes.items():
            for i in range(len(route) - 1):
                a, b = _pos(inst, plan, route[i]), _pos(inst, plan, route[i + 1])
                dist = math.hypot(a[0] - b[0], a[1] - b[1])
                if best is None or dist < best[0]:
                    best = (dist, route[i], route[i + 1])
        if best is None:
            return []
        vids = {best[1], best[2]}
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
            owned = _customers_on(plan, truck)
            route = plan.routes.get(truck, [])
            min_pos = 0
            if truck == launch:
                if s.launch_vid not in route:
                    continue
                min_pos = route.index(s.launch_vid) + 1
                if min_pos > len(route):
                    continue
            near = []
            for c in inst.customers:
                if c.customer_id in air_customers or c.customer_id in owned:
                    continue
                dist = math.hypot(c.x - endpos[0], c.y - endpos[1])
                near.append((dist, c))
            near.sort(key=lambda x: (x[0], x[1].customer_id))
            for _, c in near[:4]:
                key = (s.sid, truck, c.customer_id)
                if key in tried:
                    continue
                _funnel(stats, "generated")
                try:
                    energy = air_energy(inst, phys, sp, list(s.air), (c.x, c.y))
                except KeyError:
                    _funnel(stats, "energy")
                    continue
                if energy > phys.e_cap - phys.e_min + phys.energy_tol:
                    _funnel(stats, "energy")
                    continue
                det = _min_detour(plan, inst, truck, c.customer_id, min_pos)
                if det is None:
                    _funnel(stats, "schedule")
                    continue
                ranked.append((det[0] + phys.cost_depot_kwh * energy, s.sid, truck, c.customer_id, min_pos))
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    from .evaluate import has_wait_cycle
    out = []
    for _, sid, truck, customer, min_pos in ranked:
        if len(out) >= n:
            break
        tried.add((sid, truck, customer))
        cand = plan.clone()
        so = cand.sorties[sid]
        spot = _min_detour(cand, inst, truck, customer, min_pos)
        if spot is None:
            _funnel(stats, "schedule")
            continue
        visit = cand.add_visit(truck, customer, pos=spot[1], ground=[])
        old = so.rec_vid
        so.rec_vid = visit.vid
        ov = cand.visits.get(old)
        if ov is not None and not ov.ground and not any(
                o.sid != sid and (o.launch_vid == old or o.rec_vid == old) for o in cand.sorties.values()):
            cand.remove_visit(old)
        if has_wait_cycle(cand):
            _funnel(stats, "schedule")
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
            stats.aud("FUNNEL_SUPPORT", "schedule")
            continue
        stats.aud("SUPPORT_RENDEZVOUS", "feasible")
        if not _within_makespan_cap(ev, ctx):
            stats.aud("FUNNEL_SUPPORT", "schedule")
            continue
        if not _nominal_cross_intact(cand, ev, ctx):
            stats.aud("FUNNEL_SUPPORT", "margin")
            continue
        if best_ev is None or (ev.cost is not None and (best_ev.cost is None or ev.cost < best_ev.cost)):
            best_p, best_ev = cand, ev
    return best_p, best_ev


def try_pair_handoff(plan, ctx, budget, stats):
    """修复后的一次两机互换。只在 X 的名义阶段调用。"""
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    from .cross_nominal import propose_exchange
    if not getattr(ctx.state, "nominal_cross", False):
        return None, None
    tried = getattr(ctx, "handoff_tried", None)
    if tried is None:
        tried = set()
        ctx.handoff_tried = tried
    best_p, best_ev = None, None
    proposed = propose_exchange(plan, ctx, 1, tried)
    stats.aud("FUNNEL_HANDOFF", "generated" if proposed else "empty")
    for _, cand in proposed:
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "PAIR_HANDOFF", stats, budget)
        if ev is None:
            break
        if not ev.feasible:
            stats.aud("FUNNEL_HANDOFF", "schedule")
            continue
        if not _within_makespan_cap(ev, ctx) or not _nominal_cross_intact(cand, ev, ctx):
            stats.aud("FUNNEL_HANDOFF", "margin")
            continue
        best_p, best_ev = cand, ev
    return best_p, best_ev
