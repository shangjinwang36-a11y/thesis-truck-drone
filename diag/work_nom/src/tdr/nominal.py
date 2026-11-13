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
    drone = f"d{int(truck[1:])}"
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
    if not sortie_slot_free(cand, drone, li, ri):
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


def build_nominal(inst: Instance, phys: PhysicalConfig, alg: AlgorithmConfig,
                  rngs: dict[str, random.Random], eval_budget: int | None = None,
                  variant: str = "full") -> SolveResult:
    t0 = time.perf_counter()
    state = initial_state(inst, phys)
    stats = SearchStats()
    budget = Budget(eval_budget if eval_budget is not None else alg.nominal_eval_budget, None)
    plan = ground_only_plan(inst)
    ev = eval_counted(plan, inst, phys, state, None, "NOMINAL_GROUND", stats, budget)
    if ev is None or not ev.feasible:
        return SolveResult(plan, ev, "INVALID_INPUT", stats)
    best_plan, best_ev = plan.clone(), ev
    # 转换启动
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
            from .alns import _better
            if _better(e3, best_ev, alg):
                best_plan, best_ev = p3, e3
    stats.stop_reason = res.stats.stop_reason or "BUDGET"
    stats.wall_s = time.perf_counter() - t0
    stats.counts = dict(res.stats.counts)
    stats.counts.update({k: v for k, v in res.stats.counts.items() if k not in stats.counts})
    stats.counts["n_conversion_evals"] = n_conv
    return SolveResult(best_plan, best_ev, "FEASIBLE_LIMIT", stats)
