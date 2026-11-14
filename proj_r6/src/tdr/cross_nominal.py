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
    keep = 1 if getattr(getattr(ctx, "alg", None), "v13_rules", False) else n
    for neg_sc, sid, vid, removable in cands:
        if getattr(getattr(ctx, "alg", None), "v13_rules", False) and -neg_sc <= 1e-6:
            break
        if len(out) >= keep:
            break
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
        stats.aud("FUNNEL_CROSS", "generated")
        if ev.feasible:
            stats.aud("CROSS_CONVERT", "feasible")
            if not _within_makespan_cap(ev, ctx):
                stats.aud("HS_CAP", "rejected_convert")
                stats.aud("FUNNEL_CROSS", "cap")
                continue
            if not _cross_energy_ok(cand, plan, ev, ctx):
                stats.aud("CROSS_ENERGY_MARGIN", "rejected_convert")
                stats.aud("FUNNEL_CROSS", "energy")
                continue
            if not _nominal_cross_intact(cand, ev, ctx):
                stats.aud("CROSS_ROBUST", "rejected_convert")
                stats.aud("FUNNEL_CROSS", "margin")
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
        stats.aud("FUNNEL_CROSS", "generated")
        if not got.feasible or got.timeline is None:
            stats.aud("CONVERT_POLISH", "infeasible")
            stats.aud("FUNNEL_CROSS", "schedule")
            continue
        if not _within_makespan_cap(got, ctx):
            stats.aud("CONVERT_POLISH", "makespan")
            stats.aud("FUNNEL_CROSS", "cap")
            continue
        if cross_robust_violations(cand, ctx.inst, ctx.phys, got.timeline, slack):
            stats.aud("CONVERT_POLISH", "margin")
            stats.aud("FUNNEL_CROSS", "margin")
            continue
        if not _nominal_cross_intact(cand, got, ctx):
            stats.aud("CONVERT_POLISH", "margin")
            stats.aud("FUNNEL_CROSS", "margin")
            continue
        if not _better(got, ev, ctx.alg):
            stats.aud("CONVERT_POLISH", "not_better")
            continue
        if best_ev is None or _better(got, best_ev, ctx.alg):
            best_p, best_ev = cand, got
            ev = got
    if best_p is not None:
        stats.aud("FUNNEL_CROSS", "accepted")
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
        stats.aud("FUNNEL_CROSS", "generated")
        if not ev.feasible:
            stats.aud("CROSS_EXCHANGE", "infeasible")
            stats.aud("FUNNEL_CROSS", "schedule")
            continue
        stats.aud("CROSS_EXCHANGE", "feasible")
        if not _within_makespan_cap(ev, ctx):
            stats.aud("CROSS_EXCHANGE", "rejected_makespan")
            stats.aud("FUNNEL_CROSS", "cap")
            continue
        if not _nominal_cross_intact(cand, ev, ctx):
            stats.aud("CROSS_EXCHANGE", "rejected_robust")
            stats.aud("FUNNEL_CROSS", "margin")
            continue
        if best_ev is None or (ev.cost is not None and (best_ev.cost is None or ev.cost < best_ev.cost - 1e-9)):
            best_p, best_ev = cand, ev
    return best_p, best_ev


def _route_length(inst, plan, truck) -> float:
    route = plan.routes.get(truck, [])
    depot = (inst.depot_x, inst.depot_y)
    prev = depot
    total = 0.0
    for vid in route:
        c = _pos(inst, plan, vid)
        total += math.hypot(c[0] - prev[0], c[1] - prev[1])
        prev = c
    total += math.hypot(depot[0] - prev[0], depot[1] - prev[1])
    return total


def _apply_rec(plan, sid, vid, removable_old: bool) -> bool:
    so = plan.sorties.get(sid)
    if so is None:
        return False
    old = so.rec_vid
    so.rec_vid = vid
    if removable_old and old in plan.visits:
        ov = plan.visits[old]
        if not ov.ground and not any(o.launch_vid == old or o.rec_vid == old for o in plan.sorties.values()):
            plan.remove_visit(old)
    from .evaluate import has_wait_cycle
    return not has_wait_cycle(plan)


def _floor_kwh(phys, slack_s: float) -> float:
    from .cross_robust import x_cross_energy_floor_kwh
    return x_cross_energy_floor_kwh(phys, slack_s)


def _clears(phys, consumed: float, reserve: float) -> bool:
    return consumed <= phys.e_cap - reserve + phys.energy_tol


def scheduler_feasible(plan, inst, phys, H, slack_s: float) -> bool:
    """The real schedule, without charging a search evaluation.

    The geometric floor only prices the edited sortie. Moving its recovery point
    changes other drones' waits, and those drones are what the scheduler rejects
    with SWAP_CANNOT_FIX. This runs the same schedule, swap check, H check, and
    cross floor the evaluator uses.
    """
    from .evaluate import channel_check, has_wait_cycle, is_cross_sortie, truck_slot_check
    from .schedule import allocate_charging, initial_state, schedule_plan
    from .cross_robust import cross_robust_violations
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()) and has_wait_cycle(plan):
        return False
    state = initial_state(inst, phys)
    try:
        tl = schedule_plan(plan, inst, phys, state)
    except (KeyError, ValueError):
        # A retarget can drop a visit another sortie still names. That plan is not schedulable.
        return False
    if not tl.converged or tl.swap_msg:
        return False
    ok, _, _ = allocate_charging(tl, phys, state)
    if not ok or tl.custody_violations:
        return False
    if H is not None and any(f > float(H) + 1e-6 for f in tl.truck_finish.values()):
        return False
    if truck_slot_check(plan, inst, phys, tl, state) or channel_check(plan, phys, tl):
        return False
    for energies in tl.drone_energy.values():
        if any(e < phys.e_min - phys.energy_tol for e in energies):
            return False
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        if cross_robust_violations(plan, inst, phys, tl, slack_s):
            return False
    return True


def _rescue_open(plan, inst, phys, customer_xy, mass: float, launch: str, rec: str, floor: float) -> bool:
    """A truck other than the launch and the chosen recovery can still meet this customer."""
    for truck, route in plan.routes.items():
        if truck == launch or truck == rec:
            continue
        for vid in route:
            pos = _pos(inst, plan, vid)
            dist = math.hypot(pos[0] - customer_xy[0], pos[1] - customer_xy[1])
            need = phys.fly_energy_kwh(dist, mass) + phys.hover_energy_kwh(phys.recovery_s, mass)
            if _clears(phys, need, floor):
                return True
    return False


def census_cross_candidates(plan, inst, phys, slack_s: float = 90.0) -> dict[str, int]:
    """Cheap count of cross meetings. emin clears E_min; floor clears the 0.08333 kWh margin.

    No full evaluation. The two counts are the neighbourhood before and after that margin.
    """
    floor = _floor_kwh(phys, slack_s)
    emin = 0
    legal = 0
    if plan is None or len(plan.routes) < 2:
        return {"emin": 0, "floor": 0}
    rt_cache = {}

    def rt(truck):
        if truck not in rt_cache:
            rt_cache[truck] = route_times(plan, inst, phys, truck)
        return rt_cache[truck]

    for sids in plan.drone_sorties.values():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or not s.air or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        if plan.visits[s.launch_vid].truck != plan.visits[s.rec_vid].truck:
            continue
        ta = plan.visits[s.launch_vid].truck
        if s.launch_vid not in plan.routes.get(ta, []):
            continue
        sp = sortie_start(inst, plan, s)
        _, dep_a = rt(ta)
        la = plan.routes[ta].index(s.launch_vid)
        mass = sum(inst.parcel_mass[p] for p in s.air)
        for tb, route in plan.routes.items():
            if tb == ta:
                continue
            arr_b, _ = rt(tb)
            for bi, vid in enumerate(route):
                rp = _pos(inst, plan, vid)
                try:
                    e = air_energy(inst, phys, sp, s.air, rp)
                except KeyError:
                    continue
                tt = arr_b[bi] - dep_a[la]
                hover = phys.hover_energy_kwh(max(0.0, tt - air_time(inst, phys, sp, s.air, rp)), mass)
                consumed = e + hover
                if not _clears(phys, consumed, phys.e_min):
                    continue
                emin += 1
                if _clears(phys, consumed, floor):
                    legal += 1
    # Ground hand-offs off the critical truck. cross_air_candidates already drops E_min failures.
    from .moves import cross_air_candidates
    slow = _critical_truck(inst, plan, phys, None)
    if slow is not None:
        depot = (inst.depot_x, inst.depot_y)
        route = plan.routes.get(slow, [])
        parcels = []
        for i, vid in enumerate(route):
            v = plan.visits[vid]
            if len(v.ground) != 1:
                continue
            if any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values()):
                continue
            cc = inst.customer(v.customer)
            prv = depot if i == 0 else _pos(inst, plan, route[i - 1])
            nxt = depot if i + 1 == len(route) else _pos(inst, plan, route[i + 1])
            det = (math.hypot(cc.x - prv[0], cc.y - prv[1]) + math.hypot(nxt[0] - cc.x, nxt[1] - cc.y)
                   - math.hypot(nxt[0] - prv[0], nxt[1] - prv[1]))
            if det > 0:
                parcels.append(v.ground[0])
        for parcel in parcels[:2]:
            mass = inst.parcel_mass[parcel]
            for cand in cross_air_candidates(plan, inst, phys, parcel, max_cross=4, allow_support=True):
                if not cand.cross:
                    continue
                emin += 1
                hover = phys.hover_energy_kwh(phys.recovery_s, mass)
                if _clears(phys, cand.energy + hover, floor):
                    legal += 1
    return {"emin": emin, "floor": legal}


def propose_integrated(plan, ctx, kind: int):
    """One cross neighbourhood move. No full evaluation.

    kind 0: reassign several same-truck recoveries onto other trucks at once.
    kind 1: move a ground cluster off the critical truck onto drones that meet
    another truck, shortening that truck inside H.
    kind 2: the single best recovery retarget.
    A meeting that does not clear the 0.08333 kWh floor is not returned, so the
    caller does not spend an evaluation on it.
    """
    if not getattr(getattr(ctx, "state", None), "nominal_cross", False):
        return None
    inst, phys = ctx.inst, ctx.phys
    if kind % 4 == 1:
        return _relieve_slow_truck(plan, ctx)
    moves = []
    rt_cache = {}

    def rt(truck):
        if truck not in rt_cache:
            rt_cache[truck] = route_times(plan, inst, phys, truck)
        return rt_cache[truck]

    tails = []
    for sids in plan.drone_sorties.values():
        if not sids:
            continue
        s = plan.sorties[sids[-1]]
        if s.started or not s.air or s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        if plan.visits[s.launch_vid].truck != plan.visits[s.rec_vid].truck:
            continue
        tails.append(s)
    for s in tails:
        ta = plan.visits[s.launch_vid].truck
        rv_old = plan.visits[s.rec_vid]
        removable = (not rv_old.ground and not any(
            o.sid != s.sid and (o.launch_vid == rv_old.vid or o.rec_vid == rv_old.vid)
            for o in plan.sorties.values()))
        save = 0.0
        if removable:
            det = _detour(inst, plan, ta, rv_old.vid)
            save = phys.c_km * det / 1000.0 + phys.wage_per_s * det / phys.truck_speed_m_s
        sp = sortie_start(inst, plan, s)
        _, dep_a = rt(ta)
        if s.launch_vid not in plan.routes.get(ta, []):
            continue
        la = plan.routes[ta].index(s.launch_vid)
        floor = _floor_kwh(phys, float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0))
        n_el = max(2, int(getattr(inst, "n", 0) or 0))
        p_single = 3.0 / (2.0 * n_el)
        end = inst.customer(inst.parcel_to_customer[s.air[-1]])
        best = None
        for tb, route in plan.routes.items():
            if tb == ta:
                continue
            arr_b, _ = rt(tb)
            for bi, vid in enumerate(route):
                rp = _pos(inst, plan, vid)
                try:
                    e = air_energy(inst, phys, sp, s.air, rp)
                except KeyError:
                    continue
                tt = arr_b[bi] - dep_a[la]
                mass = sum(inst.parcel_mass[p] for p in s.air)
                t_air = air_time(inst, phys, sp, s.air, rp)
                hover = phys.hover_energy_kwh(max(0.0, tt - t_air), mass)
                # Launch, one service, and recovery are always flown. The geometric
                # check is still only this sortie; the scheduler below prices the others.
                necessary = (e + hover
                             + phys.hover_energy_kwh(phys.launch_s, mass)
                             + phys.hover_energy_kwh(phys.air_service_s, mass)
                             + phys.hover_energy_kwh(phys.recovery_s, mass))
                if not _clears(phys, necessary, floor):
                    continue
                sc = save - sync_cost(phys, t_air, tt, mass) - phys.cost_depot_kwh * e
                # Plain v1.3 failure weight. A second truck that can still meet the customer
                # leaves a cross rescue open, so this placement is worth 3/(2N) of the failure cost.
                if _rescue_open(plan, inst, phys, (end.x, end.y), mass, ta, tb, floor):
                    sc += p_single * max(save, phys.wage_per_s * phys.recovery_s)
                if best is None or sc > best[0]:
                    best = (sc, vid, removable)
        if best is not None and best[0] > 1e-6:
            moves.append((best[0], s.sid, best[1], best[2]))
    width = 1 if kind % 4 == 2 else (2 if kind % 4 == 3 else 3)
    moves.sort(reverse=True)
    # One move per launch truck. Width 2 is the pair insertion the ceiling found useful.
    chosen = []
    used_trucks = set()
    used_vids = set()
    for sc, sid, vid, removable in moves:
        truck = plan.visits[plan.sorties[sid].launch_vid].truck
        if truck in used_trucks or vid in used_vids:
            continue
        used_trucks.add(truck)
        used_vids.add(vid)
        chosen.append((sid, vid, removable))
        if len(chosen) >= width:
            break
    moves = chosen
    bundles = []
    if len(moves) >= 2:
        bundles.append(moves)
    bundles.extend([[item] for item in moves])
    found = _first_on_schedule(plan, ctx, bundles)
    if found is not None:
        return found
    if kind % 4 == 0:
        return _relieve_slow_truck(plan, ctx)
    return None


def _first_on_schedule(plan, ctx, bundles):
    """Return the first bundle the real scheduler accepts. No search evaluation."""
    if not bundles:
        return None
    inst, phys = ctx.inst, ctx.phys
    H = getattr(ctx, "H", None)
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0)
    tried = 0
    for bundle in bundles:
        if tried >= 6:
            break
        cand = plan.clone()
        applied = 0
        ok = True
        for item in bundle:
            if not _apply_rec(cand, item[0], item[1], item[2]):
                ok = False
                break
            applied += 1
        if not ok or applied == 0:
            continue
        tried += 1
        if scheduler_feasible(cand, inst, phys, H, slack):
            return cand
        ctx.schedule_rejects = int(getattr(ctx, "schedule_rejects", 0) or 0) + 1
    return None


def _critical_truck(inst, plan, phys, H: float | None) -> str | None:
    """Truck whose route is longest, with anyone already past H ranked first."""
    best = None
    speed = phys.truck_speed_m_s or 1.0
    for truck in plan.routes:
        est = _route_length(inst, plan, truck) / speed
        score = est + (1.0e6 if H is not None and est > float(H) else 0.0)
        if best is None or score > best[0]:
            best = (score, truck)
    return None if best is None else best[1]


def _relieve_slow_truck(plan, ctx):
    """Hand a cluster off the critical truck to drones that still clear the energy floor."""
    from .moves import apply_air, cross_air_candidates, remove_parcel
    inst, phys = ctx.inst, ctx.phys
    H = getattr(ctx, "H", None)
    if len(plan.routes) < 2:
        return None
    slow = _critical_truck(inst, plan, phys, H)
    if slow is None:
        return None
    floor = _floor_kwh(phys, float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0))
    n_el = max(2, int(getattr(inst, "n", 0) or 0))
    p_single = 3.0 / (2.0 * n_el)
    route = plan.routes.get(slow, [])
    depot = (inst.depot_x, inst.depot_y)
    ranked = []
    for i, vid in enumerate(route):
        v = plan.visits[vid]
        if len(v.ground) != 1:
            continue
        if any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values()):
            continue
        cc = inst.customer(v.customer)
        prv = depot if i == 0 else _pos(inst, plan, route[i - 1])
        nxt = depot if i + 1 == len(route) else _pos(inst, plan, route[i + 1])
        det = (math.hypot(cc.x - prv[0], cc.y - prv[1]) + math.hypot(nxt[0] - cc.x, nxt[1] - cc.y)
               - math.hypot(nxt[0] - prv[0], nxt[1] - prv[1]))
        if det > 0:
            yuan = phys.c_km * det / 1000.0 + phys.wage_per_s * det / phys.truck_speed_m_s
            ranked.append((yuan, v.ground[0], (cc.x, cc.y)))
    ranked.sort(reverse=True)
    if not ranked:
        return None
    cand = plan.clone()
    placed = 0
    for yuan, parcel, xy in ranked[:2]:
        trial = cand.clone()
        remove_parcel(trial, parcel)
        mass = inst.parcel_mass[parcel]
        acs = []
        for a in cross_air_candidates(trial, inst, phys, parcel, max_cross=4, allow_support=True):
            if not a.cross:
                continue
            hover = phys.hover_energy_kwh(phys.recovery_s, mass)
            if not _clears(phys, a.energy + hover, floor):
                continue
            rec = a.rec_truck or trial.visits[a.rec_vid].truck
            bonus = 0.0
            if _rescue_open(trial, inst, phys, xy, mass, a.truck, rec, floor):
                bonus = p_single * max(yuan, phys.wage_per_s * phys.recovery_s)
            acs.append((a.proxy - bonus, a))
        if not acs:
            continue
        acs.sort(key=lambda row: row[0])
        if apply_air(trial, inst, parcel, acs[0][1]):
            cand = trial
            placed += 1
    if placed == 0:
        return None
    H = getattr(ctx, "H", None)
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0)
    if scheduler_feasible(cand, inst, phys, H, slack):
        return cand
    ctx.schedule_rejects = int(getattr(ctx, "schedule_rejects", 0) or 0) + 1
    return None


def try_integrated_cross(plan, ctx, budget, stats, kind: int):
    """Evaluate one floor-legal cross move. No meeting under the floor means no evaluation."""
    from .alns import eval_counted
    cand = propose_integrated(plan, ctx, kind)
    if cand is None:
        stats.aud("CROSS_INSERT", "no_floor")
        return None, None
    if budget is None or budget.evals_left() <= 0:
        return None, None
    ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "CROSS_INSERT", stats, budget)
    stats.aud("CROSS_INSERT", "calls")
    if ev is None:
        return None, None
    if not ev.feasible:
        stats.aud("CROSS_INSERT", "infeasible")
        return None, None
    stats.aud("CROSS_INSERT", "feasible")
    return cand, ev
