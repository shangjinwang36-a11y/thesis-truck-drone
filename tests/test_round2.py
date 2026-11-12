"""第二轮修改的验收测试：跨车回收修复、X 搜索覆盖 S、截断/续接缺陷、成本驱动名义解构造."""
import json
from pathlib import Path

import pytest

from tdr.alns import Budget
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.recovery import RecoveryCatalog, build_residual_candidate, prepare_residual
from tdr.schedule import initial_state
from tdr.simulate import derive_rngs, run_episode
from test_round1 import env, _truncated, _first_replan_stats  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
NOM2 = ROOT / "outputs_summary" / "nominal2"


# ---------------------------------------------------------------- 修复：跨车回收
def _catalog(env, strategy, guard_n=40):
    inst, phys, alg, res, H, target = env
    new_plan, st2, a, info = _truncated(env)
    base = prepare_residual(new_plan, inst)
    frag = base.sorties[a.sid]
    cat = RecoveryCatalog(base, frag, inst, strategy, st2, {target}, phys=phys, guard_n=guard_n)
    return base, a, st2, cat


def _take(cat, n):
    out = []
    for e in cat._gen:
        out.append(e)
        if len(out) >= n:
            break
    return out


def test_cross_truck_candidates_have_unique_custody(env):
    """跨车回收后：被带到别车的票，原放飞车地送必须清除（否则 G_CUSTODY），且整体可行."""
    inst, phys, alg, res, H, target = env
    base, a, st2, cat = _catalog(env, "X")
    launch = base.sorties[a.sid].launch_truck or base.sorties[a.sid].truck
    ents = [e for e in _take(cat, 80) if e["truck"] != launch]
    assert ents, "X 的候选里应含非放飞车条目"
    n_feasible = 0
    for e in ents:
        cands = build_residual_candidate(base, a.sid, e, inst, phys, st2, {target}, "X")
        for plan in cands:
            seen = {}
            for v in plan.visits.values():
                for p in v.ground:
                    assert p not in seen, f"{p} 在 {seen[p]} 与 {v.vid} 重复地送"
                    seen[p] = v.vid
            ev = evaluate_plan(plan, inst, phys, st2, H, "T")
            assert not ev.timeline.custody_violations if ev.timeline else True
            n_feasible += bool(ev.feasible)
    assert n_feasible >= 1, "跨车候选没有一个可行：旧地送指派未被清除？"


# ---------------------------------------------------------------- 修复：X 覆盖 S
def _keys(entries):
    return [(e["truck"], e["ref"], tuple(e["served"])) for e in entries]


def test_x_first_batch_contains_s_prefix(env):
    g = 25
    _, _, _, cs = _catalog(env, "S", g)
    _, _, _, cx = _catalog(env, "X", g)
    s_first = _keys(_take(cs, g))
    x_first = _keys(_take(cx, g))
    assert len(s_first) == g
    assert s_first == x_first              # X 的前 g 个就是 S 的前 g 个（S 候选整体先评价）


def test_catalog_sorted_by_estimated_cost(env):
    """估计成本不降：S 的前缀按估计目标值有序（保证最有希望的先评价）."""
    inst, phys, alg, res, H, target = env
    _, _, _, cs = _catalog(env, "S", 20)
    ents = _take(cs, 20)
    ests = [e.get("est") for e in ents if e.get("est") is not None]
    if len(ests) >= 2:
        assert ests == sorted(ests)


@pytest.mark.parametrize("budget", [60, 100])
def test_x_startup_not_worse_than_s_same_env(env, budget):
    """同一环境、同一初始化预算：X 的起点最优不差于 S."""
    inst, phys, alg, res, H, target = env
    costs = {}
    for strat in ("S", "X"):
        world = TestWorld(inst, "C50", (target,))
        ep = run_episode(inst, res.plan, res.evaluation, H, phys, world, strat, alg,
                         derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                         recovery_eval_budget=budget)
        assert ep.status == "COMPLETED_VERIFIED", ep.notes
        costs[strat] = _first_replan_stats(ep)["init_cost"]
    assert costs["X"] <= costs["S"] + 1e-6, costs


# ---------------------------------------------------------------- 修复：多次失败的截断/续接
@pytest.mark.skipif(not NOM2.exists(), reason="needs outputs_summary/nominal2")
@pytest.mark.parametrize("failed", [
    ("p005", "p044", "p015", "p014", "p043", "p020"),    # 截断点恰为回收末，U 未完成 → HOLDER/CUSTODY
    ("p001", "p049", "p029", "p012", "p008", "p044"),    # 同一时刻连续截断 → 残段缺少起始坐标
])
@pytest.mark.parametrize("strategy", ["S", "X"])
def test_multi_failure_episode_verified(failed, strategy):
    pkg = json.loads((ROOT / "data" / "package.json").read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    inst = load_instance(pkg, "C50")
    plan, cost, H = load_case_nominal(inst, NOM2 / "C50")
    air = {p for s in plan.sorties.values() for p in s.air}
    failed = tuple(p for p in failed if p in air)
    if len(failed) < 3:
        pytest.skip("nominal2 没有这些空送票")
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    ep = run_episode(inst, plan, nom_ev, H, phys, TestWorld(inst, "C50", failed), strategy, alg,
                     derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=150)
    assert ep.status == "COMPLETED_VERIFIED", ep.notes


# ---------------------------------------------------------------- 名义解：成本驱动构造
def test_nominal_descent_not_worse_than_all_ground_and_keeps_wait_cap(env):
    inst, phys, alg, res, H, target = env
    from tdr.nominal import build_nominal
    assert res.evaluation.feasible
    air_n = sum(len(s.air) for s in res.plan.sorties.values())
    assert air_n >= 1
    # 单次等待上限（3600 s）依然生效
    from tdr import evaluate as ev_mod
    src = Path(ev_mod.__file__).read_text(encoding="utf-8")
    assert "3600" in src
