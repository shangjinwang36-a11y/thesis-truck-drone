"""Drive the real serve() branch. The spawn replacement does not evaluate."""
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.pop("M49_LAUNCH_APPROVED", None)
os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zero_spawn(stage, job, calls):
    state = json.loads((Path(stage) / "state.json").read_text())
    assert state["stage"] == "M49_REORDER"
    assert "evaluate_plan" not in Path(HERE / "run_actual.py").read_text()
    calls.append(tuple(job))

    class Proc:
        pid = 0

        def poll(self):
            return 0

    class Log:
        def close(self):
            return None

    return Proc(), Log(), job


def stage_with_registration():
    stage = Path(tempfile.mkdtemp(prefix="m49_serve_"))
    shutil.copy(HERE / "FRESH_JOB_REGISTRATION.json", stage / "FRESH_JOB_REGISTRATION.json")
    return stage


def test_serve_writes_state_before_zero_spawn(controller):
    stage = stage_with_registration()
    calls = []
    try:
        controller.serve(stage, lambda stage, job: zero_spawn(stage, job, calls))
        assert len(calls) == 36
        assert not (stage / "M49_REORDER").exists()
    finally:
        shutil.rmtree(stage)


def test_active_resume_does_not_spawn(controller):
    stage = stage_with_registration()
    jobs = json.loads((HERE / "FRESH_JOB_REGISTRATION.json").read_text())["jobs"]
    body = json.dumps({
        "active": [{"job": jobs[0], "pid": 424242}],
        "pending": jobs[1:],
        "completed": [],
        "failures": [],
    })
    path = stage / "FRESH_PROGRESS.json"
    path.write_text(body)
    before = path.read_bytes()
    calls = []
    try:
        try:
            controller.serve(stage, lambda stage, job: zero_spawn(stage, job, calls))
            raise AssertionError("resume spawned")
        except controller.CheckpointActive:
            pass
        assert calls == []
        assert path.read_bytes() == before
        saved = json.loads(path.read_text())
        assert saved["active"] == [{"job": jobs[0], "pid": 424242}]
        assert saved["pending"] == jobs[1:]
        assert len(saved["pending"]) == 35
    finally:
        shutil.rmtree(stage)


def test_existing_output_is_not_overwritten(controller):
    stage = stage_with_registration()
    job = tuple(json.loads((HERE / "FRESH_JOB_REGISTRATION.json").read_text())["jobs"][0])
    path = controller.exclusive_outputs(stage, job)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"keep": true}\n')
    calls = []
    try:
        try:
            controller.serve(stage, lambda stage, job: zero_spawn(stage, job, calls))
            raise AssertionError("conflict spawned")
        except SystemExit as exc:
            assert "output already exists" in str(exc)
        assert json.loads(path.read_text()) == {"keep": True}
        assert calls == []
    finally:
        shutil.rmtree(stage)


def test_controller_file_is_not_the_m47_module(worker):
    controller = worker.load_controller()
    assert Path(controller.__file__).resolve() == (HERE / "run_actual.py").resolve()
    m47 = HERE.parent / "M47_bounded_actual_20261121" / "run_actual.py"
    if m47.is_file():
        assert Path(controller.__file__).resolve() != m47.resolve()


def test_unapproved_spawn_and_shift_do_not_evaluate(controller, worker):
    stage = stage_with_registration()
    try:
        try:
            controller.popen_spawn(stage, ("M49_REORDER", "C50", "S", "dev", 1001, "own"))
            raise AssertionError("popen returned")
        except SystemExit as exc:
            assert str(exc) == "not launched"
        assert not (stage / "worker_logs").exists()
        try:
            worker.shift(("M49_REORDER", "C50", "S", "dev", 1001, "own"))
            raise AssertionError("shift returned")
        except SystemExit as exc:
            assert str(exc) == "not launched"
        assert "run_episode" in worker.execute_job.__code__.co_names
    finally:
        shutil.rmtree(stage)


def main():
    controller = load("m49_reorder_controller", "run_actual.py")
    worker = load("m49_reorder_worker", "fresh_actual.py")
    assert controller.REQUIRED_FREEZE == "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"
    assert controller.scope_ok(HERE)
    test_serve_writes_state_before_zero_spawn(controller)
    test_active_resume_does_not_spawn(controller)
    test_existing_output_is_not_overwritten(controller)
    test_controller_file_is_not_the_m47_module(worker)
    test_unapproved_spawn_and_shift_do_not_evaluate(controller, worker)
    assert not (HERE / "state.json").exists()
    assert not (HERE / "M49_REORDER").exists()
    print("ZERO_WORKER_FIVE_PASS", "native_evaluations", 0)


if __name__ == "__main__":
    main()
