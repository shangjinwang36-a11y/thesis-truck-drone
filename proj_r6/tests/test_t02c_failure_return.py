"""T02-C：每次尚未到场的空送都要能在“送不成、带货直飞回接机点”后，回收完仍不低于 E_min。
调度换电与 evaluate/verify 共用失败返航规则，含带货等车悬停。"""
import json
from pathlib import Path

import pytest

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, failure_return_violations
from tdr.experiment import plan_from_dict
from tdr.schedule import allocate_swaps, initial_state
from tdr.verify import verify_plan

ROOT = Path(__file__).resolve().parents[1]
NOM = ROOT / "r6/results/round11_tune/R11/nominal"


def _load(strat, case):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, case)
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), case)
    plan = plan_from_dict(json.loads((NOM / strat / case / "nominal_plan.json").read_text())["plan"])
    return plan, inst, phys


@pytest.mark.parametrize("strat", ["S", "X"])
@pytest.mark.parametrize("case", ["C50", "R50", "RC50", "C100", "R100", "RC100"])
def test_published_nominal_plans_are_rechecked_with_loaded_wait(strat, case):
    plan, inst, phys = _load(strat, case)
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    # T08a：旧 R/RC 计划曾漏算带货等待，并非都能靠起飞前换满电补救。
    expected_feasible = case in {"C50", "C100"}
    assert ev.feasible == expected_feasible, ev.violations
    report = verify_plan(inst, initial_state(inst, phys), plan, strat, phys)
    assert report.ok == expected_feasible
    if expected_feasible:
        assert failure_return_violations(plan, inst, phys, ev.timeline) == []
    else:
        assert ev.violations == report.violations
        assert ev.violations[0].startswith("SWAP_CANNOT_FIX:")
        assert ":stage=SERVICE:" in ev.violations[0]
        # 仅重放名义电量以核实真正的失败返航缺口，不将重放结果当可行计划。
        ev.timeline.swap_msg = ""
        allocate_swaps(ev.timeline, phys, initial_state(inst, phys))
        assert failure_return_violations(plan, inst, phys, ev.timeline)


def test_low_energy_before_a_delivery_is_rejected():
    plan, inst, phys = _load("S", "C50")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    tl = ev.timeline
    d, i = next((d, i) for d, st in tl.drone_stages.items() for i, s in enumerate(st) if s.kind == "SERVICE")
    tl.drone_energy[d] = list(tl.drone_energy[d])
    tl.drone_energy[d][i] = phys.e_min          # 到场时只剩 E_min：失败后带货回不去
    errs = failure_return_violations(plan, inst, phys, tl)
    assert errs and errs[0].startswith(f"FAIL_RETURN:{d}@")
