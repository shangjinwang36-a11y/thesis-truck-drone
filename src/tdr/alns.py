"""唯一主算法：事件触发的车机协同恢复 ALNS 数学启发式（tdr_alns_v61）.

固定组件：
  * 6 个移除算子 + 2 个修复算子（代理分数排序）
  * 普通自适应权重（每 25 轮）
  * 模拟退火接受（真实 C_res 与 z）
  * 连续放飞位置搜索（5 个基础起点 + 坐标步长细化）
  * 局部事件重排（最多 6 个相邻未执行事件；枚举实现，见 local_reorder.py）
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .config import AlgorithmConfig, PhysicalConfig
from .data import Instance
from .evaluate import Evaluation, evaluate_plan
from .moves import (air_candidates, apply_air, apply_ground, drone_of_truck, ground_candidates,
                    remove_parcel, remove_sortie_closure)
from .plan import Plan, Sortie
from .schedule import StartState


# ---------------------------------------------------------------------------
@dataclass
class SearchStats:
    eval_requests: int = 0
    eval_by_reason: dict[str, int] = field(default_factory=dict)
    rounds: int = 0
    iterations: int = 0
    best_trace: list[tuple[int, float, float]] = field(default_factory=list)
    destroy_used: dict[str, int] = field(default_factory=dict)
    repair_used: dict[str, int] = field(default_factory=dict)
    destroy_fallback: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    first_feasible_s: float | None = None
    wall_s: float = 0.0
    cover_trucks: set[str] = field(default_factory=set)
    cover_customers: set[str] = field(default_factory=set)
    cover_subsets: set[int] = field(default_factory=set)
    lp_calls: int = 0
    last_improvement_eval: int = 0

    def add_eval(self, reason: str) -> None:
        self.eval_requests += 1
        self.eval_by_reason[reason] = self.eval_by_reason.get(reason, 0) + 1


class Budget:
    """唯一预算对象：所有完整评价（含初始化、几何、坐标、MILP 回验、核验）统一扣账."""

    def __init__(self, eval_limit: int | None, wall_limit: float | None,
                 start: float | None = None, reserve: float = 0.0, used: int = 0):
        self.eval_limit = eval_limit
        self.wall_limit = wall_limit
        self.start = start if start is not None else time.perf_counter()
        self.reserve = reserve
        self.used = used

    def take(self, n: int = 1) -> bool:
        if self.eval_limit is not None and self.used + n > self.eval_limit:
            return False
        if self.wall_limit is not None and self.time_left() <= 0:
            return False
        self.used += n
        return True

    def exhausted(self) -> bool:
        return self.evals_left() <= 0 or self.time_left() <= 0

    def evals_left(self) -> float:
        if self.eval_limit is None:
            return float("inf")
        return float(max(0, self.eval_limit - self.used))

    def time_left(self) -> float:
        if self.wall_limit is None:
            return float("inf")
        return self.wall_limit - self.reserve - (time.perf_counter() - self.start)


class EvalCounter:
    def __init__(self, stats: SearchStats, budget: Budget):
        self.stats = stats
        self.budget = budget

    def take(self, reason: str) -> bool:
        if self.stats.eval_requests >= self.budget.eval_limit if self.budget.eval_limit is not None else False:
            return False
        self.stats.add_eval(reason)
        return True


def _better(a: Evaluation, b: Evaluation | None, alg: AlgorithmConfig) -> bool:
    if b is None or not b.feasible:
        return a.feasible
    if not a.feasible:
        return False
    if a.cost < b.cost - alg.cost_tolerance_yuan:
        return True
    if abs(a.cost - b.cost) <= alg.cost_tolerance_yuan:
        return a.z < b.z - alg.time_tolerance_seconds
    return False


def eval_counted(plan: Plan, inst: Instance, phys: PhysicalConfig, state: StartState,
                 H: float | None, reason: str, stats: SearchStats, budget: Budget,
                 allow_wait_repair: bool = True) -> Evaluation | None:
    """唯一完整评价入口：由统一预算对象扣账，进入即计 1 次."""
    ev = evaluate_plan(plan, inst, phys, state, H, reason, budget=budget,
                       allow_wait_repair=allow_wait_repair)
    if ev.status == "BUDGET_EXHAUSTED":
        return None
    stats.eval_by_reason[reason] = stats.eval_by_reason.get(reason, 0) + 1
    stats.eval_requests = budget.used
    stats.lp_calls += int(ev.counts.get("lp_calls", 0)) if ev.counts else 0
    return ev


# ---------------------------------------------------------------------------
# 移除算子
# ---------------------------------------------------------------------------
def adjustable_parcels(plan: Plan, inst: Instance) -> list[str]:
    out = []
    for v in plan.visits.values():
        out.extend(v.ground)
    for s in plan.sorties.values():
        if s.started:
            continue
        out.extend(s.air)
    return sorted(set(out))


def destroy(plan: Plan, op: str, q: int, rng: random.Random, inst: Instance,
            ev: Evaluation | None, ctx: "SolveContext") -> tuple[list[str], list[str]]:
    """返回 (释放的包裹, 使用的算子名).

    冻结边界：正在飞行的残段（started）及其机上货物不可被移除，只能调整其规则允许的
    未来部分（由恢复构造负责）。任何会触及冻结票的移除都整体拒绝。
    """
    frozen: set[str] = set()
    for so in plan.sorties.values():
        if so.started:
            frozen.update(so.air)
            frozen.update(so.handover)
    adj = [p for p in adjustable_parcels(plan, inst) if p not in frozen]
    if not adj:
        return [], op
    q = min(q, len(adj))
    seeds: list[str] = []
    used = op
    if not adj:
        return [], op
    if op == "RANDOM_DEPENDENCY":
        seeds = rng.sample(adj, min(q, len(adj)))
    elif op == "AFFECTED_SORTIE":
        cand = [s for s in plan.sorties.values() if not s.started]
        if ctx.affected_drones:
            cand = [s for s in cand if s.drone in ctx.affected_drones] or cand
        if cand:
            s = sorted(cand, key=lambda x: (x.drone, x.sid))[0]
            seeds = list(s.air)
        else:
            used = "RANDOM_DEPENDENCY"
    elif op == "RENDEZVOUS_RESOURCE":
        if ev is not None and ev.timeline:
            waits = ev.timeline.wait_by_sortie
            if waits:
                adj_sids = [sid for sid in waits
                            if sid in plan.sorties and not plan.sorties[sid].started]
                if adj_sids:
                    sid = max(adj_sids, key=lambda x: waits[x])
                    s = plan.sorties.get(sid)
                    if s is not None:
                        seeds = list(s.air)
        else:
            used = "RANDOM_DEPENDENCY"
    elif op == "ENERGY_CHAIN":
        if ev is not None and ev.timeline and ev.timeline.drone_energy:
            best = None
            for s in plan.sorties.values():
                if s.started:
                    continue
                stages = ev.timeline.drone_stages.get(s.drone, [])
                for i, st in enumerate(stages):
                    if st.kind == "R" and st.sid == s.sid:
                        e = ev.timeline.drone_energy[s.drone][i + 1]
                        if best is None or e < best[0]:
                            best = (e, s)
            if best is not None:
                seeds = list(best[1].air)
        else:
            used = "RANDOM_DEPENDENCY"
    elif op == "SUPPORT_VISIT":
        seeds = _support_seeds(plan, inst)
        if not seeds:
            used = "RANDOM_DEPENDENCY"
    elif op == "GROUND_TO_AIR":
        # 第二轮：把"卡车绕行最大"的地送票放出来，让修复器有机会改成空送
        scored = []
        depot = (inst.depot_x, inst.depot_y)
        for tk, route in plan.routes.items():
            for i, vid in enumerate(route):
                v = plan.visits[vid]
                if len(v.ground) != 1 or v.ground[0] in frozen:
                    continue
                if any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values()):
                    continue
                cc = inst.customer(v.customer)
                prv = depot if i == 0 else (inst.customer(plan.visits[route[i - 1]].customer).x,
                                            inst.customer(plan.visits[route[i - 1]].customer).y)
                nxt = depot if i + 1 == len(route) else (inst.customer(plan.visits[route[i + 1]].customer).x,
                                                         inst.customer(plan.visits[route[i + 1]].customer).y)
                det = (math.hypot(cc.x - prv[0], cc.y - prv[1]) + math.hypot(nxt[0] - cc.x, nxt[1] - cc.y)
                       - math.hypot(nxt[0] - prv[0], nxt[1] - prv[1]))
                scored.append((det, v.ground[0]))
        scored.sort(reverse=True)
        pool_ = [p for _, p in scored[:max(2 * q, 4)]]
        if pool_:
            seeds = rng.sample(pool_, min(q, len(pool_)))
        else:
            used = "RANDOM_DEPENDENCY"
    elif op == "SORTIE_REGROUP":
        cand = [s for s in plan.sorties.values() if not s.started and s.launch_vid is not None]
        if cand:
            s = cand[rng.randrange(len(cand))]
            seeds = list(s.air)
            seeds += [p for v in plan.visits.values() if v.truck == s.truck for p in v.ground][:2]
        else:
            used = "RANDOM_DEPENDENCY"
    seeds = [p for p in seeds if p not in frozen]
    if not seeds:
        used = "RANDOM_DEPENDENCY"
        seeds = rng.sample(adj, min(q, len(adj)))
    # 依赖闭包：同航次一并释放
    freed: list[str] = []
    done_sorties = set()
    for p in seeds:
        loc = None
        for s in plan.sorties.values():
            if p in s.air:
                loc = s
                break
        if loc is not None:
            if loc.sid in done_sorties:
                continue
            done_sorties.add(loc.sid)
            remove_sortie_closure(plan, loc.sid, freed)
        else:
            remove_parcel(plan, p, freed)
    # 补足 q
    adj2 = [p for p in adjustable_parcels(plan, inst) if p not in frozen]
    need = q - len(set(freed))
    if need > 0 and adj2:
        extra = rng.sample(adj2, min(need, len(adj2)))
        for p in extra:
            remove_parcel(plan, p, freed)
    if any(p in frozen for p in freed):
        return [], op
    return sorted(set(freed)), used


def _support_seeds(plan: Plan, inst: Instance) -> list[str]:
    """D5：选择真实支撑 P/R 的纯支援访问（无地送但被放飞/回收引用），按绕行降序."""
    best = None
    for v in plan.visits.values():
        if v.ground:
            continue
        used_by = any(s.launch_vid == v.vid or s.rec_vid == v.vid for s in plan.sorties.values())
        if not used_by:
            continue
        route = plan.routes[v.truck]
        i = route.index(v.vid)
        depot = (inst.depot_x, inst.depot_y)
        prev = depot if i == 0 else (inst.customer(plan.visits[route[i - 1]].customer).x,
                                     inst.customer(plan.visits[route[i - 1]].customer).y)
        nxt = depot if i + 1 == len(route) else (inst.customer(plan.visits[route[i + 1]].customer).x,
                                                 inst.customer(plan.visits[route[i + 1]].customer).y)
        c = inst.customer(v.customer)
        det = (math.hypot(c.x - prev[0], c.y - prev[1]) + math.hypot(nxt[0] - c.x, nxt[1] - c.y)
               - math.hypot(nxt[0] - prev[0], nxt[1] - prev[1]))
        if best is None or det > best[0]:
            best = (det, v.vid)
    if best is None:
        return []
    vid = best[1]
    out: list[str] = []
    for s in plan.sorties.values():
        if (s.rec_vid == vid or s.launch_vid == vid) and not s.started:
            out.extend(s.air)
    return out


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------
@dataclass
class SolveContext:
    inst: Instance
    phys: PhysicalConfig
    alg: AlgorithmConfig
    state: StartState
    H: float | None = None
    mode: str = "nominal"
    affected_drones: set[str] = field(default_factory=set)
    affected_sorties: set[int] = field(default_factory=set)
    ground_required: set[str] = field(default_factory=set)
    fixed_parcels: set[str] = field(default_factory=set)
    catalog: object | None = None
    frag_sid: int | None = None
    replan_index: int = 0
    rngs: dict[str, random.Random] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
@dataclass
class SolveResult:
    plan: Plan | None
    evaluation: Evaluation | None
    status: str
    stats: SearchStats
    algorithm_id: str = "tdr_alns_v61"


def prefix_fixed_cost(state, phys) -> float:
    """快照之前已发生、对所有候选相同的成本常量 C_prefix_fixed（里程费、已完成司机工时、净车充与补电）."""
    if state is None or state.t0 <= 0:
        return 0.0
    driver_s = 0.0
    for k in state.truck_start_pos:
        driver_s += state.truck_done[k] if k in state.truck_done else state.t0
    return (phys.c_km * state.prefix_distance_m / 1000.0 + phys.wage_per_s * driver_s
            + phys.cost_vehicle_kwh * phys.slot_efficiency * state.prefix_ac_kwh
            + phys.cost_depot_kwh * state.prefix_refill_kwh)


def optimize(plan: Plan, ctx: SolveContext, budget: Budget, variant: str = "full",
             stats: SearchStats | None = None, init_ev: Evaluation | None = None) -> SolveResult:
    """ALNS 主循环.

    init_ev：调用方已经完整评价过起始解时传入（恢复阶段由 initial_recovery 评价，
    计入"初始化预算"），这里不再重复评价，也不占主循环预算。
    此时 budget 是**主循环预算**（S/X 相同），SA 退火进度只由主循环进度决定。
    """
    inst, phys, alg = ctx.inst, ctx.phys, ctx.alg
    stats = stats or SearchStats()
    t_start = time.perf_counter()
    rng_op = ctx.rngs.get("operator", random.Random(1))
    rng_des = ctx.rngs.get("destroy", random.Random(2))
    rng_acc = ctx.rngs.get("accept", random.Random(3))
    # 初始评价（若外部已评价过则跳过）
    if init_ev is not None:
        cur_ev = init_ev
    elif budget.used == 0:
        cur_ev = eval_counted(plan, inst, phys, ctx.state, ctx.H,
                              "RECOVERY_INITIAL_BASE" if ctx.mode == "recovery" else "NOMINAL_GROUND",
                              stats, budget)
        if cur_ev is None:
            return SolveResult(plan, None, "NO_SOLUTION_LIMIT", stats)
    else:
        cur_ev = eval_counted(plan, inst, phys, ctx.state, ctx.H, "init", stats, budget)
        if cur_ev is None:
            return SolveResult(plan, None, "NO_SOLUTION_LIMIT", stats)
    if not cur_ev.feasible:
        return SolveResult(plan, cur_ev, "NO_SOLUTION_LIMIT", stats)
    stats.first_feasible_s = time.perf_counter() - t_start
    best_plan = plan.clone()
    best_ev = cur_ev
    stats.best_trace.append((0, best_ev.cost or 0.0, best_ev.z or 0.0))
    cur_plan = plan.clone()
    # 第四轮 M3：退火温度尺度只用“后缀成本”(全班成本扣除快照前已发生的常量 C_prefix_fixed)，
    # 规范 7.x：不得用随故障时刻增长的历史常数放大退火温度。
    C_scale = max((cur_ev.cost or 1.0) - prefix_fixed_cost(ctx.state, phys), 1.0)
    T0 = -alg.sa_initial_worse_fraction * C_scale / math.log(0.5)
    destroy_ops = list(alg.destroy_operators)
    repair_ops = list(alg.repair_operators)
    if alg.air_promote_ops and alg.operator_selector != "qlearn":
        destroy_ops.append("GROUND_TO_AIR")
        repair_ops.append("AIR_FIRST")
    w_d = {k: 1.0 for k in destroy_ops}
    w_r = {k: 1.0 for k in repair_ops}
    n_d = {k: 0 for k in destroy_ops}
    n_r = {k: 0 for k in repair_ops}
    s_d = {k: 0.0 for k in destroy_ops}
    s_r = {k: 0.0 for k in repair_ops}
    stagnation = 0
    # 变体 A：学习式选择器（None = 基线轮盘赌，行为完全不变）
    from .selector import QSelector, failure_type, get_selector
    sel = get_selector(alg, destroy_ops, repair_ops) if ctx.mode == "recovery" else None
    pend: tuple[str, int, float] | None = None       # 上一轮 (状态, 动作, 奖励)，下一轮开头再更新 Q
    frag0 = plan.sorties.get(ctx.frag_sid) if ctx.frag_sid is not None else None
    ftype = failure_type(len(ctx.ground_required), bool(frag0 is not None and frag0.air))
    last_mip_round = -10**9
    window_cursor = 0
    stats.stop_reason = "BUDGET"
    while True:
        if budget.evals_left() <= 0:
            stats.stop_reason = "EVAL_LIMIT"
            break
        if budget.wall_limit is not None and budget.time_left() <= 0:
            stats.stop_reason = "WALLCLOCK"
            break
        if stats.iterations >= alg.max_search_rounds:
            stats.stop_reason = "MAX_ROUNDS"
            break
        stats.iterations += 1
        stats.rounds += 1
        # 选算子
        if sel is None:
            op = _roulette(w_d, rng_op)
            rep = _roulette(w_r, rng_op)
        else:
            skey = QSelector.key(stagnation, _progress(stats, budget), ftype)
            if pend is not None:
                sel.update(pend[0], pend[1], pend[2], skey)
                pend = None
            op, rep, sact = sel.choose(skey, rng_op)
        n_d[op] += 1
        n_r[rep] += 1
        stats.destroy_used[op] = stats.destroy_used.get(op, 0) + 1
        stats.repair_used[rep] = stats.repair_used.get(rep, 0) + 1
        adj = adjustable_parcels(cur_plan, inst)
        if not adj:
            break
        r = rng_des.uniform(alg.destroy_fraction_min, alg.destroy_fraction_max)
        q = max(1, min(len(adj), math.ceil(r * len(adj))))
        trial = cur_plan.clone()
        freed, used_op = destroy(trial, op, q, rng_des, inst, cur_ev, ctx)
        if used_op != op:
            stats.destroy_fallback[op] = stats.destroy_fallback.get(op, 0) + 1
        if not freed:
            _reward(s_d, op, 0.0)
            _reward(s_r, rep, 0.0)
            if sel is not None:
                pend = (skey, sact, 0.0)
            continue
        if rep == "GREEDY_PROXY":
            from .moves import repair_greedy as _rep
        elif rep == "AIR_FIRST":
            from .moves import repair_air_first as _rep
        else:
            from .moves import repair_regret2 as _rep
        trial, leftover = _rep(trial, inst, phys, freed, rng_acc,
                               forbid_air=ctx.ground_required,
                               min_pos=ctx.state.truck_min_insert or None, state=ctx.state)
        if leftover:
            _reward(s_d, op, 0.0)
            _reward(s_r, rep, 0.0)
            if sel is not None:
                pend = (skey, sact, 0.0)
            stagnation += 1
            _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg)
            continue
        # 基础几何评价（5 个 λ 起点）
        new_sortie = any(sid >= cur_plan.next_sid for sid in trial.sorties)
        cand_ev, cand_plan = _geometry_evaluate(
            trial, ctx, stats, "ALNS_BASE", budget,
            multistart=(new_sortie or not alg.geometry_new_sortie_only))
        if cand_ev is None:
            _reward(s_d, op, 0.0)
            _reward(s_r, rep, 0.0)
            if sel is not None:
                pend = (skey, sact, 0.0)
            stagnation += 1
            _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg)
            continue
        reward = 0.0
        accepted = False
        if _better(cand_ev, best_ev, alg):
            best_ev, best_plan = cand_ev, cand_plan.clone()
            reward = alg.score_global_best
            accepted = True
            stagnation = 0
            stats.last_improvement_eval = stats.eval_requests
            stats.best_trace.append((stats.eval_requests, best_ev.cost or 0.0, best_ev.z or 0.0))
        elif _better(cand_ev, cur_ev, alg):
            reward = alg.score_current_improvement
            accepted = True
            stagnation = 0
        else:
            # SA
            if cand_ev.feasible:
                dc = (cand_ev.cost or 0.0) - (cur_ev.cost or 0.0)
                if abs(dc) <= alg.cost_tolerance_yuan:
                    accepted = False
                else:
                    progress = _progress(stats, budget)
                    T = T0 * (alg.sa_final_temperature_ratio ** progress)
                    if T <= 0:
                        p = 0.0
                    else:
                        try:
                            p = math.exp(-dc / T)
                        except OverflowError:
                            p = 0.0
                    if rng_acc.random() < p:
                        accepted = True
                        reward = alg.score_other_accepted
            if not accepted:
                reward = 0.0
                stagnation += 1
        if accepted:
            cur_plan, cur_ev = cand_plan.clone(), cand_ev
        _reward(s_d, op, reward)
        _reward(s_r, rep, reward)
        if sel is not None:
            pend = (skey, sact, reward / alg.score_global_best)
        # 连续位置细化：新最好解，或每 10 轮
        do_polish = variant != "no_coordinate_polish" and (
            (best_ev is cand_ev) or stats.iterations % alg.coordinate_polish_every_alns_iterations == 0)
        if do_polish and budget.evals_left() > 0:
            if alg.coordinate_light:
                p2, e2 = coordinate_polish(cur_plan, ctx, stats, budget, base_ev=cur_ev,
                                           cap=alg.coordinate_light_cap)
            else:
                p2, e2 = coordinate_polish(cur_plan, ctx, stats, budget)
            if e2 is not None and _better(e2, cur_ev, alg):
                cur_plan, cur_ev = p2, e2
                if _better(e2, best_ev, alg):
                    best_ev, best_plan = e2, p2.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 恢复邻域：继续展开受影响残段的接机车/接机点/部分继续（预算允许时）
        if ctx.catalog is not None and stats.iterations % 10 == 0 and budget.evals_left() > 0:
            p_r, e_r = try_recovery_reassign(cur_plan, ctx, budget, stats)
            if p_r is not None and e_r is not None and _better(e_r, cur_ev, alg):
                cur_plan, cur_ev = p_r, e_r
                if _better(e_r, best_ev, alg):
                    best_ev, best_plan = e_r, p_r.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 局部事件重排
        if variant != "no_local_mip" and (stats.iterations % alg.mip_period_rounds == 0
                                          or stagnation >= alg.mip_stagnation_rounds):
            if stats.iterations - last_mip_round >= alg.mip_min_interval_rounds:
                last_mip_round = stats.iterations
                from .local_reorder import try_local_reorder
                p3, e3 = try_local_reorder(best_plan, best_ev, ctx, stats, budget, window_cursor)
                window_cursor += 1
                if p3 is not None and e3 is not None and _better(e3, best_ev, alg):
                    best_ev, best_plan = e3, p3.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg, variant)
    if sel is not None and pend is not None:
        sel.update(pend[0], pend[1], pend[2], None)
    if ctx.catalog is not None:
        stats.cover_trucks = set(getattr(ctx.catalog, "covered_trucks", set()))
        stats.cover_customers = set(getattr(ctx.catalog, "covered_customers", set()))
        stats.cover_subsets = set(getattr(ctx.catalog, "covered_subsets", set()))
    stats.wall_s = time.perf_counter() - t_start
    stats.counts = {"n_eval_requests": stats.eval_requests,
                    "n_alns_iterations": stats.iterations,
                    "n_lp_calls": stats.lp_calls,
                    "n_destroy_fallback": sum(stats.destroy_fallback.values()),
                    "operator_selector": "qlearn" if sel is not None else "roulette",
                    "destroy_used": dict(stats.destroy_used),
                    "repair_used": dict(stats.repair_used),
                    "n_cover_trucks": len(stats.cover_trucks),
                    "n_cover_customers": len(stats.cover_customers),
                    "n_cover_subsets": len(stats.cover_subsets),
                    "cover_trucks": sorted(stats.cover_trucks),
                    "lp_calls": stats.lp_calls,
                    "last_improvement_eval": stats.last_improvement_eval,
                    "best_trace": stats.best_trace}
    final_ev = best_ev
    status = "FEASIBLE_LIMIT"
    if stats.stop_reason in ("EVAL_LIMIT", "WALLCLOCK", "MAX_ROUNDS") and best_ev.feasible:
        status = "FEASIBLE_LIMIT"
    return SolveResult(best_plan, final_ev, status, stats)


def _progress(stats: SearchStats, budget: Budget) -> float:
    if budget.wall_limit is not None:
        used = time.perf_counter() - budget.start
        return max(0.0, min(1.0, used / budget.wall_limit))
    return max(0.0, min(1.0, stats.eval_requests / max(1, budget.eval_limit)))


def _reward(s: dict[str, float], op: str, v: float) -> None:
    s[op] = s.get(op, 0.0) + v


def _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg, variant="full") -> None:
    if variant == "uniform_weights":
        return
    if stats.iterations % alg.weight_segment_iterations != 0:
        return
    for k in w_d:
        if n_d[k] > 0:
            w_d[k] = max(alg.operator_min_weight,
                         (1 - alg.weight_reaction) * w_d[k] + alg.weight_reaction * s_d[k] / n_d[k])
        n_d[k] = 0
        s_d[k] = 0.0
    for k in w_r:
        if n_r[k] > 0:
            w_r[k] = max(alg.operator_min_weight,
                         (1 - alg.weight_reaction) * w_r[k] + alg.weight_reaction * s_r[k] / n_r[k])
        n_r[k] = 0
        s_r[k] = 0.0


def _roulette(w: dict[str, float], rng: random.Random) -> str:
    tot = sum(w.values())
    x = rng.random() * tot
    acc = 0.0
    for k, v in w.items():
        acc += v
        if x <= acc:
            return k
    return list(w)[-1]


# ---------------------------------------------------------------------------
# 连续位置搜索
# ---------------------------------------------------------------------------
def adjustable_launches(plan: Plan) -> list[Sortie]:
    out = []
    for s in plan.sorties.values():
        if s.started or s.mode != "ARC" or s.launch_vid is None:
            continue
        v = plan.visits[s.launch_vid]
        idx = plan.routes[v.truck].index(v.vid)
        if idx + 1 >= len(plan.routes[v.truck]):
            continue
        out.append(s)
    out.sort(key=lambda s: s.sid)
    return out


def _geometry_evaluate(plan: Plan, ctx: SolveContext, stats: SearchStats, reason: str,
                       budget: Budget | None = None,
                       multistart: bool = True) -> tuple[Evaluation | None, Plan | None]:
    """5 个基础几何起点：B0 继承 λ，B1/B2/B3/B4 全 0/1/0.25/0.75，B5(0.5) 补足."""
    inst, phys = ctx.inst, ctx.phys
    adj = adjustable_launches(plan)
    if not adj:
        if budget is not None and budget.evals_left() <= 0:
            return None, None
        p = plan.clone()
        ev = eval_counted(p, inst, phys, ctx.state, ctx.H, reason, stats, budget) if budget else \
            evaluate_plan(p, inst, phys, ctx.state, ctx.H, reason)
        if ev is None:
            return None, None
        return (ev if ev.feasible else None), (p if ev.feasible else None)
    vectors = [[s.lam for s in adj]]
    for val in (0.0, 1.0, 0.25, 0.75, 0.5):
        vectors.append([val] * len(adj))
    uniq = []
    for vec in vectors:
        if vec not in uniq:
            uniq.append(vec)
    if not multistart:
        uniq = uniq[:1]          # 第二轮：没有新建航次时只评继承的 λ（B0），省 4 次评价
    best_ev = None
    best_plan = None
    for vec in uniq[:5]:
        if budget is not None and budget.evals_left() <= 0:
            break
        p = plan.clone()
        for s, lam in zip(adj, vec):
            p.sorties[s.sid].lam = lam
        ev = eval_counted(p, inst, phys, ctx.state, ctx.H, reason, stats, budget) if budget else \
            evaluate_plan(p, inst, phys, ctx.state, ctx.H, reason)
        if ev is None:
            break
        if ev.feasible and (best_ev is None or _better(ev, best_ev, ctx.alg)):
            best_ev, best_plan = ev, p
    return best_ev, best_plan


def coordinate_polish(plan: Plan, ctx: SolveContext, stats: SearchStats,
                      budget: Budget, base_ev: Evaluation | None = None,
                      cap: int | None = None) -> tuple[Plan | None, Evaluation | None]:
    """逐维 ±h 坐标模式搜索，最多 cap（默认 coordinate_extra_eval_cap）次额外评价.
    第二轮：调用方已有该计划的评价时传入 base_ev，省掉重复评价."""
    inst, phys, alg = ctx.inst, ctx.phys, ctx.alg
    adj = adjustable_launches(plan)
    if not adj:
        return None, None
    if base_ev is None:
        base_ev = eval_counted(plan, inst, phys, ctx.state, ctx.H, "COORDINATE", stats, budget)
    if base_ev is None or not base_ev.feasible:
        return None, None
    cap_n = alg.coordinate_extra_eval_cap if cap is None else cap
    cur = plan.clone()
    cur_ev = base_ev
    h = alg.coordinate_initial_step
    extra = 0
    improved_any = False
    while h >= alg.coordinate_min_step and extra < cap_n:
        improved_round = False
        for s in adj:
            if extra >= cap_n or budget.evals_left() <= 0:
                break
            for delta in (h, -h):
                if extra >= cap_n or budget.evals_left() <= 0:
                    break
                cand = cur.clone()
                old = cand.sorties[s.sid].lam
                new = max(0.0, min(1.0, old + delta))
                if abs(new - old) < 1e-12:
                    continue
                cand.sorties[s.sid].lam = new
                extra += 1
                ev = eval_counted(cand, inst, phys, ctx.state, ctx.H, "COORDINATE", stats, budget)
                if ev is None:
                    break
                if ev.feasible and _better(ev, cur_ev, alg):
                    cur, cur_ev = cand, ev
                    improved_round = True
                    improved_any = True
                    break
        if not improved_round:
            h *= alg.coordinate_shrink
        stats.counts["coordinate_extra"] = stats.counts.get("coordinate_extra", 0) + 1
    return cur, cur_ev


def try_recovery_reassign(plan: Plan, ctx: SolveContext, budget: Budget,
                          stats: SearchStats, n: int = 2):
    """在统一预算内继续展开恢复候选目录，尝试替换受影响残段的接机车/点/继续子集."""
    from .recovery import build_catalog_candidates
    cat = ctx.catalog
    if cat is None or ctx.frag_sid is None:
        return None, None
    base = getattr(cat, "base_plan", None)
    pool = getattr(cat, "pool", None)
    if base is None or pool is None:
        return None, None
    res_plan = getattr(cat, "res_plan", None) or base
    best_p, best_ev = None, None
    for _ in range(n):
        if budget.evals_left() <= 0:
            break
        entries = cat.next_entries(1)
        if not entries:
            break
        entry = entries[0]
        cat.n_evaluated += 1
        cat.covered_trucks.add(entry["truck"])
        cat.covered_customers.add(entry["ref"] if entry["support"]
                                  else res_plan.visits[entry["ref"]].customer)
        cat.covered_subsets.add(len(entry["served"]))
        cands = build_catalog_candidates(cat, entry, ctx.inst, ctx.phys, ctx.state, ctx.H,
                                         ctx.ground_required, ctx.frag_sid)
        for cand in cands:
            if budget.evals_left() <= 0:
                break
            ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H,
                              "RECOVERY_INITIAL_BASE", stats, budget)
            if ev is None:
                break
            if ev.feasible and (best_ev is None or _better(ev, best_ev, ctx.alg)):
                best_p, best_ev = cand, ev
            break
    return best_p, best_ev
