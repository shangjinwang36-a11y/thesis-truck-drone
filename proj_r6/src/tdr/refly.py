"""第四轮：X 专属恢复算子，显式比较“卡车绕路/地面改派”和“从任一合格卡车再飞”。

S 恒不产生候选。是否接受由调用方按词典序真实成本比较，并加上已知失败概率下的期望失败代价
（见 moves.new_air_risk_charge）。这里最多交出 1 个计划，避免吃掉同一份恢复评价预算。
"""
from __future__ import annotations

import math

from .moves import air_candidates, apply_air


def _coupled(plan, vid) -> bool:
    return any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values())


def _pos(inst, plan, vid):
    c = inst.customer(plan.visits[vid].customer)
    return (c.x, c.y)


def _detour_cost(plan, inst, phys, vid) -> float:
    """这个访问相对“跳过它”的里程 + 工资 + 地面服务。只对纯地面访问有意义。"""
    v = plan.visits[vid]
    route = plan.routes.get(v.truck, [])
    if vid not in route:
        return 0.0
    i = route.index(vid)
    depot = (inst.depot_x, inst.depot_y)
    prev = depot if i == 0 else _pos(inst, plan, route[i - 1])
    nxt = depot if i + 1 >= len(route) else _pos(inst, plan, route[i + 1])
    here = _pos(inst, plan, vid)
    delta = (math.hypot(prev[0] - here[0], prev[1] - here[1])
             + math.hypot(here[0] - nxt[0], here[1] - nxt[1])
             - math.hypot(prev[0] - nxt[0], prev[1] - nxt[1]))
    w = phys.wage_per_s
    return (phys.c_km * delta / 1000.0 + w * delta / phys.truck_speed_m_s
            + w * phys.ground_service_s * max(1, len(v.ground)))


def _air_lower_bound(inst, phys, plan, parcel, here) -> float:
    """最近已有访问的往返飞行电费 + 准备/回收工资。用来在调用跨车枚举之前丢掉明显不值的票。"""
    best = None
    for route in plan.routes.values():
        for vid in route:
            p = _pos(inst, plan, vid)
            d = math.hypot(p[0] - here[0], p[1] - here[1])
            if best is None or d < best:
                best = d
    dist = 0.0 if best is None else best
    mass = inst.parcel_mass[parcel]
    e = phys.fly_energy_kwh(2.0 * dist, mass)
    return phys.wage_per_s * (phys.prepare_s + phys.recovery_s) + phys.cost_depot_kwh * e


def propose(plan, ctx, k: int = 1) -> list:
    """返回至多 k 个 (tag, plan)。非 X、或没开风险价时返回空。"""
    if ctx.strategy != "X" or not getattr(ctx.alg, "x_risk_price_air", False):
        return []
    if ctx.mode != "recovery":
        return []
    p_fail = float(getattr(ctx.alg, "failure_prob", 0.0) or 0.0)
    if p_fail <= 0:
        return []
    inst, phys, state = ctx.inst, ctx.phys, ctx.state
    ceiling = set(ctx.air_ceiling or [])
    delivered = set(getattr(state, "delivered", set()) or set())
    from .recovery import _fixed_first_vids
    protect = _fixed_first_vids(plan, state)
    overhead = phys.wage_per_s * phys.recovery_s
    ranked = []
    for vid, v in plan.visits.items():
        if vid in protect or _coupled(plan, vid) or len(v.ground) != 1:
            continue
        parcel = v.ground[0]
        if parcel in ceiling or parcel in delivered:
            continue
        g = _detour_cost(plan, inst, phys, vid)
        here = _pos(inst, plan, vid)
        charge = p_fail * (max(0.0, g) + overhead)
        lb = _air_lower_bound(inst, phys, plan, parcel, here)
        gap = g - lb - charge
        if gap <= 1e-6:
            continue
        ranked.append((gap, vid, parcel))
    ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
    # 每次只认真枚举绕路最大的那一票。同车候选先试，不够再补跨车，避免每次迭代都扫完整跨车邻域。
    out = []
    for _, vid, parcel in ranked[:1]:
        if len(out) >= k:
            break
        g = _detour_cost(plan, inst, phys, vid)
        charge = p_fail * (max(0.0, g) + overhead)
        airs = air_candidates(plan, inst, phys, parcel, state=state,
                              min_pos=state.truck_min_insert or None)
        if not airs or airs[0].proxy + charge >= g - 1e-6:
            airs = air_candidates(plan, inst, phys, parcel, state=state,
                                  min_pos=state.truck_min_insert or None, allow_cross=True)
        if not airs:
            continue
        cand = airs[0]
        if cand.proxy + charge >= g - 1e-6:
            continue
        trial = plan.clone()
        v = trial.visits.get(vid)
        if v is None or parcel not in v.ground:
            continue
        v.ground = [x for x in v.ground if x != parcel]
        if not apply_air(trial, inst, parcel, cand, phys=phys):
            continue
        if not v.ground and not _coupled(trial, vid) and vid not in protect:
            truck = v.truck
            if vid in trial.routes.get(truck, []):
                trial.routes[truck].remove(vid)
            trial.visits.pop(vid, None)
        out.append(("REFLY_VS_DETOUR", trial))
    return out
