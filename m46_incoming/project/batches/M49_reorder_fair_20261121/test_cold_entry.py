"""Cold entry acceptance. One real worker main, stub only at evaluate_plan.

The subprocess has no PYTHONPATH. Approval is set only inside this test so the
body is reached; it is not a launch of the 36. Outputs are marked TEST and removed.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
JOB = ["M49_REORDER", "C50", "S", "dev", 1001, "own"]
PRIVATE = os.environ.get("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_controller():
    spec = importlib.util.spec_from_file_location("m49_cold_controller", HERE / "run_actual.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_env(root):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "M47_PRIVATE_EXEC_ROOT": PRIVATE,
        "M49_LAUNCH_APPROVED": "parent-approved",
        "M49_DRY_RUN": "1",
        "M49_EVALUATE_STUB": "1",
        "M49_OUTPUT_ROOT": str(root),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return env


def run_worker(root, registration=None):
    env = base_env(root)
    if registration is not None:
        env["M49_REGISTRATION"] = str(registration)
    return subprocess.run(
        [sys.executable, str(HERE / "fresh_actual.py"), "worker", json.dumps(JOB)],
        env=env, cwd=str(HERE), capture_output=True, text=True,
    )


def registration_copy(root, mutate):
    reg = json.loads((HERE / "FRESH_JOB_REGISTRATION.json").read_text())
    for row in reg["logical_mapping"]:
        if row["logical_job"] == JOB:
            mutate(row)
            break
    else:
        raise AssertionError("job missing from registration")
    path = root / "registration.json"
    path.write_text(json.dumps(reg))
    return path


def test_runner_binding():
    code = (
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        "path = Path(sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location('m49_worker_bind', path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "runner = module.load_runner()\n"
        "print('SEVEN_API_BOUND', Path(runner.__file__).resolve())\n"
        "print('RUNNER_API', ','.join(module.RUNNER_API))\n"
    )
    env = base_env(Path(tempfile.mkdtemp(prefix="m49_bind_")))
    proc = subprocess.run([sys.executable, "-c", code, str(HERE / "fresh_actual.py")], env=env, capture_output=True, text=True)
    shutil.rmtree(env["M49_OUTPUT_ROOT"], ignore_errors=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] + proc.stdout[-2000:])
    text = proc.stdout
    assert "source/round10_recheck/run_emin005.py" in text
    assert "audit_evaluations,evaluate_plan,initial_state,run_episode,derive_rngs,clean,verify_replay" in text
    print(text.strip())


def test_serialization_and_bad_result():
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "path = Path(sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location('m49_worker_serial', path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "module.bind_core()\n"
        "from tdr.replay import ReplayReport\n"
        "import run_emin005 as runner\n"
        "try:\n"
        "    json.dumps(ReplayReport())\n"
        "    raise SystemExit('json.dumps accepted ReplayReport')\n"
        "except TypeError as exc:\n"
        "    assert 'ReplayReport' in str(exc)\n"
        "body = json.loads(json.dumps(runner.clean(ReplayReport())))\n"
        "assert body['ok'] is False and 'violations' in body\n"
        "reason = module.completion_failure(ReplayReport(), None, {}, 0, None, [], [], [], {'budgets': []}, None)\n"
        "assert reason == 'result failed the completion checks'\n"
        "print('SERIALIZATION_PASS')\n"
        "print('BAD_RESULT_NOT_SUCCESS')\n"
    )
    env = base_env(Path(tempfile.mkdtemp(prefix="m49_serial_")))
    proc = subprocess.run([sys.executable, "-c", code, str(HERE / "fresh_actual.py")], env=env, capture_output=True, text=True)
    shutil.rmtree(env["M49_OUTPUT_ROOT"], ignore_errors=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] + proc.stdout[-2000:])
    print(proc.stdout.strip())


def test_worker_rejects_before_physical(kind):
    root = Path(tempfile.mkdtemp(prefix=f"m49_{kind}_"))
    try:
        def mutate(row):
            if kind == "witness":
                row["world_sha256"] = "0" * 64
            else:
                row["complete_input_fingerprint"] = "f" * 64
        registration = registration_copy(root, mutate)
        proc = run_worker(root, registration)
        assert proc.returncode != 0, proc.stdout + proc.stderr
        expected = "witness or nominal hash mismatch" if kind == "witness" else "scope fingerprint mismatch"
        assert expected in (proc.stderr + proc.stdout), proc.stderr[-2000:]
        assert not (root / "STUB_CALLS.json").exists()
        assert not list(root.rglob("*executions*"))
        print(f"{kind.upper()}_MISMATCH_BEFORE_PHYSICAL")
    finally:
        shutil.rmtree(root)


def test_checkpoint_scope_and_output(controller):
    stage = Path(tempfile.mkdtemp(prefix="m49_neg_"))
    calls = []
    try:
        shutil.copy(HERE / "FRESH_JOB_REGISTRATION.json", stage / "FRESH_JOB_REGISTRATION.json")
        jobs = json.loads((HERE / "FRESH_JOB_REGISTRATION.json").read_text())["jobs"]
        progress = stage / "FRESH_PROGRESS.json"
        progress.write_text(json.dumps({
            "active": [{"job": jobs[0], "pid": 424242}],
            "pending": jobs[1:],
            "completed": [],
            "failures": [],
        }))
        before = progress.read_bytes()
        try:
            controller.serve(stage, lambda stage, job: calls.append(job))
            raise AssertionError("active checkpoint spawned")
        except controller.CheckpointActive:
            pass
        assert calls == []
        assert progress.read_bytes() == before
        assert hashlib.sha256(before).hexdigest() == sha256(progress)
        print("CHECKPOINT_SHA_UNCHANGED", hashlib.sha256(before).hexdigest())

        reg = json.loads((stage / "FRESH_JOB_REGISTRATION.json").read_text())
        for row in reg["logical_mapping"]:
            if row["logical_job"] == JOB:
                row["world_sha256"] = "0" * 64
        (stage / "FRESH_JOB_REGISTRATION.json").write_text(json.dumps(reg))
        before = progress.read_bytes()
        try:
            controller.serve(stage, lambda stage, job: calls.append(job))
            raise AssertionError("scope mismatch spawned")
        except SystemExit as exc:
            assert str(exc) == "scope mismatch"
        assert calls == []
        assert progress.read_bytes() == before
        print("SCOPE_WITNESS_MISMATCH_BEFORE_SPAWN")

        shutil.copy(HERE / "FRESH_JOB_REGISTRATION.json", stage / "FRESH_JOB_REGISTRATION.json")
        progress.unlink()
        job = tuple(JOB)
        path = controller.exclusive_outputs(stage, job)[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"keep": true}\n')
        before = path.read_bytes()
        try:
            controller.serve(stage, lambda stage, job: calls.append(job))
            raise AssertionError("existing output spawned")
        except SystemExit as exc:
            assert "output already exists" in str(exc)
        assert path.read_bytes() == before
        assert calls == []
        print("EXISTING_OUTPUT_NOT_OVERWRITTEN")
    finally:
        shutil.rmtree(stage)


def test_cold_controller_chain(controller):
    stage = Path(tempfile.mkdtemp(prefix="m49_stage_"))
    root = Path(tempfile.mkdtemp(prefix="m49_out_"))
    saved = {key: os.environ.get(key) for key in (
        "PYTHONPATH", "M49_LAUNCH_APPROVED", "M49_DRY_RUN", "M49_EVALUATE_STUB", "M49_OUTPUT_ROOT")}
    try:
        os.environ.pop("PYTHONPATH", None)
        os.environ["M49_LAUNCH_APPROVED"] = "parent-approved"
        os.environ["M49_DRY_RUN"] = "1"
        os.environ["M49_EVALUATE_STUB"] = "1"
        os.environ["M49_OUTPUT_ROOT"] = str(root)
        os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", PRIVATE)
        shutil.copy(HERE / "FRESH_JOB_REGISTRATION.json", stage / "FRESH_JOB_REGISTRATION.json")
        (stage / "FRESH_PROGRESS.json").write_text(json.dumps({
            "active": [], "pending": [JOB], "completed": [], "failures": [],
        }))
        try:
            controller.serve(stage, controller.popen_spawn)
            raise AssertionError("dry run exited as a successful batch")
        except SystemExit as exc:
            assert str(exc) == "worker failed", str(exc)
        tag = "_".join(map(str, JOB))
        log = (stage / "worker_logs" / f"{tag}.log").read_text()
        assert "result failed the completion checks" in log, log[-2000:]
        ledger = json.loads((stage / "STAGE_LEDGER.json").read_text())
        assert ledger["completed_jobs"] == 0 and ledger["failed_jobs"] == 1
        assert ledger["publishable"] is False
        pid = ledger["failed"][0]["pid"]
        assert not Path(f"/proc/{pid}").exists()
        counters = json.loads((root / "DRY_RUN_COUNTERS.json").read_text())
        assert counters["real_evaluate_body"] == 0
        assert counters["stub_reasons"]
        execution = root / "M49_REORDER" / "executions" / "own" / "dev" / "C50_1001_S.json"
        body = json.loads(execution.read_text())
        assert body["record_class"] == "TEST" and body["test_only"] is True
        assert body["row"]["publishable"] is False and body["row"]["paid"] is None
        assert body["row"]["calls_is_not_stage_total"] is True
        account = body["row"]["stage_account"]
        assert body["row"]["calls"] == account["episode"]
        assert account["stage_total_accepted"] == account["startup"] + account["episode"]
        assert account["stage_total_accepted"] != body["row"]["calls"]
        assert "flags" not in body
        text = execution.read_text()
        assert "601.3641210199783" not in text and "563.5086337141618" not in text
        identity = json.loads((root / "M49_REORDER" / "startup_identity" / "own" / "dev" / "C50_1001_S.json").read_text())
        assert identity["runner_path"].endswith("source/round10_recheck/run_emin005.py")
        assert identity["record_class"] == "TEST"
        print("COLD_CHAIN_EXIT_NONZERO")
        print("STUB_REASONS", ",".join(counters["stub_reasons"]))
        print("REAL_EVALUATE_BODY", counters["real_evaluate_body"])
        print("SCHEDULE_PLAN_CALLS", counters["schedule_plan"])
        print("STAGE_ACCOUNT", json.dumps(account, sort_keys=True))
        print("NO_RESIDUAL_PID", pid)
        print("TEST_OUTPUT_REMOVED_AFTER_READ")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def main():
    assert not os.environ.get("M49_LAUNCH_APPROVED")
    freeze = sha256(CORE / "EXPERIMENT_CORE_FREEZE.json")
    assert freeze == "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"
    print("CORE_FREEZE", freeze)
    test_runner_binding()
    test_serialization_and_bad_result()
    test_worker_rejects_before_physical("witness")
    test_worker_rejects_before_physical("scope")
    controller = load_controller()
    test_checkpoint_scope_and_output(controller)
    before = {path.relative_to(HERE).as_posix() for path in HERE.rglob("*") if path.is_file()}
    test_cold_controller_chain(controller)
    after = {path.relative_to(HERE).as_posix() for path in HERE.rglob("*") if path.is_file()}
    assert before == after
    assert os.environ.get("M49_LAUNCH_APPROVED") in (None, "")
    print("COLD_ENTRY_PASS", "native_evaluate_body", 0, "launch_allowed", False)


if __name__ == "__main__":
    main()
