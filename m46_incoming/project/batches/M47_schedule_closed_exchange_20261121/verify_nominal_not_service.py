"""Independent nominal replay. This is not an actual SERVICE audit.

Checks custody, body stages, 20 s handover U, energy, swaps, slots, hard H,
the invoice, and one post-hoc fixed-scenario score. Post-hoc scenario calls
are listed separately and are not part of a search budget.
"""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
sys.path.insert(0, str(CORE))

from research import setup  # noqa: E402
import run_emin005 as rr  # noqa: E402
from bill import bill  # noqa: E402
from tdr.alns import Budget, SearchStats, SolveContext  # noqa: E402
from tdr.cross_robust import cross_robust_violations  # noqa: E402
from tdr.evaluate import is_cross_sortie, evaluate_plan  # noqa: E402
from tdr.expected_cost import expected_j, failure_prob  # noqa: E402
from tdr.experiment import plan_from_dict  # noqa: E402
from tdr.hybrid import scenario_score  # noqa: E402
from tdr.schedule import initial_state  # noqa: E402
from tdr.simulate import collect_segment, initial_run_state  # noqa: E402
from tdr.verify import verify_plan  # noqa: E402


def check(plan_path: Path, case: str, label: str) -> dict:
    inst, phys, alg = setup(case, "M47", True)
    phys.set_active()
    raw = json.loads(plan_path.read_text())
    plan = plan_from_dict(raw["plan"])
    ref = alg._nominal_reference_H
    assert raw["H_s"] == ref, (raw["H_s"], ref)
    state = initial_state(inst, phys)
    rep = verify_plan(inst, state, plan, "X", phys, ref)
    ev = evaluate_plan(plan, inst, phys, state, ref, "M47_POSTHOC_PHYSICS", budget=Budget(2, None))
    rs = initial_run_state(plan, inst, phys)
    t_end = max([rs.t0, ev.z or 0.0] + list(ev.timeline.truck_finish.values()))
    seg = rr.clean(collect_segment(plan, ev.timeline, inst, phys, rs.t0, t_end, rs))
    replay = rr.verify_replay(inst, phys, [seg], ref, "X")
    invoice = bill([seg], phys, ref)
    robust = cross_robust_violations(plan, inst, phys, ev.timeline, float(alg.x_rendezvous_slack_s or 0.0))
    crosses = []
    u_rows = [round(float(a["end"]) - float(a["start"]), 6) for a in seg["actions"] if a.get("kind") == "U"]
    service_rows = [round(float(s["end"]) - float(s["start"]), 6) for s in seg["stages"] if s.get("kind") == "SERVICE"]
    bodies = []
    for s in plan.sorties.values():
        if not is_cross_sortie(plan, s):
            continue
        stages = [st for st in ev.timeline.drone_stages.get(s.drone, []) if getattr(st, "sid", None) == s.sid]
        bodies.append(dict(
            sid=s.sid, drone=s.drone,
            launch_truck=plan.visits[s.launch_vid].truck,
            rec_truck=plan.visits[s.rec_vid].truck,
            air_parcels=list(s.air),
            stage_kinds=[st.kind for st in stages],
            nominal_not_actual_service=True,
        ))
    ctx = SolveContext(inst, phys, alg, state, ref, "nominal", makespan_cap=ref)
    ctx.state.nominal_cross = True
    ctx.scenario_on = True
    ctx.live_budget = Budget(0, None)
    ctx.live_stats = SearchStats()
    before = sum(b.used for b in getattr(alg, "_scenario_budgets", {}).values())
    score = scenario_score(plan, ev, ctx)
    scenario_native = sum(b.used for b in getattr(alg, "_scenario_budgets", {}).values()) - before
    min_e = min(replay.min_energy.values()) if replay.min_energy else None
    return dict(
        label=label,
        case=case,
        nominal_not_actual_service=True,
        verify_plan_ok=rep.ok,
        verify_plan_violations=rep.violations[:8],
        replay_ok=replay.ok,
        replay_violations=list(replay.violations)[:8],
        replay_delivered_customers=replay.delivered,
        invoice_matches_replay=abs(replay.cost - sum(invoice.values())) < 1e-7,
        invoice=invoice,
        replay_cost=replay.cost,
        published_cost=raw.get("cost") if "cost" in raw else None,
        hard_H=ref,
        makespan_s=max(ev.timeline.truck_finish.values()),
        not_X_own_H=True,
        handover_U_parameter_s=phys.handover_s,
        air_service_parameter_s=phys.air_service_s,
        observed_U_action_durations_s=u_rows,
        nominal_has_no_abnormal_handover=not u_rows and all(not s.handover for s in plan.sorties.values()),
        observed_service_stage_durations_s=sorted(set(service_rows)),
        service_matches_air_service_parameter=bool(service_rows) and all(abs(x - phys.air_service_s) < 1e-6 for x in service_rows),
        min_energy_kwh=min_e,
        e_min_kwh=phys.e_min,
        energy_at_or_above_floor=min_e is not None and min_e >= phys.e_min - phys.energy_tol,
        swaps=ev.cost_breakdown.get("swaps"),
        slot_or_channel_violations=[v for v in rep.violations if v.startswith(("SLOT", "CHANNEL"))],
        custody_violations=[v for v in rep.violations if "CUSTODY" in v or v.startswith("HOLDER")],
        robust= {str(k): v for k, v in robust.items()},
        cross_sorties=bodies,
        original_J=expected_j(ev.cost, plan, inst, phys, failure_prob(alg)),
        posthoc_scenario_score=score,
        posthoc_scenario_native_calls=scenario_native,
        posthoc_physical_calls=1,
    )


def main():
    jobs = [
        (HERE / "replay_x/RC100/X/nominal_plan.json", "RC100", "replay_x_published_RC100"),
        (HERE / "replay_x/C100/X/nominal_plan.json", "C100", "replay_x_published_C100"),
    ]
    rows = []
    for path, case, label in jobs:
        if path.exists():
            rows.append(check(path, case, label))
            print(label, "verify", rows[-1]["verify_plan_ok"], "replay", rows[-1]["replay_ok"],
                  "service", rows[-1]["service_matches_air_service_parameter"],
                  "no_U", rows[-1]["nominal_has_no_abnormal_handover"],
                  "E", rows[-1]["energy_at_or_above_floor"],
                  "cross", len(rows[-1]["cross_sorties"]),
                  "scenario_calls", rows[-1]["posthoc_scenario_native_calls"], flush=True)
    out = HERE / "POSITIVE_NOMINAL_REPLAY.json"
    out.write_text(json.dumps(dict(rows=rows, not_actual_service=True), indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
