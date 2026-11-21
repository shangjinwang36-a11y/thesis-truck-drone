"""图形输出：路线图、甘特图、能量/充电曲线、配对差值图（英文标签避免缺字）."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from .config import PhysicalConfig
from .data import Instance
from .plan import Plan

TRUCK_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
DRONE_COLORS = ["#17becf", "#bcbd22", "#e377c2", "#7f7f7f", "#8c564b"]


def _depot(inst: Instance):
    return inst.depot_x, inst.depot_y


def _customer_pos(inst: Instance, cid: str):
    c = inst.customer(cid)
    return c.x, c.y


def _segments(plan: Plan, inst: Instance):
    for truck, route in plan.routes.items():
        pts = [_depot(inst)]
        for vid in route:
            pts.append(_customer_pos(inst, plan.visits[vid].customer))
        pts.append(_depot(inst))
        yield truck, pts


def plot_nominal_route(inst: Instance, plan: Plan, ev, path: str | Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 8), dpi=130)
    for i, (truck, pts) in enumerate(_segments(plan, inst)):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, "-o", color=TRUCK_COLORS[i % 5], ms=3, lw=1.2, label=f"truck {truck}")
    for s in plan.sorties.values():
        if s.rec_vid not in plan.visits:
            continue
        rv = plan.visits[s.rec_vid]
        start = _launch_xy(inst, plan, s)
        pts = [start] + [_customer_pos(inst, inst.parcel_to_customer[p]) for p in s.air]
        pts.append(_customer_pos(inst, rv.customer))
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "--", color="#444444", lw=0.8, alpha=0.8)
    ax.scatter([inst.depot_x], [inst.depot_y], marker="s", s=90, c="black", zorder=5,
               label="depot")
    ax.scatter([c.x for c in inst.customers], [c.y for c in inst.customers], s=12, c="#333333",
               zorder=4, label="customers")
    ax.set_title(f"{inst.case_id} nominal plan (cost={ev.cost:.2f})")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.legend(fontsize=7, loc="best")
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _launch_xy(inst: Instance, plan: Plan, s) -> tuple[float, float]:
    if s.launch_vid is None:
        return _depot(inst)
    v = plan.visits[s.launch_vid]
    route = plan.routes.get(v.truck, [])
    i = route.index(v.vid)
    p = _customer_pos(inst, v.customer)
    if s.mode == "ARC" and i + 1 < len(route):
        q = _customer_pos(inst, plan.visits[route[i + 1]].customer)
        return (p[0] + (q[0] - p[0]) * s.lam, p[1] + (q[1] - p[1]) * s.lam)
    return p


def plot_nominal_gantt(inst: Instance, plan: Plan, ev, path: str | Path, H: float | None = None,
                       title: str | None = None) -> None:
    tl = ev.timeline
    rows = []
    for k in sorted(plan.routes):
        rows.append((f"truck {k}", k))
    for d in sorted(tl.drone_stages):
        rows.append((f"drone {d}", d))
    fig, ax = plt.subplots(figsize=(11, 0.45 * len(rows) + 1.5), dpi=130)
    yticks, ylabels = [], []
    for j, (label, key) in enumerate(rows):
        yticks.append(j)
        ylabels.append(label)
        if key.startswith("t"):
            for a in tl.actions:
                if a.actor != key:
                    continue
                color = {"DRIVE": "#c8d8e8", "G": "#2ca02c", "P": "#ff7f0e", "R": "#d62728",
                         "U": "#9467bd", "L": "#17becf"}.get(a.kind, "#cccccc")
                ax.barh(j, a.end - a.start, left=a.start, height=0.6, color=color, edgecolor="none")
        else:
            for st in tl.drone_stages.get(key, []):
                color = {"ON_TRUCK": "#e8e8e8", "READY": "#f5e6c8", "P": "#ff7f0e",
                         "L": "#17becf", "CRUISE": "#9ecae1", "SERVICE": "#2ca02c",
                         "WAIT": "#d62728", "R": "#8c564b", "U": "#9467bd"}.get(st.kind, "#dddddd")
                ax.barh(j, st.end - st.start, left=st.start, height=0.6, color=color, edgecolor="none")
    if H is not None:
        ax.axvline(H, color="k", ls="--", lw=0.8)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8)
    ax.set_xlabel("time (s)")
    handles = [Patch(color=c, label=n) for n, c in
               [("drive", "#c8d8e8"), ("G ground", "#2ca02c"), ("P prepare", "#ff7f0e"),
                ("R recovery", "#d62728"), ("U handover", "#9467bd"), ("L launch", "#17becf"),
                ("cruise", "#9ecae1"), ("service", "#2ca02c"), ("wait", "#d62728"),
                ("on truck", "#e8e8e8")]]
    ax.legend(handles=handles, fontsize=6, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    ax.set_title(title or f"{inst.case_id} nominal schedule")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_episode_route(inst: Instance, nominal_plan: Plan, plan: Plan | None,
                       observations, path: str | Path, title: str = "") -> None:
    fig, ax = plt.subplots(figsize=(9, 8), dpi=130)
    for i, (truck, pts) in enumerate(_segments(nominal_plan, inst)):
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "-", color=TRUCK_COLORS[i % 5],
                lw=0.6, alpha=0.35, label=f"nominal {truck}")
    if plan is not None:
        for i, (truck, pts) in enumerate(_segments(plan, inst)):
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", color=TRUCK_COLORS[i % 5],
                    lw=1.4, ms=2.5)
        for s in plan.sorties.values():
            if s.rec_vid not in plan.visits:
                continue
            rv = plan.visits[s.rec_vid]
            start = (s.start_pos if s.started and s.start_pos else _launch_xy(inst, plan, s))
            pts = [start] + [_customer_pos(inst, inst.parcel_to_customer[p]) for p in s.air]
            pts.append(_customer_pos(inst, rv.customer))
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "--", color="#111111", lw=0.9)
    fails = [o for o in observations if not o.air_delivery_available]
    if fails:
        xs = [_customer_pos(inst, o.customer_id)[0] for o in fails]
        ys = [_customer_pos(inst, o.customer_id)[1] for o in fails]
        ax.scatter(xs, ys, marker="X", s=140, c="red", zorder=6, label="observed failure")
    ax.scatter([inst.depot_x], [inst.depot_y], marker="s", s=90, c="black", zorder=5)
    ax.set_title(title)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.legend(fontsize=7)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_episode_gantt(inst: Instance, plan: Plan | None, ev, path: str | Path,
                       H: float | None = None, title: str = "") -> None:
    if ev is None or ev.timeline is None:
        return
    plot_nominal_gantt(inst, plan, ev, path, H, title=title + " (residual suffix)")


def plot_energy(inst: Instance, plan: Plan | None, ev, path: str | Path, title: str = "") -> None:
    if ev is None or ev.timeline is None:
        return
    tl = ev.timeline
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), dpi=130, sharex=True)
    for i, (d, stages) in enumerate(sorted(tl.drone_stages.items())):
        energies = tl.drone_energy.get(d, [])
        xs, ys = [], []
        for j, st in enumerate(stages):
            xs.extend([st.start, st.end])
            ys.extend([energies[j], energies[j + 1]])
        if xs:
            ax1.plot(xs, ys, color=DRONE_COLORS[i % 5], lw=1.0, label=d)
    ax1.axhline(0.1 * 3.9688, color="red", ls="--", lw=0.8, label="E_min")
    ax1.set_ylabel("battery (kWh)")
    ax1.legend(fontsize=6, ncol=2)
    ax1.set_title(title)
    # 车辆供电余额
    from .config import PhysicalConfig
    for i, k in enumerate(sorted(tl.truck_finish)):
        run = tl.truck_finish.get(k, 0.0)
        q = tl.q_by_truck.get(k, 0.0)
        ax2.barh(i, run, height=0.5, color="#eeeeee")
        ax2.barh(i, q * 0, height=0.5, color="#888888")
    ax2.set_yticks(range(len(tl.truck_finish)))
    ax2.set_yticklabels(sorted(tl.truck_finish), fontsize=7)
    ax2.set_xlabel("time (s)")
    ax2.set_title("truck shift (AC used: " + ", ".join(
        f"{k}={tl.q_by_truck.get(k, 0.0):.2f}kWh" for k in sorted(tl.truck_finish)) + ")")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_paired(rows: list[dict], path: str | Path) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=130)
    labels, deltas = [], []
    for r in rows:
        if r.get("cost_S") is not None and r.get("cost_X") is not None:
            labels.append(f"{r['case_id']}-{r['environment_seed']}")
            deltas.append(r["cost_S"] - r["cost_X"])
    colors = ["#2ca02c" if d > 1e-9 else ("#d62728" if d < -1e-9 else "#999999") for d in deltas]
    ax1.bar(range(len(deltas)), deltas, color=colors)
    ax1.axhline(0, color="k", lw=0.8)
    ax1.set_xticks(range(len(deltas)))
    ax1.set_xticklabels(labels, rotation=90, fontsize=5)
    ax1.set_ylabel("cost_S - cost_X (CNY)")
    ax1.set_title("paired differences (green: X cheaper)")
    xs = [r["cost_S"] for r in rows if r.get("cost_S") is not None and r.get("cost_X") is not None]
    ys = [r["cost_X"] for r in rows if r.get("cost_S") is not None and r.get("cost_X") is not None]
    ax2.scatter(xs, ys, s=16, c="#1f77b4")
    lo = min(xs + ys) if xs else 0
    hi = max(xs + ys) if xs else 1
    ax2.plot([lo, hi], [lo, hi], "k--", lw=0.8)
    ax2.set_xlabel("cost_S (CNY)")
    ax2.set_ylabel("cost_X (CNY)")
    ax2.set_title("S vs X cost")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
