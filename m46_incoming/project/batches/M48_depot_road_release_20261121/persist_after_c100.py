"""Persist one M48 after-fix C100 replay. Does not change search order or budgets.

The earlier PAID_AFTER summary stays the record of the unsaved run.
This file is a later, separately billed re-enactment.
"""
from pathlib import Path
import hashlib
import json
import os
import pickle
import sys
import time

CORE = Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_core_20261121")
SEED = int(sys.argv[1])
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

OUT = Path(__file__).resolve().parent / "rerun_after" / f"C100_{SEED}"
OUT.mkdir(parents=True, exist_ok=True)
raw_path = OUT / "RAW.jsonl"
receipt_path = OUT / "receipts.jsonl"
raw_f = raw_path.open("w", encoding="utf-8")
receipt_f = receipt_path.open("w", encoding="utf-8")
call_n = {"n": 0}
original_eval = evaluate_mod.evaluate_plan


def persisting_eval(plan, inst, phys, state, H, reason="", *args, **kwargs):
    ev = original_eval(plan, inst, phys, state, H, reason, *args, **kwargs)
    call_n["n"] += 1
    violation = ev.violations[0] if ev.violations else None
    raw_f.write(json.dumps(dict(
        index=call_n["n"], reason=reason, feasible=ev.feasible, status=ev.status,
        cost=ev.cost, z=ev.z, violation=violation,
        plan=plan_to_dict(plan, inst),
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

OBS = Path("/workspace/m46_incoming/project/batches/M47_bounded_actual_20261121/M47_CANDIDATE/observer/formal/own/dev")
blob = pickle.load(open(OBS / f"C100_{SEED}_X/001/VISIBLE_CONTEXT.pkl", "rb"))
inst, phys, alg, plan, state, greq, opts = blob
plan = plan.clone()
freeze = json.loads((CORE / "EXPERIMENT_CORE_FREEZE.json").read_text())
scope = {name: hashlib.sha256((CORE / name).read_bytes()).hexdigest() for name in (
    "source/proj_r6/src/tdr/cut_launch_windows.py",
    "source/proj_r6/src/tdr/recovery.py",
    "source/proj_r6/src/tdr/schedule.py",
    "source/proj_r6/src/tdr/simulate.py",
    "EXPERIMENT_CORE_FREEZE.json",
)}
assert all(scope[name] == freeze[name] for name in scope if name != "EXPERIMENT_CORE_FREEZE.json")
visible = dict(
    seed=SEED, case="C100", arm="X", strategy="X",
    H=opts["H"], frag_sid=opts["frag_sid"], rescue_evals=opts["rescue_evals"],
    init_budget=alg.recovery_init_eval_budget, main_budget=alg.deterministic_recovery_eval_budget,
    options={k: opts[k] for k in opts if k != "extra_pool"},
    extra_pool_count=len(opts.get("extra_pool") or []),
    greq_count=len(greq),
    plan=plan_to_dict(plan, inst),
    state=asdict(state),
    core_scope_sha256=scope,
    rng=f"tdr_v61|{alg.base_algorithm_seed}|{inst.case_id}|recovery|1|operator+destroy+accept",
    this_run_is="later_persisted_reenactment_not_the_unsaved_original",
)
(OUT / "INPUT_VISIBLE.json").write_text(json.dumps(visible, indent=1, default=str))
air_before = {p for s in plan.sorties.values() for p in s.air}
t0 = time.perf_counter()
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
    assert init_budget.eval_limit in (100, 1100, 1304) or init_budget.used <= init_budget.eval_limit
    main_used = None
    chosen_plan = chosen_ev = source = None
    if opt is not None:
        main = Budget(alg.deterministic_recovery_eval_budget, None)
        assert main.eval_limit == 1000 and alg.recovery_init_eval_budget == 100
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
        end = max(list(hard.timeline.truck_finish.values()) + [state.t0])
        suffix = collect_segment(chosen_plan, hard.timeline, inst, phys, state.t0, end, state)
        (OUT / "SELECTED_PLAN.json").write_text(json.dumps(plan_to_dict(chosen_plan, inst), indent=1))
        (OUT / "SELECTED_EVALUATION.json").write_text(json.dumps(dict(
            source=source, cost=chosen_ev.cost, z=chosen_ev.z, feasible=chosen_ev.feasible,
            violations=list(chosen_ev.violations), init_cost=opt.ev.cost,
            hard_feasible=hard.feasible, hard_violations=list(hard.violations),
            hard_cost=hard.cost,
        ), indent=1))
        (OUT / "SELECTED_SUFFIX_SEGMENT.json").write_text(json.dumps(suffix, indent=1))
result = dict(
    seed=SEED, calls_flushed=call_n["n"],
    init_found=opt is not None, init_used=init_budget.used, init_limit=init_budget.eval_limit,
    rescue_used=bool(info.get("rescue_used")), init_source=info.get("best_source"),
    first_reasons=list(reasons[:8]), n_reasons=len(reasons),
    main_used=main_used, source=source,
    final_cost=None if chosen_ev is None else chosen_ev.cost,
    seconds=time.perf_counter() - t0,
    ledger=audit.summary(),
    input_depot_gate=committed_first_stop_violation(plan, state),
)
if chosen_plan is not None:
    result["selected_depot_gate"] = committed_first_stop_violation(chosen_plan, state)
    result["new_air_count"] = len({p for s in chosen_plan.sorties.values() for p in s.air} - air_before)
(OUT / "RESULT.json").write_text(json.dumps(result, indent=1, default=str))
raw_f.close()
receipt_f.close()
print("RERUN", SEED, "calls", call_n["n"], "init", init_budget.used, "main", main_used, "cost", None if chosen_ev is None else chosen_ev.cost, "sec", round(result["seconds"], 1))
