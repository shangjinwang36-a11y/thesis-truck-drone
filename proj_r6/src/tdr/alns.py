"""唯一主算法：事件触发的车机协同恢复 ALNS 数学启发式（tdr_alns_v61）.

固定组件：
  * 6 个移除算子 + 2 个修复算子（代理分数排序）
  * 普通自适应权重（每 25 轮）
  * 模拟退火接受（真实 C_res 与 z）
  * 连续放飞位置搜索（5 个基础起点 + 坐标步长细化）
  * 局部事件重排（最多 6 个相邻未执行事件；枚举实现，见 local_reorder.py）
"""
from __future__ import annotations

import contextvars
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
    last_improvement_iter: int = 0
    audit: dict = field(default_factory=dict)       # 第六轮：算子审计 {算子: {计数}}
    reject: dict = field(default_factory=dict)      # 第六轮：不可行原因 {原因: 次数}

    def aud(self, name: str, key: str, n: int = 1) -> None:
        d = self.audit.setdefault(name, {})
        d[key] = d.get(key, 0) + n

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
        self.wall_hits = 0
        # Evaluations held back inside the same cap (contingency pricing). Not an extra budget.
        self.hold = 0
        # After this many evaluations, initial recovery yields to the main search if it
        # already has a feasible plan. It does not stop the search when it has none.
        self.init_release_at = None

    def take(self, n: int = 1) -> bool:
        cap = None if self.eval_limit is None else self.eval_limit - int(self.hold or 0)
        if cap is not None and self.used + n > cap:
            return False
        if self.wall_limit is not None and self.time_left() <= 0:
            self.wall_hits += 1
            return False
        self.used += n
        return True

    def exhausted(self) -> bool:
        return self.evals_left() <= 0 or self.time_left() <= 0

    def evals_left(self) -> float:
        if self.eval_limit is None:
            return float("inf")
        cap = self.eval_limit - int(getattr(self, "hold", 0) or 0)
        return float(max(0, cap - self.used))

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


def _air_penalty(plan: Plan | None, ctx: "SolveContext") -> float:
    """X 恢复接受准则里的新开空送惩罚。不影响写入结果的真实成本。

    x_risk_price_air 时按每票的期望失败代价计价（已知 p × 地面插入代理 + 回收工资）；
    否则沿用固定的 x_new_air_penalty（元/票）。两者都只在 X 的恢复阶段生效。
    """
    ceiling = getattr(ctx, "air_ceiling", None)
    if ceiling is None or plan is None or ctx.mode != "recovery" or ctx.strategy != "X":
        return 0.0
    from .recovery import _air_parcel_set
    extra = _air_parcel_set(plan) - set(ceiling)
    if not extra:
        return 0.0
    if getattr(ctx.alg, "x_risk_price_air", False):
        from .moves import new_air_risk_charge
        mp = None
        if ctx.state is not None:
            mp = ctx.state.truck_min_insert or None
        return new_air_risk_charge(plan, ctx.inst, ctx.phys, extra,
                                   float(getattr(ctx.alg, "failure_prob", 0.0) or 0.0),
                                   ctx.state, mp)
    pen = float(getattr(ctx.alg, "x_new_air_penalty", 0.0) or 0.0)
    if pen <= 0:
        return 0.0
    return pen * len(extra)


class _PenalizedEval:
    """只在接受比较时把惩罚加到 cost 上，不改原评价对象。"""

    def __init__(self, ev: Evaluation, extra: float):
        self.feasible = ev.feasible
        self.cost = None if ev.cost is None else ev.cost + extra
        self.z = ev.z
        self.timeline = ev.timeline


def _better_air(ev: Evaluation | None, plan: Plan | None,
                other: Evaluation | None, other_plan: Plan | None,
                alg: AlgorithmConfig, ctx: "SolveContext") -> bool:
    if ev is None:
        return False
    # scenario_on 只在阶段2打开。阶段1仍按真实成本下降，否则两个情景的噪声会把搜索带离
    # 情景分本身更低的方案。阶段2从该方案出发，只有情景分变好才接受。
    if (ctx.mode == "nominal" and getattr(alg, "expected_accept", False)
            and plan is not None and ev.feasible and ev.cost is not None):
        from .expected_cost import expected_j, failure_prob
        p = failure_prob(alg)
        v13 = bool(getattr(alg, "v13_rules", False))
        j_new = expected_j(ev.cost, plan, ctx.inst, ctx.phys, p, v13=v13)
        j_old = None
        if other is not None and other.feasible and other.cost is not None and other_plan is not None:
            j_old = expected_j(other.cost, other_plan, ctx.inst, ctx.phys, p, v13=v13)
        if j_new is not None and (j_old is None or j_new < j_old - alg.cost_tolerance_yuan):
            return True
        if j_new is not None and j_old is not None and abs(j_new - j_old) <= alg.cost_tolerance_yuan:
            return _better(ev, other, alg)
        # 情景评价仍是最终判据。期望值变差很多时才跳过，名义变贵本身不再跳过。
        if (getattr(alg, "scenario_aware", False) and getattr(ctx, "scenario_on", False)
                and other_plan is not None and other is not None and other.feasible):
            from .scenario_eval import screen_skips_scenario
            screen = float(getattr(alg, "scenario_screen_yuan", 0.0) or 0.0)
            if not screen_skips_scenario(j_new, j_old, screen):
                from .hybrid import scenario_score
                s_new = scenario_score(plan, ev, ctx)
                s_old = scenario_score(other_plan, other, ctx)
                if s_new is not None and s_old is not None and s_new < s_old - alg.cost_tolerance_yuan:
                    return True
        return False
    if (ctx.mode == "nominal" and getattr(alg, "scenario_aware", False)
            and getattr(ctx, "scenario_on", False)
            and plan is not None and ev.feasible):
        from .scenario_eval import screen_skips_scenario
        screen = float(getattr(alg, "scenario_screen_yuan", 0.0) or 0.0)
        old_cost = None if other is None else other.cost
        if not screen_skips_scenario(ev.cost, old_cost, screen):
            from .hybrid import scenario_score
            s_new = scenario_score(plan, ev, ctx)
        else:
            s_new = None
            if getattr(ctx, "live_stats", None) is not None:
                ctx.live_stats.aud("SCENARIO", "screened")
        if s_new is not None and (other is None or not other.feasible):
            return True
        if s_new is not None and other_plan is not None and other is not None and other.feasible:
            s_old = scenario_score(other_plan, other, ctx)
            if s_old is None:
                return True
            tol = alg.cost_tolerance_yuan
            if s_new < s_old - tol:
                return True
            if abs(s_new - s_old) <= tol:
                return _better(ev, other, alg)
            return False
    left = _PenalizedEval(ev, _air_penalty(plan, ctx))
    right = None if other is None else _PenalizedEval(other, _air_penalty(other_plan, ctx))
    return _better(left, right, alg)


def _incubate_cross(cand_plan, cur_plan, cand_ev, cur_ev, inst, phys, alg) -> bool:
    """新跨车组件可以先留在当前解里，升高不超过它自己的期望补救。不改全局最优。"""
    from .expected_cost import expected_j, failure_prob, insurance_room
    p_fail = failure_prob(alg)
    v13 = bool(getattr(alg, "v13_rules", False))
    j_new = expected_j(cand_ev.cost, cand_plan, inst, phys, p_fail, v13=v13)
    j_cur = expected_j(cur_ev.cost, cur_plan, inst, phys, p_fail, v13=v13)
    if j_new is None or j_cur is None:
        return False
    return j_new <= j_cur + insurance_room(cand_plan, cur_plan, inst, phys, p_fail) + alg.cost_tolerance_yuan


def _within_makespan_cap(ev: Evaluation | None, ctx: "SolveContext") -> bool:
    """X 名义：候选完工时刻不得超过 S 的 makespan。无上限时恒真。"""
    cap = getattr(ctx, "makespan_cap", None)
    if cap is None or ctx.mode != "nominal" or ev is None or ev.timeline is None:
        return True
    fin = ev.timeline.truck_finish
    if not fin:
        return True
    return max(fin.values()) <= cap + 1e-6


def _cross_energy_ok(cand_plan: Plan, cur_plan: Plan, ev: Evaluation | None, ctx: "SolveContext") -> bool:
    """每一条跨车航次在最终时刻表上的回收余电都要留出裕度。裕度为 0 时恒真。

    以前只在回收点改变时检查。后面的移动可以拉长飞行或等待、却不改回收客户，
    薄余电就会漏过去。cur_plan 仍保留在签名里，调用处不用改。
    """
    del cur_plan
    frac = float(getattr(ctx.alg, "x_cross_energy_margin_frac", 0.0) or 0.0)
    if frac <= 0 or ctx.mode != "nominal" or ev is None or ev.timeline is None:
        return True
    from .evaluate import is_cross_sortie
    cross_ids = [sid for sid, so in cand_plan.sorties.items() if is_cross_sortie(cand_plan, so)]
    if not cross_ids:
        return True
    need = ctx.phys.e_min + frac * ctx.phys.e_cap
    tl = ev.timeline
    for sid in cross_ids:
        so = cand_plan.sorties[sid]
        stages = tl.drone_stages.get(so.drone, [])
        energies = tl.drone_energy.get(so.drone, [])
        for i, st in enumerate(stages):
            if st.kind == "R" and not st.landed and st.sid == sid and i + 1 < len(energies):
                if energies[i + 1] < need - ctx.phys.energy_tol:
                    return False
    return True


def _nominal_cross_intact(plan: Plan, ev: Evaluation | None, ctx: "SolveContext") -> bool:
    """X 名义：最终时刻表上每一条跨车航次都要过稳健性检查。

    开关关掉时恒真，旧的「只在回收点改变时查 5%」仍然单独生效。
    S 的 nominal_cross 为假，不进这条。后面的移动即使没有改回收点，
    只要把飞行或等待拉长到门槛以下，这里也会拒绝。
    """
    if not getattr(ctx.alg, "x_cross_robust", False):
        return True
    if ctx.mode != "nominal" or not getattr(ctx.state, "nominal_cross", False):
        return True
    if plan is None:
        return True
    from .evaluate import is_cross_sortie
    if not any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        return True
    if ev is None or not ev.feasible or ev.timeline is None:
        return False
    from .cross_robust import cross_robust_violations
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 0.0) or 0.0)
    return not cross_robust_violations(plan, ctx.inst, ctx.phys, ev.timeline, slack)


_ACTIVE_CTX: contextvars.ContextVar = contextvars.ContextVar("tdr_active_ctx", default=None)


def publish_j_champion(plan, ev, stats, alg, ctx):
    """Return the stored best-J plan when the caller is about to publish something worse."""
    _note_j_champion(stats, plan, ev, alg, ctx)
    champ_p = getattr(stats, "j_champion_plan", None)
    champ_e = getattr(stats, "j_champion_ev", None)
    if champ_p is None or champ_e is None:
        return plan, ev
    if _better_air(champ_e, champ_p, ev, plan, alg, ctx):
        return champ_p.clone(), champ_e
    return plan, ev


def _note_j_champion(stats, plan, ev, alg, ctx) -> None:
    """Remember the best plain v1.3 J seen. S and X both call this. A later stage cannot drop it."""
    if ctx is None or not getattr(alg, "v13_rules", False) or getattr(ctx, "mode", None) != "nominal":
        return
    if plan is None or ev is None or not ev.feasible or ev.cost is None:
        return
    if not _nominal_cross_intact(plan, ev, ctx):
        return
    from .expected_cost import expected_j
    j = expected_j(ev.cost, plan, ctx.inst, ctx.phys, 0.0, v13=True)
    if j is None:
        return
    old = getattr(stats, "j_champion_j", None)
    if old is not None and j >= old - float(getattr(alg, "cost_tolerance_yuan", 1e-6) or 1e-6):
        return
    stats.j_champion_j = j
    stats.j_champion_plan = plan.clone()
    stats.j_champion_ev = ev
    from .evaluate import is_cross_sortie
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        stats.j_cross_champion_j = j


def eval_counted(plan: Plan, inst: Instance, phys: PhysicalConfig, state: StartState,
                 H: float | None, reason: str, stats: SearchStats, budget: Budget,
                 allow_wait_repair: bool = True) -> Evaluation | None:
    """唯一完整评价入口：由统一预算对象扣账，进入即计 1 次."""
    ev = evaluate_plan(plan, inst, phys, state, H, reason, budget=budget,
                       allow_wait_repair=allow_wait_repair)
    if ev.status == "BUDGET_EXHAUSTED":
        return None
    stats.eval_by_reason[reason] = stats.eval_by_reason.get(reason, 0) + 1
    if getattr(budget, "scenario_ledger", False):
        stats.n_scenario_eval = budget.used
    else:
        stats.eval_requests = budget.used
        if reason == "SCENARIO_RECOURSE":
            stats.n_scenario_eval = int(getattr(stats, "n_scenario_eval", 0)) + 1
        if reason in ("CROSS_CONVERT", "SUPPORT_RENDEZVOUS", "ENERGY_RETARGET",
                       "PAIR_HANDOFF", "CROSS_INSERT"):
            stats.cross_evals = int(getattr(stats, "cross_evals", 0)) + 1
    holder = _ACTIVE_CTX.get()
    if holder is not None and ev.feasible and ev.cost is not None:
        _note_j_champion(stats, plan, ev, holder.alg, holder)
        if holder.mode == "recovery":
            old = getattr(stats, "screen_champion_cost", None)
            if old is None or float(ev.cost) < float(old):
                stats.screen_champion_cost = float(ev.cost)
    if (holder is not None and ev.feasible and ev.cost is not None
            and holder.mode == "nominal"
            and reason not in ("SCENARIO_RECOURSE", "SET_PARTITION")
            and getattr(holder.alg, "set_partition", False)):
        from .hybrid import _pool
        _pool(holder, bool(getattr(holder.state, "nominal_cross", False))).add_plan(
            plan, holder.inst, holder.phys, False)
    stats.lp_calls += int(ev.counts.get("lp_calls", 0)) if ev.counts else 0
    if not ev.feasible:
        import re as _re
        v0 = _re.sub(r"[-0-9.]+", "#", (ev.violations[0] if ev.violations else ""))[:48]
        k_ = f"{reason}|{ev.status}|{v0}"
        stats.reject[k_] = stats.reject.get(k_, 0) + 1
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
    elif op == "JOINT_NEAR":
        from .support_nominal import joint_near_seeds
        seeds = joint_near_seeds(plan, inst, bool(getattr(ctx.state, "nominal_cross", False)))
        if not seeds:
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
    strategy: str = "X"
    retarget_tried: set = field(default_factory=set)
    cross_tried: set = field(default_factory=set)
    # X 名义阶段2：候选卡车完工时刻不得超过该值（通常 = S 名义 makespan）。None=不限制。
    makespan_cap: float | None = None
    # X 恢复：残差里已经会空送的票。新开的票按 x_new_air_penalty 计入接受比较。
    air_ceiling: set | None = None


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
    """绑定当前搜索，使评价入口把可行的名义方案写入列池。"""
    token = _ACTIVE_CTX.set(ctx)
    try:
        return _optimize_loop(plan, ctx, budget, variant, stats, init_ev)
    finally:
        _ACTIVE_CTX.reset(token)


def _optimize_loop(plan: Plan, ctx: SolveContext, budget: Budget, variant: str = "full",
                   stats: SearchStats | None = None, init_ev: Evaluation | None = None) -> SolveResult:
    """ALNS 主循环.

    init_ev：调用方已经完整评价过起始解时传入（恢复阶段由 initial_recovery 评价，
    计入"初始化预算"），这里不再重复评价，也不占主循环预算。
    此时 budget 是**主循环预算**（S/X 相同），SA 退火进度只由主循环进度决定。
    """
    inst, phys, alg = ctx.inst, ctx.phys, ctx.alg
    stats = stats or SearchStats()
    ctx.live_budget = budget
    ctx.live_stats = stats
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
    from .evaluate import is_cross_sortie as _is_cross_plan
    def _no_cross(p) -> bool:
        return p is not None and not any(_is_cross_plan(p, s) for s in p.sorties.values())
    same_plan = best_plan.clone() if _no_cross(best_plan) else None
    same_ev = best_ev if same_plan is not None else None
    # 第四轮 M3：退火温度尺度只用“后缀成本”(全班成本扣除快照前已发生的常量 C_prefix_fixed)，
    # 规范 7.x：不得用随故障时刻增长的历史常数放大退火温度。
    C_scale = max((cur_ev.cost or 1.0) - prefix_fixed_cost(ctx.state, phys), 1.0)
    T0 = -alg.sa_initial_worse_fraction * C_scale / math.log(0.5)
    destroy_ops = list(alg.destroy_operators)
    repair_ops = list(alg.repair_operators)
    if alg.air_promote_ops and alg.operator_selector != "qlearn":
        destroy_ops.append("GROUND_TO_AIR")
        repair_ops.append("AIR_FIRST")
    if (getattr(alg, "joint_near_destroy", False) and ctx.mode == "nominal"
            and (getattr(ctx.state, "nominal_cross", False) or getattr(ctx, "scenario_on", False))):
        destroy_ops.append("JOINT_NEAR")
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
        # Iteration cap, shared by S and X. A cross evaluation does not end the slice.
        iter_cap = getattr(stats, "iter_cap", None)
        if iter_cap is not None and stats.iterations >= int(iter_cap):
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
        if ctx.mode == "recovery" and best_ev is not None and best_ev.cost is not None:
            stats.screen_champion_cost = float(best_ev.cost)
        if alg.crn_per_iteration:
            # 共同随机数(CRN)：每轮的随机流只由(种子,算例,重规划序号,轮次)决定，与此前消耗了多少评价无关；
            # S/X 在同一轮次、同一当前解时抽到完全相同的算子/破坏量/接受随机数，削弱 X 目录更大造成的流错位噪声。
            for _nm, _r in (('operator', rng_op), ('destroy', rng_des), ('accept', rng_acc)):
                _r.seed(f'crn|{alg.base_algorithm_seed}|{inst.case_id}|{ctx.replan_index}|{stats.iterations}|{_nm}')
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
        stats.aud(op, "calls")
        stats.aud("R:" + rep, "calls")
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
            stats.aud(op, "freed0")
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
            stats.aud(op, "leftover")
            stats.aud("R:" + rep, "leftover")
            _reward(s_d, op, 0.0)
            _reward(s_r, rep, 0.0)
            if sel is not None:
                pend = (skey, sact, 0.0)
            stagnation += 1
            _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg)
            continue
        # 基础几何评价（5 个 λ 起点）
        new_sortie = any(sid >= cur_plan.next_sid for sid in trial.sorties)
        from .evaluate import is_cross_sortie as _isx
        trial_cross = any(_isx(trial, so) for so in trial.sorties.values() if so.sid >= cur_plan.next_sid)
        if trial_cross:
            stats.aud("CROSS_REPAIR_TRIALS", "gen")
            stats.aud("FUNNEL_CROSS", "generated")
        cand_ev, cand_plan = _geometry_evaluate(
            trial, ctx, stats, "ALNS_BASE", budget,
            multistart=(new_sortie or not alg.geometry_new_sortie_only))
        if ctx.state.nominal_cross:
            _cp = any(_isx(cur_plan, so) for so in cur_plan.sorties.values())
            stats.aud("PLAN_HAS_CROSS" if _cp else "PLAN_NO_CROSS", ("TC_" if trial_cross else "TN_") + ("infeasible" if cand_ev is None else "feasible"))
        if cand_ev is None:
            if trial_cross:
                stats.aud("FUNNEL_CROSS", "schedule")
            stats.aud(op, "infeasible")
            stats.aud("R:" + rep, "infeasible")
            _reward(s_d, op, 0.0)
            _reward(s_r, rep, 0.0)
            if sel is not None:
                pend = (skey, sact, 0.0)
            stagnation += 1
            _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg)
            continue
        reward = 0.0
        accepted = False
        became_same_best = False
        # A cross stored as the champion must not change the same-truck score.
        # S has no cross champion, so this reference is best_plan and the path is unchanged.
        score_ev, score_plan = best_ev, best_plan
        if (getattr(ctx.state, "nominal_cross", False) and ctx.mode == "nominal"
                and getattr(alg, "v13_rules", False) and same_ev is not None
                and best_plan is not None and not _no_cross(best_plan)):
            score_ev, score_plan = same_ev, same_plan
        stats.aud(op, "feasible")
        stats.aud("R:" + rep, "feasible")
        if trial_cross:
            stats.aud("CROSS_REPAIR_TRIALS", "feasible")
        blocked = False
        if not _within_makespan_cap(cand_ev, ctx):
            blocked = True
            stats.aud("HS_CAP", "rejected")
            if trial_cross:
                stats.aud("FUNNEL_CROSS", "cap")
        elif (trial_cross and not getattr(alg, "x_cross_robust", False)
              and not _cross_energy_ok(cand_plan, cur_plan, cand_ev, ctx)):
            blocked = True
            stats.aud("CROSS_ENERGY_MARGIN", "rejected")
            stats.aud("FUNNEL_CROSS", "energy")
        elif not _nominal_cross_intact(cand_plan, cand_ev, ctx):
            blocked = True
            stats.aud("CROSS_ROBUST", "rejected")
            if trial_cross:
                stats.aud("FUNNEL_CROSS", "margin")
        if blocked:
            reward = 0.0
            stagnation += 1
            accepted = False
        elif _better_air(cand_ev, cand_plan, score_ev, score_plan, alg, ctx):
            stats.aud(op, "best")
            stats.aud("R:" + rep, "best")
            if trial_cross:
                stats.aud("CROSS_REPAIR_TRIALS", "best")
            stats.last_improvement_iter = stats.iterations
            if _better_air(cand_ev, cand_plan, best_ev, best_plan, alg, ctx):
                best_ev, best_plan = cand_ev, cand_plan.clone()
            became_same_best = True
            reward = alg.score_global_best
            accepted = True
            stagnation = 0
            stats.last_improvement_eval = stats.eval_requests
            stats.best_trace.append((stats.eval_requests, best_ev.cost or 0.0, best_ev.z or 0.0))
        elif _better_air(cand_ev, cand_plan, cur_ev, cur_plan, alg, ctx) and not (
                trial_cross and ctx.mode == "nominal" and getattr(alg, "v13_rules", False)):
            stats.aud(op, "cur_improve")
            stats.aud("R:" + rep, "cur_improve")
            reward = alg.score_current_improvement
            accepted = True
            stagnation = 0
        elif (trial_cross and ctx.mode == "nominal" and getattr(alg, "expected_accept", False)
              and not getattr(alg, "v13_rules", False)
              and cand_ev is not None and cand_ev.feasible and cur_ev is not None and cur_ev.feasible
              and _incubate_cross(cand_plan, cur_plan, cand_ev, cur_ev, inst, phys, alg)):
            accepted = True
            reward = alg.score_current_improvement
            stagnation = 0
            stats.aud("EXPECTED", "incubated")
        elif trial_cross and getattr(alg, "x_improve_only_cross", False) and ctx.mode == "nominal" \
                and not getattr(alg, "expected_accept", False):
            # X 专属：跨车移动只接受严格改进（不用 SA），以保证相对当前解不退步
            accepted = False
            reward = 0.0
            stagnation += 1
            stats.aud("CROSS_REPAIR_TRIALS", "rejected_improve_only")
        elif (ctx.mode == "recovery" and ctx.strategy == "X"
              and (float(getattr(alg, "x_new_air_penalty", 0.0) or 0.0) > 0
                   or getattr(alg, "x_risk_price_air", False))
              and _air_penalty(cand_plan, ctx) > _air_penalty(cur_plan, ctx) + 1e-9):
            # 只有“比当前解多开空送”的移动才禁止 SA。其它移动与第三轮一样可以退火。
            accepted = False
            reward = 0.0
            stagnation += 1
        else:
            # SA. Under v1.3 a cross joins the current plan only when J improves,
            # which the two branches above already require. Annealing stays for same-truck moves.
            if trial_cross and ctx.mode == "nominal" and getattr(alg, "v13_rules", False):
                accepted = False
                stagnation += 1
            elif cand_ev.feasible:
                if ctx.mode == "nominal" and getattr(alg, "expected_accept", False):
                    from .expected_cost import expected_j, failure_prob
                    p_fail = failure_prob(alg)
                    v13 = bool(getattr(alg, "v13_rules", False))
                    j_new = expected_j(cand_ev.cost, cand_plan, inst, phys, p_fail, v13=v13)
                    j_cur = expected_j(cur_ev.cost, cur_plan, inst, phys, p_fail, v13=v13) if cur_ev is not None else None
                    dc = 0.0 if j_new is None or j_cur is None else j_new - j_cur
                else:
                    from .hybrid import cached_scenario_cost
                    sn = cached_scenario_cost(cand_plan, ctx)
                    sc = cached_scenario_cost(cur_plan, ctx)
                    if sn is not None and sc is not None:
                        dc = sn - sc
                    else:
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
            stats.aud(op, "accepted")
            stats.aud("R:" + rep, "accepted")
            if trial_cross:
                stats.aud("CROSS_REPAIR_TRIALS", "accepted")
                stats.aud("FUNNEL_CROSS", "accepted")
            if not (trial_cross and ctx.mode == "nominal" and getattr(alg, "v13_rules", False)):
                cur_plan, cur_ev = cand_plan.clone(), cand_ev
        _reward(s_d, op, reward)
        _reward(s_r, rep, reward)
        if ctx.mode == "nominal" and getattr(alg, "v13_rules", False):
            if _no_cross(cur_plan) and cur_ev is not None and cur_ev.feasible and (
                    same_ev is None or _better_air(cur_ev, cur_plan, same_ev, same_plan, alg, ctx)):
                same_plan, same_ev = cur_plan.clone(), cur_ev
            if _no_cross(best_plan) and best_ev is not None and best_ev.feasible and (
                    same_ev is None or _better_air(best_ev, best_plan, same_ev, same_plan, alg, ctx)):
                same_plan, same_ev = best_plan.clone(), best_ev
        if sel is not None:
            pend = (skey, sact, reward / alg.score_global_best)
        # Shared local search, S and X. A new same-truck champion spends at most four
        # evaluations on a deterministic descent. Infeasible trials are not reached here.
        if (became_same_best and getattr(alg, "v13_rules", False) and ctx.mode == "nominal"
                and budget.evals_left() > 4):
            from .nominal import descent_pass
            p_d, e_d, _spent = descent_pass(
                cur_plan.clone(), inst, phys, alg, ctx.state, stats, cur_ev, budget,
                max_eval=4, allow_cross=False)
            if (e_d is not None and e_d.feasible
                    and _better_air(e_d, p_d, cur_ev, cur_plan, alg, ctx)):
                cur_plan, cur_ev = p_d, e_d
                if _no_cross(cur_plan) and (
                        same_ev is None or _better_air(cur_ev, cur_plan, same_ev, same_plan, alg, ctx)):
                    same_plan, same_ev = cur_plan.clone(), cur_ev
                if _better_air(e_d, p_d, best_ev, best_plan, alg, ctx):
                    best_ev, best_plan = e_d, p_d.clone()
        # 连续位置细化：新最好解，或每 10 轮
        do_polish = variant != "no_coordinate_polish" and (
            (best_ev is cand_ev) or became_same_best
            or stats.iterations % alg.coordinate_polish_every_alns_iterations == 0)
        if do_polish and budget.evals_left() > 0:
            if alg.coordinate_light:
                p2, e2 = coordinate_polish(cur_plan, ctx, stats, budget, base_ev=cur_ev,
                                           cap=alg.coordinate_light_cap)
            else:
                p2, e2 = coordinate_polish(cur_plan, ctx, stats, budget)
            if (e2 is not None and _better_air(e2, p2, cur_ev, cur_plan, alg, ctx)
                    and _within_makespan_cap(e2, ctx) and _nominal_cross_intact(p2, e2, ctx)):
                cur_plan, cur_ev = p2, e2
                if _better_air(e2, p2, best_ev, best_plan, alg, ctx) and _within_makespan_cap(e2, ctx):
                    best_ev, best_plan = e2, p2.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 恢复邻域：继续展开受影响残段的接机车/接机点/部分继续（预算允许时）
        if ctx.catalog is not None and stats.iterations % 10 == 0 and budget.evals_left() > 0:
            p_r, e_r = try_recovery_reassign(cur_plan, ctx, budget, stats)
            if (p_r is not None and e_r is not None
                    and _better_air(e_r, p_r, best_ev if alg.reassign_adopt_only_if_best else cur_ev,
                                    best_plan if alg.reassign_adopt_only_if_best else cur_plan, alg, ctx)):
                # 第五轮修复(并入第六轮)：目录候选由名义残余计划重建、不含当前 ALNS 进展；
                # flag=True 时只在优于全局最优时才替换当前解，避免丢弃进展。S/X 同一规则。
                stats.audit['reassign:adopt_gap_max'] = max(stats.audit.get('reassign:adopt_gap_max', -1e9),
                                                            (e_r.cost or 0.0) - (best_ev.cost or 0.0))
                stats.aud('REASSIGN', 'adopt')
                cur_plan, cur_ev = p_r, e_r
                if _better_air(e_r, p_r, best_ev, best_plan, alg, ctx):
                    best_ev, best_plan = e_r, p_r.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 第四轮：恢复目标重定位（当前最优计划上；S/X 同算子同预算，资格不同）
        if (alg.recovery_retarget and ctx.mode == "recovery" and ctx.frag_sid is not None
                and stats.iterations % alg.retarget_period == alg.retarget_period // 2
                and budget.evals_left() > 0):
            p_t, e_t = try_recovery_retarget(cur_plan, ctx, budget, stats)
            if p_t is not None and e_t is not None and _better_air(e_t, p_t, cur_ev, cur_plan, alg, ctx):
                cur_plan, cur_ev = p_t, e_t
                if _better_air(e_t, p_t, best_ev, best_plan, alg, ctx):
                    best_ev, best_plan = e_t, p_t.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 第四轮：X 专用跨车算子（仅当失败航次由≠原放飞车的车接回时有资格；S 恒不触发；消耗同一份预算）
        if (alg.cross_ops and ctx.mode == "recovery" and ctx.frag_sid is not None
                and stats.iterations % alg.cross_period == alg.cross_period // 2
                and budget.evals_left() > 0):
            p_x, e_x = try_cross_truck_ops(cur_plan, ctx, budget, stats)
            if p_x is not None and e_x is not None and _better_air(e_x, p_x, cur_ev, cur_plan, alg, ctx):
                cur_plan, cur_ev = p_x, e_x
                if _better_air(e_x, p_x, best_ev, best_plan, alg, ctx):
                    best_ev, best_plan = e_x, p_x.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 第四轮：X 专属。把最贵的纯地面绕路和从任一合格卡车再飞一趟做一次真实评价，
        # 接受准则含风险价。S 的 propose 恒为空，不消耗评价。
        if (getattr(alg, "x_risk_price_air", False) and ctx.strategy == "X" and ctx.mode == "recovery"
                and stats.iterations % alg.cross_period == 1
                and budget.evals_left() > 0):
            p_f, e_f = try_refly(cur_plan, ctx, budget, stats)
            if p_f is not None and e_f is not None and _better_air(e_f, p_f, cur_ev, cur_plan, alg, ctx):
                stats.aud("REFLY", "cur_improve")
                cur_plan, cur_ev = p_f, e_f
                if _better_air(e_f, p_f, best_ev, best_plan, alg, ctx):
                    stats.aud("REFLY", "best")
                    best_ev, best_plan = e_f, p_f.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        if (getattr(alg, "expected_accept", False) and ctx.mode == "nominal"
                and getattr(alg, "scenario_aware", False) and best_plan is not None
                and best_ev is not None and best_ev.feasible):
            every = int(getattr(alg, "expected_reeval_every", 80) or 80)
            if getattr(stats, "iter_cap", None):
                mark = stats.iterations // 20 if every > 0 else 0
            else:
                mark = stats.eval_requests // every if every > 0 else 0
            if mark > getattr(ctx, "_expected_reeval_mark", 0):
                ctx._expected_reeval_mark = mark
                from .hybrid import scenario_score
                # X only. This fill is not an acceptance test. Scoring it with cross
                # recourse keeps evaluating after S's same-truck recourse has stopped,
                # and those extra charges are what walk X off S's remaining search.
                _saved_cross = None
                if getattr(ctx.state, "nominal_cross", False) and getattr(alg, "v13_rules", False):
                    _saved_cross = True
                    ctx.state.nominal_cross = False
                scenario_score(best_plan, best_ev, ctx)
                if _saved_cross:
                    ctx.state.nominal_cross = True
                stats.aud("EXPECTED", "true_reeval")
        # X only. Adaptive weights over SKIP and the three cross kinds. S never
        # enters, so S's destroy and repair roulette is unchanged. A kind that
        # finds no floor-legal meeting spends no evaluation.
        if (getattr(ctx.state, "nominal_cross", False) and ctx.mode == "nominal"
                and getattr(alg, "v13_rules", False) and budget.evals_left() > 0):
            from .cross_nominal import try_integrated_cross
            from .evaluate import is_cross_sortie as _isc_now
            _same_rng = (rng_op.getstate(), rng_des.getstate(), rng_acc.getstate())
            _ensure_cross_weights(stats)
            rng_cross = stats.cross_rng
            rng_cross.seed(
                f"crn|{alg.base_algorithm_seed}|{inst.case_id}|{ctx.replan_index}|{stats.iterations}|cross")
            chosen = _roulette(stats.cross_weights, rng_cross)
            stats.cross_n[chosen] += 1
            stats.cross_selects[chosen] = stats.cross_selects.get(chosen, 0) + 1
            if chosen == "SKIP":
                _reward(stats.cross_s, "SKIP", reward)
            else:
                kind = {"MULTI": 0, "RELIEVE": 1, "RETARGET": 2, "PAIR": 3}[chosen]
                base_i = cur_plan
                if (stats.iterations % 4 == 0 and best_plan is not None
                        and any(_isc_now(best_plan, s) for s in best_plan.sorties.values())):
                    base_i = best_plan
                from .expected_cost import expected_j as _ej
                j_b = None if best_ev is None else _ej(best_ev.cost, best_plan, inst, phys, 0.0, v13=True, rescue_aware=False)
                j_arch = getattr(stats, "j_champion_j", None)
                j_ref = j_b if j_arch is None else min(j_b, j_arch) if j_b is not None else j_arch
                charged_before = int(getattr(stats, "cross_charged", 0) or 0)
                p_i, e_i = try_integrated_cross(base_i, ctx, budget, stats, kind, j_ref=j_ref)
                charged = int(getattr(stats, "cross_charged", 0) or 0) > charged_before
                # Plain v1.3 J. Accept only when this beats the best J seen so far.
                j_i = None if e_i is None else _ej(e_i.cost, p_i, inst, phys, 0.0, v13=True, rescue_aware=False)
                accepted_cross = (p_i is not None and e_i is not None and j_i is not None and j_ref is not None
                                  and j_i < j_ref - alg.cost_tolerance_yuan
                                  and _within_makespan_cap(e_i, ctx)
                                  and _nominal_cross_intact(p_i, e_i, ctx))
                if accepted_cross:
                    # Keep the cross in the best-J archive only. Putting it in best_plan
                    # changes later same-truck scores and walks X off S's path.
                    stats.aud("CROSS_INSERT", "best")
                    stats.cross_accepted = int(getattr(stats, "cross_accepted", 0) or 0) + 1
                    stats.cross_fail_streak = 0
                    _reward(stats.cross_s, chosen, alg.score_global_best)
                    stats.cross_weights[chosen] = stats.cross_weights.get(chosen, 1.0) + 4.0
                    stats.best_trace.append((stats.eval_requests, best_ev.cost or 0.0, best_ev.z or 0.0))
                else:
                    _reward(stats.cross_s, chosen, 0.0)
                    if charged:
                        _decay_cross_share(stats, chosen)
            rng_op.setstate(_same_rng[0])
            rng_des.setstate(_same_rng[1])
            rng_acc.setstate(_same_rng[2])
        cross_room = not getattr(alg, "v13_rules", False)
        if (getattr(alg, "x_energy_retarget", False) and getattr(ctx.state, "nominal_cross", False)
                and ctx.mode == "nominal"
                and stats.iterations % alg.cross_period == 3
                and cross_room
                and budget.evals_left() > 0):
            from .support_nominal import try_energy_retarget
            p_e, e_e = try_energy_retarget(cur_plan, ctx, budget, stats)
            if (p_e is not None and e_e is not None
                    and _better_air(e_e, p_e, best_ev, best_plan, alg, ctx)
                    and _within_makespan_cap(e_e, ctx)
                    and _nominal_cross_intact(p_e, e_e, ctx)):
                stats.aud("ENERGY_RETARGET", "best")
                if getattr(alg, "v13_rules", False):
                    _remember_cross(stats, p_e, e_e, alg, ctx)
                else:
                    cur_plan, cur_ev = p_e, e_e
                    best_ev, best_plan = e_e, p_e.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 第 9 轮：插入会合访问。X 插到另一辆车，S 只插到放飞车。两边同一频率、同一评价上限。
        if (getattr(alg, "support_rendezvous", False) and ctx.mode == "nominal"
                and (getattr(ctx.state, "nominal_cross", False) or getattr(ctx, "scenario_on", False))
                and stats.iterations % alg.cross_period == 0
                and cross_room
                and budget.evals_left() > 0):
            from .support_nominal import try_support_rendezvous
            base_s, ref_e = (cur_plan, best_ev)
            if getattr(alg, "v13_rules", False):
                base_s, ref_e = _cross_base(stats, cur_plan, best_plan, best_ev, alg, ctx)
            p_s, e_s = try_support_rendezvous(base_s, ctx, budget, stats)
            ref_p = base_s if getattr(alg, "v13_rules", False) else cur_plan
            if (p_s is not None and e_s is not None
                    and _better_air(e_s, p_s, ref_e, ref_p, alg, ctx)
                    and _within_makespan_cap(e_s, ctx)
                    and _nominal_cross_intact(p_s, e_s, ctx)):
                stats.aud("FUNNEL_SUPPORT", "accepted")
                if getattr(ctx.state, "nominal_cross", False):
                    stats.aud("FUNNEL_CROSS", "accepted")
                from .hybrid import cached_scenario_cost
                sn = cached_scenario_cost(p_s, ctx)
                sc = cached_scenario_cost(cur_plan, ctx)
                if sn is not None and sc is not None and sn < sc - alg.cost_tolerance_yuan:
                    stats.aud("FUNNEL_SUPPORT", "scenario")
                stats.aud("SUPPORT_RENDEZVOUS", "cur_improve")
                if getattr(alg, "v13_rules", False):
                    _remember_cross(stats, p_s, e_s, alg, ctx)
                else:
                    cur_plan, cur_ev = p_s, e_s
                    if _better_air(e_s, p_s, best_ev, best_plan, alg, ctx) and _within_makespan_cap(e_s, ctx):
                        stats.aud("SUPPORT_RENDEZVOUS", "best")
                        stats.last_improvement_iter = stats.iterations
                        best_ev, best_plan = e_s, p_s.clone()
                        stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        if (getattr(alg, "pair_handoff", False) and getattr(ctx.state, "nominal_cross", False)
                and ctx.mode == "nominal"
                and stats.iterations % alg.cross_period == 1
                and budget.evals_left() > 0):
            from .support_nominal import try_pair_handoff
            p_h, e_h = try_pair_handoff(cur_plan, ctx, budget, stats)
            if (p_h is not None and e_h is not None
                    and _better_air(e_h, p_h, cur_ev, cur_plan, alg, ctx)
                    and _within_makespan_cap(e_h, ctx)
                    and _nominal_cross_intact(p_h, e_h, ctx)):
                stats.aud("FUNNEL_HANDOFF", "accepted")
                stats.aud("FUNNEL_CROSS", "accepted")
                cur_plan, cur_ev = p_h, e_h
                if _better_air(e_h, p_h, best_ev, best_plan, alg, ctx) and _within_makespan_cap(e_h, ctx):
                    best_ev, best_plan = e_h, p_h.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 第六轮：X 名义专用“同车航次改跨车回收”算子（S 的 state.nominal_cross=False，永不触发；同一份名义预算）
        if (getattr(ctx.state, "nominal_cross", False) and ctx.mode == "nominal"
                and stats.iterations % alg.cross_period == alg.cross_period // 2
                and cross_room
                and budget.evals_left() > 0):
            from .cross_nominal import try_cross_convert
            base_x = cur_plan
            ref_e, ref_p = cur_ev, cur_plan
            if getattr(alg, "v13_rules", False):
                base_x, ref_e = _cross_base(stats, cur_plan, best_plan, best_ev, alg, ctx)
                ref_p = base_x
            p_x, e_x = try_cross_convert(base_x, ctx, budget, stats)
            if (p_x is not None and e_x is not None
                    and _better_air(e_x, p_x, ref_e, ref_p, alg, ctx)
                    and _within_makespan_cap(e_x, ctx)
                    and _cross_energy_ok(p_x, cur_plan, e_x, ctx)
                    and _nominal_cross_intact(p_x, e_x, ctx)):
                stats.aud("CROSS_CONVERT", "cur_improve")
                stats.aud("FUNNEL_CROSS", "accepted")
                if getattr(alg, "v13_rules", False):
                    _remember_cross(stats, p_x, e_x, alg, ctx)
                else:
                    cur_plan, cur_ev = p_x, e_x
                    if _better_air(e_x, p_x, best_ev, best_plan, alg, ctx) and _within_makespan_cap(e_x, ctx):
                        stats.aud("CROSS_CONVERT", "best")
                        stats.last_improvement_iter = stats.iterations
                        best_ev, best_plan = e_x, p_x.clone()
                        stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        # 局部事件重排
        if variant != "no_local_mip" and (stats.iterations % alg.mip_period_rounds == 0
                                          or stagnation >= alg.mip_stagnation_rounds):
            if stats.iterations - last_mip_round >= alg.mip_min_interval_rounds:
                last_mip_round = stats.iterations
                from .local_reorder import try_local_reorder
                p3, e3 = try_local_reorder(best_plan, best_ev, ctx, stats, budget, window_cursor)
                window_cursor += 1
                if (p3 is not None and e3 is not None and _better_air(e3, p3, best_ev, best_plan, alg, ctx)
                        and _within_makespan_cap(e3, ctx) and _nominal_cross_intact(p3, e3, ctx)):
                    best_ev, best_plan = e3, p3.clone()
                    stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
        if (getattr(alg, "scenario_elite_refill", False) and ctx.mode == "nominal"
                and getattr(ctx, "scenario_on", False)
                and stats.iterations % 10 == 0
                and best_ev is not None and best_ev.feasible):
            from .hybrid import cached_scenario_cost, scenario_score
            if cached_scenario_cost(best_plan, ctx) is None:
                scenario_score(best_plan, best_ev, ctx)
                stats.aud("SCENARIO", "elite_refill")
        _maybe_weights(stats, w_d, w_r, n_d, n_r, s_d, s_r, alg, variant)
    # 集合划分不放进退火循环：插进去的评价会改变温度，即使不接受也会把真实成本搜索带离原轨迹。
    # 只在阶段2结束时重组一次。阶段1的列已经进池，阶段2开始前还会再解一次。
    if (getattr(alg, "set_partition", False) and ctx.mode == "nominal"
            and getattr(ctx, "scenario_on", False) and budget.evals_left() > 0):
        from .hybrid import try_set_partition
        p_m, e_m = try_set_partition(best_plan, ctx, budget, stats)
        if (p_m is not None and e_m is not None and e_m.feasible
                and _better_air(e_m, p_m, best_ev, best_plan, alg, ctx)
                and _within_makespan_cap(e_m, ctx)
                and _nominal_cross_intact(p_m, e_m, ctx)):
            stats.aud("SET_PARTITION", "adopted")
            best_ev, best_plan = e_m, p_m.clone()
            stats.best_trace.append((stats.eval_requests, best_ev.cost, best_ev.z))
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
                    "last_improvement_iter": stats.last_improvement_iter,
                    "audit": {k: (dict(v) if isinstance(v, dict) else v) for k, v in stats.audit.items()},
                    "reject": dict(stats.reject),
                    "best_trace": stats.best_trace}
    n_sc = int(getattr(stats, "n_scenario_eval", 0) or 0)
    shared_scenario = int(getattr(alg, "scenario_eval_cap", 0) or 0) <= 0
    stats.counts["n_scenario_eval"] = n_sc
    stats.counts["n_phys_eval"] = int(stats.eval_requests) - (n_sc if shared_scenario else 0)
    from .hybrid import _pool
    pool = _pool(ctx, bool(getattr(ctx.state, "nominal_cross", False))) if (
        getattr(alg, "set_partition", False) and ctx.mode == "nominal") else None
    if pool is not None:
        if pool.allow_cross:
            stats.counts["n_sync_columns"] = len(pool.sync)
            stats.counts["n_route_columns"] = 0
            stats.counts["n_link_columns"] = 0
        else:
            stats.counts["n_route_columns"] = len(pool.routes)
            stats.counts["n_link_columns"] = 0
            stats.counts["n_sync_columns"] = 0
    final_ev = best_ev
    stats.same_plan = same_plan
    stats.same_ev = same_ev
    if getattr(stats, "cross_weights", None):
        stats.counts["cross_weights"] = {k: round(float(v), 4) for k, v in stats.cross_weights.items()}
        stats.counts["cross_selects"] = dict(stats.cross_selects)
    if getattr(ctx, "schedule_rejects", None):
        stats.counts["schedule_rejects"] = int(ctx.schedule_rejects)
    if getattr(stats, "j_champion_j", None) is not None:
        stats.counts["j_champion"] = float(stats.j_champion_j)
        cross_j = getattr(stats, "j_cross_champion_j", None)
        stats.counts["j_cross_champion"] = None if cross_j is None else float(cross_j)
    if getattr(stats, "cross_weights", None):
        stats.counts["cross_charged"] = int(getattr(stats, "cross_charged", 0) or 0)
        stats.counts["cross_accepted"] = int(getattr(stats, "cross_accepted", 0) or 0)
    stats.counts["n_screens"] = int(getattr(stats, "n_screens", 0) or 0)
    status = "FEASIBLE_LIMIT"
    if stats.stop_reason in ("EVAL_LIMIT", "WALLCLOCK", "MAX_ROUNDS") and best_ev.feasible:
        status = "FEASIBLE_LIMIT"
    return SolveResult(best_plan, final_ev, status, stats)


def _remember_cross(stats, plan, ev, alg, ctx) -> bool:
    """Keep a cross plan beside the same-truck search. It does not replace that search."""
    from .evaluate import is_cross_sortie
    if plan is None or ev is None or not ev.feasible:
        return False
    if not any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        return False
    old_p = getattr(stats, "cross_champ_plan", None)
    old_e = getattr(stats, "cross_champ_ev", None)
    if old_e is not None and not _better_air(ev, plan, old_e, old_p, alg, ctx):
        return False
    stats.cross_champ_plan = plan.clone()
    stats.cross_champ_ev = ev
    return True


def _cross_base(stats, cur_plan, best_plan, best_ev, alg, ctx):
    """Propose the next cross from the cross champion once one exists."""
    cp = getattr(stats, "cross_champ_plan", None)
    ce = getattr(stats, "cross_champ_ev", None)
    if ce is not None and cp is not None and _better_air(ce, cp, best_ev, best_plan, alg, ctx):
        return cp, ce
    return cur_plan, best_ev


def _same_clock(stats: SearchStats) -> int:
    """Evaluations that belong to the same-truck loop. Cross proposals are excluded."""
    return int(stats.eval_requests) - int(getattr(stats, "cross_evals", 0) or 0)


def _progress(stats: SearchStats, budget: Budget) -> float:
    """Cooling follows iterations. S and X share this, so a cross evaluation does not change it."""
    if budget.wall_limit is not None and getattr(stats, "iter_cap", None) is None:
        used = time.perf_counter() - budget.start
        return max(0.0, min(1.0, used / budget.wall_limit))
    cap = getattr(stats, "iter_cap", None)
    if cap:
        return max(0.0, min(1.0, stats.iterations / max(1, int(cap))))
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
    # X-only tail. S never sets cross_weights, so this block does not run for S
    # and the destroy/repair update above is unchanged.
    w_c = getattr(stats, "cross_weights", None)
    if not w_c:
        return
    n_c = stats.cross_n
    s_c = stats.cross_s
    for k in w_c:
        if n_c[k] > 0:
            w_c[k] = max(alg.operator_min_weight,
                         (1 - alg.weight_reaction) * w_c[k] + alg.weight_reaction * s_c[k] / n_c[k])
        n_c[k] = 0
        s_c[k] = 0.0


def _decay_cross_share(stats, chosen: str) -> None:
    """X only. A charged cross that does not improve J loses share immediately."""
    w = stats.cross_weights
    stats.cross_fail_streak = int(getattr(stats, "cross_fail_streak", 0) or 0) + 1
    if chosen in w and chosen != "SKIP":
        w[chosen] = max(0.02, float(w[chosen]) * 0.25)
    w["SKIP"] = float(w.get("SKIP", 1.0)) + 2.0


def recovery_cross_attempt(stats) -> bool:
    """X recovery only. SKIP is the other outcome, so a failing cross loses the next draws."""
    _ensure_recovery_cross_weights(stats)
    chosen = _roulette(stats.cross_weights, stats.cross_rng)
    stats.cross_n[chosen] = stats.cross_n.get(chosen, 0) + 1
    stats.cross_selects[chosen] = stats.cross_selects.get(chosen, 0) + 1
    return chosen != "SKIP"


def _ensure_recovery_cross_weights(stats) -> None:
    if getattr(stats, "recovery_cross_ready", False):
        return
    names = ("SKIP", "CROSS")
    stats.cross_weights = {k: 1.0 for k in names}
    stats.cross_n = {k: 0 for k in names}
    stats.cross_s = {k: 0.0 for k in names}
    stats.cross_selects = {k: 0 for k in names}
    stats.cross_rng = random.Random(0)
    stats.cross_fail_streak = 0
    stats.recovery_cross_ready = True


def _ensure_cross_weights(stats) -> None:
    """X nominal only. Same reaction, segment, and floor as the destroy/repair weights."""
    if getattr(stats, "cross_weights", None):
        return
    names = ("SKIP", "MULTI", "RELIEVE", "RETARGET", "PAIR")
    stats.cross_weights = {k: 1.0 for k in names}
    stats.cross_n = {k: 0 for k in names}
    stats.cross_s = {k: 0.0 for k in names}
    stats.cross_selects = {k: 0 for k in names}
    stats.cross_rng = random.Random(0)


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
        # v1.3 nominal, S and X: the same timeline screen. A candidate that does not
        # beat the champion plain J is not charged. Recovery keeps charging its
        # same-truck neighbours; cross rescues are screened at the catalog.
        if (budget is not None and getattr(ctx.alg, "v13_rules", False)
                and ctx.mode == "nominal"):
            from .cross_nominal import screen_nominal_j
            slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0)
            tol = float(getattr(ctx.alg, "cost_tolerance_yuan", 1e-4) or 1e-4)
            if screen_nominal_j(
                    p, inst, phys, ctx.H, slack, getattr(stats, "j_champion_j", None), tol, stats) is None:
                stats.aud("SCREEN", "skip")
                continue
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
                if getattr(alg, "v13_rules", False) and ctx.mode == "nominal":
                    from .cross_nominal import screen_nominal_j
                    slack = float(getattr(alg, "x_rendezvous_slack_s", 90.0) or 90.0)
                    tol = float(getattr(alg, "cost_tolerance_yuan", 1e-4) or 1e-4)
                    if screen_nominal_j(
                            cand, inst, phys, ctx.H, slack,
                            getattr(stats, "j_champion_j", None), tol, stats) is None:
                        continue
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


def _retarget_entries(plan: Plan, ctx: SolveContext, k: int) -> list[dict]:
    """在当前计划上，按代理成本排序给出至多 k 个“新的”接机目标(车, 访问/支援点)，保持当前继续空送的票不变.

    S 只考虑原放飞车的停靠点；X 考虑全部在班车辆（含支援访问，即另一辆车绕路来接 = CROSS_TRUCK_DETOUR）。
    已经试过的目标不重复(ctx.retarget_tried)。"""
    from .recovery_milp import _d, _ground_cost, build_stops
    inst, phys, state = ctx.inst, ctx.phys, ctx.state
    frag = plan.sorties.get(ctx.frag_sid)
    if frag is None or not frag.started or frag.start_pos is None:
        return []
    cur_rec = plan.visits.get(frag.rec_vid)
    cur_key = (cur_rec.truck, frag.rec_vid) if cur_rec is not None else None
    served = list(frag.air)
    hand = list(frag.handover)
    mass = {p: inst.parcel_mass[p] for p in served + hand}
    m_tot = sum(mass.values())
    ds = state.drone_start.get(frag.drone)
    e0 = ds.energy if ds is not None else state.drone_energy.get(frag.drone, phys.e_cap)
    stops = build_stops(plan, frag, inst, phys, state, ctx.strategy)
    items = []
    for st in stops:
        if not st.support and (st.truck, st.ref) == cur_key:
            continue
        key = (st.truck, st.ref, st.support, tuple(served))
        if key in ctx.retarget_tried:
            continue
        cost = st.cost
        for p in hand:
            c = inst.customer(inst.parcel_to_customer[p])
            cost += _ground_cost(st, c.customer_id, (c.x, c.y), phys)
        cur, m_cur, t_d, en = frag.start_pos, m_tot, 0.0, 0.0
        for p in served:
            c = inst.customer(inst.parcel_to_customer[p])
            d = _d(cur, (c.x, c.y))
            en += phys.fly_energy_kwh(d, m_cur) + phys.hover_energy_kwh(phys.air_service_s, m_cur)
            t_d += d / phys.drone_speed_m_s + phys.air_service_s
            m_cur = max(0.0, m_cur - mass[p])
            cur = (c.x, c.y)
        d = _d(cur, st.pos)
        en += phys.fly_energy_kwh(d, m_cur)
        t_d += d / phys.drone_speed_m_s
        a = st.arrival - state.t0
        cost += phys.cost_depot_kwh * (en + phys.hover_power(m_tot) * max(0.0, a - t_d) / 3600.0)
        cost += phys.wage_per_s * max(0.0, t_d - a)
        if en > e0 - phys.e_min + phys.energy_tol:
            continue
        items.append((cost, st.truck, str(st.ref), key, st))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    out = []
    for c_, tk_, rf, key, st in items[:k]:
        ctx.retarget_tried.add(key)
        out.append({"truck": st.truck, "kind": "support" if st.support else "visit", "ref": st.ref,
                    "support": st.support, "served": list(served), "est": c_})
    return out


def try_recovery_retarget(plan: Plan, ctx: SolveContext, budget: Budget, stats: SearchStats):
    """RECOVERY_RETARGET：在当前最优计划上重选接机车/接机点（保留别处已找到的改进）.

    S/X 同一算子、同样的评价次数 retarget_n 与频率；X 的候选可含其他车辆绕路来接(CROSS_TRUCK_DETOUR)。"""
    from .recovery import build_residual_candidate
    if ctx.frag_sid is None:
        return None, None
    best_p, best_ev = None, None
    for entry in _retarget_entries(plan, ctx, ctx.alg.retarget_n):
        if budget.evals_left() <= 0:
            break
        cands = build_residual_candidate(plan, ctx.frag_sid, entry, ctx.inst, ctx.phys, ctx.state,
                                         ctx.ground_required, ctx.strategy)
        for cand in cands:
            if budget.evals_left() <= 0:
                break
            ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "RECOVERY_RETARGET", stats, budget)
            if ev is None:
                break
            f_ = plan.sorties[ctx.frag_sid]
            tag = "RETARGET_CROSS" if entry["truck"] != (f_.launch_truck or f_.truck) else "RETARGET_SAME"
            stats.destroy_used[tag] = stats.destroy_used.get(tag, 0) + 1
            if ev.feasible and (best_ev is None or _better_air(ev, cand, best_ev, best_p, ctx.alg, ctx)):
                best_p, best_ev = cand, ev
            break
    return best_p, best_ev


def try_refly(plan: Plan, ctx: SolveContext, budget: Budget, stats: SearchStats):
    """X 专属：地面绕路 vs 跨车再飞，至多评价 1 个候选（计入同一份恢复预算）。"""
    from .refly import propose
    best_p, best_ev = None, None
    for tag, cand in propose(plan, ctx, 1):
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "REFLY", stats, budget)
        if ev is None:
            break
        stats.destroy_used[tag] = stats.destroy_used.get(tag, 0) + 1
        if ev.feasible and (best_ev is None or _better_air(ev, cand, best_ev, best_p, ctx.alg, ctx)):
            best_p, best_ev = cand, ev
    return best_p, best_ev


def try_cross_truck_ops(plan: Plan, ctx: SolveContext, budget: Budget, stats: SearchStats):
    """X 专用跨车算子入口（见 cross_ops.propose）：每个候选评价 1 次（几何继承 λ）."""
    from .cross_ops import propose
    best_p, best_ev = None, None
    for tag, cand in propose(plan, ctx, ctx.alg.cross_n, ctx.cross_tried):
        if budget.evals_left() <= 0:
            break
        ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H, "CROSS_OP", stats, budget)
        if ev is None:
            break
        stats.destroy_used[tag] = stats.destroy_used.get(tag, 0) + 1
        if ev.feasible:
            stats.destroy_used[tag + "_FEAS"] = stats.destroy_used.get(tag + "_FEAS", 0) + 1
            if best_ev is None or _better_air(ev, cand, best_ev, best_p, ctx.alg, ctx):
                best_p, best_ev = cand, ev
    return best_p, best_ev


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
        launch = None
        if ctx.frag_sid is not None and ctx.frag_sid in (getattr(cat, "res_plan", None) or plan).sorties:
            frag = (getattr(cat, "res_plan", None) or plan).sorties[ctx.frag_sid]
            launch = frag.launch_truck or frag.truck
        is_cross = bool(getattr(ctx, "strategy", None) == "X" and launch is not None
                        and entry.get("truck") != launch)
        if getattr(ctx.alg, "v13_rules", False) and is_cross:
            if not recovery_cross_attempt(stats):
                continue
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
            if getattr(ctx.alg, "v13_rules", False):
                from .cross_nominal import screen_recovery_cost
                slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 90.0) or 90.0)
                tol = float(getattr(ctx.alg, "cost_tolerance_yuan", 1e-4) or 1e-4)
                if screen_recovery_cost(
                        cand, ctx.inst, ctx.phys, ctx.H, slack, ctx.state,
                        getattr(stats, "screen_champion_cost", None), tol, stats) is None:
                    if is_cross:
                        _decay_cross_share(stats, "CROSS")
                    break
            ev = eval_counted(cand, ctx.inst, ctx.phys, ctx.state, ctx.H,
                              "RECOVERY_INITIAL_BASE", stats, budget)
            if ev is None:
                break
            if ev.feasible and (best_ev is None or _better_air(ev, cand, best_ev, best_p, ctx.alg, ctx)):
                best_p, best_ev = cand, ev
                if is_cross:
                    _ensure_recovery_cross_weights(stats)
                    stats.cross_weights["CROSS"] = stats.cross_weights.get("CROSS", 1.0) + 4.0
                    stats.cross_fail_streak = 0
            elif is_cross:
                _decay_cross_share(stats, "CROSS")
            break
    return best_p, best_ev
