"""X-only terminal recovery move that deletes the recovery stop.

A sealed-champion diagnostic paid original J, not a free scenario pre-search.
Two families the first operator never emitted improve that J and the fixed
training score, and both stay inside the hard H and the robust timetable:

- RC100: the recovery stop has no ground parcel. Moving the terminal sortie
  onto another truck and deleting the stop gains about 22.5 on cost, J and
  the scenario score. The old gate required exactly one ground parcel.
- C100: absorbing the stop's one ground parcel gains about 0.8 on J and 3.4
  on the scenario score. The geometric proxy scored that plan at -2.3, so a
  hard proxy veto is a false negative. The proxy still ranks candidates. It
  does not veto them. At most two plans per parent are paid, and the original
  physical, J, scenario, H, robust and CAS gates decide.

Keeping the parent air parcels is a property of this move only. It is not a
global ban on removing air parcels and it does not change the publication
objective. S does not enter. Cargo that belongs to the receiving truck is not
offered. Scenario samples are not drawn here.
"""
from __future__ import annotations

from .cross_nominal import _detour
from .evaluate import has_wait_cycle, is_cross_sortie
from .expected_cost import failure_prob, recourse_terms
from .joint_air_promote import air
from .moves import air_energy, air_time, sortie_start, _pos
from .proposal_geometry import refresh


KIND = "SCHEDULE_CLOSED_DETOUR"
MAX_PER_PARENT = 2
MAX_PER_SEARCH = 4


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
        flown = air_energy(inst, phys, start, list(parcels), rec)
        fly_s = air_time(inst, phys, start, list(parcels), rec) - phys.launch_s
    except KeyError:
        return None
    if fly_s < -1e-9:
        return None
    ready = arrival + len(plan.visits[rec_vid].ground) * phys.ground_service_s
    hover = max(0.0, ready - (launch[1] + fly_s))
    truck_wait = max(0.0, (launch[1] + fly_s) - ready)
    return flown + phys.hover_energy_kwh(hover, 0.0), hover, truck_wait


def _apply(plan, sid, vid, taken, pos, rec_vid):
    cand = plan.clone()
    sortie = cand.sorties[sid]
    sortie.air = list(plan.sorties[sid].air)
    for offset, parcel in enumerate(taken):
        sortie.air.insert(pos + offset, parcel)
        cand.visits[vid].ground = [x for x in cand.visits[vid].ground if x != parcel]
    sortie.rec_vid = rec_vid
    removed = False
    if (vid in cand.visits and not cand.visits[vid].ground
            and not any(o.launch_vid == vid or o.rec_vid == vid for o in cand.sorties.values())):
        cand.remove_visit(vid)
        removed = True
    return cand, removed


def geometries(p, e, ctx, diag):
    from .complete_joint import version

    dg = diag
    dg.update(emitted=0, stops_seen=0, energy_rejected=0, owned_rejected=0,
              structure_rejected=0, proxy_ranked=0, best_proxy_j_gain=None,
              native_calls=0)
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
    room = min(MAX_PER_PARENT, MAX_PER_SEARCH - used)
    if room <= 0:
        dg["skip"] = "SEARCH_CAP"
        return []
    inst, phys = ctx.inst, ctx.phys
    p_fail = failure_prob(ctx.alg)
    # Battery floor only. The 90 s slack and the margin are the paid robust gate.
    loose = phys.e_cap - phys.e_min + phys.energy_tol
    parent_risk = sum(recourse_terms(p, inst, phys, p_fail))
    parent_air = air(p)
    parent_version = version(p)
    ranked = []
    for sid, sortie in list(p.sorties.items()):
        chain = p.drone_sorties.get(sortie.drone, [])
        if not chain or chain[-1] != sid or sortie.started or sortie.launch_vid is None:
            continue
        if sortie.rec_vid not in p.visits or sortie.launch_vid not in p.visits:
            continue
        vid = sortie.rec_vid
        visit = p.visits[vid]
        truck = visit.truck
        if p.visits[sortie.launch_vid].truck != truck:
            continue
        if any(o.sid != sid and (o.launch_vid == vid or o.rec_vid == vid) for o in p.sorties.values()):
            continue
        ground = list(visit.ground)
        mass = sum(inst.parcel_mass[x] for x in sortie.air) + sum(inst.parcel_mass[x] for x in ground)
        if mass > phys.drone_payload_limit_kg + 1e-9:
            continue
        dg["stops_seen"] += 1
        det = _detour(inst, p, truck, vid)
        yuan = phys.c_km * det / 1000.0 + phys.wage_per_s * det / phys.truck_speed_m_s
        taken = tuple(sorted(ground, key=lambda x: (inst.parcel_mass[x], x)))
        old = _leg(inst, phys, p, sortie, sortie.air, sortie.rec_vid, tl)
        if old is None:
            continue
        parcels = list(sortie.air) + list(taken)
        for pos in range(len(sortie.air) + 1):
            for other, route in p.routes.items():
                if other == truck:
                    continue
                for rec_vid in route:
                    if _owns(p, inst, other, parcels):
                        dg["owned_rejected"] += 1
                        continue
                    flown = _leg(inst, phys, p, sortie, parcels, rec_vid, tl)
                    if flown is None or flown[0] > loose:
                        dg["energy_rejected"] += 1
                        continue
                    cand, removed = _apply(p, sid, vid, taken, pos, rec_vid)
                    if (not removed or air(cand) != parent_air | set(taken)
                            or cand.validate_structure(inst, phys) or has_wait_cycle(cand)
                            or not is_cross_sortie(cand, cand.sorties[sid])):
                        dg["structure_rejected"] += 1
                        continue
                    child_risk = sum(recourse_terms(cand, inst, phys, p_fail))
                    proxy_delta = (-yuan + phys.cost_depot_kwh * (flown[0] - old[0])
                                   + phys.wage_per_s * (flown[1] + flown[2])
                                   + (child_risk - parent_risk))
                    gain = -proxy_delta
                    if dg["best_proxy_j_gain"] is None or gain > dg["best_proxy_j_gain"]:
                        dg["best_proxy_j_gain"] = gain
                    ranked.append((gain, cand, dict(
                        kind=KIND,
                        construction="SCHEDULE_CLOSED_DETOUR_CROSS",
                        sortie=sid,
                        parcel=taken[0] if len(taken) == 1 else "",
                        parcels=list(taken),
                        old_visit=vid,
                        new_rendezvous=rec_vid,
                        insert_position=pos,
                        receiver=other,
                        predicted_energy_kwh=flown[0],
                        predicted_hover_s=flown[1],
                        predicted_truck_wait_s=flown[2],
                        geometric_detour_yuan=yuan,
                        proxy_j_gain=gain,
                        stop_removed=True,
                        parent_air_kept=True,
                        proxy_does_not_veto=True,
                        approximate_clock_not_native_schedule=True,
                        paid_parent_timeline=True,
                        operator_origin="DIRECT_SCHEDULE_CLOSED_DETOUR",
                        feedback_chain=[],
                        refinement_origin=None,
                    )))
    ranked.sort(key=lambda row: -row[0])
    out = []
    seen = set()
    for gain, cand, desc in ranked:
        dg["proxy_ranked"] += 1
        if len(out) >= room:
            break
        vv = version(cand)
        if vv == parent_version or vv in seen:
            continue
        seen.add(vv)
        out.append((cand, refresh(cand, desc, inst)))
    ctx.alg._schedule_closed_emitted = used + len(out)
    dg.update(emitted=len(out), native_calls=0)
    return out
