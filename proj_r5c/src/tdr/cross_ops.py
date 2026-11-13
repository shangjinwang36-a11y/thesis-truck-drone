"""第四轮：X 专用的跨车恢复算子（仅当失败航次被"另一辆车"（≠原放飞车）接回时才有资格触发）.

S 的接机车恒为原放飞车，所以 `cross_pair()` 对 S 恒为 None —— S 永远用不上这些算子；
X 在使用它们时消耗的是自己的同一份评价预算（总预算不变），无任何偏置项/配额/惩罚。

算子（均作用于“当前最优计划”，只改地面访问的归属/次序，其余结构不动，再交完整评价器核验）：
- LAUNCH_TRUCK_RELEASE  原放飞车 K1 不必再等/绕去接机后，把 K1 与接机车 K2 剩余路线上的“纯地面”访问
                        在 K1、K2（及同一路线内）重新定位（relocate），例如 K1 提前收工、K2 顺路代送。
- TRUCK_TASK_SWAP       交换 K1 与 K2 各一个纯地面访问（剩余客户段互换）。
- FAILED_PARCEL_GROUND_REASSIGN  交接票(失败包裹)的地送在接机车 K2 上的位置重排（custody 仍属 K2，
                        只换在 K2 剩余路线里的插入位置，选更省的）。
"""
from __future__ import annotations

import math

from .moves import allowed_truck


def cross_pair(plan, frag_sid):
    """返回 (原放飞车, 接机车)；非跨车（或没有失败航次）返回 None."""
    if frag_sid is None:
        return None
    f = plan.sorties.get(frag_sid)
    if f is None or f.rec_vid not in plan.visits:
        return None
    k1 = f.launch_truck or f.truck
    k2 = plan.visits[f.rec_vid].truck
    if k1 is None or k1 == k2:
        return None
    return k1, k2


def _xy(inst, plan, vid):
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _coupled(plan, vid):
    return any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values())


def _dest_ok(plan, vid, dest, f, state):
    """访问 vid 的全部包裹能否由卡车 dest 地送（保管链约束）：DEPOT 自由；TRUCK:t 只能 t；
    失败航次的交接票(DRONE:该机)交接后属接机车。"""
    v = plan.visits[vid]
    for p in v.ground:
        h = (getattr(state, "parcel_holder", {}) or {}).get(p, "DEPOT")
        if h == "DEPOT":
            continue
        if h.startswith("TRUCK:") and h.split(":", 1)[1] == dest:
            continue
        if h.startswith("DRONE:") and p in f.handover and plan.visits[f.rec_vid].truck == dest:
            continue
        return False
    return True


def _movable_visit(plan, vid, protect):
    v = plan.visits.get(vid)
    return vid not in protect and v is not None and bool(v.ground) and not _coupled(plan, vid)


def _route_xy(inst, plan, truck, skip=None):
    depot = (inst.depot_x, inst.depot_y)
    return [depot] + [_xy(inst, plan, v) for v in plan.routes.get(truck, []) if v != skip] + [depot]


def _insert_delta(pts, j, p):
    """在 pts[j]（j=1..len-1：插在第 j-1 个访问之后，以 pts 的下标计）前插 p 的绕行距离."""
    return _d(pts[j - 1], p) + _d(p, pts[j]) - _d(pts[j - 1], pts[j])


def propose(plan, ctx, k: int, tried: set) -> list:  # noqa: F821
    """按距离/工时代理排序给出至多 k 个新的候选计划 [(tag, plan)]."""
    pair = cross_pair(plan, ctx.frag_sid)
    if pair is None:
        if getattr(ctx.alg, "cross_ops_gate", True):
            return []                     # 默认：只有跨车接机时才有资格（S 恒不满足）
        f0 = plan.sorties.get(ctx.frag_sid)
        if f0 is None or f0.rec_vid not in plan.visits:
            return []
        pair = (plan.visits[f0.rec_vid].truck,) * 2     # 对照(ungated)：同车情形也可用，S/X 同等
    k1, k2 = pair
    inst, phys, state = ctx.inst, ctx.phys, ctx.state
    from .recovery import _fixed_first_vids
    f = plan.sorties[ctx.frag_sid]
    protect = _fixed_first_vids(plan, state) | {f.rec_vid}
    low = state.truck_min_insert or {}
    rate = phys.c_km / 1000.0 + phys.wage_per_s / phys.truck_speed_m_s
    items = []                                   # (gain, tag, spec)
    trucks = tuple(dict.fromkeys((k1, k2)))
    hand = set(f.handover)
    rec_pos = plan.routes[plan.visits[f.rec_vid].truck].index(f.rec_vid)
    for a in trucks:
        for vid in list(plan.routes.get(a, [])):
            if not _movable_visit(plan, vid, protect):
                continue
            is_hand = bool(hand & set(plan.visits[vid].ground))
            p = _xy(inst, plan, vid)
            ia = plan.routes[a].index(vid)
            pts = _route_xy(inst, plan, a)
            rem = _d(pts[ia], p) + _d(p, pts[ia + 2]) - _d(pts[ia], pts[ia + 2])   # pts 下标比 route 大 1
            for b in trucks:
                if not _dest_ok(plan, vid, b, f, state):
                    continue
                ptsb = _route_xy(inst, plan, b, skip=vid)
                rb = [v for v in plan.routes[b] if v != vid]
                lo = low.get(b, 0)
                if is_hand and b == plan.visits[f.rec_vid].truck:      # 交接票只能在接机访问之后地送
                    lo = max(lo, rb.index(f.rec_vid) + 1)
                for j in range(lo, len(rb) + 1):     # 插在 rb[j] 之前
                    if a == b and j == ia:
                        continue
                    ins = _insert_delta(ptsb, j + 1, p)
                    key = ("RELOC", vid, b, rb[j - 1] if j > 0 else 0, rb[j] if j < len(rb) else 0)
                    if key in tried:
                        continue
                    if is_hand and b == a:
                        tag = "FAILED_PARCEL_GROUND_REASSIGN"
                    elif a == k1 and b != a:
                        tag = "LAUNCH_TRUCK_RELEASE"
                    elif a == k1:
                        tag = "LAUNCH_TRUCK_RELEASE"
                    else:
                        tag = "TRUCK_TASK_SWAP_RELOC"
                    items.append((rate * (rem - ins), tag, ("reloc", vid, b, j, key)))
    # 交换：K1、K2 各一个纯地面访问互换（保管链允许时）
    if k1 != k2:
        r1 = [v for v in plan.routes.get(k1, []) if _movable_visit(plan, v, protect) and _dest_ok(plan, v, k2, f, state)]
        r2 = [v for v in plan.routes.get(k2, []) if _movable_visit(plan, v, protect) and _dest_ok(plan, v, k1, f, state)]
        for va in r1:
            for vb in r2:
                ia, ib = plan.routes[k1].index(va), plan.routes[k2].index(vb)
                if ia < low.get(k1, 0) or ib < low.get(k2, 0):
                    continue
                pa, pb = _xy(inst, plan, va), _xy(inst, plan, vb)
                p1 = _route_xy(inst, plan, k1); p2 = _route_xy(inst, plan, k2)
                old = (_d(p1[ia], pa) + _d(pa, p1[ia + 2]) + _d(p2[ib], pb) + _d(pb, p2[ib + 2]))
                new = (_d(p1[ia], pb) + _d(pb, p1[ia + 2]) + _d(p2[ib], pa) + _d(pa, p2[ib + 2]))
                key = ("SWAP", va, vb)
                if key in tried:
                    continue
                items.append((rate * (old - new), "TRUCK_TASK_SWAP", ("swap", va, vb, key)))
    items.sort(key=lambda x: (-x[0], x[1], x[2][1:3]))
    out = []
    for g, tag, spec in items:
        if len(out) >= k:
            break
        if g < -1e-9 and len(out) >= 1:      # 只有当前没有任何非负收益候选时才试一个负收益的
            break
        cand = plan.clone()
        if spec[0] == "reloc":
            _, vid, b, j, key = spec
            a = cand.visits[vid].truck
            cand.routes[a].remove(vid)
            cand.routes[b].insert(j, vid)
            cand.visits[vid].truck = b
        else:
            _, va, vb, key = spec
            ia, ib = cand.routes[k1].index(va), cand.routes[k2].index(vb)
            cand.routes[k1][ia], cand.routes[k2][ib] = vb, va
            cand.visits[va].truck, cand.visits[vb].truck = k2, k1
        tried.add(key)
        out.append((tag, cand))
    return out
