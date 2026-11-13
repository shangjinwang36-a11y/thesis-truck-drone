"""名义接受用的期望执行成本，S 和 X 同一套。

J = C0 + p * Σ Q_i + p² * Σ Q_ij。Q_i 是这一趟失败后改地面的代理成本，
Q_ij 只加在会抢同一辆回收车的两趟上。不使用固定的 τ，也不按客户另加罚金。
写入结果的仍是真实 C0。最终留下哪一份计划，还要看真正的情景评价。
"""
from __future__ import annotations

import math


def _failure_cost(plan, inst, phys, sortie) -> float:
    from .moves import ground_candidates
    cost = phys.wage_per_s * phys.recovery_s
    for parcel in sortie.air:
        best = ground_candidates(plan, inst, phys, parcel)
        if best:
            cost += max(0.0, best[0].proxy)
            continue
        cust = inst.customer(inst.parcel_to_customer[parcel])
        dist = math.hypot(cust.x - inst.depot_x, cust.y - inst.depot_y)
        cost += phys.c_km * dist / 1000.0 + phys.wage_per_s * dist / phys.truck_speed_m_s
    return cost


def _overlap(plan, inst, phys, left, right) -> bool:
    from .moves import route_times
    def window(sortie):
        if sortie.launch_vid is None or sortie.rec_vid not in plan.visits:
            return None
        launch = plan.visits.get(sortie.launch_vid)
        rec = plan.visits[sortie.rec_vid]
        if launch is None:
            return None
        try:
            arr_l, dep_l = route_times(plan, inst, phys, launch.truck)
            arr_r, _ = route_times(plan, inst, phys, rec.truck)
            a = plan.routes[launch.truck].index(sortie.launch_vid)
            b = plan.routes[rec.truck].index(sortie.rec_vid)
        except (KeyError, ValueError):
            return None
        return dep_l[a], arr_r[b]
    wa, wb = window(left), window(right)
    if wa is None or wb is None:
        return False
    return wa[0] <= wb[1] and wb[0] <= wa[1]


def _consecutive(plan, left, right) -> bool:
    chain = plan.drone_sorties.get(left.drone, [])
    if left.drone != right.drone or left.sid not in chain or right.sid not in chain:
        return False
    return abs(chain.index(left.sid) - chain.index(right.sid)) == 1


def recourse_terms(plan, inst, phys, p: float) -> tuple[float, float]:
    """返回 (Σ p Q_i, Σ p² Q_ij)。p 越界时按 0 处理。"""
    p = float(p or 0.0)
    if p <= 0 or plan is None:
        return 0.0, 0.0
    rows = []
    for sortie in plan.sorties.values():
        if sortie.started or not sortie.air or sortie.rec_vid not in plan.visits:
            continue
        rows.append((sortie, _failure_cost(plan, inst, phys, sortie)))
    single = p * sum(cost for _, cost in rows)
    pair = 0.0
    for i, (left, cl) in enumerate(rows):
        for right, cr in rows[i + 1:]:
            if plan.visits[left.rec_vid].truck != plan.visits[right.rec_vid].truck:
                continue
            if not (_consecutive(plan, left, right) or left.rec_vid == right.rec_vid
                    or _overlap(plan, inst, phys, left, right)):
                continue
            pair += p * p * min(cl, cr)
    return single, pair


def expected_j(cost: float | None, plan, inst, phys, p: float) -> float | None:
    if cost is None:
        return None
    single, pair = recourse_terms(plan, inst, phys, p)
    return float(cost) + single + pair


def failure_prob(alg) -> float:
    p = float(getattr(alg, "scenario_p", 0.0) or 0.0)
    if p <= 0:
        p = float(getattr(alg, "failure_prob", 0.0) or 0.0)
    return p


def cost_gap_discards_nominal(expected_accept: bool, nominal_is_worse: bool) -> bool:
    """期望接受打开时，名义更贵本身不把方案退回 S。不可行和完工上限仍由调用方处理。"""
    if expected_accept:
        return False
    return bool(nominal_is_worse)


def same_truck_j_adopts_baseline(plan, cost, baseline, baseline_cost, inst, phys, p: float,
                                 tol: float, scenario_plan: float | None = None,
                                 scenario_base: float | None = None) -> bool:
    """没有跨车航次时，J 比基线差、情景分也没有更低，就发布基线。

    只给 X 的发布用。有跨车航次时不介入：那部分收益不靠这条门。
    情景分严格更低的方案留下来，即使 J 稍差。情景分缺失或打平时，用两边共用的 J。
    """
    from .evaluate import is_cross_sortie
    if plan is None or baseline is None or cost is None or baseline_cost is None:
        return False
    if any(is_cross_sortie(plan, sortie) for sortie in plan.sorties.values()):
        return False
    if (scenario_plan is not None and scenario_base is not None
            and scenario_plan < scenario_base - tol):
        return False
    j_plan = expected_j(cost, plan, inst, phys, p)
    j_base = expected_j(baseline_cost, baseline, inst, phys, p)
    if j_plan is None or j_base is None:
        return False
    return j_base < j_plan - tol


def insurance_room(plan, other, inst, phys, p: float) -> float:
    """新出现的跨车航次，允许名义成本升高不超过它自己的期望补救。"""
    from .evaluate import is_cross_sortie
    if plan is None:
        return 0.0
    old = set()
    if other is not None:
        old = {s.sid for s in other.sorties.values() if is_cross_sortie(other, s)}
    room = 0.0
    for sortie in plan.sorties.values():
        if not is_cross_sortie(plan, sortie) or sortie.sid in old:
            continue
        room += float(p or 0.0) * _failure_cost(plan, inst, phys, sortie)
    return room
