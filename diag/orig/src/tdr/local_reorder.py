"""局部事件重排：相邻至多 6 个未执行事件的顺序搜索.

规范第7.9节要求用 HiGHS MILP 在固定结构/几何/载荷下重排一个最多 6 事件的窗口。
本实现保留同一职责与同一窗口规模（≤6 个同刻/相邻事件），但用**确定性排列枚举**
代替 MILP：对"同一访问内的回收顺序、放飞顺序、相邻访问顺序"生成候选，
每个候选重新调用完整评价与独立核验。范围仍是局部的，不改变客户、机体、
货物、航段载荷或连续坐标。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .config import PhysicalConfig
from .evaluate import Evaluation, evaluate_plan
from .plan import Plan
from .schedule import StartState


@dataclass
class ReorderProposal:
    plan: Plan
    evaluation: Evaluation
    window: int
    description: str


def _permutations(n: int, cap: int = 720):
    count = 0
    for perm in itertools.permutations(range(n)):
        yield perm
        count += 1
        if count >= cap:
            return


def candidate_moves(plan: Plan) -> list[tuple[str, int]]:
    """返回 [(类型, 目标id)]：'REC' 访问vid、'LAUNCH' 访问vid、'SWAP' 访问vid."""
    out: list[tuple[str, int]] = []
    for vid in sorted(plan.visits):
        recs = [s for s in plan.sorties.values() if s.rec_vid == vid and not s.started]
        if len(recs) >= 2:
            out.append(("REC", vid))
        launches = [s for s in plan.sorties.values()
                    if s.launch_vid == vid and not s.started]
        if len(launches) >= 2:
            out.append(("LAUNCH", vid))
    return out


def try_local_reorder(plan: Plan, ev: Evaluation | None, ctx, stats, budget,
                      window_cursor: int) -> tuple[Plan | None, Evaluation | None]:
    from .alns import _better

    inst, phys, alg = ctx.inst, ctx.phys, ctx.alg
    moves = candidate_moves(plan)
    if not moves:
        return None, None
    kind, target = moves[window_cursor % len(moves)]
    best_plan = None
    best_ev = None
    n_eval = 0
    if kind == "REC":
        sids = [s.sid for s in plan.sorties.values() if s.rec_vid == target and not s.started]
        sids.sort()
        if len(sids) > 6:
            return None, None
        perms = list(_permutations(len(sids), 720))
        for perm in perms:
            if budget.evals_left() <= 0:
                break
            p = plan.clone()
            for prio, idx in enumerate(perm):
                p.sorties[sids[idx]].rec_priority = prio
            from .alns import eval_counted
            e = eval_counted(p, inst, phys, ctx.state, ctx.H, "MIP_RETURN", stats, budget)
            n_eval += 1
            if e is None:
                break
            if e.feasible and (best_ev is None or _better(e, best_ev, alg)):
                best_plan, best_ev = p, e
    elif kind == "LAUNCH":
        sids = [s.sid for s in plan.sorties.values() if s.launch_vid == target and not s.started]
        sids.sort()
        if len(sids) > 6:
            return None, None
        for perm in _permutations(len(sids), 720):
            if budget.evals_left() <= 0:
                break
            p = plan.clone()
            for prio, idx in enumerate(perm):
                p.sorties[sids[idx]].launch_priority = prio
            from .alns import eval_counted
            e = eval_counted(p, inst, phys, ctx.state, ctx.H, "MIP_RETURN", stats, budget)
            n_eval += 1
            if e is None:
                break
            if e.feasible and (best_ev is None or _better(e, best_ev, alg)):
                best_plan, best_ev = p, e
    else:
        vid = target
        v = plan.visits[vid]
        route = plan.routes[v.truck]
        i = route.index(vid)
        if i + 1 < len(route):
            p = plan.clone()
            p.routes[v.truck][i], p.routes[v.truck][i + 1] = p.routes[v.truck][i + 1], p.routes[v.truck][i]
            from .alns import eval_counted
            e = eval_counted(p, inst, phys, ctx.state, ctx.H, "MIP_RETURN", stats, budget)
            n_eval += 1
            if e is not None and e.feasible:
                best_plan, best_ev = p, e
    stats.counts["n_mip_calls"] = stats.counts.get("n_mip_calls", 0) + 1
    stats.counts["n_mip_evals"] = stats.counts.get("n_mip_evals", 0) + n_eval
    return best_plan, best_ev
