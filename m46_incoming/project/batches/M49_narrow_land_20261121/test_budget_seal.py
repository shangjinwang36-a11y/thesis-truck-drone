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


def test_launch_is_gated_and_uses_the_original_entry():
    tree = ast.parse((HERE / "conditional_first_recovery.py").read_text())
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    main_calls = [node.func.id for node in ast.walk(functions["main"]) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert "launch" not in main_calls or "approved" in (HERE / "conditional_first_recovery.py").read_text()
    launch_calls = [node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                    for node in ast.walk(functions["launch"]) if isinstance(node, ast.Call)]
    assert "initial_recovery" in launch_calls
    assert "optimize" in launch_calls
    text = (HERE / "recovery.py").read_text()
    simulate = (CORE / "source/proj_r6/src/tdr/simulate.py").read_text()
    assert "budget.extend(rescue_evals)" in text
    assert "budget.extend(24)" in text
    assert "JOINT_EXTRA_EVALS = 60" in text
    assert "LAND_EXTRA_EVALS = 120" in text
    assert "rescue_evals=main_limit" in simulate
    assert "budget = Budget(main_limit, recovery_wall_s, start=t_budget0)" in simulate
    assert sha256(HERE / "recovery.py") == "5a3882b7866e8b6b286480eaa3403876902c40257ec6b37dd7adbe5007c91694"


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
    env = os.environ.copy()
    env.pop("M49_CONDITIONAL_APPROVED", None)
    env.pop("M49_CONDITIONAL_OUTPUT", None)
    proc = subprocess.run([sys.executable, str(HERE / "conditional_first_recovery.py")], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["status"] == "NOT_LAUNCHED"
    assert body["cells"] == ["RC100_1002_X", "R100_1002_S"]
    assert not (HERE / "conditional_runs").exists()
    assert sha256(CORE / "source/proj_r6/src/tdr/recovery.py") == "54c730fff2b5185c2400aa30d0df751af6564b80833b67ce89c6821c7916ab3d"


def test_existing_output_is_refused_before_launch():
    import tempfile
    env = os.environ.copy()
    env.pop("M49_CONDITIONAL_APPROVED", None)
    folder = tempfile.mkdtemp(prefix="m49_cond_out_")
    (Path(folder) / "already").write_text("x")
    env["M49_CONDITIONAL_OUTPUT"] = folder
    proc = subprocess.run([sys.executable, str(HERE / "conditional_first_recovery.py")], capture_output=True, text=True, env=env)
    assert proc.returncode != 0
    assert "output already exists" in (proc.stderr + proc.stdout)


def test_budget_object_extend_is_not_a_second_main():
    os.environ.setdefault("M47_PRIVATE_EXEC_ROOT", "/home/ubuntu/m47_private_exec")
    sys.path.insert(0, str(CORE / "source/proj_r6/src"))
    from tdr.alns import Budget
    init = Budget(100, None)
    assert init.eval_limit == 100
    init.extend(24)
    init.extend(60)
    init.extend(120)
    init.extend(1000)
    assert init.eval_limit == 1304
    main = Budget(1000, None)
    assert main is not init
    assert main.eval_limit == 1000 and init.used == 0


def test_semantic_pin_is_m49_not_m48_bytes():
    report = json.loads((HERE / "SEMANTIC_INPUT.json").read_text())
    pin = json.loads((HERE / "PINNED_M49_CUT.json").read_text())
    assert pin["source"] == "M49_finished_first_recovery"
    for item in report["jobs"]:
        assert item["semantic_equal"] is True
        assert item["byte_identical"] is False
        assert item["pinned_for_the_conditional"] == "M49"
        assert pin["cells"][item["job"]]["byte_sha256"] == item["m49_byte_sha256"]
        assert pin["cells"][item["job"]]["treat_as_m48_input"] is False


def main():
    test_launch_is_gated_and_uses_the_original_entry()
    test_redacted_inputs_hide_ids()
    test_rng_matches_sealed_derive()
    test_driver_exits_without_running()
    test_existing_output_is_refused_before_launch()
    test_budget_object_extend_is_not_a_second_main()
    test_semantic_pin_is_m49_not_m48_bytes()
    print("BUDGET_SEAL_PASS", "native_evaluations", 0)


if __name__ == "__main__":
    main()
