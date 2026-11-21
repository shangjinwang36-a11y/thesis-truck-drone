"""The started fragment lands when that action is already configured. No evaluator calls."""
from dataclasses import replace
import pickle
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "M49_landed_wait_core_20261121"
sys.path.insert(0, str(CORE / "source/proj_r6/src"))
sys.path.insert(0, str(CORE))
import json
from tdr.evaluate import recovery_is_cross
from tdr.experiment import plan_from_dict
from tdr.recovery import _advance_late_recovery, _reassign_overflow_tail, build_residual_candidate  # noqa: E402

PICKLE = Path("/workspace/m46_incoming/project/batches/M48_depot_road_release_20261121/M48_RECOVERY/observer/formal/own/dev/RC100_1001_X/009/VISIBLE_CONTEXT.pkl")


def load():
    inst, phys, alg, plan, state, greq, opts = pickle.load(open(PICKLE, "rb"))
    phys.set_active()
    return inst, phys, plan, state, set(greq), opts


def test_started_fragment_lands_only_when_configured():
    inst, phys, plan, state, greq, opts = load()
    assert phys.land_and_wait
    made = build_residual_candidate(plan, opts["frag_sid"], None, inst, phys, state, greq, "X")
    assert made
    assert made[0].sorties[opts["frag_sid"]].landed
    assert made[0].sorties[opts["frag_sid"]].started
    off = replace(phys, land_and_wait=False)
    plain = build_residual_candidate(plan, opts["frag_sid"], None, inst, off, state, greq, "S")
    assert plain
    assert not plain[0].sorties[opts["frag_sid"]].landed


def test_unstarted_sortie_lands_only_when_configured():
    inst, phys, plan, state, greq, opts = load()
    made = build_residual_candidate(plan, opts["frag_sid"], None, inst, phys, state, greq, "X")
    made_s = build_residual_candidate(plan, opts["frag_sid"], None, inst, phys, state, greq, "S")
    assert made and made_s
    assert all(s.landed for s in made[0].sorties.values())
    assert all(s.landed for s in made_s[0].sorties.values())
    off = replace(phys, land_and_wait=False)
    before = {sid: sortie.landed for sid, sortie in plan.sorties.items()}
    plain = build_residual_candidate(plan, opts["frag_sid"], None, inst, off, state, greq, "S")
    assert plain
    for sid, sortie in plain[0].sorties.items():
        if sid in before:
            assert sortie.landed == before[sid]
        else:
            assert not sortie.landed


def test_same_truck_recovery_advance_is_shared_and_ground_holder_blocks_both():
    inst, phys, _plan, state, _greq, opts = load()
    raw = json.loads(next(open(
        "/workspace/m46_incoming/project/batches/M49_landed_wait_20261121/paid_rehome/RC100_1001/RAW.jsonl")))
    plan = plan_from_dict(raw["plan"])
    plan._horizon_limit = opts["H"]
    shared = _advance_late_recovery(plan, inst, phys, state, "t7", "S")
    cross = _advance_late_recovery(plan, inst, phys, state, "t7", "X")
    assert shared is not None and cross is not None
    assert shared.sorties[214].rec_vid == cross.sorties[214].rec_vid
    assert shared.visits[shared.sorties[214].rec_vid].truck == "t7"
    assert shared.visits[shared.sorties[214].rec_vid].customer == "c009"
    for strategy_plan in (shared, cross):
        for visit in strategy_plan.visits.values():
            if "p047" in visit.ground:
                assert visit.truck == "t7"
                assert visit.customer == "c047"
    # S does not move the recovery onto another truck. X may.
    assert shared.sorties[380].truck == "t7"
    for strategy in ("S", "X"):
        moved = _reassign_overflow_tail(plan, inst, phys, state, "t7", strategy)
        if moved is None:
            continue
        for visit in moved.visits.values():
            if "p047" in visit.ground:
                assert visit.truck == "t7"
                assert visit.customer == "c047"


def test_saved_sid130_metadata_is_not_a_cross_recovery():
    plan = plan_from_dict(json.loads(Path(
        "/workspace/m46_incoming/project/batches/M49_landed_wait_20261121/paid_rehome/RC100_1002/SELECTED_PLAN.json"
    ).read_text()))
    sortie = plan.sorties[130]
    assert sortie.truck == "t2"
    assert sortie.launch_truck == "t7"
    assert plan.visits[sortie.rec_vid].truck == "t7"
    assert recovery_is_cross(plan, sortie) is False


if __name__ == "__main__":
    test_started_fragment_lands_only_when_configured()
    test_unstarted_sortie_lands_only_when_configured()
    test_same_truck_recovery_advance_is_shared_and_ground_holder_blocks_both()
    test_saved_sid130_metadata_is_not_a_cross_recovery()
    print("LANDED_FRAGMENT_REGRESSION_PASS", "native_evaluations", 0)
