"""T02-C：失败直返的等车/通道耗电、惰性换电及独立核验边界。无随机种子。"""
from dataclasses import replace

import pytest

from tdr import evaluate, verify
from tdr.config import PhysicalConfig
from tdr.data import Customer, Instance
from tdr.plan import Plan
from tdr.schedule import (DroneStart, allocate_swaps, failure_return_requirement,
                          initial_state, schedule_plan, stage_energy)


def _case(*, started=True, energy=0.17, landed=False, speed=25 / 3):
    phys = PhysicalConfig(
        truck_count=1, drone_count=1, swap_mode=True,
        truck_speed_m_s=speed, drone_speed_m_s=50 / 3,
        drone_payload_limit_kg=4, battery_kwh=0.5, payload_ref_kg=4,
        range_empty_m=22500, range_slope_m_per_kg=1875,
        hover_min_empty=22.5, hover_min_ref=15, land_and_wait=True,
    )
    inst = Instance('return', 'test', 0, 0, (
        Customer('cA', 'pA', 0, 0, 4), Customer('cR', 'pR', 2000, 0, 1),
    ))
    plan = Plan(inst.case_id)
    rv = plan.add_visit('t1', 'cR', ground=['pR'])
    sortie = plan.add_sortie('d1', 't1', None, 'AIR' if started else 'ARC',
                             0, ['pA'], rv.vid)
    sortie.started = started
    sortie.landed = landed
    state = initial_state(inst, phys)
    state.drone_energy['d1'] = energy
    if started:
        state.t0 = 1
        state.truck_start_time['t1'] = 1
        state.truck_ready_time['t1'] = 1
        sortie.start_time = 1
        sortie.start_pos = (0, 0)
        state.drone_start['d1'] = DroneStart('AIRBORNE', ready_time=1,
                                             pos=(0, 0), energy=energy, aboard=['pA'])
    else:
        state.drone_start['d1'] = replace(state.drone_start['d1'], energy=energy)
    return plan, inst, phys, state, sortie


def _nominal_energy(tl, phys, state):
    """重放名义消耗，用于隔离失败返航约束（不可修复的调度会提前返回）。"""
    for d, stages in tl.drone_stages.items():
        energy = state.drone_energy[d]
        energies = [energy]
        for stage in stages:
            energy -= stage_energy(stage, phys)
            energies.append(energy)
        tl.drone_energy[d] = energies


def test_loaded_return_waits_120_seconds_and_has_only_002_left():
    plan, inst, phys, state, sortie = _case()
    tl = schedule_plan(plan, inst, phys, state)
    _nominal_energy(tl, phys, state)
    stage = next(s for s in tl.drone_stages['d1'] if s.kind == 'SERVICE')
    assert tl.rec_ready[sortie.sid] - (stage.start + 2000 / phys.drone_speed_m_s) == pytest.approx(120)
    consumption, reserve = failure_return_requirement(plan, inst, phys, tl, stage)
    assert state.drone_energy['d1'] - consumption == pytest.approx(0.02)
    assert reserve == pytest.approx(0.05)
    assert tl.drone_energy['d1'][-1] > reserve  # 名义送货可行。
    assert evaluate.failure_return_violations(plan, inst, phys, tl) == [
        'FAIL_RETURN:d1@1.0:pA:e=0.020000<0.050000'
    ]


def test_recovery_channel_and_prior_handover_delay_return():
    plan, inst, phys, state, sortie = _case(energy=0.5)
    phys = replace(phys, drone_count=2, drones_per_truck_initial=2)
    phys.set_active()
    other = plan.add_sortie('d2', 't1', None, 'AIR', 0, [], sortie.rec_vid, handover=['pR'])
    other.started, other.start_time, other.start_pos = True, 281, (2000, 0)
    other.rec_priority = -1
    state.drone_start['d2'] = DroneStart('AIRBORNE', ready_time=281, pos=(2000, 0), energy=0.5)
    state.drone_energy['d2'] = 0.5
    tl = schedule_plan(plan, inst, phys, state)
    stage = next(s for s in tl.drone_stages['d1'] if s.kind == 'SERVICE')
    assert tl.visit_arr[sortie.rec_vid] == pytest.approx(241)
    assert tl.rec_ready[sortie.sid] == pytest.approx(281 + phys.recovery_s + phys.handover_s)
    consumption, _ = failure_return_requirement(plan, inst, phys, tl, stage)
    assert consumption == pytest.approx(phys.fly_energy_kwh(2000, 4)
        + phys.hover_energy_kwh(210 + phys.recovery_s, 4))


def test_does_not_count_wait_for_own_nominal_delivery_as_channel_occupancy():
    plan, inst, phys, state, sortie = _case(energy=0.14, speed=100)
    ev = evaluate.evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    tl = ev.timeline
    assert tl.rec_ready[sortie.sid] == pytest.approx(21)
    assert tl.rec_times[sortie.sid][0] == pytest.approx(181)
    stage = next(s for s in tl.drone_stages['d1'] if s.kind == 'SERVICE')
    consumption, _ = failure_return_requirement(plan, inst, phys, tl, stage)
    assert consumption == pytest.approx(phys.fly_energy_kwh(2000, 4)
                                        + phys.hover_energy_kwh(phys.recovery_s, 4))


@pytest.mark.parametrize('strategy', ['S', 'R', 'X'])
@pytest.mark.parametrize('started', [False, True])
def test_swap_repairs_unstarted_but_cannot_repair_airborne_and_verify_agrees(strategy, started):
    plan, inst, phys, state, sortie = _case(started=started)
    ev = evaluate.evaluate_plan(plan, inst, phys, state)
    rep = verify.verify_plan(inst, state, plan, strategy, phys)
    assert ev.feasible == rep.ok == (not started), (ev.violations, rep.violations)
    if started:
        assert ev.violations == rep.violations
        assert 'SWAP_CANNOT_FIX:d1@1.0:' in ev.violations[0]
        assert 'stage=SERVICE' in ev.violations[0]
    else:
        tl = ev.timeline
        assert tl.swaps == {sortie.sid}
        assert tl.swap_count_by_truck == {'t1': 1}
        swap = next(a for a in tl.actions if a.kind == 'W')
        prep = next(a for a in tl.actions if a.kind == 'P')
        assert swap.end == prep.start
        assert evaluate.failure_return_violations(plan, inst, phys, tl) == []
        assert rep.cost == pytest.approx(ev.cost)


@pytest.mark.parametrize('strategy', ['S', 'R', 'X'])
def test_evaluate_and_verify_recheck_return_even_if_allocator_missed_it(monkeypatch, strategy):
    plan, inst, phys, state, _ = _case()
    tl = schedule_plan(plan, inst, phys, state)
    tl.swap_msg = ''  # 模拟仅验证名义能量的旧分配器输出，独立检查仍必须拒绝。
    assert allocate_swaps(tl, phys, state)[0]
    monkeypatch.setattr(evaluate, 'schedule_plan', lambda *args, **kwargs: tl)
    monkeypatch.setattr(verify, 'schedule_plan', lambda *args, **kwargs: tl)
    ev = evaluate.evaluate_plan(plan, inst, phys, state)
    rep = verify.verify_plan(inst, state, plan, strategy, phys)
    assert not ev.feasible and not rep.ok
    assert ev.violations == rep.violations == ['FAIL_RETURN:d1@1.0:pA:e=0.020000<0.050000']


@pytest.mark.parametrize('landed', [False, True])
@pytest.mark.parametrize('shortfall, rejected', [(0, False), (0.5e-6, False), (2e-6, True)])
def test_return_reserve_boundary_and_landed_nonnegative(landed, shortfall, rejected):
    plan, inst, phys, state, _ = _case(landed=landed)
    tl = schedule_plan(plan, inst, phys, state)
    _nominal_energy(tl, phys, state)
    i, stage = next((i, s) for i, s in enumerate(tl.drone_stages['d1']) if s.kind == 'SERVICE')
    expected_consumption = phys.fly_energy_kwh(2000, 4)
    if not landed:
        expected_consumption += phys.hover_energy_kwh(150, 4)
    reserve = 0 if landed else phys.e_min
    tl.drone_energy['d1'][i] = expected_consumption + reserve - shortfall
    assert bool(evaluate.failure_return_violations(plan, inst, phys, tl)) == rejected


def test_landed_low_reserve_evaluates_and_verifies():
    plan, inst, phys, state, _ = _case(landed=True, energy=0.09)
    ev = evaluate.evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    assert 0 < ev.timeline.e_return['d1'] < phys.e_min
    assert verify.verify_plan(inst, state, plan, 'S', phys).ok


def test_resumed_service_is_exempt_but_next_unobserved_service_is_checked():
    plan, inst, phys, state, sortie = _case(energy=0.12)
    inst = replace(inst, customers=(replace(inst.customers[0], mass_kg=2), inst.customers[1],
                                    Customer('cB', 'pB', 0, 0, 2)))
    sortie.air.append('pB')
    state.drone_start['d1'] = replace(state.drone_start['d1'], service_parcel='pA', service_done_s=30)
    tl = schedule_plan(plan, inst, phys, state)
    _nominal_energy(tl, phys, state)
    services = [s for s in tl.drone_stages['d1'] if s.kind == 'SERVICE']
    assert services[0].resumed and not services[1].resumed
    assert failure_return_requirement(plan, inst, phys, tl, services[0]) is None
    errors = evaluate.failure_return_violations(plan, inst, phys, tl)
    assert len(errors) == 1 and ':pB:' in errors[0]


def test_resumed_only_service_does_not_force_swap_or_fail_verify():
    plan, inst, phys, state, _ = _case(energy=0.16)
    state.drone_start['d1'] = replace(state.drone_start['d1'], service_parcel='pA', service_done_s=59)
    ev = evaluate.evaluate_plan(plan, inst, phys, state)
    assert ev.feasible, ev.violations
    assert ev.timeline.failure_return_need == {} and not ev.timeline.swaps
    assert verify.verify_plan(inst, state, plan, 'S', phys).ok
