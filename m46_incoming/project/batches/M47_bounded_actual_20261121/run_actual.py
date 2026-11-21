"""M47 actual controller.

Create and save state.json before any worker. A checkpoint that still lists
active workers is left in place and is not given a replacement process.
"""
from collections import deque
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import threading

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"

AUDITED_DRIVER = "2547a985e75f32ef5ec239db0abceb7a72dfb565d8b15243119f24507f033561"
AUDITED_CORE = "a509cc36961296e24dec23d212dddbc2dcc07bc08ec16618549ce726897e8f48"
AUDITED_REGISTRATION = "71d8fb2ed2673d135c742c5c3f1256023196c6ed44a199250b725ed3b7a7669a"


class CheckpointActive(SystemExit):
    """Previous controller still lists workers. Do not spawn."""


def dump(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ensure_state(stage):
    path = Path(stage) / "state.json"
    if path.is_file():
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            raise SystemExit("state.json is not an object")
        return state
    state = dict(
        stage="M47",
        phase="M47_bounded_actual_ready",
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


def phase_name(active, failed, pending, started, blocked):
    if blocked:
        return "M47_actual_blocked"
    if active:
        return "M47_bounded_actual_running"
    if failed:
        return "M47_actual_blocked"
    if started and not pending:
        return "M47_bounded_actual_complete_audit_pending"
    return "M47_bounded_actual_ready"


def exclusive_outputs(stage, job):
    variant, case, arm, stream, seed, hmode = job
    tag = "_".join(map(str, job))
    return [
        Path(stage) / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json",
        Path(stage) / "worker_logs" / f"{tag}.log",
        Path(stage) / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl",
        Path(stage) / "fresh_processes" / f"{variant}_{case}_{seed}_{arm}.json",
    ]


def _job(item):
    if isinstance(item, dict):
        return tuple(item["job"])
    return tuple(item)


def restore(stage, jobs):
    path = Path(stage) / "FRESH_PROGRESS.json"
    if not path.is_file():
        return deque(jobs), [], [], False
    body = json.loads(path.read_text())
    completed = list(body.get("completed") or [])
    failed = list(body.get("failures") or [])
    active = list(body.get("active") or [])
    if active:
        return deque(), completed, failed, True
    done = {_job(item) for item in completed}
    bad = {_job(item) for item in failed}
    if "pending" in body:
        pending = deque(tuple(item) for item in body["pending"] if tuple(item) not in done and tuple(item) not in bad)
    else:
        pending = deque(job for job in jobs if job not in done and job not in bad)
    return pending, completed, failed, False


def preflight(stage, reg, pending):
    sys.path.insert(0, str(stage))
    from private_root import private_root, witness
    private_root()
    freeze = json.loads((Path(stage) / "ACTUAL_EXECUTION_FREEZE.json").read_text())
    if len(freeze) != 16:
        raise SystemExit("execution freeze does not have 16 members")
    for name, digest in freeze.items():
        if sha256(Path(stage) / name) != digest:
            raise SystemExit("freeze mismatch " + name)
    if freeze["fresh_actual.py"] != AUDITED_DRIVER or freeze["FRESH_JOB_REGISTRATION.json"] != AUDITED_REGISTRATION:
        raise SystemExit("driver or registration is not the audited file")
    if reg["logical_count"] != 72 or reg["unique_fresh_jobs"] != 40 or len(reg["jobs"]) != 40 or len(reg["logical_mapping"]) != 72:
        raise SystemExit("registration is not 72 logical and 40 fresh")
    core_path = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha256(core_path) != AUDITED_CORE:
        raise SystemExit("core freeze file hash drifted")
    core = json.loads(core_path.read_text())
    if len(core) != 147:
        raise SystemExit("core freeze does not have 147 members")
    for name, digest in core.items():
        if sha256(CORE / name) != digest:
            raise SystemExit("core member mismatch " + name)
    seen = set()
    for job in reg["jobs"]:
        variant, case, arm, stream, seed, hmode = job
        if stream != "dev" or hmode != "own" or seed not in (1001, 1002) or arm not in "SRX":
            raise SystemExit("job outside the frozen batch")
        nominal = Path(stage) / variant / "nominal" / ("X" if arm == "X" else "S") / case / "nominal_plan.json"
        if not nominal.is_file() or not witness(case, seed).is_file():
            raise SystemExit("nominal or recorded witness missing")
        seen.add(tuple(job))
    if len(seen) != 40:
        raise SystemExit("canonical jobs are not unique")
    for job in pending:
        for path in exclusive_outputs(stage, tuple(job)):
            if path.exists():
                raise SystemExit("output already exists " + path.name)


def process_snapshot(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rindex(")") + 2:].split()
        tick = os.sysconf("SC_CLK_TCK")
        return dict(pid=pid, state=fields[0], cpu_s=(int(fields[11]) + int(fields[12])) / tick, resident_bytes=int(fields[21]) * os.sysconf("SC_PAGE_SIZE"))
    except FileNotFoundError:
        return dict(pid=pid, state="exited_during_snapshot")


def save(stage, mirror, active, completed, failed, pending, started, blocked, write_progress):
    path = Path(stage) / "state.json"
    state = json.loads(path.read_text())
    if started and "started_at" not in state:
        state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.setdefault("controller_started_unix", time.time())
    state.update(
        stage="M47",
        phase=phase_name(active, failed, pending, started, blocked),
        pid=os.getpid(),
        controller_pid=os.getpid(),
        optimizer_running=bool(active),
        actual_execution_running=bool(active),
        active_processes=([os.getpid()] + [proc.pid for proc, job, log in active]) if active else [],
        actual_execution_started=bool(started),
        actual_completed=len(completed),
        actual_failed=len(failed),
    )
    dump(path, state)
    if mirror is not None:
        dump(Path(mirror) / "state.json", state)
    if write_progress:
        rows = [dict(job=list(job), process=process_snapshot(proc.pid)) for proc, job, log in active]
        dump(Path(stage) / "FRESH_PROGRESS.json", dict(completed=completed, failures=failed, pending=[list(job) for job in pending], active=rows, wall_s=time.time() - state["controller_started_unix"], no_stale_log_abort=True))
        with (Path(stage) / "ACTUAL_PROCESS_SAMPLES.jsonl").open("a") as handle:
            handle.write(json.dumps(dict(unix_s=time.time(), active=rows)) + "\n")
            handle.flush()
    return state


def serve(stage, mirror, spawn, check=None):
    stage = Path(stage)
    reg = json.loads((stage / "FRESH_JOB_REGISTRATION.json").read_text())
    jobs = [tuple(job) for job in reg["jobs"]]
    ensure_state(stage)
    pending, completed, failed, blocked = restore(stage, jobs)
    (preflight if check is None else check)(stage, reg, pending)
    if blocked:
        save(stage, mirror, [], completed, failed, pending, True, True, False)
        raise CheckpointActive("checkpoint lists active workers; not spawning")
    started = bool(completed or failed)
    save(stage, mirror, [], completed, failed, pending, started, False, True)
    active = []
    pause = threading.Event()
    while pending or active:
        while pending and len(active) < 2 and not failed:
            job = pending.popleft()
            for path in exclusive_outputs(stage, job):
                if path.exists():
                    raise SystemExit("output already exists " + path.name)
            proc, log = spawn(stage, job)
            active.append((proc, job, log))
            started = True
            print("START", list(job), proc.pid, flush=True)
            save(stage, mirror, active, completed, failed, pending, started, False, True)
        for proc, job, log in list(active):
            code = proc.poll()
            if code is None:
                continue
            log.close()
            row = dict(job=list(job), pid=proc.pid, exit_code=code)
            (failed if code else completed).append(row)
            active.remove((proc, job, log))
            print("FINISH", len(completed), row, flush=True)
        save(stage, mirror, active, completed, failed, pending, started, False, True)
        if failed and not active:
            break
        if active:
            pause.wait(3.0)
    if failed:
        raise SystemExit(repr(failed))
    return json.loads((stage / "state.json").read_text())


def popen_spawn(stage, job):
    tag = "_".join(map(str, job))
    log_path = Path(stage) / "worker_logs" / f"{tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("x")
    proc = subprocess.Popen([sys.executable, str(Path(stage) / "fresh_actual.py"), "worker", json.dumps(list(job))], stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def main():
    sys.path.insert(0, str(HERE))
    from private_root import private_root
    private_root()
    serve(HERE, PROJECT, popen_spawn)


if __name__ == "__main__":
    main()
