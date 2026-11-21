"""Native-zero checks for the X-only detour cross.

The sealed M46 champions are the parents. The operator must not emit a plan
whose own J proxy is negative, must not drop air, and must not run for S.
"""
from pathlib import Path
import pickle
import random
import sys
import types

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
SEAL = HERE.parent / "M46_paid_training_robust_joint_20261121"
sys.path.insert(0, str(CORE))

from research import setup  # noqa: E402
from tdr.complete_joint import candidate_air_ok  # noqa: E402
from tdr.evaluation_audit import audit_evaluations  # noqa: E402
from tdr.joint_air_promote import air  # noqa: E402
from tdr.schedule_closed_exchange import KIND, geometries  # noqa: E402


CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]


def _parent(case):
    inst, phys, alg = setup(case, "M47", True)
    phys.set_active()
    _ci, _cp, plan, ev, state, ref = pickle.loads(
        (SEAL / f"fresh_new/{case}/X_live/normal_terminal_final.pkl").read_bytes())
    assert alg._nominal_reference_H == ref
    return inst, phys, alg, plan, ev, state, ref


def test_s_does_not_emit_and_air_loss_is_rejected():
    inst, phys, alg, plan, ev, state, ref = _parent("C50")
    state.nominal_cross = False
    ctx = types.SimpleNamespace(inst=inst, phys=phys, alg=alg, state=state, H=ref)
    diag = {}
    with audit_evaluations() as au:
        assert geometries(plan, ev, ctx, diag) == []
        assert diag["skip"] == "S_OR_NO_CROSS"
        assert au.summary()["accepted_calls"] == 0
    lost = plan.clone()
    next(iter(lost.sorties.values())).air.pop()
    assert not candidate_air_ok(plan, lost, {"kind": KIND, "parcels": ["x"]})
    same = plan.clone()
    assert not candidate_air_ok(plan, same, {"kind": KIND, "parcels": []})


def test_sealed_champions_have_no_proxy_positive_detour():
    with audit_evaluations() as au:
        for case in CASES:
            inst, phys, alg, plan, ev, state, ref = _parent(case)
            state.nominal_cross = True
            alg._mature_fullpool_air_sets = {tuple(sorted(air(plan)))}
            alg._schedule_closed_emitted = 0
            ctx = types.SimpleNamespace(inst=inst, phys=phys, alg=alg, state=state, H=ref)
            rng = random.getstate()
            parent_air = air(plan)
            diag = {}
            out = geometries(plan, ev, ctx, diag)
            assert out == []
            assert diag["emitted"] == 0
            assert diag["native_calls"] == 0
            gain = diag["best_proxy_j_gain"]
            assert gain is None or gain < 0
            assert air(plan) == parent_air
            assert random.getstate() == rng
        assert au.summary()["accepted_calls"] == 0
