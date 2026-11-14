"""T08a-5b：运行时验证统一参数传递、默认 top-k 和目录能量预筛。"""
from dataclasses import replace
from inspect import signature

import pytest

from tdr import config, recovery, recovery_milp, simulate
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.evaluate import evaluate_plan
from tdr.hidden_world import TestWorld as ForcedWorld
from tdr.plan import Plan
from tdr.schedule import initial_state


@pytest.fixture
def tiny(monkeypatch):
    # 纯手工案例，不使用实验种子；隔离评价器会刷新的全局车队配置。
    monkeypatch.setattr(config, "ACTIVE", dict(config.ACTIVE))
    phys = PhysicalConfig(truck_count=1, drone_count=1)
    inst = Instance("tiny", "T", 0.0, 0.0, (
        Customer("c1", "p1", 100.0, 0.0, 1.0),
        Customer("c2", "p2", 200.0, 0.0, 1.0),
    ))
    plan = Plan("tiny")
    plan.routes = {"t1": []}
    rv = plan.add_visit("t1", "c2", ground=["p2"])
    plan.add_sortie("d1", "t1", None, "ARC", 0.0, ["p1"], rv.vid)
    return plan, inst, phys


class ReachedMilp(Exception):
    """捕获到真实调用点后终止，避免运行无关的恢复搜索。"""


def _capture(monkeypatch):
    calls = {"initial": [], "catalog": [], "milp": []}
    real_initial = recovery.initial_recovery
    real_catalog = recovery.RecoveryCatalog
    real_milp = recovery_milp.solve_recovery_milp

    def record(name, fn, args, kwargs):
        bound = signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        calls[name].append(bound.arguments)

    def initial(*args, **kwargs):
        record("initial", real_initial, args, kwargs)
        return real_initial(*args, **kwargs)

    def catalog(*args, **kwargs):
        record("catalog", real_catalog, args, kwargs)
        return real_catalog(*args, **kwargs)

    def milp(*args, **kwargs):
        record("milp", real_milp, args, kwargs)
        raise ReachedMilp

    monkeypatch.setattr(simulate, "initial_recovery", initial)
    monkeypatch.setattr(recovery, "RecoveryCatalog", catalog)
    monkeypatch.setattr(recovery_milp, "solve_recovery_milp", milp)
    return calls


@pytest.mark.parametrize("energy_screen", [False, True])
@pytest.mark.parametrize("top_k", [10, 3])
def test_episode_passes_uniform_settings_to_initial_milp_and_catalog(tiny, monkeypatch,
                                                                   energy_screen, top_k):
    plan, inst, phys = tiny
    nominal = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "T")
    assert nominal.feasible, nominal.violations
    calls = _capture(monkeypatch)
    alg = replace(AlgorithmConfig(), recovery_decision="milp",
                  recovery_milp_top_k=top_k, recovery_energy_screen=energy_screen)
    for strategy in ("S", "R", "X"):
        with pytest.raises(ReachedMilp):
            simulate.run_episode(
                inst, plan, nominal, 10000.0, phys, ForcedWorld(inst, "tiny", ("p1",)),
                strategy, alg, simulate.derive_rngs(42, "tiny", "recovery", 0),
                recovery_eval_budget=0,
            )
    for rows in calls.values():
        assert [r["strategy"] for r in rows] == ["S", "R", "X"]
    assert [(r["milp_top_k"], r["energy_screen"]) for r in calls["initial"]] == [
        (top_k, energy_screen)] * 3
    assert [r["top_k"] for r in calls["milp"]] == [top_k] * 3
    assert [r["drop_energy_tail"] for r in calls["catalog"]] == [energy_screen] * 3


def test_direct_call_defaults(tiny, monkeypatch):
    plan, inst, phys = tiny
    frag = next(iter(plan.sorties.values()))
    frag.started = True
    frag.start_pos = (0.0, 0.0)
    calls = _capture(monkeypatch)
    for strategy in ("S", "R", "X"):
        with pytest.raises(ReachedMilp):
            simulate.initial_recovery(plan, initial_state(inst, phys), inst, phys,
                                      strategy, set(), use_milp=True)
        # 直接省略 MILP 的 top_k，捕获它自己的默认参数绑定。
        with pytest.raises(ReachedMilp):
            recovery_milp.solve_recovery_milp(plan, frag.sid, inst, phys,
                                             initial_state(inst, phys), strategy, set())
    assert [(r["milp_top_k"], r["energy_screen"]) for r in calls["initial"]] == [(10, False)] * 3
    assert [r["top_k"] for r in calls["milp"]] == [10] * 6
    assert [r["drop_energy_tail"] for r in calls["catalog"]] == [False] * 3


@pytest.mark.parametrize("guard_n", [0, 1, 40])
@pytest.mark.parametrize("energy_screen", [False, True])
def test_catalog_screen_applies_to_guard_and_tail(tiny, monkeypatch, guard_n, energy_screen):
    plan, inst, phys = tiny
    frag = next(iter(plan.sorties.values()))
    frag.start_pos = (0.0, 0.0)
    frag.air = []
    stops = [recovery_milp.Stop(truck, True, ref, ref, pos, 0.0, 0.0, [], [], 0)
             for truck in ("t1", "t2")
             for ref, pos in (("near", (0.0, 0.0)), ("far", (1e6, 0.0)))]
    monkeypatch.setattr(recovery_milp, "build_stops", lambda *args: stops)
    results = {}
    for strategy in ("S", "R", "X"):
        cat = recovery.RecoveryCatalog(plan, frag, inst, strategy, initial_state(inst, phys),
                                       phys=phys, guard_n=guard_n, drop_energy_tail=energy_screen)
        entries = cat.next_entries(100)
        assert cat.exhausted
        refs = {e["ref"] for e in entries}
        assert refs == ({"near"} if energy_screen else {"near", "far"})
        assert any(e["est"] >= 1e4 for e in entries) is (not energy_screen)
        results[strategy] = [e for e in entries if e["truck"] == "t1"]
    assert results["S"] == results["R"] == results["X"]
