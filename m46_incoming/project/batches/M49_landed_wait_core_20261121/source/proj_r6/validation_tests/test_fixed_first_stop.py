"""Keep the paid prefix; permit a new destination after failure observation."""
import pytest

from tdr.alns import SolveContext, destroy
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.evaluate import evaluate_plan
from tdr.plan import Plan
from tdr.recovery import build_candidates, build_residual_candidate, prepare_residual
from tdr.replay import verify_replay
from tdr.schedule import allocate_charging, schedule_plan
from tdr.simulate import (_admissible_recovery, air_arrivals, collect_segment, compute_commit_times,
                          initial_run_state, truncate)


@pytest.mark.parametrize("strategy", ["S", "R", "X"])
def test_continue_or_divert_only_after_observation(strategy):
    inst = Instance("fixed-first", "T", 0., 0., (
        Customer("c016", "p016", 3000., 0., 1.),
        Customer("c082", "p082", 5000., 0., 1.),
        Customer("c043", "p043", 1200., 500., 1.),
    ))
    phys = PhysicalConfig(truck_count=1, drone_count=1, drones_per_truck_initial=1, swap_mode=True)
    H = 5000.
    plan = Plan(inst.case_id)
    first = plan.add_visit("t1", "c016", ground=["p016"])
    rec = plan.add_visit("t1", "c082", ground=["p082"])
    flight = plan.add_sortie("d1", "t1", None, "ARC", .2, ["p043"], rec.vid)
    initial = initial_run_state(plan, inst, phys)
    nominal = evaluate_plan(plan, inst, phys, initial, H)
    assert nominal.feasible, nominal.violations
    a, = air_arrivals(plan, nominal.timeline, inst)
    cut, tt, td = compute_commit_times(nominal.timeline, a.time, a.drone)
    prefix = collect_segment(plan, nominal.timeline, inst, phys, 0., cut, initial,
                             failed_parcel=a.parcel, failed_time=a.time, failed_drone=a.drone,
                             T_truck=tt, T_drone=td)
    suffix, state, _ = truncate(plan, nominal.timeline, inst, phys, cut, a.time,
                                flight.sid, a.parcel, a.drone, prev_state=initial, T_truck=tt, T_drone=td)
    assert "t1" in state.truck_in_transit and not state.truck_fixed_first["t1"]
    assert suffix.routes["t1"][0] == first.vid
    required = {"p043"}
    recovered = build_residual_candidate(prepare_residual(suffix, inst), flight.sid, None,
                                         inst, phys, state, required, strategy)[0]

    class RemoveP016:
        def sample(self, population, count):
            assert "p016" in population and count == 1
            return ["p016"]

    ctx = SolveContext(inst=inst, phys=phys, alg=AlgorithmConfig(), state=state, H=H,
                       mode="recovery", strategy=strategy)
    freed, _ = destroy(recovered, "RANDOM_DEPENDENCY", 1, RemoveP016(), inst, None, ctx)
    assert freed == ["p016"]
    assert not state.truck_committed_first and state.truck_min_insert["t1"] == 0
    recovered.add_visit("t1", "c016", ground=["p016"])
    entry = {"truck": "t1", "ref": rec.vid, "support": False, "served": []}
    rebuilt, = build_candidates(recovered, [], flight.sid, entry, inst, phys, state, H, required, strategy)
    good = evaluate_plan(recovered, inst, phys, state, H, ground_required=required)
    assert good.feasible, good.violations
    assert _admissible_recovery(recovered, good, required, state)

    bypassed = recovered.clone()
    bypassed.remove_visit(first.vid)
    diverted = evaluate_plan(bypassed, inst, phys, state, H, ground_required=required)
    assert _admissible_recovery(bypassed, diverted, required, state), diverted.violations
    segment = collect_segment(bypassed, diverted.timeline, inst, phys, cut, max(diverted.timeline.truck_finish.values()), state)
    drive = next(act for act in segment["actions"] if act["kind"] == "DRIVE")
    assert drive["ref"] == "c082" and tuple(drive["from"]) == state.truck_start_pos["t1"]
    replay = verify_replay(inst, phys, [prefix, segment], H, strategy=strategy)
    assert replay.ok and replay.cost == pytest.approx(diverted.cost), replay.violations
    assert not verify_replay(inst, phys, [dict(prefix, failure=None), segment], H, strategy=strategy).ok
    drive["from"] = [0., 0.]
    assert not verify_replay(inst, phys, [prefix, segment], H, strategy=strategy).ok


def test_returning_truck_can_divert_to_cross_recovery():
    inst = Instance("return", "T", 0., 0., (
        Customer("c1", "p1", 1300., 0., 1.), Customer("c2", "p2", 3000., 0., 1.),
        Customer("c3", "p3", 2300., 0., 1.)))
    phys = PhysicalConfig(truck_count=2, drone_count=2, drones_per_truck_initial=1)
    plan = Plan(inst.case_id)
    plan.add_visit("t1", "c1", ground=["p1"])
    end = plan.add_visit("t2", "c2", ground=["p2"])
    flight = plan.add_sortie("d2", "t2", None, "ARC", .5, ["p3"], end.vid)
    initial = initial_run_state(plan, inst, phys)
    nominal = evaluate_plan(plan, inst, phys, initial)
    assert nominal.feasible, nominal.violations
    arrival, = air_arrivals(plan, nominal.timeline, inst)
    cut, trucks, drones = compute_commit_times(nominal.timeline, arrival.time, arrival.drone)
    returning, = [act for act in nominal.timeline.actions if act.actor == "t1" and act.ref == "DEPOT"]
    assert returning.start < cut < returning.end
    prefix = collect_segment(plan, nominal.timeline, inst, phys, 0., cut, initial, arrival.parcel,
                             arrival.time, arrival.drone, trucks, drones)
    suffix, state, _ = truncate(plan, nominal.timeline, inst, phys, cut, cut, flight.sid, arrival.parcel,
                                arrival.drone, initial, trucks, drones)
    assert not state.truck_fixed_first["t1"] and "t1" not in state.truck_committed_first
    suffix = prepare_residual(suffix, inst)
    from tdr.recovery_milp import build_stops
    from tdr.recovery import RecoveryCatalog
    fragment = suffix.sorties[flight.sid]
    assert not suffix.routes["t1"]
    assert any(stop.truck == "t1" for stop in build_stops(suffix, fragment, inst, phys, state, "X"))
    assert all(stop.truck == "t2" for stop in build_stops(suffix, fragment, inst, phys, state, "S"))
    from copy import deepcopy
    closed = deepcopy(state)
    closed.truck_returning.clear()
    closed.truck_start_pos["t1"] = (inst.depot_x, inst.depot_y)
    assert all(stop.truck != "t1" for stop in build_stops(suffix, fragment, inst, phys, closed, "X"))
    catalog = RecoveryCatalog(suffix, fragment, inst, "X", state, {"p3"}, phys)
    entry = next(entry for entry in catalog._entries() if entry["truck"] == "t1" and entry["ref"] == "c3")
    args = (suffix, flight.sid, entry, inst, phys, state, {"p3"})
    assert not build_residual_candidate(*args, "S")
    rerouted = build_residual_candidate(*args, "X")[0]
    good = evaluate_plan(rerouted, inst, phys, state)
    assert good.feasible, good.violations
    first = next(act for act in good.timeline.actions if act.actor == "t1" and act.kind == "DRIVE")
    assert first.ref == "c3" and first.info["from"] == state.truck_start_pos["t1"]
    segment = collect_segment(rerouted, good.timeline, inst, phys, cut, max(good.timeline.truck_finish.values()), state)
    replay = verify_replay(inst, phys, [prefix, segment], strategy="X")
    assert replay.ok and replay.cost == pytest.approx(good.cost), replay.violations
    assert not verify_replay(inst, phys, [prefix, segment], strategy="S").ok
