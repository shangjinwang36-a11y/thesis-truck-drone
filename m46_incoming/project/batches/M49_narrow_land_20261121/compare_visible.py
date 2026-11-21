"""Semantic comparison of the two saved first-recovery contexts. No evaluation."""
from pathlib import Path
import hashlib
import json
import os
import pickle
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
M48 = HERE.parent / "M48_depot_road_release_20261121/M48_RECOVERY/observer/formal/own/dev"
M49 = HERE.parent / "M49_reorder_fair_20261121/M49_REORDER/observer/formal/own/dev"
JOBS = ("RC100_1002_X", "R100_1002_S")


def _bind():
    os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    for entry in (
        CORE / "source/proj_r6/src",
        CORE / "source/round10_recheck",
        CORE,
        HERE.parent / "M47_bounded_actual_20261121",
    ):
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def load_context(path):
    _bind()
    with open(path, "rb") as handle:
        return pickle.load(handle)


def plan_view(plan):
    sorties = {}
    for sid, sortie in plan.sorties.items():
        sorties[str(sid)] = dict(
            drone=sortie.drone, truck=sortie.truck, launch_truck=sortie.launch_truck,
            launch_vid=sortie.launch_vid, rec_vid=sortie.rec_vid, started=bool(sortie.started),
            landed=bool(sortie.landed), mode=sortie.mode,
            air_sha256=digest(sorted(sortie.air)), handover_sha256=digest(sorted(sortie.handover)),
        )
    visits = {
        str(visit.vid): dict(truck=visit.truck, customer=visit.customer, ground_sha256=digest(sorted(visit.ground)))
        for visit in plan.visits.values()
    }
    return dict(
        routes={truck: list(route) for truck, route in plan.routes.items()},
        sorties=sorties, visits=visits,
        n_landed=sum(bool(s.landed) for s in plan.sorties.values()),
        n_started=sum(bool(s.started) for s in plan.sorties.values()),
    )


def state_view(state):
    drone_start = {}
    for drone, start in state.drone_start.items():
        drone_start[drone] = dict(
            kind=start.kind, truck=start.truck, ready_time=start.ready_time, pos=start.pos,
            energy=start.energy, n_aboard=len(start.aboard),
            service_done_s=start.service_done_s, has_service_parcel=start.service_parcel is not None,
        )
    holders = {"DEPOT": 0, "TRUCK": 0, "DRONE": 0, "OTHER": 0}
    for value in state.parcel_holder.values():
        text = str(value)
        key = text.split(":", 1)[0]
        holders[key if key in holders else "OTHER"] += 1
    return dict(
        t0=state.t0,
        truck_pos={key: list(value) for key, value in state.truck_start_pos.items()},
        truck_time=dict(state.truck_start_time),
        truck_done=dict(state.truck_done),
        in_transit=sorted(state.truck_in_transit),
        returning=sorted(state.truck_returning),
        committed={truck: [vid, customer] for truck, (vid, customer) in state.truck_committed_first.items()},
        min_insert=dict(state.truck_min_insert),
        fixed_first=dict(state.truck_fixed_first),
        channel_free=dict(state.truck_channel_free),
        energy=dict(state.drone_energy),
        drone_start=drone_start,
        carrier=dict(state.drone_carrier),
        holder_counts=holders,
        holder_sha256=digest(state.parcel_holder),
        delivered_count=len(state.delivered),
        delivered_sha256=digest(sorted(state.delivered)),
        dispatched_count=len(state.dispatched),
        dispatched_sha256=digest(sorted(state.dispatched)),
        x_failure_p=state.x_failure_p,
        air_ceiling_is_none=state.air_ceiling is None,
        prefix_distance_m=state.prefix_distance_m,
    )


def config_view(obj):
    return {field.name: getattr(obj, field.name) for field in obj.__dataclass_fields__.values()}


def context_view(loaded):
    inst, phys, alg, plan, state, greq, opts = loaded
    public_opts = {key: value for key, value in opts.items() if key != "extra_pool"}
    return dict(
        types=[f"{type(item).__module__}.{type(item).__name__}" for item in loaded],
        instance_id=inst.case_id,
        plan=plan_view(plan),
        state=state_view(state),
        phys_sha256=digest(config_view(phys)),
        alg_sha256=digest(config_view(alg)),
        greq_count=len(greq),
        greq_sha256=digest(sorted(greq)),
        opts=public_opts,
        extra_pool_sha256=digest(sorted(opts.get("extra_pool") or [])),
    )


def compare_job(job):
    m48 = M48 / job / "001/VISIBLE_CONTEXT.pkl"
    m49 = M49 / job / "001/VISIBLE_CONTEXT.pkl"
    left, right = load_context(m48), load_context(m49)
    view_m48, view_m49 = context_view(left), context_view(right)
    fields = {}
    for key in view_m49:
        fields[key] = view_m48[key] == view_m49[key]
    return dict(
        job=job,
        pinned_for_the_conditional="M49",
        not_claimed_to_be_the_m48_file=True,
        m48_byte_sha256=sha256(m48),
        m49_byte_sha256=sha256(m49),
        byte_identical=sha256(m48) == sha256(m49),
        byte_difference="set member order inside the pickle, first seen at the dispatched set; membership is equal",
        semantic_equal=all(fields.values()),
        field_equal=fields,
        m49_semantic_sha256=digest(view_m49),
        m49_view=view_m49,
    )


def violation_codes(path):
    import gzip
    from collections import Counter
    counts = Counter()
    with gzip.open(path, "rt") as handle:
        for line in handle:
            evaluation = (json.loads(line).get("evaluation") or {})
            if evaluation.get("feasible"):
                counts["FEASIBLE"] += 1
                continue
            raw = (evaluation.get("violations") or [evaluation.get("status") or "UNKNOWN"])[0]
            counts[str(raw).split(":", 1)[0]] += 1
    return dict(counts)


def init_raw_index():
    rows = {}
    for job in JOBS:
        rows[job] = {}
        for label, root in (("M48", M48), ("M49", M49)):
            path = root / job / "001/CANDIDATES.jsonl.gz"
            rows[job][label] = dict(sha256=sha256(path), codes=violation_codes(path), lines_are_init_evaluations=True)
    return rows


def main():
    report = dict(
        method="loaded both pickles with the sealed 39a85 classes; compared fields; did not evaluate",
        jobs=[compare_job(job) for job in JOBS],
        init_raw=init_raw_index(),
    )
    (HERE / "SEMANTIC_INPUT.json").write_text(json.dumps(report, indent=1) + "\n")
    print("SEMANTIC_COMPARE_WRITTEN", all(item["semantic_equal"] for item in report["jobs"]),
          "byte_identical", [item["byte_identical"] for item in report["jobs"]])


if __name__ == "__main__":
    main()
