#!/usr/bin/env python3
"""把不变量套到评价种子 1–10 的 60 对回合上。

这是审计，不是调参：不根据这些种子改规则。输出每对的回放违规、
S 跨车次数、以及和第四轮已发表成本是否一致。
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


def audit_one(args):
    pkg_path, case, seed, budget, nom_root = args
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.hidden_world import bernoulli_failure_flags, make_world
    from tdr.invariants import check_episode
    from tdr.schedule import initial_state
    from tdr import simulate

    pkg = json.loads(Path(pkg_path).read_text(encoding="utf-8"))
    phys, alg, _, _ = rr.configs(pkg, "R4")
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get("case_fleet"), case)
    alg.failure_prob = 0.2
    hidden = sorted(bernoulli_failure_flags(case, seed, [c.parcel_id for c in inst.customers], 0.2))
    noms = {}
    for side in ("S", "X"):
        noms[side] = load_case_nominal(inst, Path(nom_root) / side / case)
    H = noms["S"][2]
    out = {"case": case, "seed": seed, "H_S": H, "hidden_n": len(hidden), "sides": {}}
    t0 = time.perf_counter()
    for side in ("S", "X"):
        plan, _, _ = noms[side]
        nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
        world = make_world(inst, case, seed, "bernoulli", 0.2)
        # 再读一次隐藏集合，确认和策略无关
        flags = sorted(world._HiddenWorld__failed)
        rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
        ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, side, alg, rngs,
                                  recovery_eval_budget=budget, cut_mode="snapshot",
                                  max_replans=len(inst.customers))
        rep = check_episode(ep, inst, phys)
        rep["hidden_match"] = flags == hidden
        rep["n_replans"] = max(0, len(ep.replans) - 1)
        rep["wall_s"] = ep.wall_s
        out["sides"][side] = rep
    out["wall_s"] = time.perf_counter() - t0
    print(f"[audit] {case} seed={seed} "
          f"S={out['sides']['S']['status']}/{out['sides']['S']['ok']} "
          f"X={out['sides']['X']['status']}/{out['sides']['X']['ok']}",
          flush=True)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="r6/results/round5_audit")
    ap.add_argument("--nom", default="r6/results/round3")
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--round4", default="r6/results/round4/episodes.json")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    nom = Path(args.nom) / "R3" / "nominal"
    jobs = [("data/package_light.json", case, seed, args.budget, str(nom))
            for case in ["C50", "R50", "RC50", "C100", "R100", "RC100"]
            for seed in range(1, 11)]
    t0 = time.perf_counter()
    if args.workers <= 1:
        rows = [audit_one(j) for j in jobs]
    else:
        with Pool(args.workers) as pool:
            rows = pool.map(audit_one, jobs)
    prev = { (r["case"], r["seed"]): r for r in json.loads(Path(args.round4).read_text(encoding="utf-8")) }
    diffs = []
    n_bad = 0
    for row in rows:
        old = prev[(row["case"], row["seed"])]
        for side in ("S", "X"):
            cur = row["sides"][side]
            if not cur["ok"] or not cur["hidden_match"]:
                n_bad += 1
            oc = old[side].get("cost")
            if cur["status"] != old[side].get("status") or (
                    cur["cost"] is not None and oc is not None and abs(cur["cost"] - oc) > 1e-6):
                diffs.append({
                    "case": row["case"], "seed": row["seed"], "side": side,
                    "status_old": old[side].get("status"), "status_new": cur["status"],
                    "cost_old": oc, "cost_new": cur["cost"],
                    "violations": cur["violations"][:6],
                })
    summary = {
        "n_jobs": len(rows),
        "n_invariant_failures": n_bad,
        "n_result_diffs_vs_round4": len(diffs),
        "diffs": diffs,
        "wall_s": time.perf_counter() - t0,
    }
    (out / "audit.json").write_text(json.dumps({"summary": summary, "rows": rows},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    print("AUDIT", json.dumps(summary, ensure_ascii=False)[:2000])
    print("EXIT", 0 if n_bad == 0 else 1)


if __name__ == "__main__":
    main()
