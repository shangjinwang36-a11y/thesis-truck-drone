"""完成率、精确 McNemar，以及 60 对全部计入的地面收尾成本。

完成配对的成本比较仍然单独保留。这里的主比较不丢掉只完成一边的回合。
"""
from __future__ import annotations


def mcnemar_exact(n_only_left: int, n_only_right: int) -> dict:
    """不一致对上的精确 McNemar。零假设是两边各自独有的完成次数服从公平硬币。"""
    n = int(n_only_left) + int(n_only_right)
    if n == 0:
        return {"n_only_left": n_only_left, "n_only_right": n_only_right,
                "n_discordant": 0, "p_two_sided": None}
    from scipy.stats import binomtest
    p = float(binomtest(int(n_only_left), n, 0.5).pvalue)
    return {"n_only_left": int(n_only_left), "n_only_right": int(n_only_right),
            "n_discordant": n, "p_two_sided": p}


def _complete(block) -> bool:
    return (block or {}).get("status") == "COMPLETED_VERIFIED"


def fair_cost(block):
    """完成的回合用日志里的真实成本。停止的回合用地面收尾成本。没有就空着。"""
    if not block:
        return None
    if block.get("cost_fair") is not None:
        return block.get("cost_fair")
    if _complete(block):
        return block.get("cost")
    return block.get("ground_finish_cost")


def completion_table(rows, left: str, right: str) -> dict:
    both = only_left = only_right = neither = 0
    n_left = n_right = 0
    for r in rows:
        a = _complete(r.get(left))
        b = _complete(r.get(right))
        n_left += int(a)
        n_right += int(b)
        if a and b:
            both += 1
        elif a:
            only_left += 1
        elif b:
            only_right += 1
        else:
            neither += 1
    n = len(rows)
    return {
        "n": n,
        "complete_left": n_left,
        "complete_right": n_right,
        "rate_left": (n_left / n) if n else None,
        "rate_right": (n_right / n) if n else None,
        "both": both,
        "only_left": only_left,
        "only_right": only_right,
        "neither": neither,
        "mcnemar": mcnemar_exact(only_left, only_right),
    }


def paired_on(rows, left: str, right: str, cost_of) -> dict:
    deltas, rels = [], []
    missing = 0
    for r in rows:
        a = cost_of(r.get(left))
        b = cost_of(r.get(right))
        if a is None or b is None:
            missing += 1
            continue
        deltas.append(b - a)
        ns = (r.get("S_nominal") or {}).get("cost")
        if ns:
            rels.append((b - a) / ns)
    n = len(deltas)
    if n == 0:
        return {"n": 0, "missing": missing}
    mean = sum(deltas) / n
    if n >= 2:
        var = sum((d - mean) ** 2 for d in deltas) / (n - 1)
        half = 1.96 * (var ** 0.5) / (n ** 0.5)
        ci = [mean - half, mean + half]
    else:
        ci = [None, None]
    rmean = (sum(rels) / len(rels)) if rels else None
    if len(rels) >= 2:
        rv = sum((d - rmean) ** 2 for d in rels) / (len(rels) - 1)
        rhalf = 1.96 * (rv ** 0.5) / (len(rels) ** 0.5)
        rci = [rmean - rhalf, rmean + rhalf]
    else:
        rci = [None, None]
    n_right = sum(1 for d in deltas if d < -1e-9)
    n_left = sum(1 for d in deltas if d > 1e-9)
    return {
        "n": n,
        "missing": missing,
        "delta_mean": mean,
        "delta_ci95": ci,
        "delta_over_CS_mean": rmean,
        "delta_over_CS_ci95": rci,
        "sign_right_better": n_right,
        "sign_left_better": n_left,
        "sign_tie": n - n_right - n_left,
        "sign_p_two_sided": mcnemar_exact(n_right, n_left)["p_two_sided"],
    }


def fairness_report(rows, strategies=("S", "R", "X0", "X")) -> dict:
    present = [s for s in strategies if any(r.get(s) for r in rows)]
    tables = {}
    costs = {}
    for i, left in enumerate(present):
        for right in present[i + 1:]:
            key = f"{left}_vs_{right}"
            tables[key] = completion_table(rows, left, right)
            costs[key] = paired_on(rows, left, right, fair_cost)
    rates = {}
    n = len(rows)
    for s in present:
        k = sum(1 for r in rows if _complete(r.get(s)))
        rates[s] = {"complete": k, "n": n, "rate": (k / n) if n else None}
    return {"rates": rates, "completion": tables, "all_pairs_ground_finish": costs}
