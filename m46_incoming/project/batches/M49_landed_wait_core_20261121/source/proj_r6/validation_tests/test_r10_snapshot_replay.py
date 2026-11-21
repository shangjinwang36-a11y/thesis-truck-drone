"""Local execution boundaries, with no historical plans or search fixtures."""
import pytest

from tdr.config import PhysicalConfig
from tdr.data import Customer, Instance
from tdr.evaluate import evaluate_plan
from tdr.plan import Plan
from tdr.recovery import prepare_residual
from tdr.replay import verify_replay
from tdr.schedule import DroneStart, initial_state
from tdr.simulate import (air_arrivals, collect_segment, compute_commit_times,
                          initial_run_state, truck_state_at, truncate)


def instance(*locations):
    return Instance("tiny", "T", 0.0, 0.0, tuple(
        Customer(f"c{i}", f"p{i}", x, 0.0, 1.0)
        for i, x in enumerate(locations, 1)))


def timeline(plan, inst, phys, state):
    ev = evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    return ev.timeline


def test_snapshot_targets_second_visit_to_same_customer():
    inst = instance(900.0, 1800.0, 1300.0)
    phys = PhysicalConfig(truck_count=1, drone_count=1)
    plan = Plan(inst.case_id)
    plan.add_visit("t1", "c1", ground=["p1"])
    first = plan.add_visit("t1", "c2", ground=["p2"])
    rec = plan.add_visit("t1", "c1")
    plan.add_sortie("d1", "t1", first.vid, "STOP", 0.0, ["p3"], rec.vid)
    state = initial_run_state(plan, inst, phys)
    tl = timeline(plan, inst, phys, state)
    enter = next(a for a in tl.actions if a.kind == "DRIVE" and a.end == tl.visit_arr[rec.vid])
    t = (enter.start + enter.end) / 2
    pos, remaining, idx, done = truck_state_at("t1", t, plan, tl, inst, state)
    assert pos == pytest.approx((1350.0, 0.0)) and remaining > 0 and not done
    assert plan.routes["t1"][idx:] == [rec.vid]


def test_snapshot_during_depot_preparation_keeps_the_route():
    inst = instance(500.0, 900.0)
    phys = PhysicalConfig(truck_count=1, drone_count=1)
    plan = Plan(inst.case_id)
    stop = plan.add_visit("t1", "c2", ground=["p2"])
    plan.add_sortie("d1", "t1", None, "ARC", 0.01, ["p1"], stop.vid)
    state = initial_run_state(plan, inst, phys)
    tl = timeline(plan, inst, phys, state)
    prep = next(a for a in tl.actions if a.kind == "P")
    cut, tt, _ = compute_commit_times(tl, prep.start + 1.0, "another-drone")
    t = tt.get("t1", cut)
    assert prep.end == t < next(a.start for a in tl.actions if a.kind == "DRIVE")
    assert truck_state_at("t1", t, plan, tl, inst, state) == ((0.0, 0.0), 0.0, 0, False)


def test_second_failure_at_same_instant_does_not_restart_other_service():
    inst = instance(300.0, 600.0, 900.0)
    phys = PhysicalConfig(truck_count=3, drone_count=3, drone_speed_m_s=15.0,
                          air_service_s=60, battery_kwh=.5, swap_mode=True)
    plan = Plan(inst.case_id)
    state = initial_state(inst, phys)
    for i, x0 in enumerate((300.0, 300.0, 600.0), 1):
        parcel, drone, truck = f"p{i}", f"d{i}", f"t{i}"
        visit = plan.add_visit(truck, f"c{i}")
        s = plan.add_sortie(drone, truck, None, "AIR", 0.0, [parcel], visit.vid)
        s.started = True
        s.start_pos = (x0, 0.0)
        state.drone_carrier[drone] = truck
        state.drone_start[drone] = DroneStart("AIRBORNE", None, 0.0, s.start_pos, phys.e_cap)
        state.parcel_holder[parcel] = f"DRONE:{drone}"
    tl = timeline(plan, inst, phys, state)
    first, second = air_arrivals(plan, tl, inst)[1:]
    assert first.time == second.time == 20.0

    def cut(p, tline, st, a):
        t, tt, td = compute_commit_times(tline, a.time, a.drone)
        after, snapshot, _ = truncate(p, tline, inst, phys, t, a.time, a.sid, a.parcel, a.drone,
                                       prev_state=st, T_truck=tt, T_drone=td)
        return prepare_residual(after, inst), snapshot

    p1, s1 = cut(plan, tl, state, first)
    assert s1.drone_start["d1"].service_done_s == pytest.approx(20.0)
    assert s1.parcel_holder["p2"] == "DRONE:d2"
    tl1 = timeline(p1, inst, phys, s1)
    assert air_arrivals(p1, tl1, inst) == [second]
    p2, s2 = cut(p1, tl1, s1, second)
    assert s1.truck_in_transit and s2.truck_in_transit == s1.truck_in_transit
    assert not s2.truck_committed_first and not s1.truck_committed_first
    assert s2.truck_start_pos == s1.truck_start_pos
    assert s2.drone_start["d1"].service_done_s == pytest.approx(20.0)
    assert s2.parcel_holder["p3"] == "DRONE:d3"
    tl2 = timeline(p2, inst, phys, s2)
    assert not air_arrivals(p2, tl2, inst)
    serving = next(st for st in tl2.drone_stages["d1"] if st.kind == "SERVICE")
    assert serving.end == pytest.approx(60.0)
    segments = [
        collect_segment(p, line, inst, phys, st.t0, a.time, st,
                        failed_parcel=a.parcel, failed_time=a.time, failed_drone=a.drone)
        for p, line, st, a in ((plan, tl, state, first), (p1, tl1, s1, second))
    ]
    segments.append(collect_segment(p2, tl2, inst, phys, s2.t0, max(tl2.truck_finish.values()), s2))
    replay = verify_replay(inst, phys, segments, strategy="S")
    assert replay.ok and replay.delivered == 3, replay.violations
    assert replay.cost == pytest.approx(evaluate_plan(p2, inst, phys, s2).cost)


@pytest.mark.parametrize("seconds_into_unload", [0.0, 9.0])
def test_snapshot_commits_cross_recovery_unload(seconds_into_unload):
    inst = instance(300.0, 600.0)
    phys = PhysicalConfig(truck_count=2, drone_count=2, drone_speed_m_s=15.0,
                          recovery_s=30, handover_s=20)
    plan = Plan(inst.case_id)
    plan.routes["t1"] = []
    rec = plan.add_visit("t2", "c1", ground=["p1"])
    stop = plan.add_visit("t2", "c2")
    t_fail = 300.0 / phys.truck_speed_m_s + phys.recovery_s + seconds_into_unload
    state = initial_state(inst, phys)
    for i, vid, x0, air, hand in ((1, rec.vid, 300.0, [], ["p1"]),
                                 (2, stop.vid, 600.0 - t_fail*phys.drone_speed_m_s, ["p2"], [])):
        drone, truck = f"d{i}", f"t{i}"
        s = plan.add_sortie(drone, truck, None, "AIR", 0.0, air, vid, hand)
        s.started, s.start_pos, s.launch_truck = True, (x0, 0.0), truck
        state.drone_carrier[drone] = truck
        state.drone_start[drone] = DroneStart("AIRBORNE", None, 0.0, s.start_pos, phys.e_cap)
        state.parcel_holder[f"p{i}"] = f"DRONE:{drone}"
    tl = timeline(plan, inst, phys, state)
    arrival, = air_arrivals(plan, tl, inst)
    assert arrival.time == pytest.approx(t_fail)
    unload = next(a for a in tl.actions if a.kind == "U")
    assert unload.start <= arrival.time < unload.end
    cut, tt, td = compute_commit_times(tl, arrival.time, arrival.drone)
    p, snapshot, _ = truncate(plan, tl, inst, phys, cut, arrival.time, arrival.sid,
                              arrival.parcel, arrival.drone, prev_state=state, T_truck=tt, T_drone=td)
    assert tt["t2"] == td["d1"] == pytest.approx(unload.end)
    assert snapshot.parcel_holder["p1"] == "TRUCK:t2"
    assert snapshot.drone_start["d1"].truck == "t2"
    p = prepare_residual(p, inst)
    final = timeline(p, inst, phys, snapshot)
    prefix = collect_segment(plan, tl, inst, phys, 0, cut, state, arrival.parcel, arrival.time,
                             arrival.drone, tt, td)
    suffix = collect_segment(p, final, inst, phys, cut, max(final.truck_finish.values()), snapshot)
    rep = verify_replay(inst, phys, [prefix, suffix], strategy="X")
    assert rep.ok and rep.delivered == 2 and rep.terminal["d1"]["carrier"] == "t2", rep.violations


@pytest.mark.parametrize("missing", ["action", "stage"])
def test_replay_requires_both_halves_of_battery_swap(missing):
    inst = instance(900.0, 1800.0)
    phys = PhysicalConfig(truck_count=1, drone_count=1, swap_mode=True, battery_kwh=.5,
                          spare_batteries=1, drone_payload_limit_kg=4.0)
    plan = Plan(inst.case_id)
    rec = plan.add_visit("t1", "c2", ground=["p2"])
    plan.add_sortie("d1", "t1", None, "ARC", 0.1, ["p1"], rec.vid)
    state = initial_run_state(plan, inst, phys)
    state.drone_start["d1"].energy = state.drone_energy["d1"] = 0.07
    tl = timeline(plan, inst, phys, state)
    segment = collect_segment(plan, tl, inst, phys, 0.0, tl.truck_finish["t1"], state)
    valid = verify_replay(inst, phys, [segment])
    assert valid.ok and valid.n_swaps == 1, valid.violations
    field, kind = ("actions", "W") if missing == "action" else ("stages", "SWAP")
    segment[field] = [r for r in segment[field] if r["kind"] != kind]
    invalid = verify_replay(inst, phys, [segment])
    assert not invalid.ok
    assert any(v.startswith("SWAP_UNMATCHED_") for v in invalid.violations)
