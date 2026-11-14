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


def _recourse_rows(plan, inst, phys):
    rows = []
    if plan is None:
        return rows
    for sortie in plan.sorties.values():
        if sortie.started or not sortie.air or sortie.rec_vid not in plan.visits:
            continue
        rows.append((sortie, _failure_cost(plan, inst, phys, sortie)))
    return rows


def _interactions(plan, inst, phys, rows) -> list[float]:
    """Proxy I_ij for sorties that compete for one recovery truck. Not truncated."""
    out = []
    for i, (left, cl) in enumerate(rows):
        for right, cr in rows[i + 1:]:
            if plan.visits[left.rec_vid].truck != plan.visits[right.rec_vid].truck:
                continue
            if not (_consecutive(plan, left, right) or left.rec_vid == right.rec_vid
                    or _overlap(plan, inst, phys, left, right)):
                continue
            out.append(min(cl, cr))
    return out


def recourse_terms(plan, inst, phys, p: float) -> tuple[float, float]:
    """返回 (Σ p Q_i, Σ p² I_ij)。p 越界时按 0 处理。"""
    p = float(p or 0.0)
    if p <= 0 or plan is None:
        return 0.0, 0.0
    rows = _recourse_rows(plan, inst, phys)
    single = p * sum(cost for _, cost in rows)
    pair = p * p * sum(_interactions(plan, inst, phys, rows))
    return single, pair


def _q_with_cross_rescue(plan, inst, phys, sortie, q: float) -> float:
    """X only. Q_i is the cheaper of ground insertion and a reachable other truck.

    The weights stay 3/(2N) and 1/(N(N-1)). S does not call this.
    """
    from .evaluate import is_cross_sortie
    if q <= 0 or plan is None or not sortie.air or is_cross_sortie(plan, sortie):
        return q
    if sortie.launch_vid not in plan.visits:
        return q
    launch = plan.visits[sortie.launch_vid].truck
    end = inst.customer(inst.parcel_to_customer[sortie.air[-1]])
    mass = sum(inst.parcel_mass[p] for p in sortie.air)
    near = []
    for truck, route in plan.routes.items():
        if truck == launch:
            continue
        for vid in route:
            c = inst.customer(plan.visits[vid].customer)
            dist = math.hypot(c.x - end.x, c.y - end.y)
            near.append((dist, vid))
    near.sort()
    best = q
    for dist, _vid in near[:3]:
        e = phys.fly_energy_kwh(dist, mass) + phys.hover_energy_kwh(phys.recovery_s, mass)
        if e > phys.e_cap - phys.e_min:
            continue
        # The other truck is already visiting this customer, so the truck detour is 0.
        meet = phys.cost_depot_kwh * e + phys.wage_per_s * phys.recovery_s
        # Keep half the ground-failure cost. A free meeting would otherwise
        # dominate J and accept a much more expensive nominal plan.
        best = min(best, 0.5 * q + 0.5 * meet)
    return best


def expected_j(cost: float | None, plan, inst, phys, p: float, v13: bool = False,
               rescue_aware: bool = False) -> float | None:
    """Search objective. v1.3 uses 3/(2N) and 1/(N(N-1)), not p=0.2 and p²."""
    if cost is None:
        return None
    rows = _recourse_rows(plan, inst, phys)
    if rescue_aware and v13:
        singles = sum(_q_with_cross_rescue(plan, inst, phys, s, q) for s, q in rows)
    else:
        singles = sum(q for _, q in rows)
    inter = sum(_interactions(plan, inst, phys, rows))
    n = int(getattr(inst, "n", 0) or 0)
    if v13 and n >= 2:
        return float(cost) + (3.0 / (2.0 * n)) * singles + (1.0 / (n * (n - 1))) * inter
    p = float(p or 0.0)
    return float(cost) + p * singles + (p * p) * inter


def failure_prob(alg) -> float:
    """Main-experiment planning weight. v1.3 is 3/(2N). There is no 0.2 default."""
    if getattr(alg, "v13_rules", False):
        n = int(getattr(alg, "v13_n", 0) or 0)
        if n < 2:
            raise RuntimeError("v1.3 planning has no N and will not fall back to another failure weight")
        return 3.0 / (2.0 * n)
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
    """没有跨车航次、且共用的 J 比基线差时，发布基线。

    只给 X 的发布用。有跨车航次时不介入。
    同车方案没有跨车结构。两次情景样本可以碰巧喜欢多飞的票，但 J 已经把每条航次的失败代价算进去了。
    这种情况下不再让情景样本推翻 J。scenario_* 保留是为了调用处兼容，不参与判断。
    """
    del scenario_plan, scenario_base
    from .evaluate import is_cross_sortie
    if plan is None or baseline is None or cost is None or baseline_cost is None:
        return False
    if any(is_cross_sortie(plan, sortie) for sortie in plan.sorties.values()):
        return False
    j_plan = expected_j(cost, plan, inst, phys, p)
    j_base = expected_j(baseline_cost, baseline, inst, phys, p)
    if j_plan is None or j_base is None:
        return False
    return j_base < j_plan - tol


def cross_j_rejects(plan, cost, baseline, baseline_cost, inst, phys, p: float, tol: float) -> bool:
    """有跨车航次、且 J 不严格低于同车基线时，不发布这些跨车。

    只给 X 的发布用。没有跨车航次时不介入，那条路仍由 same_truck_j_adopts_baseline 处理。
    """
    from .evaluate import is_cross_sortie
    if plan is None or baseline is None or cost is None or baseline_cost is None:
        return False
    if not any(is_cross_sortie(plan, sortie) for sortie in plan.sorties.values()):
        return False
    j_plan = expected_j(cost, plan, inst, phys, p)
    j_base = expected_j(baseline_cost, baseline, inst, phys, p)
    if j_plan is None or j_base is None:
        return False
    return not (j_plan < j_base - tol)


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
