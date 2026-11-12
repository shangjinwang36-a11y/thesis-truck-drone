"""第六轮：名义跨车航次（A 放飞→B 回收，仅 X）的测试."""
import dataclasses
import json
import random
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, has_wait_cycle, is_cross_sortie
from tdr.experiment import build_case_nominal, load_case_nominal
from tdr.moves import air_candidates, find_chain_slot
from tdr.plan import Plan
from tdr.schedule import initial_state, schedule_plan

ROOT = Path(__file__).resolve().parents[1]


def _setup(case="C50"):
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    return load_instance(pkg, case), phys, alg


@pytest.fixture(scope="module")
def nominals(tmp_path_factory):
    inst, phys, alg = _setup()
    out = tmp_path_factory.mktemp("nom6")
    res = {}
    for strat in ("S", "X"):
        m = build_case_nominal(inst, phys, alg, out / strat, eval_budget=400, cross_launch=(strat == "X"))
        plan, cost, H = load_case_nominal(inst, out / strat)
        res[strat] = (m, plan, cost, H)
    return inst, phys, alg, res


def test_s_never_has_cross_sorties(nominals):
    inst, phys, alg, res = nominals
    m, plan, _, _ = res["S"]
    assert m["status"] == "FEASIBLE" and m["verified"] and m["n_cross_sorties"] == 0
    assert not any(is_cross_sortie(plan, s) for s in plan.sorties.values())


def test_x_nominal_verified_and_cross_present(nominals):
    inst, phys, alg, res = nominals
    m, plan, _, _ = res["X"]
    assert m["status"] == "FEASIBLE"
    assert m["verified"], "独立回放核验(机位/承运车/保管/电量)必须通过"
    assert m["verified_plan"]
    assert m["n_cross_sorties"] >= 1, "X 在该预算下应至少用上一个跨车航次(否则此测试不能覆盖回放对跨车的核验)"


def test_s_nominal_unaffected_by_flag_off():
    """cross_launch=False 的路径与第四轮同代码一致：候选集中没有 cross 标记."""
    inst, phys, alg = _setup()
    from tdr.plan import ground_only_plan
    plan = ground_only_plan(inst, 5, 5)
    st = initial_state(inst, phys)
    p = inst.customers[3].parcel_id
    from tdr.moves import remove_parcel
    remove_parcel(plan, p)
    s_c = air_candidates(plan, inst, phys, p, max_new=3, state=st)
    assert all(not c.cross for c in s_c)
    st.nominal_cross = True
    x_c = air_candidates(plan, inst, phys, p, max_new=3, state=st)
    key = lambda c: (c.kind, c.truck, c.launch_vid, c.rec_vid, c.mode, c.sid)
    assert {key(c) for c in s_c} <= {key(c) for c in x_c}, "X 候选必须是 S 候选的超集"
    assert any(c.cross for c in x_c), "X 应当产生跨车候选"


def test_find_chain_slot_and_cycle_detection():
    inst, phys, alg = _setup()
    from tdr.plan import ground_only_plan
    plan = ground_only_plan(inst, 5, 5)
    # 手工构造 A=t1, B=t2：d1(t1 出厂) 在 t1 访问 1 放飞，t2 访问 2 回收
    t1, t2 = plan.routes["t1"], plan.routes["t2"]
    pos = find_chain_slot(plan, "d1", "t1", 1, "t2", 2)
    assert pos == 0
    # d3 是 t2 的机体：t2 放飞→t1 回收
    pos2 = find_chain_slot(plan, "d3", "t2", 1, "t1", 2)
    assert pos2 == 0
    # 不属于放飞车的机体：d3 不能从 t1 放飞
    assert find_chain_slot(plan, "d3", "t1", 1, "t2", 2) is None
    p1 = plan.add_sortie("d1", "t1", t1[1], "ARC", 0.5, [plan.visits[t1[3]].ground[0]], t2[2], order=0)
    plan.visits[t1[3]].ground.clear()
    plan.remove_visit(t1[3])
    assert not has_wait_cycle(plan)
    # 构造死锁：d3: t2@a → t1@b；d1: t1@c → t2@d，且 t1 的 b 在 c 之前… 令两航次互相等待
    # t1 先到 visit 0 等 d3（t2 在其 visit 5 放飞），而 t2 到 visit 0 等 d1（t1 在 visit 5 放飞）
    plan2 = ground_only_plan(inst, 5, 5)
    r1, r2 = plan2.routes["t1"], plan2.routes["t2"]
    g1 = plan2.visits[r1[7]].ground[0]
    g2 = plan2.visits[r2[7]].ground[0]
    for v, r in ((r1[7], "t1"), (r2[7], "t2")):
        plan2.visits[v].ground.clear()
    plan2.remove_visit(r1[7]); plan2.remove_visit(r2[7])
    plan2.add_sortie("d1", "t1", r1[5], "STOP", 0.0, [g1], r2[0], order=0)
    plan2.add_sortie("d3", "t2", r2[5], "STOP", 0.0, [g2], r1[0], order=0)
    assert has_wait_cycle(plan2), "t1@5 放飞→t2@0 回收 与 t2@5 放飞→t1@0 回收 互相等待（0 等 5，5 排在 0 后）"
    ev = evaluate_plan(plan2, inst, phys, initial_state(inst, phys), None, "T")
    assert not ev.feasible and "CROSS_WAIT_CYCLE" in " ".join(ev.violations)


def test_slot_ledger_counts_idle_drone_after_cross_recovery(nominals):
    """跨车回收后的无人机继续占用回收车机位：把机位数压到 2 时，含跨车航次的 X 计划（回收车上 3 机）必须被判 SLOT_OVER."""
    inst, phys, alg, res = nominals
    m, plan, cost, H = res["X"]
    assert any(is_cross_sortie(plan, s) for s in plan.sorties.values())
    ev3 = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "T")
    assert ev3.feasible
    phys2 = dataclasses.replace(phys, truck_drone_slots=2)
    ev2 = evaluate_plan(plan, inst, phys2, initial_state(inst, phys2), H, "T")
    assert not ev2.feasible and any("SLOT_OVER" in v for v in ev2.violations), ev2.violations


def test_schedule_converges_for_cross_plan(nominals):
    inst, phys, alg, res = nominals
    m, plan, cost, H = res["X"]
    tl = schedule_plan(plan, inst, phys, initial_state(inst, phys))
    assert tl.converged and tl.iterations < 14


def test_drop_broken_chain_on_cross_removal(nominals):
    """删除链中间的跨车航次后，后续（放飞车=其回收车的）航次一并释放，不留悬空链."""
    inst, phys, alg, res = nominals
    m, plan, cost, H = res["X"]
    from tdr.moves import remove_sortie_closure
    chain = None
    for d, sids in plan.drone_sorties.items():
        for i, sid in enumerate(sids[:-1]):
            if is_cross_sortie(plan, plan.sorties[sid]):
                chain = (d, sid, sids[i + 1:])
    if chain is None:
        pytest.skip("该实例的 X 解里没有“后面还有航次”的跨车航次")
    p2 = plan.clone()
    freed = []
    remove_sortie_closure(p2, chain[1], freed)
    assert all(x not in p2.sorties for x in chain[2])
    assert not p2.validate_structure(inst, phys)


def test_same_visit_recovery_before_launch_deadlock():
    """同一访问内先回收后放飞：t3@3 回收来自 t5@3 的机、又要放飞去 t5@3，而 t5@3 反之——死锁必须被检出."""
    inst, phys, alg = _setup()
    from tdr.plan import ground_only_plan
    plan = ground_only_plan(inst, 5, 5)
    r3, r5 = plan.routes["t3"], plan.routes["t5"]
    pa = plan.visits[r3[6]].ground[0]
    pb = plan.visits[r5[6]].ground[0]
    for v in (r3[6], r5[6]):
        plan.visits[v].ground.clear()
    plan.remove_visit(r3[6]); plan.remove_visit(r5[6])
    # d5(t3 的机) 从 t3@3 放飞，t5@3 回收；d9(t5 的机) 从 t5@3 放飞，t3@3 回收
    plan.add_sortie("d5", "t3", r3[3], "ARC", 0.5, [pa], r5[3], order=0)
    plan.add_sortie("d9", "t5", r5[3], "ARC", 0.5, [pb], r3[3], order=0)
    assert has_wait_cycle(plan)


FIX6 = ROOT / "tests" / "fixtures" / "r6"


def test_carrier_at_committed_recovery_truncation_cross_plan():
    """R100 seed7（X 名义含跨车航次）：失败时刻 d8 正处于已承诺的回收 R 中，其承运车必须取该航次回收车(t4)，
    而不是整班最终承运车(t2)——修复前 INITIAL_RECOVERY_FAILED:航次36放飞车t4与承运车t2不符(STOPPED)."""
    from tdr.hidden_world import HiddenWorld
    from tdr import simulate
    inst, phys, alg = _setup("R100")
    alg.recovery_eval_budget_override = 1000
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    _, _, H = load_case_nominal(inst, FIX6 / "S" / "R100")
    plan, _, _ = load_case_nominal(inst, FIX6 / "X" / "R100")
    assert any(is_cross_sortie(plan, s) for s in plan.sorties.values())
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "N")
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, "R100", "recovery", 0)
    ep = simulate.run_episode(inst, plan, nom, H, phys, HiddenWorld(inst, "R100", 7), "X", alg, rngs,
                              recovery_eval_budget=1000)
    assert not any("不符" in n for n in ep.notes), ep.notes
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes[:2])


def test_two_phase_phase1_identical_and_equal_budget(tmp_path):
    inst, phys, alg = _setup("C50")
    ms = {}
    for strat in ("S", "X"):
        ms[strat] = build_case_nominal(inst, phys, alg, tmp_path / strat, eval_budget=400,
                                       cross_launch=(strat == "X"), two_phase_b=150)
    assert ms["S"]["phase1_cost"] == ms["X"]["phase1_cost"], "阶段1 必须逐位相同"
    assert ms["S"]["phase1_evals"] == ms["X"]["phase1_evals"]
    assert ms["S"]["n_cross_sorties"] == 0
    assert ms["S"]["verified"] and ms["X"]["verified"]
    assert ms["X"]["cost"] <= ms["X"]["phase1_cost"] + 1e-9 and ms["S"]["cost"] <= ms["S"]["phase1_cost"] + 1e-9
