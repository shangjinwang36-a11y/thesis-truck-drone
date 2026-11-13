"""计划与已执行回合的不变量。

这些检查不参与搜索，只回答：这份计划或这段执行日志是否还符合模型。
S 不得出现跨车回收；电量不得为负；同一无人机的阶段不得重叠；
每个客户恰好交付一次；机位与通道不超限；报告成本与回放成本一致。
"""
from __future__ import annotations

from .config import PhysicalConfig
from .data import Instance
from .evaluate import evaluate_plan, recovery_is_cross
from .plan import Plan
from .replay import verify_replay
from .schedule import StartState


def cross_recoveries(plan: Plan) -> list[str]:
    """每条记录一个放飞车 ≠ 回收车的航次，含已起飞残段。"""
    out = []
    for s in plan.sorties.values():
        if not recovery_is_cross(plan, s):
            continue
        rec = plan.visits[s.rec_vid].truck
        if s.started:
            launch = s.launch_truck or s.truck
        elif s.launch_vid in plan.visits:
            launch = plan.visits[s.launch_vid].truck
        else:
            launch = s.truck
        out.append(f"sid={s.sid}:{launch}->{rec}:started={int(s.started)}")
    return out


def check_plan(plan: Plan, inst: Instance, phys: PhysicalConfig,
               state: StartState | None = None, H: float | None = None,
               strategy: str | None = None) -> list[str]:
    """结构、策略资格、调度收敛、电量、机位、交付唯一性。

    可行计划已经过 evaluate_plan 的机位、通道、H 和回收余电检查。
    这里再核对时间轴上的电量，以及 S 是否出现跨车回收。
    """
    ev = evaluate_plan(plan, inst, phys, state, H, "INVARIANT")
    v = [] if ev.feasible else list(ev.violations)
    if strategy == "S":
        v += [f"S_CROSS:{x}" for x in cross_recoveries(plan)]
    tl = ev.timeline
    if tl is not None and ev.feasible:
        if not tl.converged:
            v.append("SCHEDULE_NOT_CONVERGED")
        for d, energies in tl.drone_energy.items():
            for i, e in enumerate(energies):
                if e < -phys.energy_tol:
                    v.append(f"NEGATIVE_SOC:{d}#{i}:{e:.6f}")
    return v


def check_segments(inst: Instance, phys: PhysicalConfig, segments: list[dict],
                   H: float | None = None, strategy: str | None = None,
                   require_complete: bool = True) -> tuple[list[str], float | None]:
    """独立回放。未完成回合允许还没送完，其余违规仍算失败。"""
    if not segments:
        return ["NO_SEGMENTS"], None
    rep = verify_replay(inst, phys, segments, H, strategy=strategy)
    v = list(rep.violations)
    if not require_complete:
        v = [x for x in v if not x.startswith("UNDELIVERED_FINAL")]
    return v, rep.cost


def check_episode(ep, inst: Instance, phys: PhysicalConfig) -> dict:
    """已执行回合：回放违规、S 跨车、完成回合的成本是否与评价器一致。"""
    violations, replay_cost = check_segments(
        inst, phys, list(ep.segments or []), ep.H, strategy=ep.strategy,
        require_complete=(ep.status == "COMPLETED_VERIFIED"))
    cost = ep.evaluation.cost if ep.evaluation is not None else None
    cost_gap = None
    if (ep.status == "COMPLETED_VERIFIED" and cost is not None and replay_cost is not None
            and abs(cost - replay_cost) > 1e-4):
        violations.append(f"COST_MISMATCH:eval={cost:.6f}:replay={replay_cost:.6f}")
        cost_gap = cost - replay_cost
    if ep.strategy == "S" and ep.plan is not None:
        for x in cross_recoveries(ep.plan):
            tag = f"S_CROSS_PLAN:{x}"
            if tag not in violations:
                violations.append(tag)
    served = set()
    double = []
    if ep.status == "COMPLETED_VERIFIED":
        for seg in ep.segments or []:
            for a in seg.get("actions", []):
                if a.get("kind") == "G" and a.get("ref"):
                    if a["ref"] in served:
                        double.append(a["ref"])
                    served.add(a["ref"])
            for st in seg.get("stages", []):
                if st.get("kind") == "SERVICE" and st.get("parcel"):
                    if st["parcel"] in served:
                        double.append(st["parcel"])
                    served.add(st["parcel"])
        missing = [c.parcel_id for c in inst.customers if c.parcel_id not in served]
        if missing:
            violations.append(f"UNSERVED:{len(missing)}")
        if double:
            violations.append(f"DOUBLE_SERVED:{double[:5]}")
    return {
        "status": ep.status,
        "ok": not violations,
        "n_violations": len(violations),
        "violations": violations[:12],
        "cost": cost,
        "replay_cost": replay_cost,
        "cost_gap": cost_gap,
        "n_cross_plan": len(cross_recoveries(ep.plan)) if ep.plan is not None else None,
    }
