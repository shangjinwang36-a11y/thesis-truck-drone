"""T08a：已有交接票地送安排时，跨车迁回放飞车须先清除旧安排。"""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from tdr import ground_finish as gf
from tdr.config import PhysicalConfig
from tdr.data import Customer, Instance
from tdr.plan import Plan
from tdr.schedule import DroneStart, initial_state


def test_relocate_preassigned_handover_back_to_launch_truck(monkeypatch):
    # 独立审查中的两客户案例；不生成或运行随机种子。
    root = Path(__file__).resolve().parents[1]
    pkg = json.loads((root / "data/package_light.json").read_text(encoding="utf-8"))
    phys = dataclasses.replace(PhysicalConfig.from_dict(pkg["config"]),
                               truck_count=2, drone_count=1, drones_per_truck_initial=1)
    inst = Instance("tiny", "T", 0.0, 0.0, (
        Customer("c1", "p1", 0.0, 0.0, 1.0),
        Customer("c2", "p2", 10000.0, 0.0, 1.0),
    ))
    plan = Plan("tiny")
    plan.routes = {"t1": [], "t2": []}
    old_rec = plan.add_visit("t2", "c2", ground=["p2"])
    old_delivery = plan.add_visit("t2", "c1", ground=["p1"])
    frag = plan.add_sortie("d1", "t2", None, "AIR", 0.0, [], old_rec.vid, handover=["p1"])
    frag.started = True
    frag.start_time = 1.0
    frag.start_pos = (0.0, 0.0)
    frag.launch_truck = "t1"
    state = initial_state(inst, phys)
    state.t0 = 1.0
    state.drone_start["d1"] = DroneStart("AIRBORNE", None, 1.0, (0.0, 0.0), 0.1, aboard=["p1"])
    state.drone_energy["d1"] = 0.1
    state.parcel_holder = {"p1": "DRONE:d1", "p2": "TRUCK:t2"}
    before_plan = copy.deepcopy(vars(plan))
    before_state = copy.deepcopy(state)

    cost, status = gf.ground_finish_cost(plan, state, inst, phys, None, relocate=False)
    assert cost is None and status.startswith("UNPRICED:"), status

    real_evaluate = gf._evaluate
    relocated = []

    def check_relocated(candidate, st, inst_, phys_, horizon):
        rec_vid = candidate.sorties[frag.sid].rec_vid
        if rec_vid != old_rec.vid:
            assert candidate.visits[rec_vid].truck == "t1"
            deliveries = [v for v in candidate.visits.values() if "p1" in v.ground]
            assert len(deliveries) == 1
            delivery = deliveries[0]
            assert delivery.truck == "t1"
            assert delivery.ground.count("p1") == 1
            route = candidate.routes["t1"]
            assert route.index(delivery.vid) >= route.index(rec_vid)
            assert candidate.visits[old_delivery.vid].ground == []
            assert candidate.visits[old_rec.vid].ground == ["p2"]
            relocated.append(rec_vid)
        return real_evaluate(candidate, st, inst_, phys_, horizon)

    monkeypatch.setattr(gf, "_evaluate", check_relocated)
    cost, status = gf.ground_finish_cost(plan, state, inst, phys, None)
    assert cost == pytest.approx(69.82890184248616), status
    assert status == "FEASIBLE:relocate:truck:landed:s1->c1@t1#0"
    assert relocated
    assert vars(plan) == before_plan
    assert state == before_state
