"""停止回合的应急收尾：剩下的客户改由卡车地面送达。

不另加每客户罚金。失败是随机事件。超出班次的时间只按模型里的加班工资计价
（soft_h，倍率 overtime_mult，基础工资已经按 1 倍计入，加班再加 (mult-1) 倍）。
S、R、X 用同一套规则，函数不接收策略。
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


def _build(plan, state, inst, phys, mode: str):
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
    # 失败票已经在交接清单里，但停止时的计划还没给它地送访问。三种收尾都补上。
    _place_handover_after_recovery(p, inst, st)
    left = _insert(p, inst, phys, st, _pool(p, st, inst, freed))
    return p, st, left


def _evaluate(plan, state, inst, phys, H):
    # 规划储备是搜索用的余量。应急收尾只拒绝电量真正为负的飞行，班次之外按加班计价。
    priced = dataclasses.replace(phys, soft_h=True, reserve_fraction=0.0)
    return evaluate_plan(plan, inst, priced, state, H, "GROUND_FINISH")


def ground_finish_cost(plan, state, inst, phys, H) -> tuple[float | None, str]:
    """返回 (真实成本, 状态)。成本含里程、工时、能耗和加班，不含每客户罚金。"""
    notes = []
    for mode in ("truck", "keep_inflight", "overtime_only"):
        try:
            built, st, left = _build(plan, state, inst, phys, mode)
            if left:
                notes.append(f"UNPLACED:{mode}:{len(left)}")
                continue
            ev = _evaluate(built, st, inst, phys, H)
        except Exception as exc:
            notes.append(f"{mode}:EXC:{type(exc).__name__}")
            continue
        if ev is not None and ev.feasible and ev.cost is not None:
            return float(ev.cost), f"FEASIBLE:{mode}"
        note = ev.status if ev is None else (ev.violations[0] if ev.violations else ev.status)
        notes.append(f"{mode}:{str(note)[:160]}")
    return None, " | ".join(notes) or "NO_ATTEMPT"
