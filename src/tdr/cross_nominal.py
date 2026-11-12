"""第六轮：X 名义规划专用算子 CROSS_CONVERT —— 把同车航次的回收点改到“另一辆车”的某个客户访问上.

只在 state.nominal_cross=True（X）时被 alns.optimize 调用；S 永不触发。
资格：航次未起飞、是该机体航次链的最后一个（改后链仍衔接）、原回收车=放飞车。
改动后：回收访问换成另一车 B 路线上已有的客户访问（回收只在客户点）；若原回收访问在放飞车 A 上
变成既无地送又不再被引用的纯支援访问，则删除该访问（A 少绕一段）。
每次调用至多评价 cross_n 个候选（代理分排序，已试过的不再重复），占用名义阶段同一份评价预算。"""
from __future__ import annotations

import math

from .moves import air_energy, route_times, sortie_start, sync_cost, air_time, _pos


def _detour(inst, plan, truck, vid):
    route = plan.routes[truck]
    i = route.index(vid)
    depot = (inst.depot_x, inst.depot_y)
    prv = depot if i == 0 else _pos(inst, plan, route[i - 1])
    nxt = depot if i + 1 == len(route) else _pos(inst, plan, route[i + 1])
    c = _pos(inst, plan, vid)
    return (math.hypot(c[0] - prv[0], c[1] - prv[1]) + math.hypot(nxt[0] - c[0], nxt[1] - c[1])
            - math.hypot(nxt[0] - prv[0], nxt[1] - prv[1]))


def propose_convert(plan, ctx, n: int, tried: set):
    inst, phys = ctx.inst, ctx.phys
    w = phys.wage_per_s
    cands = []
    rt_cache = {}

    def _rt(t_):
        if t_ not in rt_cache:
            rt_cache[t_] = route_times(plan, inst, phys, t_)
        return rt_cache[t_]
    for d, sids in plan.drone_sorties.items():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or s.launch_vid is None or s.rec_vid not in plan.visits or s.launch_vid not in plan.visits:
            continue
        ta = plan.visits[s.launch_vid].truck
        if plan.visits[s.rec_vid].truck != ta or not s.air:
            continue
        sp = sortie_start(inst, plan, s)
        rv_old = plan.visits[s.rec_vid]
        removable = (not rv_old.ground and
                     not any((o.sid != s.sid and (o.launch_vid == rv_old.vid or o.rec_vid == rv_old.vid))
                             for o in plan.sorties.values()))
        save = 0.0
        if removable:
            det = _detour(inst, plan, ta, rv_old.vid)
            save = phys.c_km * det / 1000.0 + w * det / phys.truck_speed_m_s + w * (phys.recovery_s)
        _, dep_a = _rt(ta)
        la = plan.routes[ta].index(s.launch_vid)
        for tb, route in plan.routes.items():
            if tb == ta:
                continue
            arr_b, _ = _rt(tb)
            for bi, vid in enumerate(route):
                key = (s.sid, vid)
                if key in tried:
                    continue
                rp = _pos(inst, plan, vid)
                try:
                    e = air_energy(inst, phys, sp, s.air, rp)
                except KeyError:
                    continue
                if e > phys.e_cap - phys.e_min + phys.energy_tol:
                    continue
                tt = arr_b[bi] - dep_a[la]
                mass = sum(inst.parcel_mass[p] for p in s.air)
                sc = save - sync_cost(phys, air_time(inst, phys, sp, s.air, rp), tt, mass) \
                    - phys.cost_depot_kwh * e
                cands.append((-sc, s.sid, vid, bool(removable)))
    cands.sort()
    out = []
    for _, sid, vid, removable in cands[:n]:
        tried.add((sid, vid))
        cand = plan.clone()
        so = cand.sorties[sid]
        old = so.rec_vid
        so.rec_vid = vid
        if removable and old in cand.visits:
            ov = cand.visits[old]
            if not ov.ground and not any(o.launch_vid == old or o.rec_vid == old for o in cand.sorties.values()):
                cand.remove_visit(old)
        from .evaluate import has_wait_cycle
        if has_wait_cycle(cand):
            continue
        out.append(("CROSS_CONVERT", cand))
    return out


def try_cross_convert(plan, ctx, budget, stats):
    from .alns import _better, eval_counted
    best_p, best_ev = None, None
    if not hasattr(ctx, "cross_tried"):
        return None, None
    for tag, cand in propose_convert(plan, ctx, ctx.alg.cross_n, ctx.cross_tried):
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "CROSS_CONVERT", stats, budget)
        if ev is None:
            break
        stats.aud("CROSS_CONVERT", "calls")
        if ev.feasible:
            stats.aud("CROSS_CONVERT", "feasible")
            if best_ev is None or _better(ev, best_ev, ctx.alg):
                best_p, best_ev = cand, ev
        else:
            stats.aud("CROSS_CONVERT", "infeasible")
    return best_p, best_ev
