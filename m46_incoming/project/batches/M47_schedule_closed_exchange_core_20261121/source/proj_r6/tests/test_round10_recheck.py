"""Synthetic regression tests; no historical/final environment seeds."""
from dataclasses import replace
import pytest
from tdr.config import PhysicalConfig
from tdr.data import Customer, Instance
from tdr.plan import Plan
from tdr.hybrid import _fingerprint
from tdr.schedule import initial_state, Timeline, _schedule_trucks
from tdr.replay import verify_replay


def test_launch_and_recovery_positions_are_part_of_cache_key():
    p = Plan("tiny")
    a = p.add_visit("t1", "c1")
    b = p.add_visit("t1", "c2")
    s = p.add_sortie("d1", "t1", a.vid, "ARC", 0.5, ["p3"], b.vid)
    before = _fingerprint(p)
    for name, value in [("launch_vid", None), ("rec_vid", a.vid)]:
        q = p.clone()
        setattr(q.sorties[s.sid], name, value)
        assert _fingerprint(q) != before
    assert _fingerprint(p.clone()) == before


@pytest.mark.parametrize("reservation", [0.0, 20.0])
def test_scheduler_obeys_reserved_channel_without_freezing_truck(reservation):
    phys = PhysicalConfig(truck_count=1, drone_count=1)
    inst = Instance("tiny", "T", 0., 0., (Customer("c1", "p1", 0., 0., 1.),))
    p = Plan("tiny")
    v = p.add_visit("t1", "c1")
    s = p.add_sortie("d1", "t1", None, "AIR", 0., [], v.vid)
    s.started = True
    st = initial_state(inst, phys)
    st.truck_channel_free["t1"] = reservation
    tl = Timeline(0.)
    _schedule_trucks(p, inst, phys, st, tl, ["t1"], {s.sid: 0.},
                     {v.vid: [s]}, {}, {})
    assert tl.visit_arr[v.vid] == 0.  # ARC launch does not freeze truck movement.
    assert tl.rec_times[s.sid][0] == reservation


@pytest.mark.parametrize("soft", [False, True])
def test_replay_enforces_original_hard_or_soft_h_semantics(soft):
    inst = Instance("tiny", "T", 0., 0., ())
    phys = PhysicalConfig(soft_h=soft)
    seg = {"start": {"holder": {}, "drone_carrier": {}, "energy": {},
                      "truck_pos": {"t1": [0., 0.]}},
           "actions": [{"kind": "DRIVE", "actor": "t1", "start": 0., "end": 10.,
                        "from": [0., 0.], "to": [0., 0.], "dist": 0., "ref": "DEPOT"}],
           "stages": []}
    rep = verify_replay(inst, phys, [seg], H=5.)
    assert any(v.startswith("REPLAY_H_EXCEEDED:") for v in rep.violations) is (not soft)


def test_truncate_carries_launch_channel_reservation():
    from tdr.evaluate import evaluate_plan
    from tdr.simulate import compute_commit_times, truncate
    phys = PhysicalConfig(truck_count=1, drone_count=2,
                          drones_per_truck_initial=2, truck_drone_slots=3)
    inst = Instance("tiny", "T", 0., 0., (
        Customer("c1", "p1", 3000., 0., 1.), Customer("c2", "p2", 4000., 0., 1.)))
    p = Plan("tiny")
    v = p.add_visit("t1", "c1")
    w = p.add_visit("t1", "c2")
    a = p.add_sortie("d1", "t1", None, "ARC", .1, ["p1"], v.vid)
    b = p.add_sortie("d2", "t1", None, "ARC", .1, ["p2"], w.vid)
    st = initial_state(inst, phys)
    ev = evaluate_plan(p, inst, phys, st)
    assert ev.feasible, ev.violations
    start, end, _ = ev.timeline.launch_times[b.sid]
    cut = (start + end) / 2
    _, tt, td = compute_commit_times(ev.timeline, cut, "d1")
    _, snapshot, _ = truncate(p, ev.timeline, inst, phys, cut, cut, a.sid, "p1", "d1",
                              prev_state=st, T_truck=tt, T_drone=td)
    assert snapshot.truck_channel_free["t1"] == end
    assert snapshot.truck_start_time["t1"] == cut
