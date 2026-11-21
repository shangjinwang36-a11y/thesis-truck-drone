"""One first recovery per pinned M49 cut. The approval gate is closed by default.

The physical path calls the candidate recovery's initial_recovery and the sealed
optimize, with the original Budget objects and the existing extend triggers.
Nothing here adds a rescue, a hard-suffix check, or a makespan objective.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
REG = json.loads((HERE / "BUDGET_REGISTRATION.json").read_text())
PIN = json.loads((HERE / "PINNED_M49_CUT.json").read_text())
LAUNCH_ENV = "M49_CONDITIONAL_APPROVED"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output_root():
    raw = os.environ.get("M49_CONDITIONAL_OUTPUT")
    return Path(raw) if raw else HERE / "conditional_runs"


def approved():
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def preflight():
    freeze = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha256(freeze) != REG["core_freeze_sha256"]:
        raise SystemExit("core freeze mismatch")
    core = json.loads(freeze.read_text())
    if len(core) != 147 or any(sha256(CORE / name) != digest for name, digest in core.items()):
        raise SystemExit("core member mismatch")
    if sha256(CORE / "source/proj_r6/src/tdr/simulate.py") != REG["simulate_sha256_m48_and_39a85"]:
        raise SystemExit("simulate.py is not the sealed budget caller")
    if sha256(CORE / "source/proj_r6/src/tdr/recovery.py") != REG["sealed_recovery_sha256"]:
        raise SystemExit("sealed recovery changed")
    if sha256(HERE / "recovery.py") != REG["candidate_recovery_sha256"]:
        raise SystemExit("candidate recovery changed")
    if PIN["source"] != "M49_finished_first_recovery":
        raise SystemExit("conditional input is not pinned to the M49 cut")
    for job, row in PIN["cells"].items():
        path = Path(row["visible_context"])
        if sha256(path) != row["byte_sha256"]:
            raise SystemExit("pinned M49 visible context hash mismatch " + job)
        if row.get("treat_as_m48_input"):
            raise SystemExit("M49 cut must not be labeled as an M48 input")
    root = output_root()
    if root.exists() and any(root.iterdir()):
        raise SystemExit("output already exists")
    stages = {item["name"]: item for item in REG["stages"]}
    if stages["INIT_BASE"]["amount"] != 100 or stages["MAIN"]["amount"] != 1000:
        raise SystemExit("base budgets are not INIT 100 and MAIN 1000")
    if stages["MAIN"]["budget_object"] != "main" or stages["INIT_RESCUE"]["budget_object"] != "init":
        raise SystemExit("main and init budgets are mixed")
    return dict(status="PREFLIGHT_OK", cells=list(PIN["cells"]), output=str(root))


def _bind_overlay():
    entries = [
        str(CORE / "source/proj_r6/src"),
        str(CORE / "source/round10_recheck"),
        str(CORE),
        str(HERE.parent / "M47_bounded_actual_20261121"),
    ]
    for entry in reversed(entries):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    import importlib.util
    import tdr
    spec = importlib.util.spec_from_file_location("tdr.recovery", HERE / "recovery.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tdr.recovery"] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != (HERE / "recovery.py").resolve():
        raise SystemExit("overlay did not load the candidate recovery")
    return module


def launch():
    """Real one-recovery path. Reached only after approval and preflight."""
    report = preflight()
    module = _bind_overlay()
    from tdr.alns import Budget, SearchStats, SolveContext, optimize
    from tdr.evaluation_audit import EvaluationAudit, audit_evaluations
    from tdr.simulate import derive_rngs
    import compare_visible
    root = output_root()
    root.mkdir(parents=True, exist_ok=False)
    for job, row in PIN["cells"].items():
        loaded = compare_visible.load_context(row["visible_context"])
        if compare_visible.digest(compare_visible.context_view(loaded)) != row["semantic_sha256"]:
            raise SystemExit("pinned semantic digest mismatch " + job)
        inst, phys, alg, plan, state, greq, opts = loaded
        if opts.get("rescue_evals") != alg.deterministic_recovery_eval_budget:
            raise SystemExit("saved rescue_evals is not the sealed main limit")
        case, _seed, arm = job.split("_")
        dest = root / job
        if dest.exists():
            raise SystemExit("output already exists " + job)
        journal_path = dest / "journal.jsonl"
        dest.mkdir(parents=True)
        journal = journal_path.open("x")
        original = EvaluationAudit.record

        def recorded(self, reason, budget, accepted, _original=original, _journal=journal):
            _original(self, reason, budget, accepted)
            _journal.write(json.dumps(dict(
                reason=reason, accepted=bool(accepted),
                used=None if budget is None else budget.used,
                limit=None if budget is None else budget.eval_limit,
                scenario=bool(getattr(budget, "scenario_ledger", False)),
            )) + "\n")
            _journal.flush()

        EvaluationAudit.record = recorded
        try:
            with audit_evaluations() as init_audit:
                init_budget = Budget(alg.recovery_init_eval_budget, None)
                init_stats = SearchStats()
                init_info = {}
                opt, reasons, catalog = module.initial_recovery(
                    plan, state, inst, phys, arm, greq, H=opts["H"],
                    extra_pool=opts.get("extra_pool") or [], frag_sid=opts["frag_sid"],
                    stats=init_stats, budget=init_budget, rescue_evals=opts["rescue_evals"],
                    info=init_info, use_milp=opts["use_milp"], joint=opts["joint"],
                    slot_aware=opts["slot_aware"], unlaunched=opts["unlaunched"],
                    preserve_cross=opts["preserve_cross"], keep_s_recovery=opts["keep_s_recovery"],
                    limit_new_air=opts["limit_new_air"], new_air_penalty=opts["new_air_penalty"],
                )
            init_summary = init_audit.summary()
            (dest / "init_ledger.json").write_text(json.dumps(init_summary))
            first = None if opt is None else dict(cost=opt.ev.cost, z=opt.ev.z, label=opt.label)
            (dest / "first_feasible.json").write_text(json.dumps(dict(
                found=opt is not None, first=first, reasons=reasons[:20],
                init_limit=init_budget.eval_limit, init_used=init_budget.used,
                rescue_used=bool(init_info.get("rescue_used")),
                fallback_used=bool(init_info.get("fallback_used")),
                joint_used=bool(init_info.get("joint_used")),
            )))
            final = None
            if opt is not None:
                with audit_evaluations() as main_audit:
                    main_budget = Budget(alg.deterministic_recovery_eval_budget, None)
                    main_stats = SearchStats()
                    frag = plan.sorties[opts["frag_sid"]]
                    rngs = derive_rngs(alg.base_algorithm_seed, case, "recovery", 1)
                    context = SolveContext(
                        inst=inst, phys=phys, alg=alg, state=state, H=opts["H"], mode="recovery",
                        affected_drones={frag.drone}, affected_sorties={opts["frag_sid"]},
                        ground_required=set(greq), replan_index=1, rngs=rngs, catalog=catalog,
                        frag_sid=opts["frag_sid"], strategy=arm, air_ceiling=state.air_ceiling,
                    )
                    solution = optimize(opt.plan, context, main_budget, variant="full", stats=main_stats, init_ev=opt.ev)
                final = None if solution.evaluation is None else dict(cost=solution.evaluation.cost, z=solution.evaluation.z)
                (dest / "main_ledger.json").write_text(json.dumps(main_audit.summary()))
            (dest / "final.json").write_text(json.dumps(dict(
                final=final, main_started=opt is not None,
                note="no object-external hard check is added; INIT and MAIN stay separate",
            )))
        finally:
            EvaluationAudit.record = original
            journal.close()
    return report


def main():
    report = preflight()
    if not approved():
        report["status"] = "NOT_LAUNCHED"
        print(json.dumps(report))
        return
    launch()
    print(json.dumps(dict(status="LAUNCHED", cells=report["cells"])))


if __name__ == "__main__":
    main()
