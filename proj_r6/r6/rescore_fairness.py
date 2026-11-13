"""用已有日志重放停止回合，并按卡车地面收尾重算第 7、8 轮。

完成回合的成本直接取日志，不再仿真。停止回合重放到日志里的同一停点，
核对 STOP_CONTEXT 一致之后，才采用地面收尾成本。
"""
from __future__ import annotations

import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_round2 import replay_one  # noqa: E402

from tdr.fairness import fairness_report  # noqa: E402


ROUNDS = (
    ("r6/results/round7", "R7", "r6/results/round7/R7/nominal"),
    ("r6/results/round8", "R8", "r6/results/round8/R8/nominal"),
)


def _stop_context(notes) -> str:
    for note in notes or []:
        if str(note).startswith("STOP_CONTEXT"):
            return str(note)
    return ""


def _jobs(rows, preset, nom):
    jobs = []
    for row in rows:
        for strat in ("S", "R", "X"):
            block = row.get(strat) or {}
            if not block or block.get("status") == "COMPLETED_VERIFIED":
                continue
            jobs.append((
                "data/package_light.json", preset, row["case"], row["seed"], 1000,
                nom, row.get("failure_mode") or "bernoulli", float(row.get("p") or 0.2),
                "n_cust", strat,
            ))
    return jobs


def _augment(rows, replayed):
    by = {(g["case"], g["seed"], g["strategy"]): g for g in replayed}
    out = []
    mismatches = []
    for row in rows:
        copied = dict(row)
        for strat in ("S", "R", "X"):
            block = row.get(strat)
            if not block:
                continue
            fresh = dict(block)
            if fresh.get("status") == "COMPLETED_VERIFIED":
                fresh["cost_fair"] = fresh.get("cost")
                fresh["ground_finish_status"] = "LOGGED_COMPLETE"
            else:
                got = by[(row["case"], row["seed"], strat)]
                same = (got["status"] == fresh.get("status")
                        and _stop_context(got.get("notes")) == _stop_context(fresh.get("notes")))
                fresh["replay_match"] = same
                fresh["ground_finish_status"] = got.get("ground_finish_status")
                fresh["ground_finish_cost"] = got.get("ground_finish_cost")
                if same:
                    fresh["cost_fair"] = got.get("ground_finish_cost")
                else:
                    fresh["cost_fair"] = None
                    mismatches.append({
                        "case": row["case"], "seed": row["seed"], "strategy": strat,
                        "logged": _stop_context(fresh.get("notes")),
                        "replay": _stop_context(got.get("notes")),
                        "logged_status": fresh.get("status"),
                        "replay_status": got.get("status"),
                    })
            copied[strat] = fresh
        out.append(copied)
    return out, mismatches


def main():
    for folder, preset, nom in ROUNDS:
        rows = json.loads(Path(folder, "episodes.json").read_text(encoding="utf-8"))
        jobs = _jobs(rows, preset, nom)
        print(f"{preset} replay {len(jobs)}", flush=True)
        with Pool(4) as pool:
            replayed = pool.map(replay_one, jobs)
        augmented, mismatches = _augment(rows, replayed)
        by_case = {}
        for case in sorted({r["case"] for r in augmented}):
            by_case[case] = fairness_report([r for r in augmented if r["case"] == case])
        payload = {
            "preset": preset,
            "rule": "truck ground delivery from the stop state; overtime via soft_h; no per-customer penalty",
            "n_replay": len(jobs),
            "n_mismatch": len(mismatches),
            "mismatches": mismatches,
            "overall": fairness_report(augmented),
            "by_case": by_case,
            "rows": [{
                "case": r["case"], "seed": r["seed"],
                **{s: {"status": (r.get(s) or {}).get("status"),
                       "cost": (r.get(s) or {}).get("cost"),
                       "cost_fair": (r.get(s) or {}).get("cost_fair"),
                       "ground_finish_status": (r.get(s) or {}).get("ground_finish_status")}
                   for s in ("S", "R", "X") if r.get(s)},
            } for r in augmented],
        }
        dest = Path(folder) / "fairness.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(preset, "mismatch", len(mismatches), "wrote", dest, flush=True)
        print(json.dumps(payload["overall"], ensure_ascii=False)[:2000], flush=True)


if __name__ == "__main__":
    main()
