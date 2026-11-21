"""Register 36 jobs on frozen nominal bytes. Does not evaluate and does not launch."""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
NOMINAL = HERE.parent / "M47_bounded_actual_20261121" / "M47_CANDIDATE" / "nominal"
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"
sys.path.insert(0, str(HERE.parent / "M47_bounded_actual_20261121"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CORE))
os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
from research import setup, plan_from_dict  # noqa: E402
from tdr.complete_joint import version  # noqa: E402
from tdr.simulate import derive_rngs, initial_run_state  # noqa: E402
from private_root import witness  # noqa: E402
from scope_fingerprint import complete_scope, fingerprint  # noqa: E402
from fresh_actual import nominal_role, recovery_policy  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
SEEDS = [1001, 1002]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_registration():
    freeze_path = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha(freeze_path) != REQUIRED_FREEZE:
        raise SystemExit("core freeze is not 39a85da8")
    core = json.loads(freeze_path.read_text())
    if len(core) != 147 or any(sha(CORE / name) != digest for name, digest in core.items()):
        raise SystemExit("core member mismatch")
    nominal_hashes = {}
    for case in CASES:
        for role in "SX":
            nominal_hashes[f"{role}/{case}"] = sha(NOMINAL / role / case / "nominal_plan.json")
    driver = sha(HERE / "fresh_actual.py")
    controller = sha(HERE / "run_actual.py")
    jobs = []
    details = []
    horizons = {}
    for case in CASES:
        for seed in SEEDS:
            world_hash = sha(witness(case, seed))
            for arm in "SRX":
                role = nominal_role(arm)
                raw = json.loads((NOMINAL / role / case / "nominal_plan.json").read_text())
                plan = plan_from_dict(raw["plan"])
                inst, phys, alg = setup(case, "M49")
                pol = recovery_policy(arm)
                rngs = derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
                scope = complete_scope(
                    inst, case, seed, pol, version(plan), raw["H_s"], alg, phys,
                    vars(initial_run_state(plan, inst, phys)),
                    {key: value.getstate() for key, value in rngs.items()},
                    core, driver, world_hash)
                job = ["M49_REORDER", case, arm, "dev", seed, "own"]
                jobs.append(job)
                horizons[f"{case}/{arm}/{seed}"] = raw["H_s"]
                details.append(dict(
                    logical_job=job, canonical_fresh_job=job, nominal_role=role,
                    recovery_policy=pol, plan_version=version(plan), H_s=raw["H_s"],
                    nominal_sha256=nominal_hashes[f"{role}/{case}"],
                    world_sha256=world_hash, complete_input_fingerprint=fingerprint(scope)))
    if len(jobs) != 36 or len({tuple(job) for job in jobs}) != 36:
        raise SystemExit("registration is not 36 unique jobs")
    for case in CASES:
        if horizons[f"{case}/R/1001"] != horizons[f"{case}/S/1001"]:
            raise SystemExit("R horizon is not the S horizon")
    return dict(
        status="PREREGISTERED_NOT_LAUNCHED",
        launch_allowed=False,
        reuse_of_finished_executions="not_assumed",
        do_not_inject_conditional_witnesses=["601.3641210199783", "563.5086337141618"],
        arms=dict(
            S="strong S nominal bytes, recovery policy S, shared core",
            R="S nominal bytes, recovery policy X, shared core",
            X="X nominal bytes, recovery policy X, shared core",
        ),
        jobs=jobs, logical_mapping=details, logical_count=36, unique_fresh_jobs=36,
        nominal_sha256=nominal_hashes, horizons=horizons,
        driver_sha256=driver, controller_sha256=controller,
        prepare_sha256=sha(HERE / "prepare_registration.py"),
        core_freeze_sha256=REQUIRED_FREEZE,
        init_eval_budget=100, main_eval_budget=1000,
        rescue="one extension of the init budget by main_eval when init finds nothing",
        calls_this_round=0,
        fresh_execution_written=False,
    )


def main():
    doc = build_registration()
    (HERE / "FRESH_JOB_REGISTRATION.json").write_text(json.dumps(doc, indent=1) + "\n")
    print("M49_PREREGISTERED", 36, "not_launched", "calls", 0)


if __name__ == "__main__":
    main()
