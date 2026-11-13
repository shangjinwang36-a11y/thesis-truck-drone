"""第一轮修改（修复1：残段最小改动恢复；修复2：S/X 搜索量可比）的验收测试."""
import json
from pathlib import Path

import pytest

from tdr.alns import Budget, SearchStats, _progress
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.hidden_world import TestWorld
from tdr.nominal import build_nominal
from tdr.recovery import RecoveryCatalog, build_residual_candidate, initial_recovery, prepare_residual
from tdr.schedule import initial_state
from tdr.simulate import (SearchStats as _SS, air_arrivals, compute_cut, derive_rngs,
                          initial_run_state, run_episode, truncate)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    pkg = json.loads(p.read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    inst = load_instance(pkg, "C50")
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    res = build_nominal(inst, phys, alg, derive_rngs(alg.base_algorithm_seed, "C50", "nominal", 0),
                        eval_budget=200)
    if not res.evaluation or not res.evaluation.feasible:
        pytest.skip("nominal not feasible")
    H = max(res.evaluation.timeline.truck_finish.values()) + phys.shift_slack_s
    air = [q for s in res.plan.sorties.values() for q in s.air]
    if not air:
        pytest.skip("no air parcels in nominal plan")
    return inst, phys, alg, res, H, air[0]


def _episode(env, strategy, budget):
    inst, phys, alg, res, H, target = env
    world = TestWorld(inst, "C50", (target,))
    return run_episode(inst, res.plan, res.evaluation, H, phys, world, strategy, alg,
                       derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                       recovery_eval_budget=budget)


def _first_replan_stats(ep):
    return [r for r in ep.replans if r.index >= 1][0].stats


def _truncated(env):
    """复现 run_episode 第一次失败后的截断状态，返回 (new_plan, state, frag_sid, a)."""
    inst, phys, alg, res, H, target = env
    plan = res.plan.clone()
    state = initial_run_state(plan, inst, phys)
    ev = evaluate_plan(plan, inst, phys, state, H, "T")
    tl = ev.timeline
    a = next(x for x in air_arrivals(plan, tl, inst) if x.parcel == target)
    t_cut = compute_cut(tl, a.time, a.drone)
    new_plan, st2, info = truncate(plan, tl, inst, phys, t_cut, a.time, a.sid, a.parcel,
                                   a.drone, prev_state=state)
    return new_plan, st2, a, info


@pytest.mark.parametrize("strategy", ["S", "X"])
def test_residual_not_worse_than_returned(env, strategy):
    """ALNS 返回的解不得比"残段候选"差；起点来源与成本被记录."""
    ep = _episode(env, strategy, 100)
    assert ep.status == "COMPLETED_VERIFIED", ep.notes
    st = _first_replan_stats(ep)
    assert st["init_source"] in ("RESIDUAL", "CATALOG", "REBUILD")
    assert st["residual_feasible"] is True      # 本夹具中残段候选可行，保证下面的断言不是空转
    if st["residual_feasible"]:
        assert st["init_cost"] <= st["residual_cost"] + 1e-9
        assert st["final_cost"] <= st["residual_cost"] + 1e-6
        assert ep.evaluation.cost <= st["residual_cost"] + 1e-6
    assert "RESIDUAL_GUARD_TRIGGERED" not in ep.notes


def test_residual_candidate_keeps_future_intact(env):
    """残段候选只改失败航次及失败票的地送，其他访问/航次/地送指派原样保留."""
    inst, phys, alg, res, H, target = env
    new_plan, st2, a, info = _truncated(env)
    base = prepare_residual(new_plan, inst)
    cands = build_residual_candidate(base, a.sid, None, inst, phys, st2, {target}, "X")
    assert cands, "名义计划里该失败航次的回收访问应仍在残段中"
    cand = cands[0]
    # 其他无人机的未起飞航次：全部保留
    for sid, s in base.sorties.items():
        if s.drone == a.drone:
            continue
        assert sid in cand.sorties
        assert cand.sorties[sid].air == s.air
        assert cand.sorties[sid].rec_vid == s.rec_vid
    # 原有访问的地送指派只能增加（失败票/新插入），不能丢
    for vid, v in base.visits.items():
        assert set(v.ground) <= set(cand.visits[vid].ground)
    # 失败票被安排在地面送达，且仍在机上交接清单里
    assert any(target in v.ground for v in cand.visits.values())
    assert target in cand.sorties[a.sid].handover
    assert cand.sorties[a.sid].rec_vid == base.sorties[a.sid].rec_vid


def test_s_rule_blocks_cross_truck_residual(env):
    """S：只能回收到原放飞车；X 允许任意合格车."""
    inst, phys, alg, res, H, target = env
    new_plan, st2, a, info = _truncated(env)
    base = prepare_residual(new_plan, inst)
    frag = base.sorties[a.sid]
    launch = frag.launch_truck or frag.truck
    other = next((t for t, r in base.routes.items() if t != launch and r), None)
    if other is None:
        pytest.skip("残段中没有其他车辆的访问")
    entry = {"truck": other, "kind": "visit", "ref": base.routes[other][0], "support": False,
             "served": []}
    assert build_residual_candidate(base, a.sid, entry, inst, phys, st2, {target}, "S") == []
    cat = RecoveryCatalog(base, frag, inst, "S", st2, {target})
    # S 的目录里只出现原放飞车
    assert {e["truck"] for e in cat.next_entries(80)} == {launch}


def test_init_and_main_budget_are_separate_and_comparable(env):
    """初始化与主循环分开记账，但 S/R/X 每轮共同受 150 次硬上限约束."""
    inst, phys, alg, res, H, target = env
    out = {}
    for strategy in ("S", "R", "X"):
        ep = _episode(env, strategy, 150)
        assert ep.status == "COMPLETED_VERIFIED", ep.notes
        out[strategy] = _first_replan_stats(ep)
    for st in out.values():
        assert st["n_eval_requests"] <= 150
        assert st["n_main_evals"] <= 150 - st["n_init_evals"]
        assert st["n_main_evals"] >= 150 - st["n_init_evals"] - 10
        assert st["n_init_evals"] <= min(alg.recovery_init_eval_budget, 150)
        assert st["main_budget_limit"] == 150 - st["init_budget_used"]
        assert st["init_budget_used"] == st["n_init_evals"]
        assert st["recovery_hard_cap"] == 150
        assert st["wall_cap_armed"] is False
        assert st["wall_cap_hit"] is False
        assert st["replan_wall_s"] >= 0
        assert st["n_eval_requests"] == st["n_init_evals"] + st["n_main_evals"]
        assert "RECOVERY_INITIAL_BASE" in st["init_by_reason"]
    assert out["S"]["n_init_evals"] <= alg.recovery_init_eval_budget
    assert out["X"]["n_init_evals"] <= alg.recovery_init_eval_budget
    ratio = out["S"]["n_main_iterations"] / max(1, out["X"]["n_main_iterations"])
    assert 0.5 <= ratio <= 2.0, out


def test_sa_progress_depends_on_main_loop_only():
    b = Budget(100, None)
    st = SearchStats()
    st.eval_requests = 25
    assert abs(_progress(st, b) - 0.25) < 1e-12
    st.eval_requests = 100
    assert abs(_progress(st, b) - 1.0) < 1e-12
