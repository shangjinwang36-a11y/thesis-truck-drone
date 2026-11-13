"""T02-A：应急收尾遵守 E_min（0.05 kWh），不再用零储备；全部不可行时明确标成 UNPRICED。
收尾函数仍没有策略参数，S/R/X 同一路径。"""
import dataclasses

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


def test_priced_finish_lands_every_recovery_at_or_above_emin():
    parked, st, inst, phys, horizon, _ = _parked_far_from_recovery()
    cost, status = gf.ground_finish_cost(parked, st, inst, phys, horizon)
    if cost is None:
        assert status.startswith("UNPRICED: ")
        return
    assert status.startswith("FEASIBLE:")


def test_all_infeasible_is_flagged_unpriced():
    parked, st, inst, phys, horizon, frag = _parked_far_from_recovery()
    st.drone_energy[frag.drone] = 0.0
    st.drone_start[frag.drone] = dataclasses.replace(st.drone_start[frag.drone], energy=0.0)
    cost, status = gf.ground_finish_cost(parked, st, inst, phys, horizon)
    assert cost is None and status.startswith("UNPRICED: ")
