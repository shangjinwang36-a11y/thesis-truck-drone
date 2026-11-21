"""Zero-worker checks for the M44 same-recovery controller."""
from pathlib import Path
import json
import tempfile
import unittest

import run_actual

JOB = ["M48_M44_NOMINAL", "C100", "X", "dev", 1001, "own"]


class FakeLog:
    def close(self):
        return None


class FakeProc:
    def __init__(self):
        self.pid = 424242424
        self.returncode = 0

    def poll(self):
        return 0


def write_reg(stage, jobs):
    (stage / "FRESH_JOB_REGISTRATION.json").write_text(json.dumps(dict(jobs=jobs)))


def noop(*args):
    return None


class ControllerTests(unittest.TestCase):
    def test_missing_state_is_created_before_any_spawn(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            write_reg(stage, [])
            calls = []
            state = run_actual.serve(stage, lambda stage, job: calls.append(job), check=noop)
            self.assertEqual(calls, [])
            self.assertEqual(state["phase"], "M48_M44_ready")
            self.assertFalse(state["actual_execution_started"])
            self.assertTrue((stage / "state.json").is_file())

    def test_existing_state_keeps_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            write_reg(stage, [])
            run_actual.dump(stage / "state.json", dict(note="keep-me", extra=[1]))
            state = run_actual.serve(stage, lambda stage, job: (_ for _ in ()).throw(AssertionError("spawn")), check=noop)
            self.assertEqual(state["note"], "keep-me")
            self.assertEqual(state["stage"], "M48_M44")

    def test_active_checkpoint_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            write_reg(stage, [JOB])
            run_actual.dump(stage / "state.json", dict(note="keep-me"))
            run_actual.dump(stage / "FRESH_PROGRESS.json", dict(completed=[], failures=[], active=[dict(job=JOB)]))
            before = (stage / "FRESH_PROGRESS.json").read_bytes()
            calls = []
            with self.assertRaises(run_actual.CheckpointActive):
                run_actual.serve(stage, lambda stage, job: calls.append(job), check=noop)
            self.assertEqual(calls, [])
            self.assertEqual((stage / "FRESH_PROGRESS.json").read_bytes(), before)

    def test_existing_output_is_a_path_error_before_spawn(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            write_reg(stage, [JOB])
            path = run_actual.exclusive_outputs(stage, tuple(JOB))[0]
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            calls = []
            with self.assertRaises(SystemExit):
                run_actual.serve(stage, lambda stage, job: calls.append(job), check=lambda stage, reg, pending: run_actual.refuse_existing_output(stage, pending))
            self.assertEqual(calls, [])

    def test_spawn_sees_saved_state_and_leaves_no_worker(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            write_reg(stage, [JOB])
            seen = {}

            def spawn(stage, job):
                seen["state"] = json.loads((stage / "state.json").read_text())
                return FakeProc(), FakeLog()

            state = run_actual.serve(stage, spawn, check=noop)
            self.assertEqual(seen["state"]["active_processes"], [])
            self.assertEqual(state["actual_completed"], 1)
            self.assertEqual(state["active_processes"], [])
            text = Path(run_actual.__file__).read_text()
            self.assertNotIn("M41_", text)
            self.assertNotIn("M38_", text)


if __name__ == "__main__":
    unittest.main()
