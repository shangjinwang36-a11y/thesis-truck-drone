import json
from pathlib import Path

import pytest

from tdr.data import (EXPECTED_PACKAGE_SHA256, EXPECTED_SOURCE_SHA256, canonical_json_sha256,
                      load_instance, validate_package)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pkg():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run `python -m tdr extract` first")
    return json.loads(p.read_text(encoding="utf-8"))


def test_package_hash(pkg):
    assert canonical_json_sha256(pkg) == EXPECTED_PACKAGE_SHA256


def test_source_hash():
    p = ROOT / "data" / "reference" / "dynamic_events_v3.py"
    if not p.exists():
        pytest.skip("reference source not extracted")
    import hashlib
    assert hashlib.sha256(p.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA256


def test_validate(pkg):
    meta = validate_package(pkg)
    assert meta["ok"], meta["errors"]
    assert meta["n_customers"] == 450
    assert abs(meta["total_mass_kg"] - 454.5) < 1e-9


def test_cases(pkg):
    for case_id, n in [("C50", 50), ("R50", 50), ("RC50", 50), ("C100", 100),
                       ("R100", 100), ("RC100", 100)]:
        inst = load_instance(pkg, case_id)
        assert inst.n == n
        assert len({c.customer_id for c in inst.customers}) == n
        assert len({c.parcel_id for c in inst.customers}) == n
        assert all(c.mass_kg > 0 for c in inst.customers)
