"""Register 36 M48 recovery jobs on the frozen M47 nominal bytes. Does not launch."""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M48_depot_road_release_core_20261121"
NOMINAL = HERE.parent / "M47_bounded_actual_20261121" / "M47_CANDIDATE" / "nominal"
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    # nominal bytes are frozen; this script only hashes them
    nominal_hashes = {}
    for case in CASES:
        for role in "SX":
            path = NOMINAL / role / case / "nominal_plan.json"
            nominal_hashes[f"{role}/{case}"] = sha(path)
    core = json.loads((CORE / "EXPERIMENT_CORE_FREEZE.json").read_text())
    assert all(sha(CORE / name) == digest for name, digest in core.items())
    driver = sha(HERE / "fresh_actual.py")
    jobs = []
    details = []
    for case in CASES:
        for seed in SEEDS:
            world_hash = sha(witness(case, seed))
            for arm in "SRX":
                inst, phys, alg = setup(case, "M48")
                raw = json.loads((NOMINAL / ("X" if arm == "X" else "S") / case / "nominal_plan.json").read_text())
                plan = plan_from_dict(raw["plan"])
                pol = "S" if arm == "S" else "X"
                rngs = rr.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
                scope = complete_scope(
                    inst, case, seed, pol, version(plan), raw["H_s"], alg, phys,
                    vars(initial_run_state(plan, inst, phys)),
                    {k: v.getstate() for k, v in rngs.items()}, core, driver, world_hash)
                fp = fingerprint(scope)
                job = ["M48_RECOVERY", case, arm, "dev", seed, "own"]
                jobs.append(job)
                details.append(dict(logical_job=job, canonical_fresh_job=job, plan_version=version(plan),
                                     H_s=raw["H_s"], world_sha256=world_hash, complete_input_fingerprint=fp))
    assert len(jobs) == 36
    doc = dict(
        status="PREREGISTERED_NOT_LAUNCHED",
        jobs=jobs, logical_mapping=details, logical_count=36, unique_fresh_jobs=36,
        control="existing M47 actual on the same nominal bytes and worlds; not re-executed",
        nominal_sha256=nominal_hashes,
        driver_sha256=driver,
        core_freeze_sha256=sha(CORE / "EXPERIMENT_CORE_FREEZE.json"),
        init_eval_budget=100, main_eval_budget=1000,
        rescue="one extension of the init budget by main_eval when init finds nothing",
        fresh_execution_written=False,
        diagnostic_replay_is_not_a_fresh_row=True,
    )
    (HERE / "FRESH_JOB_REGISTRATION.json").write_text(json.dumps(doc, indent=1) + "\n")
    print("M48_PREREGISTERED", 36, "not_launched")


if __name__ == "__main__":
    main()
