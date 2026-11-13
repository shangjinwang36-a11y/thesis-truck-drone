"""停止回合的应急收尾：剩下的客户改由卡车地面送达。

不另加每客户罚金。失败是随机事件。超出班次的时间只按模型里的加班工资计价
（soft_h，倍率 overtime_mult，基础工资已经按 1 倍计入，加班再加 (mult-1) 倍）。
S、R、X 用同一套规则，函数不接收策略。
"""
from __future__ import annotations

import copy
import dataclasses
import math

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


def _return_flight_kwh(sortie, plan, inst, phys) -> float:
    """按现在的残段算还要飞的电量：先送完 air，再飞回原定接机点。服务悬停不算在内。"""
    pos = sortie.start_pos
    mass = sum(inst.parcel_mass[p] for p in sortie.air + sortie.handover if p in inst.parcel_mass)
    need = 0.0
    for parcel in sortie.air:
        cust = inst.customer(inst.parcel_to_customer[parcel])
        need += phys.fly_energy_kwh(math.hypot(cust.x - pos[0], cust.y - pos[1]), mass)
        mass = max(0.0, mass - inst.parcel_mass.get(parcel, 0.0))
        pos = (cust.x, cust.y)
    if sortie.rec_vid not in plan.visits:
        return math.inf
    rec = inst.customer(plan.visits[sortie.rec_vid].customer)
    need += phys.fly_energy_kwh(math.hypot(rec.x - pos[0], rec.y - pos[1]), mass)
    return need


def _onboard_mass(sortie, inst) -> float:
    return sum(inst.parcel_mass[p] for p in sortie.air + sortie.handover if p in inst.parcel_mass)


def _nearest_reachable_customer(sortie, state, inst, phys) -> str | None:
    """当前电量直接飞得到的客户里，离无人机最近的一个。"""
    ds = state.drone_start.get(sortie.drone)
    if ds is None or ds.pos is None:
        return None
    mass = _onboard_mass(sortie, inst)
    best: tuple[tuple[float, str], str] | None = None
    for cust in inst.customers:
        hop = math.hypot(cust.x - ds.pos[0], cust.y - ds.pos[1])
        if phys.fly_energy_kwh(hop, mass) > ds.energy + phys.energy_tol:
            continue
        key = (hop, cust.customer_id)
        if best is None or key < best[0]:
            best = (key, cust.customer_id)
    return None if best is None else best[1]


def _relocate_unreachable(plan, state, inst, phys):
    """六种收尾都失败之后，把飞不回去的残段改到放飞车上当前电量够得到的点。

    接机客户取离无人机最近、并且直飞电量不超过当前电量的客户。放飞车已有不早于
    最小插入位置的同客户访问就用它，否则按最小绕行插进放飞车路线。原航程够的残段不动。
    三种策略走同一个函数，不改搜索。
    """
    from .recovery import _insert_support

    moved = plan.clone()
    changed = False
    for sortie in list(moved.sorties.values()):
        if not sortie.started or sortie.start_pos is None:
            continue
        ds = state.drone_start.get(sortie.drone)
        if ds is None or ds.pos is None:
            continue
        if _return_flight_kwh(sortie, moved, inst, phys) <= ds.energy + phys.energy_tol:
            continue
        truck = sortie.launch_truck or sortie.truck
        if truck is None or truck in state.truck_done or truck not in moved.routes:
            continue
        customer_id = _nearest_reachable_customer(sortie, state, inst, phys)
        if customer_id is None:
            continue
        route = moved.routes.get(truck, [])
        min_pos = int(state.truck_min_insert.get(truck, 0) or 0)
        vid = next((v for i, v in enumerate(route)
                    if i >= min_pos and moved.visits[v].customer == customer_id), None)
        if vid is None:
            vid = _insert_support(moved, inst, truck, customer_id, min_pos=min_pos)
        sortie.rec_vid = vid
        changed = True
    return moved if changed else None


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
        # 只改已经在飞的残段。降落等待的电耗规则在 schedule.stage_energy：
        # 落地后的等待和回收不再悬停耗电，飞到接机点的航程仍按原电耗计。
        for s in p.sorties.values():
            if s.started:
                s.landed = True
    # 失败票已经在交接清单里，但停止时的计划还没给它地送访问。三种收尾都补上。
    _place_handover_after_recovery(p, inst, st)
    left = _insert(p, inst, phys, st, _pool(p, st, inst, freed))
    return p, st, left


def _evaluate(plan, state, inst, phys, H):
    # 规划储备是搜索用的余量。应急收尾只拒绝电量真正为负的飞行，班次之外按加班计价。
    priced = dataclasses.replace(phys, soft_h=True, reserve_fraction=0.0)
    return evaluate_plan(plan, inst, priced, state, H, "GROUND_FINISH")


def _attempt(plan, state, inst, phys, H, mode: str, land: bool) -> tuple[float | None, str]:
    tag = f"{mode}:landed" if land else mode
    try:
        built, st, left = _build(plan, state, inst, phys, mode, land=land)
        if left:
            return None, f"UNPLACED:{tag}:{len(left)}"
        ev = _evaluate(built, st, inst, phys, H)
    except Exception as exc:
        return None, f"{tag}:EXC:{type(exc).__name__}"
    if ev is not None and ev.feasible and ev.cost is not None:
        return float(ev.cost), f"FEASIBLE:{tag}"
    note = ev.status if ev is None else (ev.violations[0] if ev.violations else ev.status)
    return None, f"{tag}:{str(note)[:160]}"


def _first_of_six(plan, state, inst, phys, H) -> tuple[float | None, list[str]]:
    notes = []
    for land in (False, True):
        for mode in ("truck", "keep_inflight", "overtime_only"):
            cost, note = _attempt(plan, state, inst, phys, H, mode, land)
            if cost is not None:
                return cost, [note]
            notes.append(note)
    return None, notes


def ground_finish_cost(plan, state, inst, phys, H) -> tuple[float | None, str]:
    """返回 (真实成本, 状态)。成本含里程、工时、能耗和加班，不含每客户罚金。

    前三种收尾都不可行时，才允许已在飞的残段改成降落等待。这只去掉接机点上的悬停耗电，
    不改已经由前三种收尾定过价的回合，也不加每客户罚金。飞到接机点的电耗仍照计。
    六种都失败时，才把飞不回去的接机点改到放飞车上当前电量够得到的客户，再走同一套六种。
    """
    cost, notes = _first_of_six(plan, state, inst, phys, H)
    if cost is not None:
        return cost, notes[0]
    moved = _relocate_unreachable(plan, state, inst, phys)
    if moved is not None:
        cost, extra = _first_of_six(moved, state, inst, phys, H)
        if cost is not None:
            return cost, extra[0]
        notes.extend(extra)
    return None, " | ".join(notes) or "NO_ATTEMPT"
