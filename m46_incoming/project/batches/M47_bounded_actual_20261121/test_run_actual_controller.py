"""Zero-worker controller checks. No episode, no private world is opened."""
from pathlib import Path
import json
import tempfile
import unittest

import run_actual


JOB = ["M47_CANDIDATE", "C50", "S", "dev", 1001, "own"]


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
    def test_save_without_state_still_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            with self.assertRaises(FileNotFoundError):
                run_actual.save(stage, None, [], [], [], [], False, False, False)

    def test_missing_state_is_created_before_any_spawn(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            mirror = stage / "mirror"
            write_reg(stage, [])
            calls = []

            def spawn(stage, job):
                calls.append(job)
                raise AssertionError("spawned with an empty queue")

            state = run_actual.serve(stage, mirror, spawn, check=noop)
            self.assertEqual(calls, [])
            self.assertEqual(state["stage"], "M47")
            self.assertEqual(state["phase"], "M47_bounded_actual_ready")
            self.assertFalse(state["actual_execution_started"])
            self.assertEqual(state["active_processes"], [])
            self.assertTrue((stage / "state.json").is_file())

    def test_existing_state_keeps_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            mirror = stage / "mirror"
            write_reg(stage, [])
            run_actual.dump(stage / "state.json", dict(stage="OLD", phase="OLD", note="keep-me", extra=[1, 2]))
            state = run_actual.serve(stage, mirror, lambda stage, job: (_ for _ in ()).throw(AssertionError("spawn")), check=noop)
            self.assertEqual(state["note"], "keep-me")
            self.assertEqual(state["extra"], [1, 2])
            self.assertEqual(state["stage"], "M47")
            self.assertTrue(state["phase"].startswith("M47_"))

    def test_resume_checkpoint_does_not_spawn_or_rewrite_progress(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            mirror = stage / "mirror"
            write_reg(stage, [JOB])
            run_actual.dump(stage / "state.json", dict(note="keep-me", phase="OLD"))
            progress = dict(completed=[], failures=[], pending=[JOB], active=[dict(job=JOB, process=dict(pid=77))])
            run_actual.dump(stage / "FRESH_PROGRESS.json", progress)
            before = (stage / "FRESH_PROGRESS.json").read_bytes()
            calls = []
            with self.assertRaises(run_actual.CheckpointActive):
                run_actual.serve(stage, mirror, lambda stage, job: calls.append(job), check=noop)
            self.assertEqual(calls, [])
            self.assertEqual((stage / "FRESH_PROGRESS.json").read_bytes(), before)
            state = json.loads((stage / "state.json").read_text())
            self.assertEqual(state["note"], "keep-me")
            self.assertEqual(state["phase"], "M47_actual_blocked")
            self.assertEqual(state["active_processes"], [])

    def test_spawn_sees_saved_state_and_leaves_no_active_worker(self):
        with tempfile.TemporaryDirectory() as raw:
            stage = Path(raw)
            mirror = stage / "mirror"
            write_reg(stage, [JOB])
            seen = {}

            def spawn(stage, job):
                seen["state"] = json.loads((stage / "state.json").read_text())
                return FakeProc(), FakeLog()

            state = run_actual.serve(stage, mirror, spawn, check=noop)
            self.assertEqual(seen["state"]["phase"], "M47_bounded_actual_ready")
            self.assertFalse(seen["state"]["actual_execution_started"])
            self.assertEqual(seen["state"]["active_processes"], [])
            self.assertEqual(state["phase"], "M47_bounded_actual_complete_audit_pending")
            self.assertEqual(state["actual_completed"], 1)
            self.assertEqual(state["actual_failed"], 0)
            self.assertEqual(state["active_processes"], [])
            self.assertNotIn("M41_", (Path(run_actual.__file__).read_text()))


if __name__ == "__main__":
    unittest.main()
