"""M49 worker bound to core 39a85da8. Importing it does not evaluate.

The controller is loaded from this directory by absolute path, never by sys.path.
The physical runner is the sealed run_emin005 module, which research.rr already
holds. The research wrapper itself does not provide the runner API.
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
RUNNER_API = (
    "audit_evaluations", "evaluate_plan", "initial_state", "run_episode",
    "derive_rngs", "clean", "verify_replay",
)


def approved() -> bool:
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def output_root() -> Path:
    raw = os.environ.get("M49_OUTPUT_ROOT")
    return Path(raw) if raw else HERE


def registration_path() -> Path:
    raw = os.environ.get("M49_REGISTRATION")
    return Path(raw) if raw else HERE / "FRESH_JOB_REGISTRATION.json"


def bind_core():
    """Put the audited core on sys.path before any tdr import."""
    entries = [
        str(SOURCE_ROOT / "source/proj_r6/src"),
        str(SOURCE_ROOT / "source/round10_recheck"),
        str(SOURCE_ROOT),
        str(M47_BATCH),
    ]
    for entry in reversed(entries):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)


def load_runner():
    bind_core()
    import research
    import run_emin005 as runner
    missing = [name for name in RUNNER_API if not hasattr(runner, name)]
    if missing:
        raise SystemExit("sealed runner is missing " + ",".join(missing))
    expected = (SOURCE_ROOT / "source/round10_recheck/run_emin005.py").resolve()
    if Path(runner.__file__).resolve() != expected:
        raise SystemExit("runner is not the sealed run_emin005.py")
    if Path(research.__file__).resolve() != (SOURCE_ROOT / "research.py").resolve():
        raise SystemExit("research is not the sealed wrapper")
    leaked = [name for name in RUNNER_API if hasattr(research, name)]
    if leaked:
        raise SystemExit("research wrapper is not the runner; it has " + ",".join(leaked))
    if research.rr is not runner:
        raise SystemExit("research.rr is not the sealed runner")
    return runner


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


def install_evaluate_stub():
    """Replace only evaluate_plan. The other six runner attributes stay real.

    The stub records budget and audit the way the entry does, and does not call
    the evaluator body. A nominal-verify call is marked feasible so the original
    verify_plan gate still runs; every later call is infeasible, so the episode
    cannot become a publishable result.
    """
    if os.environ.get("M49_DRY_RUN") != "1" or output_root().resolve() == HERE.resolve():
        raise SystemExit("evaluate stub requires a dry run outside the production directory")
    import tdr.evaluate as evaluate
    import tdr.schedule as schedule
    original = evaluate.evaluate_plan
    original_schedule = schedule.schedule_plan
    counters = {"stub_reasons": [], "real_evaluate_body": 0, "schedule_plan": 0}

    def stub(plan, inst, phys, state=None, H=None, reason="", check_structure=True,
             budget=None, allow_wait_repair=True, *, ground_required=None):
        counters["stub_reasons"].append(reason)
        (output_root() / "STUB_CALLS.json").write_text(json.dumps(dict(
            record_class="TEST", real_evaluate_body=0, reasons=list(counters["stub_reasons"]))))
        from tdr.evaluation_audit import _ACTIVE
        accepted = True if budget is None else bool(budget.take())
        audit = _ACTIVE.get()
        if audit is not None:
            audit.record(reason, budget, accepted)
        ev = evaluate.Evaluation(reason=reason, status="TEST_STUB_NOT_A_RESULT", feasible=False,
                                 violations=["TEST_STUB_NOT_A_RESULT"])
        if reason == "PRE_EXECUTION_NOMINAL_VERIFY" and accepted:
            ev.feasible = True
            ev.status = "TEST_NOMINAL_GATE_ONLY"
            ev.violations = []
        return ev

    def counting_schedule(*args, **kwargs):
        counters["schedule_plan"] += 1
        return original_schedule(*args, **kwargs)

    for module in list(sys.modules.values()):
        if module is None:
            continue
        for name, value in list(vars(module).items()):
            if value is original and name == "evaluate_plan":
                setattr(module, name, stub)
            elif value is original_schedule and name == "schedule_plan":
                setattr(module, name, counting_schedule)
    counters["stub"] = stub
    return counters


def stage_account(startup, episode, journal_path):
    ground_finish = int(episode.get("by_reason", {}).get("GROUND_FINISH", 0))
    external = sum(startup.get("unbudgeted_by_reason", {}).values()) + sum(episode.get("unbudgeted_by_reason", {}).values())
    failed_journal = 0
    path = Path(journal_path)
    if path.is_file():
        failed_journal = sum(1 for line in path.read_text().splitlines() if line and not json.loads(line)["accepted"])
    startup_calls = int(startup.get("accepted_calls", 0))
    episode_calls = int(episode.get("accepted_calls", 0))
    return dict(
        startup=startup_calls,
        episode=episode_calls,
        ground_finish=ground_finish,
        object_external=external,
        failed_journal=failed_journal,
        stage_total_accepted=startup_calls + episode_calls,
        row_calls_is_episode_only=True,
        slices_are_not_added_again=True,
    )


def completion_failure(replay, paid, parts, inst_n, delta, segments, observations, flags, ledger, initial_start):
    """Original M48 completion gate. A false result must not exit as success."""
    paid_ok = paid is not None and parts is not None and abs(paid - sum(parts.values())) < 1e-7 and delta is not None and delta < 1e-7
    if not (replay.ok and replay.delivered == inst_n and paid_ok):
        return "result failed the completion checks"
    if not segments or segments[0]["t0"] != 0 or segments[0]["start"] != initial_start:
        return "result failed the prefix check"
    if not all(item["air_delivery_available"] == (item["parcel_id"] not in flags) for item in observations):
        return "result failed the observation check"
    if not all(item["used"] == item["accepted_calls"] <= item["final_limit"] for item in ledger["budgets"]):
        return "result failed the budget check"
    return None


def execute_job(job):
    """M48 episode body. The runner is run_emin005, not the research wrapper."""
    runner = load_runner()
    variant, case, arm, stream, seed, hmode = job
    if stream != "dev" or hmode != "own" or seed not in (1001, 1002) or arm not in "SRX":
        raise SystemExit("job outside the registered batch")
    if variant != "M49_REORDER":
        raise SystemExit("variant is not M49_REORDER")
    from research import plan_from_dict, read, setup
    from dataclasses import replace
    from tdr.hidden_world import TestWorld
    from tdr.simulate import derive_rngs, initial_run_state, _state_record
    from tdr.verify import verify_plan
    from bill import bill
    from finish_accounting import finish_candidate_calls
    from initial_observer import observe_initializations
    from private_root import m20_s, witness as recorded_witness
    from scope_fingerprint import complete_scope, fingerprint
    import tdr.simulate as loaded_simulate
    import tdr.moves as loaded_moves
    from tdr.alns import Budget
    from tdr.complete_joint import version
    import time

    counters = install_evaluate_stub() if os.environ.get("M49_EVALUATE_STUB") == "1" else None
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
    reg = json.loads(registration_path().read_text())
    registered = next(row for row in reg["logical_mapping"] if tuple(row["logical_job"]) == tuple(job))
    witness = recorded_witness(case, seed)
    witness_sha = hashlib.sha256(witness.read_bytes()).hexdigest()
    nominal_sha = hashlib.sha256(nominal_path.read_bytes()).hexdigest()
    if witness_sha != registered["world_sha256"] or nominal_sha != registered["nominal_sha256"]:
        raise SystemExit("witness or nominal hash mismatch")
    if registered["H_s"] != json.loads(nominal_path.read_text())["H_s"]:
        raise SystemExit("horizon mismatch")
    dependencies = {
        "private_root.py": M47_BATCH / "private_root.py",
        "scope_fingerprint.py": M47_BATCH / "scope_fingerprint.py",
        "run_emin005.py": SOURCE_ROOT / "source/round10_recheck/run_emin005.py",
        "research.py": SOURCE_ROOT / "research.py",
        "initial_observer.py": SOURCE_ROOT / "initial_observer.py",
        "finish_accounting.py": SOURCE_ROOT / "finish_accounting.py",
        "bill.py": SOURCE_ROOT / "bill.py",
    }
    dependency_sha = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in dependencies.items()}
    if reg.get("dependency_sha256") != dependency_sha:
        raise SystemExit("dependency identity mismatch")
    root = output_root()
    test_only = os.environ.get("M49_DRY_RUN") == "1"
    if test_only and root.resolve() == HERE.resolve():
        raise SystemExit("dry run refuses the production directory")
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
    driver_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    rngs = derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    scope = complete_scope(
        inst, case, seed, pol, version(plan), raw["H_s"], alg, phys,
        vars(initial_run_state(plan, inst, phys)),
        {key: value.getstate() for key, value in rngs.items()},
        core, driver_sha, witness_sha)
    scope_sha = fingerprint(scope)
    if scope_sha != registered["complete_input_fingerprint"]:
        raise SystemExit("scope fingerprint mismatch")
    identity = dict(
        record_class="TEST" if test_only else "EXECUTION",
        test_only=test_only,
        driver_path=str(Path(__file__).resolve()),
        driver_sha256=driver_sha,
        runner_path=str(Path(runner.__file__).resolve()),
        runner_sha256=dependency_sha["run_emin005.py"],
        recovery_path=str((SOURCE_ROOT / "source/proj_r6/src/tdr/recovery.py").resolve()),
        recovery_sha256=hashlib.sha256((SOURCE_ROOT / "source/proj_r6/src/tdr/recovery.py").read_bytes()).hexdigest(),
        simulate_path=str(Path(loaded_simulate.__file__).resolve()),
        witness_sha256=witness_sha,
        nominal_sha256=nominal_sha,
        scope_fingerprint=scope_sha,
        core_freeze_sha256=REQUIRED_FREEZE,
        dependency_sha256=dependency_sha,
    )
    runner.dump(root / variant / "startup_identity" / hmode / stream / f"{case}_{seed}_{arm}.json", identity)
    saved = read(witness)
    flags = saved["flags"]
    if not isinstance(flags, list):
        raise SystemExit("recorded witness flags are not a list")
    world = TestWorld(inst, case, tuple(sorted(flags)))
    with runner.audit_evaluations() as startup_audit:
        ev = runner.evaluate_plan(plan, inst, phys, runner.initial_state(inst, phys), H, "PRE_EXECUTION_NOMINAL_VERIFY", budget=Budget(1, None))
    runner.dump(root / variant / "startup_ledgers" / hmode / stream / f"{case}_{seed}_{arm}.json", startup_audit.summary())
    if not (ev.feasible and verify_plan(inst, None, plan, pol, phys, H).ok):
        raise SystemExit("nominal verify failed")
    start = time.perf_counter()
    with runner.audit_evaluations() as audit, finish_candidate_calls() as finish_counts:
        try:
            with observe_initializations(root / variant / "observer/formal" / hmode / stream / f"{case}_{seed}_{arm}", world, inst, phys, alg) as observed_world:
                episode = runner.run_episode(
                    inst, plan, ev, H, phys, observed_world, pol, alg,
                    runner.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                    recovery_eval_budget=alg.deterministic_recovery_eval_budget,
                    recovery_wall_s=None, cut_mode="snapshot", max_replans=inst.n, ground_finish=True)
        finally:
            runner.dump(root / variant / "live_ledgers" / hmode / stream / f"{case}_{seed}_{arm}.json",
                        dict(ledger=audit.summary(), finish_candidates=dict(finish_counts)))
    elapsed = time.perf_counter() - start
    segments = runner.clean(episode.segments)
    observations = runner.clean(episode.observations)
    replay = runner.verify_replay(inst, replace(phys, soft_h=True) if episode.ground_finish_verified else phys, segments, H, pol)
    parts = bill(segments, phys, H)
    paid = episode.ground_finish_cost if episode.ground_finish_verified else episode.evaluation.cost if episode.status == "COMPLETED_VERIFIED" else None
    startup_summary = startup_audit.summary()
    episode_summary = audit.summary()
    account = stage_account(
        startup_summary, episode_summary,
        root / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl")
    energies = getattr(replay, "min_energy", None) or {}
    row = dict(
        record_class="TEST" if test_only else "EXECUTION",
        test_only=test_only,
        publishable=False if test_only else None,
        world_source_sha256=witness_sha,
        nominal_source_sha256=nominal_sha,
        nominal_role=role, recovery_policy=pol, variant=variant, case=case, arm=arm,
        policy=pol, stream=stream, seed=seed, hmode=hmode, H=H, paid=paid, parts=parts,
        seconds=elapsed, status=episode.status, emergency=episode.ground_finish_verified,
        valid=replay.ok, delivered=replay.delivered, parcels=inst.n,
        delta=None if paid is None or replay.cost is None else abs(replay.cost - paid),
        min_energy=min(energies.values(), default=None),
        startup_calls=account["startup"], episode_calls=account["episode"],
        calls=account["episode"], calls_is_not_stage_total=True,
        stage_account=account,
        input_plan_version=version(plan),
        loaded_identity=identity,
        core_freeze_sha256=REQUIRED_FREEZE,
        execution_pid=os.getpid(),
    )
    if counters is not None:
        row["dry_run_counters"] = dict(
            stub_reasons=list(counters["stub_reasons"]),
            real_evaluate_body=counters["real_evaluate_body"],
            schedule_plan=counters["schedule_plan"],
        )
        runner.dump(root / "DRY_RUN_COUNTERS.json", row["dry_run_counters"])
    dest = root / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json"
    if dest.exists():
        raise SystemExit("output already exists " + dest.name)
    initial_start = runner.clean(_state_record(initial_run_state(plan, inst, phys), phys))
    runner.dump(dest, dict(
        record_class=row["record_class"], test_only=test_only,
        row=row, finish_candidates=dict(finish_counts), observations=observations,
        replay=replay, ledger=episode_summary, segments=segments, notes=episode.notes, replans=episode.replans,
    ))
    failure = completion_failure(
        replay, paid, parts, inst.n, row["delta"], segments, observations, flags, episode_summary, initial_start)
    if failure:
        raise SystemExit(failure)
    return row


def shift(job):
    if not approved():
        raise SystemExit("not launched")
    bind_core()
    root = output_root()
    if os.environ.get("M49_DRY_RUN") == "1" and root.resolve() == HERE.resolve():
        raise SystemExit("dry run refuses the production directory")
    variant, case, _arm, _stream, seed, _hmode = job
    journal_path = root / "call_journals" / f"{variant}_{case}_{seed}_{job[2]}.jsonl"
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
