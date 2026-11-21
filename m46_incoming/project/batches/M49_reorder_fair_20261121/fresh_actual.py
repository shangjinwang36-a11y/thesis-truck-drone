"""M49 worker bound to core 39a85da8. Importing it does not evaluate.

The controller is loaded from this directory by absolute path, never by sys.path.
The physical body is the M48 episode runner with this stage's nominal and policy.
It runs only after the approval flag is set. This round does not set that flag.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent / "M49_landed_wait_core_20261121"
M47_BATCH = HERE.parent / "M47_bounded_actual_20261121"
NOMINAL = M47_BATCH / "M47_CANDIDATE" / "nominal"
LAUNCH_ENV = "M49_LAUNCH_APPROVED"
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"


def approved() -> bool:
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def load_controller():
    path = HERE / "run_actual.py"
    spec = importlib.util.spec_from_file_location("m49_reorder_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path.resolve():
        raise SystemExit("controller path is not the M49 controller")
    return module


def nominal_role(arm: str) -> str:
    if arm == "X":
        return "X"
    if arm in ("S", "R"):
        return "S"
    raise SystemExit("arm is not S, R, or X")


def recovery_policy(arm: str) -> str:
    if arm == "S":
        return "S"
    if arm in ("R", "X"):
        return "X"
    raise SystemExit("arm is not S, R, or X")


def execute_job(job):
    """M48 episode body, retargeted. Reached only after approval."""
    variant, case, arm, stream, seed, hmode = job
    if stream != "dev" or hmode != "own" or seed not in (1001, 1002) or arm not in "SRX":
        raise SystemExit("job outside the registered batch")
    if variant != "M49_REORDER":
        raise SystemExit("variant is not M49_REORDER")
    src = str(SOURCE_ROOT / "source/proj_r6/src")
    if src not in sys.path:
        sys.path.insert(0, src)
    sys.path.insert(0, str(SOURCE_ROOT / "source/round10_recheck"))
    sys.path.insert(0, str(SOURCE_ROOT))
    sys.path.insert(0, str(M47_BATCH))
    from research import plan_from_dict, read, setup  # noqa: E402
    import research as rr  # noqa: E402
    from dataclasses import replace  # noqa: E402
    from tdr.hidden_world import TestWorld  # noqa: E402
    from tdr.simulate import initial_run_state, _state_record  # noqa: E402
    from tdr.verify import verify_plan  # noqa: E402
    from bill import bill  # noqa: E402
    from finish_accounting import finish_candidate_calls  # noqa: E402
    from initial_observer import observe_initializations  # noqa: E402
    from private_root import m20_s, witness as recorded_witness  # noqa: E402
    import tdr.simulate as loaded_simulate  # noqa: E402
    import tdr.moves as loaded_moves  # noqa: E402
    from tdr.alns import Budget  # noqa: E402
    from tdr.complete_joint import version  # noqa: E402

    freeze_path = SOURCE_ROOT / "EXPERIMENT_CORE_FREEZE.json"
    if hashlib.sha256(freeze_path.read_bytes()).hexdigest() != REQUIRED_FREEZE:
        raise SystemExit("core freeze is not 39a85da8")
    core = json.loads(freeze_path.read_text())
    for name, digest in core.items():
        if hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest() != digest:
            raise SystemExit("core member mismatch " + name)
    if Path(loaded_simulate.__file__).resolve() != (SOURCE_ROOT / "source/proj_r6/src/tdr/simulate.py").resolve():
        raise SystemExit("simulate.py is not the M49 core")
    if Path(loaded_moves.__file__).resolve() != (SOURCE_ROOT / "source/proj_r6/src/tdr/moves.py").resolve():
        raise SystemExit("moves.py is not the M49 core")
    role = nominal_role(arm)
    pol = recovery_policy(arm)
    nominal_path = NOMINAL / role / case / "nominal_plan.json"
    strong_s = NOMINAL / "S" / case / "nominal_plan.json"
    raw = read(nominal_path)
    plan = plan_from_dict(raw["plan"])
    inst, phys, alg = setup(case, "M49")
    if alg.recovery_init_eval_budget != 100 or alg.deterministic_recovery_eval_budget != 1000:
        raise SystemExit("budgets are not INIT 100 and MAIN 1000")
    if alg.recovery_eval_budget_override is not None:
        raise SystemExit("budget override is set")
    H = read(strong_s)["H_s"]
    if H != read(m20_s(case))["H_s"] or H != alg._nominal_reference_H:
        raise SystemExit("horizon is not the strong S horizon")
    dest = HERE / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json"
    if dest.exists():
        raise SystemExit("output already exists " + dest.name)
    witness = recorded_witness(case, seed)
    saved = read(witness)
    flags = saved["flags"]
    if not isinstance(flags, list):
        raise SystemExit("recorded witness flags are not a list")
    world = TestWorld(inst, case, tuple(sorted(flags)))
    folder = dest.parent
    folder.mkdir(parents=True, exist_ok=True)
    with rr.audit_evaluations() as startup_audit:
        ev = rr.evaluate_plan(plan, inst, phys, rr.initial_state(inst, phys), H, "PRE_EXECUTION_NOMINAL_VERIFY", budget=Budget(1, None))
    (HERE / variant / "startup_ledgers" / hmode / stream).mkdir(parents=True, exist_ok=True)
    (HERE / variant / "startup_ledgers" / hmode / stream / f"{case}_{seed}_{arm}.json").write_text(json.dumps(startup_audit.summary()))
    if not (ev.feasible and verify_plan(inst, None, plan, pol, phys, H).ok):
        raise SystemExit("nominal verify failed")
    import time
    start = time.perf_counter()
    with rr.audit_evaluations() as audit, finish_candidate_calls() as finish_counts:
        try:
            with observe_initializations(HERE / variant / "observer/formal" / hmode / stream / f"{case}_{seed}_{arm}", world, inst, phys, alg) as observed_world:
                episode = rr.run_episode(
                    inst, plan, ev, H, phys, observed_world, pol, alg,
                    rr.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                    recovery_eval_budget=alg.deterministic_recovery_eval_budget,
                    recovery_wall_s=None, cut_mode="snapshot", max_replans=inst.n, ground_finish=True)
        finally:
            live = HERE / variant / "live_ledgers" / hmode / stream
            live.mkdir(parents=True, exist_ok=True)
            (live / f"{case}_{seed}_{arm}.json").write_text(json.dumps(dict(ledger=audit.summary(), finish_candidates=dict(finish_counts))))
    elapsed = time.perf_counter() - start
    segments = rr.clean(episode.segments)
    replay = rr.verify_replay(inst, replace(phys, soft_h=True) if episode.ground_finish_verified else phys, segments, H, pol)
    parts = bill(segments, phys, H)
    paid = episode.ground_finish_cost if episode.ground_finish_verified else episode.evaluation.cost if episode.status == "COMPLETED_VERIFIED" else None
    row = dict(
        world_source=str(witness),
        world_source_sha256=hashlib.sha256(witness.read_bytes()).hexdigest(),
        nominal_source_sha256=hashlib.sha256(nominal_path.read_bytes()).hexdigest(),
        nominal_role=role, recovery_policy=pol, variant=variant, case=case, arm=arm,
        policy=pol, stream=stream, seed=seed, hmode=hmode, H=H, paid=paid, parts=parts,
        seconds=elapsed, status=episode.status, emergency=episode.ground_finish_verified,
        valid=replay.ok, delivered=replay.delivered, parcels=inst.n,
        delta=abs(replay.cost - paid) if paid is not None else None,
        min_energy=min(replay.min_energy.values(), default=None),
        calls=audit.summary()["accepted_calls"],
        input_plan_version=version(plan),
        core_freeze_sha256=REQUIRED_FREEZE,
        core_root=str(SOURCE_ROOT),
        execution_pid=os.getpid(),
    )
    dest.write_text(json.dumps(dict(
        row=row, finish_candidates=dict(finish_counts), observations=rr.clean(episode.observations),
        replay=replay, ledger=audit.summary(), segments=segments, notes=episode.notes, replans=episode.replans,
    )))
    return row


def shift(job):
    if not approved():
        raise SystemExit("not launched")
    variant, case, _arm, _stream, seed, _hmode = job
    journal_path = HERE / "call_journals" / f"{variant}_{case}_{seed}_{job[2]}.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if journal_path.exists():
        raise SystemExit("output already exists " + journal_path.name)
    from tdr.evaluation_audit import EvaluationAudit
    original = EvaluationAudit.record
    journal = journal_path.open("x")

    def recorded(self, reason, budget, accepted):
        original(self, reason, budget, accepted)
        journal.write(json.dumps(dict(
            reason=reason, accepted=bool(accepted),
            used=None if budget is None else budget.used,
            limit=None if budget is None else budget.eval_limit,
            scenario=bool(getattr(budget, "scenario_ledger", False)),
        )) + "\n")
        journal.flush()

    EvaluationAudit.record = recorded
    try:
        return execute_job(job)
    finally:
        EvaluationAudit.record = original
        journal.close()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        shift(tuple(json.loads(sys.argv[2])))
        return
    controller = load_controller()
    controller.main()


if __name__ == "__main__":
    main()
