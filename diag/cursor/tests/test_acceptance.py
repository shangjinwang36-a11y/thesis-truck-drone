"""审计返工验收测试 T01—T15（可复现的非法/合法反例）."""
import json
import math
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance, load_instance
from tdr.evaluate import evaluate_plan
from tdr.plan import Plan
from tdr.schedule import StartState, initial_state

ROOT = Path(__file__).resolve().parents[1]
V = 25.0 / 3.0


@pytest.fixture(scope="module")
def phys():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    return PhysicalConfig.from_dict(json.loads(p.read_text(encoding="utf-8"))["config"])


def make_instance(case_id="TINY", n=2, positions=None):
    pos = positions or [(100.0, 0.0), (10000.0, 0.0)]
    custs = tuple(Customer(f"c{i+1:03d}", f"p{i+1:03d}", pos[i][0], pos[i][1], 1.0)
                  for i in range(n))
    return Instance(case_id, "T", 0.0, 0.0, custs)


# ---------------------------------------------------------------- T01 错址交付
def test_t01_wrong_destination_rejected(phys):
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.add_visit("t1", "c001", ground=["p001", "p002"])   # p002 应在 c002
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys))
    assert not ev.feasible
    assert ev.status == "INVALID_STRUCTURE"
    assert any("错址交付" in x for x in ev.violations)
    # 正例：各回各点
    ok = Plan("TINY")
    ok.routes["t1"] = []
    ok.add_visit("t1", "c001", ground=["p001"])
    ok.add_visit("t1", "c002", ground=["p002"])
    ev2 = evaluate_plan(ok, inst, phys, initial_state(inst, phys))
    assert ev2.feasible, ev2.violations


# ---------------------------------------------------------------- T05 货物保管
def test_t05_custody_wrong_truck_rejected(phys):
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.routes["t2"] = []
    plan.add_visit("t1", "c001", ground=["p001"])
    plan.add_visit("t2", "c002", ground=["p002"])
    state = initial_state(inst, phys)
    state.t0 = 1.0
    state.parcel_holder = {"p001": "TRUCK:t1", "p002": "TRUCK:t1"}
    state.truck_start_pos = {k: (0.0, 0.0) for k in ("t1", "t2", "t3", "t4", "t5")}
    state.truck_start_time = {k: 1.0 for k in state.truck_start_pos}
    state.truck_first_travel_s = {k: 0.0 for k in state.truck_start_pos}
    state.truck_ready_time = {k: 1.0 for k in state.truck_start_pos}
    state.truck_ac = {k: 4.0 for k in state.truck_start_pos}
    for d in range(1, 6):
        state.drone_energy[f"d{d}"] = phys.e_cap
    ev = evaluate_plan(plan, inst, phys, state)
    assert not ev.feasible
    assert any("G_CUSTODY" in x for x in ev.violations)


# ---------------------------------------------------------------- T08 运动连续
def test_t08_drive_time_matches_distance(phys):
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.add_visit("t1", "c002", ground=["p002"])
    plan.add_visit("t1", "c001", ground=[])
    state = initial_state(inst, phys)
    state.t0 = 100.0
    state.parcel_holder = {"p001": "DELIVERED", "p002": "TRUCK:t1"}
    state.delivered = {"p001"}
    state.truck_start_pos = {f"t{i+1}": (100.0, 0.0) for i in range(5)}
    state.truck_start_time = {f"t{i+1}": 100.0 for i in range(5)}
    state.truck_first_travel_s = {f"t{i+1}": 0.0 for i in range(5)}
    state.truck_ready_time = {f"t{i+1}": 100.0 for i in range(5)}
    state.truck_ac = {f"t{i+1}": 4.0 for i in range(5)}
    for d in range(1, 6):
        state.drone_energy[f"d{d}"] = phys.e_cap
    ev = evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    drives = [a for a in ev.timeline.actions if a.kind == "DRIVE" and a.actor == "t1"]
    assert drives, "必须存在真实行驶段"
    d0 = drives[0]
    assert abs((d0.end - d0.start) - 9900.0 / V) < 1e-3
    assert abs(d0.info["dist"] - 9900.0) < 1e-6
    assert tuple(d0.info["from"]) == (100.0, 0.0)


# ---------------------------------------------------------------- T09 充电等待
def test_t09_wait_for_charging_witness(phys):
    inst = make_instance(positions=[(500.0, 0.0), (1200.0, 0.0)])
    plan = Plan("TINY")
    plan.routes["t1"] = []
    v1 = plan.add_visit("t1", "c001", ground=["p001"])
    v2 = plan.add_visit("t1", "c001", ground=[])
    # d1 在 t1 上，初始 0.5 kWh；先飞 c002 再回 c001
    s = plan.add_sortie("d1", "t1", v1.vid, "STOP", 0.0, ["p002"], v2.vid)
    state = initial_state(inst, phys)
    state.drone_energy["d1"] = 0.5
    state.drone_start["d1"].energy = 0.5
    ev_no = evaluate_plan(plan, inst, phys, state, allow_wait_repair=False)
    ev_yes = evaluate_plan(plan, inst, phys, state, allow_wait_repair=True)
    assert ev_no.status == "ENERGY_INFEASIBLE"
    assert ev_yes.feasible, ev_yes.violations
    assert ev_yes.timeline.waits, "应通过合法停靠等待形成充电窗口"


# ---------------------------------------------------------------- T10 电费单位
def test_t10_charging_cost_units(phys):
    assert abs(phys.cost_vehicle_kwh - 0.731012 / (0.85 * 0.9)) < 1e-12
    qac = 2.0
    qnet = phys.slot_efficiency * qac
    assert abs(phys.cost_vehicle_kwh * qnet - 0.731012 / 0.85 * qac) < 1e-9


# ---------------------------------------------------------------- T12 预算
def test_t12_budget_hard_limit(phys):
    from tdr.alns import Budget
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.add_visit("t1", "c001", ground=["p001"])
    plan.add_visit("t1", "c002", ground=["p002"])
    state = initial_state(inst, phys)
    b = Budget(10, None)
    n = 0
    for _ in range(50):
        ev = evaluate_plan(plan, inst, phys, state, budget=b)
        if ev.status == "BUDGET_EXHAUSTED":
            break
        n += 1
    assert n == 10
    assert b.used == 10
    assert b.evals_left() == 0


# ---------------------------------------------------------------- T06 冻结边界
def test_t06_destroy_respects_inflight(phys):
    from tdr.alns import SolveContext, destroy
    from tdr.data import load_instance as _li
    pkg = json.loads((ROOT / "data" / "package.json").read_text(encoding="utf-8"))
    inst = _li(pkg, "C50")
    plan = res = None
    from tdr.nominal import build_nominal
    from tdr.simulate import derive_rngs
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    res = build_nominal(inst, phys, alg, derive_rngs(alg.base_algorithm_seed, "C50", "nominal", 0),
                        eval_budget=250)
    plan = res.plan
    # 把一个航次标记为 started，模拟在飞
    s = next(iter(plan.sorties.values()))
    s.started = True
    s.start_pos = (inst.depot_x, inst.depot_y)
    s.start_time = 0.0
    frozen = set(s.air) | set(s.handover)
    ctx = SolveContext(inst=inst, phys=phys, alg=alg, state=initial_state(inst, phys))
    import random as _r
    for op in ["RANDOM_DEPENDENCY", "RENDEZVOUS_RESOURCE", "ENERGY_CHAIN", "SUPPORT_VISIT",
               "SORTIE_REGROUP", "AFFECTED_SORTIE"]:
        trial = plan.clone()
        freed, used = destroy(trial, op, 5, _r.Random(7), inst, res.evaluation, ctx)
        assert not (set(freed) & frozen), (op, set(freed) & frozen)
        assert any(x.started for x in trial.sorties.values())


# ---------------------------------------------------------------- T14 状态门控
def test_t14_completed_verified_requires_replay(phys):
    pkg = json.loads((ROOT / "data" / "package.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    from tdr.hidden_world import TestWorld
    from tdr.nominal import build_nominal
    from tdr.simulate import derive_rngs, run_episode
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    res = build_nominal(inst, phys, alg, derive_rngs(alg.base_algorithm_seed, "C50", "nominal", 0),
                        eval_budget=250)
    H = max(res.evaluation.timeline.truck_finish.values()) + phys.shift_slack_s
    air = [p for s in res.plan.sorties.values() for p in s.air]
    ep = run_episode(inst, res.plan, res.evaluation, H, phys, TestWorld(inst, "C50", (air[0],)),
                     "S", alg, derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=120)
    if ep.status == "COMPLETED_VERIFIED":
        assert ep.replay is not None and ep.replay.ok
        assert ep.evaluation is not None and ep.evaluation.feasible
        # T13：全程重放成本必须与评价成本一致
        assert abs(ep.replay.cost - ep.evaluation.cost) < 1e-6


# ---------------------------------------------------------------- T15 输出原子性
def test_t15_outputs_rewritten_without_stale_files(phys, tmp_path):
    pkg = json.loads((ROOT / "data" / "package.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    from tdr.experiment import load_case_nominal, run_episode_dir
    nominal_dir = ROOT / "outputs" / "nominal2" / "C50"
    if not nominal_dir.exists():
        pytest.skip("run nominal first")
    plan, cost, H = load_case_nominal(inst, nominal_dir)
    out = tmp_path / "ep"
    out.mkdir()
    (out / "verification.json").write_text('{"ok": true, "cost": 1.234}', encoding="utf-8")
    run_episode_dir(inst, plan, cost, H, phys, AlgorithmConfig.from_dict(
        pkg["algorithm_protocol"]["default_parameters"]), 1, "S", out,
        recovery_eval_budget=60, make_figures=False)
    vt = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    assert vt.get("cost") != 1.234, "旧核验文件必须被清除后重写"


# ---------------------------------------------------------------- T07 机位
def test_t07_three_drones_on_two_slots_rejected(phys):
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    v1 = plan.add_visit("t1", "c001", ground=[])
    v2 = plan.add_visit("t1", "c002", ground=[])
    from tdr.plan import Sortie
    plan.sorties[1] = Sortie(1, "d2", "t1", None, "AIR", 0.0, ["p001"], v1.vid, [],
                             True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.sorties[2] = Sortie(2, "d3", "t1", None, "AIR", 0.0, ["p002"], v2.vid, [],
                             True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.drone_sorties = {"d2": [1], "d3": [2]}
    plan.next_sid = 3
    state = initial_state(inst, phys)
    state.drone_start["d2"].kind = "AIRBORNE"
    state.drone_start["d2"].truck = None
    state.drone_start["d2"].pos = (0.0, 0.0)
    state.drone_start["d3"].kind = "AIRBORNE"
    state.drone_start["d3"].truck = None
    state.drone_start["d3"].pos = (0.0, 0.0)
    ev = evaluate_plan(plan, inst, phys, state)
    assert not ev.feasible
    assert any("SLOT_OVER" in x for x in ev.violations), ev.violations


# ---------------------------------------------------------------- T11 两次失效
def test_t11_two_failures_full_replay(phys):
    pkg = json.loads((ROOT / "data" / "package.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    from tdr.hidden_world import TestWorld
    from tdr.simulate import derive_rngs, run_episode
    from tdr.experiment import load_case_nominal
    from tdr.evaluate import evaluate_plan
    from tdr.simulate import initial_run_state
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    nom_dir = ROOT / "outputs" / "nominal2" / "C50"
    if not nom_dir.exists():
        pytest.skip("run `python -m tdr nominal` first")
    plan, cost, H = load_case_nominal(inst, nom_dir)
    nom_ev = evaluate_plan(plan, inst, phys, initial_run_state(plan, inst, phys), H)
    res = type("R", (), {"plan": plan, "evaluation": nom_ev})()
    # 两张票在同一在飞航次里：失败服务删掉后，余下的票仍会飞到，第二次失效一定被观察到。
    # 排在后面另一航次上的票，恢复时可以改地送，不能用来要求“必须再观察一次”。
    targets = ("p017", "p029")
    ep = run_episode(inst, res.plan, res.evaluation, H, phys,
                     TestWorld(inst, "C50", targets),
                     "S", alg, derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
                     recovery_eval_budget=150)
    obs = [o.parcel_id for o in ep.observations if not o.air_delivery_available]
    assert sorted(obs) == sorted(targets), f"必须实际观察两次失效，实际 {obs}"
    assert ep.status == "COMPLETED_VERIFIED", (ep.status, ep.notes[:3])
    assert ep.replay is not None and ep.replay.ok
    assert len(ep.segments) >= 3, len(ep.segments)
    assert not any("_HOLDER" in v or "_ENERGY" in v or "_CARRIER" in v
                   for v in ep.replay.violations)


# ---------------------------------------------------------------- T02 异点回收货物
def test_t02_offsite_handover_delivered_at_true_customer(phys):
    inst = make_instance(positions=[(500.0, 0.0), (1500.0, 0.0)])
    from tdr.plan import Sortie
    plan = Plan("TINY")
    plan.routes["t1"] = []
    r = plan.add_visit("t1", "c002", ground=[])          # 在 c002 回收
    g = plan.add_visit("t1", "c001", ground=["p001"])    # 之后到 c001 真实地送
    plan.sorties[1] = Sortie(1, "d2", "t1", None, "AIR", 0.0, ["p002"], r.vid,
                             ["p001"], True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.drone_sorties = {"d2": [1]}
    plan.next_sid = 2
    state = initial_state(inst, phys)
    state.drone_start["d2"].kind = "AIRBORNE"
    state.drone_start["d2"].truck = None
    state.drone_start["d2"].pos = (0.0, 0.0)
    state.parcel_holder = {"p001": "DRONE:d2", "p002": "DRONE:d2"}
    ev = evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    # 在接机点 c002 直接交付 p001 必须被拒绝
    bad = plan.clone()
    bad.visits[g.vid].ground = []
    bad.visits[r.vid].ground = ["p001"]
    ev2 = evaluate_plan(bad, inst, phys, state)
    assert not ev2.feasible
    assert any("错址交付" in x for x in ev2.violations)


# ---------------------------------------------------------------- T03 同点恢复
def test_t03_same_site_recovery_legal(phys):
    inst = make_instance(positions=[(500.0, 0.0), (1500.0, 0.0)])
    from tdr.plan import Sortie
    plan = Plan("TINY")
    plan.routes["t1"] = []
    r = plan.add_visit("t1", "c001", ground=["p001"])   # 同点 R→U→G
    plan.sorties[1] = Sortie(1, "d2", "t1", None, "AIR", 0.0, ["p002"], r.vid,
                             ["p001"], True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.drone_sorties = {"d2": [1]}
    plan.next_sid = 2
    state = initial_state(inst, phys)
    state.drone_start["d2"].kind = "AIRBORNE"
    state.drone_start["d2"].truck = None
    state.drone_start["d2"].pos = (0.0, 0.0)
    state.parcel_holder = {"p001": "DRONE:d2", "p002": "DRONE:d2"}
    ev = evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations


# ---------------------------------------------------------------- T04 机体承运
def test_t04_drone_carrier_chain_rejected(phys):
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.routes["t2"] = []
    v1 = plan.add_visit("t1", "c001", ground=["p001"])
    v2 = plan.add_visit("t2", "c002", ground=["p002"])
    from tdr.plan import Sortie
    # d2 由 t1 回收后，又在 t2 放飞：缺少转移过程
    plan.sorties[1] = Sortie(1, "d2", "t1", None, "AIR", 0.0, ["p003"], v1.vid, [],
                             True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.sorties[2] = Sortie(2, "d2", "t2", v2.vid, "STOP", 0.0, ["p004"], v2.vid, [],
                             False, 0.0, None, 0, 0, "t2")
    plan.drone_sorties = {"d2": [1, 2]}
    plan.next_sid = 3
    inst3 = make_instance(n=2)
    errs = plan.validate_structure(inst3, phys)
    assert any("承运车" in e for e in errs), errs


# ---------------------------------------------------------------- T16 重放区间核验
def test_t16_replay_rejects_serving_before_arrival(phys):
    from tdr.replay import verify_replay
    inst = make_instance(positions=[(100.0, 0.0), (10000.0, 0.0)])
    base = {"t0": 0.0, "t1": 63.0,
            "start": {"holder": {"p001": "TRUCK:t1", "p002": "DELIVERED"},
                      "drone_carrier": {f"d{i}": f"t{i}" for i in range(1, 6)},
                      "energy": {f"d{i}": phys.e_cap for i in range(1, 6)},
                      "delivered": ["p002"],
                      "truck_pos": {f"t{i}": (0.0, 0.0) for i in range(1, 6)},
                      "truck_ac": {f"t{i}": 4.0 for i in range(1, 6)}, "dispatched": []},
            "actions": [
                {"kind": "DRIVE", "actor": "t1", "start": 0.0, "end": 12.0, "ref": "c001",
                 "from": [0.0, 0.0], "to": [100.0, 0.0], "dist": 100.0},
                {"kind": "G", "actor": "t1", "start": 1.0, "end": 51.0, "ref": "p001",
                 "customer": "c001"},
                {"kind": "DRIVE", "actor": "t1", "start": 51.0, "end": 63.0, "ref": "DEPOT",
                 "from": [100.0, 0.0], "to": [0.0, 0.0], "dist": 100.0}],
            "stages": []}
    r = verify_replay(inst, phys, [base])
    assert not r.ok
    assert any("G_WHILE_DRIVING" in x or "G_NOT_AT_CUSTOMER" in x for x in r.violations)
    legal = json.loads(json.dumps(base))
    legal["actions"][1]["start"] = 12.0
    legal["actions"][1]["end"] = 62.0
    legal["actions"][2]["start"] = 62.0
    legal["actions"][2]["end"] = 74.0
    legal["t1"] = 74.0
    r2 = verify_replay(inst, phys, [legal])
    assert r2.ok, r2.violations


# ---------------------------------------------------------------- T17 统一预算
def test_t17_local_reorder_charges_budget(phys):
    from tdr.alns import Budget, SearchStats
    from tdr.local_reorder import try_local_reorder
    from tdr.schedule import initial_state
    from tdr.plan import Sortie
    inst = make_instance()
    plan = Plan("TINY")
    plan.routes["t1"] = []
    v1 = plan.add_visit("t1", "c001", ground=["p001"])
    v2 = plan.add_visit("t1", "c002", ground=["p002"])
    # 同一访问两次回收，触发回收顺序重排候选
    plan.sorties[1] = Sortie(1, "d2", "t1", None, "AIR", 0.0, ["p003"], v1.vid, [],
                             True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.sorties[2] = Sortie(2, "d3", "t1", None, "AIR", 0.0, ["p004"], v1.vid, [],
                             True, 0.0, (0.0, 0.0), 0, 0, "t1")
    plan.drone_sorties = {"d2": [1], "d3": [2]}
    plan.next_sid = 3
    state = initial_state(inst, phys)
    for d in ("d2", "d3"):
        state.drone_start[d].kind = "AIRBORNE"
        state.drone_start[d].truck = None
        state.drone_start[d].pos = (0.0, 0.0)
    ctx = type("C", (), {"inst": inst, "phys": phys,
                         "alg": AlgorithmConfig(), "state": state, "H": None})()
    b = Budget(1, None)
    st = SearchStats()
    try_local_reorder(plan, None, ctx, st, b, 0)
    assert b.used <= 1, f"预算 1 次，实际使用 {b.used}"
