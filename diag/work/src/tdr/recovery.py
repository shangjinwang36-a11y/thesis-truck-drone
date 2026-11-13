"""恢复初始构造：在名义残段上热启动（第7.4节）.

保留未受影响的地送和未起飞航次。只改受影响残段的继续子集、接机车和接机访问，
并为交接票补上真实 G。余票子集按“原承诺、立即回收、全部可空送、再按票数递增”
枚举；客户按稳定 ID 轮转。找到第一个完整可行后缀就交给 ALNS，其余候选由游标在
搜索过程中继续展开，避免用固定比例的评价预算把更大的 X 目录提前花掉。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .config import PhysicalConfig
from .data import Instance
from .evaluate import Evaluation, evaluate_plan
from .alns import Budget, eval_counted
from .moves import repair_greedy, repair_ground_only, repair_regret2
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


def _residual(plan: Plan, state: StartState) -> Plan:
    """复制当前剩余计划，只去掉已交付的地送，不清空未来任务。"""
    base = plan.clone()
    delivered = set(state.delivered)
    for v in base.visits.values():
        v.ground = [p for p in v.ground if p not in delivered]
    return base


def _assigned(plan: Plan, state: StartState) -> set[str]:
    assigned = set(state.delivered)
    for v in plan.visits.values():
        assigned.update(v.ground)
    for s in plan.sorties.values():
        assigned.update(s.air)
        assigned.update(s.handover)
    return assigned


def _unassigned(plan: Plan, inst: Instance, state: StartState) -> list[str]:
    assigned = _assigned(plan, state)
    return [c.parcel_id for c in inst.customers if c.parcel_id not in assigned]


def _release_following(plan: Plan, drone: str, frag_sid: int, carrier: str) -> None:
    """跨车回收之后，原车上尚未起飞的后续航次不再满足机体链，释放其包裹。"""
    sids = list(plan.drone_sorties.get(drone, []))
    if frag_sid not in sids:
        return
    for sid in sids[sids.index(frag_sid) + 1:]:
        s = plan.sorties.get(sid)
        if s is None or s.started:
            continue
        if s.truck == carrier:
            continue
        plan.remove_sortie(sid)


def _strip_parcels(plan: Plan, parcels: list[str]) -> None:
    ban = set(parcels)
    if not ban:
        return
    for v in plan.visits.values():
        if any(p in ban for p in v.ground):
            v.ground = [p for p in v.ground if p not in ban]


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
    """热启动枚举顺序 + 游标.

    子集：先保留当前可空送余票（原承诺），再立即回收（空集），再其余子集按票数、
    订单 ID 字典序。位置：原回收访问、失效客户，然后按客户 ID 轮转；车辆原放飞车优先。
    S 只产生原放飞车。
    """

    def __init__(self, plan: Plan, frag: Sortie, inst: Instance, strategy: str,
                 state: StartState | None = None, ground_required: set[str] | None = None):
        self._base_plan = plan
        self.frag = frag
        self.inst = inst
        self.strategy = strategy
        self.state = state
        self.ground_required = set(ground_required or set())
        self.launch_truck = frag.launch_truck or frag.truck or (
            state.drone_carrier.get(frag.drone, "t1") if state else f"t{int(frag.drone[1:])}")
        self.frag_pos = frag.start_pos or (inst.depot_x, inst.depot_y)
        self._gen = self._entries()
        self.covered_trucks: set[str] = set()
        self.covered_customers: set[str] = set()
        self.covered_subsets: set[int] = set()
        self.n_generated = 0
        self.n_evaluated = 0
        self.exhausted = False

    def _trucks(self, plan: Plan) -> list[str]:
        launch = self.launch_truck
        if self.strategy == "S":
            return [launch]
        rest = [t for t in sorted(plan.routes) if t != launch]
        return [launch] + rest

    def _subsets(self) -> list[list[str]]:
        rem = sorted(p for p in self.frag.air if p not in self.ground_required)
        full = list(rem)
        ordered = [full, []]
        seen = {tuple(full), tuple()}
        for k in range(1, len(rem)):
            for comb in itertools.combinations(rem, k):
                if comb not in seen:
                    ordered.append(list(comb))
                    seen.add(comb)
        return ordered

    def _focus_customer(self) -> str | None:
        if self.frag.handover:
            p = self.frag.handover[0]
            if p in self.inst.parcel_to_customer:
                return self.inst.parcel_to_customer[p]
        return None

    def _locations(self, plan: Plan, truck: str):
        """原回收访问、失效客户，再按客户 ID：先既有访问，再一个支援插入。"""
        route = plan.routes.get(truck, [])
        by_cust: dict[str, list[int]] = {}
        for vid in route:
            by_cust.setdefault(plan.visits[vid].customer, []).append(vid)
        customers = [c.customer_id for c in self.inst.customers]
        focus = self._focus_customer()
        if focus in customers:
            customers = [focus] + [c for c in customers if c != focus]
        rec = self.frag.rec_vid
        if rec in plan.visits and plan.visits[rec].truck == truck:
            yield False, rec, plan.visits[rec].customer
        for cust in customers:
            for vid in by_cust.get(cust, []):
                if vid == rec and plan.visits[vid].truck == truck:
                    continue
                yield False, vid, cust
            yield True, cust, cust

    def _entries(self):
        plan = self._base_plan
        seen = set()
        for served in self._subsets():
            for truck in self._trucks(plan):
                for support, ref, cust in self._locations(plan, truck):
                    key = (truck, support, ref, tuple(served))
                    if key in seen:
                        continue
                    seen.add(key)
                    self.n_generated += 1
                    yield {"truck": truck, "kind": "support" if support else "visit",
                           "ref": ref, "support": support, "served": list(served),
                           "customer": cust}

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
                     H: float | None, ground_required: set[str],
                     repair: str = "GREEDY_PROXY") -> list[Plan]:
    """在残段副本上只改受影响航次，并补上因此空出来的票。"""
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
    _strip_parcels(cand, list(f.air) + list(f.handover))
    hand = _set_recovery(cand, f, truck, rv, entry["served"])
    _release_following(cand, f.drone, f.sid, truck)
    _strip_parcels(cand, list(f.air) + list(hand))
    gerr = _place_handover_g(cand, inst, truck, rv, hand)
    if gerr:
        return []
    need = _unassigned(cand, inst, state)
    extra = [p for p in pool if p not in _assigned(cand, state)]
    pool2 = list(dict.fromkeys(need + extra))
    mp = state.truck_min_insert or None
    if pool2:
        repair_fn = repair_greedy if repair == "GREEDY_PROXY" else repair_regret2
        cand, left = repair_fn(cand, inst, phys, pool2, forbid_air=ground_required,
                               min_pos=mp, state=state)
        if left:
            cand, left = repair_ground_only(cand, inst, phys, left, mp, state)
        if left:
            return []
    _cleanup(cand)
    return [cand]


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
    base = _residual(plan, state)
    # 其他已在交接清单里、但还没排 G 的残段，先补上地送，避免整张残段不完整
    for s in base.sorties.values():
        if s.sid == frag.sid or not s.handover or s.rec_vid not in base.visits:
            continue
        _place_handover_g(base, inst, base.visits[s.rec_vid].truck, s.rec_vid, list(s.handover))
    pool = list(dict.fromkeys(extra_pool or []))
    if catalog is None:
        catalog = RecoveryCatalog(base, base.sorties[frag.sid], inst, strategy, state,
                                  ground_required)
    catalog.base_plan = base
    catalog.pool = pool
    reasons: list[str] = []
    best: RecoveryOption | None = None
    cap = max_candidates
    tried = 0
    # 有可行初解就停止初始构造，把剩余评价留给 ALNS。没有可行解才继续游标，直到预算尽。
    while best is None and (budget is None or budget.evals_left() > 0):
        if cap is not None and tried >= cap:
            break
        entries = catalog.next_entries(1)
        if not entries:
            break
        entry = entries[0]
        tried += 1
        repair = "GREEDY_PROXY" if (tried % 2 == 1) else "REGRET2_PROXY"
        catalog.n_evaluated += 1
        catalog.covered_trucks.add(entry["truck"])
        if entry["support"]:
            catalog.covered_customers.add(entry["ref"])
        elif entry["ref"] in base.visits:
            catalog.covered_customers.add(base.visits[entry["ref"]].customer)
        catalog.covered_subsets.add(len(entry["served"]))
        cands = build_candidates(base, pool, frag.sid, entry, inst, phys, state, H,
                                 ground_required, repair=repair)
        if not cands:
            reasons.append("BUILD_FAILED")
            continue
        cand = cands[0]
        if budget is not None and budget.evals_left() <= 0:
            break
        if stats is not None and budget is not None:
            ev = eval_counted(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
            if ev is None:
                break
        else:
            ev = evaluate_plan(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE")
        if ev.feasible:
            best = RecoveryOption(cand, ev,
                                 f"truck={entry['truck']},rv={cand.sorties[frag.sid].rec_vid},"
                                 f"served={len(entry['served'])},repair={repair}", entry["truck"],
                                 cand.sorties[frag.sid].rec_vid, len(entry["served"]),
                                 list(cand.sorties[frag.sid].handover))
        else:
            reasons.append(ev.violations[0] if ev.violations else ev.status)
    return best, reasons[:20], catalog
