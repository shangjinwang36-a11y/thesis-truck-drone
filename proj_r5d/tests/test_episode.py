import json
from pathlib import Path

import pytest

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.hidden_world import TestWorld
from tdr.nominal import build_nominal
from tdr.schedule import initial_state
from tdr.simulate import derive_rngs, run_episode

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    pkg = json.loads(p.read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    inst = load_instance(pkg, "C50")
    from tdr.config import AlgorithmConfig
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    res = build_nominal(inst, phys, alg, derive_rngs(alg.base_algorithm_seed, "C50", "nominal", 0),
                        eval_budget=200)
    if not res.evaluation or not res.evaluation.feasible:
        pytest.skip("nominal not feasible")
    H = max(res.evaluation.timeline.truck_finish.values()) + phys.shift_slack_s
    return inst, phys, alg, res, H


def test_failure_recovery_end_to_end(env):
    inst, phys, alg, res, H = env
    air = [p for s in res.plan.sorties.values() for p in s.air]
    if not air:
        pytest.skip("no air parcels in nominal plan")
    target = air[0]
    for strategy in ("S", "X"):
        world = TestWorld(inst, "C50", (target,))
        ep = run_episode(inst, res.plan, res.evaluation, H, phys, world, strategy, alg,
                         derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                         recovery_eval_budget=120)
        assert ep.status == "COMPLETED_VERIFIED", (strategy, ep.status, ep.notes)
        assert ep.evaluation is not None and ep.evaluation.feasible
        assert sum(1 for o in ep.observations if not o.air_delivery_available) >= 1


def test_s_policy_keeps_launch_truck(env):
    inst, phys, alg, res, H = env
    air = [p for s in res.plan.sorties.values() for p in s.air]
    if not air:
        pytest.skip("no air parcels")
    target = air[0]
    world = TestWorld(inst, "C50", (target,))
    ep = run_episode(inst, res.plan, res.evaluation, H, phys, world, "S", alg,
                     derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=120)
    assert ep.status == "COMPLETED_VERIFIED"
    # S：所有 started 残段的回收车 = 原放飞车
    for s in ep.plan.sorties.values():
        if s.started and s.rec_vid in ep.plan.visits:
            lt = s.launch_truck or s.truck
            assert ep.plan.visits[s.rec_vid].truck == lt
