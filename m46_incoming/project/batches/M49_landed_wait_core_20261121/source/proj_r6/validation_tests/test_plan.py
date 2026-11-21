import json
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
    return load_instance(pkg, "C50"), PhysicalConfig.from_dict(pkg["config"])


def test_air_conversion_feasible(env):
    from tdr.nominal import try_convert
    inst, phys = env
    plan = ground_only_plan(inst)
    state = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, state)
    assert base.feasible
    cand = None
    for truck in plan.routes:
        for s in range(len(plan.routes[truck]) - 1):
            cand = try_convert(plan, inst, phys, truck, s, 2, 0.5)
            if cand is not None:
                break
        if cand is not None:
            break
    assert cand is not None, "至少存在一个可构造的空送转换"
    ev = evaluate_plan(cand, inst, phys, state)
    assert ev.feasible, ev.violations
    assert any(s.air for s in cand.sorties.values())


def test_launch_position_inside_arc(env):
    from tdr.nominal import try_convert
    inst, phys = env
    plan = ground_only_plan(inst)
    cand = None
    s0 = None
    for truck in plan.routes:
        for s in range(1, len(plan.routes[truck]) - 1):
            c = try_convert(plan, inst, phys, truck, s, 1, 0.5)
            if c is None:
                continue
            so = next(iter(c.sorties.values()))
            if so.launch_vid is not None:
                cand, s0 = c, so
                break
        if cand is not None:
            break
    if cand is None:
        pytest.skip("no arc-launch conversion in this instance")
    ev = evaluate_plan(cand, inst, phys, initial_state(inst, phys))
    assert ev.feasible
    s = s0
    lt = ev.timeline.launch_times[s.sid]
    # L 结束位置应与弧上 lambda 插值一致
    v = cand.visits[s.launch_vid]
    route = cand.routes[v.truck]
    i = route.index(v.vid)
    p = (inst.customer(v.customer).x, inst.customer(v.customer).y)
    q = (inst.customer(cand.visits[route[i + 1]].customer).x,
         inst.customer(cand.visits[route[i + 1]].customer).y)
    exp = (p[0] + (q[0] - p[0]) * s.lam, p[1] + (q[1] - p[1]) * s.lam)
    assert abs(lt[2][0] - exp[0]) < 1e-6 and abs(lt[2][1] - exp[1]) < 1e-6


def test_payload_limit(env):
    from tdr.nominal import try_convert
    inst, phys = env
    plan = ground_only_plan(inst)
    for truck in plan.routes:
        for s in range(len(plan.routes[truck])):
            for L in (1, 2, 3):
                cand = try_convert(plan, inst, phys, truck, s, L, 0.5)
                if cand is None:
                    continue
                for so in cand.sorties.values():
                    m = sum(inst.parcel_mass[p] for p in so.air)
                    assert m <= phys.drone_payload_limit_kg + 1e-9
