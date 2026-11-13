"""T01：在飞机带货、飞不到原接机点时，应急收尾可以把接机点挪到放飞车上够得着的客户点。

复现 RC100 种子 1002 的结构：电量为正，但到原接机点的巡航会把电量打成负。
旧收尾六种都只保留原接机点，全部 SWAP_CANNOT_FIX；新收尾在放飞车上找到合法会合。
只用放飞车，所以对 S、R、X 一样合法；函数仍然没有策略参数。
"""
import inspect
import json
import math
from pathlib import Path

from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
from tdr.experiment import plan_from_dict
from tdr.ground_finish import ground_finish_cost
from tdr.schedule import DroneStart, initial_state

ROOT = Path(__file__).resolve().parents[1]


def _parked_far_from_recovery():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig.from_dict(pkg["config"]).for_case(pkg.get("case_fleet"), "C50")
    raw = json.loads((ROOT / "r6/results/round3/R3/nominal/S/C50/nominal_plan.json").read_text())
    plan = plan_from_dict(raw["plan"])
    base = evaluate_plan(plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    assert base.feasible
    horizon = max(base.timeline.truck_finish.values())
    sortie = next(s for s in plan.sorties.values() if s.rec_vid in plan.visits and s.air)
    rec = inst.customer(plan.visits[sortie.rec_vid].customer)
    # 无人机停在离原接机点最远的客户上空（失败点），带着票。
    far = max(inst.customers, key=lambda c: math.hypot(c.x - rec.x, c.y - rec.y))
    parked = plan.clone()
    frag = parked.sorties[sortie.sid]
    frag.started = True
    frag.start_time = 0.0
    frag.start_pos = (far.x, far.y)
    frag.handover = list(dict.fromkeys(list(frag.air) + list(frag.handover)))
    frag.air = []
    frag.landed = False
    mass = sum(inst.parcel_mass[p] for p in frag.handover)
    need = phys.fly_energy_kwh(math.hypot(far.x - rec.x, far.y - rec.y), mass)
    e0 = 0.5 * need                       # 电量为正，但只够飞到原接机点的一半
    st = initial_state(inst, phys)
    st.drone_energy[frag.drone] = e0
    st.drone_start[frag.drone] = DroneStart("AIRBORNE", None, 0.0, (far.x, far.y), e0,
                                            aboard=list(frag.handover))
    return parked, st, inst, phys, horizon, frag


def test_old_finish_misses_a_legal_rendezvous_and_new_one_finds_it_on_the_launch_truck():
    parked, st, inst, phys, horizon, frag = _parked_far_from_recovery()
    old_cost, old_status = ground_finish_cost(parked, st, inst, phys, horizon, relocate=False)
    assert old_cost is None
    assert "SWAP_CANNOT_FIX" in old_status
    cost, status = ground_finish_cost(parked, st, inst, phys, horizon)
    assert cost is not None and cost > 0, status
    assert status.startswith("FEASIBLE:relocate:")
    launch = frag.launch_truck or frag.truck
    assert status.endswith(f"@{launch}#" + status.rsplit("#", 1)[1])   # 只在放飞车上会合（S 资格）


def test_relocation_is_strategy_free_and_deterministic():
    assert "strategy" not in inspect.signature(ground_finish_cost).parameters
    parked, st, inst, phys, horizon, _ = _parked_far_from_recovery()
    calls = [ground_finish_cost(parked, st, inst, phys, horizon) for _ in range(3)]
    assert calls[0] == calls[1] == calls[2]


def test_swap_message_names_the_stage_and_its_end_time():
    parked, st, inst, phys, horizon, frag = _parked_far_from_recovery()
    import dataclasses
    from tdr.ground_finish import _build
    built, st2, left = _build(parked, st, inst, phys, "truck")
    ev = evaluate_plan(built, inst, dataclasses.replace(phys, soft_h=True, reserve_fraction=0.0),
                       st2, horizon, "T01")
    msg = next(v for v in ev.violations if v.startswith("SWAP_CANNOT_FIX"))
    assert ":stage=CRUISE:end=" in msg
