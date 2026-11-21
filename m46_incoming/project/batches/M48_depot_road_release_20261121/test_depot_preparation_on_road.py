"""Structural regressions for consumed depot anchors. No evaluator calls."""
from pathlib import Path
import json
import sys

CORE = Path(__file__).resolve().parents[1] / "M48_depot_road_release_core_20261121"
NOMINAL = Path(__file__).resolve().parents[1] / "M47_bounded_actual_20261121"
sys.path.insert(0, str(CORE))
from research import plan_from_dict, setup  # noqa: E402
from tdr.cut_launch_windows import close  # noqa: E402
from tdr.recovery import _legalize_depot_preparation  # noqa: E402
from tdr.schedule import (committed_first_stop_violation, initial_state,
                           release_depot_preparation_on_road, schedule_plan)  # noqa: E402


def load(variant, case):
    raw = json.loads((NOMINAL / variant / "nominal" / "X" / case / "nominal_plan.json").read_text())
    return plan_from_dict(raw["plan"])


def depot_air(plan, truck):
    out = []
    for sortie in plan.sorties.values():
        if not sortie.started and sortie.launch_vid is None and sortie.truck == truck:
            out.extend(sortie.air)
    return out


def test_consumed_anchor_moves_to_the_next_visit_for_both_nominals():
    inst, phys, _alg = setup("C100", "M48")
    phys.set_active()
    for variant in ("M47_CANDIDATE", "M44_CURRENT"):
        plan = load(variant, "C100")
        state = initial_state(inst, phys)
        state.truck_in_transit.add("t2")
        air_before = set(depot_air(plan, "t2"))
        assert air_before
        assert committed_first_stop_violation(plan, state) == "DEPOT_PREPARATION_ON_ROAD:t2"
        placed = _legalize_depot_preparation(plan.clone(), inst, phys, state)
        assert committed_first_stop_violation(placed, state) is None
        still_air = {p for s in placed.sorties.values() for p in s.air}
        assert air_before <= still_air
        assert not any(not s.started and s.launch_vid is None and s.truck == "t2" for s in placed.sorties.values())


def test_return_launch_and_ordinary_depot_launch_stay():
    inst, phys, _alg = setup("C100", "M48")
    phys.set_active()
    plan = load("M47_CANDIDATE", "C100")
    ordinary = initial_state(inst, phys)
    assert committed_first_stop_violation(plan, ordinary) is None
    assert release_depot_preparation_on_road(plan.clone(), ordinary) == []
    assert close(plan, ordinary, "recovery") is None
    returning = initial_state(inst, phys)
    returning.truck_in_transit.add("t2")
    returning.truck_returning.add("t2")
    kept = plan.clone()
    assert release_depot_preparation_on_road(kept, returning) == []
    assert any(not s.started and s.launch_vid is None and s.truck == "t2" for s in kept.sorties.values())
    assert close(plan, returning, "recovery") is None


def test_arc_not_yet_launched_and_started_sortie_are_kept():
    inst, phys, _alg = setup("C100", "M48")
    phys.set_active()
    plan = __import__("tdr.plan", fromlist=["Plan"]).Plan(inst.case_id)
    rec = plan.add_visit("t1", "c1", ground=[])
    launch = plan.add_visit("t1", "c2", ground=[])
    # Customer ids on C100 are c001-style. Use visits from the published plan instead.
    published = load("M47_CANDIDATE", "C100")
    visit = next(iter(published.visits.values()))
    plan = published.clone()
    extra = plan.add_sortie("d1", visit.truck, visit.vid, "ARC", 0.0, [], visit.vid)
    state = initial_state(inst, phys)
    state.truck_in_transit.add("t9")
    placed = _legalize_depot_preparation(plan.clone(), inst, phys, state)
    after = placed.sorties[extra.sid]
    assert after.launch_vid == extra.launch_vid and after.mode == "ARC" and not after.started
    started = plan.clone()
    sample = started.sorties[extra.sid]
    sample.started = True
    sample.launch_vid = None
    state = initial_state(inst, phys)
    state.truck_in_transit.add(sample.truck)
    released = release_depot_preparation_on_road(started, state)
    assert sample.sid in started.sorties
    assert not sample.air or sample.air[0] not in released


def test_no_route_and_not_returning_goes_to_ground_without_new_air():
    inst, phys, _alg = setup("C100", "M48")
    phys.set_active()
    plan = load("M47_CANDIDATE", "C100")
    state = initial_state(inst, phys)
    state.truck_in_transit.add("t2")
    bare = plan.clone()
    bare.routes["t2"] = []
    air_ids = set(depot_air(bare, "t2"))
    n_sorties = len(bare.sorties)
    placed = _legalize_depot_preparation(bare, inst, phys, state)
    assert len(placed.sorties) <= n_sorties
    assert not (air_ids & {p for s in placed.sorties.values() for p in s.air})
    grounded = {p for v in placed.visits.values() for p in v.ground}
    assert air_ids <= grounded


def test_handover_actions_are_twenty_seconds():
    inst, phys, _alg = setup("C50", "M48")
    phys.set_active()
    assert abs(phys.handover_s - 20.0) < 1e-12
    plan = load("M47_CANDIDATE", "C50")
    state = initial_state(inst, phys)
    # Use a sortie that already has a recovery visit; force one handover parcel
    # off the air list so the scheduler emits U. This does not call evaluate.
    sortie = next(s for s in plan.sorties.values() if s.air and s.rec_vid in plan.visits)
    parcel = sortie.air.pop()
    sortie.handover.append(parcel)
    timeline = schedule_plan(plan, inst, phys, state)
    durations = [a.end - a.start for a in timeline.actions if a.kind == "U"]
    assert durations and all(abs(d - 20.0) < 1e-6 for d in durations)
    fake = durations[0]
    assert abs((fake - 10.0) - 20.0) > 1e-6


if __name__ == "__main__":
    test_consumed_anchor_moves_to_the_next_visit_for_both_nominals()
    test_return_launch_and_ordinary_depot_launch_stay()
    test_arc_not_yet_launched_and_started_sortie_are_kept()
    test_no_route_and_not_returning_goes_to_ground_without_new_air()
    test_handover_actions_are_twenty_seconds()
    print("DEPOT_ANCHOR_REGRESSION_PASS", "native_evaluations", 0)
