"""变体 B（接机决策用 MILP）的测试."""
import json
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.recovery import prepare_residual, build_residual_candidate
from tdr.recovery_milp import build_stops, solve_recovery_milp
from tdr.simulate import derive_rngs, run_episode
from tdr.hidden_world import TestWorld
from test_round1 import env, _truncated, _first_replan_stats  # noqa: F401


def _alg_milp(alg):
    import copy
    a = copy.copy(alg)
    a.recovery_decision = "milp"
    return a


def test_milp_entries_respect_s_and_x_rules(env):
    inst, phys, alg, res, H, target = env
    new_plan, st2, a, info = _truncated(env)
    base = prepare_residual(new_plan, inst)
    frag = base.sorties[a.sid]
    launch = frag.launch_truck or frag.truck
    s_res = solve_recovery_milp(base, a.sid, inst, phys, st2, "S", {target}, top_k=4)
    x_res = solve_recovery_milp(base, a.sid, inst, phys, st2, "X", {target}, top_k=4)
    assert s_res.entries and x_res.entries
    assert {e["truck"] for e in s_res.entries} == {launch}          # S：只能原放飞车
    rem = [p for p in frag.air if p != target]
    for res_ in (s_res, x_res):
        # 目标值非降；条目互不相同；继续空送的票是余票的（有序）子集
        assert res_.objective == sorted(res_.objective)
        keys = [(e["truck"], e["ref"], tuple(e["served"])) for e in res_.entries]
        assert len(set(keys)) == len(keys)
        for e in res_.entries:
            idxs = [rem.index(p) for p in e["served"]]
            assert idxs == sorted(idxs)
    # X 的最优代理值不会比 S 差（X 的可选集合包含 S 的）
    assert x_res.objective[0] <= s_res.objective[0] + 1e-6
    # 每个条目都能被残段最小改动构造器接受（至少前几个能生成候选）
    built = [build_residual_candidate(base, a.sid, e, inst, phys, st2, {target}, "X")
             for e in x_res.entries]
    assert any(built)


@pytest.mark.parametrize("strategy", ["S", "X"])
def test_variant_b_episode_verified_and_not_worse_than_residual(env, strategy):
    inst, phys, alg, res, H, target = env
    a2 = _alg_milp(alg)
    world = TestWorld(inst, "C50", (target,))
    ep = run_episode(inst, res.plan, res.evaluation, H, phys, world, strategy, a2,
                     derive_rngs(a2.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=100)
    assert ep.status == "COMPLETED_VERIFIED", ep.notes
    st = _first_replan_stats(ep)
    assert st["recovery_decision"] == "milp" and st["milp_n_options"] >= 1
    assert st["milp_status"] in ("OPTIMAL", "FEASIBLE_LIMIT")
    assert st["final_cost"] <= st["residual_cost"] + 1e-6
    assert st["n_eval_requests"] == st["n_init_evals"] + st["n_main_evals"]


def test_baseline_default_is_catalog(env):
    inst, phys, alg, res, H, target = env
    assert alg.recovery_decision == "catalog" and alg.operator_selector == "roulette"
