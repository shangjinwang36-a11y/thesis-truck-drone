"""第 9 轮汇总：调参种子上的两种上限，以及开发集 1–10 的一次评价。

公平成本用回合里已经记下的 cost_fair。完成的回合是日志成本，停止的回合是卡车地面收尾。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdr.attribution import bootstrap_mean_ci, case_aggregate, holm  # noqa: E402
from tdr.fairness import completion_table, fair_cost, paired_on  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
FUNNEL_KEYS = ("generated", "energy", "schedule", "cap", "margin", "accepted")


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_x(base: list[dict], other: list[dict]) -> list[dict]:
    """用 other 的 X 换掉 base 的 X。S 和 R 仍是 base 的，因为上限不进入 S 的搜索。"""
    by = {(row["case"], row["seed"]): row for row in other}
    out = []
    for row in base:
        got = by[(row["case"], row["seed"])]
        copied = dict(row)
        copied["X"] = got.get("X")
        copied["X_nominal"] = got.get("X_nominal")
        out.append(copied)
    return out


def _both_completed(rows, left="S", right="X") -> dict:
    kept = []
    for row in rows:
        a, b = row.get(left) or {}, row.get(right) or {}
        if a.get("status") == "COMPLETED_VERIFIED" and b.get("status") == "COMPLETED_VERIFIED":
            kept.append(row)
    return paired_on(kept, left, right, lambda block: (block or {}).get("cost"))


def _case_lists(rows, left="S", right="X") -> dict[str, list[float]]:
    out = defaultdict(list)
    for row in rows:
        a = fair_cost(row.get(left))
        b = fair_cost(row.get(right))
        if a is None or b is None:
            continue
        out[row["case"]].append(b - a)
    return out


def _equal_weight(rows, left="S", right="X") -> dict:
    by = {}
    rel_lists = defaultdict(list)
    for case, deltas in _case_lists(rows, left, right).items():
        nominals = []
        for row in rows:
            if row["case"] != case:
                continue
            ns = (row.get("S_nominal") or {}).get("cost")
            a = fair_cost(row.get(left))
            b = fair_cost(row.get(right))
            if ns and a is not None and b is not None:
                nominals.append(ns)
                rel_lists[case].append((b - a) / ns)
        by[case] = {
            "delta_mean": sum(deltas) / len(deltas),
            "nominal_mean": (sum(nominals) / len(nominals)) if nominals else None,
            "n": len(deltas),
            "rel_mean": (sum(rel_lists[case]) / len(rel_lists[case])) if rel_lists[case] else None,
        }
    yuan = case_aggregate(by)
    rel_cases = {case: {"delta_mean": row["rel_mean"], "nominal_mean": row["nominal_mean"]}
                 for case, row in by.items()}
    return {"by_case": by, "yuan": yuan, "ratio": case_aggregate(rel_cases),
            "rel_lists": {key: list(value) for key, value in rel_lists.items()}}


def _stratified_boot(rel_lists: dict[str, list[float]], n_boot: int = 2000, seed: int = 20261111) -> dict:
    import random
    names = [name for name in CASES if rel_lists.get(name)]
    if not names:
        return {"n_cases": 0}
    point = sum(sum(rel_lists[name]) / len(rel_lists[name]) for name in names) / len(names)
    rng = random.Random(seed)
    draws = []
    for _ in range(n_boot):
        means = []
        for name in names:
            xs = rel_lists[name]
            sample = [xs[rng.randrange(len(xs))] for _ in range(len(xs))]
            means.append(sum(sample) / len(sample))
        draws.append(sum(means) / len(means))
    draws.sort()
    lo = draws[int(0.025 * n_boot)]
    hi = draws[min(n_boot - 1, int(0.975 * n_boot))]
    return {"equal_weight_mean": point, "ci95": [lo, hi], "n_cases": len(names), "n_boot": n_boot}


def _holm_cases(rows, left="S", right="X") -> list[dict]:
    raw = []
    detail = []
    for case in CASES:
        part = [row for row in rows if row["case"] == case]
        paired = paired_on(part, left, right, fair_cost)
        table = completion_table(part, left, right)
        detail.append({"case": case, "paired": paired, "completion": table})
        raw.append(paired.get("sign_p_two_sided"))
    adjusted = holm(raw)
    for row, p in zip(detail, adjusted):
        row["sign_p_holm"] = p
    return detail


def _cross_counts(rows) -> dict:
    out = {}
    for name in ("S", "R", "X"):
        nom = final = fail = 0
        n = 0
        for row in rows:
            block = row.get(name) or {}
            if not block:
                continue
            n += 1
            nom += int((row.get(name + "_nominal") or {}).get("n_cross") or 0)
            final += int(block.get("n_cross_final") or 0)
            fail += int(block.get("n_fail_cross") or 0)
        out[name] = {"n": n, "nominal_cross": nom, "recovery_cross_on_failure": fail,
                     "cross_left_in_final_plan": final}
    return out


def _add_audit(total: dict, audit: dict | None) -> None:
    if not audit:
        return
    bucket = audit.get("FUNNEL_CROSS") or {}
    for key in FUNNEL_KEYS:
        total[key] = total.get(key, 0) + int(bucket.get(key) or 0)


def funnel(nominal_root: Path) -> dict:
    total = {key: 0 for key in FUNNEL_KEYS}
    published = 0
    per_case = {}
    for case in CASES:
        path = nominal_root / "X" / case / "result.json"
        if not path.exists():
            continue
        meta = json.loads(path.read_text(encoding="utf-8"))
        one = {key: 0 for key in FUNNEL_KEYS}
        _add_audit(one, meta.get("audit"))
        _add_audit(one, meta.get("phase1_audit"))
        one["published"] = int(meta.get("n_cross_sorties") or 0)
        published += one["published"]
        per_case[case] = one
        for key in FUNNEL_KEYS:
            total[key] += one[key]
    total["published"] = published
    return {"total": total, "by_case": per_case}


def nominal_table(root: Path, preset: str) -> list[dict]:
    rows = []
    base = root / preset / "nominal"
    for case in CASES:
        s = json.loads((base / "S" / case / "result.json").read_text(encoding="utf-8"))
        x = json.loads((base / "X" / case / "result.json").read_text(encoding="utf-8"))
        sb, xb = s.get("cost_breakdown") or {}, x.get("cost_breakdown") or {}
        rows.append({
            "case": case,
            "S_cost": s.get("cost"), "X_cost": x.get("cost"),
            "S_makespan": s.get("makespan_s"), "X_makespan": x.get("makespan_s"),
            "cap": x.get("makespan_cap"), "cap_basis": x.get("cap_basis"),
            "search_cap": x.get("makespan_cap_effective"),
            "S_driver_s": sb.get("driver_s"), "X_driver_s": xb.get("driver_s"),
            "S_c_driver": sb.get("c_driver"), "X_c_driver": xb.get("c_driver"),
            "X_c_km": xb.get("c_km"), "S_c_km": sb.get("c_km"),
            "n_cross": x.get("n_cross_sorties"),
            "adopted_s": x.get("adopted_s_nominal"), "adopt_reason": x.get("adopt_reason"),
        })
    return rows


def report_block(rows) -> dict:
    return {
        "completion_SX": completion_table(rows, "S", "X"),
        "completion_SR": completion_table(rows, "S", "R"),
        "completion_RX": completion_table(rows, "R", "X"),
        "fair_SX": paired_on(rows, "S", "X", fair_cost),
        "fair_SR": paired_on(rows, "S", "R", fair_cost),
        "fair_RX": paired_on(rows, "R", "X", fair_cost),
        "both_SX": _both_completed(rows, "S", "X"),
        "both_SR": _both_completed(rows, "S", "R"),
        "both_RX": _both_completed(rows, "R", "X"),
        "equal": (lambda eq: (eq.pop("rel_lists"), eq)[1])(_equal_weight(rows, "S", "X")),
        "equal_boot": _stratified_boot(_equal_weight(rows, "S", "X")["rel_lists"]),
        "pooled_boot": bootstrap_mean_ci([
            (fair_cost(row.get("X")) - fair_cost(row.get("S"))) / (row.get("S_nominal") or {}).get("cost")
            for row in rows
            if fair_cost(row.get("S")) is not None and fair_cost(row.get("X")) is not None
            and (row.get("S_nominal") or {}).get("cost")
        ]),
        "holm_SX": _holm_cases(rows, "S", "X"),
        "cross": _cross_counts(rows),
    }


def main() -> None:
    tune = Path(sys.argv[1] if len(sys.argv) > 1 else "r6/results/round9_tune")
    shift = Path(sys.argv[2] if len(sys.argv) > 2 else "r6/results/round9_tune_shift")
    base_rows = load_rows(tune / "episodes.json")
    shift_rows = merge_x(base_rows, load_rows(shift / "episodes.json"))
    payload = {
        "nominal_makespan": nominal_table(tune, "R9"),
        "nominal_shift": nominal_table(tune, "R9H"),
        "fair_makespan": report_block(base_rows),
        "fair_shift": report_block(shift_rows),
        "funnel_makespan": funnel(tune / "R9" / "nominal"),
        "funnel_shift": funnel(tune / "R9H" / "nominal"),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else tune / "cap_compare.json"
    out.write_text(text, encoding="utf-8")
    a = payload["fair_makespan"]["fair_SX"]["delta_over_CS_mean"]
    b = payload["fair_shift"]["fair_SX"]["delta_over_CS_mean"]
    print(f"cap makespan Δ/CS {a}")
    print(f"cap shift    Δ/CS {b}")
    print(f"pick {'shift' if (b is not None and a is not None and b < a) else 'makespan'}")


if __name__ == "__main__":
    main()
