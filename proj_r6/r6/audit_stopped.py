#!/usr/bin/env python3
"""只重放第四轮里停止的那一侧，检查已执行前缀的不变量。

搜索与成本应与第四轮一致。这一步专门确认：停止回合不再丢掉前缀日志，
并且前缀里没有负电量、机位超限、重复交付或 S 的跨车回收。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

spec = importlib.util.spec_from_file_location("run_round2", ROOT / "r6" / "run_round2.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def audit_side(args):
    pkg_path, case, seed, side, budget, nom_root = args
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import episode_metrics, load_case_nominal
    from tdr.hidden_world import make_world
    from tdr.invariants import check_episode
    from tdr.schedule import initial_state
    from tdr import simulate

    pkg = json.loads(Path(pkg_path).read_text(encoding="utf-8"))
    phys, alg, _, _ = rr.configs(pkg, "R4")
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get("case_fleet"), case)
    alg.failure_prob = 0.2
    plan, _, _ = load_case_nominal(inst, Path(nom_root) / side / case)
    plan_s, _, H = load_case_nominal(inst, Path(nom_root) / "S" / case)
    del plan_s
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    world = make_world(inst, case, seed, "bernoulli", 0.2)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, side, alg, rngs,
                              recovery_eval_budget=budget, cut_mode="snapshot",
                              max_replans=len(inst.customers))
    rep = check_episode(ep, inst, phys)
    metrics = episode_metrics(ep)
    rep.update({
        "case": case, "seed": seed, "side": side,
        "n_segments": len(ep.segments or []),
        "n_fail_events": metrics.get("n_fail_events"),
        "n_fail_rec": metrics.get("n_fail_rec"),
        "n_fail_cross": metrics.get("n_fail_cross"),
        "notes": (ep.notes or [])[:3],
    })
    print(f"[stopped] {case} seed={seed} {side} {rep['status']}/{rep['ok']} "
          f"seg={rep['n_segments']} cross={rep['n_fail_cross']} viol={rep['violations'][:3]}",
          flush=True)
    return rep


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="r6/results/round5_audit/stopped.json")
    ap.add_argument("--nom", default="r6/results/round3/R3/nominal")
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--round4", default="r6/results/round4/episodes.json")
    args = ap.parse_args()
    prev = json.loads(Path(args.round4).read_text(encoding="utf-8"))
    jobs = []
    for row in prev:
        for side in ("S", "X"):
            if row[side].get("status") != "COMPLETED_VERIFIED":
                jobs.append(("data/package_light.json", row["case"], row["seed"], side,
                             args.budget, args.nom))
    t0 = time.perf_counter()
    if args.workers <= 1:
        rows = [audit_side(j) for j in jobs]
    else:
        with Pool(args.workers) as pool:
            rows = pool.map(audit_side, jobs)
    diffs = []
    n_bad = 0
    for rep in rows:
        old = next(r for r in prev if r["case"] == rep["case"] and r["seed"] == rep["seed"])
        o = old[rep["side"]]
        if not rep["ok"]:
            n_bad += 1
        oc = o.get("cost")
        if rep["status"] != o.get("status") or (
                rep["cost"] is not None and oc is not None and abs(rep["cost"] - oc) > 1e-6):
            diffs.append({"case": rep["case"], "seed": rep["seed"], "side": rep["side"],
                          "status_old": o.get("status"), "status_new": rep["status"],
                          "cost_old": oc, "cost_new": rep["cost"],
                          "violations": rep["violations"][:6]})
    summary = {
        "n_jobs": len(rows),
        "n_invariant_failures": n_bad,
        "n_result_diffs_vs_round4": len(diffs),
        "diffs": diffs,
        "n_fail_cross_sum": sum(r["n_fail_cross"] or 0 for r in rows),
        "n_fail_rec_sum": sum(r["n_fail_rec"] or 0 for r in rows),
        "s_cross_events": sum((r["n_fail_cross"] or 0) for r in rows if r["side"] == "S"),
        "wall_s": time.perf_counter() - t0,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("STOPPED_AUDIT", json.dumps(summary, ensure_ascii=False)[:2000])
    print("EXIT", 0 if n_bad == 0 and not diffs else 1)


if __name__ == "__main__":
    main()
