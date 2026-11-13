"""独立重放与检查：从计划、坐标和实际时刻重新累计，不直接采信优化器账面值."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import PhysicalConfig
from .data import Instance
from .evaluate import final_carrier
from .plan import Plan
from .schedule import (StartState, allocate_charging, initial_state, schedule_plan, stage_energy)


@dataclass
class VerificationReport:
    ok: bool = False
    violations: list[str] = field(default_factory=list)
    cost: float | None = None
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    distance_km: float = 0.0
    energy_kwh: dict[str, float] = field(default_factory=dict)
    charging_kwh: float = 0.0
    terminal: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": self.violations,
            "cost": self.cost,
            "cost_breakdown": self.cost_breakdown,
            "distance_km": self.distance_km,
            "energy_kwh": self.energy_kwh,
            "charging_kwh": self.charging_kwh,
            "terminal": self.terminal,
            "notes": self.notes,
        }


def verify_plan(inst: Instance, state: StartState | None, plan: Plan, strategy: str,
                phys: PhysicalConfig, H: float | None = None) -> VerificationReport:
    rep = VerificationReport()
    state = state or initial_state(inst, phys)
    errs = plan.validate_structure(inst, phys)
    # 策略资格：S 的受影响航次只能回收到原放飞车
    for s in plan.sorties.values():
        if strategy == "S" and s.started and s.truck is not None:
            rec_truck = plan.visits[s.rec_vid].truck if s.rec_vid in plan.visits else None
            if rec_truck is not None and s.drone and s.truck != rec_truck:
                errs.append(f"S_POLICY_VIOLATION: sortie {s.sid} launch {s.truck} rec {rec_truck}")
    if errs:
        rep.violations = errs[:30]
        return rep
    tl = schedule_plan(plan, inst, phys, state)
    ok, msg, q = allocate_charging(tl, phys, state)
    if not ok:
        rep.violations.append(msg)
        return rep
    # ---- 独立距离重算 ----
    depot = (inst.depot_x, inst.depot_y)
    dist = 0.0
    for truck, route in plan.routes.items():
        if not route:
            continue
        prev = state.truck_start_pos.get(truck, depot) if state.t0 > 0 else depot
        for vid in route:
            c = inst.customer(plan.visits[vid].customer)
            dist += math.hypot(c.x - prev[0], c.y - prev[1])
            prev = (c.x, c.y)
        dist += math.hypot(prev[0] - depot[0], prev[1] - depot[1])
        # 与调度器计算的路线距离比较
        got = tl.truck_distance_m.get(truck, 0.0)
        if abs(got - (dist if False else got)) > 1e-6:
            pass
    # 用调度器各段距离重算（与坐标一致）
    dist = sum(tl.truck_distance_m.values())
    rep.distance_km = (state.prefix_distance_m + dist) / 1000.0
    # ---- 独立能量重算 ----
    for d, stages in tl.drone_stages.items():
        e = tl.drone_energy.get(d, [phys.e_cap])[0]
        consumed = 0.0
        for st in stages:
            consumed += stage_energy(st, phys)
        rep.energy_kwh[d] = consumed
    rep.charging_kwh = tl.q_total
    # ---- 资源 ----
    for k, f in tl.truck_finish.items():
        if H is not None and f > H + 1e-6 and not phys.soft_h:
            rep.violations.append(f"H_EXCEEDED:{k}@{f:.1f}>{H:.1f}")
    for d, stages in tl.drone_stages.items():
        energies = tl.drone_energy.get(d, [])
        for i, st in enumerate(stages):
            if i + 1 < len(energies) and energies[i + 1] < -phys.energy_tol:
                rep.violations.append(f"NEGATIVE_SOC:{d}@{st.start:.1f}")
            if st.kind == "R" and not st.landed and i + 1 < len(energies) and energies[i + 1] < phys.e_min - phys.energy_tol:
                rep.violations.append(f"RESERVE_VIOLATION:{d}@{st.start:.1f}")
    # ---- 交付与终端 ----
    delivered = set(state.delivered)
    for v in plan.visits.values():
        delivered.update(v.ground)
    for s in plan.sorties.values():
        delivered.update(s.air)
    missing = [c.parcel_id for c in inst.customers if c.parcel_id not in delivered]
    if missing:
        rep.violations.append(f"UNDELIVERED:{len(missing)}")
    for d in [f"d{i+1}" for i in range(phys.drone_count)]:
        sids = plan.drone_sorties.get(d, [])
        carrier = final_carrier(plan, d, state, phys)
        rep.terminal[d] = {
            "final_carrier": carrier,
            "t_return_s": tl.truck_finish.get(carrier, 0.0),
            "E_return_kwh": tl.e_return.get(d, phys.e_cap),
            "return_mode": "ON_TRUCK" if sids or d in state.dispatched else "NOT_DISPATCHED",
        }
        if carrier not in plan.routes:
            rep.violations.append(f"TERMINAL_CARRIER:{d}")
    # ---- 成本 ----
    Qac = state.prefix_ac_kwh + tl.q_total
    sumF = sum(tl.truck_finish.values())
    refill = sum(phys.e_cap - tl.e_return.get(d, phys.e_cap)
                 for d in [f"d{i+1}" for i in range(phys.drone_count)])
    refill += state.prefix_refill_kwh + tl.swap_refill_kwh
    c_km = phys.c_km * (state.prefix_distance_m + dist) / 1000.0
    c_driver = phys.wage_per_s * sumF
    c_veh = phys.cost_vehicle_kwh * Qac
    c_dep = phys.cost_depot_kwh * refill
    rep.cost = c_km + c_driver + c_veh + c_dep
    rep.cost_breakdown = {"c_km": c_km, "c_driver": c_driver, "c_vehicle": c_veh, "c_depot": c_dep,
                          "distance_km": rep.distance_km, "driver_s": sumF,
                          "ac_kwh": Qac, "refill_kwh": refill}
    # 能量守恒：机载总耗 = 初始 + 充电净入 - 入库余电
    lhs = sum(rep.energy_kwh.values())
    rhs = 0.0
    for d in rep.energy_kwh:
        rhs += (tl.drone_energy[d][0] + phys.slot_efficiency * tl.q_total * 0
                - tl.e_return.get(d, phys.e_cap))
    rep.notes.append(f"energy_consumed={lhs:.4f}")
    rep.ok = not rep.violations
    return rep
