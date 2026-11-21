"""Seal the two-cell first-recovery scope. This file does not evaluate.

Running it checks hashes and the inherited budget stages, then exits.
It has no approval switch and it does not call initial_recovery or optimize.
"""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M49_landed_wait_core_20261121"
REG = json.loads((HERE / "BUDGET_REGISTRATION.json").read_text())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check():
    freeze = CORE / "EXPERIMENT_CORE_FREEZE.json"
    if sha256(freeze) != REG["core_freeze_sha256"]:
        raise SystemExit("core freeze mismatch")
    core = json.loads(freeze.read_text())
    if len(core) != 147 or any(sha256(CORE / name) != digest for name, digest in core.items()):
        raise SystemExit("core member mismatch")
    if sha256(CORE / "source/proj_r6/src/tdr/simulate.py") != REG["simulate_sha256_m48_and_39a85"]:
        raise SystemExit("simulate.py is not the sealed budget caller")
    if sha256(CORE / "source/proj_r6/src/tdr/recovery.py") != REG["sealed_recovery_sha256"]:
        raise SystemExit("sealed recovery changed")
    if sha256(HERE / "recovery.py") != REG["candidate_recovery_sha256"]:
        raise SystemExit("candidate recovery changed")
    index = json.loads((HERE / "visible_inputs/INDEX.json").read_text())
    if set(index) != set(REG["cells"]):
        raise SystemExit("visible inputs are not the two registered cells")
    for job, row in index.items():
        if not row["input_bytes_identical"] or not row["ids_not_in_package"]:
            raise SystemExit("visible input identity mismatch " + job)
    stages = {item["name"]: item for item in REG["stages"]}
    if stages["INIT_BASE"]["amount"] != 100 or stages["MAIN"]["amount"] != 1000:
        raise SystemExit("base budgets are not INIT 100 and MAIN 1000")
    if stages["INIT_FALLBACK"]["amount"] != 24 or stages["INIT_JOINT"]["amount"] != 60 or stages["INIT_LAND_EXTRA"]["amount"] != 120:
        raise SystemExit("inherited init extensions changed")
    if stages["MAIN"]["budget_object"] == "init" or stages["INIT_RESCUE"]["budget_object"] != "init":
        raise SystemExit("main and init budgets are mixed")
    return dict(status="SEALED_NOT_RUN", cells=list(index), stages=[item["name"] for item in REG["stages"]])


def main():
    print(json.dumps(check()))


if __name__ == "__main__":
    main()
