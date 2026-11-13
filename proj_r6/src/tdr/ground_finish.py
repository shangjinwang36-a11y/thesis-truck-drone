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
    # T02-A：E_min 是硬约束，应急收尾同样遵守（不再把 reserve_fraction 置 0）。班次之外按加班计价。
    priced = dataclasses.replace(phys, soft_h=True)
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


def _reachable_customers(plan, state, inst, phys, sortie, k: int) -> list[str]:
    """在飞残段按当前电量、带当前机载质量能飞到（到达时电量不低于 E_min）的客户点，按距离取前 k 个。

    含无人机此刻所在的客户点（距离 0）。只看巡航电量；悬停、等待、回收由 _evaluate 复核。
    """
    ds = state.drone_start.get(sortie.drone)
    pos = sortie.start_pos or (ds.pos if ds is not None else None)
    if pos is None:
        return []
    e0 = state.drone_energy.get(sortie.drone, ds.energy if ds is not None else 0.0)
    mass = sum(inst.parcel_mass[p] for p in list(sortie.air) + list(sortie.handover))
    per_m = phys.fly_energy_kwh(1.0, mass)
    out = []
    for c in inst.customers:
        d = math.hypot(c.x - pos[0], c.y - pos[1])
        if d * per_m <= e0 - phys.e_min + phys.energy_tol:
            out.append((d, c.customer_id))
    out.sort()
    return [c for _, c in out[:k]]


def _attempt_relocate(plan, state, inst, phys, H, k: int = 8) -> tuple[float | None, str]:
    """T01：六种收尾都不可行时，把一个在飞残段的接机点改到它的放飞车上一个电量够得着的客户点。

    只用放飞车，所以这是 S 资格的方案，对 R、X 同样合法；函数仍不接收策略。
    原收尾只保留原接机点，在飞机飞不到原接机点时（如失败后带货回程）会漏掉合法收尾。
    电量与班次规则与 _evaluate 相同；取最便宜的可行方案，结果确定。
    """
    best: tuple[float, str] | None = None
    for s in sorted((x for x in plan.sorties.values() if x.started), key=lambda x: x.sid):
        truck = s.launch_truck or s.truck
        if truck not in plan.routes:
            continue
        lo = int((getattr(state, "truck_min_insert", {}) or {}).get(truck, 0))
        for cust in _reachable_customers(plan, state, inst, phys, s, k):
            for pos in range(lo, len(plan.routes[truck]) + 1):
                for land in (True, False):
                    for mode in ("truck", "keep_inflight", "overtime_only"):
                        p = plan.clone()
                        v = p.add_visit(truck, cust, pos=pos, ground=[])
                        p.sorties[s.sid].rec_vid = v.vid
                        # 接机点已迁移：先清除该残段交接票的旧地送，再由 _build 排到新回收点之后。
                        hand_set = set(p.sorties[s.sid].handover)
                        for visit in p.visits.values():
                            visit.ground = [parcel for parcel in visit.ground if parcel not in hand_set]
                        cost, note = _attempt(p, state, inst, phys, H, mode, land)
                        if cost is None:
                            continue
                        tag = f"FEASIBLE:relocate:{note.split(':', 1)[1]}:s{s.sid}->{cust}@{truck}#{pos}"
                        if best is None or cost < best[0] - 1e-9:
                            best = (cost, tag)
    if best is None:
        return None, "relocate:NONE"
    return best


def ground_finish_cost(plan, state, inst, phys, H, relocate: bool = True) -> tuple[float | None, str]:
    """返回 (真实成本, 状态)。成本含里程、工时、能耗和加班，不含每客户罚金。

    前三种收尾都不可行时，才允许已在飞的残段改成降落等待。这只去掉接机点上的悬停耗电，
    不改已经由前三种收尾定过价的回合，也不加每客户罚金。飞到接机点的电耗仍照计。
    六种都不可行时（T01），再试把在飞残段的接机点挪到放飞车上够得着的客户点。
    已经由前六种定过价的回合不受影响。relocate=False 复现旧行为。
    """
    notes = []
    for land in (False, True):
        for mode in ("truck", "keep_inflight", "overtime_only"):
            cost, note = _attempt(plan, state, inst, phys, H, mode, land)
            if cost is not None:
                return cost, note
            notes.append(note)
    if relocate:
        cost, note = _attempt_relocate(plan, state, inst, phys, H)
        if cost is not None:
            return cost, note
        notes.append(note)
    # T02-A：所有收尾都不可行时明确标成未定价，调用方不会把 None 当成 0。
    return None, "UNPRICED: " + (" | ".join(notes) or "NO_ATTEMPT")
