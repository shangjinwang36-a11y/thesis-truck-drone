"""Register M44 nominals on the sealed M48 recovery core.

A logical job whose complete fingerprint matches a finished M48 job is reused.
Only fingerprints that do not match are fresh. The fresh count is computed.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
SEALED = HERE.parent / "M48_depot_road_release_20261121"
CORE = HERE.parent / "M48_depot_road_release_core_20261121"
M44 = HERE.parent / "M47_bounded_actual_20261121" / "M44_CURRENT" / "nominal"
M47S = HERE.parent / "M47_bounded_actual_20261121" / "M47_CANDIDATE" / "nominal" / "S"
sys.path.insert(0, str(HERE.parent / "M47_bounded_actual_20261121"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CORE))
os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
from research import *  # noqa: E402
from tdr.complete_joint import version  # noqa: E402
from tdr.simulate import initial_run_state  # noqa: E402
from private_root import witness  # noqa: E402
from scope_fingerprint import complete_scope, fingerprint  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
SEEDS = [1001, 1002]
SEALED_CORE = "74ae8419889b98e735dd68fcf16407165b5980535acde3179e3d168a8f7e3d47"
SEALED_REG = "d7e3b9c0129e3564c057f39990d93c630560773372b5d401e798ffe635b5e422"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_registration():
    sealed_doc = json.loads((SEALED / "FRESH_JOB_REGISTRATION.json").read_text())
    if sha(SEALED / "FRESH_JOB_REGISTRATION.json") != SEALED_REG:
        raise SystemExit("sealed M48 registration changed")
    if sealed_doc["driver_sha256"] != sha(SEALED / "fresh_actual.py") or sealed_doc["core_freeze_sha256"] != SEALED_CORE:
        raise SystemExit("sealed driver or core identity changed")
    core = json.loads((CORE / "EXPERIMENT_CORE_FREEZE.json").read_text())
    if sha(CORE / "EXPERIMENT_CORE_FREEZE.json") != SEALED_CORE or len(core) != 147:
        raise SystemExit("core freeze drifted")
    assert all(sha(CORE / name) == digest for name, digest in core.items())
    sealed_driver = sealed_doc["driver_sha256"]
    this_driver = sha(HERE / "fresh_actual.py")
    by_fp = {row["complete_input_fingerprint"]: row for row in sealed_doc["logical_mapping"]}
    nominal_hashes = {}
    for case in CASES:
        for role in "SX":
            nominal_hashes[f"{role}/{case}"] = sha(M44 / role / case / "nominal_plan.json")
    details = []
    fresh_jobs = []
    for case in CASES:
        horizon = json.loads((M44 / "S" / case / "nominal_plan.json").read_text())["H_s"]
        reference = json.loads((M47S / case / "nominal_plan.json").read_text())["H_s"]
        if horizon != reference:
            raise SystemExit("M44 S horizon differs from the sealed reference " + case)
        for seed in SEEDS:
            world_hash = sha(witness(case, seed))
            for arm in "SRX":
                inst, phys, alg = setup(case, "M48")
                if alg.recovery_init_eval_budget != 100 or alg.deterministic_recovery_eval_budget != 1000 or alg.recovery_eval_budget_override is not None:
                    raise SystemExit("budget drifted")
                if horizon != alg._nominal_reference_H:
                    raise SystemExit("horizon is not the algorithm reference")
                role = "X" if arm == "X" else "S"
                raw = json.loads((M44 / role / case / "nominal_plan.json").read_text())
                plan = plan_from_dict(raw["plan"])
                pol = "S" if arm == "S" else "X"
                rngs = rr.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
                initial = vars(initial_run_state(plan, inst, phys))
                rng_state = {k: v.getstate() for k, v in rngs.items()}
                sealed_scope = complete_scope(
                    inst, case, seed, pol, version(plan), horizon, alg, phys, initial, rng_state, core, sealed_driver, world_hash)
                sealed_fp = fingerprint(sealed_scope)
                logical = ["M48_M44_NOMINAL", case, arm, "dev", seed, "own"]
                hit = by_fp.get(sealed_fp)
                if hit is not None:
                    execution = SEALED / "M48_RECOVERY" / "executions" / "own" / "dev" / f"{case}_{seed}_{arm}.json"
                    details.append(dict(
                        logical_job=logical, disposition="REUSE_FINISHED_M48",
                        canonical_fresh_job=hit["logical_job"],
                        sealed_equivalent_fingerprint=sealed_fp,
                        execution_fingerprint=sealed_fp,
                        plan_version=version(plan), H_s=horizon, world_sha256=world_hash,
                        nominal_sha256=nominal_hashes[f"{role}/{case}"],
                        reused_execution=str(execution), reused_execution_sha256=sha(execution),
                    ))
                else:
                    fresh_scope = complete_scope(
                        inst, case, seed, pol, version(plan), horizon, alg, phys, initial, rng_state, core, this_driver, world_hash)
                    fresh_fp = fingerprint(fresh_scope)
                    details.append(dict(
                        logical_job=logical, disposition="FRESH",
                        canonical_fresh_job=logical,
                        sealed_equivalent_fingerprint=sealed_fp,
                        execution_fingerprint=fresh_fp,
                        plan_version=version(plan), H_s=horizon, world_sha256=world_hash,
                        nominal_sha256=nominal_hashes[f"{role}/{case}"],
                    ))
                    fresh_jobs.append(logical)
    return dict(
        status="DEDUPLICATED_NOT_LAUNCHED",
        jobs=fresh_jobs,
        logical_mapping=details,
        logical_count=len(details),
        unique_fresh_jobs=len(fresh_jobs),
        reused_finished_jobs=len(details) - len(fresh_jobs),
        fresh_count_is_computed=True,
        control="finished M48 actual on identical fingerprints; historical M44 and K1 are not this same-fix control",
        nominal_source="M44_CURRENT",
        recovery_core="sealed M48 core, unchanged",
        nominal_sha256=nominal_hashes,
        sealed_driver_sha256=sealed_driver,
        driver_sha256=this_driver,
        sealed_registration_sha256=SEALED_REG,
        core_freeze_sha256=SEALED_CORE,
        init_eval_budget=100,
        main_eval_budget=1000,
        rescue="one extension of the init budget by main_eval when init finds nothing",
        fresh_execution_written=False,
    )


def main():
    doc = build_registration()
    (HERE / "FRESH_JOB_REGISTRATION.json").write_text(json.dumps(doc, indent=1) + "\n")
    print("M44_SAME_RECOVERY", "logical", doc["logical_count"], "fresh", doc["unique_fresh_jobs"], "reused", doc["reused_finished_jobs"])
    for job in doc["jobs"]:
        print("FRESH", job)


if __name__ == "__main__":
    main()
