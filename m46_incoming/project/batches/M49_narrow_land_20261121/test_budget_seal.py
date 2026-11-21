"""No-physical seal of the conditional scope. Does not call evaluate_plan."""
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_driver_has_no_evaluator_call():
    tree = ast.parse((HERE / "conditional_first_recovery.py").read_text())
    calls = [node.func.id if isinstance(node.func, ast.Name) else "" for node in ast.walk(tree) if isinstance(node, ast.Call)]
    for banned in ("evaluate_plan", "initial_recovery", "optimize", "run_episode"):
        assert banned not in calls


def test_redacted_inputs_hide_ids():
    for path in (HERE / "visible_inputs").glob("*_INPUT_REDACTED.json"):
        doc = json.loads(path.read_text())
        for key in ("true_greq", "artificial_greq", "effective_greq"):
            assert doc[key]["ids_withheld"] is True
            assert "count" in doc[key] and "sha256" in doc[key]
            assert not isinstance(doc[key], list)


def test_rng_matches_sealed_derive():
    os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    sys.path[:0] = [
        str(CORE / "source/proj_r6/src"),
        str(CORE / "source/round10_recheck"),
        str(CORE),
        str(HERE.parent / "M47_bounded_actual_20261121"),
    ]
    from tdr.simulate import derive_rngs
    reg = json.loads((HERE / "BUDGET_REGISTRATION.json").read_text())
    for case, expected in reg["rng"]["state_sha256"].items():
        rngs = derive_rngs(20261111, case, "recovery", 1)
        for name, digest in expected.items():
            assert hashlib.sha256(str(rngs[name].getstate()).encode()).hexdigest() == digest


def test_driver_exits_without_running():
    proc = subprocess.run([sys.executable, str(HERE / "conditional_first_recovery.py")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["status"] == "SEALED_NOT_RUN"
    assert body["stages"] == ["INIT_BASE", "INIT_RESCUE", "INIT_FALLBACK", "INIT_JOINT", "INIT_LAND_EXTRA", "MAIN"]
    assert sha256(CORE / "source/proj_r6/src/tdr/recovery.py") == "54c730fff2b5185c2400aa30d0df751af6564b80833b67ce89c6821c7916ab3d"


def main():
    test_driver_has_no_evaluator_call()
    test_redacted_inputs_hide_ids()
    test_rng_matches_sealed_derive()
    test_driver_exits_without_running()
    print("BUDGET_SEAL_PASS", "native_evaluations", 0)


if __name__ == "__main__":
    main()
