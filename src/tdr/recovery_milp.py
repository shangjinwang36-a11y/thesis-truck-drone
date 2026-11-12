"""变体 B：失败后“接机决策”用一个小型 MILP（HiGHS）精确求解.

要决定的东西（对应规范 4.2/4.5/7.4）：
  * 哪辆合格卡车来接（S：只能是原放飞车；X：任意在班车辆）；
  * 在哪个停靠点接（该车残段路线上已有的访问，或新插入的支援访问，客户点均可）；
  * 机上其余可空送的票继续送哪几张（保持原顺序），其余随失败票一起带回、由接收车地送；
  * 带回的票在哪里地送（接机点本客户，或接机后最小绕行插入）。
残段路线保持不动（固定），MILP 只做上面这个“小决策”，然后把前 K 个最优解交给完整评价器核验，
最好的作为 ALNS 的起点之一（见 recovery.initial_recovery）。

模型是一个**线性代理模型**：用几何距离、固定时长和线性化的悬停/等待项估计成本（元），
并带一条能量上界约束；最终是否可行、真实成本一律由完整评价器 evaluate_plan 判定。
所以它是“代理模型下的精确最优 + 完整评价核验”，不是对整个问题的全局最优证明.

变量（m = 机上还可继续空送的票数，通常 0–3）：
  x[v]    选择接机停靠点 v（恰好选一个）
  z[i]    第 i 张余票继续空送（1）还是带回（0）
  u[i,j]  无人机路径弧：起点(0) → 被服务的余票 → 接机点；e[i,v] 为最后一段弧（i → 接机点 v）
  t[i,v]  线性化变量，表示“余票 i 被带回、且在 v 接机”→ 产生地送成本
  w1, w2  悬停等车时间 / 卡车等无人机的时间（≥0）
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .config import PhysicalConfig
from .data import Instance
from .plan import Plan, Sortie
from .schedule import StartState


@dataclass
class Stop:
    truck: str
    support: bool
    ref: object           # 既有访问 vid，或支援访问的客户 ID
    customer: str
    pos: tuple[float, float]
    arrival: float        # 卡车到达时刻估计
    cost: float           # 在此接机的卡车侧成本（绕行 + R/U 司机工时）
    after_nodes: list[tuple[float, float]]   # 接机点之后的卡车路径节点（用于估计地送绕行）
    after_customers: list[str]
    idx: int              # 既有访问在路线中的下标 / 支援访问的插入位置


@dataclass
class MilpResult:
    entries: list[dict] = field(default_factory=list)
    status: str = "NOT_RUN"
    objective: list[float] = field(default_factory=list)
    n_stops: int = 0
    n_vars: int = 0
    n_solves: int = 0
    wall_s: float = 0.0


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _truck_timeline(res: Plan, inst: Instance, phys: PhysicalConfig, state: StartState,
                    truck: str) -> tuple[list[float], list[float]]:
    """估计残段路线上各访问的到达/离开时刻（只用于代理成本，不用于可行性判定）."""
    route = res.routes.get(truck, [])
    v = phys.truck_speed_m_s
    t = state.t0
    pos = state.truck_start_pos.get(truck, (inst.depot_x, inst.depot_y))
    arr, dep = [], []
    for i, vid in enumerate(route):
        vis = res.visits[vid]
        c = inst.customer(vis.customer)
        if i == 0 and state.truck_fixed_first.get(truck):
            t = state.t0 + state.truck_first_travel_s.get(truck, 0.0)
        else:
            t = t + _d(pos, (c.x, c.y)) / v
        arr.append(t)
        n_launch = sum(1 for s in res.sorties.values() if s.launch_vid == vid and not s.started)
        n_rec = sum(1 for s in res.sorties.values() if s.rec_vid == vid)
        dwell = (phys.ground_service_s * len(vis.ground) + phys.prepare_s * n_launch
                 + (phys.recovery_s + phys.handover_s) * n_rec)
        t = t + dwell
        dep.append(t)
        pos = (c.x, c.y)
    return arr, dep


def release_credit(res: Plan, frag: Sortie, inst: Instance, phys: PhysicalConfig,
                   state: StartState) -> tuple[int | None, float]:
    """第四轮 H4：原回收访问 rv0 一旦不再接机，原车省下的成本（接机点不是 rv0 的方案共享该项）.

    = R/U 司机工时；若 rv0 除接机外没有别的任务（地送票只含将被移交的票、无放飞、无其他回收），
    则整个访问被清理，还省去绕行里程与驾驶工时。这是跨车(及同车异点)接机的主要收益来源，
    旧代理成本漏计了它。
    """
    rv0 = frag.rec_vid
    vis = res.visits.get(rv0)
    if vis is None:
        return None, 0.0
    ru = phys.recovery_s + phys.handover_s
    credit = phys.wage_per_s * ru
    moving = set(frag.handover) | set(frag.air)
    other_ground = [p for p in vis.ground if p not in moving]
    others = [s for s in res.sorties.values()
              if s.sid != frag.sid and (s.rec_vid == rv0 or (s.launch_vid == rv0 and not s.started))]
    route = res.routes.get(vis.truck, [])
    if other_ground or others or rv0 not in route:
        return rv0, credit
    i = route.index(rv0)
    if i == 0 and state.truck_fixed_first.get(vis.truck):
        return rv0, credit
    depot = (inst.depot_x, inst.depot_y)
    c0 = inst.customer(vis.customer)
    prev = state.truck_start_pos.get(vis.truck, depot) if i == 0 else \
        (inst.customer(res.visits[route[i - 1]].customer).x, inst.customer(res.visits[route[i - 1]].customer).y)
    nxt = depot if i == len(route) - 1 else \
        (inst.customer(res.visits[route[i + 1]].customer).x, inst.customer(res.visits[route[i + 1]].customer).y)
    det = _d(prev, (c0.x, c0.y)) + _d((c0.x, c0.y), nxt) - _d(prev, nxt)
    credit += phys.c_km * det / 1000.0 + phys.wage_per_s * det / phys.truck_speed_m_s
    return rv0, credit


def build_stops(res: Plan, frag: Sortie, inst: Instance, phys: PhysicalConfig,
                state: StartState, strategy: str) -> list[Stop]:
    launch = frag.launch_truck or frag.truck
    rv0, credit0 = release_credit(res, frag, inst, phys, state)
    trucks = [launch] if strategy == "S" else sorted(res.routes)
    depot = (inst.depot_x, inst.depot_y)
    v = phys.truck_speed_m_s
    ru = phys.recovery_s + phys.handover_s
    stops: list[Stop] = []
    for k in trucks:
        route = res.routes.get(k, [])
        if not route and k != launch:
            continue                       # 已收班/未出库的车不为救援额外启用（规范 4.3）
        arr, dep = _truck_timeline(res, inst, phys, state, k)
        pts = [(inst.customer(res.visits[x].customer).x, inst.customer(res.visits[x].customer).y)
               for x in route]
        custs = [res.visits[x].customer for x in route]
        start_pos = state.truck_start_pos.get(k, depot)
        # --- 既有访问 ---
        for i, vid in enumerate(route):
            after = pts[i + 1:] + [depot]
            stops.append(Stop(k, False, vid, custs[i], pts[i], arr[i], phys.wage_per_s * ru,
                              [pts[i]] + after, [custs[i]] + custs[i + 1:] + [""], i))
        # --- 支援访问：每个客户一个最小绕行插入位置（与 recovery._insert_support 同规则）---
        min_pos = state.truck_min_insert.get(k, 0)
        have = {vv.customer for vv in (res.visits[x] for x in route)}
        for c in inst.customers:
            if c.customer_id in have:
                continue          # 第四轮：该车已有同客户访问 → 既有访问更优，不再生成重复的支援访问占 top-K
            cp = (c.x, c.y)
            best = None
            for i in range(min_pos, len(route) + 1):
                prev = start_pos if i == 0 else pts[i - 1]
                nxt = depot if i == len(route) else pts[i]
                det = _d(prev, cp) + _d(cp, nxt) - _d(prev, nxt)
                if best is None or det < best[0]:
                    best = (det, i, prev)
            det, i, prev = best
            t_prev = state.t0 if i == 0 else dep[i - 1]
            a = t_prev + _d(prev, cp) / v
            cost = phys.c_km * det / 1000.0 + phys.wage_per_s * (det / v + ru)
            after = [cp] + pts[i:] + [depot]
            stops.append(Stop(k, True, c.customer_id, c.customer_id, cp, a, cost, after,
                              [c.customer_id] + custs[i:] + [""], i))
    for s_ in stops:
        if not (not s_.support and s_.ref == rv0):
            s_.cost -= credit0          # 原回收访问不再接机：原车省下 R/U 工时(及整段绕行)
    return stops


def _ground_cost(stop: Stop, parcel_customer: str, cpos: tuple[float, float],
                 phys: PhysicalConfig) -> float:
    """在 stop 接机后，由接收车地送一票的估计成本（同点：只有 G 工时；否则最小绕行插入）."""
    g = phys.wage_per_s * phys.ground_service_s
    if parcel_customer == stop.customer:
        return g
    if parcel_customer in stop.after_customers[1:]:
        return g                            # 之后路线本来就会经过该客户
    best = None
    nodes = stop.after_nodes
    for a, b in zip(nodes, nodes[1:]):
        det = _d(a, cpos) + _d(cpos, b) - _d(a, b)
        if best is None or det < best:
            best = det
    best = best or 0.0
    return g + phys.c_km * best / 1000.0 + phys.wage_per_s * best / phys.truck_speed_m_s


def solve_recovery_milp(res: Plan, frag_sid: int, inst: Instance, phys: PhysicalConfig,
                        state: StartState, strategy: str, ground_required: set[str],
                        top_k: int = 6, time_limit_s: float = 3.0,
                        max_support: int = 12) -> MilpResult:
    t_wall = time.perf_counter()
    out = MilpResult()
    frag = res.sorties.get(frag_sid)
    if frag is None or frag.start_pos is None:
        out.status = "NO_FRAGMENT"
        return out
    ds = state.drone_start.get(frag.drone)
    e0 = ds.energy if ds is not None else state.drone_energy.get(frag.drone, phys.e_cap)
    rem = [p for p in frag.air if p not in ground_required]       # 可继续空送的余票（保持顺序）
    fixed_back = [p for p in frag.handover] + [p for p in frag.air if p in ground_required]
    m = len(rem)
    stops = build_stops(res, frag, inst, phys, state, strategy)
    # 预筛选（不改变可行域的下界剪枝）：无人机不论怎么飞，到该点的能量下界都超过剩余电量的点直接去掉；
    # 支援访问只保留离无人机当前位置最近的 max_support 个客户（每车），控制 MILP 规模。
    m_min = sum(inst.parcel_mass[p] for p in fixed_back)
    lim = e0 - phys.e_min + phys.energy_tol
    keep: list[Stop] = []
    sup_by_truck: dict[str, list[Stop]] = {}
    for s_ in stops:
        if phys.fly_energy_kwh(_d(frag.start_pos, s_.pos), m_min) > lim:
            continue
        if s_.support:
            sup_by_truck.setdefault(s_.truck, []).append(s_)
        else:
            keep.append(s_)
    for k_, lst in sup_by_truck.items():
        lst.sort(key=lambda q: _d(frag.start_pos, q.pos))
        keep.extend(lst[:max_support])
    stops = keep
    V = len(stops)
    out.n_stops = V
    if V == 0:
        out.status = "NO_STOPS"
        return out
    mass = {p: inst.parcel_mass[p] for p in rem + fixed_back}
    M_tot = sum(mass.values())
    nodes = [frag.start_pos] + [(inst.customer(inst.parcel_to_customer[p]).x,
                                 inst.customer(inst.parcel_to_customer[p]).y) for p in rem]
    mass_out = [M_tot] + [max(0.0, M_tot - mass[p]) for p in rem]
    vd = phys.drone_speed_m_s
    c_e = phys.cost_depot_kwh

    # ---- 变量编号 ----
    idx: dict[tuple, int] = {}
    def new(key):
        idx[key] = len(idx)
        return idx[key]
    for vi in range(V):
        new(("x", vi))
    for i in range(1, m + 1):
        new(("z", i))
    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            new(("u", i, j))
    for i in range(m + 1):
        for vi in range(V):
            new(("e", i, vi))
    for i in range(1, m + 1):
        for vi in range(V):
            new(("t", i, vi))
    new(("w1",))
    new(("w2",))
    n = len(idx)
    out.n_vars = n
    cost = np.zeros(n)
    integrality = np.zeros(n)
    lb = np.zeros(n)
    ub = np.ones(n)
    for key, j in idx.items():
        if key[0] in ("x", "z", "u", "e"):
            integrality[j] = 1
    ub[idx[("w1",)]] = 1e5
    ub[idx[("w2",)]] = 1e5

    # ---- 成本系数 ----
    p_h = phys.hover_power(M_tot)
    serv_e = phys.hover_energy_kwh(phys.air_service_s, M_tot)
    g_fixed = []
    for vi, s in enumerate(stops):
        cst = s.cost
        for p in fixed_back:
            c = inst.customer(inst.parcel_to_customer[p])
            cst += _ground_cost(s, c.customer_id, (c.x, c.y), phys)
        cost[idx[("x", vi)]] = cst
        g_fixed.append(cst)
    for i in range(1, m + 1):
        cost[idx[("z", i)]] = c_e * serv_e
    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            cost[idx[("u", i, j)]] = c_e * phys.fly_energy_kwh(_d(nodes[i], nodes[j]), mass_out[i])
        for vi, s in enumerate(stops):
            cost[idx[("e", i, vi)]] = c_e * phys.fly_energy_kwh(_d(nodes[i], s.pos), mass_out[i])
    for i in range(1, m + 1):
        c = inst.customer(inst.parcel_to_customer[rem[i - 1]])
        for vi, s in enumerate(stops):
            cost[idx[("t", i, vi)]] = _ground_cost(s, c.customer_id, (c.x, c.y), phys)
    cost[idx[("w1",)]] = c_e * p_h / 3600.0
    cost[idx[("w2",)]] = phys.wage_per_s

    # ---- 约束 ----
    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0
    def add(terms, lo_, hi_):
        nonlocal r
        for k_, v_ in terms:
            rows.append(r); cols.append(k_); vals.append(v_)
        lo.append(lo_); hi.append(hi_)
        r += 1
    add([(idx[("x", vi)], 1.0) for vi in range(V)], 1, 1)
    # 路径流
    out0 = [(idx[("u", 0, j)], 1.0) for j in range(1, m + 1)] + [(idx[("e", 0, vi)], 1.0) for vi in range(V)]
    add(out0, 1, 1)
    for i in range(1, m + 1):
        add([(idx[("u", h, i)], 1.0) for h in range(i)] + [(idx[("z", i)], -1.0)], 0, 0)
        add([(idx[("u", i, j)], 1.0) for j in range(i + 1, m + 1)]
            + [(idx[("e", i, vi)], 1.0) for vi in range(V)] + [(idx[("z", i)], -1.0)], 0, 0)
    for vi in range(V):
        add([(idx[("e", i, vi)], 1.0) for i in range(m + 1)] + [(idx[("x", vi)], -1.0)], 0, 0)
    # t >= x - z
    for i in range(1, m + 1):
        for vi in range(V):
            add([(idx[("t", i, vi)], 1.0), (idx[("x", vi)], -1.0), (idx[("z", i)], 1.0)], 0, np.inf)
    # 时间：无人机抵达接机点的时刻 T_d；w1 = 悬停等车，w2 = 卡车等机
    def drone_time_terms(sign):
        terms = []
        for i in range(m + 1):
            for j in range(i + 1, m + 1):
                terms.append((idx[("u", i, j)], sign * _d(nodes[i], nodes[j]) / vd))
            for vi, s in enumerate(stops):
                terms.append((idx[("e", i, vi)], sign * _d(nodes[i], s.pos) / vd))
        for i in range(1, m + 1):
            terms.append((idx[("z", i)], sign * phys.air_service_s))
        return terms
    A_terms = [(idx[("x", vi)], s.arrival - state.t0) for vi, s in enumerate(stops)]
    # w1 >= A - T_d ; w2 >= T_d - A
    add([(idx[("w1",)], 1.0)] + [(k_, -v_) for k_, v_ in A_terms] + drone_time_terms(+1.0), 0, np.inf)
    add([(idx[("w2",)], 1.0)] + drone_time_terms(-1.0) + [(k_, v_) for k_, v_ in A_terms], 0, np.inf)
    # 能量上界：飞行 + 服务悬停 + 悬停等车 ≤ 剩余电量 − E_min
    en_terms = []
    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            en_terms.append((idx[("u", i, j)], phys.fly_energy_kwh(_d(nodes[i], nodes[j]), mass_out[i])))
        for vi, s in enumerate(stops):
            en_terms.append((idx[("e", i, vi)], phys.fly_energy_kwh(_d(nodes[i], s.pos), mass_out[i])))
    for i in range(1, m + 1):
        en_terms.append((idx[("z", i)], serv_e))
    en_terms.append((idx[("w1",)], p_h / 3600.0))
    add(en_terms, -np.inf, e0 - phys.e_min + phys.energy_tol)
    A = coo_matrix((vals, (rows, cols)), shape=(r, n)).tocsr()
    base_cons = (A, np.array(lo), np.array(hi))

    # ---- 求 top-K（逐个加“排除已出现的 (x,z) 组合”割）----
    cuts: list[tuple[list[int], list[int], int]] = []
    status_all = []
    for k in range(top_k):
        if cuts:
            rr, cc, vv, lo2, hi2 = [], [], [], [], []
            for ri, (ones, zeros, _) in enumerate(cuts):
                for j in zeros:
                    rr.append(ri); cc.append(j); vv.append(1.0)
                for j in ones:
                    rr.append(ri); cc.append(j); vv.append(-1.0)
                lo2.append(1 - len(ones)); hi2.append(np.inf)
            Ac = coo_matrix((vv, (rr, cc)), shape=(len(cuts), n)).tocsr()
            from scipy.sparse import vstack
            AA = vstack([base_cons[0], Ac]).tocsr()
            LL = np.concatenate([base_cons[1], np.array(lo2)])
            UU = np.concatenate([base_cons[2], np.array(hi2)])
        else:
            AA, LL, UU = base_cons
        res_m = milp(cost, constraints=LinearConstraint(AA, LL, UU), integrality=integrality,
                     bounds=Bounds(lb, ub), options={"time_limit": time_limit_s, "disp": False})
        out.n_solves += 1
        status_all.append(int(res_m.status))
        if res_m.x is None or res_m.status not in (0, 1):
            break
        xs = res_m.x
        vi = int(np.argmax([xs[idx[("x", q)]] for q in range(V)]))
        zs = [int(round(xs[idx[("z", i)]])) for i in range(1, m + 1)]
        s = stops[vi]
        served = [rem[i] for i in range(m) if zs[i] == 1]
        out.entries.append({"truck": s.truck, "kind": "support" if s.support else "visit",
                            "ref": s.ref, "support": s.support, "served": served})
        out.objective.append(float(res_m.fun))
        ones = [idx[("x", vi)]] + [idx[("z", i + 1)] for i in range(m) if zs[i] == 1]
        zeros = [idx[("z", i + 1)] for i in range(m) if zs[i] == 0]
        cuts.append((ones, zeros, vi))
        if res_m.status == 1:               # 触及时限：已有最好解，不再继续
            break
    # 第四轮 H4：X 每辆合格的其他车再各取一个最优方案(top-K 常被同车方案占满，跨车最优方案进不了评价)。
    # S 只有一辆合格车，天然不触发；X 追加的是“新增候选”，其评价同样计入同一恢复预算。
    if strategy != "S" and out.entries and status_all and all(s_ == 0 for s_ in status_all):
        have_trucks = {e_["truck"] for e_ in out.entries}
        for tk in sorted({s_.truck for s_ in stops} - have_trucks):
            row = coo_matrix(([1.0] * sum(1 for s_ in stops if s_.truck == tk),
                              ([0] * sum(1 for s_ in stops if s_.truck == tk),
                               [idx[("x", q)] for q, s_ in enumerate(stops) if s_.truck == tk])),
                             shape=(1, n)).tocsr()
            from scipy.sparse import vstack as _vs
            AA = _vs([base_cons[0], row]).tocsr()
            LL = np.concatenate([base_cons[1], [1.0]])
            UU = np.concatenate([base_cons[2], [1.0]])
            r_ = milp(cost, constraints=LinearConstraint(AA, LL, UU), integrality=integrality,
                      bounds=Bounds(lb, ub), options={"time_limit": time_limit_s, "disp": False})
            out.n_solves += 1
            if r_.x is None or r_.status not in (0, 1):
                continue
            xs = r_.x
            vi = int(np.argmax([xs[idx[("x", q)]] for q in range(V)]))
            zs = [int(round(xs[idx[("z", i)]])) for i in range(1, m + 1)]
            s_ = stops[vi]
            out.entries.append({"truck": s_.truck, "kind": "support" if s_.support else "visit",
                                "ref": s_.ref, "support": s_.support,
                                "served": [rem[i] for i in range(m) if zs[i] == 1]})
            out.objective.append(float(r_.fun))
    out.status = "OPTIMAL" if status_all and all(s == 0 for s in status_all) else \
        ("NO_FEASIBLE" if not out.entries else "FEASIBLE_LIMIT")
    out.wall_s = time.perf_counter() - t_wall
    return out
