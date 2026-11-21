"""T08a：重复客户访问的地送位置必须区分真实情景缓存项。"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tdr.alns import Budget, SearchStats, SolveContext
from tdr.config import ACTIVE, AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.evaluate import evaluate_plan
from tdr.hybrid import cached_scenario_cost, scenario_score
from tdr.plan import Plan
from tdr.schedule import initial_state


@pytest.mark.parametrize("allow_cross", [False, True])
def test_repeated_customer_ground_positions_use_separate_cache_entries(monkeypatch, allow_cross):
    # 评价会更新全局车队配置；用 monkeypatch 在测试结束时恢复，避免顺序依赖。
    for key, value in ACTIVE.items():
        monkeypatch.setitem(ACTIVE, key, value)
    root = Path(__file__).resolve().parents[1]
    pkg = json.loads((root / "data/package_light.json").read_text(encoding="utf-8"))
    phys = replace(PhysicalConfig.from_dict(pkg["config"]),
                   truck_count=1, drone_count=1, drones_per_truck_initial=1)
    inst = Instance("tiny", "T", 0.0, 0.0, (
        Customer("c1", "p1", 100.0, 0.0, 1.0),
        Customer("c2", "p2", 200.0, 0.0, 1.0),
        Customer("c3", "p3", 3000.0, 0.0, 1.0),
    ))
    first = Plan(inst.case_id)
    early = first.add_visit("t1", "c1", ground=["p1"])
    first.add_visit("t1", "c2", ground=["p2"])
    late = first.add_visit("t1", "c1")
    first.add_sortie("d1", "t1", None, "ARC", 0.0, ["p3"], late.vid)
    second = first.clone()
    second.visits[early.vid].ground = []
    second.visits[late.vid].ground = ["p1"]
    state = initial_state(inst, phys)
    state.nominal_cross = allow_cross
    ev_first = evaluate_plan(first, inst, phys, state)
    ev_second = evaluate_plan(second, inst, phys, state)
    assert ev_first.feasible, ev_first.violations
    assert ev_second.feasible, ev_second.violations
    assert ev_first.cost == pytest.approx(7.807784866593134)
    assert ev_second.cost == pytest.approx(8.512712495371337)

    alg = AlgorithmConfig(scenario_aware=True)
    ctx = SolveContext(inst, phys, alg, state, None, "nominal")
    # 固定无失败情景的真实情景分等于实际成本，不涉及任何随机种子。
    ctx.scenarios = [frozenset()]
    ctx.live_budget = Budget(2, None)
    ctx.live_stats = SearchStats()
    assert cached_scenario_cost(first, ctx) is None
    assert scenario_score(first, ev_first, ctx) == pytest.approx(ev_first.cost)
    assert cached_scenario_cost(second, ctx) is None
    assert scenario_score(second, ev_second, ctx) == pytest.approx(ev_second.cost)
    assert len(alg._scenario_cache) == 2

    # 去掉 live_budget 后仅已有缓存可返回值，证明两计划及 clone 均真实命中。
    ctx.live_budget = None
    for plan, ev in ((first, ev_first), (second, ev_second)):
        assert cached_scenario_cost(plan, ctx) == pytest.approx(ev.cost)
        assert scenario_score(plan.clone(), ev, ctx) == pytest.approx(ev.cost)

    # 访问 ID 只是标识；重编号不应改变相同路线结构的缓存命中。
    renamed = second.clone()
    mapping = {vid: vid + 10 for vid in renamed.visits}
    renamed.visits = {mapping[vid]: replace(v, vid=mapping[vid])
                      for vid, v in renamed.visits.items()}
    renamed.routes = {truck: [mapping[vid] for vid in route]
                      for truck, route in renamed.routes.items()}
    for sortie in renamed.sorties.values():
        sortie.rec_vid = mapping[sortie.rec_vid]
    renamed.next_vid += 10
    assert cached_scenario_cost(renamed, ctx) == pytest.approx(ev_second.cost)
    assert scenario_score(renamed, ev_second, ctx) == pytest.approx(ev_second.cost)
    assert len(alg._scenario_cache) == 2
