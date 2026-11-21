"""停止回合的应急收尾：剩下的客户改由卡车地面送达。

不另加每客户罚金。失败是随机事件。超出班次的时间只按模型里的加班工资计价
（soft_h，倍率 overtime_mult，基础工资已经按 1 倍计入，加班再加 (mult-1) 倍）。
S、R、X 用同一套规则，函数不接收策略。
"""
from __future__ import annotations

import copy
import dataclasses
import math
from dataclasses import dataclass

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
            # A retargeted handover must not leave a stale/duplicate ground drop.
            for visit in plan.visits.values():
                visit.ground = [p for p in visit.ground if p != parcel]
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
    # The sole requested model change: no reserve exemption. Original paid overtime stays.
    priced = dataclasses.replace(phys, soft_h=True)
    return evaluate_plan(plan, inst, priced, state, H, "GROUND_FINISH")


@dataclass
class FinishCandidate:
    plan: object = None
    state: object = None
    evaluation: object = None
    status: str = "UNPRICED"
    eval_requests: int = 0

    @property
    def cost(self):
        return self.evaluation.cost if self.evaluation is not None else None


def _candidate(plan, state, inst, phys, H, mode, land, audit):
    tag = f"{mode}:landed" if land else mode
    try:
        built, st, left = _build(plan, state, inst, phys, mode, land=land)
        if left:
            return FinishCandidate(status=f"UNPLACED:{tag}:{len(left)}")
        audit["eval_requests"] += 1
        ev = _evaluate(built, st, inst, phys, H)
    except Exception as exc:
        return FinishCandidate(status=f"{tag}:EXC:{type(exc).__name__}:{exc}")
    if ev.feasible and ev.cost is not None:
        return FinishCandidate(built, st, ev, f"FEASIBLE:{tag}")
    why = ev.violations[0] if ev.violations else ev.status
    return FinishCandidate(status=f"{tag}:{why}")


def _attempt(plan, state, inst, phys, H, mode, land):
    c = _candidate(plan, state, inst, phys, H, mode, land, {"eval_requests": 0})
    return c.cost, c.status


def _reachable_customers(plan, state, inst, phys, sortie, k=8):
    ds = state.drone_start.get(sortie.drone)
    pos = sortie.start_pos or (ds.pos if ds else None)
    if pos is None:
        return []
    energy = state.drone_energy.get(sortie.drone, ds.energy if ds else 0.)
    mass = sum(inst.parcel_mass[p] for p in set(sortie.air + sortie.handover))
    candidates = []
    for customer in inst.customers:
        distance = math.hypot(customer.x - pos[0], customer.y - pos[1])
        if phys.fly_energy_kwh(distance, mass) <= energy - phys.e_min + phys.energy_tol:
            candidates.append((distance, customer.customer_id))
    return [c for _, c in sorted(candidates)[:k]]


def ground_finish_plan(plan, state, inst, phys, H, relocate=True):
    """Original six modes/order, with actual plan returned for execution, not assumed success.

    Only if all six fail, repair the known omitted reachable rendezvous on the launch truck.
    Common S/R/X fallback; eight nearest reachable customers, existing or inserted visits.
    No failures/world are visible to this deterministic planner.
    """
    audit = {"eval_requests": 0}
    notes = []
    for land in (False, True):
        for mode in ("truck", "keep_inflight", "overtime_only"):
            candidate = _candidate(plan, state, inst, phys, H, mode, land, audit)
            if candidate.cost is not None:
                candidate.eval_requests = audit["eval_requests"]
                return candidate
            notes.append(candidate.status)
    best = None
    if relocate:
        for sortie in sorted(plan.sorties.values(), key=lambda s: s.sid):
            if not sortie.started:
                continue
            truck = sortie.launch_truck or sortie.truck
            if truck not in plan.routes or truck in state.truck_done:
                continue
            lo = state.truck_min_insert.get(truck, 0)
            for customer in _reachable_customers(plan, state, inst, phys, sortie):
                existing = [(i, vid) for i, vid in enumerate(plan.routes[truck])
                            if i >= lo and plan.visits[vid].customer == customer]
                inserted = [(i, None) for i in range(lo, len(plan.routes[truck]) + 1)]
                for targets in (existing, inserted):
                    found = False
                    for pos, vid in targets:
                        for land in (True, False):
                            for mode in ("truck", "keep_inflight", "overtime_only"):
                                trial = plan.clone()
                                if vid is None:
                                    rec = trial.add_visit(truck, customer, pos=pos).vid
                                else:
                                    rec = vid
                                trial.sorties[sortie.sid].rec_vid = rec
                                result = _candidate(trial, state, inst, phys, H, mode, land, audit)
                                if result.cost is None:
                                    continue
                                found = True
                                result.status += f":relocate:s{sortie.sid}->{customer}@{truck}#{pos}"
                                if best is None or result.cost < best.cost - 1e-9:
                                    best = result
                    if found:
                        break  # retain/reuse valid visits rather than duplicating them
    if best is not None:
        best.eval_requests = audit["eval_requests"]
        return best
    if relocate:
        # Several fragments may simultaneously be unable to reach their old rendezvous.
        # Repairing only one cannot pass full evaluation. Deterministic nearest safe customer
        # for each, land and wait, all parcels by truck; not a new search/tuning operator.
        joint = plan.clone()
        moved = 0
        for sortie in sorted(joint.sorties.values(), key=lambda s: s.sid):
            if not sortie.started:
                continue
            truck = sortie.launch_truck or sortie.truck
            reachable = _reachable_customers(joint, state, inst, phys, sortie, k=1)
            if not reachable or truck not in joint.routes or truck in state.truck_done:
                break
            customer = reachable[0]
            lo = state.truck_min_insert.get(truck, 0)
            existing = next((vid for vid in joint.routes[truck][lo:]
                             if joint.visits[vid].customer == customer), None)
            if existing is None:
                existing = joint.add_visit(truck, customer).vid
            sortie.rec_vid = existing
            moved += 1
        else:
            if moved > 1:
                result = _candidate(joint, state, inst, phys, H, "truck", True, audit)
                if result.cost is not None:
                    result.status += ":relocate_joint_nearest"
                    result.eval_requests = audit["eval_requests"]
                    return result
    return FinishCandidate(status="UNPRICED:" + " | ".join(notes),
                           eval_requests=audit["eval_requests"])


def ground_finish_cost(plan, state, inst, phys, H, relocate=True):
    """Static candidate estimate only; run_episode must execute and replay before publishing it."""
    result = ground_finish_plan(plan, state, inst, phys, H, relocate)
    return result.cost, result.status
