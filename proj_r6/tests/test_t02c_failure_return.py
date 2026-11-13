"""T02-C：每次尚未到场的空送都要能在“送不成、带货直飞回接机点”后，回收完仍不低于 E_min。
规则写在 evaluate_plan 里（failure_return_violations），名义、恢复、收尾、S/R/X 共用。"""
import json
from pathlib import Path

import pytest

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, failure_return_violations
from tdr.experiment import plan_from_dict
from tdr.schedule import initial_state

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
def test_published_nominal_plans_already_satisfy_the_rule(strat, case):
    plan, inst, phys = _load(strat, case)
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    assert ev.feasible, ev.violations
    assert failure_return_violations(plan, inst, phys, ev.timeline) == []


def test_low_energy_before_a_delivery_is_rejected():
    plan, inst, phys = _load("S", "C50")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    tl = ev.timeline
    d, i = next((d, i) for d, st in tl.drone_stages.items() for i, s in enumerate(st) if s.kind == "SERVICE")
    tl.drone_energy[d] = list(tl.drone_energy[d])
    tl.drone_energy[d][i] = phys.e_min          # 到场时只剩 E_min：失败后带货回不去
    errs = failure_return_violations(plan, inst, phys, tl)
    assert errs and errs[0].startswith(f"FAIL_RETURN:{d}@")
