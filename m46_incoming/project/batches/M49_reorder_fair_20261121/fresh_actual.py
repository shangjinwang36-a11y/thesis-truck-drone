"""M49 worker. The default is refusal. Importing this file does not evaluate."""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent / "M49_landed_wait_core_20261121"
M47_BATCH = HERE.parent / "M47_bounded_actual_20261121"
LAUNCH_ENV = "M49_LAUNCH_APPROVED"
REQUIRED_FREEZE = "39a85da8c9b63d785754cdee4c3e596827e2b9986d32ed37480cab20306c8363"
sys.path.insert(0, str(M47_BATCH))
sys.path.insert(0, str(SOURCE_ROOT))


def approved() -> bool:
    return os.environ.get(LAUNCH_ENV) == "parent-approved"


def freeze_sha256() -> str:
    return hashlib.sha256((SOURCE_ROOT / "EXPERIMENT_CORE_FREEZE.json").read_bytes()).hexdigest()


def nominal_role(arm: str) -> str:
    if arm not in "SRX":
        raise SystemExit("arm is not S, R, or X")
    return "X" if arm == "X" else "S"


def recovery_policy(arm: str) -> str:
    """S stays the strong policy. R is the S nominal with the X recovery policy. The core is shared."""
    if arm == "S":
        return "S"
    if arm in ("R", "X"):
        return "X"
    raise SystemExit("arm is not S, R, or X")


def shift(job):
    if not approved():
        raise SystemExit("not launched")
    raise SystemExit("registration is not approved for launch")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        shift(tuple(json.loads(sys.argv[2])))
        return
    from run_actual import main as control
    control()


if __name__ == "__main__":
    main()
