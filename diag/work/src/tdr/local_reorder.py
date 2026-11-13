"""局部事件重排：相邻至多 6 个未执行事件，用 HiGHS MILP 选顺序。

窗口外的事件顺序不动。MILP 只决定窗口内事件的排列，并遵守同一航次“先放飞、后回收”。
求出的新顺序只做一次完整评价；顺序没变就不扣评价预算。
目标是各事件权重乘位置（余电更紧的回收尽量靠前）。这还不是规范 7.15 把充电量、
等待和资源占用全部放进同一个整数模型的写法，时间与充电仍由外层评价器求解。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .evaluate import Evaluation
from .plan import Plan


@dataclass
class ReorderProposal:
    plan: Plan
    evaluation: Evaluation
    window: int
    description: str


def candidate_moves(plan: Plan) -> list[tuple[str, int]]:
    """返回 [(类型, 目标id)]：'REC' 访问vid、'LAUNCH' 访问vid、'SWAP' 访问vid."""
    out: list[tuple[str, int]] = []
    for vid in sorted(plan.visits):
        recs = [s for s in plan.sorties.values() if s.rec_vid == vid and not s.started]
        if len(recs) >= 2:
            out.append(("REC", vid))
        launches = [s for s in plan.sorties.values()
                    if s.launch_vid == vid and not s.started]
        if len(launches) >= 2:
            out.append(("LAUNCH", vid))
    return out


def _future_events(plan: Plan) -> list[tuple]:
    ev = []
    for s in plan.sorties.values():
        if s.rec_vid not in plan.visits:
            continue
        if not s.started and s.launch_vid is not None and s.launch_vid in plan.visits:
            ev.append(("L", s.sid, s.launch_vid, s.launch_priority))
        ev.append(("R", s.sid, s.rec_vid, s.rec_priority))

    def key(e):
        vid = e[2]
        v = plan.visits[vid]
        route = plan.routes.get(v.truck, [])
        idx = route.index(vid) if vid in route else 0
        return (v.truck, idx, 0 if e[0] == "L" else 1, e[3], e[1])

    ev.sort(key=key)
    return ev


def _solve_window(weight: list[float], precede: list[tuple[int, int]], node_limit: int):
    n = len(weight)
    if n < 2:
        return None
    N = n * n
    c = np.zeros(N)
    for e in range(n):
        for r in range(n):
            # 权重相同时间保持原顺序，避免无差别重排白白消耗一次评价。
            c[e * n + r] = weight[e] * r + 1e-3 * abs(r - e)
    rows = []
    lb = []
    ub = []
    for e in range(n):
        row = np.zeros(N)
        row[e * n:(e + 1) * n] = 1.0
        rows.append(row)
        lb.append(1.0)
        ub.append(1.0)
    for r in range(n):
        row = np.zeros(N)
        for e in range(n):
            row[e * n + r] = 1.0
        rows.append(row)
        lb.append(1.0)
        ub.append(1.0)
    for a, b in precede:
        row = np.zeros(N)
        for r in range(n):
            row[a * n + r] += r
            row[b * n + r] -= r
        rows.append(row)
        lb.append(-np.inf)
        ub.append(-1.0)
    try:
        res = milp(c, integrality=np.ones(N), bounds=Bounds(0, 1),
                   constraints=LinearConstraint(np.vstack(rows), lb, ub),
                   options={"presolve": True, "disp": False,
                            "node_limit": int(node_limit), "mip_rel_gap": 0.0})
    except Exception:
        return None
    if res.x is None:
        return None
    assign = [int(np.argmax(res.x[e * n:(e + 1) * n])) for e in range(n)]
    if sorted(assign) != list(range(n)):
        return None
    order = [0] * n
    for e, r in enumerate(assign):
        order[r] = e
    return order


def _apply_order(plan: Plan, events: list[tuple]) -> None:
    rec_n: dict[int, int] = {}
    launch_n: dict[int, int] = {}
    for kind, sid, vid, _prio in events:
        s = plan.sorties.get(sid)
        if s is None:
            continue
        if kind == "R":
            s.rec_priority = rec_n.get(vid, 0)
            rec_n[vid] = rec_n.get(vid, 0) + 1
        else:
            s.launch_priority = launch_n.get(vid, 0)
            launch_n[vid] = launch_n.get(vid, 0) + 1


def try_local_reorder(plan: Plan, ev: Evaluation | None, ctx, stats, budget,
                      window_cursor: int) -> tuple[Plan | None, Evaluation | None]:
    events = _future_events(plan)
    n = len(events)
    if n < 2:
        return None, None
    w = min(6, n)
    n_windows = n - w + 1
    start = window_cursor % n_windows
    window = events[start:start + w]
    weight = []
    energy = getattr(ctx.state, "drone_energy", {}) or {}
    for kind, sid, _vid, _prio in window:
        drone = plan.sorties[sid].drone
        e = float(energy.get(drone, 1.0))
        weight.append((1.0 / max(e, 0.05)) if kind == "R" else 0.01)
    index_of = {(kind, sid): i for i, (kind, sid, _v, _p) in enumerate(window)}
    precede = []
    sids = {sid for _k, sid, _v, _p in window}
    for sid in sids:
        if ("L", sid) in index_of and ("R", sid) in index_of:
            precede.append((index_of[("L", sid)], index_of[("R", sid)]))
    node_limit = getattr(ctx.alg, "mip_node_limit", 1000)
    order = _solve_window(weight, precede, node_limit)
    stats.counts["n_mip_calls"] = stats.counts.get("n_mip_calls", 0) + 1
    if order is None:
        return None, None
    new_window = [window[i] for i in order]
    if new_window == window:
        return None, None
    if budget.evals_left() <= 0:
        return None, None
    full = list(events)
    full[start:start + w] = new_window
    p = plan.clone()
    _apply_order(p, full)
    from .alns import eval_counted
    e = eval_counted(p, ctx.inst, ctx.phys, ctx.state, ctx.H, "MIP_RETURN", stats, budget)
    stats.counts["n_mip_evals"] = stats.counts.get("n_mip_evals", 0) + 1
    if e is None or not e.feasible:
        return None, None
    return p, e
