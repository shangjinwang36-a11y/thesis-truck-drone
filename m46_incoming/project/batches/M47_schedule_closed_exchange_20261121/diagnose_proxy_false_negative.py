"""Diagnostic, not fresh. Paid native physical + original J on a wider family.

The production operator refuses a stop unless it is a terminal recovery, holds
one ground parcel, clears the slack energy floor, and has a positive J proxy.
This script drops those gates one at a time, pays at most eight native
evaluations per sealed X champion, and records whether the proxy would have
rejected a plan whose original J improves. Scenario draws are not used.
"""
from pathlib import Path
import json
import pickle
import sys
import time

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
SEAL = HERE.parent / "M46_paid_training_robust_joint_20261121"
sys.path.insert(0, str(CORE))

from research import setup  # noqa: E402
import run_emin005 as rr  # noqa: E402
from tdr.alns import Budget  # noqa: E402
from tdr.cross_nominal import _detour  # noqa: E402
from tdr.cross_robust import cross_robust_violations, max_occupancy  # noqa: E402
from tdr.evaluate import has_wait_cycle, is_cross_sortie  # noqa: E402
from tdr.expected_cost import expected_j, failure_prob, recourse_terms  # noqa: E402
from tdr.joint_air_promote import air  # noqa: E402
from tdr.moves import air_energy, air_time, sortie_start, _pos  # noqa: E402

PAY_PER_MAP = 8


def owns(plan, inst, truck, parcels):
    customers = {plan.visits[v].customer for v in plan.routes.get(truck, [])}
    return any(inst.parcel_to_customer.get(x) in customers for x in parcels)


def leg(inst, phys, plan, sortie, parcels, rec_vid, tl):
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


def build(plan, sid, vid, parcel_ids, pos, rec_vid):
    cand = plan.clone()
    sortie = cand.sorties[sid]
    sortie.air = list(plan.sorties[sid].air)
    for offset, parcel in enumerate(parcel_ids):
        sortie.air.insert(pos + offset, parcel)
        cand.visits[vid].ground = [x for x in cand.visits[vid].ground if x != parcel]
    sortie.rec_vid = rec_vid
    removed = False
    if vid in cand.visits and not cand.visits[vid].ground and not any(
            o.launch_vid == vid or o.rec_vid == vid for o in cand.sorties.values()):
        cand.remove_visit(vid)
        removed = True
    return cand, removed


def enumerate_rows(plan, inst, phys, tl):
    """Structural family wider than the production operator. No native call."""
    rows = []
    loose = phys.e_cap - phys.e_min + phys.energy_tol
    for sid, sortie in plan.sorties.items():
        if sortie.started or sortie.launch_vid is None or sortie.rec_vid not in plan.visits:
            continue
        chain = plan.drone_sorties.get(sortie.drone, [])
        if sid not in chain:
            continue
        terminal = chain[-1] == sid
        vid = sortie.rec_vid
        visit = plan.visits[vid]
        launches = [s for s in plan.sorties.values() if s.launch_vid == vid and s.sid != sid]
        # Keep the stop's other launch users; only absorb ground that this sortie can lift.
        if launches:
            continue
        truck = visit.truck
        if plan.visits[sortie.launch_vid].truck != truck and not terminal:
            continue
        ground = list(visit.ground)
        # Subsets: nothing, or a prefix of the lightest parcels that fit.
        options = [()]
        light = sorted(ground, key=lambda x: (inst.parcel_mass[x], x))
        acc = []
        mass = sum(inst.parcel_mass[x] for x in sortie.air)
        for parcel in light:
            if mass + inst.parcel_mass[parcel] > phys.drone_payload_limit_kg + 1e-9:
                break
            acc.append(parcel)
            mass += inst.parcel_mass[parcel]
            options.append(tuple(acc))
        det = _detour(inst, plan, truck, vid)
        yuan = phys.c_km * det / 1000.0 + phys.wage_per_s * det / phys.truck_speed_m_s
        old = leg(inst, phys, plan, sortie, list(sortie.air), sortie.rec_vid, tl)
        if old is None:
            continue
        for taken in options:
            parcels = list(sortie.air) + list(taken)
            for other, route in plan.routes.items():
                if other == truck:
                    continue
                for rec_vid in route:
                    if owns(plan, inst, other, parcels):
                        continue
                    flown = leg(inst, phys, plan, sortie, parcels, rec_vid, tl)
                    if flown is None or flown[0] > loose:
                        continue
                    # Production shape: terminal, exactly the one ground parcel, stop deleted.
                    production_shape = terminal and taken == tuple(ground) and len(ground) == 1
                    rows.append(dict(
                        sid=sid, vid=vid, taken=taken, rec_vid=rec_vid, other=other,
                        terminal=terminal, yuan=yuan if taken or not ground else 0.0,
                        delete_possible=not ground or set(taken) == set(ground),
                        production_shape=production_shape,
                        energy=flown[0], hover=flown[1], truck_wait=flown[2], old_energy=old[0],
                    ))
    return rows


def proxy_gain(plan, inst, phys, p_fail, row, cand):
    parent_risk = sum(recourse_terms(plan, inst, phys, p_fail))
    child_risk = sum(recourse_terms(cand, inst, phys, p_fail))
    delta = (-(row["yuan"] if row["delete_possible"] else 0.0)
             + phys.cost_depot_kwh * (row["energy"] - row["old_energy"])
             + phys.wage_per_s * (row["hover"] + row["truck_wait"])
             + (child_risk - parent_risk))
    return -delta


def main():
    report = []
    grand = Budget(PAY_PER_MAP * 6, None)
    for case in ["C50", "R50", "RC50", "C100", "R100", "RC100"]:
        inst, phys, alg = setup(case, "M47", True)
        phys.set_active()
        _a, _b, plan, ev, state, ref = pickle.loads(
            (SEAL / f"fresh_new/{case}/X_live/normal_terminal_final.pkl").read_bytes())
        tl = ev.timeline
        p_fail = failure_prob(alg)
        parent_j = expected_j(ev.cost, plan, inst, phys, p_fail)
        tic = time.process_time()
        rows = enumerate_rows(plan, inst, phys, tl)
        # Prefer plans that delete a stop, then large detour, then low energy.
        rows.sort(key=lambda r: (not r["delete_possible"], -r["yuan"], r["energy"]))
        paid = []
        seen = set()
        local = Budget(PAY_PER_MAP, None)
        false_neg = 0
        for row in rows:
            if local.evals_left() <= 0:
                break
            key = (row["sid"], row["vid"], row["taken"], row["rec_vid"])
            if key in seen:
                continue
            seen.add(key)
            cand, removed = build(plan, row["sid"], row["vid"], row["taken"], 0, row["rec_vid"])
            if (cand.validate_structure(inst, phys) or has_wait_cycle(cand)
                    or not is_cross_sortie(cand, cand.sorties[row["sid"]])):
                continue
            gain_hat = proxy_gain(plan, inst, phys, p_fail, row, cand)
            ee = rr.evaluate_plan(cand, inst, phys, state, ref, "M47_PROXY_AUDIT", budget=local)
            grand.used += 1 if ee.status != "BUDGET_EXHAUSTED" else 0
            # evaluate_plan charges local via budget object.
            j = expected_j(ee.cost, cand, inst, phys, p_fail) if ee.feasible else None
            j_gain = None if j is None else parent_j - j
            robust = None
            if ee.feasible and ee.timeline is not None:
                robust = cross_robust_violations(cand, inst, phys, ee.timeline, float(alg.x_rendezvous_slack_s or 0))
            if gain_hat < 0 and j_gain is not None and j_gain > 1e-6:
                false_neg += 1
            paid.append(dict(
                sid=row["sid"], terminal=row["terminal"], taken=list(row["taken"]),
                receiver=row["other"], detour_yuan=round(row["yuan"], 3),
                stop_removed=removed, production_shape=row["production_shape"],
                proxy_j_gain=round(gain_hat, 3),
                feasible=bool(ee.feasible),
                cost_gain=None if ee.cost is None else round(ev.cost - ee.cost, 3),
                j_gain=None if j_gain is None else round(j_gain, 3),
                robust_tags=sorted({t.split(":")[0] for tags in (robust or {}).values() for t in tags}),
                violation=(ee.violations[0][:80] if ee.violations else ""),
                air_delta=len(air(cand)) - len(air(plan)),
            ))
        report.append(dict(
            case=case, enumerated=len(rows), paid=len(paid),
            false_negative_j=false_neg,
            best_j=max((x["j_gain"] for x in paid if x["j_gain"] is not None), default=None),
            best_feasible_cost=max((x["cost_gain"] for x in paid if x["feasible"]), default=None),
            cpu_s=time.process_time() - tic,
            native_charged=local.used,
            rows=paid,
        ))
        print(case, "enum", len(rows), "paid", len(paid), "false_neg", false_neg,
              "bestJ", report[-1]["best_j"], "cpu", round(report[-1]["cpu_s"], 3), flush=True)
    out = dict(kind="DIAGNOSTIC_NOT_FRESH", native_budget_cap=PAY_PER_MAP,
               native_charged_sum=sum(r["native_charged"] for r in report),
               scenario_calls=0, maps=report)
    path = HERE / "PROXY_FALSE_NEGATIVE.json"
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
