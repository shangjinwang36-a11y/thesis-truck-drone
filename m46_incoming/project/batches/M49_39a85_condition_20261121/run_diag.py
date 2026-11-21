"""One paid diagnostic on an original visible pickle. Refuses to overwrite anything."""
from pathlib import Path
import hashlib
import json
import os
import pickle
import sys
import time
from dataclasses import asdict

CORE = Path("/workspace/m46_incoming/project/batches/M49_landed_wait_core_20261121")
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"
REQUIRED_RECOVERY = "54c730fff2b5185c2400aa30d0df751af6564b80833b67ce89c6821c7916ab3d"
PICKLES = {
    1001: (
        Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_20261121/M48_RECOVERY/observer/formal/own/dev/RC100_1001_X/009/VISIBLE_CONTEXT.pkl"),
        "7991dc301fbc41e56270a77c1021f15655e288c1f314a493c34556880475373b",
    ),
    1002: (
        Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_20261121/M48_RECOVERY/observer/formal/own/dev/RC100_1002_X/011/VISIBLE_CONTEXT.pkl"),
        "8dcbc98d80810b4407df872f021ec43f128d4c03712b564aa2e3120be340c45a",
    ),
}
SEED = int(sys.argv[1])
OUT = Path(__file__).resolve().parent / f"RC100_{SEED}"
if OUT.exists() and any(OUT.iterdir()):
    raise SystemExit("output directory is not empty " + str(OUT))
OUT.mkdir()
for name in ("RAW.jsonl", "receipts.jsonl", "INPUT_VISIBLE.json", "RESULT.json"):
    if (OUT / name).exists():
        raise SystemExit("output already exists " + name)

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

freeze_path = CORE / "EXPERIMENT_CORE_FREEZE.json"
freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
if freeze_sha != REQUIRED_FREEZE:
    raise SystemExit("core freeze is not 39a85da8")
freeze = json.loads(freeze_path.read_text())
if len(freeze) != 147:
    raise SystemExit("core is not 147 members")
for name, digest in freeze.items():
    if hashlib.sha256((CORE / name).read_bytes()).hexdigest() != digest:
        raise SystemExit("core member mismatch " + name)
recovery_sha = hashlib.sha256((CORE / "source/proj_r6/src/tdr/recovery.py").read_bytes()).hexdigest()
if recovery_sha != REQUIRED_RECOVERY:
    raise SystemExit("recovery.py is not the audited file")
if "schedule_plan" in (CORE / "source/proj_r6/src/tdr/recovery.py").read_text().split("does not call schedule_plan", 1)[-1]:
    pass
src, expected = PICKLES[SEED]
got = hashlib.sha256(src.read_bytes()).hexdigest()
if got != expected:
    raise SystemExit("pickle identity mismatch")

raw_f = (OUT / "RAW.jsonl").open("x", encoding="utf-8")
receipt_f = (OUT / "receipts.jsonl").open("x", encoding="utf-8")
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

inst, phys, alg, plan, state, greq, opts = pickle.load(open(src, "rb"))
plan = plan.clone()
if alg.recovery_init_eval_budget != 100 or alg.deterministic_recovery_eval_budget != 1000 or opts["rescue_evals"] != 1000:
    raise SystemExit("budgets are not the original contract")
(OUT / "INPUT_VISIBLE.json").write_text(json.dumps(dict(
    seed=SEED, case="RC100", H=opts["H"], frag_sid=opts["frag_sid"],
    source_pickle_sha256=got, core_freeze_sha256=freeze_sha, recovery_sha256=recovery_sha,
    plan=plan_to_dict(plan, inst), state=asdict(state), ground_required_count=len(greq),
    this_run_is="M49_39a85_fresh_directory_geometric_reorder",
    injected_prior_winner=False,
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
            chosen_plan, chosen_ev, source_name = sol.plan, sol.evaluation, "ALNS"
        else:
            chosen_plan, chosen_ev, source_name = opt.plan, opt.ev, "INITIAL"
        hard = persisting_eval(chosen_plan, inst, phys, state, opts["H"], "DIAGNOSTIC_HARD_SUFFIX")
        chosen = dict(source=source_name, cost=chosen_ev.cost, hard=bool(hard.feasible), hard_violations=list(hard.violations[:6]))
        if hard.timeline is not None:
            end = max(list(hard.timeline.truck_finish.values()) + [state.t0])
            suffix = collect_segment(chosen_plan, hard.timeline, inst, phys, state.t0, end, state)
            (OUT / "SELECTED_PLAN.json").write_text(json.dumps(plan_to_dict(chosen_plan, inst), indent=1))
            (OUT / "SELECTED_SUFFIX_SEGMENT.json").write_text(json.dumps(suffix, indent=1))
            (OUT / "SELECTED_EVALUATION.json").write_text(json.dumps(dict(
                source=source_name, cost=chosen_ev.cost, feasible=chosen_ev.feasible,
                violations=list(chosen_ev.violations), hard_feasible=hard.feasible,
                hard_violations=list(hard.violations), hard_cost=hard.cost,
                depot_gate=committed_first_stop_violation(chosen_plan, state),
            ), indent=1))
result = dict(
    seed=SEED, calls=call_n["n"], seconds=time.perf_counter() - started,
    init_found=opt is not None, init_used=init_budget.used, init_limit=init_budget.eval_limit,
    rescue_used=bool(info.get("rescue_used")), first_reasons=list(reasons[:8]),
    main_used=main_used, chosen=chosen, ledger=audit.summary(),
    core_freeze_sha256=freeze_sha, recovery_sha256=recovery_sha, source_pickle_sha256=got,
)
(OUT / "RESULT.json").write_text(json.dumps(result, indent=1, default=str))
raw_f.close()
receipt_f.close()
print("M49_39A85", SEED, "calls", call_n["n"], "found", opt is not None, "init", init_budget.used, "main", main_used, "rescue", bool(info.get("rescue_used")), "chosen", chosen, "reasons", reasons[:3])
