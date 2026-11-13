"""第 9 轮：会合访问只在 X 上产生跨车；S 的近邻破坏留在同一辆车；S 不接受更贵的真实成本。"""
import json
from pathlib import Path

from tdr.alns import SolveContext
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.evaluate import is_cross_sortie
from tdr.nominal import s_true_cost_keeps_phase1
from tdr.plan import Plan
from tdr.schedule import initial_state
from tdr.expected_cost import expected_j, same_truck_j_adopts_baseline
from tdr.moves import air_energy, sortie_start
from tdr.support_nominal import joint_near_seeds, propose_support_rendezvous

ROOT = Path(__file__).resolve().parents[1]


def _tiny():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    phys.set_active()
    inst = Instance("TINY", "T", 0.0, 0.0, (
        Customer("c001", "p001", 400.0, 0.0, 1.0),
        Customer("c002", "p002", 700.0, 0.0, 1.0),
        Customer("c003", "p003", 1200.0, 0.0, 1.0),
        Customer("c004", "p004", 800.0, 600.0, 1.0),
        Customer("c005", "p005", 750.0, 150.0, 1.0),
    ))
    plan = Plan("TINY")
    plan.routes["t1"] = []
    plan.routes["t2"] = []
    launch = plan.add_visit("t1", "c001", ground=["p001"])
    plan.add_visit("t1", "c003", ground=["p003"])
    plan.add_visit("t1", "c005", ground=["p005"])
    plan.add_visit("t2", "c004", ground=["p004"])
    plan.add_sortie("d1", "t1", launch.vid, "ARC", 0.5, ["p002"], plan.routes["t1"][1])
    return inst, phys, plan


def _parcels(plan):
    got = [p for v in plan.visits.values() for p in v.ground]
    got += [p for s in plan.sorties.values() for p in s.air]
    return sorted(got)


def test_x_inserts_a_cross_rendezvous_and_s_stays_on_one_truck():
    inst, phys, plan = _tiny()
    alg = AlgorithmConfig(cross_n=2)
    state = initial_state(inst, phys)
    ctx = SolveContext(inst, phys, alg, state, None, "nominal")
    before = _parcels(plan)
    from tdr.support_nominal import rendezvous_candidates
    end = inst.customer("c002")
    legal = rendezvous_candidates(plan, inst, "t2", (end.x, end.y), {"c002"})
    assert 1 <= len(legal) <= 10
    assert all(customer in {c.customer_id for c in inst.customers} for customer in legal)
    cross = propose_support_rendezvous(plan, ctx, 1, set(), True)
    assert cross
    _, cand = cross[0]
    crossed = [s for s in cand.sorties.values() if is_cross_sortie(cand, s)]
    assert len(crossed) == 1
    rec = cand.visits[crossed[0].rec_vid]
    assert rec.truck != cand.visits[crossed[0].launch_vid].truck
    assert rec.customer in legal
    assert rec.customer not in {inst.parcel_to_customer[p] for p in crossed[0].air}
    if rec.vid not in plan.visits:
        assert rec.ground == []
    assert _parcels(cand) == before

    same = propose_support_rendezvous(plan, ctx, 2, set(), False)
    assert same
    for _, cand_s in same:
        assert not any(is_cross_sortie(cand_s, s) for s in cand_s.sorties.values())
        assert _parcels(cand_s) == before


def test_joint_near_uses_two_trucks_only_when_cross_is_allowed():
    inst, _, plan = _tiny()
    same = joint_near_seeds(plan, inst, False)
    cross = joint_near_seeds(plan, inst, True)

    def trucks(seeds):
        found = set()
        for p in seeds:
            for v in plan.visits.values():
                if p in v.ground:
                    found.add(v.truck)
        return found

    assert trucks(same) == {"t1"}
    assert trucks(cross) == {"t1", "t2"}


def test_s_phase1_does_not_take_the_new_same_truck_operators():
    from tdr.nominal import same_truck_phase1_unchanged
    assert same_truck_phase1_unchanged(False, False)
    assert not same_truck_phase1_unchanged(False, True)
    assert not same_truck_phase1_unchanged(True, False)


def test_s_true_cost_floor_does_not_apply_to_x():
    assert s_true_cost_keeps_phase1(False, True, 100.0, 110.0, 1e-4)
    assert not s_true_cost_keeps_phase1(False, True, 110.0, 100.0, 1e-4)
    assert not s_true_cost_keeps_phase1(True, True, 100.0, 110.0, 1e-4)
    assert not s_true_cost_keeps_phase1(False, False, 100.0, 110.0, 1e-4)


def test_new_flags_default_off():
    alg = AlgorithmConfig()
    assert alg.support_rendezvous is False
    assert alg.joint_near_destroy is False
    assert alg.pair_handoff is False
    assert alg.s_keep_true_cost is False
    assert alg.convert_polish_n == 0
    assert alg.x_s_second_start is False
    assert alg.scenario_eval_cap == 0
    assert alg.scenario_screen_yuan == 0.0
    assert alg.scenario_elite_refill is False
    assert alg.expected_accept is False
    assert alg.expected_reeval_every == 80
    assert alg.x_short_return is False
    assert alg.x_same_truck_j_gate is False
    assert "JOINT_NEAR" not in alg.destroy_operators


def test_scenario_screen_and_phase2_budget_split():
    from tdr.scenario_eval import phase2_slices, scenario_budget_for, screen_skips_scenario
    from tdr.alns import Budget
    assert screen_skips_scenario(30.0, 0.0, 20.0)
    assert not screen_skips_scenario(10.0, 0.0, 20.0)
    assert not screen_skips_scenario(30.0, 0.0, 0.0)
    assert phase2_slices(200) == (100, 100)
    assert phase2_slices(5) == (2, 3)
    assert phase2_slices(1) == (1, 0)
    assert sum(phase2_slices(7)) == 7
    alg = AlgorithmConfig(scenario_eval_cap=3)
    shared = Budget(10, None)
    x_budget = scenario_budget_for(alg, "C100", True, shared)
    s_budget = scenario_budget_for(alg, "C100", False, shared)
    assert x_budget is not s_budget
    assert x_budget is scenario_budget_for(alg, "C100", True, shared)
    assert x_budget.eval_limit == 3 and x_budget.scenario_ledger
    plain = AlgorithmConfig()
    assert scenario_budget_for(plain, "C100", True, shared) is shared


def test_support_launch_inserts_a_visit_the_receiver_did_not_have():
    from tdr.moves import apply_air, cross_air_candidates
    inst, phys, plan = _tiny()
    off = cross_air_candidates(plan, inst, phys, "p003", allow_support=False)
    assert all(c.support_customer is None for c in off)
    on = cross_air_candidates(plan.clone(), inst, phys, "p003", allow_support=True)
    support = [c for c in on if c.support_customer]
    assert support
    cand = support[0]
    owned = {plan.visits[v].customer for v in plan.routes[cand.rec_truck]}
    assert cand.support_customer not in owned
    assert cand.support_customer != "c003"
    before = len(plan.routes[cand.rec_truck])
    assert apply_air(plan, inst, "p003", cand, phys)
    customers = {plan.visits[v].customer for v in plan.routes[cand.rec_truck]}
    assert cand.support_customer in customers
    assert len(plan.routes[cand.rec_truck]) == before + 1


def _geom(name, customers):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    phys.set_active()
    inst = Instance(name, "T", 0.0, 0.0, customers)
    return inst, phys


def _ctx(inst, phys, short_return: bool):
    alg = AlgorithmConfig(x_short_return=short_return, cross_n=2)
    return SolveContext(inst, phys, alg, initial_state(inst, phys), None, "nominal")


def _split_plan():
    """整段回到接机车超电，只飞靠近接机弧的前缀则不超。电池仍是数据包里的 0.5 kWh。"""
    inst, phys = _geom("SPLIT", (
        Customer("cL", "pL", 500.0, 0.0, 1.0),
        Customer("cA", "pA", 2000.0, 0.0, 1.0),
        Customer("cB", "pB", 18000.0, 0.0, 1.0),
        Customer("cFar", "pF", 19000.0, 0.0, 1.0),
        Customer("cMeet", "pM", 2200.0, 100.0, 1.0),
        Customer("cAlso", "pAlso", 2500.0, 0.0, 1.0),
    ))
    plan = Plan("SPLIT")
    launch = plan.add_visit("t1", "cL", ground=["pL"])
    far = plan.add_visit("t1", "cFar", ground=["pF"])
    plan.add_visit("t2", "cMeet", ground=["pM"])
    plan.add_visit("t2", "cAlso", ground=["pAlso"])
    plan.add_sortie("d1", "t1", launch.vid, "ARC", 0.0, ["pA", "pB"], far.vid)
    return inst, phys, plan


def _reselect_plan():
    """早放飞超电，晚放飞不超。晚放飞必须晚于上一航次的回收。"""
    inst, phys = _geom("LAUNCH", (
        Customer("cBefore", "pBefore", -20000.0, 0.0, 1.0),
        Customer("cPrev", "pP", -16000.0, 0.0, 1.0),
        Customer("cEarly", "pE", -15000.0, 0.0, 1.0),
        Customer("cLate", "pLate", 1500.0, 0.0, 1.0),
        Customer("cRec", "pRec", 19000.0, 0.0, 1.0),
        Customer("cA", "pA", 2000.0, 0.0, 1.0),
        Customer("cMeet", "pM", 2200.0, 100.0, 1.0),
    ))
    plan = Plan("LAUNCH")
    before = plan.add_visit("t1", "cBefore", ground=["pBefore"])
    prev = plan.add_visit("t1", "cPrev", ground=[])
    early = plan.add_visit("t1", "cEarly", ground=["pE"])
    plan.add_visit("t1", "cLate", ground=["pLate"])
    rec = plan.add_visit("t1", "cRec", ground=["pRec"])
    plan.add_visit("t2", "cMeet", ground=["pM"])
    plan.add_sortie("d1", "t1", before.vid, "ARC", 0.0, ["pP"], prev.vid)
    plan.add_sortie("d1", "t1", early.vid, "ARC", 0.0, ["pA"], rec.vid)
    return inst, phys, plan


def _energy(inst, phys, plan, sortie):
    rec = plan.visits[sortie.rec_vid]
    cust = inst.customer(rec.customer)
    return air_energy(inst, phys, sortie_start(inst, plan, sortie), list(sortie.air), (cust.x, cust.y))


def test_short_return_splits_a_leg_onto_the_nearer_arc_customer():
    inst, phys, plan = _split_plan()
    assert phys.battery_kwh == 0.5
    limit = phys.e_cap - phys.e_min
    full = plan.sorties[plan.drone_sorties["d1"][-1]]
    meet = inst.customer("cMeet")
    assert air_energy(inst, phys, sortie_start(inst, plan, full), list(full.air), (meet.x, meet.y)) > limit
    before = _parcels(plan)
    ctx = _ctx(inst, phys, True)
    got = propose_support_rendezvous(plan, ctx, 1, set(), True)
    assert got
    _, cand = got[0]
    crossed = [s for s in cand.sorties.values() if is_cross_sortie(cand, s)]
    assert len(crossed) == 1
    flown = crossed[0]
    assert flown.air == ["pA"]
    rec = cand.visits[flown.rec_vid]
    assert rec.customer == "cMeet"
    assert rec.customer not in {inst.parcel_to_customer[p] for p in flown.air}
    assert rec.customer in {c.customer_id for c in inst.customers}
    assert _energy(inst, phys, cand, flown) <= limit + phys.energy_tol
    end = inst.customer("cA")
    new_return = ((inst.customer(rec.customer).x - end.x) ** 2 + (inst.customer(rec.customer).y - end.y) ** 2) ** 0.5
    old_return = ((inst.customer("cFar").x - end.x) ** 2 + (inst.customer("cFar").y - end.y) ** 2) ** 0.5
    assert new_return < old_return
    assert "pB" in [p for v in cand.visits.values() for p in v.ground]
    assert _parcels(cand) == before
    # 关掉几何、或只允许同车时，不把这段拆到另一辆车上。
    same_air = propose_support_rendezvous(plan, _ctx(inst, phys, False), 2, set(), True)
    assert all(list(s.air) == ["pA", "pB"] for _, alt in same_air for s in alt.sorties.values() if s.air)
    for _, alt in propose_support_rendezvous(plan, _ctx(inst, phys, True), 2, set(), False):
        assert not any(is_cross_sortie(alt, s) for s in alt.sorties.values())
        assert all(len(s.air) == 2 for s in alt.sorties.values() if s.drone == "d1" and s.air)


def test_short_return_reselects_a_later_launch_without_passing_the_previous_recovery():
    inst, phys, plan = _reselect_plan()
    limit = phys.e_cap - phys.e_min
    tail = plan.sorties[plan.drone_sorties["d1"][-1]]
    meet = inst.customer("cMeet")
    early = next(v for v in plan.visits.values() if v.customer == "cEarly")
    late = next(v for v in plan.visits.values() if v.customer == "cLate")
    assert air_energy(inst, phys, (inst.customer("cEarly").x, inst.customer("cEarly").y),
                      ["pA"], (meet.x, meet.y)) > limit
    assert air_energy(inst, phys, (inst.customer("cLate").x, inst.customer("cLate").y),
                      ["pA"], (meet.x, meet.y)) <= limit
    before = _parcels(plan)
    got = propose_support_rendezvous(plan, _ctx(inst, phys, True), 1, set(), True)
    assert got
    _, cand = got[0]
    flown = next(s for s in cand.sorties.values() if is_cross_sortie(cand, s))
    assert flown.air == ["pA"]
    assert cand.visits[flown.launch_vid].customer == "cLate"
    route = cand.routes["t1"]
    prev = next(v.vid for v in cand.visits.values() if v.customer == "cPrev")
    assert route.index(flown.launch_vid) >= route.index(prev)
    assert cand.visits[flown.launch_vid].vid != early.vid
    assert _energy(inst, phys, cand, flown) <= limit + phys.energy_tol
    assert _parcels(cand) == before
    assert late.customer == "cLate"


def test_same_truck_j_gate_drops_extra_air_and_keeps_a_cross():
    inst, phys, base = _tiny()
    other = base.clone()
    for visit in other.visits.values():
        if "p003" in visit.ground:
            visit.ground.remove("p003")
    extra = next(iter(other.sorties.values()))
    extra.air.append("p003")
    assert expected_j(100.0, other, inst, phys, 0.2) > expected_j(100.0, base, inst, phys, 0.2)
    assert same_truck_j_adopts_baseline(other, 100.0, base, 100.0, inst, phys, 0.2, 1e-4, None, None)
    # 没有跨车时，两次情景样本更低也不推翻 J。
    assert same_truck_j_adopts_baseline(other, 100.0, base, 100.0, inst, phys, 0.2, 1e-4, 90.0, 100.0)
    # J 本身更好时不退回。
    assert not same_truck_j_adopts_baseline(other, 0.0, base, 100.0, inst, phys, 0.2, 1e-4, None, None)
    crossed = other.clone()
    rec = next(v.vid for v in crossed.visits.values() if v.truck == "t2")
    next(iter(crossed.sorties.values())).rec_vid = rec
    assert any(is_cross_sortie(crossed, s) for s in crossed.sorties.values())
    assert not same_truck_j_adopts_baseline(crossed, 100.0, base, 100.0, inst, phys, 0.2, 1e-4, None, None)
