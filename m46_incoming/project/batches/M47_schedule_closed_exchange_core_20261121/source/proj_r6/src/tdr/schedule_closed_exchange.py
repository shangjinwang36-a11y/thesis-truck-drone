"""X-only: delete one recovery-only truck stop by flying its parcel onward.

The published M46 plans have no pure drone-support stop left, and swapping two
terminal recoveries keeps both truck routes. Those swaps are physically feasible
on C100 and R100 and keep the air set, but original J gets worse, so they are
not generated.

What can still cut cost is a stop that exists only to recover one terminal
sortie and to ground-deliver one parcel. The parcel joins that sortie, the
sortie recovers at another truck's existing visit, and the stop is removed.
Hover and energy use the parent evaluation's launch ending and visit arrival.
A candidate is emitted only when the same Q terms as original J, plus the
geometric detour and the paid-timeline hover, predict a lower J. The paid
physical, J, scenario, H, robust and CAS gates are unchanged.

S never enters. No new empty sortie is opened. Air may grow by that one parcel
and may not shrink.
"""
from __future__ import annotations

from .cross_nominal import _detour
from .cross_robust import max_occupancy, reserve_kwh, slack_floor_kwh
from .evaluate import has_wait_cycle, is_cross_sortie
from .expected_cost import failure_prob, recourse_terms
from .joint_air_promote import air
from .moves import air_energy, air_time, sortie_start, _pos
from .proposal_geometry import refresh


KIND = "SCHEDULE_CLOSED_DETOUR"
MAX_PER_PARENT = 4
MAX_PER_SEARCH = 8


def _owns(plan, inst, truck, parcels) -> bool:
    customers = {plan.visits[v].customer for v in plan.routes.get(truck, [])}
    return any(inst.parcel_to_customer.get(x) in customers for x in parcels)


def _leg(inst, phys, plan, sortie, parcels, rec_vid, tl):
    launch = tl.launch_times.get(sortie.sid)
    arrival = tl.visit_arr.get(rec_vid)
    if launch is None or arrival is None:
        return None
    start = sortie_start(inst, plan, sortie)
    rec = _pos(inst, plan, rec_vid)
    try:
        flown = air_energy(inst, phys, start, parcels, rec)
        fly_s = air_time(inst, phys, start, parcels, rec) - phys.launch_s
    except KeyError:
        return None
    if fly_s < -1e-9:
        return None
    ready = arrival + len(plan.visits[rec_vid].ground) * phys.ground_service_s
    hover = max(0.0, ready - (launch[1] + fly_s))
    truck_wait = max(0.0, (launch[1] + fly_s) - ready)
    return flown + phys.hover_energy_kwh(hover, 0.0), hover, truck_wait


def geometries(p, e, ctx, diag):
    from .complete_joint import version

    dg = diag
    dg.update(emitted=0, stops_seen=0, energy_rejected=0, owned_rejected=0,
              slot_rejected=0, proxy_rejected=0, structure_rejected=0,
              best_proxy_j_gain=None)
    if not bool(getattr(ctx.state, "nominal_cross", False)):
        dg["skip"] = "S_OR_NO_CROSS"
        return []
    if tuple(sorted(air(p))) not in getattr(ctx.alg, "_mature_fullpool_air_sets", set()):
        dg["skip"] = "NO_ORIGINAL_MATURE_FULLPOOL_CAS"
        return []
    tl = getattr(e, "timeline", None)
    if tl is None or e.cost is None or not getattr(tl, "visit_arr", None):
        dg["skip"] = "NO_PAID_PARENT_TIMELINE"
        return []
    if any(s.started or s.handover for s in p.sorties.values()):
        dg["skip"] = "NOT_INITIAL_COMPLETE_NOMINAL"
        return []
    used = int(getattr(ctx.alg, "_schedule_closed_emitted", 0))
    room = MAX_PER_SEARCH - used
    if room <= 0:
        dg["skip"] = "SEARCH_CAP"
        return []
    inst, phys = ctx.inst, ctx.phys
    p_fail = failure_prob(ctx.alg)
    tol = float(getattr(ctx.alg, "cost_tolerance_yuan", 1e-6) or 1e-6)
    slack = float(getattr(ctx.alg, "x_rendezvous_slack_s", 0.0) or 0.0)
    need = max(reserve_kwh(phys), slack_floor_kwh(phys, slack))
    ceiling = phys.e_cap - need + phys.energy_tol
    parent_risk = sum(recourse_terms(p, inst, phys, p_fail))
    parent_air = air(p)
    parent_version = version(p)
    ranked = []
    for truck, route in p.routes.items():
        for vid in route:
            visit = p.visits[vid]
            launches = [s for s in p.sorties.values() if s.launch_vid == vid]
            recs = [s for s in p.sorties.values() if s.rec_vid == vid]
            if launches or len(visit.ground) != 1 or len(recs) != 1:
                continue
            sortie = recs[0]
            chain = p.drone_sorties.get(sortie.drone, [])
            if not chain or chain[-1] != sortie.sid or sortie.launch_vid is None:
                continue
            parcel = visit.ground[0]
            parcels0 = list(sortie.air)
            mass = sum(inst.parcel_mass[x] for x in parcels0) + inst.parcel_mass[parcel]
            if mass > phys.drone_payload_limit_kg + 1e-9:
                continue
            dg["stops_seen"] += 1
            yuan = (phys.c_km * _detour(inst, p, truck, vid) / 1000.0
                    + phys.wage_per_s * _detour(inst, p, truck, vid) / phys.truck_speed_m_s)
            old = _leg(inst, phys, p, sortie, parcels0, sortie.rec_vid, tl)
            if old is None:
                continue
            for pos in range(len(parcels0) + 1):
                parcels = parcels0[:pos] + [parcel] + parcels0[pos:]
                for other, other_route in p.routes.items():
                    if other == truck:
                        continue
                    for rec_vid in other_route:
                        if _owns(p, inst, other, parcels):
                            dg["owned_rejected"] += 1
                            continue
                        leg = _leg(inst, phys, p, sortie, parcels, rec_vid, tl)
                        if leg is None or leg[0] > ceiling:
                            dg["energy_rejected"] += 1
                            continue
                        ready_wait = leg[2]
                        t0 = tl.visit_arr[rec_vid]
                        t1 = tl.truck_finish.get(other, t0)
                        if max_occupancy(p, phys, tl, other, t0, t1) + 1 > phys.truck_drone_slots:
                            dg["slot_rejected"] += 1
                            continue
                        ranked.append((yuan, leg[0], sortie.sid, vid, parcel, pos, rec_vid, other, leg, old, ready_wait))
    # One receiver per stop: largest geometric detour, then lowest energy.
    best = {}
    for row in ranked:
        key = (row[2], row[3])
        cur = best.get(key)
        if cur is None or (row[0], -row[1]) > (cur[0], -cur[1]):
            best[key] = row
    out = []
    seen = set()
    for row in sorted(best.values(), key=lambda z: (-z[0], z[1])):
        if len(out) >= min(MAX_PER_PARENT, room):
            break
        yuan, energy, sid, vid, parcel, pos, rec_vid, other, leg, old, truck_wait = row
        cand = p.clone()
        sortie = cand.sorties[sid]
        sortie.air = list(p.sorties[sid].air)
        sortie.air.insert(pos, parcel)
        sortie.rec_vid = rec_vid
        cand.visits[vid].ground = [x for x in cand.visits[vid].ground if x != parcel]
        if (not cand.visits[vid].ground
                and not any(o.launch_vid == vid or o.rec_vid == vid for o in cand.sorties.values())):
            cand.remove_visit(vid)
        if (air(cand) != parent_air | {parcel} or cand.validate_structure(inst, phys)
                or has_wait_cycle(cand) or not is_cross_sortie(cand, cand.sorties[sid])):
            dg["structure_rejected"] += 1
            continue
        child_risk = sum(recourse_terms(cand, inst, phys, p_fail))
        delta_e = leg[0] - old[0]
        proxy_delta = (-yuan + phys.cost_depot_kwh * delta_e
                       + phys.wage_per_s * (leg[1] + truck_wait) + (child_risk - parent_risk))
        gain = -proxy_delta
        if dg["best_proxy_j_gain"] is None or gain > dg["best_proxy_j_gain"]:
            dg["best_proxy_j_gain"] = gain
        if proxy_delta >= -tol:
            dg["proxy_rejected"] += 1
            continue
        vv = version(cand)
        if vv == parent_version or vv in seen:
            continue
        seen.add(vv)
        desc = dict(
            kind=KIND,
            construction="SCHEDULE_CLOSED_DETOUR_CROSS",
            sortie=sid,
            parcel=parcel,
            parcels=[parcel],
            old_visit=vid,
            new_rendezvous=rec_vid,
            insert_position=pos,
            receiver=other,
            predicted_energy_kwh=leg[0],
            predicted_hover_s=leg[1],
            predicted_truck_wait_s=truck_wait,
            geometric_detour_yuan=yuan,
            proxy_j_gain=gain,
            all_old_air_preserved=True,
            approximate_clock_not_native_schedule=True,
            paid_parent_timeline=True,
            operator_origin="DIRECT_SCHEDULE_CLOSED_DETOUR",
            feedback_chain=[],
            refinement_origin=None,
        )
        out.append((cand, refresh(cand, desc, inst)))
    ctx.alg._schedule_closed_emitted = used + len(out)
    dg.update(emitted=len(out), native_calls=0)
    return out
