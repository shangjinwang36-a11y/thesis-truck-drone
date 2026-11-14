"""停止回合的应急收尾：剩下的客户改由卡车地面送达。

不另加罚金，不把班次改成加班，也不把储备清零。无人机仍在空中且没有合法回收时，
不生成有限成本。S、R、X 用同一套规则，函数不接收策略。
"""
from __future__ import annotations

import copy
import dataclasses

from .evaluate import evaluate_plan
from .moves import remove_sortie_closure, repair_ground_append, repair_ground_only


def _covered(plan) -> set[str]:
    got = {p for v in plan.visits.values() for p in v.ground}
    for s in plan.sorties.values():
        got.update(s.air)
        got.update(s.handover)
    return got


def _place_handover_after_recovery(plan, inst, state) -> None:
    """在飞机上的票落地后由回收车地送。落点之前的访问不接收这些票。"""
    delivered = set(state.delivered)
    for s in list(plan.sorties.values()):
        if not s.started:
            continue
        if s.rec_vid not in plan.visits:
            truck = s.truck
            if not s.handover:
                continue
            cust = inst.parcel_to_customer[s.handover[0]]
            visit = plan.add_visit(truck, cust, pos=len(plan.routes.get(truck, [])), ground=[])
            s.rec_vid = visit.vid
        if s.rec_vid not in plan.visits:
            continue
        truck = plan.visits[s.rec_vid].truck
        route = plan.routes[truck]
        rec_i = route.index(s.rec_vid)
        for parcel in list(s.handover):
            if parcel in delivered:
                continue
            cust = inst.parcel_to_customer[parcel]
            placed = False
            for i, vid in enumerate(route):
                if i >= rec_i and plan.visits[vid].customer == cust:
                    if parcel not in plan.visits[vid].ground:
                        plan.visits[vid].ground.append(parcel)
                    placed = True
                    break
            if placed:
                continue
            plan.add_visit(truck, cust, pos=len(plan.routes[truck]), ground=[parcel])
            route = plan.routes[truck]


def _cancel_unstarted(plan, state) -> list[str]:
    freed: list[str] = []
    holders = dict(state.parcel_holder)
    while True:
        sid = next((s.sid for s in plan.sorties.values() if not s.started), None)
        if sid is None:
            break
        s = plan.sorties[sid]
        for parcel in list(s.air) + list(s.handover):
            holders.setdefault(parcel, f"TRUCK:{s.truck}")
            if str(holders.get(parcel, "")).startswith("DRONE"):
                holders[parcel] = f"TRUCK:{s.truck}"
        remove_sortie_closure(plan, sid, freed)
    state.parcel_holder = holders
    return freed


def _pool(plan, state, inst, freed: list[str]) -> list[str]:
    delivered = set(state.delivered)
    covered = _covered(plan)
    pool = []
    for parcel in list(freed) + list(inst.parcel_mass):
        if parcel in delivered or parcel in covered or parcel in pool:
            continue
        pool.append(parcel)
    return pool


def _insert(plan, inst, phys, state, pool: list[str]) -> list[str]:
    min_pos = dict(getattr(state, "truck_min_insert", {}) or {})
    plan, left = repair_ground_only(plan, inst, phys, pool, min_pos, state)
    if left:
        plan, left = repair_ground_append(plan, inst, phys, left, min_pos, state)
    return left


def _build(plan, state, inst, phys, mode: str, land: bool = False):
    p = plan.clone()
    st = copy.copy(state)
    st.parcel_holder = dict(state.parcel_holder)
    st.delivered = set(state.delivered)
    freed: list[str] = []
    if mode != "overtime_only":
        freed = _cancel_unstarted(p, st)
    if mode == "truck":
        for s in p.sorties.values():
            if not s.started:
                continue
            for parcel in list(s.air):
                if parcel not in s.handover:
                    s.handover.append(parcel)
            s.air = []
    if land:
        raise AssertionError("landed wait/recovery branch must never trigger")
    # 失败票已经在交接清单里，但停止时的计划还没给它地送访问。三种收尾都补上。
    _place_handover_after_recovery(p, inst, st)
    left = _insert(p, inst, phys, st, _pool(p, st, inst, freed))
    return p, st, left


def _evaluate(plan, state, inst, phys, H, budget=None):
    # 硬 H、硬 E_min。不切换 soft_h，不清零储备。评价计入调用方传来的同一份预算。
    if phys.soft_h or phys.reserve_fraction <= 0.0:
        raise AssertionError("ground finish must not relax H or the energy floor")
    return evaluate_plan(plan, inst, phys, state, H, "GROUND_FINISH", budget=budget)


def _attempt(plan, state, inst, phys, H, mode: str, land: bool, budget=None) -> tuple[float | None, str]:
    tag = mode
    try:
        built, st, left = _build(plan, state, inst, phys, mode, land=land)
        if left:
            return None, f"UNPLACED:{tag}:{len(left)}"
        # 仍在空中的航次必须留有回收访问。没有合法回收就不能把货直接算成地面完成。
        for s in built.sorties.values():
            if s.started and s.rec_vid not in built.visits:
                return None, f"AIRBORNE_WITHOUT_RECOVERY:{tag}:{s.sid}"
        ev = _evaluate(built, st, inst, phys, H, budget=budget)
    except Exception as exc:
        return None, f"{tag}:EXC:{type(exc).__name__}"
    if ev is not None and ev.feasible and ev.cost is not None:
        return float(ev.cost), f"FEASIBLE:{tag}"
    note = ev.status if ev is None else (ev.violations[0] if ev.violations else ev.status)
    return None, f"{tag}:{str(note)[:160]}"


def ground_finish_cost(plan, state, inst, phys, H, budget=None) -> tuple[float | None, str]:
    """返回 (真实地面配送成本, 状态)。没有合法完整收尾时成本是 None，不加罚分。"""
    notes = []
    for mode in ("truck", "keep_inflight", "overtime_only"):
        cost, note = _attempt(plan, state, inst, phys, H, mode, False, budget=budget)
        if cost is not None:
            return cost, note
        notes.append(note)
    return None, " | ".join(notes) or "NO_LEGAL_COMPLETION_FOUND"
