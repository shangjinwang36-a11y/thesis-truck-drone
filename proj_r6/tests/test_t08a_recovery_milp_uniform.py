"""T08a-5b：恢复初始化的 MILP 候选数与能量预筛对 S/R/X 相同（T03 定案：top_k=10，预筛关闭）。"""
import ast
from pathlib import Path

from tdr.config import AlgorithmConfig

SRC = Path(__file__).resolve().parents[1] / "src" / "tdr" / "simulate.py"


def _kw():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "initial_recovery":
            return {k.arg: ast.get_source_segment(SRC.read_text(encoding="utf-8"), k.value) for k in node.keywords}
    raise AssertionError("initial_recovery call not found")


def test_defaults():
    a = AlgorithmConfig()
    assert a.recovery_milp_top_k == 10 and a.recovery_energy_screen is False


def test_no_strategy_branch_in_milp_and_screen():
    kw = _kw()
    for name in ("milp_top_k", "energy_screen"):
        assert "strategy" not in kw[name], kw[name]
