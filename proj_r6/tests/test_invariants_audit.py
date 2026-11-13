"""第五轮审计：模型不变量。不读取评价种子上的成本来决定规则。"""
import inspect
import json
from pathlib import Path

import pytest

from tdr.alns import _better
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, is_cross_sortie, recovery_is_cross
from tdr.experiment import load_case_nominal
from tdr.hidden_world import bernoulli_failure_flags
from tdr.invariants import check_plan, check_segments
from tdr.plan import Plan
from tdr.schedule import initial_state, schedule_plan
from tdr.simulate import collect_segment, initial_run_state

ROOT = Path(__file__).resolve().parents[1]
CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]


def _light(case):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, case)
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), case)
    return inst, phys


def test_failure_flags_ignore_strategy_and_match_across_calls():
    inst, _ = _light("C50")
    parcels = [c.parcel_id for c in inst.customers]
    a = bernoulli_failure_flags("C50", 3, parcels, 0.2)
    b = bernoulli_failure_flags("C50", 3, parcels, 0.2)
    assert a == b
    # 策略不进入哈希：同一函数没有 strategy 参数
    assert "strategy" not in inspect.signature(bernoulli_failure_flags).parameters


def test_reported_cost_has_no_strategy_argument():
    assert "strategy" not in inspect.signature(evaluate_plan).parameters


def test_lexicographic_cost_then_z():
    alg = AlgorithmConfig()

    class E:
        def __init__(self, cost, z, feasible=True):
            self.cost, self.z, self.feasible = cost, z, feasible

    assert _better(E(1.0, 9.0), E(2.0, 0.0), alg)
    assert not _better(E(2.0, 0.0), E(1.0, 9.0), alg)
    assert _better(E(1.0, 3.0), E(1.0, 4.0), alg)
    assert not _better(E(1.0, 4.0), E(1.0, 3.0), alg)


def test_same_truck_launch_not_before_recovery_is_invalid():
    inst, phys = _light("C50")
    plan = Plan("C50")
    for t in range(phys.truck_count):
        plan.routes[f"t{t + 1}"] = []
    a = plan.add_visit("t1", inst.customers[0].customer_id, ground=[inst.customers[0].parcel_id])
    b = plan.add_visit("t1", inst.customers[1].customer_id, ground=[])
    # 其余客户留在后面的车上，避免“未安排交付”掩盖结构错误
    for i, c in enumerate(inst.customers[1:], start=1):
        truck = f"t{(i % phys.truck_count) + 1}"
        if c.parcel_id == inst.customers[1].parcel_id:
            continue
        plan.add_visit(truck, c.customer_id, ground=[c.parcel_id])
    drone = phys.home_drones("t1")[0]
    # 放飞在较晚的访问 b，回收在较早的访问 a
    plan.add_sortie(drone, "t1", b.vid, "STOP", 0.0, [inst.customers[1].parcel_id], a.vid)
    # 把 p of customer 1 off the ground visit so it is only on the sortie
    b.ground = [p for p in b.ground if p != inst.customers[1].parcel_id]
    errs = plan.validate_structure(inst, phys)
    assert any("不早于回收" in e for e in errs), errs


def test_unconverged_timeline_is_not_feasible(monkeypatch):
    inst, phys = _light("C50")
    plan, _, H = load_case_nominal(inst, ROOT / "r6/results/round3/R3/nominal/S/C50")
    real = schedule_plan

    def fake(*args, **kwargs):
        tl = real(*args, **kwargs)
        tl.converged = False
        return tl

    monkeypatch.setattr("tdr.evaluate.schedule_plan", fake)
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "AUDIT")
    assert not ev.feasible
    assert ev.violations == ["SCHEDULE_NOT_CONVERGED"]


def test_started_fragment_cross_is_visible_to_s_policy():
    inst, phys = _light("C50")
    plan, _, _ = load_case_nominal(inst, ROOT / "r6/results/round3/R3/nominal/S/C50")
    s = next(iter(plan.sorties.values()))
    other = next(v for v in plan.visits.values() if v.truck != plan.visits[s.launch_vid].truck)
    s.started = True
    s.start_pos = (0.0, 0.0)
    s.launch_truck = s.truck
    s.rec_vid = other.vid
    s.truck = other.truck
    assert not is_cross_sortie(plan, s)
    assert recovery_is_cross(plan, s)
    hits = [x for x in check_plan(plan, inst, phys, strategy="S") if x.startswith("S_CROSS")]
    assert hits


def test_nominal_plans_recheck_return_and_feasible_ones_satisfy_replay():
    for case in CASES:
        inst, phys = _light(case)
        for side in ("S", "X"):
            plan, _, H = load_case_nominal(inst, ROOT / f"r6/results/round3/R3/nominal/{side}/{case}")
            v = check_plan(plan, inst, phys, initial_state(inst, phys), H, strategy=side)
            # T08a：历史计划的失败带货等待缺口必须拒绝，不能继续声称全部可行。
            unsafe = case in {"R100", "RC100"} or (case, side) == ("R50", "X")
            if unsafe:
                assert len(v) == 1 and v[0].startswith("SWAP_CANNOT_FIX:"), (case, side, v)
                assert ":stage=SERVICE:" in v[0]
                continue
            assert v == [], (case, side, v[:5])
            st = initial_run_state(plan, inst, phys)
            ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
            assert ev.feasible and ev.timeline.converged
            t_end = max(list(ev.timeline.truck_finish.values())
                        + [x.end for lst in ev.timeline.drone_stages.values() for x in lst] + [0.0])
            seg = collect_segment(plan, ev.timeline, inst, phys, 0.0, t_end, st)
            viol, cost = check_segments(inst, phys, [seg], H, strategy=side, require_complete=True)
            assert viol == [], (case, side, viol[:5])
            assert cost is not None and abs(cost - ev.cost) <= 1e-4


def test_s_catalog_does_not_offer_another_truck():
    """估计成本目录对 S 只产出原放飞车。"""
    from tdr.recovery import RecoveryCatalog
    from tdr.schedule import DroneStart

    inst, phys = _light("R50")
    plan, _, _ = load_case_nominal(inst, ROOT / "r6/results/round3/R3/nominal/S/R50")
    s = next(x for x in plan.sorties.values() if x.air and x.launch_vid is not None)
    s.started = True
    s.start_pos = (inst.depot_x, inst.depot_y)
    s.mode = "AIR"
    s.launch_truck = s.truck
    st = initial_state(inst, phys)
    st.t0 = 10.0
    st.drone_start[s.drone] = DroneStart("AIRBORNE", None, 10.0, s.start_pos, phys.e_cap)
    cat = RecoveryCatalog(plan, s, inst, "S", st, set(), phys=phys, guard_n=5)
    entries = cat.next_entries(30)
    assert entries
    assert {e["truck"] for e in entries} == {s.launch_truck}


def test_cross_nominal_is_not_published_when_flag_on():
    """诊断回退的行为锁：开关打开时，含跨车的 X 名义整份换成 S 的克隆。默认关，不是最终设计。"""
    from tdr.evaluate import is_cross_sortie
    from tdr.experiment import nominal_plan_for_run

    inst, phys = _light("R50")
    plan_s, _, _ = load_case_nominal(inst, ROOT / "r6/results/round3/R3/nominal/S/R50")
    plan_x, _, _ = load_case_nominal(inst, ROOT / "r6/results/round3/R3/nominal/X/R50")
    assert any(is_cross_sortie(plan_x, s) for s in plan_x.sorties.values())
    kept = nominal_plan_for_run(plan_s, plan_x, "X", False)
    assert kept is plan_x
    published = nominal_plan_for_run(plan_s, plan_x, "X", True)
    assert published is not plan_s
    assert not any(is_cross_sortie(published, s) for s in published.sorties.values())
    ev_s = evaluate_plan(plan_s, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    ev_p = evaluate_plan(published, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    assert abs(ev_s.cost - ev_p.cost) <= 1e-9
    # S 不受这个开关影响；没有跨车的 X 名义也不被替换
    assert nominal_plan_for_run(plan_s, plan_x, "S", True) is plan_x
    inst_c, _ = _light("C100")
    c_s, _, _ = load_case_nominal(inst_c, ROOT / "r6/results/round3/R3/nominal/S/C100")
    c_x, _, _ = load_case_nominal(inst_c, ROOT / "r6/results/round3/R3/nominal/X/C100")
    assert not any(is_cross_sortie(c_x, s) for s in c_x.sorties.values())
    assert nominal_plan_for_run(c_s, c_x, "X", True) is c_x


def test_stopped_episode_keeps_prefix_and_prefix_obeys_physics(monkeypatch):
    """恢复失败时，已经飞过的前缀必须留下来，并且除了“还没送完”以外没有物理违规。"""
    from tdr.hidden_world import make_world
    from tdr.invariants import check_episode
    from tdr.simulate import derive_rngs, run_episode

    def _fail(*_a, **_k):
        return None, ["PROBE"], None

    monkeypatch.setattr("tdr.simulate.initial_recovery", _fail)
    inst, phys = _light("C50")
    for side in ("S", "X"):
        plan, _, H = load_case_nominal(
            inst, ROOT / f"r6/results/round3/R3/nominal/{side}/C50")
        nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
        world = make_world(inst, "C50", 1, "bernoulli", 0.2)
        ep = run_episode(inst, plan, nom, H, phys, world, side, AlgorithmConfig(),
                         derive_rngs(1, "C50", "recovery", 0),
                         recovery_eval_budget=10, cut_mode="snapshot",
                         max_replans=len(inst.customers))
        assert ep.status == "STOPPED_NO_FEASIBLE_SUFFIX"
        assert ep.segments, side
        rep = check_episode(ep, inst, phys)
        assert rep["ok"], (side, rep["violations"])
        if side == "S":
            assert rep["n_cross_plan"] == 0
            for seg in ep.segments:
                for a in seg["actions"]:
                    if a.get("kind") == "R" and a.get("launch_truck"):
                        assert a["launch_truck"] == a["actor"]
