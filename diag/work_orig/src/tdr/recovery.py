"""恢复初始构造：同点/异点、原车/跨车、机上余票子集、R-U-G 闭包（第7.4节）.

候选目录按"接机车辆 → 接机位置（既有访问或全客户支援访问）→ 继续配送子集"
的稳定顺序**持续展开**，由统一预算决定本次评到哪一步；不再用固定候选上限。
每次求解释放一个 `RecoveryCatalog`，其游标可在 ALNS 的恢复邻域中继续前进，
从而保证"增加预算 → 覆盖更多接机车/接机客户/继续子集"。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .config import PhysicalConfig
from .data import Instance
from .evaluate import Evaluation, evaluate_plan
from .alns import Budget, eval_counted
from .moves import (ground_candidates, repair_greedy, repair_ground_append,
                    repair_ground_only, repair_regret2)
from .plan import Plan, Sortie
from .schedule import StartState


@dataclass
class RecoveryOption:
    plan: Plan
    ev: Evaluation
    description: str
    recovery_truck: str
    recovery_vid: int
    served_air: int
    handover: list[str] = field(default_factory=list)


def _pos(inst: Instance, plan: Plan, vid: int) -> tuple[float, float]:
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


def _insert_support(plan: Plan, inst: Instance, truck: str, customer: str,
                    min_pos: int = 0) -> int:
    route = plan.routes[truck]
    depot = (inst.depot_x, inst.depot_y)
    c = inst.customer(customer)
    cpos = (c.x, c.y)
    best = None
    for i in range(min_pos, len(route) + 1):
        prev = depot if i == 0 else _pos(inst, plan, route[i - 1])
        nxt = depot if i == len(route) else _pos(inst, plan, route[i])
        det = (math.hypot(prev[0] - cpos[0], prev[1] - cpos[1])
               + math.hypot(cpos[0] - nxt[0], cpos[1] - nxt[1])
               - math.hypot(prev[0] - nxt[0], prev[1] - nxt[1]))
        if best is None or det < best[0]:
            best = (det, i)
    return plan.add_visit(truck, customer, pos=best[1], ground=[]).vid


def _skeleton(plan: Plan, inst: Instance) -> tuple[Plan, list[str]]:
    base = Plan(plan.case_id)
    base.next_vid = plan.next_vid
    base.next_sid = plan.next_sid
    for truck in plan.routes:
        base.routes[truck] = []
    fixed: set[str] = set()
    for s in plan.sorties.values():
        if s.started:
            base.sorties[s.sid] = s.clone()
            base.drone_sorties.setdefault(s.drone, []).append(s.sid)
            fixed.update(s.air)
            fixed.update(s.handover)
    for truck, route in plan.routes.items():
        for vid in route:
            v = plan.visits[vid].clone()
            v.ground = []
            base.visits[vid] = v
            base.routes[truck].append(vid)
    pool = [c.parcel_id for c in inst.customers if c.parcel_id not in fixed]
    return base, pool


def _place_handover_g(plan: Plan, inst: Instance, truck: str, rv: int,
                      parcels: list[str]) -> list[str]:
    errs: list[str] = []
    route = plan.routes[truck]
    if rv not in route:
        return [f"RECOVERY_VISIT_MISSING:{rv}"]
    rv_cust = plan.visits[rv].customer
    for p in sorted(set(parcels)):
        cust = inst.parcel_to_customer[p]
        if cust == rv_cust:
            if p not in plan.visits[rv].ground:
                plan.visits[rv].ground.append(p)
            continue
        idx = route.index(rv)
        target = next((vid for vid in route[idx + 1:] if plan.visits[vid].customer == cust), None)
        if target is not None:
            if p not in plan.visits[target].ground:
                plan.visits[target].ground.append(p)
            continue
        depot = (inst.depot_x, inst.depot_y)
        c = inst.customer(cust)
        best = None
        for i in range(idx + 1, len(route) + 1):
            prev = _pos(inst, plan, route[i - 1])
            nxt = depot if i == len(route) else _pos(inst, plan, route[i])
            det = (math.hypot(prev[0] - c.x, prev[1] - c.y)
                   + math.hypot(c.x - nxt[0], c.y - nxt[1])
                   - math.hypot(prev[0] - nxt[0], prev[1] - nxt[1]))
            if best is None or det < best[0]:
                best = (det, i)
        plan.add_visit(truck, cust, pos=best[1], ground=[p])
        route = plan.routes[truck]
    return errs


def _cleanup(plan: Plan) -> None:
    used = set()
    for s in plan.sorties.values():
        used.add(s.rec_vid)
        if s.launch_vid is not None:
            used.add(s.launch_vid)
    for truck in list(plan.routes):
        keep = []
        for vid in plan.routes[truck]:
            v = plan.visits.get(vid)
            if v is None:
                continue
            if v.ground or vid in used:
                keep.append(vid)
            else:
                plan.visits.pop(vid, None)
        plan.routes[truck] = keep


def _set_recovery(plan: Plan, frag: Sortie, rec_truck: str, rec_vid: int,
                  served: list[str]) -> list[str]:
    remain = list(frag.air)
    served_set = set(served)
    handover = list(frag.handover) + [p for p in remain if p not in served_set]
    frag.air = [p for p in remain if p in served_set]
    frag.handover = handover
    frag.rec_vid = rec_vid
    if frag.launch_truck is None:
        frag.launch_truck = frag.truck
    frag.truck = rec_truck
    return handover


# ---------------------------------------------------------------------------
# 持续展开的候选目录
# ---------------------------------------------------------------------------
class RecoveryCatalog:
    """稳定的候选枚举顺序 + 游标 + 覆盖统计.

    顺序：接机车辆（原放飞车优先，其余按到失败点距离）→ 接机位置（既有访问按距离，
    再对全部客户生成支援访问按距离）→ 继续配送子集（空集、单票、全集，票数≤4时补两票组合）。
    """

    def __init__(self, plan: Plan, frag: Sortie, inst: Instance, strategy: str,
                 state: StartState | None = None, ground_required: set[str] | None = None):
        self._base_plan = plan
        self.frag = frag
        self.inst = inst
        self.strategy = strategy
        self.state = state
        self.ground_required = set(ground_required or set())
        self.launch_truck = frag.truck or (state.drone_carrier.get(frag.drone, "t1")
                                           if state else f"t{int(frag.drone[1:])}")
        self.frag_pos = frag.start_pos or (inst.depot_x, inst.depot_y)
        self._gen = self._entries()
        self.covered_trucks: set[str] = set()
        self.covered_customers: set[str] = set()
        self.covered_subsets: set[int] = set()
        self.n_generated = 0
        self.n_evaluated = 0
        self.exhausted = False

    def _truck_order(self, plan: Plan) -> list[str]:
        trucks = [self.launch_truck] if self.strategy == "S" else sorted(plan.routes)
        def dist(truck):
            if not plan.routes.get(truck):
                return math.inf
            best = min(math.hypot(_pos(self.inst, plan, vid)[0] - self.frag_pos[0],
                                  _pos(self.inst, plan, vid)[1] - self.frag_pos[1])
                       for vid in plan.routes[truck])
            return best
        return sorted(trucks, key=lambda t: (t != self.launch_truck, dist(t), t))

    def _entries(self):
        # 全局按"到失败点的距离"排序：各车的最远位置交错出现，避免某辆车独占预算
        plan = self._base_plan
        rem = [p for p in self.frag.air if p not in self.ground_required]
        subsets: list[list[str]] = [[]]
        subsets += [[p] for p in rem]
        if len(rem) >= 2:
            subsets.append(list(rem))
            if len(rem) <= 4:
                subsets += [list(c) for c in itertools.combinations(rem, 2)]
        items = []
        launch = self.launch_truck
        trucks = [launch] if self.strategy == "S" else sorted(plan.routes)
        for truck in trucks:
            route = plan.routes.get(truck, [])
            for vid in route:
                pos = _pos(self.inst, plan, vid)
                items.append((math.hypot(pos[0] - self.frag_pos[0], pos[1] - self.frag_pos[1]),
                              truck, 0, vid, plan.visits[vid].customer))
            for c in self.inst.customers:
                pos = (c.x, c.y)
                items.append((math.hypot(pos[0] - self.frag_pos[0], pos[1] - self.frag_pos[1]),
                              truck, 1, c.customer_id, c.customer_id))
        items.sort(key=lambda x: (x[0], x[1] != launch, x[2], str(x[3])))
        seen = set()
        for dist, truck, kind_rank, ref, cust in items:
            support = kind_rank == 1
            for served in subsets:
                key = (truck, ref, tuple(served))
                if key in seen:
                    continue
                seen.add(key)
                self.n_generated += 1
                yield {"truck": truck, "kind": "support" if support else "visit",
                       "ref": ref, "support": support, "served": list(served)}

    def next_entries(self, n: int):
        out = []
        for _ in range(n):
            try:
                out.append(next(self._gen))
            except StopIteration:
                self.exhausted = True
                break
        return out


def build_candidates(base: Plan, pool: list[str], frag_sid: int, entry: dict,
                     inst: Instance, phys: PhysicalConfig, state: StartState,
                     H: float | None, ground_required: set[str]) -> list[Plan]:
    cand = base.clone()
    f = cand.sorties.get(frag_sid)
    if f is None:
        return []
    truck = entry["truck"]
    if entry["support"]:
        rv = _insert_support(cand, inst, truck, entry["ref"],
                             min_pos=state.truck_min_insert.get(truck, 0))
    else:
        rv = entry["ref"]
        if rv not in cand.visits or cand.visits[rv].truck != truck:
            return []
    hand = _set_recovery(cand, f, truck, rv, entry["served"])
    gerr = _place_handover_g(cand, inst, truck, rv, hand)
    if gerr:
        return []
    pool2 = [p for p in pool if p not in hand]
    attempts = []
    mp = state.truck_min_insert or None
    if pool2:
        c1, left = repair_greedy(cand.clone(), inst, phys, pool2,
                                 forbid_air=ground_required, min_pos=mp, state=state)
        if not left:
            attempts.append(c1)
        attempts.append(repair_ground_append(cand.clone(), inst, phys, pool2, mp, state)[0])
        attempts.append(repair_ground_only(cand.clone(), inst, phys, pool2, mp, state)[0])
    else:
        attempts.append(cand)
    for at in attempts:
        _cleanup(at)
    return attempts


def initial_recovery(plan: Plan, state: StartState, inst: Instance, phys: PhysicalConfig,
                     strategy: str, ground_required: set[str],
                     max_candidates: int | None = None, H: float | None = None,
                     extra_pool: list[str] | None = None, frag_sid: int | None = None,
                     stats=None, budget: Budget | None = None,
                     catalog: RecoveryCatalog | None = None
                     ) -> tuple[RecoveryOption | None, list[str], RecoveryCatalog | None]:
    frag = plan.sorties.get(frag_sid) if frag_sid is not None else \
        next((s for s in plan.sorties.values() if s.started), None)
    if frag is None:
        return None, ["NO_FRAGMENT"], catalog
    base, pool = _skeleton(plan, inst)
    pool = [p for p in pool if p not in state.delivered]
    for s in base.sorties.values():
        if s.sid != frag.sid and s.handover:
            rv = s.rec_vid
            if rv in base.visits:
                _place_handover_g(base, inst, base.visits[rv].truck, rv, list(s.handover))
                for p in s.handover:
                    if p in pool:
                        pool.remove(p)
    pool = list(dict.fromkeys(list(extra_pool or []) + pool))   # 去重：同一票只能插入一次
    if catalog is None:
        catalog = RecoveryCatalog(base, frag, inst, strategy, state, ground_required)
    catalog.base_plan = base
    catalog.pool = pool
    reasons: list[str] = []
    best: RecoveryOption | None = None
    best_by_truck: dict[str, float] = {}
    cap = max_candidates
    if cap is None:
        cap = max(40, int(0.25 * (budget.eval_limit if budget and budget.eval_limit else 250)))
    tried = 0
    # 初始份额用尽但还没有任何可行解时，继续在共同预算内展开（不提前宣告无解）
    while (tried < cap or best is None) and (budget is None or budget.evals_left() > 0):
        entries = catalog.next_entries(1)
        if not entries:
            break
        entry = entries[0]
        tried += 1
        catalog.n_evaluated += 1
        catalog.covered_trucks.add(entry["truck"])
        catalog.covered_customers.add(entry["ref"] if entry["support"]
                                      else base.visits[entry["ref"]].customer)
        catalog.covered_subsets.add(len(entry["served"]))
        cands = build_candidates(base, pool, frag.sid, entry, inst, phys, state, H,
                                 ground_required)
        if not cands:
            reasons.append("BUILD_FAILED")
            continue
        for cand in cands:
            if budget is not None and budget.evals_left() <= 0:
                break
            if stats is not None and budget is not None:
                ev = eval_counted(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
                if ev is None:
                    break
            else:
                ev = evaluate_plan(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE")
            if ev.feasible:
                opt = RecoveryOption(cand, ev,
                                     f"truck={entry['truck']},rv={cand.sorties[frag.sid].rec_vid},"
                                     f"served={len(entry['served'])}", entry["truck"],
                                     cand.sorties[frag.sid].rec_vid, len(entry["served"]),
                                     list(cand.sorties[frag.sid].handover))
                if best is None or (ev.cost or 0) < (best.ev.cost or 0):
                    best = opt
                best_by_truck[entry["truck"]] = min(best_by_truck.get(entry["truck"], float("inf")),
                                                    ev.cost or 0)
                break
            else:
                reasons.append(ev.violations[0] if ev.violations else ev.status)
    if best is not None:
        best.description += "|" + ",".join(f"{k}:{v:.2f}" for k, v in sorted(best_by_truck.items()))
    return best, reasons[:20], catalog
