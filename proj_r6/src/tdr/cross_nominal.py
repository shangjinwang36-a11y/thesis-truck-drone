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
                t_air_ = air_time(inst, phys, sp, s.air, rp)
                if e + phys.hover_energy_kwh(max(0.0, tt - t_air_), 0.0) > phys.e_cap - phys.e_min + phys.energy_tol:
                    continue      # 悬停等车的电量预检（X 专用候选的合法性过滤）
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
    from .alns import _better, _cross_energy_ok, _nominal_cross_intact, _within_makespan_cap, eval_counted
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
            if not _within_makespan_cap(ev, ctx):
                stats.aud("HS_CAP", "rejected_convert")
                continue
            if not _cross_energy_ok(cand, plan, ev, ctx):
                stats.aud("CROSS_ENERGY_MARGIN", "rejected_convert")
                continue
            if not _nominal_cross_intact(cand, ev, ctx):
                stats.aud("CROSS_ROBUST", "rejected_convert")
                continue
            if best_ev is None or _better(ev, best_ev, ctx.alg):
                best_p, best_ev = cand, ev
        else:
            stats.aud("CROSS_CONVERT", "infeasible")
    return best_p, best_ev


def _kept_air(plan, inst, air, receiver: str) -> tuple[list[str], list[str]]:
    """接机车路线上的客户留在车上。返回（仍空送的票，改地面的票）。"""
    owned = set()
    for vid in plan.routes.get(receiver, []):
        owned.add(plan.visits[vid].customer)
    kept, moved = [], []
    for p in air:
        cust = inst.parcel_to_customer.get(p)
        if cust in owned:
            moved.append(p)
        else:
            kept.append(p)
    return kept, moved


def _place_on_truck(plan, inst, parcels, truck: str) -> None:
    by_c = {}
    for vid in plan.routes.get(truck, []):
        by_c.setdefault(plan.visits[vid].customer, vid)
    for p in parcels:
        cust = inst.parcel_to_customer[p]
        vid = by_c.get(cust)
        if vid is None:
            continue
        ground = plan.visits[vid].ground
        if p not in ground:
            ground.append(p)


def propose_exchange(plan, ctx, n: int, tried: set):
    """X 名义：两架无人机互换回收车。

    单向把客机留在对方车上直到收工，会在「每车 2 架、3 个机位」下把对方占满。
    互换以后每车仍是走一架、来一架：离开的那架先起飞，进来的那架才落地，
    落地之后在车的机体数不超过机位数减一。S 的 nominal_cross 为假，这里直接空。
    """
    if not getattr(ctx.state, "nominal_cross", False):
        return []
    if not getattr(ctx.alg, "x_cross_exchange", False):
        return []
    inst, phys = ctx.inst, ctx.phys
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 0.0) or 0.0)
    from .cross_robust import reserve_kwh, slack_floor_kwh
    need = max(reserve_kwh(phys), slack_floor_kwh(phys, slack))
    tails = []
    for sids in plan.drone_sorties.values():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or not s.air or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        lt = plan.visits[s.launch_vid].truck
        if plan.visits[s.rec_vid].truck != lt:
            continue
        route = plan.routes.get(lt, [])
        if s.launch_vid not in route or s.rec_vid not in route:
            continue
        if route.index(s.launch_vid) >= route.index(s.rec_vid):
            continue
        tails.append(s)
    ranked = []
    for i, a in enumerate(tails):
        ta = plan.visits[a.launch_vid].truck
        for b in tails[i + 1:]:
            tb = plan.visits[b.launch_vid].truck
            if ta == tb:
                continue
            key = (min(a.sid, b.sid), max(a.sid, b.sid))
            if key in tried:
                continue
            kept_a, _ = _kept_air(plan, inst, a.air, tb)
            kept_b, _ = _kept_air(plan, inst, b.air, ta)
            if not kept_a or not kept_b:
                continue
            try:
                ea = air_energy(inst, phys, sortie_start(inst, plan, a), kept_a, _pos(inst, plan, b.rec_vid))
                eb = air_energy(inst, phys, sortie_start(inst, plan, b), kept_b, _pos(inst, plan, a.rec_vid))
            except KeyError:
                continue
            # 飞行电量已经吃掉裕度时，最终时刻表不可能合格，不必再送去完整评价。
            if ea > phys.e_cap - need + phys.energy_tol or eb > phys.e_cap - need + phys.energy_tol:
                continue
            ranked.append((ea + eb, a.sid, b.sid))
    ranked.sort()
    out = []
    from .evaluate import has_wait_cycle
    for _, sa, sb in ranked:
        if len(out) >= n:
            break
        key = (min(sa, sb), max(sa, sb))
        tried.add(key)
        cand = plan.clone()
        a = cand.sorties[sa]
        b = cand.sorties[sb]
        ta = cand.visits[a.launch_vid].truck
        tb = cand.visits[b.launch_vid].truck
        rec_a, rec_b = a.rec_vid, b.rec_vid
        kept_a, moved_a = _kept_air(cand, inst, a.air, tb)
        kept_b, moved_b = _kept_air(cand, inst, b.air, ta)
        _place_on_truck(cand, inst, moved_a, tb)
        _place_on_truck(cand, inst, moved_b, ta)
        a.air = kept_a
        b.air = kept_b
        a.rec_vid = rec_b
        b.rec_vid = rec_a
        if has_wait_cycle(cand):
            continue
        out.append(("CROSS_EXCHANGE", cand))
    return out


def _exchange_worth(ev, cur_ev, alg) -> bool:
    """严格改进，或成本上升不超过 tau。tau=0 时只收改进，和主循环一样。"""
    from .alns import _better
    if cur_ev is None or ev is None or not ev.feasible:
        return False
    if _better(ev, cur_ev, alg):
        return True
    tau = float(getattr(alg, "x_exchange_cost_tau", 0.0) or 0.0)
    if tau <= 0 or ev.cost is None or cur_ev.cost is None:
        return False
    return ev.cost <= cur_ev.cost + tau + 1e-9


# 从同一份名义预算里留出的评价次数。按飞行电量排序时，C100/RC100 上成本最低的稳健互换排在第 14 位左右。
EXCHANGE_EVALS = 24


def polish_with_convert(plan, ev, ctx, budget, stats, n: int):
    """采用 S 之后，用词典序改进把同车航次改成跨车。

    只接受更低的真实成本，完工不超过上限，最终时刻表上每条跨车都过稳健检查。
    不看情景分，也不允许 tau 把名义抬贵。
    """
    from .alns import _better, _nominal_cross_intact, _within_makespan_cap, eval_counted
    from .cross_robust import cross_robust_violations
    best_p, best_ev = None, None
    tried: set = set()
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 0.0) or 0.0)
    for _, cand in propose_convert(plan, ctx, n, tried):
        if budget.evals_left() <= 0:
            break
        got = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "CONVERT_POLISH", stats, budget)
        if got is None:
            break
        stats.aud("CONVERT_POLISH", "calls")
        if not got.feasible or got.timeline is None:
            stats.aud("CONVERT_POLISH", "infeasible")
            continue
        if not _within_makespan_cap(got, ctx):
            stats.aud("CONVERT_POLISH", "makespan")
            continue
        if cross_robust_violations(cand, ctx.inst, ctx.phys, got.timeline, slack):
            stats.aud("CONVERT_POLISH", "margin")
            continue
        if not _nominal_cross_intact(cand, got, ctx):
            stats.aud("CONVERT_POLISH", "margin")
            continue
        if not _better(got, ev, ctx.alg):
            stats.aud("CONVERT_POLISH", "not_better")
            continue
        if best_ev is None or _better(got, best_ev, ctx.alg):
            best_p, best_ev = cand, got
            ev = got
    return best_p, best_ev


def try_cross_exchange(plan, ctx, budget, stats, n: int | None = None):
    from .alns import _nominal_cross_intact, _within_makespan_cap, eval_counted
    best_p, best_ev = None, None
    if not hasattr(ctx, "cross_tried"):
        return None, None
    tried = getattr(ctx, "exchange_tried", None)
    if tried is None:
        tried = set()
        ctx.exchange_tried = tried
    limit = ctx.alg.cross_n if n is None else n
    for tag, cand in propose_exchange(plan, ctx, limit, tried):
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "CROSS_EXCHANGE", stats, budget)
        if ev is None:
            break
        stats.aud("CROSS_EXCHANGE", "calls")
        if not ev.feasible:
            stats.aud("CROSS_EXCHANGE", "infeasible")
            continue
        stats.aud("CROSS_EXCHANGE", "feasible")
        if not _within_makespan_cap(ev, ctx):
            stats.aud("CROSS_EXCHANGE", "rejected_makespan")
            continue
        if not _nominal_cross_intact(cand, ev, ctx):
            stats.aud("CROSS_EXCHANGE", "rejected_robust")
            continue
        if best_ev is None or (ev.cost is not None and (best_ev.cost is None or ev.cost < best_ev.cost - 1e-9)):
            best_p, best_ev = cand, ev
    return best_p, best_ev
