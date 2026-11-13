"""Round2：X 专属算子与 v7 开关默认关闭。"""
import json
from pathlib import Path

import pytest

from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan, is_cross_sortie
from tdr.experiment import build_case_nominal, load_case_nominal
from tdr.plan import Plan
from tdr.recovery import build_residual_candidate
from tdr.schedule import StartState, initial_state

ROOT = Path(__file__).resolve().parents[1]


def test_v7_and_x_flags_default_off():
    alg = AlgorithmConfig()
    phys = PhysicalConfig()
    assert phys.land_and_wait is False
    assert alg.joint_inflight_retarget is False
    assert alg.slot_aware_recovery is False
    assert alg.unlaunched_repair is False
    assert alg.x_improve_only_cross is False
    assert alg.x_adopt_s_nominal is False
    assert alg.x_preserve_cross_repair is False
    assert alg.x_keep_s_recovery is False
    assert alg.x_cross_hs_cap is False
    assert alg.x_cross_energy_margin_frac == 0.0
    assert alg.x_limit_new_air is False
    assert alg.x_new_air_penalty == 0.0
    assert alg.x_risk_price_air is False
    assert alg.failure_prob == 0.0


def test_x_nominal_from_s_improve_only_and_adopt(tmp_path):
    """两阶段 + 改进才接受的跨车 + 若 X>S 则采用 S：构造上 X 名义成本 ≤ S。"""
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    ad = dict(pkg["algorithm_protocol"]["default_parameters"])
    ad.update(x_improve_only_cross=True, x_adopt_s_nominal=True, nominal_two_phase_b=80)
    alg = AlgorithmConfig.from_dict(ad)
    ms = build_case_nominal(inst, phys, alg, tmp_path / "S", eval_budget=250, cross_launch=False, two_phase_b=80)
    mx = build_case_nominal(inst, phys, alg, tmp_path / "X", eval_budget=250, cross_launch=True, two_phase_b=80,
                            adopt_from=tmp_path / "S")
    assert ms["status"] == "FEASIBLE" and mx["status"] == "FEASIBLE"
    assert mx["cost"] <= ms["cost"] + 1e-9
    plan_s, _, _ = load_case_nominal(inst, tmp_path / "S")
    assert not any(is_cross_sortie(plan_s, s) for s in plan_s.sorties.values())


def test_preserve_cross_keeps_followon_when_rec_changes_to_its_launch_truck():
    """改回收车到后续航次的放飞车时，preserve_cross 应保留后续航次而不是丢掉。"""
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    inst = load_instance(pkg, "R50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "R50")
    plan, _, H = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "r6" / "X" / "R50_tp")
    # d4: 45 t2->t4, 52 t4->t4
    assert plan.sorties[45].drone == "d4" and plan.sorties[52].truck == "t4"
    s45 = plan.sorties[45]
    s45.started = True
    s45.start_pos = (0.0, 0.0)
    s45.mode = "AIR"
    st = initial_state(inst, phys)
    st.t0 = 1.0
    st.drone_start["d4"] = st.drone_start.get("d4") or type("D", (), {})()
    from tdr.schedule import DroneStart
    st.drone_start["d4"] = DroneStart("AIRBORNE", None, 1.0, (0.0, 0.0), phys.e_cap)
    st.drone_carrier["d4"] = "t2"
    # change rec of 45 to an existing t4 visit (52's launch)
    rec = plan.sorties[52].launch_vid
    entry = {"truck": "t4", "kind": "visit", "ref": rec, "support": False,
             "served": list(s45.air)}
    drop = build_residual_candidate(plan, 45, entry, inst, phys, st, set(), "X", preserve_cross=False)
    keep = build_residual_candidate(plan, 45, entry, inst, phys, st, set(), "X", preserve_cross=True)
    assert drop, "应至少构造出取消后续航次的候选"
    assert any(52 not in c.sorties for c in drop)
    assert keep and any(52 in c.sorties and c.sorties[52].truck == "t4" for c in keep)


def test_recovery_prefers_blocks_new_air_then_cost():
    """X 恢复比较：先比新开空送票数，再比成本。ceiling 为 None 时只比成本。"""
    from tdr.plan import Sortie
    from tdr.recovery import _recovery_prefers

    def _plan(air):
        p = Plan("T")
        p.routes["t1"] = []
        p.sorties[1] = Sortie(1, "d1", "t1", None, "ARC", 0.0, list(air), 0, [])
        return p

    class Ev:
        def __init__(self, cost, z=0.0):
            self.cost, self.z = cost, z

    ceiling = {"p1"}
    # 新开 p2 的方案即使更便宜也不应替换只飞 p1 的方案
    assert not _recovery_prefers(Ev(1.0), _plan(["p1", "p2"]), Ev(10.0), _plan(["p1"]), ceiling)
    assert _recovery_prefers(Ev(9.0), _plan(["p1"]), Ev(10.0), _plan(["p1"]), ceiling)
    # 两边都新开时回到成本
    assert _recovery_prefers(Ev(1.0), _plan(["p1", "p2"]), Ev(5.0), _plan(["p1", "p3"]), ceiling)
    # 旧行为：不看空送集合
    assert _recovery_prefers(Ev(1.0), _plan(["p1", "p2"]), Ev(10.0), _plan(["p1"]), None)
    # 惩罚 12：省下超过 12 元才允许多开一票；省 10 元不行
    assert _recovery_prefers(Ev(1.0), _plan(["p1", "p2"]), Ev(20.0), _plan(["p1"]), ceiling, 12.0)
    assert not _recovery_prefers(Ev(10.0), _plan(["p1", "p2"]), Ev(20.0), _plan(["p1"]), ceiling, 12.0)


def test_makespan_cap_rejects_longer_nominal():
    from tdr.alns import SolveContext, _within_makespan_cap
    from tdr.schedule import Timeline

    class Ev:
        def __init__(self, finish):
            self.timeline = Timeline(0.0)
            self.timeline.truck_finish = {"t1": finish}
            self.feasible = True

    ctx = SolveContext(inst=None, phys=PhysicalConfig(), alg=AlgorithmConfig(),
                       state=None, mode="nominal", makespan_cap=1000.0)
    assert _within_makespan_cap(Ev(1000.0), ctx)
    assert not _within_makespan_cap(Ev(1000.1), ctx)
    ctx.mode = "recovery"
    assert _within_makespan_cap(Ev(5000.0), ctx)


def test_replay_landed_wait_and_recovery_skip_reserve():
    """降落等待的 WAIT/R 不扣悬停能量，R 动作不要求 E_min。未标 landed 的同样段仍扣、仍查备用电量。"""
    from tdr.data import Customer, Instance
    from tdr.replay import verify_replay

    phys = PhysicalConfig()
    inst = Instance("TINY", "T", 0.0, 0.0, (Customer("c001", "p001", 0.0, 0.0, 1.0),))
    e0 = phys.e_min * 0.4
    trucks = {f"t{i}": (0.0, 0.0) for i in range(1, 6)}
    drones = {f"d{i}": phys.e_cap for i in range(1, 6)}
    drones["d1"] = e0
    carriers = {f"d{i}": f"t{i}" for i in range(1, 6)}

    def seg(landed):
        return {"t0": 0.0, "t1": phys.recovery_s,
                "start": {"holder": {"p001": "DELIVERED"},
                          "drone_carrier": dict(carriers),
                          "energy": dict(drones),
                          "delivered": ["p001"],
                          "truck_pos": {k: list(v) for k, v in trucks.items()},
                          "truck_ac": {f"t{i}": 4.0 for i in range(1, 6)},
                          "dispatched": ["d1"]},
                "actions": [
                    {"kind": "R", "actor": "t1", "start": 0.0, "end": phys.recovery_s,
                     "ref": "S1", "drone": "d1", "customer": "c001", "landed": landed,
                     "partial": False},
                ],
                "stages": [
                    {"kind": "WAIT", "drone": "d1", "start": 0.0, "end": 20.0,
                     "mass": 0.0, "landed": landed},
                    {"kind": "R", "drone": "d1", "start": 20.0, "end": phys.recovery_s,
                     "mass": 0.0, "landed": landed},
                ]}

    landed = verify_replay(inst, phys, [seg(True)])
    assert not any(x.startswith("R_RESERVE") for x in landed.violations), landed.violations
    assert abs(landed.e_return["d1"] - e0) < 1e-9
    hovering = verify_replay(inst, phys, [seg(False)])
    assert any(x.startswith("R_RESERVE") for x in hovering.violations), hovering.violations
    assert hovering.e_return["d1"] < e0 - 1e-6


def test_risk_adjusted_proxy_uses_known_p_and_skips_ceiling_and_s():
    """期望失败代价 = p × (地面代理 + 一次回收工资)。残差里已有的票、以及 p=0，都不加价。"""
    from tdr.moves import _risk_adjusted_air_proxy
    phys = PhysicalConfig()
    st = StartState()
    st.x_failure_p = 0.2
    st.air_ceiling = set()
    overhead = phys.wage_per_s * phys.recovery_s
    assert _risk_adjusted_air_proxy(1.0, "p1", 10.0, st, phys) == pytest.approx(1.0 + 0.2 * (10.0 + overhead))
    st.air_ceiling = {"p1"}
    assert _risk_adjusted_air_proxy(1.0, "p1", 10.0, st, phys) == 1.0
    st.x_failure_p = 0.0
    st.air_ceiling = set()
    assert _risk_adjusted_air_proxy(1.0, "p1", 10.0, st, phys) == 1.0
    assert _risk_adjusted_air_proxy(1.0, "p1", 10.0, None, phys) == 1.0


def test_risk_price_accepts_new_air_only_when_saving_covers_expected_failure():
    """词典序仍会否决任何新开空送；风险价只在真实节省超过该票期望失败代价时才接受。"""
    from tdr.moves import new_air_risk_charge
    from tdr.plan import Sortie
    from tdr.recovery import _recovery_prefers
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    st = initial_state(inst, phys)

    def _plan(air):
        p = Plan("T")
        p.routes["t1"] = []
        p.sorties[1] = Sortie(1, "d1", "t1", None, "ARC", 0.0, list(air), 0, [])
        return p

    class Ev:
        def __init__(self, cost, z=0.0):
            self.cost, self.z = cost, z

    ceiling = {"p001"}
    base, extra = _plan(["p001"]), _plan(["p001", "p002"])
    ch = new_air_risk_charge(extra, inst, phys, {"p002"}, 0.2, st, None)
    assert ch > 0
    kw = dict(risk_p=0.2, inst=inst, phys=phys, state=st)
    assert not _recovery_prefers(Ev(100 - 0.5 * ch), extra, Ev(100), base, ceiling, **kw)
    assert _recovery_prefers(Ev(100 - ch - 1.0), extra, Ev(100), base, ceiling, **kw)
    assert not _recovery_prefers(Ev(1.0), extra, Ev(100), base, ceiling)


def test_refly_operator_is_x_only():
    from tdr.alns import SolveContext
    from tdr.refly import propose
    alg = AlgorithmConfig(x_risk_price_air=True, failure_prob=0.2)
    ctx = SolveContext(inst=None, phys=PhysicalConfig(), alg=alg, state=StartState(),
                       mode="recovery", strategy="S")
    assert propose(Plan("T"), ctx) == []
    ctx.strategy = "X"
    ctx.alg = AlgorithmConfig()
    assert propose(Plan("T"), ctx) == []


def test_drop_broken_chain_tail_frees_mismatched_sortie():
    """无人机实际在 t2，修复器却从 t3 放飞：拆掉该航次，票交回地面，而不是整份候选结构失败。"""
    from tdr.recovery import drop_broken_chain_tails
    from tdr.schedule import DroneStart
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    plan = Plan("T")
    plan.routes["t2"] = []
    plan.routes["t3"] = []
    v = plan.add_visit("t3", "c001")
    plan.add_sortie("d1", "t3", v.vid, "STOP", 0.0, ["p001"], v.vid)
    st = initial_state(inst, phys)
    st.t0 = 10.0
    st.drone_start["d1"] = DroneStart("ON_TRUCK", "t2", 10.0, (0.0, 0.0), phys.e_cap)
    st.drone_carrier["d1"] = "t2"
    freed = drop_broken_chain_tails(plan, st)
    assert freed == ["p001"]
    assert plan.sorties == {}


def test_preserve_cross_keeps_second_followon_on_previous_recovery_truck():
    """改接机车时只改紧邻的后续航次；再下一趟仍从上一趟的回收车放飞，不能整链改到同一辆车。"""
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    inst = load_instance(pkg, "R50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "R50")
    plan, _, _ = load_case_nominal(inst, ROOT / "tests" / "fixtures" / "r6" / "X" / "R50_tp")
    s45, s52 = plan.sorties[45], plan.sorties[52]
    assert s52.drone == s45.drone
    rec_truck = plan.visits[s52.rec_vid].truck
    launch = s52.rec_vid
    extra_v = plan.add_visit(rec_truck, plan.visits[launch].customer)
    later = [extra_v.vid]
    # 借一票还没进这条链的地面票，做成第三趟：从 52 的回收车放飞
    donor = None
    for v in plan.visits.values():
        if v.ground:
            donor = v.ground.pop()
            break
    assert donor is not None
    plan.add_sortie(s45.drone, rec_truck, launch, "STOP", 0.0, [donor], later[0])
    s45.started = True
    s45.start_pos = (0.0, 0.0)
    s45.mode = "AIR"
    # 把 45 的回收改到一辆不是 rec_truck 的车上
    other = next(t for t in plan.routes if t != rec_truck and plan.routes[t])
    new_rec = plan.routes[other][0]
    from tdr.schedule import DroneStart
    st = initial_state(inst, phys)
    st.t0 = 1.0
    st.drone_start[s45.drone] = DroneStart("AIRBORNE", None, 1.0, (0.0, 0.0), phys.e_cap)
    st.drone_carrier[s45.drone] = s45.truck or "t2"
    entry = {"truck": other, "kind": "visit", "ref": new_rec, "support": False, "served": list(s45.air)}
    keep = build_residual_candidate(plan, 45, entry, inst, phys, st, set(), "X", preserve_cross=True)
    assert keep, "preserve_cross 应给出候选"
    ok = False
    for c in keep:
        chain = [c.sorties[s] for s in c.drone_sorties.get(s45.drone, []) if s in c.sorties and not c.sorties[s].started]
        if len(chain) < 2:
            continue
        first, second = chain[0], chain[1]
        if first.truck == other and second.truck == rec_truck:
            errs = c.validate_structure(inst, phys, initial_carrier={s45.drone: other})
            assert not any("不符" in e for e in errs), errs
            ok = True
            break
    assert ok, "第二趟后续航次应留在上一趟的回收车上"
