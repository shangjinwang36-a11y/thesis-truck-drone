"""第 12 轮只检查参数覆盖。搜索代码不在这里。"""
import importlib.util
import os
from pathlib import Path

import pytest


def _runner():
    cwd = os.getcwd()
    path = Path(__file__).resolve().parents[1] / "r6" / "run_round2.py"
    spec = importlib.util.spec_from_file_location("run_round2_r12", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    return mod


def test_no_override_leaves_the_frozen_split():
    mod = _runner()
    assert mod.overrides_for("C50", 1000) is None
    assert mod.overrides_for("RC100", 1000, truck_delta=0) is None


def test_phase2_stays_one_fifth_and_matches_200_at_the_frozen_budget():
    mod = _runner()
    assert mod.overrides_for("C50", 1000, phase2_frac=0.2)["nominal_two_phase_b"] == 200
    assert mod.overrides_for("C50", 2000, phase2_frac=0.2)["nominal_two_phase_b"] == 400
    assert mod.overrides_for("C50", 100, phase2_frac=0.2)["nominal_two_phase_b"] == 20
    assert mod.overrides_for("C50", 250, phase2_frac=0.2)["nominal_two_phase_b"] == 50
    assert mod.overrides_for("C50", 500, phase2_frac=0.2)["nominal_two_phase_b"] == 100


def test_battery_scale_keeps_the_reserve_fraction_and_absolute_reserve_sets_it():
    mod = _runner()
    scaled = mod.overrides_for("C100", 1000, battery_scale=0.8)["phys"]
    assert scaled["battery_kwh"] == pytest.approx(0.4)
    assert scaled["reserve_fraction"] == pytest.approx(0.1)
    assert "truck_count" not in scaled
    held = mod.overrides_for("C50", 1000, reserve_kwh=0.075)["phys"]
    assert held["battery_kwh"] == pytest.approx(0.5)
    assert held["reserve_fraction"] == pytest.approx(0.15)
    both = mod.overrides_for("R50", 1000, battery_scale=1.2, reserve_kwh=0.10)["phys"]
    assert both["battery_kwh"] == pytest.approx(0.6)
    assert both["reserve_fraction"] == pytest.approx(0.10 / 0.6)


def test_fleet_and_drone_counts_follow_the_case_and_reject_an_overfull_truck():
    mod = _runner()
    plus = mod.overrides_for("C100", 1000, truck_delta=1)["phys"]
    assert plus["truck_count"] == 9
    assert plus["drone_count"] == 18
    assert plus["drones_per_truck_initial"] == 2
    minus = mod.overrides_for("C50", 1000, truck_delta=-1)["phys"]
    assert minus["truck_count"] == 4
    assert minus["drone_count"] == 8
    three = mod.overrides_for("RC50", 1000, drones_per_truck=3, slots=4)["phys"]
    assert three["truck_count"] == 5
    assert three["drone_count"] == 15
    assert three["truck_drone_slots"] == 4
    with pytest.raises(ValueError):
        mod.overrides_for("C50", 1000, drones_per_truck=3, slots=2)


def test_apply_overrides_is_a_no_op_when_empty_and_sets_slack_and_scenario_p():
    mod = _runner()
    from tdr.config import AlgorithmConfig, PhysicalConfig
    phys, alg = PhysicalConfig(), AlgorithmConfig()
    ad = {"nominal_two_phase_b": 200}
    same = mod._apply_overrides(phys, alg, ad, None)
    assert same[0] is phys and same[1] is alg and same[2] is ad
    ov = mod.overrides_for("C50", 1000, slack_s=30, scenario_p=0.4, phase2_frac=0.2)
    phys2, alg2, ad2 = mod._apply_overrides(phys, alg, ad, ov)
    assert phys2 is phys
    assert alg2.x_rendezvous_slack_s == 30
    assert alg2.scenario_p == pytest.approx(0.4)
    assert ad2["nominal_two_phase_b"] == 200
    assert ad["nominal_two_phase_b"] == 200
