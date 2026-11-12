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


def test_l1_validate_structure_chain_order():
    """同机同车相邻航次：后一航次放飞访问早于前一航次回收访问 → 结构校验报错."""
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert not [e for e in plan.validate_structure(inst, phys) if "链次序" in e]
    found = False
    for d, sids in plan.drone_sorties.items():
        for a, b in zip(sids, sids[1:]):
            s1, s2 = plan.sorties[a], plan.sorties[b]
            if s1.launch_vid is None or s2.launch_vid is None:
                continue
            r1, l2 = s1.rec_vid, s2.launch_vid
            if r1 == l2 or plan.visits[r1].truck != plan.visits[l2].truck:
                continue
            rt = plan.routes[plan.visits[r1].truck]
            i, j = rt.index(r1), rt.index(l2)
            rt[i], rt[j] = rt[j], rt[i]
            errs = plan.validate_structure(inst, phys)
            assert any("链次序" in e for e in errs), errs
            found = True
            break
        if found:
            break
    assert found


def test_wait_cap_follows_spec_null():
    """规范 fixed_wait_cap_s=null：默认不设能量修复等待上限；旧 3600 s 上限仅为显式敏感性选项."""
    pkg, phys, alg, inst, plan, H = _spec("C50")
    assert phys.energy_wait_cap_s is None
    import dataclasses
    assert dataclasses.replace(phys, energy_wait_cap_s=3600.0).energy_wait_cap_s == 3600.0


def test_stopped_max_replans_label():
    import inspect
    src = inspect.getsource(simulate.run_episode)
    assert "STOPPED_MAX_REPLANS" in src


def test_h4_cross_truck_candidates_include_release_credit():
    """规范 C50 / HiddenWorld seed 3：穷举(oracle)最优 X=196.3；修复前代码初始 X=208.7，修复后应≈197.9(<200)，S=226.0 不变."""
    from tdr import recovery as R
    from tdr.alns import Budget, SearchStats
    pkg = json.load(open(ROOT / "data" / "package.json"))
    case = "C50"
    phys = PhysicalConfig.from_dict(dict(pkg["config"]))
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    inst = load_instance(pkg, case)
    plan, nc, H = load_case_nominal(inst, FIX / "spec_m03" / case)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    out = {}
    for strat in "SX":
        got = []
        orig = simulate.initial_recovery

        def hook(np_, st, i_, p_, s, gr, **kw):
            got.append((np_.clone(), st, set(gr), kw))
            raise _Stop()
        simulate.initial_recovery = hook
        try:
            simulate.run_episode(inst, plan, nom, H, phys, HiddenWorld(inst, case, 3), strat, alg,
                                 simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0),
                                 recovery_eval_budget=1000)
        except _Stop:
            pass
        finally:
            simulate.initial_recovery = orig
        np_, st, gr, kw = got[0]
        opt, _, _ = R.initial_recovery(np_, st, inst, phys, strat, gr, H=H, frag_sid=kw["frag_sid"],
                                       stats=SearchStats(), budget=Budget(alg.recovery_init_eval_budget, None),
                                       rescue_evals=1000, info={}, use_milp=True, extra_pool=kw.get("extra_pool"))
        out[strat] = opt.ev.cost
    assert out["S"] == pytest.approx(226.01, abs=0.05)
    assert out["X"] < 200.0, out


def test_h4_continue_subsets_prefixes():
    from tdr.recovery import _continue_subsets
    rem = ["a", "b", "c", "d", "e", "f"]
    subs = _continue_subsets(rem)
    assert [] in subs and ["a"] in subs and rem in subs
    for k in range(2, 6):
        assert rem[:k] in subs
    assert len({tuple(s) for s in subs}) == len(subs)
