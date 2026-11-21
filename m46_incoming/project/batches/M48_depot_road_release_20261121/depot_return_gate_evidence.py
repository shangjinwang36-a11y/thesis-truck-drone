"""Formal gate evidence for an unfinished return. Not a recovery search.

The original gate is called inside evaluate_plan. These calls are a separate
diagnostic and are not part of the 36 actual jobs.
"""
from pathlib import Path
import hashlib
import inspect
import json
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M48_depot_road_release_core_20261121"
M47 = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
sys.path.insert(0, str(CORE))
from research import plan_from_dict, setup  # noqa: E402
from tdr.alns import Budget  # noqa: E402
from tdr.evaluate import evaluate_plan  # noqa: E402
from tdr.evaluation_audit import audit_evaluations  # noqa: E402
from tdr.recovery import _legalize_depot_preparation  # noqa: E402
from tdr.schedule import committed_first_stop_violation, initial_state, schedule_plan  # noqa: E402

OUT = HERE / "RETURN_GATE_EVIDENCE_X.json"
NOMINAL = HERE.parent / "M47_bounded_actual_20261121" / "M47_CANDIDATE" / "nominal" / "X" / "C50" / "nominal_plan.json"
HORIZON = HERE.parent / "M47_bounded_actual_20261121" / "M47_CANDIDATE" / "nominal" / "S" / "C50" / "nominal_plan.json"


def gate_source(root):
    path = root / "source/proj_r6/src/tdr/schedule.py"
    text = path.read_text()
    start = text.index("def committed_first_stop_violation")
    end = text.index("\ndef initial_state")
    return text[start:end]


def first_drive(timeline, truck):
    return next(a for a in timeline.actions if a.actor == truck and a.kind == "DRIVE")


def main():
    inst, phys, alg = setup("C50", "M48")
    phys.set_active()
    raw = json.loads(NOMINAL.read_text())
    plan = plan_from_dict(raw["plan"])
    H = json.loads(HORIZON.read_text())["H_s"]
    assert any(not s.started and s.launch_vid is None and s.truck == "t2" for s in plan.sorties.values())
    depot = (inst.depot_x, inst.depot_y)
    m47_gate = gate_source(M47)
    m48_gate = gate_source(CORE)
    rows = []
    with audit_evaluations() as audit:
        parked = initial_state(inst, phys)
        parked_ev = evaluate_plan(plan, inst, phys, parked, H, "RETURN_GATE_AT_DEPOT", budget=Budget(1, None))
        drive = first_drive(parked_ev.timeline, "t2")
        rows.append(dict(
            name="at_depot_not_in_transit",
            formal_evaluations=1,
            feasible=bool(parked_ev.feasible),
            status=parked_ev.status,
            violation=parked_ev.violations[:1],
            gate=committed_first_stop_violation(plan, parked),
            first_drive_from=list(drive.info["from"]),
            first_drive_from_is_depot=list(drive.info["from"]) == list(depot),
            prepare_before_drive=any(a.kind == "P" and a.info.get("depot") and a.end <= drive.start + 1e-9 for a in parked_ev.timeline.actions if a.actor == "t2"),
        ))
        returning = initial_state(inst, phys)
        returning.t0 = 30.0
        returning.truck_start_pos["t2"] = (depot[0] + 400.0, depot[1] + 250.0)
        returning.truck_start_time["t2"] = 30.0
        returning.truck_ready_time["t2"] = 30.0
        returning.truck_in_transit.add("t2")
        returning.truck_returning.add("t2")
        back_ev = evaluate_plan(plan, inst, phys, returning, H, "RETURN_GATE_UNFINISHED_RETURN", budget=Budget(1, None))
        raised = None
        try:
            schedule_plan(plan, inst, phys, returning)
        except ValueError as exc:
            raised = str(exc)
        rows.append(dict(
            name="unfinished_return_depot_launch",
            formal_evaluations=1,
            schedule_plan_extra_evaluations=0,
            feasible=bool(back_ev.feasible),
            status=back_ev.status,
            violation=back_ev.violations[:1],
            timeline_emitted=back_ev.timeline is not None,
            schedule_plan_raised=raised,
            body_is_depot=list(returning.truck_start_pos["t2"]) == list(depot),
        ))
        arrived = initial_state(inst, phys)
        arrived.t0 = 30.0
        for truck in list(arrived.truck_start_time):
            arrived.truck_start_time[truck] = 30.0
            arrived.truck_ready_time[truck] = 30.0
        arrived_ev = evaluate_plan(plan, inst, phys, arrived, H, "RETURN_GATE_ARRIVED_AT_DEPOT", budget=Budget(1, None))
        arrived_drive = None if arrived_ev.timeline is None else first_drive(arrived_ev.timeline, "t2")
        rows.append(dict(
            name="arrived_at_depot_future_launch",
            formal_evaluations=1,
            feasible=bool(arrived_ev.feasible),
            status=arrived_ev.status,
            violation=arrived_ev.violations[:3],
            gate=committed_first_stop_violation(plan, arrived),
            in_transit=sorted(arrived.truck_in_transit),
            first_drive_from=None if arrived_drive is None else list(arrived_drive.info["from"]),
            first_drive_from_is_depot=None if arrived_drive is None else list(arrived_drive.info["from"]) == list(depot),
        ))
        moving = initial_state(inst, phys)
        moving.t0 = 30.0
        moving.truck_start_pos["t2"] = (depot[0] + 400.0, depot[1] + 250.0)
        moving.truck_start_time["t2"] = 30.0
        moving.truck_ready_time["t2"] = 30.0
        moving.truck_in_transit.add("t2")
        placed = _legalize_depot_preparation(plan.clone(), inst, phys, moving)
        moved_ev = evaluate_plan(placed, inst, phys, moving, H, "RETURN_GATE_RETARGET_NEXT_VISIT", budget=Budget(1, None))
        moved_drive = None if moved_ev.timeline is None else first_drive(moved_ev.timeline, "t2")
        snapshot = list(moving.truck_start_pos["t2"])
        launch_at_depot = False
        prepare_during_drive = False
        if moved_ev.timeline is not None and moved_drive is not None:
            for action in moved_ev.timeline.actions:
                if action.actor != "t2":
                    continue
                if action.kind == "P" and action.info.get("depot") and action.start < moved_drive.end - 1e-9:
                    prepare_during_drive = True
                if action.kind == "L" and action.info.get("pos") is not None:
                    pos = action.info["pos"]
                    if abs(pos[0] - depot[0]) < 1e-6 and abs(pos[1] - depot[1]) < 1e-6 and snapshot != list(depot):
                        launch_at_depot = True
        rows.append(dict(
            name="in_transit_retarget_then_formal",
            formal_evaluations=1,
            feasible=bool(moved_ev.feasible),
            status=moved_ev.status,
            violation=moved_ev.violations[:3],
            gate_after_retarget=committed_first_stop_violation(placed, moving),
            first_drive_from=None if moved_drive is None else list(moved_drive.info["from"]),
            first_drive_matches_snapshot=None if moved_drive is None else list(moved_drive.info["from"]) == snapshot,
            depot_prepare_while_body_elsewhere=prepare_during_drive,
            launch_position_is_depot_while_body_elsewhere=launch_at_depot,
        ))
        ledger = audit.summary()
    report = dict(
        claim_retracted="An unfinished return does not make a new depot launch legal. The original gate still rejects it, and the scheduler raises before emitting preparation.",
        gate_source_matches_m47=m48_gate == m47_gate,
        gate_sha256=hashlib.sha256(m48_gate.encode()).hexdigest(),
        native_search_evaluations=0,
        formal_evaluate_plan_calls=ledger["accepted_calls"],
        ledger=ledger,
        rows=rows,
        H=H,
        prior_s_nominal_calls_not_a_depot_witness=4,
        plan="C50 X nominal",
    )
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(dict(gate_same=report["gate_source_matches_m47"], calls=report["formal_evaluate_plan_calls"], rows=[(r["name"], r["feasible"], r.get("violation")) for r in rows]), indent=1))


if __name__ == "__main__":
    main()
