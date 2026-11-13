import json
from pathlib import Path

import pytest

from tdr.data import load_instance
from tdr.hidden_world import HiddenWorld

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inst():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    return load_instance(json.loads(p.read_text(encoding="utf-8")), "C50")


def test_deterministic(inst):
    a = HiddenWorld(inst, "C50", 3)
    b = HiddenWorld(inst, "C50", 3)
    assert a.configured_failure_count == b.configured_failure_count
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels


def test_count_between_one_and_two(inst):
    for seed in range(1, 21):
        w = HiddenWorld(inst, "C50", seed)
        assert w.configured_failure_count in (1, 2)


def test_idempotent_observation(inst):
    w = HiddenWorld(inst, "C50", 1)
    target = inst.customers[0]
    o1 = w.observe_air_arrival(target.parcel_id, 10.0, "att-1", target.customer_id, "d1")
    o2 = w.observe_air_arrival(target.parcel_id, 10.0, "att-1", target.customer_id, "d1")
    assert o1 == o2


def test_observation_matches_hidden_set(inst):
    w = HiddenWorld(inst, "C50", 5)
    audit = w.finish_episode()
    hidden = set(audit.hidden_failure_parcels)
    w2 = HiddenWorld(inst, "C50", 5)
    for c in inst.customers:
        o = w2.observe_air_arrival(c.parcel_id, 1.0, "a" + c.parcel_id, c.customer_id, "d1")
        assert (not o.air_delivery_available) == (c.parcel_id in hidden)
