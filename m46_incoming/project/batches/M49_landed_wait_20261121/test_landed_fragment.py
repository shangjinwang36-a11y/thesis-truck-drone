"""The started fragment lands when that action is already configured. No evaluator calls."""
from dataclasses import replace
import pickle
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "M49_landed_wait_core_20261121"
sys.path.insert(0, str(CORE / "source/proj_r6/src"))
sys.path.insert(0, str(CORE))
from tdr.recovery import build_residual_candidate  # noqa: E402

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


def test_unstarted_sortie_is_not_forced_to_land():
    inst, phys, plan, state, greq, opts = load()
    sample = next(s for s in plan.sorties.values() if not s.started)
    made = build_residual_candidate(plan, sample.sid, None, inst, phys, state, greq, "X")
    if made and sample.sid in made[0].sorties:
        assert not made[0].sorties[sample.sid].landed


if __name__ == "__main__":
    test_started_fragment_lands_only_when_configured()
    test_unstarted_sortie_is_not_forced_to_land()
    print("LANDED_FRAGMENT_REGRESSION_PASS", "native_evaluations", 0)
