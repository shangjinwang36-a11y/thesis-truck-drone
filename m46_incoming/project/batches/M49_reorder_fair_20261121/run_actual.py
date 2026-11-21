"""State-first entry for a future M49 fair batch. It does not spawn workers."""
from collections import deque
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
LAUNCH_ENV = "M49_LAUNCH_APPROVED"
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"


class CheckpointActive(SystemExit):
    """A checkpoint still lists workers. Do not spawn."""


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
    if body.get("active"):
        return deque(), list(body.get("completed") or []), list(body.get("failures") or []), True
    done = {tuple(item["job"]) if isinstance(item, dict) else tuple(item) for item in body.get("completed") or []}
    pending = deque(tuple(job) for job in jobs if tuple(job) not in done)
    return pending, list(body.get("completed") or []), list(body.get("failures") or []), False


def exclusive_outputs(stage, job):
    variant, case, _arm, stream, seed, hmode = job
    tag = "_".join(map(str, job))
    return [
        Path(stage) / variant / "executions" / hmode / stream / f"{case}_{seed}_{job[2]}.json",
        Path(stage) / "worker_logs" / f"{tag}.log",
    ]


def refuse_existing_output(stage, pending):
    for job in pending:
        for path in exclusive_outputs(stage, tuple(job)):
            if path.exists():
                raise SystemExit("output already exists " + path.name)


def core_members_match():
    freeze_path = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha256(freeze_path) != REQUIRED_FREEZE:
        return False
    freeze = json.loads(freeze_path.read_text())
    if len(freeze) != 147:
        return False
    return all(sha256(CORE / name) == digest for name, digest in freeze.items())


def main():
    if os.environ.get(LAUNCH_ENV) != "parent-approved":
        raise SystemExit("not launched")
    if not core_members_match():
        raise SystemExit("core freeze mismatch")
    raise SystemExit("registration is not approved for launch")


if __name__ == "__main__":
    main()
