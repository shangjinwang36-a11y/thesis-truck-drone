"""变体 A（学习式算子选择）的测试."""
import copy
import json
import random

import pytest

from tdr import selector
from tdr.hidden_world import TestWorld
from tdr.selector import QSelector, stag_bucket, temp_bucket, failure_type
from tdr.simulate import derive_rngs, run_episode
from test_round1 import env, _first_replan_stats  # noqa: F401

D = ["d1", "d2", "d3"]
R = ["r1", "r2"]


def test_buckets():
    assert [stag_bucket(x) for x in (0, 1, 9, 10, 24, 25, 99)] == [0, 1, 1, 2, 2, 3, 3]
    assert [temp_bucket(p) for p in (0.0, 0.3, 0.5, 0.7, 1.0)] == [0, 0, 1, 2, 2]
    assert {failure_type(a, b) for a in (0, 2) for b in (False, True)} == {0, 1, 2, 3}


def test_q_update_learns_better_action():
    sel = QSelector(D, R, eps=0.0, learn=True, alpha=0.5, gamma=0.0)
    rng = random.Random(1)
    best = 3
    for _ in range(400):
        key = "0|0|0"
        d, r, a = sel.choose(key, rng)
        sel.update(key, a, 1.0 if a == best else 0.0, None)
    sel.learn = False
    picks = {sel.choose("0|0|0", rng)[2] for _ in range(20)}
    assert picks == {best}


def test_frozen_does_not_update_and_unseen_state_is_random():
    sel = QSelector(D, R, eps=0.0, learn=False)
    sel.update("x", 0, 5.0, None)
    assert sel.q == {} and sel.n_updates == 0
    rng = random.Random(2)
    seen = {sel.choose("unseen", rng)[2] for _ in range(200)}
    assert len(seen) > 3


def test_json_roundtrip_and_merge():
    s1 = QSelector(D, R, learn=True)
    s1.update("k", 0, 1.0, None)
    s2 = QSelector(D, R, learn=True)
    s2.update("k", 0, 0.0, None)
    s2.update("k2", 1, 1.0, None)
    m = QSelector.merge([s1.to_json(), s2.to_json()])
    assert set(m["q"]) == {"k", "k2"} and m["n"]["k"][0] == 2
    s3 = QSelector(D, R)
    s3.load_json(json.loads(json.dumps(m)))
    assert s3.q["k"][0] == pytest.approx(0.5 * 0.2 * 1.0 * 0 + (0.2 + 0.0) / 2)
    with pytest.raises(ValueError):
        QSelector(D, ["r1"]).load_json(m)


def test_default_is_roulette(env):
    inst, phys, alg, res, H, target = env
    assert alg.operator_selector == "roulette"
    assert selector.get_selector(alg, D, R) is None


@pytest.mark.parametrize("strategy", ["S", "X"])
def test_qlearn_episode_verified(env, strategy):
    inst, phys, alg, res, H, target = env
    a2 = copy.copy(alg)
    a2.operator_selector = "qlearn"                  # 无 Q 表 → 全部未见状态 → 随机选择，也必须可行
    world = TestWorld(inst, "C50", (target,))
    ep = run_episode(inst, res.plan, res.evaluation, H, phys, world, strategy, a2,
                     derive_rngs(a2.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=100)
    assert ep.status == "COMPLETED_VERIFIED", ep.notes
    assert _first_replan_stats(ep)["operator_selector"] == "qlearn"
