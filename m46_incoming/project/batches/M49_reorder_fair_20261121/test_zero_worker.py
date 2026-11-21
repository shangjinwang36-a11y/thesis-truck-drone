"""Five checks. None of them spawn a worker or call evaluate_plan."""
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent / "run_actual.py"
REAL_STATE = Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_20261121/state.json")


def load():
    spec = importlib.util.spec_from_file_location("m49_controller", SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_before_worker(module, stage):
    state = module.ensure_state(stage)
    assert (stage / "state.json").is_file()
    assert state["active_processes"] == []
    assert state["actual_execution_started"] is False
    assert state["optimizer_running"] is False


def test_resume_blocks(module, stage):
    job = ("M49_REORDER", "RC100", "X", "dev", 1001, "own")
    (stage / "FRESH_PROGRESS.json").write_text(json.dumps({"active": [{"job": list(job)}], "completed": [], "failures": []}))
    pending, _completed, _failed, blocked = module.restore(stage, [job])
    assert blocked is True
    assert len(pending) == 0


def test_path_conflict_keeps_the_file(module, stage):
    job = ("M49_REORDER", "RC100", "X", "dev", 1001, "own")
    path = module.exclusive_outputs(stage, job)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    try:
        module.refuse_existing_output(stage, [job])
        raise AssertionError("conflict was not raised")
    except SystemExit as exc:
        assert "output already exists" in str(exc)
    assert path.is_file()


def test_no_residue(stage, before):
    shutil.rmtree(stage)
    assert not stage.exists()
    after = hashlib.sha256(REAL_STATE.read_bytes()).hexdigest() if REAL_STATE.is_file() else None
    assert before == after


def test_main_does_not_spawn_and_core_matches(module):
    assert module.core_members_match()
    try:
        module.main()
        raise AssertionError("main returned")
    except SystemExit as exc:
        assert str(exc) == "not launched"


def main():
    module = load()
    before = hashlib.sha256(REAL_STATE.read_bytes()).hexdigest() if REAL_STATE.is_file() else None
    stage = Path(tempfile.mkdtemp(prefix="m49_five_"))
    test_state_before_worker(module, stage)
    test_resume_blocks(module, stage)
    test_path_conflict_keeps_the_file(module, stage)
    test_no_residue(stage, before)
    test_main_does_not_spawn_and_core_matches(module)
    print("ZERO_WORKER_FIVE_PASS", "native_evaluations", 0)


if __name__ == "__main__":
    main()
