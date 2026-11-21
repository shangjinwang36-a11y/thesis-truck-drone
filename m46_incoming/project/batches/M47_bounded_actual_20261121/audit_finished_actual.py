"""Independent audit of the finished M47 actual batch.

Reads the 40 canonical executions and the 36 historical K1 rows. Replay and
invoice checks do not start a search. Flag lists stay in memory only long
enough to compare identity; they are not written.
"""
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time

H = Path(__file__).resolve().parent
B = H.parent
C = B / "M47_schedule_closed_exchange_core_20261121"
sys.path.insert(0, str(H))
sys.path.insert(0, str(C))
from private_root import k1_execution  # noqa: E402
from research import *  # noqa: E402
from bill import bill  # noqa: E402
from tdr.complete_joint import version  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
SEEDS = [1001, 1002]
VARIANTS = ["M47_CANDIDATE", "M44_CURRENT"]
AUDITED_DRIVER = "2547a985e75f32ef5ec239db0abceb7a72dfb565d8b15243119f24507f033561"
AUDITED_CORE = "a509cc36961296e24dec23d212dddbc2dcc07bc08ec16618549ce726897e8f48"
AUDITED_REGISTRATION = "71d8fb2ed2673d135c742c5c3f1256023196c6ed44a199250b725ed3b7a7669a"
AUDITED_CONTROLLER = "5267ff30be3a12d7d64eaaf5b00e258834d43c2b3de9aab7ef1b5ffc7e30b732"
INIT_LIMITS = {100 + a * 1000 + b * 24 + c * 60 + d * 120 for a in (0, 1) for b in (0, 1) for c in (0, 1) for d in (0, 1)}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_finished():
    state = json.loads((H / "state.json").read_text())
    pid = state.get("controller_pid")
    alive = bool(pid) and Path(f"/proc/{pid}").exists()
    if alive or state.get("phase") != "M47_bounded_actual_complete_audit_pending" or state.get("actual_completed") != 40 or state.get("actual_failed") != 0:
        raise SystemExit(f"batch not finished cleanly: phase={state.get('phase')} completed={state.get('actual_completed')} failed={state.get('actual_failed')} alive={alive} pid={pid}")
    return state


def durations(segments, kind, source):
    total = defaultdict(float)
    for seg in segments:
        rows = seg["stages"] if source == "stage" else seg["actions"]
        for row in rows:
            if row.get("kind") != kind:
                continue
            key = row.get("parcel") or row.get("ref")
            total[key] += row["end"] - row["start"]
    return total


def flights_of(segments):
    found = {}
    for seg in segments:
        for action in seg["actions"]:
            if action.get("kind") not in ("L", "R"):
                continue
            slot = found.setdefault(action["ref"], dict(ref=action["ref"], drone=action.get("drone")))
            if action["kind"] == "L":
                slot["launch"] = action.get("truck")
                slot["l0"] = min(slot.get("l0", action["start"]), action["start"])
                slot["l1"] = max(slot.get("l1", action["end"]), action["end"])
            else:
                slot["recover"] = action.get("actor")
                slot["launch_named"] = action.get("launch_truck")
                slot["r0"] = min(slot.get("r0", action["start"]), action["start"])
                slot["r1"] = max(slot.get("r1", action["end"]), action["end"])
    return found


def service_metrics(segments, inst, phys):
    """Completed air SERVICE is a stage that still carries a parcel.

    The frozen simulator rewrites a service clipped by a segment boundary into
    WAIT and records the delivery only on the completion stage. That stage can
    be the remaining portion of the 60 s service, so its duration is not a
    second copy of air_service_s. Each U action is checked on its own.
    """
    air = set()
    customers = {}
    full60 = remainder = 0
    for seg in segments:
        for stage in seg["stages"]:
            if stage.get("kind") != "SERVICE" or not stage.get("parcel"):
                continue
            air.add(stage["parcel"])
            customers[stage["parcel"]] = stage.get("customer")
            if abs((stage["end"] - stage["start"]) - phys.air_service_s) <= 1e-4:
                full60 += 1
            else:
                remainder += 1
    ground = set()
    ground_bad = []
    u_bad = []
    u_actions = 0
    for seg in segments:
        for action in seg["actions"]:
            if action.get("kind") == "G":
                ground.add(action["ref"])
                if abs((action["end"] - action["start"]) - phys.ground_service_s) > 1e-4:
                    ground_bad.append(action["ref"])
            elif action.get("kind") == "U":
                u_actions += 1
                if abs((action["end"] - action["start"]) - phys.handover_s) > 1e-4:
                    u_bad.append(action.get("ref"))
    flights = flights_of(segments)
    cross_refs = [ref for ref, slot in flights.items() if slot.get("launch") and slot.get("recover") and (slot.get("launch_named") or slot.get("launch")) != slot.get("recover")]
    cross_parcels = set()
    flights_with_service = set()
    for seg in segments:
        for stage in seg["stages"]:
            if stage.get("kind") != "SERVICE" or stage.get("parcel") not in air:
                continue
            for ref in cross_refs:
                slot = flights[ref]
                if slot.get("drone") == stage.get("drone") and slot.get("l0", 0) - 1e-6 <= stage["start"] <= slot.get("r1", 0) + 1e-6:
                    cross_parcels.add(stage["parcel"])
                    flights_with_service.add(ref)
    drive = sum(a["end"] - a["start"] for seg in segments for a in seg["actions"] if a.get("kind") == "DRIVE")
    truck_w = sum(a["end"] - a["start"] for seg in segments for a in seg["actions"] if a.get("kind") == "W")
    drone_wait = sum(s["end"] - s["start"] for seg in segments for s in seg["stages"] if s.get("kind") == "WAIT")
    return dict(
        air=air, ground=ground, ground_bad=ground_bad, u_bad=u_bad, u_actions=u_actions,
        service_full60=full60, service_remainder=remainder, customers=customers,
        cross_parcels=cross_parcels, cross_refs=cross_refs,
        actual_unique_SERVICE_customers=len({customers[p] for p in air}),
        actual_cross_completed_SERVICE_customers=len({customers[p] for p in cross_parcels}),
        actual_cross_completed_SERVICE_flights=len(flights_with_service),
        actual_all_cross_recoveries=len(cross_refs),
        truck_DRIVE_s=drive, recorded_truck_W_s=truck_w, drone_WAIT_s=drone_wait,
        SERVICE_parcels=sorted(air),
    )


def trace(document):
    copied = json.loads(json.dumps(document["segments"]))
    for seg in copied:
        seg.get("start", {}).pop("truck_done", None)
    return copied


def budget_split(ledger, histogram):
    init = main = 0
    for entry in ledger["budgets"]:
        limit = entry["final_limit"]
        histogram[limit] += 1
        if limit == 1000:
            main += entry["accepted_calls"]
        elif limit in INIT_LIMITS:
            init += entry["accepted_calls"]
        else:
            raise SystemExit(f"unexpected budget limit {limit}")
    return init, main


def replay_one(inst, phys, document, paid, h_value, policy):
    soft = rr.verify_replay(inst, replace(phys, soft_h=True) if document["row"]["emergency"] else phys, document["segments"], h_value, policy)
    strict = rr.verify_replay(inst, phys, document["segments"], h_value, policy)
    invoice = sum(bill(document["segments"], phys, h_value).values())
    return soft, strict, invoice


def main():
    state = require_finished()
    freeze = json.loads((H / "ACTUAL_EXECUTION_FREEZE.json").read_text())
    core = json.loads((C / "EXPERIMENT_CORE_FREEZE.json").read_text())
    if sha256(H / "fresh_actual.py") != AUDITED_DRIVER or freeze["fresh_actual.py"] != AUDITED_DRIVER:
        raise SystemExit("driver hash drifted")
    if sha256(H / "FRESH_JOB_REGISTRATION.json") != AUDITED_REGISTRATION:
        raise SystemExit("registration hash drifted")
    if sha256(H / "run_actual.py") != AUDITED_CONTROLLER or freeze["run_actual.py"] != AUDITED_CONTROLLER:
        raise SystemExit("controller hash drifted")
    if sha256(C / "EXPERIMENT_CORE_FREEZE.json") != AUDITED_CORE or len(core) != 147:
        raise SystemExit("core freeze drifted")
    if any(sha256(C / name) != digest for name, digest in core.items()):
        raise SystemExit("a core member drifted")
    reg = json.loads((H / "FRESH_JOB_REGISTRATION.json").read_text())
    if reg["logical_count"] != 72 or reg["unique_fresh_jobs"] != 40 or len(reg["jobs"]) != 40:
        raise SystemExit("registration shape drifted")
    rows = {}
    physical = []
    strong = []
    account = Counter()
    external = Counter()
    limits = Counter()
    failures = []
    journals = []
    for job in reg["jobs"]:
        variant, case, arm, stream, seed, hmode = job
        path = H / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json"
        document = json.loads(path.read_text())
        flags = document.pop("flags")
        row = document["row"]
        inst, phys, alg = setup(case, variant)
        phys.set_active()
        nominal = H / variant / "nominal" / ("X" if arm == "X" else "S") / case / "nominal_plan.json"
        plan = plan_from_dict(json.loads(nominal.read_text())["plan"])
        if row["input_plan_version"] != version(plan) or row["nominal_source_sha256"] != sha256(nominal):
            failures.append(dict(job=job, check="nominal_identity"))
        if row["H"] != alg._nominal_reference_H or row["loaded_driver_hash"] != AUDITED_DRIVER:
            failures.append(dict(job=job, check="H_or_driver"))
        if sha256(row["world_source"]) != row["world_source_sha256"]:
            failures.append(dict(job=job, check="world_hash"))
        historical = json.loads(k1_execution(case, seed, arm).read_text())
        if flags != historical["flags"] or row["H"] != historical["row"]["H"]:
            failures.append(dict(job=job, check="world_or_H_vs_K1"))
        del historical
        soft, strict, invoice = replay_one(inst, phys, document, row["paid"], row["H"], row["policy"])
        metrics = service_metrics(document["segments"], inst, phys)
        parcels = {customer.parcel_id for customer in inst.customers}
        if metrics["air"] | metrics["ground"] != parcels or metrics["air"] & metrics["ground"] or metrics["ground_bad"] or metrics["u_bad"]:
            failures.append(dict(job=job, check="inventory_or_duration", air=len(metrics["air"]), ground=len(metrics["ground"]), ground_bad=len(metrics["ground_bad"]), u_bad=len(metrics["u_bad"])))
        accepted = {item["parcel_id"] for item in document["observations"] if item["kind"] == "AIR_DELIVERY_ACCEPTED"}
        unavailable = {item["parcel_id"] for item in document["observations"] if item["kind"] == "DELIVERY_UNAVAILABLE"}
        intermediate = accepted & metrics["ground"]
        if (accepted - metrics["ground"]) != metrics["air"] or not unavailable <= metrics["ground"]:
            failures.append(dict(job=job, check="observation_vs_stage", accepted=len(accepted), air=len(metrics["air"]), unavailable=len(unavailable), ground=len(metrics["ground"]), intermediate_then_ground=len(intermediate)))
        if any(item["air_delivery_available"] != (item["parcel_id"] not in flags) for item in document["observations"]):
            failures.append(dict(job=job, check="observation_visibility"))
        custody = [item for item in soft.violations if "CUSTODY" in item or item.startswith("HOLDER") or item.startswith("U_")]
        if not soft.ok or soft.delivered != inst.n or custody or min(soft.min_energy.values(), default=1) < phys.e_min - 1e-7:
            failures.append(dict(job=job, check="replay_custody_energy", ok=soft.ok, delivered=soft.delivered, custody=len(custody), min_energy=min(soft.min_energy.values(), default=None)))
        if abs(soft.cost - row["paid"]) > 1e-7 or abs(invoice - row["paid"]) > 1e-7:
            failures.append(dict(job=job, check="invoice", replay=soft.cost, invoice=invoice, paid=row["paid"]))
        init, main = budget_split(document["ledger"], limits)
        external_n = sum(document["ledger"]["unbudgeted_by_reason"].values())
        if init + main + external_n != document["ledger"]["accepted_calls"]:
            failures.append(dict(job=job, check="ledger_split"))
        if any(entry["used"] != entry["accepted_calls"] or entry["accepted_calls"] > entry["final_limit"] for entry in document["ledger"]["budgets"]):
            failures.append(dict(job=job, check="budget_cap"))
        startup = json.loads((H / variant / "startup_ledgers" / hmode / stream / f"{case}_{seed}_{arm}.json").read_text())
        journal_path = H / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl"
        journal = [json.loads(line) for line in journal_path.read_text().splitlines()]
        if startup["accepted_calls"] != 1 or sum(item["accepted"] for item in journal) != document["ledger"]["accepted_calls"] + 1:
            failures.append(dict(job=job, check="startup_or_journal"))
        journals.append(dict(file=journal_path.name, sha256=sha256(journal_path), lines=len(journal), bytes=journal_path.stat().st_size))
        account.update(accepted=document["ledger"]["accepted_calls"], init=init, main=main, object_external=external_n, denied=document["ledger"]["denied_calls"], startup=1)
        external.update(document["ledger"]["unbudgeted_by_reason"])
        out = dict(
            paid=row["paid"], status=row["status"], emergency=bool(row["emergency"]), strict_H=bool(strict.ok),
            actual_unique_SERVICE_customers=metrics["actual_unique_SERVICE_customers"],
            actual_cross_completed_SERVICE_customers=metrics["actual_cross_completed_SERVICE_customers"],
            actual_cross_completed_SERVICE_flights=metrics["actual_cross_completed_SERVICE_flights"],
            actual_all_cross_recoveries=metrics["actual_all_cross_recoveries"],
            truck_km=row["parts"]["distance"] / phys.c_km, driver_s=row["parts"]["driver"] / phys.wage_per_s,
            recorded_truck_W_s=metrics["recorded_truck_W_s"], drone_WAIT_s=metrics["drone_WAIT_s"], truck_DRIVE_s=metrics["truck_DRIVE_s"],
            parts=row["parts"], H=row["H"], seconds=row["seconds"], delivered=soft.delivered,
            min_energy=min(soft.min_energy.values(), default=None), accepted=document["ledger"]["accepted_calls"],
            init=init, main=main, external=external_n, denied=document["ledger"]["denied_calls"],
            SERVICE_parcels=metrics["SERVICE_parcels"], case=case, arm=arm, seed=seed, variant=variant,
            replay_distance_km=soft.distance_km, replay_driver_s=soft.driver_s,
            air_service_s=phys.air_service_s, handover_s=phys.handover_s, ground_service_s=phys.ground_service_s,
            service_full60=metrics["service_full60"], service_remainder=metrics["service_remainder"], u_actions=metrics["u_actions"],
            intermediate_air_observation_then_ground=len(accepted & metrics["ground"]),
        )
        rows[tuple(job)] = out
        physical.append(dict(job=job, ok=soft.ok, strict_H=strict.ok, emergency=bool(row["emergency"]), delivered=soft.delivered, min_energy=out["min_energy"], u_bad=len(metrics["u_bad"]), custody=len(custody)))
        if arm == "S":
            old = json.loads(k1_execution(case, seed, arm).read_text())
            old.pop("flags", None)
            old_metrics = service_metrics(old["segments"], inst, phys)
            same = trace(document) == trace(old) and document["observations"] == old["observations"] and document["ledger"] == old["ledger"] and abs(row["paid"] - old["row"]["paid"]) < 1e-7
            strong.append(dict(job=job, label="strong_original_K1_S", exact_trace_ledger_invoice=same, delta_paid=row["paid"] - old["row"]["paid"], delta_SERVICE=out["actual_unique_SERVICE_customers"] - old_metrics["actual_unique_SERVICE_customers"], old_emergency=bool(old["row"]["emergency"]), new_emergency=bool(row["emergency"])))
        del flags
    logical = []
    for item in reg["logical_mapping"]:
        logical.append(dict(logical_job=item["logical_job"], canonical_job=item["canonical_fresh_job"], metrics=rows[tuple(item["canonical_fresh_job"])]))
    historical_rows = []
    for case in CASES:
        inst, phys, alg = setup(case, "M47_CANDIDATE")
        phys.set_active()
        for arm in "SRX":
            for seed in SEEDS:
                document = json.loads(k1_execution(case, seed, arm).read_text())
                document.pop("flags", None)
                row = document["row"]
                policy = row.get("policy", "S" if arm == "S" else "X")
                soft, strict, invoice = replay_one(inst, phys, document, row["paid"], alg._nominal_reference_H, policy)
                metrics = service_metrics(document["segments"], inst, phys)
                if row["H"] != alg._nominal_reference_H or not soft.ok or abs(invoice - row["paid"]) > 1e-7 or abs(soft.cost - row["paid"]) > 1e-7:
                    failures.append(dict(case=case, arm=arm, seed=seed, check="historical_K1"))
                historical_rows.append(dict(
                    case=case, arm=arm, seed=seed, paid=row["paid"], emergency=bool(row["emergency"]), strict_H=bool(strict.ok), H=row["H"],
                    actual_unique_SERVICE_customers=metrics["actual_unique_SERVICE_customers"],
                    actual_cross_completed_SERVICE_customers=metrics["actual_cross_completed_SERVICE_customers"],
                    actual_cross_completed_SERVICE_flights=metrics["actual_cross_completed_SERVICE_flights"],
                    actual_all_cross_recoveries=metrics["actual_all_cross_recoveries"],
                    truck_km=soft.distance_km, driver_s=soft.driver_s, recorded_truck_W_s=metrics["recorded_truck_W_s"],
                    drone_WAIT_s=metrics["drone_WAIT_s"], truck_DRIVE_s=metrics["truck_DRIVE_s"], parts=row["parts"],
                    historical_not_fresh=True, delivered=soft.delivered, min_energy=min(soft.min_energy.values(), default=None),
                    SERVICE_parcels=metrics["SERVICE_parcels"],
                ))
    sampled = Counter()
    sample_lines = 0
    sample_path = H / "ACTUAL_PROCESS_SAMPLES.jsonl"
    if sample_path.is_file():
        for line in sample_path.read_text().splitlines():
            sample_lines += 1
            rec = json.loads(line)
            for item in rec.get("active") or []:
                proc = item.get("process") or {}
                if "cpu_s" in proc:
                    sampled[proc["pid"]] = max(sampled[proc["pid"]], proc["cpu_s"])
    identity = dict(
        driver_sha256=AUDITED_DRIVER, controller_sha256=AUDITED_CONTROLLER, registration_sha256=AUDITED_REGISTRATION,
        core_freeze_sha256=AUDITED_CORE, core_members=147, execution_freeze_members=len(freeze),
        controller_tests="test_run_actual_controller.py five zero-worker tests", python=sys.version,
        controller_pid=state.get("controller_pid"), started_at=state.get("started_at"),
        native_search_evaluations_in_this_audit=0,
    )
    dump(H / "ACTUAL_INDEPENDENT_AUDIT.json", dict(
        unique_rows=list(rows.values()), logical_rows=logical, historical_K1_rows=historical_rows,
        S_and_same_input_references=strong, physical_checks=physical, failures=failures,
        unique_actual_jobs=len(rows), logical_jobs=len(logical), historical_rows=len(historical_rows),
        unique_delivered=sum(item["delivered"] for item in rows.values()),
        unique_strict_H=sum(item["strict_H"] for item in rows.values()),
        unique_emergencies=sum(item["emergency"] for item in rows.values()),
        metric_definitions=dict(
            SERVICE="A SERVICE stage that still names a parcel is a completed air delivery. The frozen simulator rewrites a segment-clipped service to WAIT and keeps the delivery on the completion stage, whose duration may be the remaining portion of air_service_s.",
            U="Every recorded U action has duration phys.handover_s. That is the abnormal handover, separate from the 60 s air SERVICE stage.",
            cross="Recovery truck differs from launch truck on the same sortie ref. A cross flight counts when one of its completed SERVICE stages falls between its launch and recovery.",
            service_metrics_module="not present in this checkout; counts are taken from the executed segments and observations",
        ),
        identity=identity, all_new_canonical_fresh=True, historical_K1_independent_invoice_replay=True,
    ))
    dump(H / "ACTUAL_ACCOUNTING.json", dict(
        counts=dict(account), external_subset_not_added=dict(external),
        init_budget_final_limits={str(k): v for k, v in limits.items()},
        init_limit_note="1000 is the separate main ALNS budget. Other limits are the init budget 100 plus the frozen recovery extensions: one rescue of 1000, fallback 24, joint 60, and land 120.",
        logical_rows_are_not_independent_calls=True, unique_actual_all_fresh=True,
        diagnostic_audit_native_evaluations=0, historical_K1_replayed_native_evaluations=0,
        episode_wall_s=sum(item["seconds"] for item in rows.values()),
        sampled_worker_cpu_s_lower_bound=sum(sampled.values()), process_sample_lines=sample_lines,
        cpu_note="Samples keep the highest cpu_s seen while a worker pid was still alive. CPU after the last sample of a pid is not reconstructed.",
        controller_started_at=state.get("started_at"), no_unknown_imputation=True,
    ))
    dump(H / "CALL_JOURNAL_MANIFEST.json", dict(journals=journals, files=len(journals)))
    summary = build_summary(rows, logical, historical_rows, strong, failures)
    dump(H / "COMPREHENSIVE_ACTUAL_SUMMARY.json", summary)
    dump(H / "ACTUAL_DECISION.json", dict(decision=summary["decision"], reasons=summary["decision_reasons"], failures=len(failures), unique_actual_jobs=40, logical_jobs=72, historical_K1=36, identity=identity))
    print("AUDIT", summary["decision"], "failures", len(failures), "strict", sum(item["strict_H"] for item in rows.values()), "emergency", sum(item["emergency"] for item in rows.values()))


def handover_count(segments):
    return [1 for seg in segments for action in seg["actions"] if action.get("kind") == "U"]


def nominal_costs():
    out = {}
    for case in CASES:
        fresh = json.loads((B / "M47_schedule_closed_exchange_20261121/fresh_new" / case / "S/result.json").read_text())["cost"]
        current = json.loads((B / "M44_paid_temporal_body_skeleton_20261121/fresh_new" / case / "S/result.json").read_text())["cost"]
        k1 = json.loads((B / "K1_R10_S_warm_restore_20261120/K1/nominal/S" / case / "cost.json").read_text())["cost"]
        if abs(fresh - current) > 1e-9 or abs(fresh - k1) > 1e-9:
            raise SystemExit(f"S nominal denominators differ on {case}")
        out[case] = fresh
    return out


def boot(ds):
    names = [case for case in CASES if ds.get(case)]
    draw = random.Random(20261111)
    samples = []
    for _ in range(2000):
        means = []
        for case in names:
            vals = ds[case]
            means.append(sum(vals[draw.randrange(len(vals))] for _ in range(len(vals))) / len(vals))
        samples.append(sum(means) / len(names))
    samples.sort()
    return dict(mean=sum(sum(ds[case]) / len(ds[case]) for case in names) / len(names), ci95=[samples[50], samples[1950]])


def grouped(points, vals):
    return {case: [value for (point, value) in zip(points, vals) if point[0] == case] for case in CASES}


def ci(points, vals):
    return boot(grouped(points, vals))["ci95"]


def pctboot(points, ds):
    z = boot({case: [-x / 100 for x in values] for case, values in ds.items()})
    return dict(mean=-100 * z["mean"], ci95=[-100 * x for x in reversed(z["ci95"])])


def stats(vals):
    ordered = sorted(vals)
    return dict(mean=statistics.mean(vals), minimum=min(vals), maximum=max(vals), p90=ordered[max(0, math.ceil(.90 * len(vals)) - 1)], p95=ordered[max(0, math.ceil(.95 * len(vals)) - 1)], n=len(vals), tail_is_small_sample_descriptive=True)


def build_summary(rows, logical, historical_rows, strong, failures):
    metrics = ["paid", "actual_unique_SERVICE_customers", "actual_cross_completed_SERVICE_customers", "actual_cross_completed_SERVICE_flights", "actual_all_cross_recoveries", "truck_km", "driver_s", "recorded_truck_W_s", "drone_WAIT_s", "truck_DRIVE_s"]
    lookup = {tuple(item["logical_job"]): item["metrics"] for item in logical}
    old = {(item["case"], item["arm"], item["seed"]): item for item in historical_rows}
    denominators = nominal_costs()

    def get(variant, case, arm, seed):
        if variant == "K1":
            return old[case, arm, seed]
        return lookup[variant, case, arm, "dev", seed, "own"]

    groups = []
    policies = []
    changes = []
    for scope in CASES + ["ALL_EQUAL_WEIGHT"]:
        chosen = CASES if scope == "ALL_EQUAL_WEIGHT" else [scope]
        points = [(case, seed) for case in chosen for seed in SEEDS]
        for variant in ["K1"] + VARIANTS:
            for arm in "SRX":
                selected = [get(variant, case, arm, seed) for case, seed in points]
                groups.append(dict(scope=scope, variant=variant, arm=arm, metrics={name: stats([item[name] for item in selected]) for name in metrics}, emergencies=sum(item["emergency"] for item in selected), strict_H=sum(item["strict_H"] for item in selected), parts={name: statistics.mean(item["parts"].get(name, 0.0) for item in selected) for name in ["driver", "distance", "electricity", "overtime"]}, n=len(selected)))
            for source, target in [("R", "X"), ("S", "X"), ("S", "R")]:
                deltas = {name: [get(variant, case, target, seed)[name] - get(variant, case, source, seed)[name] for case, seed in points] for name in metrics}
                saving = -statistics.mean(deltas["paid"])
                policies.append(dict(
                    scope=scope, variant=variant, comparison=source + "->" + target, delta_is_target_minus_source=True,
                    metrics={name: dict(mean=statistics.mean(vals), paired_differences=vals, original_bootstrap95=ci(points, vals)) for name, vals in deltas.items()},
                    cost_saving=saving, current_S_nominal_denominators={case: denominators[case] for case in chosen},
                    historical_fixed_S_nominal_denominators={case: denominators[case] for case in chosen},
                    strong_K1_S_nominal_denominators={case: denominators[case] for case in chosen},
                    denominator_note="Fresh M47 S, fresh M44 S, and K1 nominal/S cost.json match on all six maps. HISTORICAL_SOURCE_RESULT_MATCH.json is not in this checkout.",
                    original_saved_yuan=boot(grouped(points, [-x for x in deltas["paid"]])),
                    original_percent_current_S=pctboot(points, grouped(points, [-100 * x / denominators[case] for (case, _), x in zip(points, deltas["paid"])])),
                    original_percent_fixed_historical_S=pctboot(points, grouped(points, [-100 * x / denominators[case] for (case, _), x in zip(points, deltas["paid"])])),
                    n=len(points),
                ))
        for arm in "SRX":
            for ref in ["M44_CURRENT", "K1"]:
                deltas = {name: [get("M47_CANDIDATE", case, arm, seed)[name] - get(ref, case, arm, seed)[name] for case, seed in points] for name in metrics}
                changes.append(dict(scope=scope, arm=arm, comparison="M47_CANDIDATE minus " + ref, original_saved_yuan_reference_minus_new=boot(grouped(points, [-x for x in deltas["paid"]])), metrics={name: dict(mean=statistics.mean(vals), paired_differences=vals, original_bootstrap95=ci(points, vals)) for name, vals in deltas.items()}, n=len(points)))
    s_reg = [item for item in strong if item["delta_paid"] > 1e-7 or item["delta_SERVICE"] < 0 or (item["new_emergency"] and not item["old_emergency"])]

    def overall(variant, arm):
        return next(item for item in groups if (item["scope"], item["variant"], item["arm"]) == ("ALL_EQUAL_WEIGHT", variant, arm))

    ns = overall("M47_CANDIDATE", "S")
    nx = overall("M47_CANDIDATE", "X")
    ks = overall("K1", "S")
    rx = next(item for item in policies if item["scope"] == "ALL_EQUAL_WEIGHT" and item["variant"] == "M47_CANDIDATE" and item["comparison"] == "R->X")
    sx = next(item for item in policies if item["scope"] == "ALL_EQUAL_WEIGHT" and item["variant"] == "M47_CANDIDATE" and item["comparison"] == "S->X")
    against_k1 = next(item for item in changes if item["scope"] == "ALL_EQUAL_WEIGHT" and item["arm"] == "X" and item["comparison"] == "M47_CANDIDATE minus K1")
    against_current = next(item for item in changes if item["scope"] == "ALL_EQUAL_WEIGHT" and item["arm"] == "X" and item["comparison"] == "M47_CANDIDATE minus M44_CURRENT")
    s_fee = next(item for item in changes if item["scope"] == "ALL_EQUAL_WEIGHT" and item["arm"] == "S" and item["comparison"] == "M47_CANDIDATE minus K1")
    reasons = []
    if failures:
        reasons.append("physical, custody, inventory, energy, duration, invoice, or identity check failed")
    if against_k1["original_saved_yuan_reference_minus_new"]["mean"] <= 0:
        reasons.append("full X mean paid fails improvement over strong K1")
    if against_k1["original_saved_yuan_reference_minus_new"]["ci95"][0] <= 0:
        reasons.append("full X paid gain over strong K1 lacks positive fixed95 lower bound")
    if nx["metrics"]["actual_unique_SERVICE_customers"]["mean"] < max(ns["metrics"]["actual_unique_SERVICE_customers"]["mean"], ks["metrics"]["actual_unique_SERVICE_customers"]["mean"]):
        reasons.append("actual X SERVICE coverage remains below current and/or original strong S")
    if s_fee["metrics"]["paid"]["mean"] > 0:
        reasons.append("shared S mean paid regresses against strong K1; no rollback used")
    if s_fee["metrics"]["actual_unique_SERVICE_customers"]["mean"] < 0:
        reasons.append("shared S actual SERVICE decreases against strong K1; no rollback used")
    if ns["emergencies"] > ks["emergencies"]:
        reasons.append("shared S emergency/softH count increases against K1")
    per_map = []
    for case in CASES:
        for seed in SEEDS:
            for variant in VARIANTS:
                for arm in "SRX":
                    item = get(variant, case, arm, seed)
                    per_map.append(dict(case=case, seed=seed, variant=variant, arm=arm, paid=item["paid"], SERVICE_customers=item["actual_unique_SERVICE_customers"], cross_customers=item["actual_cross_completed_SERVICE_customers"], cross_flights=item["actual_cross_completed_SERVICE_flights"], all_cross_recoveries=item["actual_all_cross_recoveries"], emergency=item["emergency"], strict_H=item["strict_H"]))
    return dict(
        groups=groups, policy_comparisons=policies, new_vs_references=changes, per_map=per_map,
        strong_S_individual_regressions=s_reg, all_strong_S_comparisons_exact=all(item["exact_trace_ledger_invoice"] for item in strong),
        unique_actual_jobs=40, logical_rows=72, unique_strict_H=sum(item["strict_H"] for item in rows.values()),
        unique_emergencies=sum(item["emergency"] for item in rows.values()), equal_weight_graphs=True,
        worlds_are_development_not_blind=True,
        CI_method="Exact original stratified paired bootstrap CASES order C50,R50,RC50,C100,R100,RC100; seed20261111,2000 draws, indices50/1950; original pctboot sign/reversal and per-map nominal-S denominators",
        decision="AUDIT_BLOCKED" if failures else ("DROP" if reasons else "DEVELOPMENT_EVIDENCE_REQUIRES_ORIGINAL_GATE_REVIEW"),
        decision_reasons=reasons,
        gate_source="Same complete-development mean/CI/coverage/strong-S/emergency rules as the M41 summarize_actual transcription of M25 audit_development.py:147-155; no release/confirmation",
        summary=dict(R_to_X=rx, S_to_X=sx, X_vs_K1=against_k1, X_vs_current=against_current),
        no_confirmation=True, failures=failures,
    )


if __name__ == "__main__":
    main()
