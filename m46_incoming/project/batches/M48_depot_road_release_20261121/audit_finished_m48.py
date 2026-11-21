"""Audit the finished 36 M48 actual jobs. Does not start a worker or a search.

Flag lists are compared in memory and are not written.
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

HERE = Path(__file__).resolve().parent
M47_BATCH = HERE.parent / "M47_bounded_actual_20261121"
CORE = HERE.parent / "M48_depot_road_release_core_20261121"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(M47_BATCH))
sys.path.insert(0, str(CORE))
os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
from private_root import k1_execution  # noqa: E402
from research import *  # noqa: E402
from bill import bill  # noqa: E402

CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
SEEDS = [1001, 1002]
DRIVER = "3ff50aa8a9bfc2aa61f8387c0e577bbce523aece3a4ebcc1dac4de27045c7dda"
CORE_HASH = "74ae8419889b98e735dd68fcf16407165b5980535acde3179e3d168a8f7e3d47"
REGISTRATION = "d7e3b9c0129e3564c057f39990d93c630560773372b5d401e798ffe635b5e422"
INIT_LIMITS = {100 + a * 1000 + b * 24 + c * 60 + d * 120 for a in (0, 1) for b in (0, 1) for c in (0, 1) for d in (0, 1)}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str) + "\n")


def require_finished():
    state = json.loads((HERE / "state.json").read_text())
    pid = state.get("controller_pid")
    alive = bool(pid) and Path(f"/proc/{pid}").exists()
    if alive or state.get("phase") != "M48_bounded_actual_complete_audit_pending" or state.get("actual_completed") != 36 or state.get("actual_failed") != 0:
        raise SystemExit(f"batch not finished cleanly: phase={state.get('phase')} completed={state.get('actual_completed')} failed={state.get('actual_failed')} alive={alive} pid={pid}")
    return state


def flight_chains(segments):
    by_drone = defaultdict(list)
    for segment in segments:
        for action in segment["actions"]:
            if action.get("kind") in ("L", "R") and action.get("drone"):
                by_drone[action["drone"]].append(action)
    chains = []
    unmatched = []
    for drone, seq in by_drone.items():
        seq.sort(key=lambda action: (action["start"], 0 if action["kind"] == "L" else 1))
        index = 0
        while index < len(seq):
            if seq[index]["kind"] != "L":
                unmatched.append(dict(drone=drone, kind=seq[index]["kind"], ref=seq[index].get("ref")))
                index += 1
                continue
            launch = seq[index]
            recover = None
            nxt = index + 1
            while nxt < len(seq) and seq[nxt]["kind"] != "R":
                if seq[nxt]["kind"] == "L":
                    break
                nxt += 1
            if nxt < len(seq) and seq[nxt]["kind"] == "R":
                recover = seq[nxt]
                index = nxt + 1
            else:
                unmatched.append(dict(drone=drone, kind="L", ref=launch.get("ref")))
                index += 1
                continue
            served = []
            for segment in segments:
                for stage in segment["stages"]:
                    if stage.get("kind") != "SERVICE" or not stage.get("parcel") or stage.get("drone") != drone:
                        continue
                    if launch["end"] - 1e-6 <= stage["start"] and stage["end"] <= recover["start"] + 1e-6:
                        served.append(stage)
            chains.append(dict(
                drone=drone, ref=launch.get("ref"),
                launch_truck=launch.get("truck"), recover_truck=recover.get("actor"),
                launch_truck_on_recovery=recover.get("launch_truck"),
                l0=launch["start"], l1=launch["end"], r0=recover["start"], r1=recover["end"],
                parcels=sorted({stage["parcel"] for stage in served}),
                customers=sorted({stage.get("customer") for stage in served if stage.get("customer")}),
                cross=launch.get("truck") != recover.get("actor"),
            ))
    return chains, unmatched


def service_metrics(segments, phys):
    air = {}
    full60 = remainder = 0
    for segment in segments:
        for stage in segment["stages"]:
            if stage.get("kind") != "SERVICE" or not stage.get("parcel"):
                continue
            air[stage["parcel"]] = stage.get("customer")
            if abs((stage["end"] - stage["start"]) - phys.air_service_s) <= 1e-4:
                full60 += 1
            else:
                remainder += 1
    ground = set()
    ground_bad = []
    u_bad = []
    u_actions = 0
    for segment in segments:
        for action in segment["actions"]:
            if action.get("kind") == "G":
                ground.add(action["ref"])
                if abs((action["end"] - action["start"]) - phys.ground_service_s) > 1e-4:
                    ground_bad.append(action["ref"])
            elif action.get("kind") == "U":
                u_actions += 1
                if abs((action["end"] - action["start"]) - phys.handover_s) > 1e-4:
                    u_bad.append(action.get("ref"))
    chains, unmatched = flight_chains(segments)
    served = {parcel for chain in chains for parcel in chain["parcels"]}
    cross = [chain for chain in chains if chain["cross"] and chain["parcels"]]
    cross_customers = {customer for chain in cross for customer in chain["customers"]}
    return dict(
        air=set(air), ground=ground, customers=air, ground_bad=ground_bad, u_bad=u_bad, u_actions=u_actions,
        service_full60=full60, service_remainder=remainder, chains=len(chains), unmatched=unmatched,
        unpaired_service=sorted(set(air) - served),
        launch_metadata_mismatch=[chain["ref"] for chain in chains if chain["launch_truck_on_recovery"] not in (None, chain["launch_truck"])],
        actual_unique_SERVICE_customers=len(set(air.values())),
        actual_cross_completed_SERVICE_customers=len(cross_customers),
        actual_cross_completed_SERVICE_flights=len(cross),
        actual_all_cross_recoveries=sum(chain["cross"] for chain in chains),
        truck_DRIVE_s=sum(action["end"] - action["start"] for segment in segments for action in segment["actions"] if action.get("kind") == "DRIVE"),
        recorded_truck_W_s=sum(action["end"] - action["start"] for segment in segments for action in segment["actions"] if action.get("kind") == "W"),
        drone_WAIT_s=sum(stage["end"] - stage["start"] for segment in segments for stage in segment["stages"] if stage.get("kind") == "WAIT"),
        SERVICE_parcels=sorted(air),
    )


def budget_split(ledger):
    init = main = 0
    limits = {}
    for entry in ledger["budgets"]:
        limit = entry["final_limit"]
        limits[limit] = limits.get(limit, 0) + 1
        if limit == 1000:
            main += entry["accepted_calls"]
        elif limit in INIT_LIMITS:
            init += entry["accepted_calls"]
        else:
            raise SystemExit(f"unexpected budget limit {limit}")
    return init, main, limits


def metrics_of(document, phys):
    metrics = service_metrics(document["segments"], phys)
    row = document["row"]
    return dict(
        paid=row["paid"], status=row["status"], emergency=bool(row["emergency"]),
        H=row["H"], seconds=row.get("seconds"), parts=row.get("parts") or {},
        actual_unique_SERVICE_customers=metrics["actual_unique_SERVICE_customers"],
        actual_cross_completed_SERVICE_customers=metrics["actual_cross_completed_SERVICE_customers"],
        actual_cross_completed_SERVICE_flights=metrics["actual_cross_completed_SERVICE_flights"],
        actual_all_cross_recoveries=metrics["actual_all_cross_recoveries"],
        truck_DRIVE_s=metrics["truck_DRIVE_s"], recorded_truck_W_s=metrics["recorded_truck_W_s"], drone_WAIT_s=metrics["drone_WAIT_s"],
        SERVICE_parcels=metrics["SERVICE_parcels"], u_actions=metrics["u_actions"],
        service_full60=metrics["service_full60"], service_remainder=metrics["service_remainder"],
        metrics=metrics,
    )


def historical_document(source, case, seed, arm):
    if source == "K1":
        path = k1_execution(case, seed, arm)
        alias = False
    elif source == "M47":
        path = M47_BATCH / "M47_CANDIDATE" / "executions" / "own" / "dev" / f"{case}_{seed}_{arm}.json"
        alias = False
    else:
        reg = json.loads((M47_BATCH / "FRESH_JOB_REGISTRATION.json").read_text())
        logical = ["M44_CURRENT", case, arm, "dev", seed, "own"]
        canon = next(item["canonical_fresh_job"] for item in reg["logical_mapping"] if item["logical_job"] == logical)
        variant = canon[0]
        path = M47_BATCH / variant / "executions" / "own" / "dev" / f"{case}_{seed}_{arm}.json"
        alias = variant != "M44_CURRENT"
    document = json.loads(Path(path).read_text())
    document.pop("flags", None)
    document["_reference_aliased_to_m47"] = alias
    return document


def boot(grouped_values):
    names = [case for case in CASES if grouped_values.get(case)]
    draw = random.Random(20261111)
    samples = []
    for _ in range(2000):
        means = []
        for case in names:
            values = grouped_values[case]
            means.append(sum(values[draw.randrange(len(values))] for _ in range(len(values))) / len(values))
        samples.append(sum(means) / len(names))
    samples.sort()
    return dict(mean=sum(sum(grouped_values[case]) / len(grouped_values[case]) for case in names) / len(names), ci95=[samples[50], samples[1950]])


def grouped(points, values):
    return {case: [value for (point, value) in zip(points, values) if point[0] == case] for case in CASES}


def main():
    state = require_finished()
    freeze = json.loads((HERE / "ACTUAL_EXECUTION_FREEZE.json").read_text())
    core = json.loads((CORE / "EXPERIMENT_CORE_FREEZE.json").read_text())
    if sha256(HERE / "fresh_actual.py") != DRIVER or freeze["fresh_actual.py"] != DRIVER:
        raise SystemExit("driver hash drifted")
    if sha256(HERE / "FRESH_JOB_REGISTRATION.json") != REGISTRATION:
        raise SystemExit("registration hash drifted")
    if sha256(CORE / "EXPERIMENT_CORE_FREEZE.json") != CORE_HASH or len(core) != 147:
        raise SystemExit("core freeze drifted")
    if any(sha256(CORE / name) != digest for name, digest in core.items()):
        raise SystemExit("a core member drifted")
    reg = json.loads((HERE / "FRESH_JOB_REGISTRATION.json").read_text())
    if len(reg["jobs"]) != 36:
        raise SystemExit("registration is not 36 jobs")
    failures = []
    rows = {}
    account = Counter()
    external = Counter()
    limits = Counter()
    journals = []
    redacted_root = Path("/tmp/m48_redacted_executions")
    if redacted_root.exists():
        for old in redacted_root.rglob("*"):
            if old.is_file():
                old.unlink()
    for job in reg["jobs"]:
        variant, case, arm, stream, seed, hmode = job
        path = HERE / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json"
        raw = json.loads(path.read_text())
        flags = raw.pop("flags")
        document = raw
        row = document["row"]
        inst, phys, alg = setup(case, "M48")
        phys.set_active()
        nominal = M47_BATCH / "M47_CANDIDATE" / "nominal" / ("X" if arm == "X" else "S") / case / "nominal_plan.json"
        if row["nominal_source_sha256"] != sha256(nominal) or row["H"] != alg._nominal_reference_H or row["loaded_driver_hash"] != DRIVER:
            failures.append(dict(job=job, check="nominal_H_or_driver"))
        if sha256(row["world_source"]) != row["world_source_sha256"]:
            failures.append(dict(job=job, check="world_hash"))
        historical = json.loads(k1_execution(case, seed, "S").read_text())
        same_world = flags == historical["flags"]
        del historical
        if not same_world:
            failures.append(dict(job=job, check="world_vs_K1_S"))
        del flags
        policy = row["policy"]
        soft = rr.verify_replay(inst, replace(phys, soft_h=True) if row["emergency"] else phys, document["segments"], row["H"], policy)
        strict = rr.verify_replay(inst, phys, document["segments"], row["H"], policy)
        invoice = bill(document["segments"], phys, row["H"])
        invoice_total = sum(invoice.values())
        metrics = service_metrics(document["segments"], phys)
        parcels = {customer.parcel_id for customer in inst.customers}
        if metrics["air"] | metrics["ground"] != parcels or metrics["air"] & metrics["ground"] or metrics["ground_bad"] or metrics["u_bad"]:
            failures.append(dict(job=job, check="inventory_or_duration"))
        if metrics["unpaired_service"] or metrics["unmatched"] or metrics["launch_metadata_mismatch"]:
            failures.append(dict(job=job, check="flight_chain", unpaired=len(metrics["unpaired_service"]), unmatched=len(metrics["unmatched"]), metadata=len(metrics["launch_metadata_mismatch"])))
        accepted = {item["parcel_id"] for item in document["observations"] if item["kind"] == "AIR_DELIVERY_ACCEPTED"}
        unavailable = {item["parcel_id"] for item in document["observations"] if item["kind"] == "DELIVERY_UNAVAILABLE"}
        if (accepted - metrics["ground"]) != metrics["air"] or not unavailable <= metrics["ground"]:
            failures.append(dict(job=job, check="observation_vs_stage"))
        custody = [item for item in soft.violations if "CUSTODY" in item or item.startswith("HOLDER") or item.startswith("U_")]
        if not soft.ok or soft.delivered != inst.n or custody or min(soft.min_energy.values(), default=1) < phys.e_min - 1e-7:
            failures.append(dict(job=job, check="replay_custody_energy", ok=soft.ok, delivered=soft.delivered, custody=len(custody), energy=min(soft.min_energy.values(), default=None)))
        if abs(soft.cost - row["paid"]) > 1e-7 or abs(invoice_total - row["paid"]) > 1e-7:
            failures.append(dict(job=job, check="invoice", replay=soft.cost, invoice=invoice_total, paid=row["paid"]))
        init, main, used_limits = budget_split(document["ledger"])
        for limit, count in used_limits.items():
            limits[limit] += count
        external_n = sum(document["ledger"]["unbudgeted_by_reason"].values())
        if init + main + external_n != document["ledger"]["accepted_calls"]:
            failures.append(dict(job=job, check="ledger_split"))
        startup = json.loads((HERE / variant / "startup_ledgers" / hmode / stream / f"{case}_{seed}_{arm}.json").read_text())
        journal_path = HERE / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl"
        journal = [json.loads(line) for line in journal_path.read_text().splitlines()]
        if startup["accepted_calls"] != 1 or sum(item["accepted"] for item in journal) != document["ledger"]["accepted_calls"] + 1:
            failures.append(dict(job=job, check="startup_or_journal"))
        journals.append(dict(file=journal_path.name, sha256=sha256(journal_path), lines=len(journal)))
        account.update(accepted=document["ledger"]["accepted_calls"], init=init, main=main, object_external=external_n, denied=document["ledger"]["denied_calls"], startup=1)
        external.update(document["ledger"]["unbudgeted_by_reason"])
        public = json.loads(path.read_text())
        public["flags"] = "REDACTED"
        dest = redacted_root / f"{case}_{seed}_{arm}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(public))
        rows[(case, arm, seed)] = dict(
            case=case, arm=arm, seed=seed, paid=row["paid"], parts=invoice, emergency=bool(row["emergency"]), strict_H=bool(strict.ok),
            actual_unique_SERVICE_customers=metrics["actual_unique_SERVICE_customers"],
            actual_cross_completed_SERVICE_customers=metrics["actual_cross_completed_SERVICE_customers"],
            actual_cross_completed_SERVICE_flights=metrics["actual_cross_completed_SERVICE_flights"],
            actual_all_cross_recoveries=metrics["actual_all_cross_recoveries"],
            chains=metrics["chains"], u_actions=metrics["u_actions"], service_full60=metrics["service_full60"], service_remainder=metrics["service_remainder"],
            min_energy=min(soft.min_energy.values(), default=None), seconds=row["seconds"], delivered=soft.delivered,
            accepted=document["ledger"]["accepted_calls"], init=init, main=main, external=external_n, denied=document["ledger"]["denied_calls"],
            truck_DRIVE_s=metrics["truck_DRIVE_s"], recorded_truck_W_s=metrics["recorded_truck_W_s"], drone_WAIT_s=metrics["drone_WAIT_s"],
            SERVICE_parcels=metrics["SERVICE_parcels"],
        )
    references = {}
    for source in ("M47", "M44", "K1"):
        for case in CASES:
            inst, phys, alg = setup(case, "M48")
            phys.set_active()
            for arm in "SRX":
                for seed in SEEDS:
                    document = historical_document(source, case, seed, arm)
                    view = metrics_of(document, phys)
                    view["stored_replay_ok"] = document["row"].get("valid")
                    view["reference_aliased_to_m47"] = bool(document.get("_reference_aliased_to_m47"))
                    view["metrics"] = None
                    references[(source, case, arm, seed)] = view
    names = ["paid", "actual_unique_SERVICE_customers", "actual_cross_completed_SERVICE_customers", "actual_cross_completed_SERVICE_flights", "actual_all_cross_recoveries"]
    points = [(case, seed) for case in CASES for seed in SEEDS]
    comparisons = []
    per_map = []
    for arm in "SRX":
        for source in ("M47", "M44", "K1"):
            deltas = {name: [rows[(case, arm, seed)][name] - references[(source, case, arm, seed)][name] for case, seed in points] for name in names}
            comparisons.append(dict(
                arm=arm, comparison=f"M48 minus {source}", n=len(points),
                metrics={name: dict(mean=statistics.mean(vals), paired=vals, equal_weight_bootstrap95=boot(grouped(points, vals))["ci95"]) for name, vals in deltas.items()},
                m48_emergencies=sum(rows[(case, arm, seed)]["emergency"] for case, seed in points),
                reference_emergencies=sum(references[(source, case, arm, seed)]["emergency"] for case, seed in points),
                m48_strict_H=sum(rows[(case, arm, seed)]["strict_H"] for case, seed in points),
                reference_stored_replay_ok=sum(bool(references[(source, case, arm, seed)].get("stored_replay_ok")) for case, seed in points),
                reference_cells_aliased_to_m47=sum(bool(references[(source, case, arm, seed)].get("reference_aliased_to_m47")) for case, seed in points),
            ))
        for case, seed in points:
            item = rows[(case, arm, seed)]
            per_map.append(dict(case=case, seed=seed, arm=arm, paid=item["paid"], parts=item["parts"], SERVICE=item["actual_unique_SERVICE_customers"], cross_customers=item["actual_cross_completed_SERVICE_customers"], cross_flights=item["actual_cross_completed_SERVICE_flights"], cross_recoveries=item["actual_all_cross_recoveries"], emergency=item["emergency"], strict_H=item["strict_H"], min_energy=item["min_energy"], accepted=item["accepted"]))
    sampled = {}
    sample_lines = 0
    first_sample = last_sample = None
    sample_path = HERE / "ACTUAL_PROCESS_SAMPLES.jsonl"
    for line in sample_path.read_text().splitlines():
        sample_lines += 1
        rec = json.loads(line)
        first_sample = rec["unix_s"] if first_sample is None else first_sample
        last_sample = rec["unix_s"]
        for item in rec.get("active") or []:
            proc = item.get("process") or {}
            if "cpu_s" in proc:
                sampled[proc["pid"]] = max(sampled.get(proc["pid"], 0.0), proc["cpu_s"])
    evidence_s = json.loads((HERE / "RETURN_GATE_EVIDENCE.json").read_text())
    evidence_x = json.loads((HERE / "RETURN_GATE_EVIDENCE_X.json").read_text())
    diagnostic = dict(
        calls=evidence_s["formal_evaluate_plan_calls"] + evidence_x["formal_evaluate_plan_calls"],
        C50_S_not_a_depot_witness=evidence_s["formal_evaluate_plan_calls"],
        C50_X_formal_gate=evidence_x["formal_evaluate_plan_calls"],
        not_included_in_the_36=True,
    )
    dump(HERE / "M48_ACTUAL_AUDIT.json", dict(
        failures=failures, rows=list(rows.values()), per_map=per_map, comparisons=comparisons,
        accounting=dict(counts=dict(account), external=dict(external), budget_objects=dict(limits), journals=len(journals), diagnostic_outside_the_36=diagnostic),
        cpu=dict(sampled_worker_cpu_s_lower_bound=sum(sampled.values()), sample_lines=sample_lines, sample_span_s=None if first_sample is None else last_sample - first_sample, episode_seconds=sum(item["seconds"] for item in rows.values())),
        identity=dict(controller_pid=state.get("controller_pid"), started_at=state.get("started_at"), driver=DRIVER, core=CORE_HASH, registration=REGISTRATION, jobs=36),
        chain_definition="Each drone's next L is paired with its next R before another L. SERVICE counts only for that drone between L end and R start. Cross means the launch truck differs from the recovery truck.",
        native_search_evaluations_in_this_audit=0,
    ))
    print("M48_AUDIT", "failures", len(failures), "jobs", len(rows), "accepted", account["accepted"], "startup", account["startup"])


if __name__ == "__main__":
    main()
