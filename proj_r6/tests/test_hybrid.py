"""第 8 轮：情景样本与评价种子分开；S 的补救和列池都不产生跨车；评价计入预算。"""
import json
from pathlib import Path

from tdr.alns import Budget, SearchStats, SolveContext
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import is_cross_sortie
from tdr.experiment import plan_from_dict
from tdr.hidden_world import bernoulli_failure_flags
from tdr.hybrid import (
    assemble,
    build_recourse,
    extract_columns,
    milp_select,
    sample_failure_scenarios,
    scenario_score,
)
from tdr.moves import parcel_delivery
from tdr.nominal import phase1_allows_cross
from tdr.schedule import initial_state

ROOT = Path(__file__).resolve().parents[1]


def _c50():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    return inst, phys, plan


def test_nominal_scenarios_are_fixed_and_not_the_episode_stream():
    inst, _, _ = _c50()
    ids = [c.parcel_id for c in inst.customers]
    a = sample_failure_scenarios("C50", ids, 0.2, 2, 0)
    b = sample_failure_scenarios("C50", ids, 0.2, 2, 0)
    assert a == b
    assert len(a) == 2
    for seed in list(range(1, 11)) + [101]:
        episode = bernoulli_failure_flags("C50", seed, ids, 0.2)
        assert a[0] != episode
        assert a[1] != episode


def test_s_recourse_stays_on_the_launch_truck_and_x_may_use_another():
    inst, phys, plan = _c50()
    sortie = next(s for s in plan.sorties.values() if s.air)
    parcel = sortie.air[0]
    launch = sortie.truck
    customer = inst.parcel_to_customer[parcel]
    other = next(t for t in plan.routes if t != launch)
    plan.add_visit(other, customer, pos=0, ground=[])
    s_plan = build_recourse(plan, frozenset({parcel}), inst, phys, False)
    x_plan = build_recourse(plan, frozenset({parcel}), inst, phys, True)
    assert parcel_delivery(s_plan, parcel)[0] == "G"
    s_truck = s_plan.visits[parcel_delivery(s_plan, parcel)[1]].truck
    x_truck = x_plan.visits[parcel_delivery(x_plan, parcel)[1]].truck
    assert s_truck == launch
    assert x_truck == other


def test_scenario_score_spends_one_eval_per_failing_scenario_and_then_caches():
    inst, phys, plan = _c50()
    sortie = next(s for s in plan.sorties.values() if s.air)
    parcel = sortie.air[0]
    alg = AlgorithmConfig(scenario_aware=True, scenario_count=2, scenario_p=0.2,
                          scenario_infeasible_penalty=400.0)
    state = initial_state(inst, phys)
    state.nominal_cross = False
    ctx = SolveContext(inst, phys, alg, state, None, "nominal")
    ctx.scenarios = [frozenset({parcel}), frozenset({parcel})]
    ctx.live_budget = Budget(6, None)
    ctx.live_stats = SearchStats()
    class Ev:
        feasible = True
        cost = 10.0
    score = scenario_score(plan, Ev(), ctx)
    assert score is not None
    assert ctx.live_budget.used == 2
    again = scenario_score(plan, Ev(), ctx)
    assert again == score
    assert ctx.live_budget.used == 2


def test_x_columns_are_coupled_components_not_single_trucks():
    from tdr.hybrid import ColumnPool, SyncColumn, assemble_sync, extract_sync, milp_select_sync
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C100")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C100")
    raw = json.loads((ROOT / "r6/results/round7/R7/nominal/X/C100/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    comps = extract_sync(plan, inst, phys)
    assert comps
    assert extract_columns(plan, inst, phys, True) is None
    for col in comps:
        assert len(col.trucks) >= 2
        assert col.crosses
        for drone, lt, rt, lc, rc, air, mode, lam in col.crosses:
            assert lt in col.trucks and rt in col.trucks and lt != rt
            assert air and set(air) <= col.covers
    pool = ColumnPool(True)
    pool.add_plan(plan, inst, phys)
    assert pool.routes == []
    assert pool.links == []
    assert pool.sync
    built = assemble_sync(plan, comps[:1], inst, phys)
    assert built is not None
    assert built.assigned_parcels() == plan.assigned_parcels()
    assert any(is_cross_sortie(built, s) for s in built.sorties.values())
    cheap = comps[0]
    other = SyncColumn(cheap.trucks, cheap.routes, cheap.crosses, cheap.proxy + 500.0,
                       cheap.covers, cheap.drones)
    picked = milp_select_sync([cheap, other], plan, inst, phys)
    assert picked is not None
    assert len(picked) <= 1


def test_recombined_plan_is_scored_on_the_scenario_pool():
    inst, phys, plan = _c50()
    from tdr.hybrid import try_set_partition
    alg = AlgorithmConfig(scenario_aware=True, set_partition=True, scenario_count=2,
                          scenario_p=0.2, scenario_infeasible_penalty=400.0)
    state = initial_state(inst, phys)
    state.nominal_cross = False
    ctx = SolveContext(inst, phys, alg, state, None, "nominal")
    ctx.scenario_on = True
    ctx.live_budget = Budget(30, None)
    ctx.live_stats = SearchStats()
    # 放进一条更短的同车列，主问题会把它和其余路线配起来；接受前必须有情景分。
    from tdr.hybrid import ColumnPool, _pool
    pool = _pool(ctx, False)
    pool.add_plan(plan, inst, phys, keep=True)
    assert pool.routes
    short = pool.routes[0]
    short.proxy = -1.0e6
    ctx.live_stats.audit = {}
    got = try_set_partition(plan, ctx, ctx.live_budget, ctx.live_stats)
    assert got[0] is not None and got[1] is not None and got[1].feasible
    assert ctx.live_stats.audit["SET_PARTITION"]["scenario_scored"] >= 1
    assert not any(is_cross_sortie(got[0], s) for s in got[0].sorties.values())


def test_strategy_r_freezes_s_nominal_and_uses_x_recovery():
    from tdr.experiment import nominal_and_recovery
    from tdr.plan import Plan
    s = Plan("C50")
    s.add_visit("t1", "c1", ground=["p1"])
    x = Plan("C50")
    x.add_visit("t2", "c2", ground=["p1"])
    plan_r, rec_r = nominal_and_recovery("R", s, x, False)
    plan_s, rec_s = nominal_and_recovery("S", s, x, False)
    plan_x, rec_x = nominal_and_recovery("X", s, x, False)
    assert rec_s == "S" and rec_r == "X" and rec_x == "X"
    assert plan_r is not s
    assert plan_r.assigned_parcels() == s.assigned_parcels()
    assert plan_x.assigned_parcels() == x.assigned_parcels()


def test_s_column_pool_does_not_recombine_into_a_cross_sortie():
    inst, phys, plan = _c50()
    got = extract_columns(plan, inst, phys, False)
    assert got is not None
    routes, links = got
    assert links == []
    chosen = milp_select(routes, [], [c.parcel_id for c in inst.customers])
    assert chosen is not None
    assert chosen[1] == []
    built = assemble(chosen[0], [], inst)
    assert built is not None
    assert not any(is_cross_sortie(built, s) for s in built.sorties.values())
    assert built.assigned_parcels() == plan.assigned_parcels()


def test_r8_preset_gives_s_and_x_the_same_hybrid_without_opening_s():
    import os
    import sys
    cwd = os.getcwd()
    sys.path.insert(0, str(ROOT / "r6"))
    try:
        from run_round2 import configs
        pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
        _, alg, _, _ = configs(pkg, "R8")
    finally:
        os.chdir(cwd)
    assert alg.scenario_aware is True
    assert alg.set_partition is True
    assert alg.scenario_count == 2
    assert alg.x_adopt_s_if_cross is False
    assert alg.x_adopt_s_nominal is False
    assert alg.x_cross_from_start is True
    assert phase1_allows_cross(False, alg) is False
    assert phase1_allows_cross(True, alg) is True
