"""S_SEED 兜底目录必须沿用初始化的能量预筛开关。"""
import pytest

from tdr import recovery, recovery_milp
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.plan import Plan
from tdr.schedule import initial_state


@pytest.mark.parametrize("energy_screen", [True, False, None],
                         ids=["enabled", "disabled", "default"])
def test_s_seed_catalog_preserves_energy_screen(monkeypatch, energy_screen):
    # 手工案例，不使用实验种子；近点可达，远点产生能量惩罚。
    phys = PhysicalConfig(truck_count=1, drone_count=1)
    inst = Instance("s_seed", "T", 0.0, 0.0, (
        Customer("near", "p1", 0.0, 0.0, 1.0),
        Customer("far", "p2", 1e6, 0.0, 1.0),
    ))
    plan = Plan("s_seed")
    plan.routes = {"t1": []}
    rv = plan.add_visit("t1", "near")
    frag = plan.add_sortie("d1", "t1", None, "ARC", 0.0, [], rv.vid)
    frag.started, frag.start_pos = True, (0.0, 0.0)
    stops = [recovery_milp.Stop("t1", True, ref, ref, pos, 0.0, 0.0, [], [], 0)
             for ref, pos in (("near", (0.0, 0.0)), ("far", (1e6, 0.0)))]
    monkeypatch.setattr(recovery_milp, "build_stops", lambda *args: stops)

    calls = []

    def unavailable(res, sid, entry, inst, phys, state, ground_required, strategy,
                    **kwargs):
        calls.append((strategy, entry))
        return []

    # 无可构造解且预算仍有剩余，确保真实 initial_recovery 走完 S_SEED。
    # 保留真实 RecoveryCatalog 构造、排序和筛选，捕获传往候选构造器的条目。
    monkeypatch.setattr(recovery, "build_residual_candidate", unavailable)
    monkeypatch.setattr(recovery, "build_candidates", lambda *args, **kwargs: [])
    budget = recovery.Budget(eval_limit=100, wall_limit=None)
    info = {}
    kwargs = {} if energy_screen is None else {"energy_screen": energy_screen}
    best, _, catalog = recovery.initial_recovery(
        plan, initial_state(inst, phys), inst, phys, "X", set(),
        budget=budget, keep_s_recovery=True, info=info, **kwargs,
    )

    assert AlgorithmConfig().recovery_energy_screen is False
    assert best is None and budget.evals_left() > 0
    assert info["s_seed_used"] is True
    assert catalog.exhausted
    assert [strategy for strategy, entry in calls if entry is None] == ["X", "S"]
    main = [entry for strategy, entry in calls if strategy == "X" and entry is not None]
    seed = [entry for strategy, entry in calls if strategy == "S" and entry is not None]
    expected = {"near"} if energy_screen else {"near", "far"}
    assert {entry["ref"] for entry in main} == expected
    assert {entry["ref"] for entry in seed} == expected
    assert seed == main
    assert any(entry["est"] >= 1e4 for entry in seed) is (not bool(energy_screen))
