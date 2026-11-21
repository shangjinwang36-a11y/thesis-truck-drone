"""round3d：资源梯度变体数据包与 200 客户试验包."""
import collections
import json
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import load_instance, validate_package

D = Path(__file__).resolve().parents[1] / "data"


def _pkg(name):
    return json.loads((D / name).read_text(encoding="utf-8"))


def test_variants_validate_and_fleet():
    for name, swap, dpt in (("package_light_1drone.json", True, 1), ("package_light_chg.json", False, 2)):
        pkg = _pkg(name)
        meta = validate_package(pkg)
        assert meta["ok"], meta["errors"]
        cfg = pkg["config"]
        assert cfg["swap_mode"] is swap and cfg["drones_per_truck_initial"] == dpt
        phys = PhysicalConfig.from_dict(cfg)
        for case, tr in (("C50", 5), ("R100", 8)):
            p = phys.for_case(pkg["case_fleet"], case)
            assert p.truck_count == tr and p.drone_count == tr * dpt
        assert abs(phys.reserve_fraction - 0.1) < 1e-12 and phys.drone_payload_limit_kg == 4.0
    chg = PhysicalConfig.from_dict(_pkg("package_light_chg.json")["config"])
    assert chg.slot_ac_kw == 2.0 and chg.truck_initial_ac_kwh == 4.0


def test_gh200_package():
    for name, dpt in (("package_gh200_light2.json", 2), ("package_gh200_light1.json", 1)):
        pkg = _pkg(name)
        meta = validate_package(pkg)
        assert meta["ok"], meta["errors"]
        phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg["case_fleet"], "C200")
        assert phys.truck_count == 15 and phys.drone_count == 15 * dpt
    pkg = _pkg("package_gh200_light2.json")
    for case in ("C200", "R200", "RC200"):
        inst = load_instance(pkg, case)
        assert len(inst.customers) == 200
        xs = [c.x for c in inst.customers] + [c.y for c in inst.customers]
        assert 0 <= min(xs) and max(xs) <= 20000 + 1e-6 and (inst.depot_x, inst.depot_y) == (10000.0, 10000.0)
        cnt = collections.Counter(round(c.mass_kg / 0.8, 6) for c in inst.customers)
        assert cnt == {0.2: 40, 0.5: 60, 1.0: 60, 2.0: 24, 3.0: 12, 5.0: 4}
        assert max(c.mass_kg for c in inst.customers) <= 4.0 + 1e-9
