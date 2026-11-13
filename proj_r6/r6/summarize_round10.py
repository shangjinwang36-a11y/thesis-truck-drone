"""第 10 轮汇总。开发集和调参集都读已经落盘的 episodes.json，不重新抽样。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from summarize_round9 import (  # noqa: E402
    CASES,
    funnel,
    load_rows,
    nominal_table,
    report_block,
)
from tdr.fairness import fair_cost, paired_on  # noqa: E402

ROUND9_DEV = -0.06282517956812037


def per_case(rows, left: str, right: str) -> dict:
    out = {}
    for case in CASES:
        part = [row for row in rows if row["case"] == case]
        out[case] = paired_on(part, left, right, fair_cost)
    return out


def r50_seeds(rows) -> list[dict]:
    out = []
    for row in rows:
        if row.get("case") != "R50":
            continue
        s = fair_cost(row.get("S"))
        r = fair_cost(row.get("R"))
        x = fair_cost(row.get("X"))
        ns = (row.get("S_nominal") or {}).get("cost")
        out.append({
            "seed": row.get("seed"),
            "status": [((row.get(k) or {}).get("status")) for k in ("S", "R", "X")],
            "S": s, "R": r, "X": x,
            "d_SX": None if s is None or x is None else x - s,
            "d_SR": None if s is None or r is None else r - s,
            "d_RX": None if r is None or x is None else x - r,
            "rel_SX": None if not ns or s is None or x is None else (x - s) / ns,
            "fails": [((row.get(k) or {}).get("n_fail_events")) for k in ("S", "R", "X")],
            "cross_nom": [((row.get(k + "_nominal") or {}).get("n_cross")) for k in ("S", "R", "X")],
        })
    return out


def main() -> None:
    tune = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("r6/results/round10_tune")
    dev = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("r6/results/round10_dev")
    r9 = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("r6/results/round9_dev")
    final = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    r9_rows = load_rows(r9 / "episodes.json")
    payload = {
        "round9_dev": {
            "report": report_block(r9_rows),
            "per_case_SR": per_case(r9_rows, "S", "R"),
            "per_case_RX": per_case(r9_rows, "R", "X"),
            "per_case_SX": per_case(r9_rows, "S", "X"),
            "r50_seeds": r50_seeds(r9_rows),
        },
        "threshold_dev_delta_over_CS": ROUND9_DEV,
    }
    if (tune / "episodes.json").exists():
        tune_rows = load_rows(tune / "episodes.json")
        payload["tune"] = report_block(tune_rows)
        payload["tune_nominal"] = nominal_table(tune, "R10")
        payload["tune_funnel"] = funnel(tune / "R10" / "nominal")
        payload["tune_per_case_SX"] = per_case(tune_rows, "S", "X")
    if (dev / "episodes.json").exists():
        dev_rows = load_rows(dev / "episodes.json")
        block = report_block(dev_rows)
        got = block["fair_SX"].get("delta_over_CS_mean")
        payload["dev"] = block
        payload["dev_per_case_SX"] = per_case(dev_rows, "S", "X")
        payload["dev_per_case_SR"] = per_case(dev_rows, "S", "R")
        payload["dev_per_case_RX"] = per_case(dev_rows, "R", "X")
        payload["dev_not_worse_than_round9"] = (
            got is not None and got <= ROUND9_DEV + 1e-12)
    if final is not None and (final / "episodes.json").exists():
        final_rows = load_rows(final / "episodes.json")
        payload["final"] = report_block(final_rows)
        payload["final_per_case_SX"] = per_case(final_rows, "S", "X")
        payload["final_per_case_SR"] = per_case(final_rows, "S", "R")
        payload["final_per_case_RX"] = per_case(final_rows, "R", "X")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out = tune / "round10_summary.json"
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    if "dev" in payload:
        print("dev Δ/CS", payload["dev"]["fair_SX"].get("delta_over_CS_mean"),
              "not_worse", payload["dev_not_worse_than_round9"])
    if "tune" in payload:
        print("tune Δ/CS", payload["tune"]["fair_SX"].get("delta_over_CS_mean"))


if __name__ == "__main__":
    main()
