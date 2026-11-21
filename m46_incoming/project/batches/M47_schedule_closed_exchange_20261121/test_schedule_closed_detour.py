"""Operator path tests. Native calls are diagnostic, not a fresh nominal run.

Positive: the sealed RC100 and C100 champions emit a complete cross and that
plan is compared with original J after a charged physical evaluation.
Negative: energy (reserve floor), timing (hard H), and cargo custody (the
receiver already visits the customer) each fail on a charged evaluation.
"""
from dataclasses import replace
from pathlib import Path
import pickle

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
SEAL = HERE.parent / "M46_paid_training_robust_joint_20261121"
import sys
sys.path.insert(0, str(CORE))

from research import setup  # noqa: E402
import run_emin005 as rr  # noqa: E402
from tdr.alns import Budget, SearchStats, SolveContext  # noqa: E402
from tdr.cross_robust import cross_robust_violations  # noqa: E402
from tdr.evaluate import has_wait_cycle, is_cross_sortie  # noqa: E402
from tdr.expected_cost import expected_j, failure_prob  # noqa: E402
from tdr.hybrid import scenario_score  # noqa: E402
from tdr.joint_air_promote import air  # noqa: E402
from tdr.schedule_closed_exchange import geometries  # noqa: E402


def _sealed(case):
    inst, phys, alg = setup(case, "M47", True)
    phys.set_active()
    _ci, _cp, plan, ev, state, ref = pickle.loads(
        (SEAL / f"fresh_new/{case}/X_live/normal_terminal_final.pkl").read_bytes())
    state.nominal_cross = True
    alg._mature_fullpool_air_sets = {tuple(sorted(air(plan)))}
    alg._schedule_closed_emitted = 0
    ctx = type("C", (), {})()
    ctx.inst, ctx.phys, ctx.alg, ctx.state, ctx.H = inst, phys, alg, state, ref
    return inst, phys, alg, plan, ev, state, ref, ctx


def _emit(case):
    inst, phys, alg, plan, ev, state, ref, ctx = _sealed(case)
    diag = {}
    out = geometries(plan, ev, ctx, diag)
    assert diag["native_calls"] == 0
    return inst, phys, alg, plan, ev, state, ref, out, diag


def test_rc100_and_c100_enter_native_j_and_scenario():
    """Complete candidates. Proxy veto would have dropped the C100 plan."""
    physical = Budget(4, None)
    # RC100: delete an empty recovery stop. J and the fixed scenario both rise.
    inst, phys, alg, plan, ev, state, ref, out, diag = _emit("RC100")
    assert out and all(desc["parcels"] == [] for _q, desc in out)
    parent_j = expected_j(ev.cost, plan, inst, phys, failure_prob(alg))
    q, desc = out[0]
    assert air(q) == air(plan)
    assert is_cross_sortie(q, q.sorties[desc["sortie"]])
    ee = rr.evaluate_plan(q, inst, phys, state, ref, "M47_POSITIVE_RC100", budget=physical)
    assert ee.feasible and ee.timeline is not None
    assert not cross_robust_violations(q, inst, phys, ee.timeline, 90.0)
    assert max(ee.timeline.truck_finish.values()) <= ref + alg.time_tolerance_seconds
    assert parent_j - expected_j(ee.cost, q, inst, phys, failure_prob(alg)) > 20
    ctx = SolveContext(inst, phys, alg, state, ref, "nominal", makespan_cap=ref)
    ctx.state.nominal_cross = True
    ctx.scenario_on = True
    ctx.live_budget = Budget(0, None)
    ctx.live_stats = SearchStats()
    before = sum(b.used for b in getattr(alg, "_scenario_budgets", {}).values())
    sp = scenario_score(plan, ev, ctx)
    sc = scenario_score(q, ee, ctx)
    scenario_native = sum(b.used for b in alg._scenario_budgets.values()) - before
    assert sp is not None and sc is not None and sp - sc > 20
    assert scenario_native > 0
    assert physical.used == 1
    # C100: the geometric proxy is negative and the original J is positive.
    inst, phys, alg, plan, ev, state, ref, out, diag = _emit("C100")
    assert any(desc["proxy_j_gain"] < 0 and desc["parcels"] == ["p026"] for _q, desc in out)
    parent_j = expected_j(ev.cost, plan, inst, phys, failure_prob(alg))
    gains = []
    for q, desc in out:
        ee = rr.evaluate_plan(q, inst, phys, state, ref, "M47_POSITIVE_C100", budget=physical)
        assert ee.feasible
        gains.append(parent_j - expected_j(ee.cost, q, inst, phys, failure_prob(alg)))
        assert air(plan) <= air(q)
    assert max(gains) > 0.5
    assert physical.used == 1 + len(out)
    assert scenario_native != physical.used


def test_energy_timing_and_custody_fail_on_charged_evaluations():
    inst, phys, alg, plan, ev, state, ref, out, _diag = _emit("RC100")
    q, desc = out[0]
    physical = Budget(8, None)
    tight = replace(phys, reserve_fraction=0.99)
    tight.set_active()
    energy = rr.evaluate_plan(q, inst, tight, state, ref, "M47_NEGATIVE_ENERGY", budget=physical)
    assert not energy.feasible
    assert energy.violations and ("SWAP_CANNOT_FIX" in energy.violations[0] or "e=" in energy.violations[0] or "ENERGY" in energy.violations[0])
    phys.set_active()
    timing = rr.evaluate_plan(plan, inst, phys, state, 100.0, "M47_NEGATIVE_H", budget=physical)
    assert not timing.feasible and timing.violations[0].startswith("H_EXCEEDED")
    # Cargo custody on the sealed C100 champion: a light sortie recovers at a
    # visit of the parcel's own customer. Feasible timetable, robust GROUND tag.
    c_inst, c_phys, _c_alg, c_plan, _c_ev, c_state, c_ref, _c_ctx = _sealed("C100")
    held = None
    held_sid = None
    held_parcel = None
    for sid, sortie in c_plan.sorties.items():
        if held is not None:
            break
        if sortie.launch_vid is None or sortie.started or not sortie.air:
            continue
        if c_plan.drone_sorties[sortie.drone][-1] != sid:
            continue
        launch = c_plan.visits[sortie.launch_vid].truck
        mass = sum(c_inst.parcel_mass[x] for x in sortie.air)
        for host in c_plan.visits.values():
            if host.truck == launch or not host.ground:
                continue
            parcel = host.ground[0]
            if mass + c_inst.parcel_mass[parcel] > c_phys.drone_payload_limit_kg:
                continue
            cand = c_plan.clone()
            cand.sorties[sid].air = list(sortie.air) + [parcel]
            cand.visits[host.vid].ground = [x for x in host.ground if x != parcel]
            cand.sorties[sid].rec_vid = host.vid
            if cand.validate_structure(c_inst, c_phys) or has_wait_cycle(cand):
                continue
            if not is_cross_sortie(cand, cand.sorties[sid]):
                continue
            trial = rr.evaluate_plan(cand, c_inst, c_phys, c_state, c_ref, "M47_NEGATIVE_CUSTODY", budget=physical)
            if not trial.feasible or trial.timeline is None:
                continue
            tags = cross_robust_violations(cand, c_inst, c_phys, trial.timeline, 90.0).get(sid, [])
            if any(t.startswith(f"GROUND:{parcel}@") for t in tags):
                held, held_sid, held_parcel = trial, sid, parcel
                break
    assert held is not None and held_sid is not None
    assert physical.used >= 3
    _inst, _phys, _alg, _plan, _ev, _state, _ref, ctx = _sealed("RC100")
    offered = geometries(_plan, _ev, ctx, {})
    for q, d in offered:
        receiver = q.visits[d["new_rendezvous"]].truck
        customers = {q.visits[v].customer for v in q.routes.get(receiver, [])}
        assert all(inst.parcel_to_customer[x] not in customers for x in q.sorties[d["sortie"]].air)


def test_s_still_emits_nothing():
    _inst, _phys, _alg, plan, ev, state, _ref, ctx = _sealed("RC100")
    state.nominal_cross = False
    diag = {}
    assert geometries(plan, ev, ctx, diag) == []
    assert diag["skip"] == "S_OR_NO_CROSS"
