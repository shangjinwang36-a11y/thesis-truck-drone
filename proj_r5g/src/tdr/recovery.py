"""恢复初始构造：同点/异点、原车/跨车、机上余票子集、R-U-G 闭包（第7.4节）.

【第一轮修改（修复1）】初始解不再"清空未来重建"，而是以**名义残段**（truncate 之后保持原样的
未执行部分）为底板，只做最小改动：给失败票安排一次回收 + 回收后的地面送达。
  * 候选 RESIDUAL：保持原计划的回收访问不变（S/X 都允许，只要回收车合规）；
  * 候选 CATALOG：在残段底板上换接机车/接机点/继续配送子集（仍不清空其余任务）；
  * 候选 REBUILD：旧的"清空重建"路径，只作为对照候选，不再是默认起点。
三类候选都评价（计入"初始化预算"，与 ALNS 主循环预算分开），取最优者作为 ALNS 起点，
因此 ALNS 返回的解永远不会比 RESIDUAL 候选差。

候选目录按"接机车辆 → 接机位置（既有访问或全客户支援访问）→ 继续配送子集"
的稳定顺序**持续展开**，由统一预算决定本次评到哪一步；不再用固定候选上限。
每次求解释放一个 `RecoveryCatalog`，其游标可在 ALNS 的恢复邻域中继续前进，
从而保证"增加预算 → 覆盖更多接机车/接机客户/继续子集"。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .config import PhysicalConfig, home_truck
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


def _cleanup(plan: Plan, protect: set[int] | None = None) -> None:
    protect = protect or set()
    used = set(protect)
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
    frag.landed = False                  # 改派回收后默认不是降落等待(由 _landing_candidates 显式置位)
    if frag.launch_truck is None:
        frag.launch_truck = frag.truck
    frag.truck = rec_truck
    return handover


def _continue_subsets(rem: list[str]) -> list[list[str]]:
    """继续空送的票子集（稳定顺序）：空、单票、全集、全部前缀(第四轮 H4)、票数≤4 时的两两组合."""
    out: list[list[str]] = [[]] + [[p] for p in rem]
    if len(rem) >= 2:
        out.append(list(rem))
        out += [list(rem[:k]) for k in range(2, len(rem))]
        if len(rem) <= 4:
            out += [list(c) for c in itertools.combinations(rem, 2)]
    seen: set = set()
    uniq = []
    for x in out:
        if tuple(x) not in seen:
            seen.add(tuple(x))
            uniq.append(x)
    return uniq


# ---------------------------------------------------------------------------
# 持续展开的候选目录
# ---------------------------------------------------------------------------
class RecoveryCatalog:
    """稳定的候选枚举顺序 + 游标 + 覆盖统计.

    顺序：接机车辆（原放飞车优先，其余按到失败点距离）→ 接机位置（既有访问按距离，
    再对全部客户生成支援访问按距离）→ 继续配送子集（空集、单票、全集，票数≤4时补两票组合）。
    """

    def __init__(self, plan: Plan, frag: Sortie, inst: Instance, strategy: str,
                 state: StartState | None = None, ground_required: set[str] | None = None,
                 phys: PhysicalConfig | None = None, guard_n: int = 40, slot_aware: bool = False):
        self.phys = phys
        self.slot_aware = slot_aware      # 第五轮 v4：按接机车机位占用给估计成本加惩罚（S/X 同一公式）
        self.guard_n = guard_n      # X 的第一批评价必须包含 S 排序的前 guard_n 个候选（第二轮修复2）
        self._base_plan = plan
        self.frag = frag
        self.inst = inst
        self.strategy = strategy
        self.state = state
        self.ground_required = set(ground_required or set())
        # 第三轮：用真正的放飞车(launch_truck)；frag.truck 在一次恢复改派后是“接机车”
        self.launch_truck = frag.launch_truck or frag.truck or (state.drone_carrier.get(frag.drone, "t1")
                                           if state else home_truck(frag.drone))
        self.frag_pos = frag.start_pos or (inst.depot_x, inst.depot_y)
        self._gen = self._entries()
        self.covered_trucks: set[str] = set()
        self.covered_customers: set[str] = set()
        self.covered_subsets: set[int] = set()
        self.n_generated = 0
        self.n_evaluated = 0
        self.exhausted = False
        self.skip_keys: set[tuple] = set()      # 已作为 RESIDUAL 候选评价过的条目，不重复
        self.mode = "rebuild"                   # "residual"：在名义残段上做最小改动
        self.res_plan: Plan | None = None

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
        if (self.phys is not None and self.state is not None
                and self.frag.start_pos is not None):
            yield from self._entries_est()
            return
        yield from self._entries_dist()

    # -- 第二轮修复2：按“估计成本”排序，并保证 X 的第一批包含 S 的前 guard_n 名 --
    def _entries_est(self):
        from .recovery_milp import _d, _ground_cost, build_stops
        plan, frag, inst, phys, state = self._base_plan, self.frag, self.inst, self.phys, self.state
        rem = [p for p in frag.air if p not in self.ground_required]
        fixed_back = list(frag.handover) + [p for p in frag.air if p in self.ground_required]
        subsets = _continue_subsets(rem)
        stops = build_stops(plan, frag, inst, phys, state, "X")
        launch = self.launch_truck
        ds = state.drone_start.get(frag.drone)
        e0 = ds.energy if ds is not None else state.drone_energy.get(frag.drone, phys.e_cap)
        mass = {p: inst.parcel_mass[p] for p in rem + fixed_back}
        m_tot = sum(mass.values())
        p_h = phys.hover_power(m_tot)
        c_e = phys.cost_depot_kwh
        vd = phys.drone_speed_m_s
        ppos = {p: (inst.customer(inst.parcel_to_customer[p]).x,
                    inst.customer(inst.parcel_to_customer[p]).y) for p in rem + fixed_back}
        pcust = {p: inst.parcel_to_customer[p] for p in rem + fixed_back}
        occ: dict[str, int] = {}
        if self.slot_aware:
            from .moves import drone_carriers
            for d_, t_ in drone_carriers(plan, state).items():
                if d_ != frag.drone:
                    occ[t_] = occ.get(t_, 0) + 1
        slots_ = getattr(phys, "truck_drone_slots", 2)

        def est(stop, served: list[str]) -> float:
            cost = stop.cost
            for p in fixed_back + [q for q in rem if q not in served]:
                cost += _ground_cost(stop, pcust[p], ppos[p], phys)
            cur, m_cur, t_d, en = frag.start_pos, m_tot, 0.0, 0.0
            for p in served:
                d = _d(cur, ppos[p])
                en += phys.fly_energy_kwh(d, m_cur) + phys.hover_energy_kwh(phys.air_service_s, m_cur)
                t_d += d / vd + phys.air_service_s
                m_cur = max(0.0, m_cur - mass[p])
                cur = ppos[p]
            d = _d(cur, stop.pos)
            en += phys.fly_energy_kwh(d, m_cur)
            t_d += d / vd
            a = stop.arrival - state.t0
            w1, w2 = max(0.0, a - t_d), max(0.0, t_d - a)
            en += p_h * w1 / 3600.0
            cost += c_e * en + phys.wage_per_s * w2
            if en > e0 - phys.e_min + phys.energy_tol:
                cost += 1e4                  # 能量上界不满足：排到最后，但不删除（以完整评价为准）
            if self.slot_aware and occ.get(stop.truck, 0) + 1 > slots_:
                cost += 5e3                  # 接机车机位已满(其它机体占满)：排后，不删除（以完整评价为准）
            return cost

        items = []
        for st in stops:
            for served in subsets:
                key = (st.truck, st.ref, tuple(served))
                items.append((est(st, served), st.truck != launch, st.truck, str(st.ref),
                              tuple(served), key, st))
        items.sort(key=lambda x: (x[0], x[2], x[3], x[4]))
        s_list = [x for x in items if x[2] == launch]
        seen: set = set()

        def make(x):
            st = x[6]
            return {"truck": st.truck, "kind": "support" if st.support else "visit",
                    "ref": st.ref, "support": st.support, "served": list(x[4]), "est": x[0]}

        n_guard = 0
        trucks_ok = [launch] if self.strategy == "S" else None
        for x in s_list:                       # 先放 S 排序的前 guard_n 个（X、S 完全一致）
            if n_guard >= self.guard_n and self.strategy != "S":
                break
            if x[5] in seen or x[5] in self.skip_keys:
                continue
            seen.add(x[5])
            n_guard += 1
            self.n_generated += 1
            yield make(x)
        for x in (s_list if self.strategy == "S" else items):
            if x[5] in seen or x[5] in self.skip_keys:
                continue
            seen.add(x[5])
            self.n_generated += 1
            yield make(x)

    def _entries_dist(self):
        # 全局按"到失败点的距离"排序：各车的最远位置交错出现，避免某辆车独占预算
        plan = self._base_plan
        rem = [p for p in self.frag.air if p not in self.ground_required]
        subsets = _continue_subsets(rem)
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
                if key in seen or key in self.skip_keys:
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


def _assigned(plan: Plan) -> set[str]:
    out: set[str] = set()
    for v in plan.visits.values():
        out.update(v.ground)
    for so in plan.sorties.values():
        out.update(so.air)
        out.update(so.handover)
    return out


def _fixed_first_vids(plan: Plan, state: StartState) -> set[int]:
    """正在驶向的首个访问（已承诺的道路段）不得被清理."""
    out: set[int] = set()
    for truck, route in plan.routes.items():
        if route and state.truck_fixed_first.get(truck):
            out.add(route[0])
    return out


def _place_handover_guarded(plan: Plan, inst: Instance, truck: str, rv: int,
                            parcels: list[str]) -> list[str]:
    """同 _place_handover_g，但已经安排了地面交付的票不再重复安排（残段底板里可能已有）."""
    already: set[str] = set()
    for v in plan.visits.values():
        already.update(v.ground)
    todo = [p for p in parcels if p not in already]
    if not todo:
        return []
    return _place_handover_g(plan, inst, truck, rv, todo)


def prepare_residual(new_plan: Plan, inst: Instance) -> Plan:
    """名义残段底板：truncate 之后的计划原样保留（不清空任何未来任务）.

    只做一件事：其他已在飞残段（非本次失败航次）带的交接票，若还没有地送安排则补上。
    """
    base = new_plan.clone()
    for so in list(base.sorties.values()):
        if so.started and so.handover and so.rec_vid in base.visits:
            _place_handover_guarded(base, inst, base.visits[so.rec_vid].truck, so.rec_vid,
                                    list(so.handover))
    return base


def build_residual_candidate(res: Plan, frag_sid: int, entry: dict | None, inst: Instance,
                             phys: PhysicalConfig, state: StartState, ground_required: set[str],
                             strategy: str) -> list[Plan]:
    """在残段底板上构造一个"最小改动"恢复候选.

    entry=None  → RESIDUAL：保持残段原计划的回收访问不变，只给失败票/交接票补地送。
    entry=dict  → CATALOG：换接机车/接机点/继续配送子集；该无人机之后的未起飞航次整体释放重排
                  （回收点变了，原后续航次的放飞时刻/承运车不再成立），其余任务保持原样。
    规则：S 只能回收到原放飞车；X 可回收到任意车（含原放飞车）。
    返回候选列表（尝试不同的补位修复方式），可能为空。
    """
    cand = res.clone()
    f = cand.sorties.get(frag_sid)
    if f is None:
        return []
    launch_truck = f.launch_truck or f.truck
    if entry is None:
        rv = f.rec_vid
        if rv not in cand.visits:
            return []                      # 原回收访问已不存在 → 无法保持原样
        truck = cand.visits[rv].truck
        served = [p for p in f.air if p not in ground_required]
        changed = False
    else:
        truck = entry["truck"]
        if entry["support"]:
            rv = _insert_support(cand, inst, truck, entry["ref"],
                                 min_pos=state.truck_min_insert.get(truck, 0))
        else:
            rv = entry["ref"]
            if rv not in cand.visits or cand.visits[rv].truck != truck:
                return []
        served = list(entry["served"])
        changed = True
    if strategy == "S" and truck != launch_truck:
        return []
    freed_later: list[str] = []
    if changed:
        # 回收点变化：该机之后的未起飞航次释放，由修复器重排
        for sid in list(cand.drone_sorties.get(f.drone, [])):
            if sid == frag_sid:
                continue
            so = cand.sorties.get(sid)
            if so is None or so.started:
                continue
            freed_later.extend(so.air + so.handover)
            cand.remove_sortie(sid)
    hand = _set_recovery(cand, f, truck, rv, served)
    # 第二轮修复（跨车 bug）：失败票/未续飞票由机上交接给接机车。残段底板里这些票遗留在
    # 别的车（通常是原放飞车）上的旧地送安排必须先清除，否则货物保管冲突(G_CUSTODY)，
    # 所有跨车候选都不可行。
    hand_set = set(hand)
    # 第四轮 M4：同车残段里已预置的旧地送(接机点之前的访问)也要清除，否则“先送后接”被判 G_CUSTODY
    # (候选构造错误，不是真实约束)；统一清除后交接票全部重新排到接机点之后。
    for v in cand.visits.values():
        v.ground = [p for p in v.ground if p not in hand_set]
    if _place_handover_guarded(cand, inst, truck, rv, hand):
        return []
    protect = _fixed_first_vids(cand, state) | {rv}
    pool = [c.parcel_id for c in inst.customers
            if c.parcel_id not in state.delivered and c.parcel_id not in _assigned(cand)]
    mp = state.truck_min_insert or None
    attempts: list[Plan] = []
    if not pool:
        attempts.append(cand)
    else:
        c1, left = repair_greedy(cand.clone(), inst, phys, pool, forbid_air=ground_required,
                                 min_pos=mp, state=state)
        if not left:
            attempts.append(c1)
        attempts.append(repair_ground_append(cand.clone(), inst, phys, pool, mp, state)[0])
        attempts.append(repair_ground_only(cand.clone(), inst, phys, pool, mp, state)[0])
    for at in attempts:
        _cleanup(at, protect)
    return attempts


def build_catalog_candidates(cat: "RecoveryCatalog", entry: dict, inst: Instance,
                             phys: PhysicalConfig, state: StartState, H: float | None,
                             ground_required: set[str], frag_sid: int) -> list[Plan]:
    """ALNS 恢复邻域/初始化共用：按目录模式分派到"残段最小改动"或"清空重建"."""
    if cat.mode == "residual" and cat.res_plan is not None:
        return build_residual_candidate(cat.res_plan, frag_sid, entry, inst, phys, state,
                                        ground_required, cat.strategy)
    return build_candidates(cat.base_plan, cat.pool, frag_sid, entry, inst, phys, state, H,
                            ground_required)


def _first_feasible(cands: list[Plan], inst, phys, state, H, stats, budget):
    """按顺序评价候选，返回第一个可行者 (plan, ev)；预算耗尽返回 (None, None, True)."""
    reasons: list[str] = []
    for cand in cands:
        if budget is not None and budget.evals_left() <= 0:
            return None, None, True, reasons
        if stats is not None and budget is not None:
            ev = eval_counted(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
            if ev is None:
                return None, None, True, reasons
        else:
            ev = evaluate_plan(cand, inst, phys, state, H, "RECOVERY_INITIAL_BASE")
        if ev.feasible:
            return cand, ev, False, reasons
        reasons.append(ev.violations[0] if ev.violations else ev.status)
    return None, None, False, reasons


JOINT_EXTRA_EVALS = 60
LAND_EXTRA_EVALS = 120   # v6：降落等待候选额外额度(S/X 相同，仅 land_and_wait 开启时)      # 联合重选阶段额外评价额度（S/X 同一常数，记入初始化预算）


def _joint_target(plan: Plan, ev: Evaluation, frag_sid: int, done: set[int]) -> int | None:
    """从评价违规里找出需要“重选接机”的在飞航次：SWAP_CANNOT_FIX:<机体> 或 SLOT_OVER:<车>."""
    import re
    for v in ev.violations:
        m = re.match(r"SWAP_CANNOT_FIX:(d\d+)@", v)
        if m:
            for sid in plan.drone_sorties.get(m.group(1), []):
                so = plan.sorties.get(sid)
                if so is not None and so.started and sid != frag_sid and sid not in done:
                    return sid
        m = re.match(r"SLOT_OVER:(t\d+)@", v)
        if m:
            for sid in sorted(plan.sorties):
                so = plan.sorties[sid]
                if (so.started and sid != frag_sid and sid not in done and so.rec_vid in plan.visits
                        and plan.visits[so.rec_vid].truck == m.group(1)):
                    return sid
    return None



def _slot_relief_candidates(plan: Plan, ev: Evaluation, frag_sid: int, state: StartState,
                            max_n: int = 4) -> list[Plan]:
    """机位缓解修复（v4，S/X 同一规则）：评价报 SLOT_OVER:<车>@t 时，把该车上仍占着机位的“排队等放飞”的未起飞航次
    的放飞访问提前到路线上更早的访问(最多提前 2 个位置，不早于 truck_min_insert、不早于同机体上一航次的回收访问)，
    使其更早离车从而释放机位。候选交完整评价器核验。"""
    import re
    m = None
    for v in ev.violations:
        m = re.match(r"SLOT_OVER:(t\d+)@([0-9.]+)=", v)
        if m:
            break
    tl = getattr(ev, "timeline", None)
    if m is None or tl is None:
        return []
    T, t = m.group(1), float(m.group(2))
    route = plan.routes.get(T, [])
    low = (state.truck_min_insert or {}).get(T, 0)
    queued = sorted((tl.launch_times[sid][1], sid) for sid, so in plan.sorties.items()
                    if not so.started and so.truck == T and sid in tl.launch_times
                    and tl.launch_times[sid][1] > t - 1e-6 and so.launch_vid in route)
    out: list[Plan] = []
    for _, sid in queued:
        so = plan.sorties[sid]
        li = route.index(so.launch_vid)
        prev_rec = -1
        for q in plan.drone_sorties.get(so.drone, []):
            if q == sid:
                break
            qs = plan.sorties.get(q)
            if qs is not None and qs.rec_vid in route and plan.visits[qs.rec_vid].truck == T:
                prev_rec = max(prev_rec, route.index(qs.rec_vid))
        for back in (1, 2):
            ni = li - back
            if ni < max(low, prev_rec) or ni < 0:
                continue
            cand = plan.clone()
            cand.sorties[sid].launch_vid = route[ni]
            out.append(cand)
            if len(out) >= max_n:
                return out
    return out



def _landing_candidates(plan: Plan, tgt_sid: int, inst: Instance, phys: PhysicalConfig,
                        state: StartState, ground_required: set[str], strategy: str,
                        guard_n: int, n_scan: int = 200, max_n: int = 4) -> list[Plan]:
    """v6 变体(a) 降落等待候选（S/X 同一规则）：在飞/失败机降落在“下一个空送客户点”(无剩余空送票则取离当前位置最近的客户点)，
    回收访问就设在该客户点(由目录给出的接机车辆：S 仅原放飞车，X 任意车)，继续空送子集只能是 ∅ 或首票；
    落地等待零能耗、回收免 E_min 备用电量(电量仍须 ≥0)。候选交完整评价器核验。"""
    so = plan.sorties.get(tgt_sid)
    if so is None or not so.started:
        return []
    rem = [p for p in so.air if p not in ground_required]
    if rem:
        land_c = inst.parcel_to_customer[rem[0]]
    else:
        pos = so.start_pos or (inst.depot_x, inst.depot_y)
        land_c = min(inst.customers, key=lambda c: (math.hypot(c.x - pos[0], c.y - pos[1]), c.customer_id)).customer_id
    allowed = [[]] + ([[rem[0]]] if rem else [])
    cat = RecoveryCatalog(plan, so, inst, strategy, state, ground_required, phys=phys, guard_n=guard_n)
    out: list[Plan] = []
    for ent in cat.next_entries(n_scan):
        rc = ent["ref"] if ent["support"] else (plan.visits[ent["ref"]].customer if ent["ref"] in plan.visits else None)
        if rc != land_c or list(ent["served"]) not in allowed:
            continue
        for c in build_residual_candidate(plan, tgt_sid, ent, inst, phys, state, ground_required, strategy)[:2]:
            if tgt_sid in c.sorties:
                c.sorties[tgt_sid].landed = True
                out.append(c)
        if len(out) >= max_n:
            break
    return out



def _unlaunched_target(plan: Plan, ev: Evaluation, done_u: set[int]) -> int | None:
    """SWAP_CANNOT_FIX:<机体>@t 且该机在 t 对应的是“未起飞”航次(换电后仍能量不足)时，返回该航次 sid."""
    import re
    tl = getattr(ev, "timeline", None)
    for v in ev.violations:
        m = re.match(r"SWAP_CANNOT_FIX:(d\d+)@([0-9.]+):", v)
        if not m:
            continue
        d, t = m.group(1), float(m.group(2))
        sid_hit = None
        if tl is not None:
            for st in tl.drone_stages.get(d, []):
                if st.sid is not None and abs(st.start - t) < 0.06:
                    sid_hit = st.sid
                    break
        cands = [sid_hit] if sid_hit is not None else list(plan.drone_sorties.get(d, []))
        for sid in cands:
            so = plan.sorties.get(sid)
            if so is not None and not so.started and sid not in done_u:
                return sid
    return None


def _unlaunched_candidates(plan: Plan, sid: int, inst: Instance, phys: PhysicalConfig,
                           state: StartState, strategy: str) -> list[Plan]:
    """v7：对“未起飞但能量不可行”的航次生成修复候选（S/X 同一规则，仅回收点可选范围按策略限制）：
    ① 改回收访问(最近的 2 个访问；S 只限本放飞车，X 任意车)；② 丢掉最后一个空送客户转地面；③ 整个航次转地面。"""
    from .moves import repair_ground_only, repair_ground_append, remove_sortie_closure
    so = plan.sorties.get(sid)
    if so is None or so.started or not so.air:
        return []
    out: list[Plan] = []
    last = inst.customer(inst.parcel_to_customer[so.air[-1]])
    launch_truck = so.truck
    lv = plan.visits.get(so.launch_vid) if so.launch_vid is not None else None
    cand_v = []
    for vid, v in plan.visits.items():
        if vid == so.rec_vid or vid == so.launch_vid:
            continue
        if strategy == "S" and v.truck != launch_truck:
            continue
        if v.truck == launch_truck and lv is not None:
            route = plan.routes.get(launch_truck, [])
            if vid not in route or so.launch_vid not in route or route.index(vid) <= route.index(so.launch_vid):
                continue
        c = inst.customer(v.customer)
        cand_v.append((math.hypot(c.x - last.x, c.y - last.y), v.truck, vid))
    cand_v.sort()
    for _, _, vid in cand_v[:2]:
        c = plan.clone()
        c.sorties[sid].rec_vid = vid
        out.append(c)
    if len(so.air) >= 2:
        c = plan.clone()
        p = c.sorties[sid].air.pop()
        c, rem = repair_ground_only(c, inst, phys, [p], dict(state.truck_min_insert), state)
        if not rem:
            out.append(c)
    c = plan.clone()
    freed = remove_sortie_closure(c, sid, [])
    c, rem = repair_ground_only(c, inst, phys, freed, dict(state.truck_min_insert), state)
    if not rem:
        out.append(c)
    return out


def _joint_retarget(res: Plan, frag: Sortie, inst: Instance, phys: PhysicalConfig, state: StartState,
                    H: float | None, ground_required: set[str], strategy: str, stats, budget,
                    tried_entries: list[dict], info: dict, consider, guard_n: int,
                    slot_aware: bool = False, unlaunched: bool = False) -> bool:
    """第五轮·联合重选：失败机的回收方案找不到可行解、且违规来自“别的在飞无人机”(SWAP_CANNOT_FIX/SLOT_OVER)时，
    对这些在飞航次也重选接机车/接机点/继续子集（S 只能回原放飞车，X 任意车；同一目录/同一候选构造/同一预算规则）。
    贪心深度≤3，每层最多 3 个条目×2 种补位，评价计入初始化预算（额外额度 JOINT_EXTRA_EVALS，S/X 相同）。"""
    seeds: list[Plan] = []
    for ent in [None] + list(tried_entries[:2]):
        for c in build_residual_candidate(res, frag.sid, ent, inst, phys, state, ground_required, strategy)[:2]:
            seeds.append(c)
    seeds = seeds[:4]
    if phys.land_and_wait:
        for c in _landing_candidates(res, frag.sid, inst, phys, state, ground_required, strategy, guard_n)[:2]:
            seeds.append(c)
            info['landing_seeds'] = info.get('landing_seeds', 0) + 1
    if not seeds or budget is None:
        return False
    budget.eval_limit = (budget.eval_limit or 0) + JOINT_EXTRA_EVALS + (LAND_EXTRA_EVALS if (phys.land_and_wait or unlaunched) else 0)
    info["joint_used"] = True
    info["joint_retargets"] = 0
    for seed in seeds:
        plan_j = seed
        done: set[int] = set()
        done_u: set[int] = set()
        for _depth in range(3 + (2 if (phys.land_and_wait or unlaunched) else 0)):
            if budget.evals_left() <= 0:
                return False
            ev = eval_counted(plan_j, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
            if ev is None:
                return False
            if ev.feasible:
                fs = plan_j.sorties[frag.sid]
                consider(plan_j, ev, {"truck": plan_j.visits[fs.rec_vid].truck, "kind": "visit", "ref": fs.rec_vid,
                                      "support": False, "served": list(fs.air)}, "JOINT")
                return True
            tgt = _joint_target(plan_j, ev, frag.sid, done)
            if slot_aware and any(v.startswith('SLOT_OVER') for v in ev.violations):
                first_rel = None
                for cnd in _slot_relief_candidates(plan_j, ev, frag.sid, state):
                    if budget.evals_left() <= 0:
                        return False
                    ev2 = eval_counted(cnd, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
                    if ev2 is None:
                        return False
                    info["slot_relief_tries"] = info.get("slot_relief_tries", 0) + 1
                    if ev2.feasible:
                        fs = cnd.sorties[frag.sid]
                        info["slot_relief_ok"] = info.get("slot_relief_ok", 0) + 1
                        consider(cnd, ev2, {"truck": cnd.visits[fs.rec_vid].truck, "kind": "visit", "ref": fs.rec_vid,
                                            "support": False, "served": list(fs.air)}, "JOINT_SLOT")
                        return True
                    if first_rel is None:
                        first_rel = cnd
                if first_rel is not None and tgt is None:
                    plan_j = first_rel
                    continue
            if tgt is None and unlaunched:
                usid = _unlaunched_target(plan_j, ev, done_u)
                if usid is not None:
                    done_u.add(usid)
                    first_u = None
                    for cnd in _unlaunched_candidates(plan_j, usid, inst, phys, state, strategy):
                        if budget.evals_left() <= 0:
                            return False
                        ev2 = eval_counted(cnd, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
                        if ev2 is None:
                            return False
                        info["unlaunched_tries"] = info.get("unlaunched_tries", 0) + 1
                        if ev2.feasible:
                            fs = cnd.sorties[frag.sid]
                            info["unlaunched_ok"] = info.get("unlaunched_ok", 0) + 1
                            consider(cnd, ev2, {"truck": cnd.visits[fs.rec_vid].truck, "kind": "visit",
                                                "ref": fs.rec_vid, "support": False, "served": list(fs.air)},
                                     "JOINT_UNLAUNCHED")
                            return True
                        if first_u is None:
                            first_u = cnd
                    if first_u is not None:
                        plan_j = first_u
                        continue
            if tgt is None:
                break
            done.add(tgt)
            cat = RecoveryCatalog(plan_j, plan_j.sorties[tgt], inst, strategy, state, ground_required,
                                  phys=phys, guard_n=guard_n, slot_aware=slot_aware)
            first_inf = None
            for ent in cat.next_entries(3):
                for cnd in build_residual_candidate(plan_j, tgt, ent, inst, phys, state, ground_required,
                                                    strategy)[:2]:
                    if budget.evals_left() <= 0:
                        return False
                    ev2 = eval_counted(cnd, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
                    if ev2 is None:
                        return False
                    info["joint_retargets"] = info.get("joint_retargets", 0) + 1
                    if ev2.feasible:
                        fs = cnd.sorties[frag.sid]
                        consider(cnd, ev2, {"truck": cnd.visits[fs.rec_vid].truck, "kind": "visit",
                                            "ref": fs.rec_vid, "support": False, "served": list(fs.air)}, "JOINT")
                        return True
                    if first_inf is None:
                        first_inf = cnd
            first_land = None
            if phys.land_and_wait:
                for cnd in _landing_candidates(plan_j, tgt, inst, phys, state, ground_required, strategy,
                                               guard_n)[:3]:
                    if budget.evals_left() <= 0:
                        return False
                    ev2 = eval_counted(cnd, inst, phys, state, H, "RECOVERY_INITIAL_BASE", stats, budget)
                    if ev2 is None:
                        return False
                    info["landing_tries"] = info.get("landing_tries", 0) + 1
                    if ev2.feasible:
                        fs = cnd.sorties[frag.sid]
                        info["landing_ok"] = info.get("landing_ok", 0) + 1
                        consider(cnd, ev2, {"truck": cnd.visits[fs.rec_vid].truck, "kind": "visit",
                                            "ref": fs.rec_vid, "support": False, "served": list(fs.air)}, "JOINT_LAND")
                        return True
                    if first_land is None:
                        first_land = cnd
            if first_land is not None:
                first_inf = first_land          # 降落等待候选优先作为下一层底板(正常目录条目已全部不可行)
            if first_inf is None:
                break
            plan_j = first_inf
    return False


def initial_recovery(plan: Plan, state: StartState, inst: Instance, phys: PhysicalConfig,
                     strategy: str, ground_required: set[str],
                     max_candidates: int | None = None, H: float | None = None,
                     extra_pool: list[str] | None = None, frag_sid: int | None = None,
                     stats=None, budget: Budget | None = None,
                     catalog: RecoveryCatalog | None = None,
                     init_catalog_entries: int | None = None,
                     rescue_evals: int = 0, info: dict | None = None,
                     use_milp: bool = False, milp_top_k: int = 6, joint: bool = False,
                     slot_aware: bool = False, unlaunched: bool = False
                     ) -> tuple[RecoveryOption | None, list[str], RecoveryCatalog | None]:
    """恢复初始解（修复1）：RESIDUAL → CATALOG（残段最小改动）→ REBUILD（旧清空重建，对照）.

    budget 是**初始化预算**（S/X 相同上限），与 ALNS 主循环预算分开记账；
    若初始化预算内一个可行解都没有，再追加 rescue_evals 次评价继续找（两种策略同规则）。
    info（可选）被填入：residual_cost / residual_feasible / best_source / rebuild_cost / rescue_used。
    """
    info = info if info is not None else {}
    info.update({"residual_feasible": False, "residual_cost": None, "residual_z": None,
                 "rebuild_cost": None, "best_source": None, "rescue_used": False,
                 "n_catalog_entries": 0})
    frag = plan.sorties.get(frag_sid) if frag_sid is not None else \
        next((s for s in plan.sorties.values() if s.started), None)
    if frag is None:
        return None, ["NO_FRAGMENT"], catalog
    res = prepare_residual(plan, inst)
    if catalog is None:
        catalog = RecoveryCatalog(res, frag, inst, strategy, state, ground_required, phys=phys,
                                  guard_n=max(1, ((budget.eval_limit or 100) - 4) // 2), slot_aware=slot_aware)
    catalog.mode = "residual"
    catalog.res_plan = res
    # 重建路径（对照）所需的底板与待插入票
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
    pool = list(dict.fromkeys(list(extra_pool or []) + pool))
    catalog.base_plan = base
    catalog.pool = pool

    reasons: list[str] = []
    best: RecoveryOption | None = None
    best_src = None
    best_entry: dict | None = None
    best_s_eligible = False          # 第三轮：是否已有“S 资格”（接机车=原放飞车）的可行候选

    def _consider(cand_plan, ev, entry, src):
        nonlocal best, best_src, best_entry, best_s_eligible
        rv = cand_plan.sorties[frag.sid].rec_vid
        if cand_plan.visits[rv].truck == catalog.launch_truck:
            best_s_eligible = True
        opt = RecoveryOption(cand_plan, ev, f"{src}:truck={cand_plan.visits[rv].truck},rv={rv},"
                             f"served={len(cand_plan.sorties[frag.sid].air)}",
                             cand_plan.visits[rv].truck, rv, len(cand_plan.sorties[frag.sid].air),
                             list(cand_plan.sorties[frag.sid].handover))
        if best is None or (ev.cost or 0) < (best.ev.cost or 0) - 1e-9:
            best, best_src, best_entry = opt, src, entry

    def _rescue_check():
        # 初始化预算耗尽且还没有可行解：追加一次 rescue 额度（两种策略同规则）
        if (budget is not None and best is None and rescue_evals > 0
                and not info["rescue_used"] and budget.evals_left() <= 0):
            budget.eval_limit = (budget.eval_limit or 0) + rescue_evals
            info["rescue_used"] = True

    # ① RESIDUAL：保持原回收访问
    cands = build_residual_candidate(res, frag.sid, None, inst, phys, state, ground_required,
                                     strategy)
    if cands:
        cp, ev, exhausted, rs = _first_feasible(cands, inst, phys, state, H, stats, budget)
        reasons += rs
        if cp is not None:
            info["residual_feasible"] = True
            info["residual_cost"] = ev.cost
            info["residual_z"] = ev.z
            ent = {"truck": cp.visits[cp.sorties[frag.sid].rec_vid].truck, "kind": "visit",
                   "ref": cp.sorties[frag.sid].rec_vid, "support": False,
                   "served": list(cp.sorties[frag.sid].air)}
            catalog.skip_keys.add((ent["truck"], ent["ref"], tuple(ent["served"])))
            _consider(cp, ev, ent, "RESIDUAL")
            info["_residual"] = (cp, ev)
    else:
        reasons.append("RESIDUAL_NOT_AVAILABLE")

    # ②-B 变体 B：接机决策用小型 MILP（HiGHS）求前 K 个最优，再交给完整评价器核验
    if use_milp:
        from .recovery_milp import solve_recovery_milp
        mres = solve_recovery_milp(res, frag.sid, inst, phys, state, strategy, ground_required,
                                   top_k=milp_top_k)
        info["milp_status"] = mres.status
        info["milp_n_stops"] = mres.n_stops
        info["milp_n_options"] = len(mres.entries)
        info["milp_wall_s"] = mres.wall_s
        info["milp_surrogate_obj"] = list(mres.objective)
        info["milp_true_costs"] = []
        for ent in mres.entries:
            if budget is not None and budget.evals_left() <= 3:
                break
            key = (ent["truck"], ent["ref"], tuple(ent["served"]))
            if key in catalog.skip_keys:
                info["milp_true_costs"].append(None)
                continue
            catalog.skip_keys.add(key)
            cands = build_residual_candidate(res, frag.sid, ent, inst, phys, state,
                                             ground_required, strategy)
            if not cands:
                info["milp_true_costs"].append(None)
                continue
            cp, ev, _, rs = _first_feasible(cands, inst, phys, state, H, stats, budget)
            reasons += rs
            info["milp_true_costs"].append(ev.cost if cp is not None else None)
            if cp is not None:
                _consider(cp, ev, ent, "MILP")

    # ② CATALOG：残段底板上换接机车/点/继续子集（初始化预算内，S/X 同上限）
    cap = init_catalog_entries if init_catalog_entries is not None else \
        (max_candidates if max_candidates is not None else 10 ** 9)   # 实际由初始化预算限制
    tried = 0
    tried_entries: list[dict] = []
    while (tried < cap or best is None):
        _rescue_check()
        if budget is not None and budget.evals_left() <= 0:
            break
        if best is not None and budget is not None and budget.evals_left() <= 3:
            break                      # 给 REBUILD 对照候选留 3 次评价
        entries = catalog.next_entries(1)
        if not entries:
            break
        entry = entries[0]
        tried += 1
        if len(tried_entries) < 12:
            tried_entries.append(entry)
        info["n_catalog_entries"] = tried
        catalog.n_evaluated += 1
        catalog.covered_trucks.add(entry["truck"])
        catalog.covered_customers.add(entry["ref"] if entry["support"]
                                      else res.visits[entry["ref"]].customer)
        catalog.covered_subsets.add(len(entry["served"]))
        cands = build_residual_candidate(res, frag.sid, entry, inst, phys, state,
                                         ground_required, strategy)
        if not cands:
            reasons.append("BUILD_FAILED")
            continue
        cp, ev, exhausted, rs = _first_feasible(cands, inst, phys, state, H, stats, budget)
        reasons += rs
        if cp is not None:
            _consider(cp, ev, entry, "CATALOG")
        if exhausted:
            continue

    # ②-F 第二轮兜底：残段/目录/MILP 都没有可行解（常见于多次失败后剩余航次的充电/能量不可行），
    # 退回"清空未来重建"路径，对前若干个条目各试一次；S/X 规则相同、额外评价额度相同。
    # 第三轮修复(X⊇S 覆盖)：兜底的触发条件由“没有任何可行解”改为“没有 S 资格的可行解”。
    # S 只能用原放飞车，所以对 S 二者等价；但 X 若靠 X 专有的接机车找到可行解就会跳过兜底，
    # 而 S 在同样条件下会走兜底并得到更便宜的解，造成 X 的起始最优反而比 S 差。
    if not best_s_eligible and tried_entries and budget is not None:
        info["fallback_used"] = True
        budget.eval_limit = (budget.eval_limit or 0) + 24
        for ent in tried_entries:
            if budget.evals_left() <= 0:
                break
            rb = build_candidates(base, pool, frag.sid, ent, inst, phys, state, H, ground_required)
            if not rb:
                continue
            cp, ev, _, rs = _first_feasible(rb, inst, phys, state, H, stats, budget)
            reasons += rs
            if cp is not None:
                info["rebuild_cost"] = ev.cost
                _consider(cp, ev, ent, "REBUILD_FALLBACK")
                break

    # ②-J 第五轮：联合重选所有在飞无人机的接机（S/X 同一路径）；仅当仍无任何可行解时启用
    if (joint or phys.land_and_wait or unlaunched) and best is None and budget is not None:
        _joint_retarget(res, frag, inst, phys, state, H, ground_required, strategy, stats, budget,
                        tried_entries, info, _consider, catalog.guard_n, slot_aware, unlaunched)

    # ③ REBUILD：对照候选——用当前最优接机安排，但清空未来重建（旧做法）
    if best is not None and best_entry is not None and (budget is None or budget.evals_left() > 0):
        if best_entry["support"]:
            pass  # 重建路径用 build_candidates 的支援访问插入，同样支持
        rb = build_candidates(base, pool, frag.sid, best_entry, inst, phys, state, H,
                              ground_required)
        if rb:
            cp, ev, _, rs = _first_feasible(rb, inst, phys, state, H, stats, budget)
            if cp is not None:
                info["rebuild_cost"] = ev.cost
                _consider(cp, ev, best_entry, "REBUILD")
    if best is not None:
        info["best_source"] = best_src
        info["init_cost"] = best.ev.cost
    return best, reasons[:20], catalog
