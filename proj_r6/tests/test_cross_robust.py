"""第 6 轮：名义跨车按航次检查最终时刻表，不整份退回同车。"""
import json
from pathlib import Path

from tdr.alns import SolveContext, _cross_energy_ok, _nominal_cross_intact
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.cross_nominal import propose_exchange
from tdr.cross_robust import (
    cross_robust_violations,
    repair_nominal_cross,
    reserve_kwh,
)
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, is_cross_sortie
from tdr.experiment import plan_from_dict
from tdr.schedule import initial_state

ROOT = Path(__file__).resolve().parents[1]


def _light(case):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, case)
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), case)
    return inst, phys


def _saved(case, side):
    inst, phys = _light(case)
    raw = json.loads((ROOT / f"r6/results/round3/R3/nominal/{side}/{case}/nominal_plan.json").read_text())
    return inst, phys, plan_from_dict(raw["plan"])


def _ctx(inst, phys, robust=True):
    ctx = SolveContext(
        inst, phys,
        AlgorithmConfig(x_cross_robust=robust, x_cross_energy_margin_frac=0.05,
                        x_rendezvous_slack_s=90.0, x_cross_exchange=True),
        initial_state(inst, phys), None, "nominal")
    ctx.state.nominal_cross = True
    return ctx


def test_light_reserve_is_0_075_kwh():
    _, phys = _light("R50")
    assert abs(reserve_kwh(phys) - 0.075) < 1e-12


def test_published_cross_sorties_fail_final_timetable_checks():
    inst, phys, plan = _saved("R50", "X")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    viol = cross_robust_violations(plan, inst, phys, ev.timeline, 90.0)
    assert set(viol) == {48, 53, 54}
    assert any(t.startswith("MARGIN:") for t in viol[48])
    assert any(t.startswith("SLACK:") for t in viol[48])
    assert any(t.startswith("SLOT:") for t in viol[48])
    assert any(t.startswith("GROUND:p030@") for t in viol[48])
    # s53 余电够 0.075，也够 90 秒；它不合格是因为占满机位，并且带走了接机车自己的客户。
    assert not any(t.startswith("MARGIN:") for t in viol[53])
    assert not any(t.startswith("SLACK:") for t in viol[53])
    assert any(t.startswith("SLOT:") for t in viol[53])
    assert any(t.startswith("GROUND:p014@") for t in viol[53])
    assert any(t.startswith("GROUND:p027@") for t in viol[54])
    inst2, phys2, plan2 = _saved("RC50", "X")
    ev2 = evaluate_plan(plan2, inst2, phys2, initial_state(inst2, phys2), None, "NOMINAL")
    viol2 = cross_robust_violations(plan2, inst2, phys2, ev2.timeline, 90.0)
    assert 12 in viol2
    assert any(t.startswith("GROUND:p041@") for t in viol2[12])
    assert any(t.startswith("SLOT:") for t in viol2[12])


def test_longer_slack_rejects_a_sortie_the_90s_check_allows():
    inst, phys, plan = _saved("R50", "X")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    short = cross_robust_violations(plan, inst, phys, ev.timeline, 90.0)
    long = cross_robust_violations(plan, inst, phys, ev.timeline, 300.0)
    assert not any(t.startswith("SLACK:") for t in short[53])
    assert any(t.startswith("SLACK:") for t in long[53])


def test_final_timetable_rechecks_a_cross_sortie_whose_recovery_did_not_change():
    """旧门槛只在回收点改变时查。最终时刻表上的薄余电必须仍然被拒绝。"""
    inst, phys, plan = _saved("R50", "X")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    ctx = _ctx(inst, phys, robust=True)
    assert _cross_energy_ok(plan, plan.clone(), ev, ctx) is True
    assert _nominal_cross_intact(plan, ev, ctx) is False
    ctx.state.nominal_cross = False
    assert _nominal_cross_intact(plan, ev, ctx) is True
    ctx_off = _ctx(inst, phys, robust=False)
    assert _nominal_cross_intact(plan, ev, ctx_off) is True


def test_repair_is_per_sortie_and_leaves_a_feasible_plan():
    inst, phys, plan = _saved("R50", "X")
    repaired, actions = repair_nominal_cross(plan, inst, phys, 90.0)
    assert actions
    assert all(a.startswith(("strip:", "uncross:", "dissolve:", "remove_empty:")) for a in actions)
    ev = evaluate_plan(repaired, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    assert ev.feasible, ev.violations
    assert cross_robust_violations(repaired, inst, phys, ev.timeline, 90.0) == {}
    inst_s, phys_s, plan_s = _saved("R50", "S")
    repaired_s, actions_s = repair_nominal_cross(plan_s, inst_s, phys_s, 90.0)
    assert actions_s == []
    ev_s = evaluate_plan(plan_s, inst_s, phys_s, initial_state(inst_s, phys_s), None, "NOMINAL")
    ev_sr = evaluate_plan(repaired_s, inst_s, phys_s, initial_state(inst_s, phys_s), None, "NOMINAL")
    assert abs(ev_s.cost - ev_sr.cost) <= 1e-9


def test_exchange_tau_bounds_the_nominal_cost_increase():
    from types import SimpleNamespace
    from tdr.cross_nominal import _exchange_worth
    cur = SimpleNamespace(feasible=True, cost=100.0, z=10.0)
    alg = AlgorithmConfig(x_exchange_cost_tau=2.0)
    assert _exchange_worth(SimpleNamespace(feasible=True, cost=101.3, z=10.0), cur, alg)
    assert not _exchange_worth(SimpleNamespace(feasible=True, cost=107.1, z=10.0), cur, alg)
    assert not _exchange_worth(SimpleNamespace(feasible=True, cost=100.2, z=10.0), cur,
                               AlgorithmConfig(x_exchange_cost_tau=0.0))


def test_exchange_is_off_for_same_truck_search_and_can_be_robust():
    inst, phys, plan = _saved("C100", "S")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.inst, ctx.phys, ctx.H = inst, phys, None
    ctx.state = type("S", (), {"nominal_cross": False})()
    ctx.alg = AlgorithmConfig(x_cross_exchange=True, x_rendezvous_slack_s=90.0)
    assert propose_exchange(plan, ctx, 4, set()) == []
    ctx.state = type("S", (), {"nominal_cross": True})()
    ctx.alg = AlgorithmConfig(x_cross_exchange=False, x_rendezvous_slack_s=90.0)
    assert propose_exchange(plan, ctx, 4, set()) == []
    ctx.alg = AlgorithmConfig(x_cross_exchange=True, x_rendezvous_slack_s=90.0)
    cands = propose_exchange(plan, ctx, 12, set())
    assert cands
    robust = 0
    for _, cand in cands:
        ev = evaluate_plan(cand, inst, phys, initial_state(inst, phys), None, "NOMINAL")
        if not ev.feasible or ev.timeline is None:
            continue
        viol = cross_robust_violations(cand, inst, phys, ev.timeline, 90.0)
        n_cross = sum(1 for s in cand.sorties.values() if is_cross_sortie(cand, s))
        if not viol and n_cross >= 2:
            robust += 1
            for s in cand.sorties.values():
                if not is_cross_sortie(cand, s):
                    continue
                rec = cand.visits[s.rec_vid].truck
                owned = {cand.visits[v].customer for v in cand.routes[rec]}
                assert all(inst.parcel_to_customer[p] not in owned for p in s.air)
    assert robust >= 1
