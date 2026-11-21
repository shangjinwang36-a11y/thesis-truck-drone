"""Controller for the M44 nominals that the sealed M48 run did not already cover.

Creates state before any worker. Does not touch the sealed M48 state or core.
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
CORE = HERE.parent / "M48_depot_road_release_core_20261121"
M47_BATCH = HERE.parent / "M47_bounded_actual_20261121"
SEALED_CORE = "74ae8419889b98e735dd68fcf16407165b5980535acde3179e3d168a8f7e3d47"
AUDITED_DRIVER = "c51adad6f8d6d5bcd3622b34729ff2f1625948205bbc831751c73dad81099d0b"
AUDITED_REGISTRATION = "cfe78cd9429c5293636fea3ef64c37063200242c15748bf9ba684c1d985e5a71"


class CheckpointActive(SystemExit):
    """A checkpoint still lists workers. Do not spawn."""


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
        stage="M48_M44", phase="M48_M44_ready", pid=None, controller_pid=None,
        optimizer_running=False, actual_execution_running=False, active_processes=[],
        actual_execution_started=False, actual_completed=0, actual_failed=0,
    )
    dump(path, state)
    return state


def phase_name(active, failed, pending, started, blocked):
    if blocked or failed:
        return "M48_M44_blocked"
    if active:
        return "M48_M44_running"
    if started and not pending:
        return "M48_M44_complete_audit_pending"
    return "M48_M44_ready"


def exclusive_outputs(stage, job):
    variant, case, arm, stream, seed, hmode = job
    tag = "_".join(map(str, job))
    return [
        Path(stage) / variant / "executions" / hmode / stream / f"{case}_{seed}_{arm}.json",
        Path(stage) / "worker_logs" / f"{tag}.log",
        Path(stage) / "call_journals" / f"{variant}_{case}_{seed}_{arm}.jsonl",
        Path(stage) / "fresh_processes" / f"{variant}_{case}_{seed}_{arm}.json",
    ]


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
    done = {tuple(item["job"]) if isinstance(item, dict) else tuple(item) for item in completed}
    bad = {tuple(item["job"]) if isinstance(item, dict) else tuple(item) for item in failed}
    pending = deque(job for job in jobs if job not in done and job not in bad)
    return pending, completed, failed, False


def refuse_existing_output(stage, pending):
    for job in pending:
        for path in exclusive_outputs(stage, tuple(job)):
            if path.exists():
                raise SystemExit("output already exists " + path.name)


def preflight(stage, reg, pending):
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(M47_BATCH))
    os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    from private_root import private_root, witness
    from prepare_registration import build_registration
    private_root()
    freeze = json.loads((Path(stage) / "ACTUAL_EXECUTION_FREEZE.json").read_text())
    for name, digest in freeze.items():
        if sha256(Path(stage) / name) != digest:
            raise SystemExit("freeze mismatch " + name)
    if freeze["fresh_actual.py"] != AUDITED_DRIVER or freeze["FRESH_JOB_REGISTRATION.json"] != AUDITED_REGISTRATION:
        raise SystemExit("driver or registration is not the audited file")
    if reg["init_eval_budget"] != 100 or reg["main_eval_budget"] != 1000 or reg["driver_sha256"] != AUDITED_DRIVER:
        raise SystemExit("budget or driver hash drifted")
    if reg["core_freeze_sha256"] != SEALED_CORE or sha256(CORE / "EXPERIMENT_CORE_FREEZE.json") != SEALED_CORE:
        raise SystemExit("core is not the sealed M48 core")
    core = json.loads((CORE / "EXPERIMENT_CORE_FREEZE.json").read_text())
    if len(core) != 147 or any(sha256(CORE / name) != digest for name, digest in core.items()):
        raise SystemExit("core member drifted")
    fresh = build_registration()
    if fresh["jobs"] != reg["jobs"] or fresh["logical_count"] != 36:
        raise SystemExit("registration does not match the recomputed scope")
    if [row["execution_fingerprint"] for row in fresh["logical_mapping"]] != [row["execution_fingerprint"] for row in reg["logical_mapping"]]:
        raise SystemExit("fingerprint mismatch")
    if len(reg["jobs"]) != reg["unique_fresh_jobs"] or len(reg["logical_mapping"]) != 36:
        raise SystemExit("fresh list is not the computed remainder")
    reused = [row for row in reg["logical_mapping"] if row["disposition"] == "REUSE_FINISHED_M48"]
    if len(reused) + len(reg["jobs"]) != 36:
        raise SystemExit("reuse plus fresh is not 36 logical jobs")
    for row in reused:
        path = Path(row["reused_execution"])
        if not path.is_file() or sha256(path) != row["reused_execution_sha256"]:
            raise SystemExit("reused execution is missing or changed")
    for job in reg["jobs"]:
        variant, case, arm, stream, seed, hmode = job
        if variant != "M48_M44_NOMINAL" or arm not in "SRX" or stream != "dev" or hmode != "own" or seed not in (1001, 1002):
            raise SystemExit("fresh job is outside the computed remainder")
        if not witness(case, seed).is_file():
            raise SystemExit("recorded witness missing")
    refuse_existing_output(stage, pending)


def process_snapshot(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rindex(")") + 2:].split()
        tick = os.sysconf("SC_CLK_TCK")
        return dict(pid=pid, state=fields[0], cpu_s=(int(fields[11]) + int(fields[12])) / tick, resident_bytes=int(fields[21]) * os.sysconf("SC_PAGE_SIZE"))
    except FileNotFoundError:
        return dict(pid=pid, state="exited_during_snapshot")


def save(stage, active, completed, failed, pending, started, blocked, write_progress):
    path = Path(stage) / "state.json"
    state = json.loads(path.read_text())
    if started and "started_at" not in state:
        state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.setdefault("controller_started_unix", time.time())
    state.update(
        stage="M48_M44", phase=phase_name(active, failed, pending, started, blocked),
        pid=os.getpid(), controller_pid=os.getpid(), optimizer_running=bool(active),
        actual_execution_running=bool(active),
        active_processes=([os.getpid()] + [proc.pid for proc, job, log in active]) if active else [],
        actual_execution_started=bool(started), actual_completed=len(completed), actual_failed=len(failed),
    )
    dump(path, state)
    if write_progress:
        rows = [dict(job=list(job), process=process_snapshot(proc.pid)) for proc, job, log in active]
        dump(Path(stage) / "FRESH_PROGRESS.json", dict(completed=completed, failures=failed, pending=[list(job) for job in pending], active=rows, wall_s=time.time() - state["controller_started_unix"]))
        with (Path(stage) / "ACTUAL_PROCESS_SAMPLES.jsonl").open("a") as handle:
            handle.write(json.dumps(dict(unix_s=time.time(), active=rows)) + "\n")
            handle.flush()
    return state


def serve(stage, spawn, check=None):
    stage = Path(stage)
    reg = json.loads((stage / "FRESH_JOB_REGISTRATION.json").read_text())
    jobs = [tuple(job) for job in reg["jobs"]]
    ensure_state(stage)
    pending, completed, failed, blocked = restore(stage, jobs)
    (preflight if check is None else check)(stage, reg, pending)
    if blocked:
        save(stage, [], completed, failed, pending, True, True, False)
        raise CheckpointActive("checkpoint lists active workers; not spawning")
    started = bool(completed or failed)
    save(stage, [], completed, failed, pending, started, False, True)
    active = []
    pause = threading.Event()
    while pending or active:
        while pending and len(active) < 2 and not failed:
            job = pending.popleft()
            refuse_existing_output(stage, [job])
            proc, log = spawn(stage, job)
            active.append((proc, job, log))
            started = True
            print("START", list(job), proc.pid, flush=True)
            save(stage, active, completed, failed, pending, started, False, True)
        for proc, job, log in list(active):
            code = proc.poll()
            if code is None:
                continue
            log.close()
            row = dict(job=list(job), pid=proc.pid, exit_code=code)
            (failed if code else completed).append(row)
            active.remove((proc, job, log))
            print("FINISH", len(completed), row, flush=True)
        save(stage, active, completed, failed, pending, started, False, True)
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
    env = dict(os.environ)
    env["M47_PRIVATE_EXEC_ROOT"] = os.environ.get("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    proc = subprocess.Popen([sys.executable, str(Path(stage) / "fresh_actual.py"), "worker", json.dumps(list(job))], stdout=log, stderr=subprocess.STDOUT, env=env)
    return proc, log


def main():
    os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    sys.path.insert(0, str(M47_BATCH))
    from private_root import private_root
    private_root()
    serve(HERE, popen_spawn)


if __name__ == "__main__":
    main()
