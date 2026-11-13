"""停止回合用卡车收尾，不计每客户罚金。完成率用精确 McNemar。"""
import json
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import plan_from_dict
from tdr.fairness import completion_table, fair_cost, mcnemar_exact
from tdr.ground_finish import ground_finish_cost
from tdr.schedule import DroneStart, initial_state

ROOT = Path(__file__).resolve().parents[1]


def _light(case):
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, case)
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), case)
    return inst, phys


def test_mcnemar_matches_the_binomial_on_discordant_pairs():
    from scipy.stats import binomtest
    got = mcnemar_exact(8, 2)
    assert got["n_discordant"] == 10
    assert got["p_two_sided"] == float(binomtest(8, 10, 0.5).pvalue)
    assert mcnemar_exact(0, 0)["p_two_sided"] is None


def test_holm_of_a_ten_to_zero_sign_test_is_six_times_the_raw_p():
    """C100 的 10/0：双侧精确符号检验是 binomtest(10, 10, 0.5)，Holm 乘上当时的 6 个检验。"""
    from scipy.stats import binomtest

    from tdr.attribution import holm
    raw = float(binomtest(10, 10, 0.5).pvalue)
    assert abs(raw - 0.001953125) < 1e-15
    adjusted = holm([raw, 0.021484375, 0.75390625, 0.75390625, 0.75390625, 1.0])
    assert abs(adjusted[0] - 6.0 * raw) < 1e-15
    assert abs(adjusted[0] - 0.01171875) < 1e-15


def test_completion_table_counts_discordant_stops():
    rows = []
    for i, (s, x) in enumerate((
        ("COMPLETED_VERIFIED", "COMPLETED_VERIFIED"),
        ("COMPLETED_VERIFIED", "STOPPED_NO_FEASIBLE_SUFFIX"),
        ("STOPPED_NO_FEASIBLE_SUFFIX", "COMPLETED_VERIFIED"),
        ("STOPPED_NO_FEASIBLE_SUFFIX", "STOPPED_NO_FEASIBLE_SUFFIX"),
    )):
        rows.append({
            "S": {"status": s, "cost": 10.0 if s.startswith("COMP") else None},
            "X": {"status": x, "cost": 12.0 if x.startswith("COMP") else None,
                  "ground_finish_cost": None if x.startswith("COMP") else 30.0},
        })
    table = completion_table(rows, "S", "X")
    assert table["both"] == 1
    assert table["only_left"] == 1
    assert table["only_right"] == 1
    assert table["neither"] == 1
    assert table["rate_left"] == 0.5
    assert table["mcnemar"]["n_discordant"] == 2
    assert fair_cost(rows[1]["S"]) == 10.0
    assert fair_cost(rows[1]["X"]) == 30.0
    assert fair_cost(rows[3]["S"]) is None


def test_ground_finish_uses_truck_delivery_and_overtime_not_a_penalty():
    inst, phys = _light("C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    state = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, state, None, "NOMINAL")
    assert base.feasible
    cost, status = ground_finish_cost(plan, state, inst, phys, base.timeline and max(base.timeline.truck_finish.values()))
    assert status == "FEASIBLE:truck"
    assert cost is not None and cost > 0
    # 班次设得很短时，收尾仍然可行，多出来的是加班工资，不是一笔按客户计的罚金。
    short, short_status = ground_finish_cost(plan, state, inst, phys, 1.0)
    assert short_status == "FEASIBLE:truck"
    assert short > cost


def test_hover_at_recovery_lands_only_after_the_three_modes_fail():
    """飞机已经在接机客户上空，电量不够悬停等车。前三种收尾因此不可行。
    降落等待只去掉这段悬停的电耗，票仍由卡车地面送达。已经可行的收尾不走这条。"""
    inst, phys = _light("C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    state = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, state, None, "NOMINAL")
    assert base.feasible
    plain, plain_status = ground_finish_cost(
        plan, state, inst, phys, max(base.timeline.truck_finish.values()))
    assert plain_status == "FEASIBLE:truck"

    sortie = next(s for s in plan.sorties.values() if s.rec_vid in plan.visits)
    rec = plan.visits[sortie.rec_vid]
    customer = inst.customer(rec.customer)
    parked = plan.clone()
    frag = parked.sorties[sortie.sid]
    frag.started = True
    frag.start_time = 0.0
    frag.start_pos = (customer.x, customer.y)
    frag.handover = list(dict.fromkeys(list(frag.air) + list(frag.handover)))
    frag.air = []
    frag.landed = False
    low = initial_state(inst, phys)
    low.drone_energy[frag.drone] = 0.01
    low.drone_start[frag.drone] = DroneStart(
        "AIRBORNE", None, 0.0, (customer.x, customer.y), 0.01, aboard=list(frag.handover))
    cost, status = ground_finish_cost(
        parked, low, inst, phys, max(base.timeline.truck_finish.values()))
    assert status == "FEASIBLE:truck:landed"
    assert cost is not None and cost > 0
    # 同一份计划、电量充足时仍由原来的卡车收尾定价，不改成降落。
    enough = initial_state(inst, phys)
    enough.drone_start[frag.drone] = DroneStart(
        "AIRBORNE", None, 0.0, (customer.x, customer.y), phys.e_cap, aboard=list(frag.handover))
    enough_cost, enough_status = ground_finish_cost(
        parked, enough, inst, phys, max(base.timeline.truck_finish.values()))
    assert enough_status == "FEASIBLE:truck"
    assert enough_cost is not None


def test_infeasible_return_is_priced_from_where_the_drone_stopped():
    """六种收尾都不改接机点，所以飞不回去时都拒绝给价。

    这之后才把接机点改到放飞车上、当前电量够得到的最近客户，并按最小绕行插入。
    原航程电量够的残段不改接机点。票都要落到某个地面访问上。
    """
    import math

    from tdr.ground_finish import _attempt, _build, _relocate_unreachable
    from tdr.recovery import _insert_support

    inst, phys = _light("C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    state = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, state, None, "NOMINAL")
    assert base.feasible
    horizon = max(base.timeline.truck_finish.values())
    sortie = next(s for s in plan.sorties.values() if s.rec_vid in plan.visits and s.air)
    rec = plan.visits[sortie.rec_vid]
    rec_customer = inst.customer(rec.customer)
    here = max(inst.customers, key=lambda c: math.hypot(c.x - rec_customer.x, c.y - rec_customer.y))
    assert here.customer_id != rec.customer
    parked = plan.clone()
    frag = parked.sorties[sortie.sid]
    frag.started = True
    frag.start_time = 0.0
    frag.start_pos = (here.x, here.y)
    frag.handover = list(dict.fromkeys(list(frag.air) + list(frag.handover)))
    mass = sum(inst.parcel_mass[p] for p in frag.handover)
    need = phys.fly_energy_kwh(math.hypot(rec_customer.x - here.x, rec_customer.y - here.y), mass)
    assert need > 0.05
    frag.air = []
    frag.landed = False
    frag.launch_truck = frag.launch_truck or frag.truck
    low = initial_state(inst, phys)
    low.drone_energy[frag.drone] = need * 0.5
    low.drone_start[frag.drone] = DroneStart(
        "AIRBORNE", None, 0.0, (here.x, here.y), need * 0.5, aboard=list(frag.handover))
    for land in (False, True):
        for mode in ("truck", "keep_inflight", "overtime_only"):
            missed, note = _attempt(parked, low, inst, phys, horizon, mode, land)
            assert missed is None, note
    cost, status = ground_finish_cost(parked, low, inst, phys, horizon)
    assert cost is not None, status
    assert status.startswith("FEASIBLE")
    moved = _relocate_unreachable(parked, low, inst, phys)
    assert moved is not None
    truck = frag.launch_truck
    route = moved.routes[truck]
    placed_vid = moved.sorties[frag.sid].rec_vid
    assert moved.visits[placed_vid].customer == here.customer_id
    assert moved.visits[placed_vid].truck == truck
    # 最小绕行的位置，不是一律接到路线末尾。
    fresh = parked.clone()
    inserted = _insert_support(fresh, inst, truck, here.customer_id, min_pos=0)
    assert route.index(placed_vid) == fresh.routes[truck].index(inserted)
    built, _, left = _build(moved, low, inst, phys, "truck", land=True)
    assert left == []
    placed = {p for v in built.visits.values() for p in v.ground}
    assert set(frag.handover) <= placed
    # 人已经在原定接机客户上空、电量够飞回时，六种收尾不改接机点。
    at_rec = plan.clone()
    stay = at_rec.sorties[sortie.sid]
    stay.started = True
    stay.start_time = 0.0
    stay.start_pos = (rec_customer.x, rec_customer.y)
    stay.handover = list(frag.handover)
    stay.air = []
    enough = initial_state(inst, phys)
    enough.drone_energy[stay.drone] = phys.e_cap
    enough.drone_start[stay.drone] = DroneStart(
        "AIRBORNE", None, 0.0, stay.start_pos, phys.e_cap, aboard=list(stay.handover))
    assert _relocate_unreachable(at_rec, enough, inst, phys) is None
    kept, _, _ = _build(at_rec, enough, inst, phys, "truck", land=False)
    assert kept.visits[kept.sorties[stay.sid].rec_vid].customer == rec.customer


def test_land_and_wait_pricing_is_identical_for_s_r_x_and_matches_stage_energy():
    """收尾函数没有策略参数。同一停点评三次，成本和状态相同。

    降落之后，等待和回收的电量为 0，回收时长仍是 recovery_s。
    飞到接机点的巡航电量照计。
    """
    import inspect

    from tdr.ground_finish import _build, _evaluate
    from tdr.schedule import DroneStage, stage_energy

    assert "strategy" not in inspect.signature(ground_finish_cost).parameters
    inst, phys = _light("C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    state = initial_state(inst, phys)
    base = evaluate_plan(plan, inst, phys, state, None, "NOMINAL")
    assert base.feasible
    horizon = max(base.timeline.truck_finish.values())
    sortie = next(s for s in plan.sorties.values() if s.rec_vid in plan.visits)
    rec = plan.visits[sortie.rec_vid]
    customer = inst.customer(rec.customer)
    parked = plan.clone()
    frag = parked.sorties[sortie.sid]
    frag.started = True
    frag.start_time = 0.0
    frag.start_pos = (customer.x, customer.y)
    frag.handover = list(dict.fromkeys(list(frag.air) + list(frag.handover)))
    frag.air = []
    frag.landed = False
    low = initial_state(inst, phys)
    low.drone_energy[frag.drone] = 0.01
    low.drone_start[frag.drone] = DroneStart(
        "AIRBORNE", None, 0.0, (customer.x, customer.y), 0.01, aboard=list(frag.handover))
    calls = [ground_finish_cost(parked, low, inst, phys, horizon) for _ in range(3)]
    assert calls[0] == calls[1] == calls[2]
    assert calls[0][1] == "FEASIBLE:truck:landed"
    assert calls[0][0] is not None and calls[0][0] > 0

    flown = parked.clone()
    piece = flown.sorties[sortie.sid]
    piece.start_pos = (customer.x + 800.0, customer.y)
    rich = initial_state(inst, phys)
    rich.drone_energy[piece.drone] = phys.e_cap
    rich.drone_start[piece.drone] = DroneStart(
        "AIRBORNE", None, 0.0, piece.start_pos, phys.e_cap, aboard=list(piece.handover))
    built, st, left = _build(flown, rich, inst, phys, "truck", land=True)
    assert left == []
    assert built.sorties[piece.sid].landed is True
    ev = _evaluate(built, st, inst, phys, horizon)
    assert ev.feasible, ev.violations[:4]
    stages = [s for s in ev.timeline.drone_stages[piece.drone] if s.sid == piece.sid]
    cruises = [s for s in stages if s.kind == "CRUISE" and s.dist > 0]
    recoveries = [s for s in stages if s.kind == "R"]
    assert cruises and recoveries
    assert all(stage_energy(s, phys) > 0 for s in cruises)
    for s in recoveries:
        assert s.landed
        assert abs((s.end - s.start) - phys.recovery_s) < 1e-6
        assert stage_energy(s, phys) == 0.0
    for s in stages:
        if s.kind == "WAIT":
            assert s.landed
            assert s.end >= s.start
            assert stage_energy(s, phys) == 0.0
    landed_wait = DroneStage("WAIT", 10.0, 40.0, mass=1.0, landed=True)
    hovering = DroneStage("WAIT", 10.0, 40.0, mass=1.0, landed=False)
    assert stage_energy(landed_wait, phys) == 0.0
    assert stage_energy(hovering, phys) > 0.0


def test_a_priced_ground_finish_has_placed_every_remaining_order():
    from tdr.data import Customer, Instance
    from tdr.ground_finish import _build, _covered
    from tdr.plan import Plan

    _, phys = _light("C50")
    phys.set_active()
    inst = Instance("GF", "T", 0.0, 0.0, (
        Customer("c1", "p1", 500.0, 0.0, 1.0),
        Customer("c2", "p2", 900.0, 100.0, 1.0),
    ))
    plan = Plan("GF")
    plan.add_visit("t1", "c1", ground=["p1"])
    state = initial_state(inst, phys)
    cost, status = ground_finish_cost(plan, state, inst, phys, 100000.0)
    assert cost is not None, status
    land = "landed" in status
    mode = "truck" if "truck" in status else ("keep_inflight" if "keep" in status else "overtime_only")
    built, _, left = _build(plan, state, inst, phys, mode, land=land)
    assert left == []
    assert {"p1", "p2"} <= _covered(built)


def test_unplaced_orders_are_not_given_a_ground_finish_cost(monkeypatch):
    import tdr.ground_finish as gf
    from tdr.data import Customer, Instance
    from tdr.plan import Plan

    _, phys = _light("C50")
    inst = Instance("GF", "T", 0.0, 0.0, (Customer("c1", "p1", 500.0, 0.0, 1.0),))
    plan = Plan("GF")
    plan.add_visit("t1", "c1", ground=["p1"])

    def leftover(plan_, state_, inst_, phys_, mode, land=False):
        return plan_, state_, ["p-still-out"]

    monkeypatch.setattr(gf, "_build", leftover)
    cost, status = gf.ground_finish_cost(plan, initial_state(inst, phys), inst, phys, 1.0)
    assert cost is None
    assert "UNPLACED" in status
