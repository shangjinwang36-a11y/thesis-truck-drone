"""第 7 轮：X 从阶段1 就可以跨车。S 的阶段1 仍然同车，不合格的跨车不能从下降阶段漏进去。"""
import json
from pathlib import Path

from tdr.alns import Budget, SearchStats
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.cross_robust import cross_robust_violations
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, is_cross_sortie
from tdr.experiment import plan_from_dict
from tdr.nominal import descent_pass, phase1_allows_cross
from tdr.schedule import initial_state

ROOT = Path(__file__).resolve().parents[1]


def test_phase1_cross_stays_off_unless_x_and_the_flag():
    off = AlgorithmConfig()
    on = AlgorithmConfig(x_cross_from_start=True)
    assert phase1_allows_cross(False, on) is False
    assert phase1_allows_cross(True, off) is False
    assert phase1_allows_cross(True, on) is True


def test_r6_preset_does_not_open_phase1_and_r7_does():
    import os
    import sys
    cwd = os.getcwd()
    sys.path.insert(0, str(ROOT / "r6"))
    try:
        from run_round2 import configs
        pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
        _, alg6, _, _ = configs(pkg, "R6")
        _, alg7, _, _ = configs(pkg, "R7")
    finally:
        os.chdir(cwd)
    assert alg6.x_cross_from_start is False
    assert alg6.x_adopt_s_if_cross is False
    assert alg7.x_cross_from_start is True
    assert alg7.x_cross_robust is True
    assert alg7.x_adopt_s_if_cross is False
    assert alg7.x_cross_exchange is True
    assert phase1_allows_cross(False, alg7) is False
    assert phase1_allows_cross(True, alg7) is True


def test_descent_with_cross_open_does_not_keep_a_fragile_sortie():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    state = initial_state(inst, phys)
    state.nominal_cross = True
    alg = AlgorithmConfig(x_cross_robust=True, x_rendezvous_slack_s=90.0,
                          x_cross_energy_margin_frac=0.05)
    base = evaluate_plan(plan, inst, phys, state, None, "NOMINAL")
    stats = SearchStats()
    budget = Budget(8, None)
    out, ev, _ = descent_pass(plan, inst, phys, alg, state, stats, base, budget,
                              max_eval=8, allow_cross=True)
    assert ev is not None and ev.feasible
    if ev.timeline is not None:
        assert cross_robust_violations(out, inst, phys, ev.timeline, 90.0) == {}
    state.nominal_cross = False
    out_s, _, _ = descent_pass(plan, inst, phys, alg, state, SearchStats(), base, Budget(4, None),
                               max_eval=4, allow_cross=False)
    assert not any(is_cross_sortie(out_s, s) for s in out_s.sorties.values())
