"""Stage nominal inputs and refuse registration until recorded witnesses exist.

Does not sample worlds, does not run episodes, and does not write
FRESH_JOB_REGISTRATION.json when any required file is absent.
"""
from pathlib import Path
import hashlib
import json
import pickle
import shutil
import sys

H = Path(__file__).resolve().parent
B = H.parent
C = B / "M47_schedule_closed_exchange_core_20261121"
sys.path.insert(0, str(C))
from research import *  # noqa: E402
from tdr.complete_joint import version  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
SEEDS = [1001, 1002]
VARIANTS = ["M47_CANDIDATE", "M44_CURRENT"]
WITNESS_DIR = B / "J2_historical_R10_integrated_repair_20261120/J2/executions/own/dev"
M20 = B / "M20_canonical_H_sixmap_20261121/preflight_fresh"
K1_EXEC = B / "K1_R10_S_warm_restore_20261120/K1/executions/own/dev"
M47_NOMINAL = B / "M47_schedule_closed_exchange_20261121/fresh_new"
M44_NOMINAL = B / "M44_paid_temporal_body_skeleton_20261121/fresh_new"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    missing = []
    historical = []
    for case in CASES:
        m20 = M20 / case / "S/nominal_plan.json"
        if not m20.is_file():
            missing.append(dict(
                path=str(m20),
                role="frozen_H_identity",
                format="nominal_plan.json with H_s equal to sealed K1 S H_s and to alg._nominal_reference_H",
                shareable=True,
                hidden_flags=False,
            ))
        for seed in SEEDS:
            witness = WITNESS_DIR / f"{case}_{seed}_S.json"
            if not witness.is_file():
                missing.append(dict(
                    path=str(witness),
                    role="recorded_dev_world_shared_by_S_R_X_and_both_variants",
                    format="JSON object. Required key flags: a list. The registration hashes the whole file. Do not send the list for plan construction.",
                    shareable=False,
                    hidden_flags=True,
                ))
            for arm in "SRX":
                old = K1_EXEC / f"{case}_{seed}_{arm}.json"
                historical.append(dict(
                    path=str(old),
                    present=old.is_file(),
                    role="historical_K1_actual_reference_not_a_fresh_job",
                    used_by="audit_source_and_world_identity.py compares flags and H after an execution exists",
                ))
    report = dict(
        registration_written=False,
        actual_started=False,
        worlds_not_generated=True,
        missing=missing,
        historical_k1_actual_rows=historical,
        nominal_inputs_staged=False,
    )
    if missing:
        dump(H / "MISSING_DEPENDENCIES.json", report)
        print("REGISTRATION_BLOCKED", len(missing), "missing", flush=True)
        return 2
    # Witnesses and M20 exist. Stage nominals, then build the same fingerprint registry.
    from tdr.simulate import initial_run_state
    core = read(C / "EXPERIMENT_CORE_FREEZE.json")
    driver_hash = sha(H / "fresh_actual.py")
    held = []
    for variant, root in (("M47_CANDIDATE", M47_NOMINAL), ("M44_CURRENT", M44_NOMINAL)):
        for case in CASES:
            for role in "SX":
                src = root / case / role / "nominal_plan.json"
                dst = H / variant / "nominal" / role / case / "nominal_plan.json"
                if dst.exists():
                    raise FileExistsError(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                raw = read(dst)
                held.append(dict(variant=variant, case=case, role=role, source=str(src),
                                 sha256=sha(src), version=version(plan_from_dict(raw["plan"])), H_s=raw["H_s"]))
    seen = {}
    jobs = []
    mapping = []
    details = []
    for variant in VARIANTS:
        for case in CASES:
            for seed in SEEDS:
                world = WITNESS_DIR / f"{case}_{seed}_S.json"
                world_hash = sha(world)
                for arm in "SRX":
                    inst, phys, alg = setup(case, variant)
                    alg.recovery_eval_budget_override = 1000
                    raw_path = H / variant / "nominal" / ("X" if arm == "X" else "S") / case / "nominal_plan.json"
                    raw = read(raw_path)
                    plan = plan_from_dict(raw["plan"])
                    pol = "S" if arm == "S" else "X"
                    rngs = rr.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
                    scope = (inst, case, seed, pol, version(plan), raw["H_s"], vars(alg), phys,
                             vars(initial_run_state(plan, inst, phys)),
                             {k: v.getstate() for k, v in rngs.items()}, core, driver_hash, world_hash)
                    fp = hashlib.sha256(pickle.dumps(scope, protocol=5)).hexdigest()
                    job = (variant, case, arm, "dev", seed, "own")
                    if fp not in seen:
                        seen[fp] = job
                        jobs.append(job)
                    details.append(dict(logical_job=job, world_source_sha256=world_hash,
                                        complete_input_fingerprint=fp))
                    mapping.append(dict(logical_job=list(job), canonical_fresh_job=list(seen[fp]),
                                        plan_version=version(plan), H_s=raw["H_s"],
                                        complete_input_fingerprint=fp))
    assert len(mapping) == 72
    dump(H / "FRESH_JOB_REGISTRATION.json", dict(
        jobs=[list(j) for j in jobs], logical_mapping=mapping, held_nominal=held,
        logical_count=72, candidate_logical=36, control_logical=36,
        unique_fresh_jobs=len(jobs), no_new_nominal_preparation=True,
        all_actual_share_same_recovery_code=True, full_scope_dedup=True,
        no_old_actual_rows_used=True, exact_scope_details=details,
        worlds=SEEDS, variants=VARIANTS, stream="dev", hmode="own"))
    report.update(registration_written=True, nominal_inputs_staged=True,
                  unique_fresh_jobs=len(jobs), logical_count=72)
    dump(H / "MISSING_DEPENDENCIES.json", report)
    print("BOUNDED_ACTUAL_REGISTERED", len(jobs), "canonical for 72 logical", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
