"""T08a-6: initialization and optimization share one recovery hard cap."""
import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tdr import recovery, simulate
from tdr.alns import Budget
from tdr.hidden_world import TestWorld
from test_round1 import env  # Shared deterministic nominal fixture.

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "tdr"


def _tree(path):
    # AST parsing ignores comments; remove docstrings as well.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return tree


@pytest.mark.parametrize("name", ["recovery", "recovery_milp", "hybrid", "simulate", "alns"])
def test_recovery_paths_never_increase_eval_limit(name):
    tree = _tree(SRC / (name + ".py"))
    # Stronger than banning +=: the only allowed write is Budget's constructor.
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
              and n.attr == "eval_limit" and isinstance(n.ctx, ast.Store)]
    if name == "alns":
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Budget")
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        assignment = next(n for n in init.body if isinstance(n, ast.Assign)
                          and any(t in writes for t in n.targets))
        assert ast.unparse(assignment) == "self.eval_limit = eval_limit"
        assert writes == assignment.targets
    else:
        assert not writes


def test_extra_eval_constants_removed():
    for name in ("JOINT_EXTRA_EVALS", "LAND_EXTRA_EVALS"):
        assert not hasattr(recovery, name)
        assert name not in ast.unparse(_tree(SRC / "recovery.py"))


def test_budget_allocation_uses_remaining_cap_without_strategy_branches():
    tree = _tree(SRC / "simulate.py")
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_episode")
    loop = next(n for n in run.body if isinstance(n, ast.While))
    parents = {child: parent for parent in ast.walk(run) for child in ast.iter_child_nodes(parent)}
    allocations = {}
    for node in ast.walk(run):
        if not isinstance(node, ast.Assign):
            continue
        target = ast.unparse(node.targets[0])
        if target in {"main_limit", "recovery_budget", "init_budget", "recovery_budget.used",
                      "main_budget_limit", "budget"}:
            allocations[target] = node.value
            assert parents[node] is loop, "budget allocation must not be strategy-conditional"
            assert "strategy" not in ast.unparse(node.value)
    assert ast.unparse(allocations["main_limit"]) == (
        "recovery_eval_budget if recovery_eval_budget is not None else alg.deterministic_recovery_eval_budget")
    assert ast.unparse(allocations["recovery_budget"].args[0]) == "main_limit"
    assert ast.unparse(allocations["init_budget"].args[0]) == "min(alg.recovery_init_eval_budget, main_limit)"
    assert ast.unparse(allocations["recovery_budget.used"]) == "init_budget.used"
    assert ast.unparse(allocations["main_budget_limit"]) == "max(0, main_limit - recovery_budget.used)"
    assert ast.unparse(allocations["budget"].args[0]) == "main_budget_limit"


def test_joint_retarget_returns_without_work_when_budget_exhausted(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("exhausted joint search must not construct candidates")

    monkeypatch.setattr(recovery, "build_residual_candidate", unexpected)
    budget = Budget(1, None, used=1)
    info = {}
    assert recovery._joint_retarget(None, None, None, None, None, None, set(), "X",
                                    None, budget, [], info, unexpected, 1) is False
    assert budget.eval_limit == budget.used == 1
    assert not info.get("joint_used")


@pytest.mark.parametrize("strategy", ["S", "R", "X"])
@pytest.mark.parametrize("hard_cap,init_limit,wall_limit", [
    (0, 100, None), (1, 100, None), (50, 100, None), (150, 10, None), (150, 100, 0.0),
])
def test_episode_cap_and_audit(env, strategy, hard_cap, init_limit, wall_limit):
    inst, phys, alg, nominal, H, target = env
    alg = replace(alg, recovery_init_eval_budget=init_limit)
    ep = simulate.run_episode(
        inst, nominal.plan, nominal.evaluation, H, phys, TestWorld(inst, "C50", (target,)),
        strategy, alg, simulate.derive_rngs(alg.base_algorithm_seed, "C50", "recovery", 0),
        recovery_eval_budget=hard_cap, recovery_wall_s=wall_limit,
    )
    assert ep.replans[1:], ep.notes
    for rec in ep.replans[1:]:
        s = rec.stats
        assert s["recovery_hard_cap"] == hard_cap
        assert s["init_budget_limit"] == min(init_limit, hard_cap)
        assert s["init_budget_used"] == s["n_init_evals"] <= min(init_limit, hard_cap)
        assert s["main_budget_limit"] == hard_cap - s["init_budget_used"]
        assert s["n_main_evals"] <= s["main_budget_limit"]
        assert s["n_eval_requests"] == s["n_init_evals"] + s["n_main_evals"] <= hard_cap
        assert s["wall_cap_armed"] is (wall_limit is not None)
        assert s["wall_cap_hit"] is (wall_limit == 0.0)
        assert s["replan_wall_s"] >= 0
        assert isinstance(s["init_joint_used"], bool)
        assert isinstance(s["init_fallback_used"], bool)
    if hard_cap == 0 or wall_limit == 0.0:
        assert ep.status == "STOPPED_NO_FEASIBLE_SUFFIX"
        assert ep.replans[-1].stats["n_eval_requests"] == 0


def test_episode_budget_audit_aggregation():
    # Load the pure helper without the experiment runner's import-time chdir.
    tree = _tree(ROOT / "r6" / "run_round2.py")
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_budget_audit")
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "run_round2.py", "exec"), namespace)
    audit = namespace["_budget_audit"]
    assert audit([]) == dict(wall_cap_armed=False, n_wall_cap_hits=0, n_replans_over_60s=0,
                            max_replan_wall_s=0.0, init_evals_used=0, n_init_joint=0,
                            n_init_rescue_would_trigger=0, n_init_fallback=0, max_recovery_evals=0)
    records = [SimpleNamespace(stats=s) for s in [
        dict(wall_cap_armed=True, wall_cap_hit=True, replan_wall_s=61.0, init_budget_used=10,
             init_joint_used=True, init_rescue_used=True, init_fallback_used=True, n_eval_requests=90),
        dict(wall_cap_armed=False, wall_cap_hit=False, replan_wall_s=60.0, init_budget_used=20,
             init_joint_used=True, init_rescue_used=False, init_fallback_used=True, n_eval_requests=100),
        {},
    ]]
    assert audit(records) == dict(wall_cap_armed=True, n_wall_cap_hits=1, n_replans_over_60s=1,
                                 max_replan_wall_s=61.0, init_evals_used=30, n_init_joint=2,
                                 n_init_rescue_would_trigger=1, n_init_fallback=2, max_recovery_evals=100)


@pytest.mark.parametrize("name", ["recovery.py", "simulate.py"])
def test_preserve_crlf(name):
    raw = (SRC / name).read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
