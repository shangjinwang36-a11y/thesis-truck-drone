import json
import math
from pathlib import Path

import pytest

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.plan import ground_only_plan
from tdr.schedule import initial_state

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    pkg = json.loads(p.read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    inst = load_instance(pkg, "C50")
    return inst, phys


def test_energy_constants(env):
    inst, phys = env
    assert abs(phys.e_cap - 3.9688) < 1e-12
    assert abs(phys.e_min - 0.39688) < 1e-12
    # 空载/满载参考航程
    assert abs(phys.reference_range_m(0) - 28000) < 1e-9
    assert abs(phys.reference_range_m(30) - 16000) < 1e-9
    # 30 kg 满载悬停功率
    assert abs(phys.hover_power(0) - phys.p0) < 1e-9
    assert abs(phys.hover_power(30) - phys.p30) < 1e-9
    assert abs(phys.c_km - 1.67693) < 1e-9
    assert abs(phys.cost_depot_kwh - 0.731012 / 0.9) < 1e-12
    assert abs(phys.cost_vehicle_kwh - 0.731012 / (0.85 * 0.9)) < 1e-12


def test_ground_plan_matches_forward_formula(env):
    inst, phys = env
    plan = ground_only_plan(inst)
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys))
    assert ev.feasible
    D = sum(ev.timeline.truck_distance_m.values())
    fsum = 0.0
    for truck, route in plan.routes.items():
        prev = (inst.depot_x, inst.depot_y)
        for vid in route:
            c = inst.customer(plan.visits[vid].customer)
            D2 = math.hypot(c.x - prev[0], c.y - prev[1])
            prev = (c.x, c.y)
        D2 = math.hypot(prev[0] - inst.depot_x, prev[1] - inst.depot_y)
        # 逐车里程由调度器给出
        fsum += ev.timeline.truck_finish[truck]
    cg = phys.c_km * D / 1000 + phys.wage_per_s * fsum
    assert abs(ev.cost - cg) < 1e-6


def test_all_customers_delivered(env):
    inst, phys = env
    plan = ground_only_plan(inst)
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys))
    assert ev.feasible
    delivered = set()
    for v in plan.visits.values():
        delivered.update(v.ground)
    for s in plan.sorties.values():
        delivered.update(s.air)
    assert delivered == set(inst.parcel_mass)
