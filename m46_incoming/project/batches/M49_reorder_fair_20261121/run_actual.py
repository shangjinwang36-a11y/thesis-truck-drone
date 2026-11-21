"""M49 controller. State is written before any worker. Spawn is replaceable and refuses by default."""
from collections import deque
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
M47_BATCH = HERE.parent / "M47_bounded_actual_20261121"
LAUNCH_ENV = "M49_LAUNCH_APPROVED"
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"


class CheckpointActive(SystemExit):
    """A checkpoint still lists workers. Do not spawn."""


def approved() -> bool:
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def ensure_state(stage):
    path = Path(stage) / "state.json"
    if path.is_file():
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            raise SystemExit("state.json is not an object")
        return state
    state = dict(
        stage="M49_REORDER",
        phase="ready",
        pid=None,
        controller_pid=None,
        optimizer_running=False,
        actual_execution_running=False,
        active_processes=[],
        actual_execution_started=False,
        actual_completed=0,
        actual_failed=0,
    )
    dump(path, state)
    return state


def restore(stage, jobs):
    path = Path(stage) / "FRESH_PROGRESS.json"
    if not path.is_file():
        return deque(jobs), [], [], False
    body = json.loads(path.read_text())
    completed = list(body.get("completed") or [])
    failed = list(body.get("failures") or [])
    if body.get("active"):
        return deque(), completed, failed, True
    done = {tuple(item["job"]) if isinstance(item, dict) else tuple(item) for item in completed}
    bad = {tuple(item["job"]) if isinstance(item, dict) else tuple(item) for item in failed}
    if "pending" in body:
        pending = deque(tuple(item) for item in body["pending"] if tuple(item) not in done and tuple(item) not in bad)
    else:
        pending = deque(job for job in jobs if job not in done and job not in bad)
    return pending, completed, failed, False


def exclusive_outputs(stage, job):
    variant, case, arm, stream, seed, hmode = job
    tag = "_".join(map(str, job))
    return [
        Path(stage) / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json",
        Path(stage) / "worker_logs" / f"{tag}.log",
        Path(stage) / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl",
    ]


def refuse_existing_output(stage, pending):
    for job in pending:
        for path in exclusive_outputs(stage, tuple(job)):
            if path.exists():
                raise SystemExit("output already exists " + path.name)


def scope_ok(stage):
    freeze_path = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha256(freeze_path) != REQUIRED_FREEZE:
        return False
    freeze = json.loads(freeze_path.read_text())
    if len(freeze) != 147 or any(sha256(CORE / name) != digest for name, digest in freeze.items()):
        return False
    reg_path = Path(stage) / "FRESH_JOB_REGISTRATION.json"
    if not reg_path.is_file():
        return False
    reg = json.loads(reg_path.read_text())
    if reg.get("core_freeze_sha256") != REQUIRED_FREEZE:
        return False
    if reg.get("init_eval_budget") != 100 or reg.get("main_eval_budget") != 1000:
        return False
    if reg.get("logical_count") != 36 or len(reg.get("jobs") or []) != 36:
        return False
    if sha256(HERE / "fresh_actual.py") != reg.get("driver_sha256"):
        return False
    if sha256(HERE / "run_actual.py") != reg.get("controller_sha256"):
        return False
    nominal = M47_BATCH / "M47_CANDIDATE" / "nominal"
    for case in ("C50", "R50", "RC50", "C100", "R100", "RC100"):
        if sha256(nominal / "S" / case / "nominal_plan.json") != reg["nominal_sha256"][f"S/{case}"]:
            return False
        if sha256(nominal / "X" / case / "nominal_plan.json") != reg["nominal_sha256"][f"X/{case}"]:
            return False
    for row in reg["logical_mapping"]:
        arm = row["logical_job"][2]
        case = row["logical_job"][1]
        if arm in ("S", "R") and row["nominal_sha256"] != reg["nominal_sha256"][f"S/{case}"]:
            return False
        if arm == "X" and row["nominal_sha256"] != reg["nominal_sha256"][f"X/{case}"]:
            return False
        if arm == "S" and row["recovery_policy"] != "S":
            return False
        if arm in ("R", "X") and row["recovery_policy"] != "X":
            return False
    return True


def save(stage, active, completed, failed, pending, started, blocked):
    path = Path(stage) / "state.json"
    state = json.loads(path.read_text())
    state.update(
        stage="M49_REORDER",
        phase="blocked" if blocked else ("running" if active else "ready"),
        pid=os.getpid(),
        controller_pid=os.getpid(),
        optimizer_running=bool(active),
        actual_execution_running=bool(active),
        active_processes=[proc.pid for proc, _job, _log in active],
        actual_execution_started=bool(started or active),
        actual_completed=len(completed),
        actual_failed=len(failed),
    )
    dump(path, state)
    dump(Path(stage) / "FRESH_PROGRESS.json", dict(
        completed=completed, failures=failed,
        pending=[list(job) for job in pending],
        active=[{"job": list(job), "pid": proc.pid} for proc, job, _log in active],
    ))
    return state


def serve(stage, spawn):
    """Real launch branch. `spawn` is the only process factory. Tests pass a zero-worker."""
    stage = Path(stage)
    ensure_state(stage)
    if not scope_ok(stage):
        raise SystemExit("scope mismatch")
    reg = json.loads((stage / "FRESH_JOB_REGISTRATION.json").read_text())
    jobs = [tuple(job) for job in reg["jobs"]]
    pending, completed, failed, blocked = restore(stage, jobs)
    if blocked:
        save(stage, [], completed, failed, pending, True, True)
        raise CheckpointActive("checkpoint lists active workers; not spawning")
    refuse_existing_output(stage, pending)
    save(stage, [], completed, failed, pending, bool(completed or failed), False)
    active = []
    while pending or active:
        while pending and len(active) < 2 and not failed:
            job = pending.popleft()
            refuse_existing_output(stage, [job])
            proc, log, job = spawn(stage, job)
            active.append((proc, job, log))
            save(stage, active, completed, failed, pending, True, False)
        for proc, job, log in list(active):
            code = proc.poll()
            if code is None:
                continue
            if log is not None:
                log.close()
            (failed if code else completed).append(dict(job=list(job), pid=proc.pid, exit_code=code))
            active.remove((proc, job, log))
            save(stage, active, completed, failed, pending, True, False)
        if failed and not active:
            break
        if active:
            time.sleep(0.01)
    if failed:
        raise SystemExit("worker failed")
    return json.loads((stage / "state.json").read_text())


def popen_spawn(stage, job):
    if not approved():
        raise SystemExit("not launched")
    tag = "_".join(map(str, job))
    log_path = Path(stage) / "worker_logs" / f"{tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("x")
    worker = Path(__file__).resolve().parent / "fresh_actual.py"
    proc = subprocess.Popen(
        [sys.executable, str(worker), "worker", json.dumps(list(job))],
        stdout=log, stderr=subprocess.STDOUT,
        env={**os.environ, "M47_PRIVATE_EXEC_ROOT": os.environ.get("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")},
    )
    return proc, log, job


def approved() -> bool:
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def main():
    if not approved():
        ensure_state(HERE)
        if not scope_ok(HERE):
            raise SystemExit("scope mismatch")
        raise SystemExit("not launched")
    serve(HERE, popen_spawn)


if __name__ == "__main__":
    main()
