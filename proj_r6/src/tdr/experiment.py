"""批量实验：名义计划复用、S/X 共享环境、配对统计与输出."""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import ALGORITHM_ID, GENERATOR_VERSION, SCHEMA_VERSION, __version__
from .alns import Budget, SolveContext
from .config import AlgorithmConfig, PhysicalConfig
from .data import Instance, load_instance
from .evaluate import evaluate_plan
from .hidden_world import HiddenWorld
from .nominal import build_nominal
from .plan import Plan
from .schedule import initial_state
from .simulate import derive_rngs, run_episode
from .verify import verify_plan


def plan_to_dict(plan: Plan, inst: Instance) -> dict:
    return {
        "case_id": plan.case_id,
        "routes": {k: list(v) for k, v in plan.routes.items()},
        "visits": {str(v.vid): {"vid": v.vid, "truck": v.truck, "customer": v.customer,
                                "ground": list(v.ground)} for v in plan.visits.values()},
        "sorties": {str(s.sid): {"sid": s.sid, "drone": s.drone, "truck": s.truck,
                                 "launch_vid": s.launch_vid, "mode": s.mode, "lam": s.lam,
                                 "air": list(s.air), "rec_vid": s.rec_vid,
                                 "handover": list(s.handover), "started": s.started,
                                 "start_time": s.start_time, "start_pos": s.start_pos,
                                 "rec_priority": s.rec_priority,
                                 "launch_priority": s.launch_priority,
                                 "launch_truck": s.launch_truck,
                                 "landed": s.landed}
                          for s in plan.sorties.values()},
        "drone_sorties": {k: list(v) for k, v in plan.drone_sorties.items()},
        "next_vid": plan.next_vid,
        "next_sid": plan.next_sid,
    }


def plan_from_dict(d: dict) -> Plan:
    p = Plan(d["case_id"])
    p.next_vid = d["next_vid"]
    p.next_sid = d["next_sid"]
    p.routes = {k: list(v) for k, v in d["routes"].items()}
    from .plan import Sortie, Visit
    for k, v in d["visits"].items():
        p.visits[v["vid"]] = Visit(v["vid"], v["truck"], v["customer"], list(v["ground"]))
    for k, v in d["sorties"].items():
        p.sorties[v["sid"]] = Sortie(v["sid"], v["drone"], v["truck"], v["launch_vid"], v["mode"],
                                     v["lam"], list(v["air"]), v["rec_vid"], list(v["handover"]),
                                     v["started"], v["start_time"],
                                     tuple(v["start_pos"]) if v["start_pos"] else None,
                                     v.get("rec_priority", 0), v.get("launch_priority", 0),
                                     v.get("launch_truck"), bool(v.get("landed", False)))
    p.drone_sorties = {k: list(v) for k, v in d["drone_sorties"].items()}
    return p


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, allow_nan=False)


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


# ---------------------------------------------------------------------------
# 名义计划
# ---------------------------------------------------------------------------
def nominal_makespan_cap(cmax_s: float | None, shift_slack_s: float, use_shift: bool) -> float | None:
    """X 的搜索和发布上限。默认是 S 的完工时刻。use_shift 时改成评价班次 H。"""
    if cmax_s is None:
        return None
    if use_shift:
        return float(cmax_s) + float(shift_slack_s)
    return float(cmax_s)


def build_case_nominal(inst: Instance, phys: PhysicalConfig, alg: AlgorithmConfig,
                       out_dir: str | Path, eval_budget: int | None = None,
                       variant: str = "full", cross_launch: bool = False,
                       two_phase_b: int | None = None,
                       adopt_from: str | Path | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rngs = derive_rngs(alg.base_algorithm_seed, inst.case_id, "nominal", 0)
    t = time.perf_counter()
    starts = [alg.nominal_start_trucks]
    if alg.nominal_truck_starts and phys.truck_count > 5:
        starts = [5, phys.truck_count]
    res, start_used, start_costs = None, None, {}
    import dataclasses
    phys_nom = phys
    if alg.nominal_reserve_margin > 0:
        phys_nom = dataclasses.replace(phys, reserve_fraction=phys.reserve_fraction + alg.nominal_reserve_margin)
    makespan_cap = None
    s_plan_cap = None
    s_ev_cap = None
    if (adopt_from and cross_launch and (
            getattr(alg, "x_cross_hs_cap", False) or getattr(alg, "x_s_second_start", False))):
        s_plan_cap, _, _ = load_case_nominal(inst, adopt_from)
        s_ev_cap = evaluate_plan(s_plan_cap, inst, phys, initial_state(inst, phys), None, "NOMINAL")
        if s_ev_cap.feasible and s_ev_cap.timeline and s_ev_cap.timeline.truck_finish:
            makespan_cap = nominal_makespan_cap(
                max(s_ev_cap.timeline.truck_finish.values()), phys.shift_slack_s,
                bool(getattr(alg, "x_cap_is_shift", False)))
    for ns in starts:
        r_ = build_nominal(inst, phys_nom, alg, derive_rngs(alg.base_algorithm_seed, inst.case_id, "nominal", 0),
                           eval_budget=eval_budget, variant=variant, n_used=ns,
                           cross_launch=cross_launch, two_phase_b=two_phase_b,
                           makespan_cap=makespan_cap,
                           alt_start=s_plan_cap if getattr(alg, "x_s_second_start", False) else None)
        c_ = r_.evaluation.cost if (r_.plan is not None and r_.evaluation is not None and r_.evaluation.feasible) else None
        start_costs[str(ns)] = c_
        if c_ is not None and (res is None or c_ < res.evaluation.cost):
            res, start_used = r_, ns
    if res is None:
        res = r_
    wall = time.perf_counter() - t
    if res.plan is None or res.evaluation is None or not res.evaluation.feasible:
        meta = {"case_id": inst.case_id, "status": "NO_FEASIBLE_NOMINAL",
                "solver_status": res.status, "wall_s": wall}
        _write_json(out / "result.json", meta)
        return meta
    ev = res.evaluation
    if phys_nom is not phys:
        # 以真实储备重评价（抬高储备的可行解在真实参数下必可行），成本/H/核验均按真实参数
        ev = evaluate_plan(res.plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
        assert ev.feasible, ev.violations
    repair_actions: list[str] = []
    n_cross_before_repair = None
    if cross_launch and getattr(alg, "x_cross_robust", False) and ev is not None and ev.feasible:
        from .cross_robust import repair_nominal_cross
        from .evaluate import is_cross_sortie as _isc_before
        n_cross_before_repair = sum(1 for s in res.plan.sorties.values() if _isc_before(res.plan, s))
        slack_s = float(getattr(alg, "x_rendezvous_slack_s", 0.0) or 0.0)
        res.plan, repair_actions = repair_nominal_cross(res.plan, inst, phys, slack_s)
        ev = evaluate_plan(res.plan, inst, phys, initial_state(inst, phys), None, "NOMINAL")
    adopted_s = False
    adopt_reason = None
    if (adopt_from and cross_launch and ev is not None
            and (getattr(alg, "x_adopt_s_nominal", False) or makespan_cap is not None
                 or not ev.feasible)):
        if s_plan_cap is None:
            s_plan_cap, _, _ = load_case_nominal(inst, adopt_from)
            s_ev_cap = evaluate_plan(s_plan_cap, inst, phys, initial_state(inst, phys), None, "NOMINAL")
        s_plan, s_ev = s_plan_cap, s_ev_cap
        over_cap = False
        # 搜索时上限抬到阶段1，避免阶段1本身越限导致跨车移动全灭。
        # 最终对外的 X 方案仍必须 makespan ≤ S：否则评价用 H_S 时余量被吃掉（C50 只长 18s 也会在失败后变贵）。
        if makespan_cap is not None and ev.feasible and ev.timeline and ev.timeline.truck_finish:
            over_cap = max(ev.timeline.truck_finish.values()) > makespan_cap + 1e-6
        worse = (getattr(alg, "x_adopt_s_nominal", False) and s_ev is not None and s_ev.feasible
                 and ev.feasible and ev.cost is not None and s_ev.cost is not None
                 and ev.cost > s_ev.cost + 1e-9)
        keep_robust = False
        if (getattr(alg, "x_cross_robust", False) and ev.feasible and ev.timeline is not None
                and not over_cap):
            from .cross_robust import cross_robust_violations
            from .evaluate import is_cross_sortie as _isc_keep
            slack_s = float(getattr(alg, "x_rendezvous_slack_s", 0.0) or 0.0)
            has_cross = any(_isc_keep(res.plan, s) for s in res.plan.sorties.values())
            viol = cross_robust_violations(res.plan, inst, phys, ev.timeline, slack_s) if has_cross else {}
            tau = float(getattr(alg, "x_exchange_cost_tau", 0.0) or 0.0)
            within_tau = True
            if (s_ev is not None and s_ev.cost is not None and ev.cost is not None):
                within_tau = ev.cost <= s_ev.cost + tau + 1e-9
            # 稳健跨车可以比 S 贵，但贵不过 tau。否则先回到 S，再在 S 上试一次互换。
            keep_robust = has_cross and not viol and within_tau
        from .expected_cost import cost_gap_discards_nominal
        drop_for_cost = cost_gap_discards_nominal(
            bool(getattr(alg, "expected_accept", False)), worse) and not keep_robust
        if s_ev is not None and s_ev.feasible and (
                not ev.feasible or over_cap or drop_for_cost):
            if not ev.feasible:
                adopt_reason = "repair_infeasible"
            elif over_cap and worse:
                adopt_reason = "makespan_cap+cost"
            elif over_cap:
                adopt_reason = "makespan_cap"
            else:
                adopt_reason = "cost"
            res.plan, ev = s_plan, s_ev
            adopted_s = True
    # 诊断回退，默认关。打开后整份丢掉仍含跨车的 X 名义。正式设计要保留名义跨车，不走这里。
    if cross_launch and getattr(alg, "x_adopt_s_if_cross", False) and adopt_from:
        from .evaluate import is_cross_sortie as _is_cross
        if any(_is_cross(res.plan, s) for s in res.plan.sorties.values()):
            if s_plan_cap is None:
                s_plan_cap, _, _ = load_case_nominal(inst, adopt_from)
                s_ev_cap = evaluate_plan(s_plan_cap, inst, phys, initial_state(inst, phys), None, "NOMINAL")
            if s_plan_cap is not None and s_ev_cap is not None and s_ev_cap.feasible:
                res.plan, ev = s_plan_cap.clone(), s_ev_cap
                adopted_s = True
                adopt_reason = (adopt_reason + "+cross_nominal") if adopt_reason else "cross_nominal"
    polish_n = int(getattr(alg, "convert_polish_n", 0) or 0) if cross_launch else 0
    if polish_n > 0 and ev is not None and ev.feasible and res.plan is not None:
        from .alns import Budget, SearchStats, SolveContext
        from .cross_nominal import polish_with_convert
        from .evaluate import is_cross_sortie as _isc_pol
        if not any(_isc_pol(res.plan, s) for s in res.plan.sorties.values()):
            state_p = initial_state(inst, phys)
            state_p.nominal_cross = True
            cap_p = makespan_cap
            if cap_p is None and ev.timeline is not None and ev.timeline.truck_finish:
                cap_p = max(ev.timeline.truck_finish.values())
            ctx_p = SolveContext(inst=inst, phys=phys, alg=alg, state=state_p, H=None,
                                 mode="nominal", makespan_cap=cap_p)
            stats_p = SearchStats()
            b_p = Budget(polish_n, None)
            p_c, e_c = polish_with_convert(res.plan, ev, ctx_p, b_p, stats_p, polish_n)
            if p_c is not None and e_c is not None:
                res.plan, ev = p_c, e_c
                stats_p.aud("CONVERT_POLISH", "adopted")
                stats_p.aud("FUNNEL_CROSS", "published_polish")
            res.stats.eval_requests = int(res.stats.eval_requests) + int(b_p.used)
            if res.stats.counts is None:
                res.stats.counts = {}
            audit = res.stats.counts.setdefault("audit", {})
            for name, keys in stats_p.audit.items():
                bucket = audit.setdefault(name, {})
                for k, v in keys.items():
                    bucket[k] = bucket.get(k, 0) + v
    # 互换放在“是否退回 S”之后：阶段2没超过 S 时，基线就是 S，成本差是相对 S 的，
    # 不是相对还贵着几元到十几元的阶段1解。已经有跨车航次就不再叠第二条互换。
    if (cross_launch and getattr(alg, "x_cross_exchange", False) and ev is not None
            and ev.feasible and res.plan is not None):
        from .alns import SearchStats, _nominal_cross_intact, _within_makespan_cap
        from .cross_nominal import EXCHANGE_EVALS, _exchange_worth, try_cross_exchange
        from .evaluate import is_cross_sortie as _isc_ex
        state_ex = initial_state(inst, phys)
        state_ex.nominal_cross = True
        cap_ex = makespan_cap
        if cap_ex is None and ev.timeline is not None and ev.timeline.truck_finish:
            cap_ex = max(ev.timeline.truck_finish.values())
        ctx_ex = SolveContext(inst=inst, phys=phys, alg=alg, state=state_ex, H=None,
                              mode="nominal", makespan_cap=cap_ex)
        stats_ex = SearchStats()
        b_ex = Budget(EXCHANGE_EVALS, None)
        # 情景目标下，S 的计划也是 X 的可行候选。只在 S 的情景分更低时改用它，
        # 名义更贵但情景分更好的跨车方案会留下来。比较本身计入互换那 24 次评价。
        if getattr(alg, "scenario_aware", False) and adopt_from and b_ex.evals_left() > 0:
            if s_plan_cap is None:
                s_plan_cap, _, _ = load_case_nominal(inst, adopt_from)
                s_ev_cap = evaluate_plan(s_plan_cap, inst, phys, initial_state(inst, phys), None, "NOMINAL")
            if s_plan_cap is not None and s_ev_cap is not None and s_ev_cap.feasible:
                from .hybrid import scenario_score
                ctx_ex.live_budget = b_ex
                ctx_ex.live_stats = stats_ex
                ctx_ex.scenario_on = True
                score_x = scenario_score(res.plan, ev, ctx_ex)
                score_s = scenario_score(s_plan_cap, s_ev_cap, ctx_ex)
                if (score_x is not None and score_s is not None
                        and score_s < score_x - alg.cost_tolerance_yuan):
                    res.plan, ev = s_plan_cap.clone(), s_ev_cap
                    adopted_s = True
                    adopt_reason = "scenario"
                    stats_ex.aud("SCENARIO", "adopted_s")
        already = any(_isc_ex(res.plan, s) for s in res.plan.sorties.values())
        if not already:
            from .cross_robust import cross_robust_violations
            p_e, e_e = try_cross_exchange(res.plan, ctx_ex, b_ex, stats_ex, n=EXCHANGE_EVALS)
            slack_s = float(getattr(alg, "x_rendezvous_slack_s", 0.0) or 0.0)
            robust_ok = False
            if (p_e is not None and e_e is not None and e_e.feasible and e_e.timeline is not None):
                robust_ok = not cross_robust_violations(p_e, inst, phys, e_e.timeline, slack_s)
            ok = (robust_ok and _within_makespan_cap(e_e, ctx_ex)
                  and _nominal_cross_intact(p_e, e_e, ctx_ex))
            scenario_decided = False
            # 这 24 次物理评价经常已经用完。情景分记在单独的账本上，用完物理预算也要按它决定。
            if ok and getattr(alg, "scenario_aware", False):
                from .hybrid import scenario_score
                ctx_ex.live_budget = b_ex
                ctx_ex.live_stats = stats_ex
                ctx_ex.scenario_on = True
                s_new = scenario_score(p_e, e_e, ctx_ex)
                s_old = scenario_score(res.plan, ev, ctx_ex)
                if s_new is not None and s_old is not None:
                    scenario_decided = True
                    if s_new >= s_old - alg.cost_tolerance_yuan:
                        ok = False
                        stats_ex.aud("CROSS_EXCHANGE", "rejected_scenario")
            if ok and not scenario_decided:
                ok = _exchange_worth(e_e, ev, alg)
            if ok:
                res.plan, ev = p_e, e_e
                stats_ex.aud("CROSS_EXCHANGE", "adopted")
                stats_ex.aud("FUNNEL_CROSS", "accepted")
            else:
                stats_ex.aud("CROSS_EXCHANGE", "not_adopted")
        else:
            stats_ex.aud("CROSS_EXCHANGE", "skipped_existing")
        res.stats.eval_requests = int(res.stats.eval_requests) + int(b_ex.used)
        if res.stats.counts is None:
            res.stats.counts = {}
        audit = res.stats.counts.setdefault("audit", {})
        for name, keys in stats_ex.audit.items():
            bucket = audit.setdefault(name, {})
            for k, v in keys.items():
                bucket[k] = bucket.get(k, 0) + v
    H = max(ev.timeline.truck_finish.values()) + phys.shift_slack_s
    from .evaluate import is_cross_sortie as is_cross_sortie_
    if not cross_launch:   # S：名义阶段不得出现跨车航次
        from .evaluate import is_cross_sortie
        assert not any(is_cross_sortie(res.plan, s) for s in res.plan.sorties.values()), "S nominal has cross sortie"
    from .replay import verify_replay
    from .simulate import collect_segment, initial_run_state
    st0 = initial_run_state(res.plan, inst, phys)
    tl = ev.timeline
    t_end = max(list(tl.truck_finish.values()) +
                [s.end for lst in tl.drone_stages.values() for s in lst] + [0.0])
    seg = collect_segment(res.plan, tl, inst, phys, 0.0, t_end, st0)
    replay = verify_replay(inst, phys, [seg])
    rep = verify_plan(inst, initial_state(inst, phys), res.plan,
                      "X" if cross_launch else "S", phys, None)
    plan_id = f"{inst.case_id}-nominal-{SCHEMA_VERSION}"
    _write_json(out / "nominal_plan.json",
                {"plan_id": plan_id, "H_s": H, "algorithm_id": ALGORITHM_ID,
                 "plan": plan_to_dict(res.plan, inst)})
    _write_json(out / "cost.json",
                {"cost": ev.cost, "z_s": ev.z, "breakdown": ev.cost_breakdown,
                 "H_s": H, "nominal_eval_requests": res.stats.eval_requests})
    _write_json(out / "verification.json", replay.to_dict())
    _write_json(out / "verification_scheduler.json", rep.to_dict())
    _write_json(out / "config_snapshot.json",
                {"schema_version": SCHEMA_VERSION, "version": __version__,
                 "algorithm_id": ALGORITHM_ID, "generator_version": GENERATOR_VERSION,
                 "physical": asdict(phys), "algorithm": asdict(alg)})
    # 初始指派
    assign = []
    for v in res.plan.visits.values():
        for p in v.ground:
            assign.append({"parcel_id": p, "customer_id": v.customer, "mode": "GROUND",
                           "truck": v.truck, "visit_id": v.vid})
    for s in res.plan.sorties.values():
        for p in s.air:
            assign.append({"parcel_id": p, "customer_id": inst.parcel_to_customer[p],
                           "mode": "AIR", "drone": s.drone, "sortie_id": s.sid,
                           "launch_vid": s.launch_vid, "rec_vid": s.rec_vid})
    _write_csv(out / "initial_assignment.csv", assign,
               ["parcel_id", "customer_id", "mode", "truck", "drone", "visit_id", "sortie_id",
                "launch_vid", "rec_vid"])
    try:
        from .report import plot_nominal_route, plot_nominal_gantt
        plot_nominal_route(inst, res.plan, ev, out / "nominal_route.png")
        plot_nominal_gantt(inst, res.plan, ev, out / "nominal_gantt.png", H)
    except Exception as exc:  # noqa: BLE001
        (out / "figure_error.txt").write_text(str(exc), encoding="utf-8")
    meta = {
        "case_id": inst.case_id, "status": "FEASIBLE", "plan_id": plan_id, "H_s": H,
        "cost": ev.cost, "z_s": ev.z, "n_sorties": len(res.plan.sorties),
        "n_air_parcels": sum(len(s.air) for s in res.plan.sorties.values()),
        "n_visits": len(res.plan.visits), "eval_requests": res.stats.eval_requests,
        "wall_s": wall, "verified": bool(replay.ok), "verified_plan": bool(rep.ok),
        "start_trucks": start_used, "start_costs": start_costs,
        "distance_km": ev.cost_breakdown.get("truck_km"),
        "cost_breakdown": ev.cost_breakdown,
        "n_cross_sorties": sum(1 for s_ in res.plan.sorties.values() if is_cross_sortie_(res.plan, s_)),
        "cross_launch": bool(cross_launch),
        "audit": res.stats.counts.get("audit"), "reject": res.stats.counts.get("reject"),
        "last_improvement_iter": res.stats.counts.get("last_improvement_iter"),
        "n_iterations": res.stats.counts.get("n_alns_iterations"),
        "best_trace": res.stats.counts.get("best_trace"),
        "two_phase_b": two_phase_b, "phase1_evals": res.stats.counts.get("phase1_evals"),
        "phase1_cost": res.stats.counts.get("phase1_cost"),
        "phase1_cross": res.stats.counts.get("phase1_cross"),
        "phase1_makespan": res.stats.counts.get("phase1_makespan"),
        "makespan_cap_effective": res.stats.counts.get("makespan_cap_effective"),
        "phase1_audit": res.stats.counts.get("phase1_audit"),
        "n_route_columns": res.stats.counts.get("n_route_columns"),
        "n_link_columns": res.stats.counts.get("n_link_columns"),
        "n_sync_columns": res.stats.counts.get("n_sync_columns"),
        "adopted_s_nominal": adopted_s,
        "adopt_reason": adopt_reason,
        "n_cross_before_repair": n_cross_before_repair,
        "cross_repair": repair_actions,
        "makespan_cap": makespan_cap,
        "cap_basis": ("shift" if getattr(alg, "x_cap_is_shift", False) else "makespan"),
        "makespan_s": (max(ev.timeline.truck_finish.values())
                       if ev.timeline and ev.timeline.truck_finish else None),
    }
    _write_json(out / "result.json", meta)
    return meta


def nominal_plan_for_run(plan_s: Plan, plan: Plan, strategy: str, drop_cross: bool) -> Plan:
    """本回合使用的名义计划。

    S 用自己的计划。drop_cross 为真且 X 的名义仍含跨车航次时，改用 S 的名义的克隆。
    这是第 5 轮的诊断回退：它去掉名义阶段的跨车，只把跨车留在恢复里。正式设计不采用。
    克隆是为了不让 X 的恢复改写 S 那份计划对象。恢复时的策略仍是调用方传入的 X。
    """
    if strategy != "X" or not drop_cross:
        return plan
    from .evaluate import is_cross_sortie
    if any(is_cross_sortie(plan, s) for s in plan.sorties.values()):
        return plan_s.clone()
    return plan


def nominal_and_recovery(strategy: str, plan_s: Plan, plan_x: Plan, drop_cross: bool):
    """回合用的名义计划和恢复规则。

    S：自己的名义，同车恢复。
    R：冻结的 S 名义（克隆，恢复不会改写 S 的对象），恢复规则与 X 相同。
    X：自己的名义，跨车恢复。
    三者的恢复评价上限由调用方传入同一个数。
    """
    if strategy == "S":
        return plan_s, "S"
    if strategy in ("R", "X0"):
        # X0 与 X 用同一套恢复。当前名义搜索在关掉跨车之后就是 S 的路径，所以 X0 的名义等于 S。
        return plan_s.clone(), "X"
    return nominal_plan_for_run(plan_s, plan_x, "X", drop_cross), "X"


def load_case_nominal(inst: Instance, nominal_dir: str | Path) -> tuple[Plan, dict, float]:
    d = json.load(open(Path(nominal_dir) / "nominal_plan.json", encoding="utf-8"))
    plan = plan_from_dict(d["plan"])
    cost = json.load(open(Path(nominal_dir) / "cost.json", encoding="utf-8"))
    return plan, cost, float(d["H_s"])


# ---------------------------------------------------------------------------
# 单回合
# ---------------------------------------------------------------------------
def episode_metrics(ep) -> dict:
    """第三轮：每次运行的服务/时间指标与停止原因（S/X 对照用）.

    failed_delivery_delay：失败包裹从“到达客户点发现失败”到“地面交付结束”的时长；
    makespan：最晚卡车返库时刻；driver_total：各车工时之和；z_s：实际出库无人机最晚随车入库时刻。"""
    fail_time = {o.parcel_id: o.time_s for o in ep.observations if not o.air_delivery_available}
    deliv: dict[str, float] = {}
    for seg in ep.segments:
        for a in seg["actions"]:
            if a["kind"] == "G" and a.get("ref"):
                deliv[a["ref"]] = a["end"]
        for st in seg["stages"]:
            if st["kind"] == "SERVICE" and st.get("parcel"):
                deliv[st["parcel"]] = st["end"]
    delays = [deliv[p] - t for p, t in fail_time.items() if p in deliv]
    ok = ep.evaluation is not None and ep.evaluation.feasible
    tf = (ep.evaluation.counts or {}).get("truck_finish", {}) if ok else {}
    stop = [n[:300] for n in ep.notes if n.startswith(("STOP_CONTEXT", "INITIAL_RECOVERY_FAILED", "MAX_REPLANS"))]
    # 第四轮：失败触发的回收(被恢复的失败航次的 R 动作)与其中的跨车比例；例行回收不计入
    fsids = {f"S{sid}" for sid in getattr(ep, "failed_sids", [])}
    rec_f: dict[str, dict] = {}
    for seg in ep.segments:
        for a in seg["actions"]:
            if a["kind"] == "R" and a.get("ref") in fsids:
                rec_f[a["ref"]] = a
    n_fail_rec = len(rec_f)
    n_fail_cross = sum(1 for a in rec_f.values() if (a.get("launch_truck") or a["actor"]) != a["actor"])
    return {
        "n_fail_events": len(getattr(ep, "failed_sids", [])),
        "n_fail_rec": n_fail_rec,
        "n_fail_cross": n_fail_cross,
        "failed_delivery_delays_s": delays,
        "failed_delivery_delay_mean_s": (sum(delays) / len(delays)) if delays else None,
        "failed_delivery_delay_max_s": max(delays) if delays else None,
        "makespan_s": max(tf.values()) if tf else None,
        "driver_total_s": sum(tf.values()) if tf else None,
        "z_s_metric": ep.evaluation.z if ok else None,
        "n_swaps": (ep.replay.n_swaps if ep.replay is not None else None),
        "stop_reason": " | ".join(stop) if stop else None,
    }


def run_episode_dir(inst: Instance, nominal_plan: Plan, nominal_cost: dict, H: float,
                    phys: PhysicalConfig, alg: AlgorithmConfig, seed: int, strategy: str,
                    out_dir: str | Path, recovery_eval_budget: int | None = None,
                    recovery_wall_s: float | None = None, variant: str = "full",
                    make_figures: bool = True) -> dict:
    import shutil
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)          # 原子重写：不保留旧运行的核验/结果文件
    out.mkdir(parents=True, exist_ok=True)
    world = HiddenWorld(inst, inst.case_id, seed)
    rngs = derive_rngs(alg.base_algorithm_seed, inst.case_id, "recovery", 0)
    nom_ev = evaluate_plan(nominal_plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    ep = run_episode(inst, nominal_plan, nom_ev, H, phys, world, strategy, alg, rngs,
                     recovery_eval_budget=recovery_eval_budget, recovery_wall_s=recovery_wall_s,
                     variant=variant)
    run_id = f"{inst.case_id}-s{seed:02d}-{strategy}-{alg.base_algorithm_seed}"
    obs = [{"time_s": o.time_s, "parcel_id": o.parcel_id, "customer_id": o.customer_id,
            "air_delivery_available": o.air_delivery_available, "drone_id": o.drone_id}
           for o in ep.observations]
    _write_json(out / "run_metadata.json", {
        "schema_version": SCHEMA_VERSION, "project_version": __version__, "run_id": run_id,
        "case_id": inst.case_id, "strategy": strategy, "environment_seed": seed,
        "algorithm_id": ALGORITHM_ID, "algorithm_base_seed": alg.base_algorithm_seed,
        "generator_version": GENERATOR_VERSION, "H_s": H, "variant": variant,
        "recovery_eval_budget": recovery_eval_budget, "recovery_wall_s": recovery_wall_s,
        "recovery_decision": alg.recovery_decision, "operator_selector": alg.operator_selector,
        "recovery_init_eval_budget": alg.recovery_init_eval_budget,
    })
    with open(out / "public_events.jsonl", "w", encoding="utf-8") as f:
        for o in obs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    if ep.audit is not None:
        _write_json(out / "private_world_audit.json", asdict(ep.audit))
    with open(out / "replans.jsonl", "w", encoding="utf-8") as f:
        for r in ep.replans:
            f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")
    # ---- 全程执行账本（所有段） ----
    action_rows: list[dict] = []
    charge_rows: list[dict] = []
    rec_rows: list[dict] = []
    deliver: dict[str, dict] = {}
    for si, seg in enumerate(ep.segments):
        for a in seg["actions"]:
            action_rows.append({
                "segment": si, "kind": a["kind"], "actor": a["actor"],
                "start_s": a["start"], "end_s": a["end"], "ref": a.get("ref", ""),
                "drone": a.get("drone", ""), "customer": a.get("customer", ""),
                "dist_m": a.get("dist", 0.0), "parcels": ",".join(a.get("parcels", [])),
                "from_xy": (f"{a['from'][0]:.1f},{a['from'][1]:.1f}" if "from" in a else ""),
                "to_xy": (f"{a['to'][0]:.1f},{a['to'][1]:.1f}" if "to" in a else ""),
            })
            if a["kind"] == "G" and a.get("ref"):
                deliver[a["ref"]] = {"time": a["end"], "mode": "GROUND",
                                     "truck": a["actor"], "drone": "", "customer": a.get("customer")}
            if a["kind"] == "U":
                for p in a.get("parcels", []):
                    deliver.setdefault(p, {})["handover_time"] = a["start"]
            if a["kind"] == "R":
                rec_rows.append({
                    "segment": si, "recovery_truck_id": a["actor"], "drone_id": a.get("drone"),
                    "launch_truck_id": a.get("launch_truck", ""),
                    "recovery_customer_id": a.get("customer"), "R_start_s": a["start"],
                    "R_end_s": a["end"],
                    "same_truck": (a.get("launch_truck") == a["actor"]),
                    "onboard_parcels": ",".join(a.get("onboard", [])),
                    "handover_parcels": ",".join(a.get("handover", [])),
                    "n_undelivered_at_recovery": len(a.get("handover", [])),
                })
        for st in seg["stages"]:
            if st["kind"] == "SERVICE" and st.get("parcel"):
                deliver[st["parcel"]] = {"time": st["end"], "mode": "AIR",
                                         "truck": "", "drone": st["drone"],
                                         "customer": st.get("customer")}
            if st["kind"] in ("ON_TRUCK", "READY") and float(st.get("q_ac", 0.0)) > 0:
                charge_rows.append({"segment": si, "drone_id": st["drone"],
                                    "carrier": st.get("truck"), "start_s": st["start"],
                                    "end_s": st["end"], "ac_kwh": float(st["q_ac"]),
                                    "net_kwh": phys.slot_efficiency * float(st["q_ac"])})
    _write_csv(out / "actions.csv", action_rows,
               ["segment", "kind", "actor", "start_s", "end_s", "ref", "drone", "customer",
                "dist_m", "parcels", "from_xy", "to_xy"])
    parcel_rows = []
    for c in inst.customers:
        d = deliver.get(c.parcel_id)
        parcel_rows.append({"parcel_id": c.parcel_id, "customer_id": c.customer_id,
                            "mass_kg": c.mass_kg,
                            "final_mode": d.get("mode") if d else None,
                            "delivered_s": d.get("time") if d else None,
                            "truck": d.get("truck") if d else None,
                            "drone": d.get("drone") if d else None,
                            "air_failure_observed": any(
                                o.parcel_id == c.parcel_id and not o.air_delivery_available
                                for o in ep.observations)})
    _write_csv(out / "parcel_ledger.csv", parcel_rows,
               ["parcel_id", "customer_id", "mass_kg", "final_mode", "delivered_s",
                "truck", "drone", "air_failure_observed"])
    _write_csv(out / "charging_ledger.csv", charge_rows,
               ["segment", "drone_id", "carrier", "start_s", "end_s", "ac_kwh", "net_kwh"])
    _write_csv(out / "recovery_ledger.csv", rec_rows,
               ["segment", "recovery_truck_id", "drone_id", "launch_truck_id",
                "recovery_customer_id", "R_start_s", "R_end_s", "same_truck",
                "onboard_parcels", "handover_parcels", "n_undelivered_at_recovery"])
    term_rows = []
    if ep.replay is not None:
        for d, t in sorted(ep.replay.terminal.items()):
            carrier = t.get("carrier")
            term_rows.append({"drone_id": d, "final_carrier": carrier,
                              "truck_depot_arrival_s": ep.replay.truck_finish.get(carrier)
                              if hasattr(ep.replay, "truck_finish") else None,
                              "E_return_kwh": t.get("energy"),
                              "return_mode": "ON_TRUCK" if carrier else "AIRBORNE_AT_END"})
    _write_csv(out / "drone_terminal.csv", term_rows,
               ["drone_id", "final_carrier", "truck_depot_arrival_s", "E_return_kwh",
                "return_mode"])
    cost_obj = None
    if ep.evaluation is not None and ep.evaluation.feasible:
        cost_obj = {"cost": ep.evaluation.cost, "z_s": ep.evaluation.z,
                    "breakdown": ep.evaluation.cost_breakdown,
                    "replay_cost": ep.replay.cost if ep.replay else None,
                    "nominal_cost": nominal_cost.get("cost"),
                    "delta_vs_nominal": (ep.evaluation.cost - nominal_cost.get("cost")
                                         if nominal_cost.get("cost") else None)}
    _write_json(out / "cost.json", cost_obj or {"cost": None, "note": "no feasible suffix"})
    n_obs_fail = sum(1 for o in ep.observations if not o.air_delivery_available)
    verified = bool(ep.replay.ok) if ep.replay is not None else False
    if ep.replay is not None:
        _write_json(out / "verification.json", ep.replay.to_dict())
    result = {
        **episode_metrics(ep),
        "run_id": run_id, "case_id": inst.case_id, "strategy": strategy,
        "environment_seed": seed, "episode_status": ep.status,
        "configured_failure_count": world.configured_failure_count,
        "observed_air_failure_count": n_obs_fail,
        "observed_parcels": [o.parcel_id for o in ep.observations if not o.air_delivery_available],
        "hidden_failure_parcels": list(ep.audit.hidden_failure_parcels) if ep.audit else None,
        "cost": ep.evaluation.cost if ep.evaluation is not None else None,
        "z_s": ep.evaluation.z if ep.evaluation is not None else None,
        "n_replans": len(ep.replans) - 1,
        "replan_wall_s": ep.replan_times,
        "wall_s": ep.wall_s, "verified": verified,
        "replay_cost": ep.replay.cost if ep.replay is not None else None,
        "replay_violations": ep.replay.violations[:20] if ep.replay else [],
        "n_segments": len(ep.segments),
        "notes": ep.notes,
    }
    _write_json(out / "result.json", result)
    if make_figures:
        try:
            from .report import plot_episode_route, plot_episode_gantt, plot_energy
            plot_episode_route(inst, nominal_plan, ep.plan, ep.observations,
                               out / "route.png", title=f"{inst.case_id} {strategy} seed {seed}")
            plot_episode_gantt(inst, ep.plan, ep.evaluation, out / "gantt.png", H,
                               title=f"{inst.case_id} {strategy} seed {seed}")
            plot_energy(inst, ep.plan, ep.evaluation, out / "energy.png",
                        title=f"{inst.case_id} {strategy} seed {seed}")
        except Exception as exc:  # noqa: BLE001
            (out / "figure_error.txt").write_text(str(exc), encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# 批量
# ---------------------------------------------------------------------------
def paired_statistics(rows: list[dict]) -> dict:
    pairs = [r for r in rows if r.get("cost_S") is not None and r.get("cost_X") is not None]
    deltas = [r["cost_S"] - r["cost_X"] for r in pairs]
    out = {
        "n_environments": len(rows),
        "n_episodes": len(rows) * 2,
        "n_pairs": len(pairs),
        "mean_delta": statistics.mean(deltas) if deltas else None,
        "std_delta": statistics.stdev(deltas) if len(deltas) > 1 else None,
        "min_delta": min(deltas) if deltas else None,
        "max_delta": max(deltas) if deltas else None,
        "n_positive": sum(1 for d in deltas if d > 1e-9),
        "n_zero": sum(1 for d in deltas if abs(d) <= 1e-9),
        "n_negative": sum(1 for d in deltas if d < -1e-9),
    }
    if len(deltas) > 1:
        from scipy.stats import t as _t
        df = len(deltas) - 1
        crit = float(_t.ppf(0.975, df))
        se = out["std_delta"] / math.sqrt(len(deltas))
        out["se"] = se
        out["df"] = df
        out["t_critical_975"] = crit
        out["ci95_halfwidth"] = crit * se
        out["ci95_lower"] = out["mean_delta"] - crit * se
        out["ci95_upper"] = out["mean_delta"] + crit * se
    else:
        out["se"] = None
        out["df"] = None
        out["t_critical_975"] = None
        out["ci95_halfwidth"] = None
        out["ci95_lower"] = None
        out["ci95_upper"] = None
    return out


def run_batch(pkg: dict, cases: list[str], seeds: list[int], strategies: list[str],
              nominal_root: str | Path, out_root: str | Path, phys: PhysicalConfig,
              alg: AlgorithmConfig, recovery_eval_budget: int | None,
              recovery_wall_s: float | None, variant: str = "full",
              make_figures: bool = True, progress: bool = True) -> dict:
    out = Path(out_root)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.perf_counter()
    for case in cases:
        inst = load_instance(pkg, case)
        phys_c = phys.for_case(pkg.get("case_fleet"), case)
        nominal_dir = Path(nominal_root) / case
        nominal_plan, nominal_cost, H = load_case_nominal(inst, nominal_dir)
        for seed in seeds:
            res_by_strategy = {}
            for strategy in strategies:
                ep_dir = out / f"{case}_seed{seed:02d}_{strategy}"
                r = run_episode_dir(inst, nominal_plan, nominal_cost, H, phys_c, alg, seed,
                                    strategy, ep_dir, recovery_eval_budget=recovery_eval_budget,
                                    recovery_wall_s=recovery_wall_s, variant=variant,
                                    make_figures=make_figures)
                res_by_strategy[strategy] = r
            row = {
                "case_id": case, "environment_seed": seed,
                "status_S": res_by_strategy.get("S", {}).get("episode_status"),
                "status_X": res_by_strategy.get("X", {}).get("episode_status"),
                "cost_S": res_by_strategy.get("S", {}).get("cost"),
                "cost_X": res_by_strategy.get("X", {}).get("cost"),
                "obs_fail_S": res_by_strategy.get("S", {}).get("observed_air_failure_count"),
                "obs_fail_X": res_by_strategy.get("X", {}).get("observed_air_failure_count"),
                "configured_failures": res_by_strategy.get("S", {}).get("configured_failure_count"),
                "delta": None,
            }
            if row["cost_S"] is not None and row["cost_X"] is not None:
                row["delta"] = row["cost_S"] - row["cost_X"]
            rows.append(row)
            if progress:
                print(f"{case} seed{seed}: S={row['cost_S']} X={row['cost_X']} "
                      f"delta={row['delta']} obs={row['obs_fail_S']}/{row['obs_fail_X']}", flush=True)
    _write_csv(out / "episodes.csv", rows,
               ["case_id", "environment_seed", "status_S", "status_X", "cost_S", "cost_X",
                "delta", "obs_fail_S", "obs_fail_X", "configured_failures"])
    summ = paired_statistics(rows)
    by_case = {}
    for case in cases:
        sub = [r for r in rows if r["case_id"] == case]
        by_case[case] = paired_statistics(sub)
    summ["by_case"] = by_case
    summ["wall_s"] = time.perf_counter() - t0
    summ["variant"] = variant
    summ["recovery_eval_budget"] = recovery_eval_budget
    summ["recovery_wall_s"] = recovery_wall_s
    summ["recovery_decision"] = alg.recovery_decision
    summ["operator_selector"] = alg.operator_selector
    _write_json(out / "summary.json", summ)
    _write_csv(out / "paired_results.csv", rows,
               ["case_id", "environment_seed", "cost_S", "cost_X", "delta"])
    counts: dict[str, int] = {}
    for r in rows:
        for key in ("status_S", "status_X"):
            st = r.get(key)
            counts[f"{key}:{st}"] = counts.get(f"{key}:{st}", 0) + 1
    _write_csv(out / "status_counts.csv", [{"key": k, "count": v} for k, v in sorted(counts.items())],
               ["key", "count"])
    try:
        from .report import plot_paired
        plot_paired(rows, out / "paired_delta.png")
    except Exception as exc:  # noqa: BLE001
        (out / "figure_error.txt").write_text(str(exc), encoding="utf-8")
    return summ
