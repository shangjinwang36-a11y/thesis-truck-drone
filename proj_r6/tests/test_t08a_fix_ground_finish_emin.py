"""T08a：低于 E_min 但能原地降落的残段仍须允许迁移接机并定价。"""
import dataclasses

import pytest

from tdr import ground_finish as gf
from test_t01_ground_finish_relocate import _parked_far_from_recovery


@pytest.mark.parametrize("energy", [0.025, 0.0])
def test_below_emin_can_relocate_to_land_in_place(energy):
    plan, state, inst, phys, horizon, frag = _parked_far_from_recovery()
    assert phys.e_min == pytest.approx(0.05)
    assert energy < phys.e_min
    state.drone_energy[frag.drone] = energy
    state.drone_start[frag.drone] = dataclasses.replace(state.drone_start[frag.drone], energy=energy)
    customer = next(c for c in inst.customers if (c.x, c.y) == frag.start_pos)

    # 原接机点不可达，但显式插入当前位置后，完整评价应允许降落收尾。
    old_cost, old_status = gf.ground_finish_cost(plan, state, inst, phys, horizon, relocate=False)
    assert old_cost is None and old_status.startswith("UNPRICED:"), old_status
    manual = plan.clone()
    visit = manual.add_visit(frag.launch_truck or frag.truck, customer.customer_id, pos=0, ground=[])
    manual.sorties[frag.sid].rec_vid = visit.vid
    landed, st, left = gf._build(manual, state, inst, phys, "truck", land=True)
    assert not left
    ev = gf._evaluate(landed, st, inst, phys, horizon)
    assert ev.feasible and ev.cost is not None, ev.violations
    recoveries = [(stage, ev.timeline.drone_energy[frag.drone][i + 1])
                  for i, stage in enumerate(ev.timeline.drone_stages[frag.drone])
                  if stage.kind == "R" and stage.sid == frag.sid]
    assert recoveries
    for stage, remaining in recoveries:
        assert stage.landed
        assert remaining == pytest.approx(energy)
    hover_cost, _ = gf._attempt(manual, state, inst, phys, horizon, "truck", land=False)
    assert hover_cost is None  # 同样电量不能通过悬停回收的 E_min 检查。

    assert customer.customer_id in gf._reachable_customers(plan, state, inst, phys, frag, k=8)
    cost, status = gf.ground_finish_cost(plan, state, inst, phys, horizon)
    assert cost is not None and 0.0 < cost <= ev.cost + 1e-9, status
    assert status.startswith("FEASIBLE:relocate:") and ":landed:" in status
