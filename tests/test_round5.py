import json
from pathlib import Path

import pytest

from tdr.data import load_instance
from tdr.hidden_world import BernoulliWorld, HiddenWorld, bernoulli_failure_flags, make_world

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inst():
    p = ROOT / "data" / "package.json"
    if not p.exists():
        pytest.skip("run extract first")
    return load_instance(json.loads(p.read_text(encoding="utf-8")), "C50")


def test_default_mode_unchanged(inst):
    a = make_world(inst, "C50", 3)
    b = HiddenWorld(inst, "C50", 3)
    assert isinstance(a, HiddenWorld) and not isinstance(a, BernoulliWorld)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels


def test_bernoulli_deterministic_and_strategy_independent(inst):
    a = make_world(inst, "C50", 5, "bernoulli", 0.2)
    b = make_world(inst, "C50", 5, "bernoulli", 0.2)
    assert a.finish_episode().hidden_failure_parcels == b.finish_episode().hidden_failure_parcels
    c = make_world(inst, "C50", 6, "bernoulli", 0.2)
    assert make_world(inst, "C50", 5, "bernoulli", 0.2).configured_failure_count >= 0
    assert c.finish_episode().hidden_failure_parcels != make_world(inst, "C50", 5, "bernoulli", 0.2).finish_episode().hidden_failure_parcels


def test_bernoulli_nested_across_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    f1 = bernoulli_failure_flags("C50", 1, ids, 0.1)
    f2 = bernoulli_failure_flags("C50", 1, ids, 0.2)
    f3 = bernoulli_failure_flags("C50", 1, ids, 0.3)
    assert f1 <= f2 <= f3


def test_bernoulli_rate_close_to_p(inst):
    ids = [c.parcel_id for c in inst.customers]
    for p in (0.1, 0.2, 0.3):
        tot = sum(len(bernoulli_failure_flags("C50", s, ids, p)) for s in range(1, 201))
        rate = tot / (200 * len(ids))
        assert abs(rate - p) < 0.02, (p, rate)
    assert bernoulli_failure_flags("C50", 1, ids, 0.0) == frozenset()
    assert bernoulli_failure_flags("C50", 1, ids, 1.0) == frozenset(ids)


def test_bernoulli_reveal_only_on_arrival(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    ids = [c for c in inst.customers]
    obs = [w.observe_air_arrival(c.parcel_id, 1.0, f"a-{i}", c.customer_id, "d") for i, c in enumerate(ids)]
    audit = w.finish_episode()
    failed_obs = {o.parcel_id for o in obs if not o.air_delivery_available}
    assert failed_obs == set(audit.hidden_failure_parcels) == set(audit.observed_air_failure_parcels)
    assert len(failed_obs) > 0


def test_bernoulli_unattempted_not_observed(inst):
    w = make_world(inst, "C50", 2, "bernoulli", 0.5)
    c = inst.customers[0]
    w.observe_air_arrival(c.parcel_id, 1.0, "x", c.customer_id, "d")
    audit = w.finish_episode()
    assert set(audit.observed_air_failure_parcels) <= {c.parcel_id}


def _episode_audit(strat, flag):
    import random, zlib
    from tdr.config import AlgorithmConfig, PhysicalConfig
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.hidden_world import TestWorld
    from tdr.schedule import initial_state
    from tdr import simulate
    case = "C50"
    pkg = json.load(open(ROOT / "data" / "package.json"))
    fx = ROOT / "tests" / "fixtures" / "spec" / case
    if not fx.exists():
        pytest.skip("fixture missing")
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    alg.recovery_eval_budget_override = 300
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = "milp"
    alg.reassign_adopt_only_if_best = flag
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, fx)
    nom = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, "NOMINAL")
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    rng = random.Random(zlib.crc32(f"{case}:1:3".encode()))
    world = TestWorld(inst, case, tuple(rng.sample(air, 3)))
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, "recovery", 0)
    cap = []
    orig = simulate.optimize

    def wrap(p, ctx, b, **kw):
        r = orig(p, ctx, b, **kw)
        cap.append(r)
        return r
    simulate.optimize = wrap
    try:
        ep = simulate.run_episode(inst, plan, nom, H, phys, world, strat, alg, rngs, recovery_eval_budget=300)
    finally:
        simulate.optimize = orig
    return ep, cap


@pytest.mark.parametrize("strat", ["S", "X"])
def test_reassign_flag_never_adopts_worse_than_best(strat):
    """reassign_adopt_only_if_best=True：目录候选只有优于全局最优才替换当前解（防止丢弃 ALNS 进展）."""
    ep, cap = _episode_audit(strat, True)
    assert ep.status.startswith("COMPLETED") or ep.status.startswith("STOPPED")
    for r in cap:
        gap = r.stats.audit.get("reassign:adopt_gap_max")
        assert gap is None or gap < 0.0


def test_reassign_flag_default_false():
    from tdr.config import AlgorithmConfig
    assert AlgorithmConfig().reassign_adopt_only_if_best is False


def _light_plan():
    from tdr.experiment import load_case_nominal
    pkg = json.load(open(ROOT / "data" / "package_light.json"))
    fx = ROOT / "tests" / "fixtures" / "light"
    case = "C50"
    if not (fx / case).exists():
        pytest.skip("fixture missing")
    from tdr.config import PhysicalConfig
    phys = PhysicalConfig.from_dict(dict(pkg["config"])).for_case(pkg.get("case_fleet"), case)
    inst = load_instance(pkg, case)
    plan, _, H = load_case_nominal(inst, fx / case)
    return inst, phys, plan


def _overlaps(plan):
    from tdr.moves import drone_chain
    bad = []
    for d in plan.drone_sorties:
        ch = drone_chain(plan, d)
        for i in range(len(ch)):
            for j in range(i + 1, len(ch)):
                _, li, ri = ch[i]; _, lj, rj = ch[j]
                if not (ri < lj or li > rj):
                    bad.append((d, ch[i], ch[j]))
    return bad


@pytest.mark.parametrize("recheck", [True, False])
def test_apply_air_recheck_prevents_overlapping_chain(recheck):
    """贪心修复里两个 NEW 候选在修复开始时选了同一机体同一区间：应用第二个时必须重新核对机位."""
    from tdr import moves
    from tdr.moves import AirCandidate, apply_air, drones_on_truck, sortie_slot_free
    inst, phys, plan = _light_plan()
    plan = plan.clone()
    # 清空某车的全部航次以制造空闲机位
    truck = max(sorted(plan.routes), key=lambda t: len(plan.routes[t]))
    for sid in [s.sid for s in plan.sorties.values() if s.truck == truck and not s.started]:
        plan.remove_sortie(sid)
    route = plan.routes[truck]
    assert len(route) >= 4
    drones = drones_on_truck(plan, truck)
    assert len(drones) >= 1
    d0 = drones[0]
    a, b = 1, 3
    assert sortie_slot_free(plan, d0, a, b)
    parcels = [p for p in inst.parcel_mass][:2]
    old = moves.CHAIN_RECHECK
    moves.CHAIN_RECHECK = recheck
    try:
        oks = []
        for p in parcels:
            cand = AirCandidate("NEW", truck, route[a], "ARC", 0.5, route[b], proxy=0.0, energy=0.0, drone=d0)
            oks.append(apply_air(plan, inst, p, cand, phys=phys))
    finally:
        moves.CHAIN_RECHECK = old
    if recheck:
        assert _overlaps(plan) == []                    # 无重叠：第二个换机体或失败
        assert oks[0] is True
    else:
        assert len(_overlaps(plan)) >= 1                # 旧行为复现：同机体区间重叠
