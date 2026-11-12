"""第四轮修复的回归测试."""
import json
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.schedule import initial_state
from tdr import simulate

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


def _gh(case, budget=1000):
    pkg = json.load(open(ROOT / "data" / "package_gh200_light1.json"))
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = budget
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, FIX / "gh200L1" / case)
    return pkg, phys, alg, inst, plan, H


def _gh_episode(case, seed, strat, budget=1000):
    pkg, phys, alg, inst, plan, H = _gh(case, budget)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    world = HiddenWorld(inst, case, seed)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    return simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs, recovery_eval_budget=budget)


@pytest.mark.parametrize("seed", [2, 8])
def test_h2_ghost_sortie_no_fragment(seed):
    """失败机旧计划里之后的航次(幽灵)不能覆盖失败航次(修复前 INITIAL_RECOVERY_FAILED:NO_FRAGMENT)."""
    ep = _gh_episode("C200", seed, "S")
    assert not any("NO_FRAGMENT" in n for n in ep.notes), ep.notes
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes)
