"""Zero-evaluation check of the narrowed recovery. It does not call evaluate_plan."""
import ast
import hashlib
import importlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEALED_CORE = HERE.parent / "M49_landed_wait_core_20261121"
SEALED_RECOVERY = SEALED_CORE / "source/proj_r6/src/tdr/recovery.py"
NEW_RECOVERY = HERE / "recovery.py"
SEALED_HASH = "54c730fff2b5185c2400aa30d0df751af6564b80833b67ce89c6821c7916ab3d"
FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_sealed_core_untouched():
    assert sha256(SEALED_CORE / "EXPERIMENT_CORE_FREEZE.json") == FREEZE
    assert sha256(SEALED_RECOVERY) == SEALED_HASH
    freeze = (SEALED_CORE / "EXPERIMENT_CORE_FREEZE.json").read_text()
    assert SEALED_HASH in freeze


def test_patch_shape():
    text = NEW_RECOVERY.read_text()
    tree = ast.parse(text)
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_sync_recovery_truck" in names
    assert "_reorder_same_truck" not in names
    assert "_drive_meters" not in names
    assert "schedule_plan" not in text
    assert "sortie.landed = True" not in text
    assert "if phys.land_and_wait and f.started:" in text
    assert "f.landed = True" in text
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert "_reorder_same_truck" not in calls
    assert "_sync_recovery_truck" in calls


def test_truck_contract_on_the_patched_module():
    tmp = Path(tempfile.mkdtemp(prefix="m49_narrow_"))
    try:
        src = tmp / "src"
        shutil.copytree(SEALED_CORE / "source/proj_r6/src", src)
        shutil.copy(NEW_RECOVERY, src / "tdr/recovery.py")
        sys.path.insert(0, str(src))
        for name in list(sys.modules):
            if name == "tdr" or name.startswith("tdr."):
                del sys.modules[name]
        recovery = importlib.import_module("tdr.recovery")
        from tdr.plan import Visit
        plan = recovery.Plan("case")
        plan.visits[1] = Visit(1, "t1", "c1")
        plan.visits[2] = Visit(2, "t7", "c2")
        unstarted = recovery.Sortie(1, "d1", "t7", 1, "ARC", 0.0, ["p1"], 2)
        plan.sorties[1] = unstarted
        recovery._sync_recovery_truck(plan)
        assert unstarted.truck == "t1"
        assert unstarted.launch_truck == "t1"
        assert unstarted.landed is False
        started = recovery.Sortie(2, "d2", "t1", None, "AIR", 0.0, ["p2"], 2, started=True)
        plan.sorties[2] = started
        recovery._sync_recovery_truck(plan)
        assert started.truck == "t7"
        assert started.launch_truck == "t1"
        assert "evaluate_plan" not in recovery._sync_recovery_truck.__code__.co_names
    finally:
        shutil.rmtree(tmp)
        sys.path.pop(0)


def main():
    test_sealed_core_untouched()
    test_patch_shape()
    test_truck_contract_on_the_patched_module()
    assert sha256(SEALED_RECOVERY) == SEALED_HASH
    print("NARROW_LAND_ZERO_EVAL_PASS", "native_evaluations", 0)


if __name__ == "__main__":
    main()
