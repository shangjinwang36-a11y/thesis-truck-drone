"""名义搜索的情景账本。

规划样本用标签 ``nominal-scenario``，和评价种子 1–10 的 ``bernoulli`` 流不是同一批。
``scenario_eval_cap > 0`` 时，情景补救单独记账，S 和 X 各自一份上限，不占用 1000 次物理评价。
``scenario_screen_yuan > 0`` 时，真实成本变差超过该值的候选不做情景评价。
"""
from __future__ import annotations


def screen_skips_scenario(new_cost: float | None, old_cost: float | None, screen: float) -> bool:
    """真实成本已经差过门槛时，不再花情景评价。门槛为 0 表示不筛。"""
    if screen <= 0 or new_cost is None or old_cost is None:
        return False
    return float(new_cost) > float(old_cost) + float(screen)


def phase2_slices(limit: int) -> tuple[int, int]:
    """阶段 2 预算分成两个起点。第二个为 0 时不再另起一次搜索。两者之和不超过 limit。"""
    limit = max(0, int(limit))
    if limit <= 1:
        return limit, 0
    half = limit // 2
    return half, limit - half


def scenario_budget_for(alg, case_id: str, allow_cross: bool, fallback):
    """返回这次情景补救该扣的预算。cap 为 0 时沿用物理预算。"""
    cap = int(getattr(alg, "scenario_eval_cap", 0) or 0)
    if cap <= 0 or fallback is None:
        return fallback
    pools = getattr(alg, "_scenario_budgets", None)
    if pools is None:
        pools = {}
        alg._scenario_budgets = pools
    key = (case_id, bool(allow_cross))
    budget = pools.get(key)
    if budget is None:
        from .alns import Budget
        budget = Budget(cap, None)
        budget.scenario_ledger = True
        pools[key] = budget
    return budget
