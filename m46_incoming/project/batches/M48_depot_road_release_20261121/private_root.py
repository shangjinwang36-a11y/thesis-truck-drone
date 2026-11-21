"""Resolve recorded executor inputs. Never copy them into the git checkout."""
from pathlib import Path
import os


def private_root() -> Path:
    raw = os.environ.get("M47_PRIVATE_EXEC_ROOT", "")
    if not raw:
        raise SystemExit("M47_PRIVATE_EXEC_ROOT must point at the extracted executor-only tree outside the git checkout")
    root = Path(raw).resolve()
    git = Path("/workspace").resolve()
    try:
        root.relative_to(git)
    except ValueError:
        inside = False
    else:
        inside = True
    if inside or not root.is_dir():
        raise SystemExit("M47_PRIVATE_EXEC_ROOT is missing or lies inside the git checkout")
    return root


def witness(case: str, seed: int) -> Path:
    return private_root() / "project/batches/J2_historical_R10_integrated_repair_20261120/J2/executions/own/dev" / f"{case}_{seed}_S.json"


def m20_s(case: str) -> Path:
    return private_root() / "project/batches/M20_canonical_H_sixmap_20261121/preflight_fresh" / case / "S/nominal_plan.json"


def k1_execution(case: str, seed: int, arm: str) -> Path:
    return private_root() / "project/batches/K1_R10_S_warm_restore_20261120/K1/executions/own/dev" / f"{case}_{seed}_{arm}.json"
