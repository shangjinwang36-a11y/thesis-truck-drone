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
from tdr.recovery import _reorder_same_truck, _sync_recovery_truck, build_residual_candidate  # noqa: E402

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


def test_same_truck_reorder_is_shared_and_does_not_schedule():
    import tdr.schedule as schedule
    inst, phys, _plan, state, _greq, _opts = load()
    raw = json.loads(next(open(
        "/workspace/m46_incoming/project/batches/M49_landed_wait_20261121/paid_rehome/RC100_1002/RAW.jsonl")))
    plan = plan_from_dict(raw["plan"])
    calls = {"n": 0}
    real = schedule.schedule_plan

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    schedule.schedule_plan = counted
    try:
        shared = _reorder_same_truck(plan, inst, phys, state, "t7")
        again = _reorder_same_truck(plan, inst, phys, state, "t7")
    finally:
        schedule.schedule_plan = real
    assert calls["n"] == 0
    assert shared is not None and again is not None
    order_s = [shared.visits[v].customer for v in shared.routes["t7"]]
    order_x = [again.visits[v].customer for v in again.routes["t7"]]
    assert order_s == order_x
    assert set(order_s) == set(plan.visits[v].customer for v in plan.routes["t7"])
    for visit in shared.visits.values():
        if "p047" in visit.ground:
            assert visit.truck == "t7"
    from tdr.alns import Budget
    budget = Budget(100, None)
    assert budget.take() and budget.used == 1 and budget.evals_left() == 99
    assert budget.eval_limit == 100


def test_sync_keeps_an_unstarted_cross_and_aligns_a_started_fragment():
    from tdr.plan import Plan, Sortie
    inst, phys, _plan, _state, _greq, _opts = load()
    built = Plan(inst.case_id)
    launch = built.add_visit("t1", "c001")
    recover = built.add_visit("t2", "c002")
    later = built.add_visit("t1", "c003")
    cross = Sortie(1, "d1", "t1", launch.vid, "STOP", 0.0, [], recover.vid, launch_truck="t1")
    same = Sortie(2, "d1", "t1", launch.vid, "STOP", 0.0, [], later.vid, launch_truck="t1")
    started = Sortie(3, "d2", "t9", None, "AIR", 0.0, [], recover.vid, started=True,
                     start_pos=(0.0, 0.0), launch_truck="t7")
    built.sorties = {1: cross, 2: same, 3: started}
    built.drone_sorties = {"d1": [1, 2], "d2": [3]}
    _sync_recovery_truck(built)
    assert cross.truck == "t1"
    assert built.visits[cross.launch_vid].truck == cross.truck
    assert recovery_is_cross(built, cross) is True
    assert same.truck == "t1"
    assert recovery_is_cross(built, same) is False
    assert started.launch_truck == "t7"
    assert started.truck == "t2"
    assert recovery_is_cross(built, started) is True
    errors = built.validate_structure(inst, phys)
    assert not any("放飞访问不属于放飞车" in error for error in errors)


def test_saved_sid130_metadata_is_not_a_cross_recovery():
    plan = plan_from_dict(json.loads(Path(
        "/workspace/m46_incoming/project/batches/M49_landed_wait_20261121/paid_rehome/RC100_1002/SELECTED_PLAN.json"
    ).read_text()))
    sortie = plan.sorties[130]
    assert sortie.truck == "t2"
    assert sortie.launch_truck == "t7"
    assert plan.visits[sortie.rec_vid].truck == "t7"
    assert recovery_is_cross(plan, sortie) is False
    _sync_recovery_truck(plan)
    assert plan.sorties[130].truck == "t7"
    assert plan.sorties[130].launch_truck == "t7"
    assert recovery_is_cross(plan, plan.sorties[130]) is False


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
    test_same_truck_reorder_is_shared_and_does_not_schedule()
    test_sync_keeps_an_unstarted_cross_and_aligns_a_started_fragment()
    test_saved_sid130_metadata_is_not_a_cross_recovery()
    print("LANDED_FRAGMENT_REGRESSION_PASS", "native_evaluations", 0)
