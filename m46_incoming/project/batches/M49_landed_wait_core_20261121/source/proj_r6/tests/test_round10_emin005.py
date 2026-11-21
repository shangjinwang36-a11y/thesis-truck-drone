"""R10 new reserve rule and execution closure. Synthetic worlds only."""
from dataclasses import replace
import pytest
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import Customer, Instance
from tdr.plan import Plan
from tdr.schedule import DroneStart, DroneStage, Timeline, initial_state, _swap_pass
from tdr.evaluate import evaluate_plan
from tdr.ground_finish import ground_finish_plan, _candidate
from tdr.hidden_world import TestWorld
from tdr.simulate import initial_run_state, run_episode, derive_rngs


def tiny():
    return Instance("tiny", "T", 0., 0., (
        Customer("c1", "p1", 500., 0., 1.), Customer("c2", "p2", 1000., 0., 1.)))


def light(**kw):
    return PhysicalConfig(truck_count=1, drone_count=1, drones_per_truck_initial=1,
                          battery_kwh=.5, swap_mode=True, land_and_wait=True, **kw)


@pytest.mark.parametrize("landed", [False, True])
@pytest.mark.parametrize("energy,valid", [(.049, False), (.05, True), (-.001, False)])
def test_no_landed_or_initial_reserve_exemption(landed, energy, valid):
    inst = Instance("tiny", "T", 0., 0., (Customer("c1", "p1", 0., 0., 1.),))
    phys = light()
    p = Plan("tiny")
    v = p.add_visit("t1", "c1", ground=["p1"])
    s = p.add_sortie("d1", "t1", None, "AIR", 0., [], v.vid)
    s.started = True
    s.start_pos = (0., 0.)
    s.landed = landed
    st = initial_state(inst, phys)
    st.t0 = 1.
    st.drone_start["d1"] = DroneStart("AIRBORNE", None, 1., (0., 0.), energy)
    st.drone_energy["d1"] = energy
    ev = evaluate_plan(p, inst, phys, st)
    # Nonlanded R consumes additional reserve, so exactly .05 is invalid there.
    assert ev.feasible is (valid and landed)


def test_reserve_is_checked_before_future_swap_not_only_terminal():
    phys = light()
    st = initial_state(tiny(), phys)
    p = Plan("tiny")
    tl = Timeline(0., drone_stages={"d1": [DroneStage("CRUISE", 0., 1., dist=26000.),
                                            DroneStage("SWAP", 1., 61.)]})
    _, why = _swap_pass(tl, p, phys, st, set())
    assert why.startswith("SWAP_CANNOT_FIX")


def test_overtime_is_still_allowed_and_priced():
    inst = tiny()
    phys = light()
    p = Plan("tiny")
    p.add_visit("t1", "c1", ground=["p1"])
    p.add_visit("t1", "c2", ground=["p2"])
    st = initial_run_state(p, inst, phys)
    assert not evaluate_plan(p, inst, phys, st, 1.).feasible
    finish = ground_finish_plan(p, st, inst, phys, 1.)
    assert finish.cost is not None
    assert finish.evaluation.cost_breakdown["overtime_s"] > 0.
    assert finish.evaluation.cost_breakdown["c_overtime"] > 0.
    assert all(min(es) >= phys.e_min - phys.energy_tol
               for es in finish.evaluation.timeline.drone_energy.values())


def test_future_failures_in_kept_air_are_executed_not_assumed_success(monkeypatch):
    import tdr.ground_finish as gf
    inst = tiny()
    phys = light()
    p = Plan("tiny")
    v = p.add_visit("t1", "c2")
    p.add_sortie("d1", "t1", None, "ARC", .1, ["p1", "p2"], v.vid)
    ev = evaluate_plan(p, inst, phys, initial_run_state(p, inst, phys))
    assert ev.feasible, ev.violations
    monkeypatch.setattr("tdr.simulate.initial_recovery", lambda *a, **k: (None, ["TEST"], None))
    real = gf.ground_finish_plan
    calls = []
    def choose(plan, state, inst, phys, H, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            candidate = _candidate(plan, state, inst, phys, H, "keep_inflight", True,
                                   {"eval_requests": 0})
            assert candidate.cost is not None, candidate.status
            return candidate
        return real(plan, state, inst, phys, H, **kwargs)
    monkeypatch.setattr(gf, "ground_finish_plan", choose)
    world = TestWorld(inst, "tiny", ("p1", "p2"))
    ep = run_episode(inst, p, ev, 1000., phys, world, "S", AlgorithmConfig(),
                     derive_rngs(1, "tiny", "recovery", 0), ground_finish=True)
    assert ep.ground_finish_stats["n_future_failures"] == 1
    assert sum(not o.air_delivery_available for o in ep.observations) == 2
    assert ep.ground_finish_verified, (ep.notes, ep.ground_finish_status,
                                       ep.ground_finish_stats)
    assert ep.ground_finish_cost == pytest.approx(ep.replay.cost)
    assert ep.replay.delivered == len(inst.customers)
    assert min(ep.replay.min_energy.values()) >= phys.e_min - phys.energy_tol


def test_full_evaluation_audit_does_not_change_budget():
    from tdr.evaluation_audit import audit_evaluations
    from tdr.alns import Budget
    inst = tiny()
    phys = light()
    p = Plan("tiny")
    for c in inst.customers:
        p.add_visit("t1", c.customer_id, ground=[c.parcel_id])
    with audit_evaluations() as audit:
        b = Budget(1, None)
        evaluate_plan(p, inst, phys, budget=b, reason="ONE")
        ev = evaluate_plan(p, inst, phys, budget=b, reason="TWO")
    assert b.used == 1
    assert ev.status == "BUDGET_EXHAUSTED"
    assert audit.summary()["accepted_calls"] == 1
    assert audit.summary()["denied_calls"] == 1


def test_relocate_repairs_unreachable_old_rendezvous_without_duplicate_delivery():
    inst = Instance("tiny", "T", 0., 0., (
        Customer("c1", "p1", 100., 0., 1.), Customer("c2", "p2", 5000., 0., 1.)))
    phys = light()
    p = Plan("tiny")
    old = p.add_visit("t1", "c1", ground=["p1"])
    rec = p.add_visit("t1", "c2", ground=["p2"])
    s = p.add_sortie("d1", "t1", None, "AIR", 0., [], rec.vid)
    s.started = True
    s.start_pos = (100., 0.)
    s.start_time = 1.
    s.handover = ["p1"]
    s.launch_truck = "t1"
    st = initial_state(inst, phys)
    st.t0 = 1.
    st.drone_energy["d1"] = .06
    st.drone_start["d1"] = DroneStart("AIRBORNE", None, 1., (100., 0.), .06)
    st.parcel_holder = {"p1": "DRONE:d1", "p2": "TRUCK:t1"}
    none = ground_finish_plan(p, st, inst, phys, 2., relocate=False)
    assert none.cost is None
    repaired = ground_finish_plan(p, st, inst, phys, 2.)
    assert repaired.cost is not None, repaired.status
    assert "relocate" in repaired.status
    assert sum(v.ground.count("p1") for v in repaired.plan.visits.values()) == 1
    assert min(repaired.evaluation.timeline.drone_energy["d1"]) >= .05-phys.energy_tol
    assert p.sorties[s.sid].rec_vid == rec.vid  # input was not mutated


def test_two_simultaneously_unreachable_fragments_can_both_land_safely():
    inst = Instance("tiny", "T", 0., 0., (
        Customer("c1", "p1", 100., 0., 1.), Customer("c2", "p2", 200., 0., 1.),
        Customer("c3", "p3", 5000., 0., 1.)))
    phys = PhysicalConfig(truck_count=1, drone_count=2, drones_per_truck_initial=2,
                          truck_drone_slots=3, battery_kwh=.5, swap_mode=True, land_and_wait=True)
    p = Plan("tiny")
    rec = p.add_visit("t1", "c3", ground=["p3"])
    st = initial_state(inst, phys)
    st.t0 = 1.
    st.parcel_holder = {"p1":"DRONE:d1","p2":"DRONE:d2","p3":"TRUCK:t1"}
    for i in [1,2]:
        d=f"d{i}"
        so=p.add_sortie(d,"t1",None,"AIR",0.,[],rec.vid)
        so.started=True
        so.start_time=1.
        so.start_pos=(100.*i,0.)
        so.handover=[f"p{i}"]
        so.launch_truck="t1"
        st.drone_energy[d]=.05001
        st.drone_start[d]=DroneStart("AIRBORNE",None,1.,so.start_pos,.05001)
    result=ground_finish_plan(p,st,inst,phys,2.)
    assert result.cost is not None,result.status
    assert "relocate_joint_nearest" in result.status
    assert all(min(es)>=phys.e_min-phys.energy_tol for es in result.evaluation.timeline.drone_energy.values())
