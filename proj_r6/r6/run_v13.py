#!/usr/bin/env python3
"""v1.3 baseline: S, R, X on tune seeds 101-110 and dev seeds 1-10.

Final test seeds 4001-4030 are refused. R reuses S's nominal plan and does no
nominal search. X does not read S's search. H is the frozen per-map constant.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
M1 = 10
M2 = 10


def _apply_ablation(alg, name: str):
    """X-only switches. S ignores them. Every run uses the v1.3 objective."""
    alg.v13_x_rank = True
    alg.v13_x_rescue = True
    alg.v13_x_sync = True
    alg.v13_x_nominal = True
    alg.x_cross_from_start = True
    alg.x_energy_retarget = True
    alg.support_rendezvous = True
    if name == "norescue":
        alg.v13_x_rescue = False
    elif name == "norank":
        alg.v13_x_rank = False
    elif name == "nonominal":
        alg.v13_x_nominal = False
        alg.x_cross_from_start = False
        alg.x_energy_retarget = False
        alg.support_rendezvous = False
    elif name == "nosync":
        alg.v13_x_sync = False
        alg.x_energy_retarget = False
        alg.support_rendezvous = False
    return alg


def _alg(cfg, case_id, ablation: str = "full"):
    import dataclasses
    from tdr.config import AlgorithmConfig, PhysicalConfig
    from tdr.v13 import physical_kwargs_from_resolved
    phys = PhysicalConfig(**physical_kwargs_from_resolved(cfg, case_id))
    alg = AlgorithmConfig(
        v13_rules=True,
        v13_m1=M1,
        v13_m2=M2,
        nominal_eval_budget=1000,
        deterministic_recovery_eval_budget=1000,
        recovery_wallclock_seconds=60.0,
        recovery_decision="milp",
        reassign_adopt_only_if_best=True,
        joint_inflight_retarget=True,
        slot_aware_recovery=True,
        unlaunched_repair=True,
        x_cross_from_start=True,
        x_cross_robust=True,
        x_rendezvous_slack_s=90.0,
        x_energy_retarget=True,
        support_rendezvous=True,
        x_recovery_wider=True,
        cross_ops=True,
        scenario_aware=True,
        scenario_eval_cap=0,
        scenario_infeasible_penalty=None,
        expected_accept=True,
        x_adopt_s_nominal=False,
        x_s_second_start=False,
        x_adopt_s_if_cross=False,
        x_limit_new_air=False,
        x_risk_price_air=False,
    )
    # land_and_wait and soft_h stay at the resolved-config values (both false).
    alg.v13_H = float(cfg["cases"][case_id]["H_case_s"])
    alg.v13_n = int(cfg["cases"][case_id]["N_air_eligible"])
    _apply_ablation(alg, ablation)
    assert phys.land_and_wait is False and phys.soft_h is False and phys.swap_mode is True
    del dataclasses
    return phys, alg


def _nominal_one(args):
    cfg, case, strategy, out_root, ablation = args
    from tdr.data import load_instance
    from tdr.config import load_package
    from tdr.experiment import build_case_nominal
    from tdr.v13 import assert_seed_allowed
    del assert_seed_allowed
    pkg = load_package(ROOT / "data" / "package_light.json")
    phys, alg = _alg(cfg, case, ablation)
    inst = load_instance(pkg, case)
    dest = Path(out_root) / "nominal" / strategy / case
    t0 = time.perf_counter()
    if strategy == "R":
        return {"case": case, "strategy": "R", "nominal_evals": 0, "status": "REUSES_S"}
    meta = build_case_nominal(inst, phys, alg, dest, eval_budget=1000, cross_launch=(strategy == "X"))
    meta = dict(meta)
    meta["wall_s"] = time.perf_counter() - t0
    meta["strategy"] = strategy
    return {"case": case, "strategy": strategy, "status": meta.get("status"),
            "cost": meta.get("cost"), "nominal_evals": meta.get("nominal_eval_requests"),
            "H_s": meta.get("H_s"), "wall_s": meta["wall_s"]}


def _episode_one(args):
    cfg, case, seed, nom_root, ablation = args
    from tdr.config import load_package
    from tdr.data import load_instance
    from tdr.evaluate import evaluate_plan, is_cross_sortie
    from tdr.experiment import load_case_nominal
    from tdr.hidden_world import HiddenWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    from tdr.v13 import assert_seed_allowed, planner_log_record
    assert_seed_allowed(seed, formal=False)
    pkg = load_package(ROOT / "data" / "package_light.json")
    phys, alg = _alg(cfg, case, ablation)
    inst = load_instance(pkg, case)
    H = float(cfg["cases"][case]["H_case_s"])
    plan_s, _, _ = load_case_nominal(inst, Path(nom_root) / "nominal" / "S" / case)
    plan_x, _, _ = load_case_nominal(inst, Path(nom_root) / "nominal" / "X" / case)
    # Audit-only hidden set, built after the plans are fixed and not passed to the planner.
    hidden = list(HiddenWorld(inst, case, seed).finish_episode().hidden_failure_parcels)
    out = {"case": case, "seed": seed, "H": H}
    plans = {"S": (plan_s, "S"), "R": (plan_s, "X"), "X": (plan_x, "X")}
    for strat, (plan, recovery) in plans.items():
        nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
        rec = {"nominal_cost": nom.cost, "nominal_feasible": bool(nom.feasible),
               "n_cross": sum(1 for s in plan.sorties.values() if is_cross_sortie(plan, s)),
               "nominal_evals": 0 if strat == "R" else None}
        if not nom.feasible:
            rec.update(status="NO_LEGAL_COMPLETION_FOUND", cost=None, notes=nom.violations[:3])
            out[strat] = rec
            continue
        world = HiddenWorld(inst, case, seed)
        rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0, public_history=())
        t0 = time.perf_counter()
        ep = simulate.run_episode(inst, plan, nom, H, phys, world, recovery, alg, rngs,
                                  recovery_eval_budget=1000, recovery_wall_s=60.0,
                                  max_replans=len(inst.customers), ground_finish=True)
        walls = []
        evals = 0
        screens = 0
        hits = 0
        process_evals = []
        n_cross_rescues = 0
        for rep in ep.replans[1:]:
            stt = rep.stats or {}
            n_req = int(stt.get("n_eval_requests") or 0)
            process_evals.append(n_req)
            n_cross_rescues += int(bool(stt.get("cross_rescue")))
            evals += n_req
            screens += int(stt.get("n_screens") or 0)
            hits += int(stt.get("wall_hits") or 0)
            if stt.get("wall_s") is not None:
                walls.append(float(stt["wall_s"]))
        rec.update(
            status=getattr(ep, "v13_status", ep.status),
            cost=getattr(ep, "v13_cost", None),
            legacy_status=ep.status,
            recovery_evals=evals,
            recovery_screens=screens,
            max_process_evals=max(process_evals) if process_evals else 0,
            wall_hits=hits,
            wall_max_s=max(walls) if walls else 0.0,
            n_recoveries=max(0, len(ep.replans) - 1),
            n_cross_rescues=n_cross_rescues,
            episode_wall_s=time.perf_counter() - t0,
            ground_finish_status=ep.ground_finish_status,
        )
        # Planner-visible slice of the record. The hidden set stays in the audit block.
        out[strat] = planner_log_record(rec)
    out["audit"] = {"hidden_failure_parcels": hidden}
    return out


def _summarize(episodes, nominals):
    from tdr.v13 import holm, mcnemar_exact, saving_decomposition, sign_test, stratified_paired_bootstrap
    by = {c: [] for c in CASES}
    for ep in episodes:
        by[ep["case"]].append(ep)
    maps = {}
    sx_boot = {}
    pvalues = []
    for cid in CASES:
        rows = []
        for ep in by[cid]:
            row = {"seed": ep["seed"]}
            for k in "SRX":
                block = ep.get(k) or {}
                row[f"cost_{k}"] = block.get("cost")
                row[f"status_{k}"] = block.get("status")
            rows.append(row)
        dec = saving_decomposition(rows)
        for item in dec["srx"]:
            if abs(item["g_sx"] - (item["g_sr"] + item["g_rx"])) > 1e-8:
                raise SystemExit(f"saving identity failed on {cid}")
        diffs = [item["diff_sx"] for item in dec["sx_main"]]
        signed = sign_test(diffs) if diffs else {"tested": False, "pvalue": None, "wins": 0, "losses": 0, "ties": 0, "n_effective": 0}
        if signed.get("tested") and signed.get("pvalue") is not None:
            pvalues.append(signed["pvalue"])
        # Completion McNemar on the full seed list: completed vs not, S vs X.
        b = c = 0
        for ep in by[cid]:
            s_ok = (ep.get("S") or {}).get("status") in ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")
            x_ok = (ep.get("X") or {}).get("status") in ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")
            if s_ok and not x_ok:
                b += 1
            elif x_ok and not s_ok:
                c += 1
        def _rate(key, pred):
            blocks = [(ep.get(key) or {}) for ep in by[cid]]
            return sum(1 for b_ in blocks if pred(b_.get("status"))) / len(blocks) if blocks else None
        walls = [float((ep.get(k) or {}).get("wall_max_s") or 0.0) for ep in by[cid] for k in "SRX"]
        evals = [int((ep.get(k) or {}).get("recovery_evals") or 0) for ep in by[cid] for k in "SRX"]
        hits = sum(int((ep.get(k) or {}).get("wall_hits") or 0) for ep in by[cid] for k in "SRX")
        nom = {n["strategy"]: n for n in nominals if n["case"] == cid}
        maps[cid] = {
            "n": len(by[cid]),
            "n_sx": dec["n_sx"],
            "n_srx": dec["n_srx"],
            "mean_cost": {k: _mean([row[f"cost_{k}"] for row in rows if row[f"status_{k}"] in ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")]) for k in "SRX"},
            "mean_g_sx": (sum(i["g_sx"] for i in dec["sx_main"]) / len(dec["sx_main"])) if dec["sx_main"] else None,
            "mean_g_sr": (sum(i["g_sr"] for i in dec["srx"]) / len(dec["srx"])) if dec["srx"] else None,
            "mean_g_rx": (sum(i["g_rx"] for i in dec["srx"]) / len(dec["srx"])) if dec["srx"] else None,
            "sign_test": signed,
            "mcnemar_S_done_X_not_vs_X_done_S_not": mcnemar_exact(b, c),
            "full_completion_rate": {k: _rate(k, lambda s: s in ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")) for k in "SRX"},
            "online_rate": {k: _rate(k, lambda s: s == "COMPLETED_ONLINE") for k in "SRX"},
            "stop_rate": {k: _rate(k, lambda s: s not in ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")) for k in "SRX"},
            "recovery_evals_mean": (sum(evals) / len(evals)) if evals else None,
            "wall_hits": hits,
            "wall_max_s": max(walls) if walls else None,
            "nominal_cost_S": (nom.get("S") or {}).get("cost"),
            "nominal_cost_X": (nom.get("X") or {}).get("cost"),
            "nominal_X_minus_S": None if not nom.get("S") or not nom.get("X") or nom["S"].get("cost") is None or nom["X"].get("cost") is None
            else nom["X"]["cost"] - nom["S"]["cost"],
        }
        if by[cid]:
            sx_boot[cid] = [i["g_sx"] for i in dec["sx_main"]]
    boot = stratified_paired_bootstrap(sx_boot, replicates=10000, seed=20261114)
    return {"maps": maps, "bootstrap_g_sx": boot, "holm_sx_sign": holm(pvalues)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "r6/results/v13_baseline"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--smoke", action="store_true", help="C50 nominal plus tune seed 101 only")
    parser.add_argument("--which", choices=("tune", "dev", "both"), default="both")
    parser.add_argument("--ablation", default="full",
                        choices=("full", "norescue", "norank", "nonominal", "nosync"))
    args = parser.parse_args()
    from tdr.v13 import git_run_metadata, load_run_config
    cfg, view, digest = load_run_config(formal=False, m1=M1, m2=M2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "resolved_sha256.txt").write_text(digest + "\n")
    cases = ["C50"] if args.smoke else CASES
    if args.smoke:
        seeds = [101]
    elif args.which == "tune":
        seeds = list(range(101, 111))
    elif args.which == "dev":
        seeds = list(range(1, 11))
    else:
        seeds = list(range(101, 111)) + list(range(1, 11))
    t0 = time.perf_counter()
    nom_jobs = [(cfg, c, s, str(out), args.ablation) for c in cases for s in ("S", "X")]
    with Pool(args.workers) as pool:
        nominals = pool.map(_nominal_one, nom_jobs)
    print("nominal done", time.perf_counter() - t0, flush=True)
    ep_jobs = [(cfg, c, seed, str(out), args.ablation) for c in cases for seed in seeds]
    with Pool(args.workers) as pool:
        episodes = pool.map(_episode_one, ep_jobs)
    print("episodes done", time.perf_counter() - t0, flush=True)
    summary = _summarize(episodes, nominals)
    summary["ablation"] = args.ablation
    summary["m1"] = M1
    summary["m2"] = M2
    summary["resolved_sha256"] = digest
    summary["planner_view_sha256"] = cfg["information_isolation"]["planner_view_sha256"]
    summary["metadata"] = git_run_metadata(str(ROOT))
    summary["nominals"] = nominals
    summary["wall_s"] = time.perf_counter() - t0
    (out / "episodes.json").write_text(json.dumps(episodes) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("bootstrap_g_sx", "m1", "m2")}, indent=2))


if __name__ == "__main__":
    main()
