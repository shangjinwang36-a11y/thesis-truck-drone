"""第四轮修复的回归测试."""
import json
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld, TestWorld
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


# ------------------------------------------------------------------ 失败事件快照截获（供候选级回归测试复用）
class _Stop(Exception):
    pass


def _spec(case):
    pkg = json.load(open(ROOT / "data" / "package.json"))
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, FIX / "spec" / case)
    return pkg, phys, alg, inst, plan, H


def capture_first_event(pkgfn, case, failed, strat="S"):
    """运行到第一次恢复调用即停，返回 (inst, phys, H, new_plan, state, ground_required, kw)."""
    pkg, phys, alg, inst, plan, H = pkgfn(case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    world = TestWorld(inst, case, tuple(failed))
    got = []
    orig = simulate.initial_recovery

    def hook(np_, st, i_, p_, strategy, gr, **kw):
        got.append((np_.clone(), st, set(gr), kw))
        raise _Stop()
    simulate.initial_recovery = hook
    try:
        simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg,
                             simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                             recovery_eval_budget=1000)
    except _Stop:
        pass
    finally:
        simulate.initial_recovery = orig
    if not got:
        return None
    np_, st, gr, kw = got[0]
    return inst, phys, H, np_, st, gr, kw


def test_m4_same_truck_custody_no_false_reject():
    """同车接机：残段里已预置在接机点之前的旧地送必须清除(修复前 spec C50 约 43/190 个同车候选被误判 G_CUSTODY)."""
    from tdr import recovery as R
    import random
    case = "C50"
    pkg, phys, alg, inst, plan, H = _spec(case)
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    n_custody = n_ok = 0
    for seed in range(8):
        f = random.Random(seed).sample(air, 2)
        cap = capture_first_event(_spec, case, f)
        if cap is None:
            continue
        inst, phys, H, np_, st, gr, kw = cap
        frag = next(s for s in np_.sorties.values() if s.sid == kw["frag_sid"])
        res = R.prepare_residual(np_, inst)
        launch = frag.launch_truck or frag.truck
        rem = [p for p in frag.air if p not in gr]
        for vid in res.routes.get(launch, []):
            for sv in ([], rem[:1], rem):
                ent = dict(truck=launch, kind="visit", ref=vid, support=False, served=list(sv))
                for cp in R.build_residual_candidate(res, frag.sid, ent, inst, phys, st, gr, "S"):
                    e = evaluate_plan(cp, inst, phys, st, H, "T")
                    n_ok += e.feasible
                    n_custody += e.status == "INVALID_CUSTODY"
    assert n_ok > 50
    assert n_custody == 0


def test_m3_sa_scale_excludes_prefix():
    from tdr.alns import prefix_fixed_cost
    from tdr.schedule import StartState
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert prefix_fixed_cost(StartState(t0=0.0), phys) == 0.0
    st = StartState(t0=1000.0, prefix_distance_m=5000.0, prefix_ac_kwh=1.0,
                    truck_start_pos={"t1": (0, 0), "t2": (0, 0)}, truck_done={"t2": 800.0})
    exp = (phys.c_km * 5.0 + phys.wage_per_s * (1000.0 + 800.0)
           + phys.cost_vehicle_kwh * phys.slot_efficiency * 1.0)
    assert prefix_fixed_cost(st, phys) == pytest.approx(exp)
    assert prefix_fixed_cost(st, phys) > 0
