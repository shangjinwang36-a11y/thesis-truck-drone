"""第 8 轮：情景估价的 ALNS + 列池集合划分。

名义搜索的接受准则是

    情景均值 = 固定样本上各情景补救成本的平均

样本在搜索开始时抽一次，S 和 X 共用，和评价种子不是同一条随机流。
每个情景若有失败的空送票，就用一次完整评价核验补救计划，这一次计入名义预算。
没有失败的情景直接等于名义成本，不再评价。

补救是恢复逻辑的便宜近似：失败票从航次上拿下来，按与名义修复相同的地面插入代理放回卡车。
S 只能放回该航次的放飞车。X 可以放到绕行最小的任意卡车。不新开空送。
补救计划不可行时，这一情景按名义成本加固定罚金计，罚金不是在评价种子上拟合的。

集合划分：S 用同车路线列，每个包裹恰好被一条列覆盖。
X 不用单车路线列。X 的一列是一个同步分量：一条跨车航次，加上它连着的两辆（或多辆）
卡车的整段路线和这两段路线上的同车航次。分量之间卡车、无人机、包裹都不得重叠。
主问题只提议“替换后卡车里程代理更短”的分量组合。拼回去之后必须再用同一组情景样本
重新评价，情景分没有变好就不接受。这一次完整评价和情景评价都计入同一份名义预算。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .hidden_world import GENERATOR_VERSION


def sample_failure_scenarios(case_id: str, parcel_ids, p: float, n: int, stream: int = 0) -> list[frozenset]:
    """名义搜索用的固定伯努利样本。

    哈希标签是 ``nominal-scenario``，不含策略，也不用评价种子。
    因此 S/X 看到同一批情景，而且这批情景不是回合里要揭示的那一批。
    """
    out = []
    ids = sorted(parcel_ids)
    for k in range(max(0, int(n))):
        failed = []
        for pid in ids:
            enc = json.dumps(
                [GENERATOR_VERSION, "nominal-scenario", case_id, int(stream), int(k), pid],
                ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            u = int.from_bytes(hashlib.sha256(enc).digest(), "big") / float(1 << 256)
            if u < p:
                failed.append(pid)
        out.append(frozenset(failed))
    return out


def _cache(alg) -> dict:
    box = getattr(alg, "_scenario_cache", None)
    if box is None:
        box = {}
        setattr(alg, "_scenario_cache", box)
    return box


def _fingerprint(plan) -> tuple:
    routes = tuple((t, tuple(plan.route_customers(t))) for t in sorted(plan.routes))
    # T03/T08a：放飞点和接机点按（车, 路线位置, 客户）记入。以前只记接机车，
    # 同一航次换到同车另一访问放飞/回收时指纹不变，会错用别的计划的情景分。
    pos = {}
    for t, route in plan.routes.items():
        for i, vid in enumerate(route):
            pos[vid] = (t, i, plan.visits[vid].customer)
    # 地送也须区分同一客户的重复访问；使用路线位置，不依赖访问 ID。
    ground = tuple(sorted(
        (*pt, tuple(plan.visits[vid].ground)) for vid, pt in pos.items()))
    air = []
    for s in plan.sorties.values():
        launch_pt = pos.get(s.launch_vid) if s.launch_vid is not None else ("DEPOT",)
        rec_pt = pos.get(s.rec_vid)
        air.append((s.drone, str(s.truck), str(s.launch_truck), repr(launch_pt), repr(rec_pt), tuple(s.air),
                    tuple(s.handover), s.mode, round(float(s.lam), 5), int(s.launch_priority),
                    int(s.rec_priority), bool(s.landed), bool(s.started)))
    return (routes, ground, tuple(sorted(air)))


def _allow_cross(ctx) -> bool:
    return bool(getattr(getattr(ctx, "state", None), "nominal_cross", False))


def _scenarios_of(ctx) -> list[frozenset]:
    ready = getattr(ctx, "scenarios", None)
    if ready is None:
        inst = ctx.inst
        alg = ctx.alg
        ready = sample_failure_scenarios(
            inst.case_id, [c.parcel_id for c in inst.customers],
            float(getattr(alg, "scenario_p", 0.2) or 0.0),
            int(getattr(alg, "scenario_count", 2) or 0),
            int(getattr(alg, "scenario_stream", 0) or 0))
        ctx.scenarios = ready
    return ready


def _pool(ctx, allow_cross: bool) -> "ColumnPool":
    """列池挂在算法配置上，阶段1和阶段2共用。S 与 X 用 allow_cross 分开。"""
    alg = getattr(ctx, "alg", None)
    case_id = getattr(getattr(ctx, "inst", None), "case_id", "")
    key = (case_id, bool(allow_cross))
    pools = getattr(alg, "_column_pools", None) if alg is not None else None
    if pools is None:
        pools = {}
        if alg is not None:
            alg._column_pools = pools
    pool = pools.get(key)
    if pool is None or pool.allow_cross != allow_cross:
        pool = ColumnPool(allow_cross)
        pools[key] = pool
    return pool


def build_recourse(plan, failed_air: frozenset, inst, phys, allow_cross: bool):
    """把失败的空送票放回地面。S 只放回放飞车，X 选代理成本最低的车。"""
    from .moves import apply_ground, ground_candidates, parcel_delivery, remove_parcel
    rep = plan.clone()
    launch: dict[str, str | None] = {}
    pending = []
    for pid in sorted(failed_air):
        loc = parcel_delivery(rep, pid)
        if loc is None or loc[0] != "AIR":
            continue
        sortie = rep.sorties.get(loc[1])
        launch[pid] = None if sortie is None else sortie.truck
        pending.append(pid)
    freed: list[str] = []
    for pid in pending:
        if parcel_delivery(rep, pid) is None:
            continue
        before = len(freed)
        remove_parcel(rep, pid, freed)
        for q in freed[before:]:
            launch.setdefault(q, launch.get(pid))
    for pid in sorted(set(freed)):
        if parcel_delivery(rep, pid) is not None:
            continue
        cands = ground_candidates(rep, inst, phys, pid, state=None)
        home = launch.get(pid)
        if not allow_cross and home is not None:
            cands = [c for c in cands if c.truck == home]
        if not cands:
            continue
        apply_ground(rep, inst, pid, cands[0])
    return rep


def scenario_score(plan, ev, ctx) -> float | None:
    """情景均值。已经算过的计划结构不再评价。预算不够时返回 None，调用方改用真实成本。"""
    alg = ctx.alg
    if not getattr(alg, "scenario_aware", False) or getattr(ctx, "mode", None) != "nominal":
        return None
    if plan is None or ev is None or not ev.feasible or ev.cost is None:
        return None
    allow = _allow_cross(ctx)
    key = (plan.case_id, allow, _fingerprint(plan))
    cache = _cache(alg)
    hit = cache.get(key)
    if hit is not None:
        return hit
    physical = getattr(ctx, "live_budget", None)
    stats = getattr(ctx, "live_stats", None)
    if physical is None or stats is None:
        return None
    from .scenario_eval import scenario_budget_for
    budget = scenario_budget_for(alg, plan.case_id, allow, physical)
    air = frozenset(p for s in plan.sorties.values() for p in s.air)
    costs = []
    from .alns import eval_counted
    for sc in _scenarios_of(ctx):
        failed = sc & air
        if not failed:
            costs.append(float(ev.cost))
            continue
        if budget.evals_left() <= 0:
            return None
        repaired = build_recourse(plan, failed, ctx.inst, ctx.phys, allow)
        rev = eval_counted(repaired, ctx.inst, ctx.phys, ctx.state, ctx.H,
                           "SCENARIO_RECOURSE", stats, budget)
        if rev is None:
            return None
        stats.aud("SCENARIO", "evaluated")
        if not rev.feasible or rev.cost is None:
            stats.aud("SCENARIO", "infeasible")
            costs.append(float(ev.cost) + float(getattr(alg, "scenario_infeasible_penalty", 400.0) or 0.0))
        else:
            costs.append(float(rev.cost))
    if not costs:
        return None
    score = sum(costs) / len(costs)
    cache[key] = score
    _pool(ctx, allow).add_plan(plan, ctx.inst, ctx.phys)
    return score


def cached_scenario_cost(plan, ctx) -> float | None:
    """只读缓存，供退火使用，不再花评价。"""
    if plan is None or not getattr(ctx.alg, "scenario_aware", False) or getattr(ctx, "mode", None) != "nominal":
        return None
    allow = _allow_cross(ctx)
    return _cache(ctx.alg).get((plan.case_id, allow, _fingerprint(plan)))


@dataclass
class RouteColumn:
    truck: str
    sequence: tuple[str, ...]
    ground_at: tuple[tuple[str, ...], ...]
    sorties: tuple
    proxy: float
    covers: frozenset
    drones: frozenset
    visits: frozenset
    keep: bool = False

    @property
    def key(self) -> tuple:
        return (self.truck, self.sequence, self.ground_at, self.sorties)


@dataclass
class LinkColumn:
    drone: str
    launch_truck: str
    rec_truck: str
    launch_customer: str
    rec_customer: str
    air: tuple[str, ...]
    mode: str
    lam: float
    proxy: float
    covers: frozenset
    keep: bool = False

    @property
    def key(self) -> tuple:
        return (self.drone, self.launch_truck, self.rec_truck, self.launch_customer,
                self.rec_customer, self.air, self.mode, round(self.lam, 5))


def _path_proxy(inst, phys, sequence: tuple[str, ...]) -> float:
    depot = (inst.depot_x, inst.depot_y)
    prev = depot
    dist = 0.0
    for cust in sequence:
        c = inst.customer(cust)
        dist += math.hypot(c.x - prev[0], c.y - prev[1])
        prev = (c.x, c.y)
    dist += math.hypot(depot[0] - prev[0], depot[1] - prev[1])
    speed = phys.truck_speed_m_s if phys.truck_speed_m_s else 1.0
    return phys.c_km * dist / 1000.0 + phys.wage_per_s * dist / speed


def _truck_route_column(plan, inst, phys, truck: str) -> RouteColumn | None:
    route = plan.routes.get(truck) or []
    if not route:
        return None
    sequence = tuple(plan.visits[vid].customer for vid in route)
    ground_at = tuple(tuple(plan.visits[vid].ground) for vid in route)
    covers: set[str] = set()
    for parcels in ground_at:
        covers.update(parcels)
    index_of = {vid: i for i, vid in enumerate(route)}
    sorties = []
    drones: set[str] = set()
    for s in plan.sorties.values():
        if s.launch_vid not in index_of or s.rec_vid not in index_of:
            continue
        if plan.visits[s.rec_vid].truck != truck:
            continue
        li = index_of[s.launch_vid]
        ri = index_of[s.rec_vid]
        sorties.append((s.drone, li, ri, tuple(s.air), s.mode, float(s.lam)))
        drones.add(s.drone)
        covers.update(s.air)
    return RouteColumn(
        truck, sequence, ground_at, tuple(sorties), _path_proxy(inst, phys, sequence),
        frozenset(covers), frozenset(drones), frozenset(sequence))


def extract_columns(plan, inst, phys, allow_cross: bool):
    """S 的同车路线列。含跨车航次的计划不进入 S 的池。X 不走这里。"""
    from .evaluate import is_cross_sortie
    if allow_cross:
        return None
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        return None
    routes = []
    for truck in plan.routes:
        col = _truck_route_column(plan, inst, phys, truck)
        if col is not None:
            routes.append(col)
    return routes, []


@dataclass
class SyncColumn:
    """跨车同步分量：跨车航次和它两端卡车的整段路线绑在一起，不能拆开选。"""
    trucks: tuple[str, ...]
    routes: tuple
    crosses: tuple
    proxy: float
    covers: frozenset
    drones: frozenset
    keep: bool = False

    @property
    def key(self) -> tuple:
        return (self.trucks, tuple(r.key for r in self.routes), self.crosses)


def extract_sync(plan, inst, phys) -> list[SyncColumn]:
    """X 的列。没有跨车的计划不产生列；单车路线不是列。"""
    from .evaluate import is_cross_sortie
    crossed = [s for s in plan.sorties.values() if is_cross_sortie(plan, s)]
    if not crossed:
        return []
    parent: dict[str, str] = {}

    def find(t: str) -> str:
        parent.setdefault(t, t)
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for s in crossed:
        lt = plan.visits[s.launch_vid].truck
        rt = plan.visits[s.rec_vid].truck
        if lt == rt:
            continue
        union(lt, rt)
    by_root: dict[str, list] = {}
    for s in crossed:
        lt = plan.visits[s.launch_vid].truck
        rt = plan.visits[s.rec_vid].truck
        if lt == rt:
            continue
        by_root.setdefault(find(lt), []).append(s)
    out = []
    for members in by_root.values():
        trucks = tuple(sorted({plan.visits[s.launch_vid].truck for s in members}
                              | {plan.visits[s.rec_vid].truck for s in members}))
        if len(trucks) < 2:
            continue
        routes = []
        for truck in trucks:
            col = _truck_route_column(plan, inst, phys, truck)
            if col is None:
                routes = []
                break
            routes.append(col)
        if len(routes) != len(trucks):
            continue
        crosses = []
        covers = set()
        drones: set[str] = set()
        for col in routes:
            covers |= set(col.covers)
            drones |= set(col.drones)
        for s in members:
            lt = plan.visits[s.launch_vid].truck
            rt = plan.visits[s.rec_vid].truck
            crosses.append((s.drone, lt, rt, plan.visits[s.launch_vid].customer,
                            plan.visits[s.rec_vid].customer, tuple(s.air), s.mode, float(s.lam)))
            covers.update(s.air)
            drones.add(s.drone)
        crosses.sort()
        out.append(SyncColumn(
            trucks, tuple(routes), tuple(crosses),
            sum(col.proxy for col in routes), frozenset(covers), frozenset(drones)))
    return out


def milp_select(routes: list[RouteColumn], links: list[LinkColumn], parcels: list[str]):
    """集合划分。返回选中的路线列和连接列。不可行或求解失败时返回 None。

    连接列 y 要求：放飞车有一条选中路线包含放飞客户，回收车有一条选中路线包含回收客户。
    """
    if not routes or not parcels:
        return None
    cols: list[RouteColumn | LinkColumn] = list(routes) + list(links)
    n = len(cols)
    n_r = len(routes)
    c = np.array([col.proxy for col in cols], dtype=float)
    rows_i: list[int] = []
    cols_j: list[int] = []
    data: list[float] = []
    lb: list[float] = []
    ub: list[float] = []
    row = 0

    def add(pairs, lo, hi):
        nonlocal row
        for j, v in pairs:
            rows_i.append(row)
            cols_j.append(j)
            data.append(v)
        lb.append(lo)
        ub.append(hi)
        row += 1

    cover_of = []
    for col in cols:
        cover_of.append(col.covers)
    for pid in parcels:
        idx = [j for j, cov in enumerate(cover_of) if pid in cov]
        if not idx:
            return None
        add([(j, 1.0) for j in idx], 1.0, 1.0)
    trucks = sorted({col.truck for col in routes})
    for truck in trucks:
        idx = [j for j, col in enumerate(routes) if col.truck == truck]
        add([(j, 1.0) for j in idx], 0.0, 1.0)
    drones = set()
    for col in cols:
        if isinstance(col, LinkColumn):
            drones.add(col.drone)
        else:
            drones.update(col.drones)
    for drone in sorted(drones):
        idx = []
        for j, col in enumerate(cols):
            if isinstance(col, LinkColumn) and col.drone == drone:
                idx.append(j)
            elif isinstance(col, RouteColumn) and drone in col.drones:
                idx.append(j)
        if idx:
            add([(j, 1.0) for j in idx], 0.0, 1.0)
    for j, link in enumerate(links):
        launch_ok = [i for i, col in enumerate(routes)
                     if col.truck == link.launch_truck and link.launch_customer in col.visits]
        rec_ok = [i for i, col in enumerate(routes)
                  if col.truck == link.rec_truck and link.rec_customer in col.visits]
        if not launch_ok or not rec_ok:
            add([(n_r + j, 1.0)], 0.0, 0.0)
            continue
        add([(n_r + j, 1.0)] + [(i, -1.0) for i in launch_ok], -np.inf, 0.0)
        add([(n_r + j, 1.0)] + [(i, -1.0) for i in rec_ok], -np.inf, 0.0)
    A = coo_matrix((data, (rows_i, cols_j)), shape=(row, n))
    try:
        res = milp(c, integrality=np.ones(n), bounds=Bounds(0, 1),
                   constraints=LinearConstraint(A, np.array(lb), np.array(ub)),
                   options={"time_limit": 1.0})
    except Exception:
        return None
    if res.x is None:
        return None
    pick = [i for i, v in enumerate(res.x) if v > 0.5]
    chosen_routes = [routes[i] for i in pick if i < n_r]
    chosen_links = [links[i - n_r] for i in pick if i >= n_r]
    covered: list[str] = []
    for col in chosen_routes + chosen_links:
        covered.extend(col.covers)
    if sorted(covered) != sorted(parcels):
        return None
    per_truck: dict[str, int] = {}
    for col in chosen_routes:
        per_truck[col.truck] = per_truck.get(col.truck, 0) + 1
    if any(v > 1 for v in per_truck.values()):
        return None
    return chosen_routes, chosen_links


def assemble(routes: list[RouteColumn], links: list[LinkColumn], inst):
    """把选中的列拼成一份计划。访问点对不上、或同一架无人机被两条列使用时返回 None。"""
    from .plan import Plan
    plan = Plan(inst.case_id)
    loc: dict[tuple[str, str], int] = {}
    used: set[str] = set()
    for col in routes:
        if len(col.ground_at) != len(col.sequence):
            return None
        if used & set(col.drones):
            return None
        vids = []
        for cust, parcels in zip(col.sequence, col.ground_at):
            vid = plan.add_visit(col.truck, cust, ground=list(parcels)).vid
            vids.append(vid)
            loc.setdefault((col.truck, cust), vid)
        for spec in sorted(col.sorties, key=lambda s: (s[1], s[2], s[0])):
            drone, li, ri, air, mode, lam = spec
            if not air:
                return None
            if not (0 <= li < ri < len(vids)):
                return None
            plan.add_sortie(drone, col.truck, vids[li], mode, lam, list(air), vids[ri])
        used |= set(col.drones)
    for link in links:
        if link.drone in used or not link.air:
            return None
        lv = loc.get((link.launch_truck, link.launch_customer))
        rv = loc.get((link.rec_truck, link.rec_customer))
        if lv is None or rv is None:
            return None
        if link.launch_truck == link.rec_truck:
            return None
        plan.add_sortie(link.drone, link.launch_truck, lv, link.mode, link.lam, list(link.air), rv)
        used.add(link.drone)
    return plan


def milp_select_sync(columns: list[SyncColumn], incumbent, inst, phys):
    """选择互不重叠的同步分量。目标是替换后卡车里程代理更短。空选择表示保持原计划。"""
    if not columns or incumbent is None:
        return None
    base: dict[str, float] = {}
    for truck, route in incumbent.routes.items():
        seq = tuple(incumbent.visits[vid].customer for vid in route if vid in incumbent.visits)
        base[truck] = _path_proxy(inst, phys, seq)
    n = len(columns)
    coeff = np.array([
        col.proxy - sum(base.get(t, 0.0) for t in col.trucks) for col in columns
    ], dtype=float)
    rows_i: list[int] = []
    cols_j: list[int] = []
    data: list[float] = []
    lb: list[float] = []
    ub: list[float] = []
    row = 0

    def add(pairs, lo, hi):
        nonlocal row
        for j, v in pairs:
            rows_i.append(row)
            cols_j.append(j)
            data.append(v)
        lb.append(lo)
        ub.append(hi)
        row += 1

    parcels = sorted(set().union(*(col.covers for col in columns)))
    for pid in parcels:
        idx = [j for j, col in enumerate(columns) if pid in col.covers]
        add([(j, 1.0) for j in idx], 0.0, 1.0)
    trucks = sorted({t for col in columns for t in col.trucks})
    for truck in trucks:
        idx = [j for j, col in enumerate(columns) if truck in col.trucks]
        add([(j, 1.0) for j in idx], 0.0, 1.0)
    drones = sorted({d for col in columns for d in col.drones})
    for drone in drones:
        idx = [j for j, col in enumerate(columns) if drone in col.drones]
        if idx:
            add([(j, 1.0) for j in idx], 0.0, 1.0)
    A = coo_matrix((data, (rows_i, cols_j)), shape=(row, n))
    try:
        res = milp(coeff, integrality=np.ones(n), bounds=Bounds(0, 1),
                   constraints=LinearConstraint(A, np.array(lb), np.array(ub)),
                   options={"time_limit": 1.0})
    except Exception:
        return None
    if res.x is None:
        return None
    chosen = [columns[i] for i, v in enumerate(res.x) if v > 0.5]
    if not chosen:
        return []
    if float(sum(coeff[i] for i, v in enumerate(res.x) if v > 0.5)) >= -1e-6:
        return []
    seen_t: set[str] = set()
    seen_p: set[str] = set()
    seen_d: set[str] = set()
    for col in chosen:
        if seen_t & set(col.trucks) or seen_p & set(col.covers) or seen_d & set(col.drones):
            return None
        if len(col.trucks) < 2 or not col.crosses:
            return None
        seen_t |= set(col.trucks)
        seen_p |= set(col.covers)
        seen_d |= set(col.drones)
    return chosen


def assemble_sync(incumbent, columns: list[SyncColumn], inst, phys):
    """把选中的同步分量换上，其余卡车留在原计划里。包裹对不齐就返回 None。"""
    from .evaluate import is_cross_sortie
    from .moves import apply_ground, ground_candidates, remove_parcel
    if not columns:
        return None
    plan = incumbent.clone()
    original = set(plan.assigned_parcels())
    trucks: set[str] = set()
    covers: set[str] = set()
    drones: set[str] = set()
    for col in columns:
        if len(col.trucks) < 2 or not col.crosses:
            return None
        if trucks & set(col.trucks) or covers & set(col.covers) or drones & set(col.drones):
            return None
        for drone, lt, rt, lc, rc, air, mode, lam in col.crosses:
            if lt not in col.trucks or rt not in col.trucks or lt == rt or not air:
                return None
            if not any(r.truck == lt and lc in r.visits for r in col.routes):
                return None
            if not any(r.truck == rt and rc in r.visits for r in col.routes):
                return None
        trucks |= set(col.trucks)
        covers |= set(col.covers)
        drones |= set(col.drones)
    orphans: list[str] = []
    seen = set(covers)
    for t in trucks:
        for vid in plan.routes.get(t, []):
            for p in plan.visits[vid].ground:
                if p not in seen:
                    orphans.append(p)
                    seen.add(p)
    for s in plan.sorties.values():
        if s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            continue
        lt = plan.visits[s.launch_vid].truck
        rt = plan.visits[s.rec_vid].truck
        if lt in trucks or rt in trucks or s.drone in drones:
            for p in s.air:
                if p not in seen:
                    orphans.append(p)
                    seen.add(p)
    freed: list[str] = []
    for pid in sorted(covers | set(orphans)):
        remove_parcel(plan, pid, freed)
    for p in freed:
        if p not in covers and p not in orphans:
            orphans.append(p)
    for s in list(plan.sorties.values()):
        if s.launch_vid not in plan.visits or s.rec_vid not in plan.visits:
            plan.remove_sortie(s.sid)
            continue
        lt = plan.visits[s.launch_vid].truck
        rt = plan.visits[s.rec_vid].truck
        if s.drone in drones or lt in trucks or rt in trucks:
            plan.remove_sortie(s.sid)
    for t in trucks:
        for vid in list(plan.routes.get(t, [])):
            plan.remove_visit(vid)
    for col in columns:
        loc: dict[tuple[str, str], int] = {}
        used: set[str] = set()
        for route in col.routes:
            if route.truck not in col.trucks or len(route.ground_at) != len(route.sequence):
                return None
            if used & set(route.drones):
                return None
            vids = []
            for cust, parcels in zip(route.sequence, route.ground_at):
                vid = plan.add_visit(route.truck, cust, ground=list(parcels)).vid
                vids.append(vid)
                loc[(route.truck, cust)] = vid
            for spec in sorted(route.sorties, key=lambda s: (s[1], s[2], s[0])):
                drone, li, ri, air, mode, lam = spec
                if not air or not (0 <= li < ri < len(vids)):
                    return None
                plan.add_sortie(drone, route.truck, vids[li], mode, lam, list(air), vids[ri])
            used |= set(route.drones)
        for drone, lt, rt, lc, rc, air, mode, lam in col.crosses:
            lv = loc.get((lt, lc))
            rv = loc.get((rt, rc))
            if lv is None or rv is None or not air:
                return None
            plan.add_sortie(drone, lt, lv, mode, lam, list(air), rv)
    for pid in orphans:
        from .moves import parcel_delivery
        if parcel_delivery(plan, pid) is not None:
            continue
        cands = [c for c in ground_candidates(plan, inst, phys, pid, state=None) if c.truck not in trucks]
        if not cands or not apply_ground(plan, inst, pid, cands[0]):
            return None
    if set(plan.assigned_parcels()) != original:
        return None
    for col in columns:
        for drone, lt, rt, lc, rc, air, mode, lam in col.crosses:
            still = [s for s in plan.sorties.values()
                     if s.drone == drone and tuple(s.air) == air and is_cross_sortie(plan, s)]
            if not still:
                return None
    return plan


@dataclass
class ColumnPool:
    allow_cross: bool
    routes: list[RouteColumn] = field(default_factory=list)
    links: list[LinkColumn] = field(default_factory=list)
    sync: list[SyncColumn] = field(default_factory=list)
    _rkeys: set = field(default_factory=set)
    _lkeys: set = field(default_factory=set)
    _skeys: set = field(default_factory=set)
    route_cap: int = 36
    link_cap: int = 18
    sync_cap: int = 24

    def add_plan(self, plan, inst, phys, keep: bool = False) -> None:
        if self.allow_cross:
            for col in extract_sync(plan, inst, phys):
                if len(col.trucks) < 2 or not col.crosses:
                    continue
                if col.key in self._skeys:
                    if keep:
                        for old in self.sync:
                            if old.key == col.key:
                                old.keep = True
                    continue
                col.keep = keep
                self.sync.append(col)
                self._skeys.add(col.key)
            self._trim(self.sync, self.sync_cap, self._skeys)
            return
        got = extract_columns(plan, inst, phys, False)
        if got is None:
            return
        routes, _links = got
        assigned = set(plan.assigned_parcels())
        covered = set()
        for col in routes:
            covered |= set(col.covers)
        if covered != assigned:
            return
        for col in routes:
            if col.key in self._rkeys:
                if keep:
                    for old in self.routes:
                        if old.key == col.key:
                            old.keep = True
                continue
            col.keep = keep
            self.routes.append(col)
            self._rkeys.add(col.key)
        self._trim(self.routes, self.route_cap, self._rkeys)

    @staticmethod
    def _trim(cols, cap, keys):
        if len(cols) <= cap:
            return
        victims = sorted((i for i, col in enumerate(cols) if not col.keep),
                         key=lambda i: cols[i].proxy, reverse=True)
        drop = []
        for i in victims:
            if len(cols) - len(drop) <= cap:
                break
            drop.append(i)
        for i in sorted(drop, reverse=True):
            keys.discard(cols[i].key)
            cols.pop(i)

    def solve(self, inst, incumbent=None, phys=None):
        if self.allow_cross:
            return milp_select_sync(self.sync, incumbent, inst, phys)
        parcels = [c.parcel_id for c in inst.customers]
        return milp_select(self.routes, [], parcels)


def try_set_partition(best_plan, ctx, budget, stats):
    """重组一次。拼出的计划先完整评价，再在同一组情景上重新打分；打不出分就不交给调用方。"""
    if best_plan is None or getattr(ctx, "mode", None) != "nominal":
        return None, None
    if not getattr(ctx.alg, "set_partition", False):
        return None, None
    allow = _allow_cross(ctx)
    pool = _pool(ctx, allow)
    pool.add_plan(best_plan, ctx.inst, ctx.phys, keep=True)
    if budget.evals_left() <= 0:
        return None, None
    if allow and not pool.sync:
        return None, None
    if not allow and not pool.routes:
        return None, None
    chosen = pool.solve(ctx.inst, best_plan, ctx.phys)
    if chosen is None:
        stats.aud("SET_PARTITION", "infeasible")
        return None, None
    if not chosen:
        stats.aud("SET_PARTITION", "kept_incumbent")
        return None, None
    stats.aud("SET_PARTITION", "solved")
    if allow:
        plan = assemble_sync(best_plan, chosen, ctx.inst, ctx.phys)
    else:
        plan = assemble(chosen[0], chosen[1], ctx.inst)
    if plan is None:
        stats.aud("SET_PARTITION", "assemble_fail")
        return None, None
    from .evaluate import is_cross_sortie
    has_cross = any(is_cross_sortie(plan, s) for s in plan.sorties.values())
    if allow and not has_cross:
        stats.aud("SET_PARTITION", "rejected_no_cross")
        return None, None
    if not allow and has_cross:
        stats.aud("SET_PARTITION", "rejected_cross")
        return None, None
    from .alns import eval_counted
    ev = eval_counted(plan, ctx.inst, ctx.phys, ctx.state, ctx.H, "SET_PARTITION", stats, budget)
    if ev is None or not ev.feasible:
        stats.aud("SET_PARTITION", "eval_infeasible")
        return None, None
    if getattr(ctx, "scenario_on", False):
        score = scenario_score(plan, ev, ctx)
        if score is None:
            stats.aud("SET_PARTITION", "scenario_unscored")
            return None, None
        stats.aud("SET_PARTITION", "scenario_scored")
    return plan, ev
