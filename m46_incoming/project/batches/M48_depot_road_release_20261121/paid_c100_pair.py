"""Paid before/after replay of the saved C100 first-failure visible state.

Does not read world flags. Does not write a fresh execution row.
"""
from pathlib import Path
import json
import os
import pickle
import sys
import time

CORE = Path(sys.argv[1]).resolve()
SEED = int(sys.argv[2])
LABEL = sys.argv[3]
os.environ.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.path.insert(0, str(CORE / "source/proj_r6/src"))
sys.path.insert(0, str(CORE / "source/round10_recheck"))
sys.path.insert(0, str(CORE))

from tdr.alns import Budget, SearchStats, SolveContext, optimize  # noqa: E402
from tdr.evaluate import evaluate_plan, forbidden_air_parcel  # noqa: E402
from tdr.evaluation_audit import audit_evaluations  # noqa: E402
from tdr.recovery import initial_recovery  # noqa: E402
from tdr.replay import verify_replay  # noqa: E402
from tdr.schedule import committed_first_stop_violation  # noqa: E402
from tdr.simulate import derive_rngs  # noqa: E402
from bill import bill  # noqa: E402

OBS = Path("/workspace/m46_incoming/project/batches/M47_bounded_actual_20261121/M47_CANDIDATE/observer/formal/own/dev")
blob = pickle.load(open(OBS / f"C100_{SEED}_X/001/VISIBLE_CONTEXT.pkl", "rb"))
inst, phys, alg, plan, state, greq, opts = blob
plan = plan.clone()
air_before = {p for s in plan.sorties.values() for p in s.air}
started = time.perf_counter()
out = dict(label=LABEL, seed=SEED, core=str(CORE), native_is_diagnostic=True, fresh_execution=False)
with audit_evaluations() as audit:
    init_budget = Budget(alg.recovery_init_eval_budget, None)
    info = {}
    stats = SearchStats()
    opt, reasons, _catalog = initial_recovery(
        plan, state, inst, phys, "X", set(greq),
        H=opts["H"], extra_pool=list(opts.get("extra_pool") or []), frag_sid=opts["frag_sid"],
        stats=stats, budget=init_budget, rescue_evals=opts["rescue_evals"], info=info,
        use_milp=opts["use_milp"], joint=opts["joint"], slot_aware=opts["slot_aware"],
        unlaunched=opts["unlaunched"], preserve_cross=opts["preserve_cross"],
        keep_s_recovery=opts["keep_s_recovery"], limit_new_air=opts["limit_new_air"],
        new_air_penalty=opts["new_air_penalty"])
    out["init"] = dict(
        found=opt is not None, used=init_budget.used, limit=init_budget.eval_limit,
        rescue_used=bool(info.get("rescue_used")), source=info.get("best_source"),
        first_reasons=list(reasons[:8]), n_reasons=len(reasons),
        depot_gate=committed_first_stop_violation(plan, state),
    )
    final = None
    if opt is not None:
        main = Budget(alg.deterministic_recovery_eval_budget, None)
        rngs = derive_rngs(alg.base_algorithm_seed, inst.case_id, "recovery", 1)
        ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=state, H=opts["H"], mode="recovery",
                           affected_drones=set(), affected_sorties={opts["frag_sid"]},
                           ground_required=set(greq), replan_index=1, rngs=rngs, frag_sid=opts["frag_sid"],
                           strategy="X")
        sol = optimize(opt.plan, ctx, main, variant="full", stats=SearchStats(), init_ev=opt.ev)
        chosen = sol if sol.evaluation is not None and sol.evaluation.feasible else None
        if chosen is None or not chosen.evaluation.feasible:
            chosen_plan, chosen_ev, source = opt.plan, opt.ev, "INITIAL"
        else:
            chosen_plan, chosen_ev, source = sol.plan, sol.evaluation, "ALNS" if sol.evaluation.cost <= opt.ev.cost + 1e-9 else "INITIAL"
            if opt.ev.cost + 1e-9 < chosen_ev.cost:
                chosen_plan, chosen_ev, source = opt.plan, opt.ev, "INITIAL"
        hard = evaluate_plan(chosen_plan, inst, phys, state, opts["H"], "DIAGNOSTIC_HARD_SUFFIX")
        from tdr.simulate import collect_segment
        segments = []
        if hard.timeline is not None:
            end = max(list(hard.timeline.truck_finish.values()) + [state.t0])
            suffix = collect_segment(chosen_plan, hard.timeline, inst, phys, state.t0, end, state)
            exec_path = Path("/workspace/m46_incoming/project/batches/M47_bounded_actual_20261121/M47_CANDIDATE/executions/own/dev") / f"C100_{SEED}_X.json"
            original = json.loads(exec_path.read_text())
            original.pop("flags", None)
            prefix = original["segments"][0]
            segments = [prefix, suffix]
        replay = verify_replay(inst, phys, segments, opts["H"], "X") if segments else None
        invoice = None if not segments else sum(bill(segments, phys, opts["H"]).values())
        air_after = {p for s in chosen_plan.sorties.values() for p in s.air}
        drives = []
        if hard.timeline is not None:
            for truck, pos in state.truck_start_pos.items():
                first = next((a for a in hard.timeline.actions if a.actor == truck and a.kind == "DRIVE"), None)
                if first is not None:
                    drives.append(dict(truck=truck, from_matches_snapshot=list(first.info["from"]) == list(pos), ref=first.ref))
        u_bad = []
        if hard.timeline is not None:
            u_bad = [round(a.end - a.start, 6) for a in hard.timeline.actions if a.kind == "U" and abs((a.end - a.start) - phys.handover_s) > 1e-4]
        out["suffix"] = dict(
            source=source, init_cost=opt.ev.cost, final_cost=chosen_ev.cost,
            main_used=main.used, main_limit=main.eval_limit,
            hard_feasible=bool(hard.feasible), hard_violations=list(hard.violations[:8]),
            depot_gate=committed_first_stop_violation(chosen_plan, state),
            ground_required_still_air=forbidden_air_parcel(chosen_plan, set(greq)),
            replay_ok=None if replay is None else bool(replay.ok),
            replay_violations=None if replay is None else list(replay.violations[:8]),
            min_energy=None if replay is None else min(replay.min_energy.values(), default=None),
            invoice=invoice, invoice_matches_replay=None if invoice is None or replay is None else abs(invoice - replay.cost) < 1e-6,
            new_air_parcels=sorted(air_after - air_before),
            u_not_20s=u_bad,
            drives=drives,
            h=opts["H"], e_min=phys.e_min,
        )
        final = out["suffix"]["hard_feasible"] and out["suffix"]["replay_ok"] and not out["suffix"]["new_air_parcels"] and out["suffix"]["depot_gate"] is None
    out["ledger"] = audit.summary()
out["seconds"] = time.perf_counter() - started
out["complete_hard_suffix"] = bool(final)
dest = Path(__file__).resolve().parent / f"PAID_{LABEL}_C100_{SEED}.json"
dest.write_text(json.dumps(out, indent=1, default=str))
print(LABEL, SEED, "init_found", out["init"]["found"], "init_used", out["init"]["used"], "reasons", out["init"]["first_reasons"][:3], "hard", out.get("suffix", {}).get("hard_feasible"), "sec", round(out["seconds"], 1))
