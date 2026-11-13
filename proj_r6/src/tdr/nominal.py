"""名义计划：全地送初解 + 空送转换启动 + 固定 ALNS（不读取任何隐藏故障信息）."""
from __future__ import annotations

import math
import random
import time

from .alns import (Budget, SearchStats, SolveContext, SolveResult, coordinate_polish,
                   eval_counted, optimize)
from .config import AlgorithmConfig, PhysicalConfig
from .data import Instance
from .evaluate import evaluate_plan
from .plan import Plan, ground_only_plan
from .schedule import initial_state


# ---------------------------------------------------------------------------
def _block_saving(inst: Instance, plan: Plan, truck: str, s: int, L: int) -> float:
    route = plan.routes[truck]
    depot = (inst.depot_x, inst.depot_y)
    prev = depot if s == 0 else _pos(inst, plan, route[s - 1])
    nxt = depot if s + L >= len(route) else _pos(inst, plan, route[s + L])
    inside = 0.0
    cur = prev
    for vid in route[s:s + L]:
        p = _pos(inst, plan, vid)
        inside += math.hypot(p[0] - cur[0], p[1] - cur[1])
        cur = p
    inside += math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
    return inside - math.hypot(nxt[0] - prev[0], nxt[1] - prev[1])


def _pos(inst: Instance, plan: Plan, vid: int) -> tuple[float, float]:
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


def try_convert(plan: Plan, inst: Instance, phys: PhysicalConfig, truck: str, s: int, L: int,
                lam: float = 0.5) -> Plan | None:
    route = plan.routes.get(truck, [])
    if s + L > len(route):
        return None
    block = route[s:s + L]
    for vid in block:
        v = plan.visits[vid]
        if not v.ground:
            return None
        for so in plan.sorties.values():
            if so.launch_vid == vid or so.rec_vid == vid:
                return None
    parcels: list[str] = []
    for vid in block:
        parcels.extend(plan.visits[vid].ground)
    if sum(inst.parcel_mass[p] for p in parcels) > phys.drone_payload_limit_kg + 1e-9:
        return None
    cand = plan.clone()
    prev_vid = route[s - 1] if s > 0 else None
    next_vid = route[s + L] if s + L < len(route) else None
    for vid in block:
        cand.remove_visit(vid)
    if next_vid is None:
        last_cust = plan.visits[block[-1]].customer
        rv = cand.add_visit(truck, last_cust, ground=[])
        next_vid = rv.vid
    from .config import home_drones
    drones_ = home_drones(truck)
    launch_vid = prev_vid
    mode = "ARC"
    new_route = cand.routes[truck]
    if launch_vid is None:
        # 从仓库出发，在仓库后首段弧上放飞
        if not new_route:
            return None
        # P 在仓库 -> launch_vid=None
        pass
    # 无人机航次链可行性
    from .moves import sortie_slot_free
    li = -1 if launch_vid is None else new_route.index(launch_vid)
    ri = new_route.index(next_vid)
    drone = next((d for d in drones_ if sortie_slot_free(cand, d, li, ri)), None)
    if drone is None:
        return None
    cand.add_sortie(drone, truck, launch_vid, mode, lam, parcels, next_vid)
    return cand


def conversion_pass(plan: Plan, inst: Instance, phys: PhysicalConfig, alg: AlgorithmConfig,
                    state, stats: SearchStats, best_ev, budget: Budget, max_eval: int = 120):
    """空送转换启动阶段：按可节省车程排序，逐个完整评价并贪婪接受."""
    from .alns import _better
    improved = True
    evals = 0
    while improved and evals < max_eval:
        improved = False
        cands = []
        for truck in plan.routes:
            route = plan.routes[truck]
            for s in range(len(route)):
                for L in (1, 2, 3):
                    if s + L > len(route):
                        continue
                    if not all(plan.visits[v].ground for v in route[s:s + L]):
                        continue
                    sav = _block_saving(inst, plan, truck, s, L)
                    if sav <= 0:
                        continue
                    cands.append((sav, truck, s, L))
        cands.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
        for sav, truck, s, L in cands[:40]:
            if evals >= max_eval or stats.eval_requests >= budget.eval_limit:
                break
            if budget.evals_left() <= 0:
                break
            cand = try_convert(plan, inst, phys, truck, s, L, 0.5)
            if cand is None:
                continue
            evals += 1
            ev = eval_counted(cand, inst, phys, state, None, "NOMINAL_AIR_BASE", stats, budget)
            if ev is None:
                break
            if ev.feasible and _better(ev, best_ev, alg):
                # 对最好结构做 5 个基础 λ 起点
                from .alns import _geometry_evaluate
                ctx = SolveContext(inst, phys, alg, state, None, "nominal")
                ev2, p2 = _geometry_evaluate(cand, ctx, stats, "NOMINAL_AIR_BASE", budget)
                if ev2 is not None and _better(ev2, best_ev, alg):
                    ev, cand = ev2, p2
                plan = cand
                best_ev = ev
                improved = True
                break
    return plan, best_ev, evals


def descent_pass(plan: Plan, inst: Instance, phys: PhysicalConfig, alg: AlgorithmConfig,
                 state, stats: SearchStats, best_ev, budget: Budget, max_eval: int = 450,
                 allow_cross: bool = False):
    """第二轮：成本驱动的"转空送"下降（取代旧的按节省里程排序的块转换）.

    每个地送客户按"卡车去掉它能省的绕行"从大到小依次尝试：取该票最好的 ≤3 个空送候选
    （并入已有航次 / 新建航次，代理分已含同步等待与电费），各用**完整评价的真实成本**判断，
    更便宜才接受。只有新建航次被接受时才补评另外 4 个 λ 起点（省评价）。
    整个阶段的评价次数计入名义总预算。"""
    from .alns import _better, _geometry_evaluate, SolveContext, _nominal_cross_intact
    from .moves import air_candidates, apply_air, remove_parcel
    ctx = SolveContext(inst, phys, alg, state, None, "nominal")
    spent = 0
    depot = (inst.depot_x, inst.depot_y)

    def room() -> bool:
        return spent < max_eval and budget.evals_left() > 0

    improved_pass = True
    while improved_pass and room():
        improved_pass = False
        scored = []
        for tk, route in plan.routes.items():
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
                scored.append((det, v.ground[0]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for det, p in scored:
            if not room():
                break
            if not any(p in v.ground for v in plan.visits.values()):
                continue                      # 已被前面的接受改走
            base = plan.clone()
            remove_parcel(base, p)
            if allow_cross and getattr(state, "nominal_cross", False):
                _all = air_candidates(base, inst, phys, p, max_new=3, state=state)
                acs = [x for x in _all if not x.cross][:3] + [x for x in _all if x.cross][:2]
            else:
                acs = air_candidates(base, inst, phys, p, max_new=3, state=None)[:3]
            win = None
            for ac in acs:
                if not room():
                    break
                cand = base.clone()
                if not apply_air(cand, inst, p, ac):
                    continue
                ev = eval_counted(cand, inst, phys, state, None, "NOMINAL_AIR_BASE", stats, budget)
                spent += 1
                if ev is None:
                    break
                if ev.feasible and _better(ev, best_ev, alg) and _nominal_cross_intact(cand, ev, ctx) \
                        and (win is None or _better(ev, win[1], alg)):
                    win = (cand, ev, ac)
            if win is None:
                continue
            cand, ev, ac = win
            if ac.kind == "NEW" and budget.evals_left() > 0:
                before = stats.eval_requests
                ev2, p2 = _geometry_evaluate(cand, ctx, stats, "NOMINAL_AIR_BASE", budget)
                spent += stats.eval_requests - before
                if ev2 is not None and _better(ev2, ev, alg) and _nominal_cross_intact(p2, ev2, ctx):
                    cand, ev = p2, ev2
            plan, best_ev = cand, ev
            improved_pass = True
    return plan, best_ev, spent


def phase1_allows_cross(cross_launch: bool, alg) -> bool:
    """阶段1 是否允许跨车。S 的 cross_launch 为假，这里恒假。

    默认关：阶段1 与 S 相同，跨车只在阶段2。x_cross_from_start 为真时，X 从构造阶段就开始跨车。
    """
    return bool(cross_launch and getattr(alg, "x_cross_from_start", False))


def _build_two_phase(inst, phys, alg, rngs, eval_budget, variant, n_used, cross_launch, b,
                     makespan_cap=None):
    """两阶段名义。

    阶段1（预算 B−b）：默认与 S 相同的同车流程。x_cross_from_start 且本次是 X 时，
    阶段1 的构造、下降和 ALNS 也允许跨车放飞/回收，并走 CROSS_CONVERT。稳健性检查跟着开。
    阶段2（剩余预算，X 再留出互换用的评价）：S 仍同车；X 继续跨车。总预算仍是 B。
    阶段1 搜索里不设完工上限，否则全地送初解已经长过 S，一步都走不动。
    发布时仍要求完工时刻不超过 S。
    """
    t0 = time.perf_counter()
    B = eval_budget if eval_budget is not None else alg.nominal_eval_budget
    phase1_cross = phase1_allows_cross(cross_launch, alg)
    r1 = build_nominal(inst, phys, alg, rngs, eval_budget=B - b, variant=variant, n_used=n_used,
                       cross_launch=phase1_cross, two_phase_b=0)
    if r1.plan is None or r1.evaluation is None or not r1.evaluation.feasible:
        return r1
    used1 = r1.stats.eval_requests
    state = initial_state(inst, phys)
    state.nominal_cross = bool(cross_launch)
    stats2 = SearchStats()
    # 互换回收车的评价从阶段2的同一份预算里留出，发布时再花。S 不留。
    hold = 0
    if cross_launch and getattr(alg, "x_cross_exchange", False):
        from .cross_nominal import EXCHANGE_EVALS
        hold = EXCHANGE_EVALS
    budget2 = Budget(max(1, B - used1 - hold), None)
    # 上限至少抬到阶段1完工时刻。S 的阶段2常常把 makespan 再压短，若直接用 S 的完工时刻，
    # 阶段1解本身已经越限，跨车移动会被全部拒绝。这里只禁止「比共享阶段1更长」。
    p1_finish = None
    if r1.evaluation.timeline and r1.evaluation.timeline.truck_finish:
        p1_finish = max(r1.evaluation.timeline.truck_finish.values())
    cap = None
    if cross_launch and (makespan_cap is not None or getattr(alg, "x_cross_hs_cap", False)):
        cap = p1_finish if makespan_cap is None else max(makespan_cap, p1_finish or makespan_cap)
    ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state, H=None, mode="nominal", rngs=rngs,
                       makespan_cap=cap)
    res = optimize(r1.plan, ctx, budget2, variant=variant, stats=stats2)
    best_plan, best_ev = r1.plan, r1.evaluation
    from .alns import _better, _nominal_cross_intact, _within_makespan_cap
    if res.plan is not None and res.evaluation is not None and res.evaluation.feasible \
            and _better(res.evaluation, best_ev, alg) \
            and _within_makespan_cap(res.evaluation, ctx) \
            and _nominal_cross_intact(res.plan, res.evaluation, ctx):
        best_plan, best_ev = res.plan, res.evaluation
    stats2.eval_requests = used1 + stats2.eval_requests
    stats2.wall_s = time.perf_counter() - t0
    stats2.counts = dict(res.stats.counts)
    stats2.counts["exchange_hold"] = hold
    stats2.counts["phase1_cross"] = phase1_cross
    stats2.counts["phase1_evals"] = used1
    stats2.counts["phase1_cost"] = r1.evaluation.cost
    stats2.counts["makespan_cap_effective"] = cap
    stats2.counts["phase1_makespan"] = p1_finish
    stats2.counts["phase1_audit"] = r1.stats.counts.get("audit")
    stats2.stop_reason = res.stats.stop_reason
    return SolveResult(best_plan, best_ev, "FEASIBLE_LIMIT", stats2)


def build_nominal(inst: Instance, phys: PhysicalConfig, alg: AlgorithmConfig,
                  rngs: dict[str, random.Random], eval_budget: int | None = None,
                  variant: str = "full", n_used: int | None = None,
                  cross_launch: bool = False, two_phase_b: int | None = None,
                  makespan_cap: float | None = None) -> SolveResult:
    if two_phase_b is None:
        two_phase_b = getattr(alg, "nominal_two_phase_b", None)
    if two_phase_b:
        return _build_two_phase(inst, phys, alg, rngs, eval_budget, variant, n_used, cross_launch,
                                two_phase_b, makespan_cap=makespan_cap if cross_launch else None)
    t0 = time.perf_counter()
    state = initial_state(inst, phys)
    state.nominal_cross = bool(cross_launch)     # 第六轮：True=X（名义阶段允许跨车航次）；False=S（行为与之前完全一致）
    stats = SearchStats()
    budget = Budget(eval_budget if eval_budget is not None else alg.nominal_eval_budget, None)
    plan = ground_only_plan(inst, n_used or phys.truck_count, phys.truck_count)
    ev = eval_counted(plan, inst, phys, state, None, "NOMINAL_GROUND", stats, budget)
    if ev is None or not ev.feasible:
        return SolveResult(plan, ev, "INVALID_INPUT", stats)
    best_plan, best_ev = plan.clone(), ev
    ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state, H=None, mode="nominal",
                       rngs=rngs)
    if alg.nominal_two_start and variant == "full" and budget.eval_limit is not None \
            and budget.eval_limit >= 600:
        from .alns import _better, _nominal_cross_intact
        total = budget.eval_limit
        pA, eA, nA = descent_pass(plan.clone(), inst, phys, alg, state, stats, best_ev, budget,
                                  max_eval=alg.nominal_descent_eval_budget,
                                  allow_cross=bool(getattr(state, "nominal_cross", False)))
        pB, eB, nB = conversion_pass(plan.clone(), inst, phys, alg, state, stats, best_ev, budget,
                                     max_eval=alg.nominal_air_bootstrap_eval_budget)
        best = None
        for p0, e0 in ((pA, eA), (pB, eB)):
            if e0 is None or not e0.feasible:
                continue
            budget.eval_limit = min(total, budget.used + alg.nominal_start_slice)
            r0 = optimize(p0, ctx, budget, variant=variant, stats=stats)
            budget.eval_limit = total
            if r0.plan is not None and r0.evaluation is not None and r0.evaluation.feasible:
                if best is None or _better(r0.evaluation, best[1], alg):
                    best = (r0.plan, r0.evaluation)
        if best is not None:
            best_plan, best_ev = best
        n_conv = nA + nB
        reserve = int(alg.nominal_final_descent_frac * total) if variant == "full" else 0
        budget.eval_limit = total - reserve
        res = optimize(best_plan, ctx, budget, variant=variant, stats=stats)
        budget.eval_limit = total
        if res.plan is not None and res.evaluation is not None and res.evaluation.feasible:
            best_plan, best_ev = res.plan, res.evaluation
        if reserve > 0 and budget.evals_left() > 0:
            # 第三轮：ALNS 后收尾的成本驱动下降（诊断：贪心单步转空送仍能再降 1–1.4% 成本）
            p4, e4, n4 = descent_pass(best_plan.clone(), inst, phys, alg, state, stats, best_ev, budget,
                                      max_eval=reserve, allow_cross=True)
            n_conv += n4
            if e4 is not None and e4.feasible and _better(e4, best_ev, alg) \
                    and _nominal_cross_intact(p4, e4, ctx):
                best_plan, best_ev = p4, e4
        if variant != "no_coordinate_polish" and budget.evals_left() > 0:
            p3, e3 = coordinate_polish(best_plan, ctx, stats, budget)
            if p3 is not None and e3 is not None and _better(e3, best_ev, alg) \
                    and _nominal_cross_intact(p3, e3, ctx):
                best_plan, best_ev = p3, e3
        stats.stop_reason = res.stats.stop_reason or "BUDGET"
        stats.wall_s = time.perf_counter() - t0
        stats.counts = dict(res.stats.counts)
        stats.counts["n_conversion_evals"] = n_conv
        return SolveResult(best_plan, best_ev, "FEASIBLE_LIMIT", stats)
    # 转换启动
    if alg.nominal_descent:
        plan2, ev2, n_conv = descent_pass(plan.clone(), inst, phys, alg, state, stats, best_ev, budget,
                                          max_eval=alg.nominal_descent_eval_budget,
                                          allow_cross=bool(getattr(state, "nominal_cross", False)))
    else:
        plan2, ev2, n_conv = conversion_pass(plan.clone(), inst, phys, alg, state, stats, best_ev, budget,
                                             max_eval=alg.nominal_air_bootstrap_eval_budget)
    if ev2 is not None and ev2.feasible:
        best_plan, best_ev = plan2, ev2
    # ALNS
    ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state, H=None, mode="nominal",
                       rngs=rngs)
    res = optimize(best_plan, ctx, budget, variant=variant, stats=stats)
    if res.plan is not None and res.evaluation is not None and res.evaluation.feasible:
        best_plan, best_ev = res.plan, res.evaluation
    # 启动阶段结束：一次坐标细化
    if variant != "no_coordinate_polish" and budget.evals_left() > 0:
        p3, e3 = coordinate_polish(best_plan, ctx, stats, budget)
        if p3 is not None and e3 is not None:
            from .alns import _better, _nominal_cross_intact
            if _better(e3, best_ev, alg) and _nominal_cross_intact(p3, e3, ctx):
                best_plan, best_ev = p3, e3
    stats.stop_reason = res.stats.stop_reason or "BUDGET"
    stats.wall_s = time.perf_counter() - t0
    stats.counts = dict(res.stats.counts)
    stats.counts.update({k: v for k, v in res.stats.counts.items() if k not in stats.counts})
    stats.counts["n_conversion_evals"] = n_conv
    return SolveResult(best_plan, best_ev, "FEASIBLE_LIMIT", stats)
