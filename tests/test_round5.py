import json
from pathlib import Path

import pytest

from tdr.data import load_instance
from tdr.hidden_world import BernoulliWorld, HiddenWorld, bernoulli_failure_flags, make_world

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inst():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    return load_instance(json.loads(p.read_text(encoding="utf-8")), "C50")


def test_default_mode_unchanged(inst):
    a = make_world(inst, "C50", 3)
    b = HiddenWorld(inst, "C50", 3)
    assert isinstance(a, HiddenWorld) and not isinstance(a, BernoulliWorld)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels


def test_bernoulli_deterministic_and_strategy_independent(inst):
    a = make_world(inst, "C50", 5, "bernoulli", 0.2)
    b = make_world(inst, "C50", 5, "bernoulli", 0.2)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels
    c = make_world(inst, "C50", 6, "bernoulli", 0.2)
    assert make_world(inst, "C50", 5, "bernoulli", 0.2).configured_failure_count >= 0
    assert c.finish_episode().hidden_failure_parcels != make_world(inst, "C50", 5, "bernoulli", 0.2).finish_episode().hidden_failure_parcels


def test_bernoulli_nested_across_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    f1 = bernoulli_failure_flags("C50", 1, ids, 0.1)
    f2 = bernoulli_failure_flags("C50", 1, ids, 0.2)
    f3 = bernoulli_failure_flags("C50", 1, ids, 0.3)
    assert f1 <= f2 <= f3


def test_bernoulli_rate_close_to_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    for p in (0.1, 0.2, 0.3):
        tot = sum(len(bernoulli_failure_flags("C50", s, ids, p)) for s in range(1, 201))
        rate = tot / (200 * len(ids))
        assert abs(rate - p) < 0.02, (p, rate)
    assert bernoulli_failure_flags("C50", 1, ids, 0.0) == frozenset()
    assert bernoulli_failure_flags("C50", 1, ids, 1.0) == frozenset(ids)


def test_bernoulli_reveal_only_on_arrival(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    ids = [c for c in inst.customers]
    obs = [w.observe_air_arrival(c.parcel_id, 1.0, f"a-{i}", c.customer_id, "d") for i, c in enumerate(ids)]
    audit = w.finish_episode()
    failed_obs = {o.parcel_id for o in obs if not o.air_delivery_available}
    assert failed_obs == set(audit.hidden_failure_parcels) == set(audit.observed_air_failure_parcels)
    assert len(failed_obs) > 0


def test_bernoulli_unattempted_not_observed(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    c = inst.customers[0]
    w.observe_air_arrival(c.parcel_id, 1.0, "x", c.customer_id, "d")
    audit = w.finish_episode()
    assert set(audit.observed_air_failure_parcels) <= {c.parcel_id}
