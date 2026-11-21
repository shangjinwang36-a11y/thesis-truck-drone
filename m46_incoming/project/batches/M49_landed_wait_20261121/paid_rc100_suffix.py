"""Paid M49 suffix for one saved RC100 visible state. Does not read world flags."""
from pathlib import Path
import hashlib
import json
import os
import pickle
import sys
import time

CORE = Path("/workspace/m46_incoming/project/batches/M49_landed_wait_core_20261121")
SEED = int(sys.argv[1])
FOLDER = {1001: "009", 1002: "011"}[SEED]
os.environ.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.path.insert(0, str(CORE / "source/proj_r6/src"))
sys.path.insert(0, str(CORE / "source/round10_recheck"))
sys.path.insert(0, str(CORE))

import tdr.alns as alns_mod  # noqa: E402
import tdr.evaluate as evaluate_mod  # noqa: E402
from tdr.alns import Budget, SearchStats, SolveContext, optimize  # noqa: E402
from tdr.evaluation_audit import audit_evaluations  # noqa: E402
from tdr.experiment import plan_to_dict  # noqa: E402
from tdr.recovery import initial_recovery  # noqa: E402
from tdr.schedule import committed_first_stop_violation  # noqa: E402
from tdr.simulate import collect_segment, derive_rngs  # noqa: E402
from dataclasses import asdict  # noqa: E402

OUT = Path(__file__).resolve().parent / "paid_rehome" / f"RC100_{SEED}"
OUT.mkdir(parents=True, exist_ok=True)
raw_f = (OUT / "RAW.jsonl").open("w", encoding="utf-8")
receipt_f = (OUT / "receipts.jsonl").open("w", encoding="utf-8")
call_n = {"n": 0}
original_eval = evaluate_mod.evaluate_plan


def persisting_eval(plan, inst, phys, state, H, reason="", *args, **kwargs):
    ev = original_eval(plan, inst, phys, state, H, reason, *args, **kwargs)
    call_n["n"] += 1
    violation = ev.violations[0] if ev.violations else None
    raw_f.write(json.dumps(dict(
        index=call_n["n"], reason=reason, feasible=ev.feasible, status=ev.status,
        cost=ev.cost, z=ev.z, violation=violation, plan=plan_to_dict(plan, inst),
    ), ensure_ascii=False) + "\n")
    raw_f.flush()
    os.fsync(raw_f.fileno())
    receipt_f.write(json.dumps(dict(
        index=call_n["n"], reason=reason, feasible=ev.feasible, status=ev.status,
        cost=ev.cost, violation=violation,
        budget_used=None if kwargs.get("budget") is None else kwargs["budget"].used,
        budget_limit=None if kwargs.get("budget") is None else kwargs["budget"].eval_limit,
    ), ensure_ascii=False) + "\n")
    receipt_f.flush()
    os.fsync(receipt_f.fileno())
    return ev


evaluate_mod.evaluate_plan = persisting_eval
alns_mod.evaluate_plan = persisting_eval

src = Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_20261121/M48_RECOVERY/observer/formal/own/dev") / f"RC100_{SEED}_X" / FOLDER / "VISIBLE_CONTEXT.pkl"
inst, phys, alg, plan, state, greq, opts = pickle.load(open(src, "rb"))
plan = plan.clone()
assert alg.recovery_init_eval_budget == 100 and alg.deterministic_recovery_eval_budget == 1000
assert opts["rescue_evals"] == 1000
scope = hashlib.sha256((CORE / "EXPERIMENT_CORE_FREEZE.json").read_bytes()).hexdigest()
(OUT / "INPUT_VISIBLE.json").write_text(json.dumps(dict(
    seed=SEED, case="RC100", H=opts["H"], frag_sid=opts["frag_sid"],
    source_pickle_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
    core_freeze_sha256=scope,
    plan=plan_to_dict(plan, inst), state=asdict(state),
    ground_required_count=len(greq),
    this_run_is="M49_rehome_overflow_visits_keep_customer",
), indent=1, default=str))
started = time.perf_counter()
with audit_evaluations() as audit:
    init_budget = Budget(alg.recovery_init_eval_budget, None)
    info = {}
    opt, reasons, _catalog = initial_recovery(
        plan, state, inst, phys, "X", set(greq),
        H=opts["H"], extra_pool=list(opts.get("extra_pool") or []), frag_sid=opts["frag_sid"],
        stats=SearchStats(), budget=init_budget, rescue_evals=opts["rescue_evals"], info=info,
        use_milp=opts["use_milp"], joint=opts["joint"], slot_aware=opts["slot_aware"],
        unlaunched=opts["unlaunched"], preserve_cross=opts["preserve_cross"],
        keep_s_recovery=opts["keep_s_recovery"], limit_new_air=opts["limit_new_air"],
        new_air_penalty=opts["new_air_penalty"])
    chosen = None
    main_used = None
    if opt is not None:
        main = Budget(alg.deterministic_recovery_eval_budget, None)
        rngs = derive_rngs(alg.base_algorithm_seed, inst.case_id, "recovery", 1)
        ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state, H=opts["H"], mode="recovery",
                           affected_drones=set(), affected_sorties={opts["frag_sid"]},
                           ground_required=set(greq), replan_index=1, rngs=rngs, frag_sid=opts["frag_sid"],
                           strategy="X")
        sol = optimize(opt.plan, ctx, main, variant="full", stats=SearchStats(), init_ev=opt.ev)
        main_used = main.used
        if sol.evaluation is not None and sol.evaluation.feasible and sol.evaluation.cost <= opt.ev.cost + 1e-9:
            chosen_plan, chosen_ev, source = sol.plan, sol.evaluation, "ALNS"
        else:
            chosen_plan, chosen_ev, source = opt.plan, opt.ev, "INITIAL"
        hard = persisting_eval(chosen_plan, inst, phys, state, opts["H"], "DIAGNOSTIC_HARD_SUFFIX")
        chosen = dict(source=source, cost=chosen_ev.cost, hard=bool(hard.feasible), hard_violations=list(hard.violations[:6]))
        if hard.timeline is not None:
            end = max(list(hard.timeline.truck_finish.values()) + [state.t0])
            suffix = collect_segment(chosen_plan, hard.timeline, inst, phys, state.t0, end, state)
            (OUT / "SELECTED_PLAN.json").write_text(json.dumps(plan_to_dict(chosen_plan, inst), indent=1))
            (OUT / "SELECTED_SUFFIX_SEGMENT.json").write_text(json.dumps(suffix, indent=1))
            from tdr.replay import verify_replay
            sys.path.insert(0, str(CORE))
            from bill import bill
            replay = verify_replay(inst, phys, [suffix], opts["H"], "X")
            invoice = sum(bill([suffix], phys, opts["H"]).values())
            chosen.update(
                replay_ok=bool(replay.ok), replay_violations=list(replay.violations[:6]),
                min_energy=min(replay.min_energy.values(), default=None),
                invoice=invoice, invoice_matches_hard=hard.cost is not None and abs(invoice - hard.cost) < 1e-6,
            )
        (OUT / "SELECTED_EVALUATION.json").write_text(json.dumps(dict(
            source=source, cost=chosen_ev.cost, feasible=chosen_ev.feasible,
            violations=list(chosen_ev.violations), hard_feasible=hard.feasible,
            hard_violations=list(hard.violations), hard_cost=hard.cost,
            depot_gate=committed_first_stop_violation(chosen_plan, state),
        ), indent=1))
result = dict(
    seed=SEED, calls=call_n["n"], seconds=time.perf_counter() - started,
    init_found=opt is not None, init_used=init_budget.used, init_limit=init_budget.eval_limit,
    rescue_used=bool(info.get("rescue_used")), first_reasons=list(reasons[:8]),
    main_used=main_used, chosen=chosen, ledger=audit.summary(),
)
(OUT / "RESULT.json").write_text(json.dumps(result, indent=1, default=str))
raw_f.close()
receipt_f.close()
print("M49", SEED, "calls", call_n["n"], "found", opt is not None, "init", init_budget.used, "main", main_used, "chosen", chosen, "reasons", reasons[:3])
