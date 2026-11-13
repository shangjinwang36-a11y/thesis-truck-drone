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
