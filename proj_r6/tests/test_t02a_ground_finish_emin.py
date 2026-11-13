"""T02-A：非降落回收遵守 E_min（0.05 kWh），降落只需非负；全部不可行时明确标成 UNPRICED。
收尾函数仍没有策略参数，S/R/X 同一路径。"""
import dataclasses
import math

import pytest

from tdr import ground_finish as gf
from test_t01_ground_finish_relocate import _parked_far_from_recovery


def test_finish_prices_with_true_emin(monkeypatch):
    parked, st, inst, phys, horizon, _ = _parked_far_from_recovery()
    seen = []
    real = gf.evaluate_plan

    def spy(plan, inst_, phys_, state, H, reason, *a, **kw):
        seen.append(phys_.e_min)
        return real(plan, inst_, phys_, state, H, reason, *a, **kw)

    monkeypatch.setattr(gf, "evaluate_plan", spy)
    gf.ground_finish_cost(parked, st, inst, phys, horizon)
    assert seen and all(abs(e - phys.e_min) < 1e-12 for e in seen)
    assert phys.e_min > 0.0


@pytest.mark.parametrize("full_battery", [False, True])
def test_priced_finish_keeps_non_landed_recovery_at_or_above_emin(monkeypatch, full_battery):
    parked, st, inst, phys, horizon, frag = _parked_far_from_recovery()
    if full_battery:
        st.drone_energy[frag.drone] = phys.e_cap
        st.drone_start[frag.drone] = dataclasses.replace(st.drone_start[frag.drone], energy=phys.e_cap)
    real = gf._evaluate
    checked = []
    hovering = []

    def check_recovery(plan, state, inst_, phys_, H):
        ev = real(plan, state, inst_, phys_, H)
        if ev.feasible:
            for drone, stages in ev.timeline.drone_stages.items():
                energies = ev.timeline.drone_energy[drone]
                for i, stage in enumerate(stages):
                    if stage.kind == "R":
                        required = 0.0 if stage.landed else phys_.e_min
                        assert energies[i + 1] >= required - phys_.energy_tol
                        checked.append(ev.cost)
                        if not stage.landed:
                            hovering.append(energies[i + 1])
        return ev

    monkeypatch.setattr(gf, "_evaluate", check_recovery)
    cost, status = gf.ground_finish_cost(parked, st, inst, phys, horizon)
    assert cost is not None, status
    assert status.startswith("FEASIBLE:")
    assert cost in checked
    if full_battery:
        assert hovering  # 确保真正检查了非降落回收，而非空断言。


def test_all_infeasible_is_flagged_unpriced():
    parked, st, inst, phys, horizon, frag = _parked_far_from_recovery()
    # 零电量且不在任何客户点：到每个合法接机点都需要正的巡航电量。
    pos = (max(c.x for c in inst.customers) + 1000.0,
           max(c.y for c in inst.customers) + 1000.0)
    frag.start_pos = pos
    st.drone_energy[frag.drone] = 0.0
    st.drone_start[frag.drone] = dataclasses.replace(st.drone_start[frag.drone], pos=pos, energy=0.0)
    mass = sum(inst.parcel_mass[p] for p in frag.handover)
    assert all(phys.fly_energy_kwh(math.hypot(c.x - pos[0], c.y - pos[1]), mass)
               > phys.energy_tol for c in inst.customers)
    cost, status = gf.ground_finish_cost(parked, st, inst, phys, horizon)
    assert cost is None and status.startswith("UNPRICED: ")
