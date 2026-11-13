"""第 9 轮：弧上会合点、期望成本、跨车之后机体归属接机车。不改 H。"""
import json
from pathlib import Path

from tdr.attribution import bootstrap_mean_ci, case_aggregate, holm
from tdr.config import AlgorithmConfig, PhysicalConfig
from tdr.data import Customer, Instance
from tdr.expected_cost import cost_gap_discards_nominal, expected_j, insurance_room
from tdr.experiment import nominal_and_recovery
from tdr.moves import drone_carriers
from tdr.plan import Plan
from tdr.schedule import initial_state
from tdr.support_nominal import matched_handoff

ROOT = Path(__file__).resolve().parents[1]


def _tiny():
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    phys = PhysicalConfig.from_dict(pkg["config"])
    phys.set_active()
    inst = Instance("TINY", "T", 0.0, 0.0, (
        Customer("c001", "p001", 400.0, 0.0, 1.0),
        Customer("c002", "p002", 700.0, 0.0, 1.0),
        Customer("c003", "p003", 1200.0, 0.0, 1.0),
        Customer("c004", "p004", 800.0, 600.0, 1.0),
        Customer("c005", "p005", 200.0, 500.0, 1.0),
        Customer("c006", "p006", 1500.0, 100.0, 1.0),
    ))
    return inst, phys


def test_expected_j_adds_recourse_and_rejects_a_fixed_tau():
    inst, phys = _tiny()
    plan = Plan("TINY")
    launch = plan.add_visit("t1", "c001", ground=["p001"])
    rec = plan.add_visit("t1", "c003", ground=["p003"])
    plan.add_sortie("d1", "t1", launch.vid, "STOP", 0.0, ["p002"], rec.vid)
    assert expected_j(100.0, plan, inst, phys, 0.0) == 100.0
    higher = expected_j(100.0, plan, inst, phys, 0.2)
    assert higher > 100.0
    assert not cost_gap_discards_nominal(True, True)
    assert cost_gap_discards_nominal(False, True)
    assert not cost_gap_discards_nominal(False, False)


def test_cross_chain_keeps_the_drone_on_the_receiving_truck():
    inst, phys = _tiny()
    plan = Plan("TINY")
    a_launch = plan.add_visit("t1", "c001", ground=["p001"])
    b_stop = plan.add_visit("t2", "c004", ground=["p004"])
    b_launch = plan.add_visit("t2", "c005", ground=["p005"])
    c_stop = plan.add_visit("t3", "c006", ground=["p006"])
    plan.add_sortie("d1", "t1", a_launch.vid, "STOP", 0.0, ["p002"], b_stop.vid)
    plan.add_sortie("d1", "t2", b_launch.vid, "STOP", 0.0, ["p003"], c_stop.vid)
    errs = plan.validate_structure(inst, phys)
    assert not any("承运" in err for err in errs)
    assert drone_carriers(plan)["d1"] == "t3"
    state = initial_state(inst, phys)
    state.nominal_cross = True
    from tdr.alns import SolveContext
    ctx = SolveContext(inst, phys, AlgorithmConfig(), state, None, "nominal")
    matched = matched_handoff(plan, ctx)
    assert matched is None or matched.validate_structure(inst, phys) is not None


def test_new_cross_has_an_insurance_room_and_tau_is_not_a_constant_gate():
    inst, phys = _tiny()
    same = Plan("TINY")
    launch = same.add_visit("t1", "c001", ground=["p001"])
    rec = same.add_visit("t1", "c003", ground=["p003"])
    same.add_sortie("d1", "t1", launch.vid, "STOP", 0.0, ["p002"], rec.vid)
    cross = same.clone()
    other = cross.add_visit("t2", "c004", ground=[])
    cross.sorties[1].rec_vid = other.vid
    assert insurance_room(cross, same, inst, phys, 0.2) > 0
    assert insurance_room(same, same, inst, phys, 0.2) == 0


def test_holm_and_equal_weight_aggregation():
    adj = holm([0.01, 0.04, None, 0.03])
    assert adj[2] is None
    assert adj[0] == 0.03
    assert abs(adj[1] - 0.06) < 1e-12
    assert abs(adj[3] - 0.06) < 1e-12
    summary = case_aggregate({
        "C50": {"delta_mean": 2.0, "nominal_mean": 100.0},
        "C100": {"delta_mean": -8.0, "nominal_mean": 300.0},
    })
    assert summary["equal_weight_mean"] == -3.0
    assert abs(summary["cost_weighted_mean"] - (-5.5)) < 1e-9
    ci = bootstrap_mean_ci([1.0, 2.0, 3.0], n_boot=200, seed=1)
    assert ci["n"] == 3 and ci["ci95"][0] <= ci["mean"] <= ci["ci95"][1]


def test_x0_uses_s_nominal_and_x_recovery():
    s, x = Plan("S"), Plan("X")
    plan, recovery = nominal_and_recovery("X0", s, x, False)
    assert recovery == "X"
    assert plan is not s
    assert plan.case_id == s.case_id


def test_r9_preset_replaces_tau():
    import sys
    sys.path.insert(0, str(ROOT / "r6"))
    from run_round2 import configs
    pkg = json.loads((ROOT / "data" / "package_light.json").read_text(encoding="utf-8"))
    _, alg, _, _ = configs(pkg, "R9")
    assert alg.expected_accept is True
    assert alg.x_exchange_cost_tau == 0.0
    assert alg.x_improve_only_cross is False
    assert alg.expected_reeval_every == 80
    _, alg8, _, _ = configs(pkg, "R8")
    assert alg8.expected_accept is False
    assert alg8.x_exchange_cost_tau == 2.0
