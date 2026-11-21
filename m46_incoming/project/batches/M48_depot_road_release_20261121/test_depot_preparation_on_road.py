"""Zero-evaluation check: an in-transit truck cannot keep a depot launch.

Uses the published nominal plans only. No world flags and no evaluator.
"""
from pathlib import Path
import json
import sys

CORE = Path(__file__).resolve().parents[1] / "M48_depot_road_release_core_20261121"
NOMINAL = Path(__file__).resolve().parents[1] / "M47_bounded_actual_20261121"
sys.path.insert(0, str(CORE))
from research import plan_from_dict, setup  # noqa: E402
from tdr.moves import repair_ground_only  # noqa: E402
from tdr.schedule import (committed_first_stop_violation, initial_state,
                           release_depot_preparation_on_road)  # noqa: E402


def load(variant, case):
    raw = json.loads((NOMINAL / variant / "nominal" / "X" / case / "nominal_plan.json").read_text())
    return plan_from_dict(raw["plan"])


def exposed_trucks(plan):
    return sorted({s.truck for s in plan.sorties.values() if not s.started and s.launch_vid is None})


def test_c100_nominals_are_exposed_once_t2_has_left():
    inst, phys, _alg = setup("C100", "M48")
    phys.set_active()
    for variant in ("M47_CANDIDATE", "M44_CURRENT"):
        plan = load(variant, "C100")
        state = initial_state(inst, phys)
        assert "t2" in exposed_trucks(plan)
        state.truck_in_transit.add("t2")
        assert committed_first_stop_violation(plan, state) == "DEPOT_PREPARATION_ON_ROAD:t2"
        released = plan.clone()
        freed = release_depot_preparation_on_road(released, state)
        assert freed
        placed, left = repair_ground_only(released, inst, phys, freed, state.truck_min_insert or None, state)
        assert left == []
        assert committed_first_stop_violation(placed, state) is None
        assert all(s.started or s.launch_vid is not None or s.truck != "t2" for s in placed.sorties.values())


if __name__ == "__main__":
    test_c100_nominals_are_exposed_once_t2_has_left()
    print("DEPOT_ROAD_RELEASE_PASS", "native_evaluations", 0)
