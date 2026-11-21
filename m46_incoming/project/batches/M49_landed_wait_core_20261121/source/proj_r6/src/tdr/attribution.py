"""四策略对照和跨案例汇总。种子 1001 起的正式检验在算法冻结之后才跑。

S：同车名义，同车恢复。
R：冻结的 S 名义，X 的恢复。
X0：与 X 相同的算法和预算，但名义阶段不允许跨车。当前代码里这就是 S 的名义。
X：名义和恢复都允许跨车。
R−S 是恢复共享，X0−R 是同车搜索的差异，X−X0 是名义跨车本身。
"""
from __future__ import annotations

import random


def holm(pvalues: list[float]) -> list[float]:
    """Holm 逐步校正。输入里的 None 原样留空。"""
    indexed = [(i, p) for i, p in enumerate(pvalues) if p is not None]
    indexed.sort(key=lambda item: item[1])
    m = len(indexed)
    adj = [None] * len(pvalues)
    running = 0.0
    for rank, (i, p) in enumerate(indexed):
        value = min(1.0, (m - rank) * float(p))
        running = max(running, value)
        adj[i] = running
    return adj


def bootstrap_mean_ci(deltas: list[float], n_boot: int = 2000, seed: int = 20261111,
                      alpha: float = 0.05) -> dict:
    xs = [float(x) for x in deltas if x is not None]
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "ci95": [None, None]}
    mean = sum(xs) / n
    if n == 1:
        return {"n": 1, "mean": mean, "ci95": [None, None]}
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        draw = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(draw) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"n": n, "mean": mean, "ci95": [lo, hi]}


def case_aggregate(by_case: dict[str, dict]) -> dict:
    """每个案例先取均值，再对案例等权；另给按名义成本加权的节省。

    by_case[case] = {"delta_mean": float, "nominal_mean": float, "n": int}
    """
    rows = [(name, row) for name, row in by_case.items()
            if row.get("delta_mean") is not None]
    if not rows:
        return {"n_cases": 0}
    equal = sum(row["delta_mean"] for _, row in rows) / len(rows)
    weight = sum(row.get("nominal_mean") or 0.0 for _, row in rows)
    weighted = None
    if weight:
        weighted = sum((row.get("nominal_mean") or 0.0) * row["delta_mean"] for _, row in rows) / weight
    return {"n_cases": len(rows), "equal_weight_mean": equal,
            "cost_weighted_mean": weighted}
