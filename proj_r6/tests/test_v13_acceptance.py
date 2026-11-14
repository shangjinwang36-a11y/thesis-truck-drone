"""Section 12 acceptance tests for SCENARIO_RULES v1.3.

These are the freeze checks. A green run of the older suite does not replace them.
"""
from __future__ import annotations

import inspect
import math
import random
from pathlib import Path

import pytest

from tdr.config import PhysicalConfig, load_package
from tdr.data import load_instance
from tdr.hidden_world import HiddenWorld
from tdr.schedule import DroneStage, stage_energy
from tdr.v13 import (
    DRAFT_PLANNER_VIEW_SHA256,
    DRAFT_RESOLVED_SHA256,
    BudgetLedger,
    FormalRunRefused,
    HistoryError,
    ObservationRecord,
    SwapLedger,
    algorithm_rng_seed,
    apply_swap_cut,
    batch_by_exact_time,
    bernoulli_unrevealed_failure_probability,
    cache_key,
    classify_episode,
    electricity_cost_cny,
    enumerate_local_world,
    exact_j,
    git_run_metadata,
    j_hat,
    load_run_config,
    local_subset_probability,
    mcnemar_exact,
    nominal_search_evaluations,
    p_k2_given_one_failure,
    physical_kwargs_from_resolved,
    planner_log_record,
    planner_view_forbidden_keys,
    posterior_weights,
    recovery_truck_allowed,
    reject_warm_start,
    require_implementation,
    sample_conditional_failures,
    saving_decomposition,
    scenario_rng,
    sign_test,
    stratified_paired_bootstrap,
    training_scenarios,
    unrevealed_failure_probability,
    verify_draft_config,
    x_nominal_cross_floor_kwh,
)
from tdr.v13_config import sha256_obj

ROOT = Path(__file__).resolve().parents[1]
CASES = ("C50", "R50", "RC50", "C100", "R100", "RC100")


@pytest.fixture(scope="module")
def draft():
    cfg, view = verify_draft_config()
    return cfg, view


def test_t_gen_matches_registered_samples(draft):
    cfg, _ = draft
    samples = cfg["generator_check_samples"]["samples"]
    pkg = load_package(ROOT / "data" / "package_light.json")
    assert samples.keys() == set(CASES)
    for cid in CASES:
        inst = load_instance(pkg, cid)
        for seed in (1, 2, 3):
            world = HiddenWorld(inst, cid, seed)
            got = list(world.finish_episode().hidden_failure_parcels)
            assert got == samples[cid][str(seed)], (cid, seed, got)


def test_t_post_posterior_and_local_weights():
    assert posterior_weights(50, 1, 0)[1] == pytest.approx(2.0 / 3.0)
    assert p_k2_given_one_failure(50, 0) == pytest.approx(2.0 / 3.0)
    assert p_k2_given_one_failure(50, 10) == pytest.approx(78.0 / 127.0)
    assert unrevealed_failure_probability(50, 1, 10) == pytest.approx(2.0 / 127.0)
    assert unrevealed_failure_probability(50, 2, 0) == 0.0
    # f=0, s>0: the posterior is not the flat 3/(2N). Expected remaining failures fall.
    # Per remaining customer the rate is that expectation over n = N-s, which the formula
    # can increase because the pool shrinks. The acceptance check is the formula, plus the
    # drop in expected remaining failures.
    w_prior = posterior_weights(50, 0, 0)
    w_after = posterior_weights(50, 0, 10)
    e_prior = w_prior[0] * 1 + w_prior[1] * 2
    e_after = w_after[0] * 1 + w_after[1] * 2
    assert e_after < e_prior
    assert unrevealed_failure_probability(50, 0, 10) == pytest.approx(e_after / 40.0)
    assert unrevealed_failure_probability(50, 0, 0) == pytest.approx(3.0 / 100.0)

    rec = ObservationRecord()
    assert rec.note_air_arrival("c1", failed=False) is True
    assert rec.note_air_arrival("c1", failed=True) is False  # first arrival wins; ground is not this path
    assert rec.s == 1 and rec.f == 0
    # n = 0 does not sample and does not divide.
    done = ObservationRecord(successes=["a"], failures=["b"])
    assert sample_conditional_failures(random.Random(0), [], 2, done) == []
    assert unrevealed_failure_probability(2, 1, 1) == 0.0
    with pytest.raises(HistoryError):
        posterior_weights(4, 3, 0)

    # Bernoulli entry is not the 1-or-2 posterior.
    assert bernoulli_unrevealed_failure_probability(0.2, "c9", [], []) == 0.2
    assert bernoulli_unrevealed_failure_probability(0.2, "c9", ["c9"], []) == 1.0
    assert inspect.signature(posterior_weights).parameters.keys() <= {"n_eligible", "n_fail", "n_success", "q"}
    assert "world" not in inspect.signature(sample_conditional_failures).parameters

    # Ground-delivered but unrevealed customers are in the caller's pool and can be drawn.
    seen = set()
    for seed in range(40):
        drawn = sample_conditional_failures(
            random.Random(seed), ["ground_cust", "still_open"], 2, ObservationRecord())
        seen.update(drawn)
    assert "ground_cust" in seen

    # Small-world enumeration of P(F ∩ L = B) with no history, N=5, |L|=2.
    n, m = 5, 2
    manual = {0: 0.0, 1: 0.0, 2: 0.0}
    customers = list(range(n))
    local = customers[:m]
    worlds = []
    for k in (1, 2):
        from itertools import combinations
        for chosen in combinations(customers, k):
            worlds.append(frozenset(chosen))
    for chosen in worlds:
        b = len(chosen & set(local))
        manual[b] += 0.5 * (1.0 / math.comb(n, len(chosen)))
    closed = enumerate_local_world(n, 0, 0, m, observed=False)
    for b in range(0, m + 1):
        # The closed form is the probability of one specific B with |B|=b.
        specific = manual[b] / math.comb(m, b)
        assert local_subset_probability(n, 0, 0, m, b, observed=False) == pytest.approx(specific)
        assert closed[b] == pytest.approx(specific)
    assert local_subset_probability(n, 0, 0, m, 3, observed=False) == 0.0
    # After one failure and no success the weights are no longer the prior 1/2, 1/2.
    w = posterior_weights(n, 1, 0)
    assert w[1] == pytest.approx(2.0 / 3.0)
    cond = local_subset_probability(n, 1, 0, 1, 1, observed=True)
    assert 0.0 < cond < 1.0


def test_t_sim_exact_timestamp_batches():
    events = [
        {"time": 0.0, "customer_id": "c2", "parcel_id": "p2", "kind": "success"},
        {"time": 0.0005, "customer_id": "c1", "parcel_id": "p1", "kind": "failure"},
        {"time": 0.0005, "customer_id": "c3", "parcel_id": "p3", "kind": "success"},
        {"time": 0.0008, "customer_id": "c4", "parcel_id": "p4", "kind": "failure"},
        {"time": 0.0016, "customer_id": "c0", "parcel_id": "p0", "kind": "success"},
    ]
    batches = batch_by_exact_time(events)
    assert [len(b) for b in batches] == [1, 2, 1, 1]
    assert [e["time"] for b in batches for e in [b[0]]] == [0.0, 0.0005, 0.0008, 0.0016]
    # Same timestamp: success and failure are one batch, ordered by customer id only.
    assert [e["customer_id"] for e in batches[1]] == ["c1", "c3"]
    assert {e["kind"] for e in batches[1]} == {"failure", "success"}


def test_t_iso_planner_cannot_see_hidden_world(draft):
    cfg, view = draft
    leaked = planner_view_forbidden_keys(view, cfg["information_isolation"]["manager_only_keys"])
    assert leaked == []
    assert sha256_obj(view) == DRAFT_PLANNER_VIEW_SHA256
    # Algorithm stream ignores the environment seed: the function has no such argument.
    assert "environment_seed" not in inspect.signature(algorithm_rng_seed).parameters
    a = algorithm_rng_seed(20261111, "C50", "recovery", (("c1", "AIR_DELIVERY_ACCEPTED"),), "operator")
    b = algorithm_rng_seed(20261111, "C50", "recovery", (("c1", "AIR_DELIVERY_ACCEPTED"),), "operator")
    c = algorithm_rng_seed(20261111, "C50", "recovery", (("c1", "DELIVERY_UNAVAILABLE"),), "operator")
    assert a == b and a != c
    hidden_log = planner_log_record({
        "case": "C50", "hidden_failure_parcels": ["p1"], "air_hidden": ["p1"],
        "environment_seed": 4001, "action": "launch",
    })
    assert hidden_log == {"case": "C50", "action": "launch"}
    key = cache_key(plan_fingerprint=(1,), public_history=(("c1", "ok"),), state_fingerprint=(0.0,),
                    spares=(("t1", 4),), strategy="S", probability_model="main",
                    recovery_version="v13", scenario_set=(("p1",),))
    assert all("p027" not in str(part) for part in key)
    blob = repr(key)
    assert "true_F" not in blob
    # Posterior does not accept a world object.
    with pytest.raises(TypeError):
        posterior_weights(HiddenWorld)  # type: ignore[arg-type]


def test_t_inv_swap_debits_once_across_cuts():
    spares = {"t1": 4.0, "t2": 4.0}
    ledger = SwapLedger()
    # Cut falls inside the swap: reserve once.
    mid = apply_swap_cut(spares, ledger, [{"key": ("d1", 10.0), "truck": "t1", "status": "reserved"}])
    assert mid["t1"] == 3.0 and ("d1", 10.0) in ledger.reserved
    # The same swap completes at the next cut. No second debit.
    done = apply_swap_cut(mid, ledger, [{"key": ("d1", 10.0), "truck": "t1", "status": "completed"}])
    assert done["t1"] == 3.0 and ("d1", 10.0) in ledger.completed
    assert ("d1", 10.0) not in ledger.reserved
    # A later replan sees the completed key again and still does not debit.
    again = apply_swap_cut(done, ledger, [{"key": ("d1", 10.0), "truck": "t1", "status": "completed"}])
    assert again["t1"] == 3.0
    # Cross-truck: the next swap debits the new carrier, and a clone of the numbers is not reset.
    crossed = apply_swap_cut(again, ledger, [{"key": ("d1", 80.0), "truck": "t2", "status": "completed"}])
    assert crossed["t2"] == 3.0 and crossed["t1"] == 3.0
    cloned = dict(crossed)
    assert cloned["t1"] == 3.0 and cloned["t2"] == 3.0


def test_t_perm_strategy_permissions(draft):
    cfg, _ = draft
    mapping = cfg["strategy_mapping"]
    assert mapping["R"]["nominal_source"] == "S"
    assert mapping["R"]["recovery_policy"] == "X"
    assert mapping["R"]["nominal_search_evaluations"] == 0
    assert nominal_search_evaluations("R") == 0
    assert nominal_search_evaluations("S") == 1000
    assert recovery_truck_allowed("S", "t1", "t2", nominal=False) is False
    assert recovery_truck_allowed("S", "t1", "t1", nominal=False) is True
    assert recovery_truck_allowed("X", "t1", "t2", nominal=True) is True
    # R nominal is S; R recovery is X. A new ordinary sortie returns to its launch truck,
    # which the caller expresses by asking the S question for that sortie.
    assert recovery_truck_allowed("R", "t1", "t2", nominal=True) is False
    assert recovery_truck_allowed("R", "t1", "t2", nominal=False) is True
    assert recovery_truck_allowed("S", "t3", "t3", nominal=True) is True


def test_t_warm_x_does_not_read_s(tmp_path):
    with pytest.raises(Exception):
        reject_warm_start("X", reads_s_search=True, same_truck_phase=True, common_constructor=True)
    info = reject_warm_start("X", reads_s_search=False, same_truck_phase=True, common_constructor=True)
    assert info["same_truck_phase_counts_in_own_budget"] is True
    assert info["common_constructor_counts_in_own_budget"] is True
    from tdr.config import AlgorithmConfig
    from tdr.data import load_instance
    from tdr.experiment import build_case_nominal
    from tdr.v13 import WarmStartForbidden
    pkg = load_package(ROOT / "data" / "package_light.json")
    inst = load_instance(pkg, "C50")
    phys = PhysicalConfig(**physical_kwargs_from_resolved(verify_draft_config()[0], "C50"))
    alg = AlgorithmConfig(v13_rules=True, x_adopt_s_nominal=True)
    with pytest.raises(WarmStartForbidden):
        build_case_nominal(inst, phys, alg, tmp_path / "X", eval_budget=10, cross_launch=True,
                           adopt_from=tmp_path / "S")


def test_t_bud_shared_cap_and_wall():
    ledger = BudgetLedger(limit=1000, wall_s=60.0)
    assert ledger.charge("initialisation", 100)
    assert ledger.charge("catalog", 50)
    assert ledger.charge("MILP candidate verification", 10)
    assert ledger.charge("main search", 20)
    assert ledger.charge("scenario sub-evaluations", 5)
    assert ledger.charge("contingency/ground finish", 3)
    assert ledger.used == 188
    assert sum(ledger.by_reason.values()) == ledger.used
    # Cannot exceed the cap, and a fresh process does not inherit the count.
    assert ledger.charge("main search", 900) is False
    other = BudgetLedger(limit=1000, wall_s=0.0)
    assert other.charge("main search") is False
    assert other.wall_hits >= 1
    # The recovery source no longer tops up the cap.
    text = (ROOT / "src" / "tdr" / "recovery.py").read_text()
    assert "eval_limit = (budget.eval_limit or 0) +" not in text
    assert "JOINT_EXTRA_EVALS +" not in text


def test_t_e_energy_floor_hover_and_price(draft):
    cfg, _ = draft
    phys = PhysicalConfig(**physical_kwargs_from_resolved(cfg, "C50"))
    assert phys.swap_mode is True
    assert phys.land_and_wait is False
    assert phys.slot_ac_kw == 0.0
    for mass, power in ((0.0, 4.0 / 3.0), (1.0, 1.5), (2.0, 5.0 / 3.0), (4.0, 2.0)):
        assert phys.hover_power(mass) == pytest.approx(power)
    floor = x_nominal_cross_floor_kwh(phys.e_min, phys.e_cap, phys.hover_energy_kwh(90.0, 0.0))
    assert floor == pytest.approx(0.05 + max(0.025, phys.hover_energy_kwh(90.0, 0.0)))
    assert floor == pytest.approx(cfg["x_nominal_cross_gate"]["value_kwh"])
    landed = DroneStage("WAIT", 0.0, 10.0, mass=1.0, landed=True)
    with pytest.raises(AssertionError):
        stage_energy(landed, phys)
    assert electricity_cost_cny(0.9, 0.731012, 0.9) == pytest.approx(0.731012)
    # Negative duration is not an energy credit.
    assert phys.hover_energy_kwh(-5.0, 1.0) == float("inf")
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.schedule import initial_state
    inst = load_instance(load_package(ROOT / "data" / "package_light.json"), "C50")
    plan, _, _ = load_case_nominal(inst, ROOT / "r6/results/round11_tune/R11/nominal/S/C50")
    ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), cfg["cases"]["C50"]["H_case_s"], "NOMINAL")
    assert ev.feasible
    assert ev.cost_breakdown["c_vehicle"] == 0.0
    assert ev.cost_breakdown["ac_kwh"] == 0.0
    refill = ev.cost_breakdown["depot_refill_kwh"]
    assert ev.cost_breakdown["c_depot"] == pytest.approx(electricity_cost_cny(refill, phys.electricity_cny_kwh, phys.depot_efficiency))


def test_t_h_feasibility_witness(draft):
    """One legal nominal plan per map under v1.3 physics and the frozen H. H is not edited."""
    cfg, _ = draft
    from tdr.evaluate import evaluate_plan
    from tdr.experiment import load_case_nominal
    from tdr.schedule import initial_state
    pkg = load_package(ROOT / "data" / "package_light.json")
    failures = []
    for cid in CASES:
        phys = PhysicalConfig(**physical_kwargs_from_resolved(cfg, cid))
        inst = load_instance(pkg, cid)
        plan, _, _ = load_case_nominal(inst, ROOT / "r6/results/round11_tune/R11/nominal/S" / cid)
        h = cfg["cases"][cid]["H_case_s"]
        ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), h, "NOMINAL")
        if not (ev.feasible and ev.cost is not None and ev.timeline is not None):
            failures.append((cid, ev.status, (ev.violations or [])[:3]))
            continue
        makespan = max(ev.timeline.truck_finish.values())
        if makespan > h + 1e-6:
            failures.append((cid, "H", makespan, h))
        # No landed stage, and every recorded energy stays on the floor.
        for stages in ev.timeline.drone_stages.values():
            assert all(not st.landed for st in stages)
        for energies in ev.timeline.drone_energy.values():
            assert all(e >= phys.e_min - phys.energy_tol for e in energies)
    assert failures == []


def test_t_stat_pair_sets_ties_and_empty_map():
    rows = []
    for seed, cs, cr, cx in ((1, 100.0, 90.0, 80.0), (2, 100.0, 100.0, 100.00005)):
        rows.append({"seed": seed, "cost_S": cs, "cost_R": cr, "cost_X": cx,
                     "status_S": "COMPLETED_ONLINE", "status_R": "COMPLETED_ONLINE",
                     "status_X": "COMPLETED_ONLINE"})
    dec = saving_decomposition(rows)
    for item in dec["srx"]:
        assert item["g_sx"] == pytest.approx(item["g_sr"] + item["g_rx"])
    # The 1e-4 tie is kept in the mean and dropped only from the sign test.
    signed = sign_test([item["diff_sx"] for item in dec["sx_main"]])
    assert signed["ties"] == 1 and signed["n_effective"] == 1 and signed["wins"] == 1
    assert signed["mean_diff"] == pytest.approx((20.0 + (100.0 - 100.00005)) / 2.0)
    empty = stratified_paired_bootstrap({"C50": [0.1], "R50": []})
    assert empty["status"] == "NOT_COMPUTABLE" and empty["mean"] is None
    full = stratified_paired_bootstrap({"C50": [0.1, 0.2], "R50": [0.0, 0.0]}, replicates=200, seed=20261114)
    assert full["status"] == "OK" and full["ci_low"] <= full["mean"] <= full["ci_high"]
    mc = mcnemar_exact(3, 1)
    assert mc["b"] == 3 and mc["c"] == 1 and mc["pvalue"] is not None
    online, cost = classify_episode(verified_complete=True, used_contingency_finish=False,
                                    hard_violation=False, finish_cost=10.0)
    assert online == "COMPLETED_ONLINE"
    cont, _ = classify_episode(verified_complete=False, used_contingency_finish=True,
                               hard_violation=False, finish_cost=12.0)
    assert cont == "COMPLETED_CONTINGENCY"
    missing, none_cost = classify_episode(verified_complete=False, used_contingency_finish=False,
                                          hard_violation=False, finish_cost=None)
    assert missing == "NO_LEGAL_COMPLETION_FOUND" and none_cost is None


def test_t_cfg_hash_formal_refusal_and_metadata(draft):
    cfg, view = draft
    assert sha256_obj(cfg) == DRAFT_RESOLVED_SHA256
    assert cfg["planning_probability"]["M1"] is None
    with pytest.raises(FormalRunRefused):
        load_run_config(formal=True)
    with pytest.raises(FormalRunRefused):
        load_run_config(formal=True, m1=4, m2=4, status="DRAFT_NOT_FROZEN")
    dev, dev_view, digest = load_run_config(formal=False, m1=4, m2=4)
    assert dev["planning_probability"]["M1"] == 4
    assert sha256_obj(dev) == digest
    assert digest != DRAFT_RESOLVED_SHA256
    with pytest.raises(Exception):
        require_implementation("posterior_main", "not-a-real-posterior")
    meta = git_run_metadata(str(ROOT))
    assert meta["run_commit"]
    assert "worktree_clean" in meta
    # Final test seeds are refused outside a frozen formal run.
    from tdr.v13 import assert_seed_allowed
    with pytest.raises(FormalRunRefused):
        assert_seed_allowed(4001, formal=False)
    assert "seeds" not in view
    assert "statistics" not in view


def test_t_post_objective_weights_and_isolated_scenarios():
    # Negative interaction is kept. Weights are 3/(2N) and 1/(N(N-1)), not a pooled average.
    j = exact_j(10.0, [1.0, -2.0], [-4.0], 2)
    assert j == pytest.approx(10.0 + (3.0 / 4.0) * (1.0 - 2.0) + (1.0 / 2.0) * (-4.0))
    # M1 != M2 still splits the 1/2 weight. 400 is not added for a missing world.
    assert j_hat([10.0, 30.0], [0.0]) == pytest.approx(0.5 * 20.0 + 0.5 * 0.0)
    rng_a = scenario_rng("C50", 20261111)
    rng_b = scenario_rng("C50", 20261111)
    assert rng_a.random() == rng_b.random()
    # Different case, same algorithm seed: independent stream. Environment seed is not an input.
    singles, pairs = training_scenarios("C50", [f"p{i:03d}" for i in range(1, 51)], 3, 2, 20261111)
    assert len(singles) == 3 and len(pairs) == 2
    assert all(len(s) == 1 for s in singles) and all(len(p) == 2 for p in pairs)
