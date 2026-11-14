#!/usr/bin/env python3
"""Choose M1 and M2 on tune seeds 101-110 only.

The estimator is J_hat of a shared deterministic recourse policy (failed air
orders moved to ground, then one full evaluation). Each scenario is one
evaluation, so M1+M2 must stay inside the 1000-evaluation nominal budget.
Environment seeds other than 101-110 are not read.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tdr.config import PhysicalConfig, load_package
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.hybrid import build_recourse
from tdr.schedule import initial_state
from tdr.v13 import j_hat, physical_kwargs_from_resolved, scenario_rng, verify_draft_config

CASES = ("C50", "R50", "RC50", "C100", "R100", "RC100")
TUNE = list(range(101, 111))
REF = 40  # reference sample, still far under the 1000 cap


def _cost(plan, inst, phys, failed, allow_cross, H):
    state = initial_state(inst, phys)
    state.known_air_failures = set(failed)
    repaired = build_recourse(plan, frozenset(failed), inst, phys, allow_cross)
    ev = evaluate_plan(repaired, inst, phys, state, H, "SCENARIO")
    if ev is None or not ev.feasible or ev.cost is None:
        return None
    return float(ev.cost)


def _draw(case_id, ids, m1, m2, seed):
    rng = scenario_rng(case_id, seed)
    singles = [frozenset(rng.sample(ids, 1)) for _ in range(m1)]
    pairs = [frozenset(rng.sample(ids, 2)) for _ in range(m2)]
    return singles, pairs


def main():
    cfg, _ = verify_draft_config()
    pkg = load_package(ROOT / "data" / "package_light.json")
    base = ROOT / "r6/results/round11_tune/R11/nominal"
    rows = []
    # Precompute reference scenario costs once per plan. Prefixes of the same
    # stream are the nested samples, so rankings at small M are comparable.
    bank = {}
    for cid in CASES:
        phys = PhysicalConfig(**physical_kwargs_from_resolved(cfg, cid))
        inst = load_instance(pkg, cid)
        H = cfg["cases"][cid]["H_case_s"]
        ids = [c.parcel_id for c in inst.customers]
        plans = {}
        for label, path, cross in (
            ("S", base / "S" / cid, False),
            ("X", base / "X" / cid, True),
        ):
            if not (path / "nominal_plan.json").exists():
                continue
            plan, _, _ = load_case_nominal(inst, path)
            plans[label] = (plan, cross)
        singles, pairs = _draw(cid, ids, REF, REF, cfg["seeds"]["base_algorithm_seed"])
        for label, (plan, cross) in plans.items():
            sc = [_cost(plan, inst, phys, s, cross, H) for s in singles]
            pc = [_cost(plan, inst, phys, s, cross, H) for s in pairs]
            bank[(cid, label)] = (sc, pc)
            finite_s = [c for c in sc if c is not None]
            finite_p = [c for c in pc if c is not None]
            print(f"{cid} {label} finite {len(finite_s)}/{REF} {len(finite_p)}/{REF}", flush=True)
        # Tune-seed check under the same policy. These seeds are not used to draw M.
        tune_costs = {label: [] for label in plans}
        for seed in TUNE:
            failed = set(HiddenWorld(inst, cid, seed).finish_episode().hidden_failure_parcels)
            for label, (plan, cross) in plans.items():
                tune_costs[label].append(_cost(plan, inst, phys, failed, cross, H))
        rows.append({"case": cid, "tune_mean": {k: (None if any(v is None for v in vs) else float(np.mean(vs)))
                                                for k, vs in tune_costs.items()}})

    grid = [2, 4, 6, 8, 10, 15, 20, 30, 40]
    best = None
    report_grid = []
    for m in grid:
        ranks = {}
        rels = []
        ok = True
        for cid in CASES:
            scores = {}
            for label in ("S", "X"):
                sc, pc = bank.get((cid, label), (None, None))
                if sc is None:
                    continue
                ss = [c for c in sc[:m] if c is not None]
                pp = [c for c in pc[:m] if c is not None]
                # A prefix that lost every single or every pair has no J_hat.
                if not ss or not pp:
                    ok = False
                    scores[label] = None
                    continue
                scores[label] = j_hat(ss, pp)
                finite_s = [c for c in sc if c is not None]
                finite_p = [c for c in pc if c is not None]
                if len(finite_s) < 2 or len(finite_p) < 2:
                    rels.append(float("inf"))
                else:
                    se = 0.5 * ((statistics.pstdev(finite_s) ** 2 / m + statistics.pstdev(finite_p) ** 2 / m) ** 0.5)
                    rels.append(se / abs(scores[label]) if scores[label] else float("inf"))
            if "S" in scores and "X" in scores and scores["S"] is not None and scores["X"] is not None:
                ranks[cid] = "X" if scores["X"] < scores["S"] else "S"
            else:
                ok = False
        ref_ranks = {}
        for cid in CASES:
            scs = [c for c in bank[(cid, "S")][0] if c is not None]
            pcs = [c for c in bank[(cid, "S")][1] if c is not None]
            scx = [c for c in bank[(cid, "X")][0] if c is not None]
            pcx = [c for c in bank[(cid, "X")][1] if c is not None]
            if not scs or not pcs or not scx or not pcx:
                ref_ranks[cid] = None
                continue
            js, jx = j_hat(scs, pcs), j_hat(scx, pcx)
            ref_ranks[cid] = "X" if jx < js else "S"
        agree = all(ranks.get(c) == ref_ranks.get(c) for c in CASES)
        worst_rel = max(rels) if rels else float("inf")
        report_grid.append({"M": m, "agree_with_M40": agree, "worst_rel_se": worst_rel, "ranks": ranks, "ok": ok})
        print(f"M={m} agree={agree} worst_rel_se={worst_rel:.4f} ok={ok}", flush=True)
        if ok and agree and worst_rel <= 0.02 and best is None:
            best = m
    if best is None:
        # Fall back to the smallest M that matches the reference ranking.
        for row in report_grid:
            if row["ok"] and row["agree_with_M40"]:
                best = row["M"]
                break
    if best is None:
        best = REF
    out = {
        "M1": best,
        "M2": best,
        "rule": "smallest equal M where J_hat ranking matches M=40 and worst relative SE <= 0.02; "
                "else smallest ranking match. Tune seeds 101-110 are a check, not the sample.",
        "grid": report_grid,
        "tune_seed_means": rows,
        "seeds_used": "101-110 only, plus the scenario stream of base_algorithm_seed (no environment seed)",
        "seeds_not_used": ["1-10", "2001-2010", "1001-1010", "3001-3030", "4001-4030"],
        "policy": "deterministic ground recourse of the published round-11 nominal plans; "
                  "not the episode ALNS. Used only to size M.",
    }
    dest = ROOT / "r6/results/v13_m_selection.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print("chosen", best, "wrote", dest)


if __name__ == "__main__":
    main()
