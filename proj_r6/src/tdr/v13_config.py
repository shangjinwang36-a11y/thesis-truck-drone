"""Build SCENARIO_RULES v1.3 resolved_config from package_light.json and frozen H files.

Canonical hash is sha256 of json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).
The null-M draft must match the registered hash. M1/M2 overrides produce a separate draft.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def canon_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_obj(obj) -> str:
    return hashlib.sha256(canon_bytes(obj)).hexdigest()


def build_resolved_config(m1=None, m2=None, status: str = "DRAFT_NOT_FROZEN"):
    """Return (resolved_config, planner_view)."""
    ROOT = Path(__file__).resolve().parents[2]
    PKG = ROOT / "data/package_light.json"
    pkg_bytes = PKG.read_bytes(); pkg = json.loads(pkg_bytes)
    cfg = pkg["config"]
    def canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    H_SRC = ROOT / "r6/results/round11_tune/R11/nominal/S"
    cases = {}
    for c in pkg["cases"]:
        cid = c["case_id"]; cust = c["customers"]
        masses = [m[3] for m in cust]
        elig = [m for m in cust if m[3] <= cfg["drone_payload_limit_kg"] + 1e-12]
        hs = json.loads((H_SRC / cid / "nominal_plan.json").read_text())["H_s"]
        cases[cid] = {
            "n_customers": len(cust), "N_air_eligible": len(elig),
            "air_eligible_rule": "static: parcel mass_kg <= drone_payload_limit_kg (4.0)",
            "total_mass_kg": round(sum(masses), 10), "max_parcel_mass_kg": max(masses),
            "truck_count": pkg["case_fleet"][cid]["truck_count"], "drone_count": pkg["case_fleet"][cid]["drone_count"],
            "depot_xy_m": c["depot_xy_m"],
            "customers_sha256": hashlib.sha256(canon(cust)).hexdigest(),
            "H_case_s": hs, "T_ref_case_s": hs - cfg["shift_slack_s"],
            "H_source": "round11-frozen (5eab1b2) round11_tune/R11/nominal/S/%s/nominal_plan.json H_s = Cmax(S nominal)+1800, frozen as constant" % cid,
        }
    Ecap = cfg["battery_kwh"]
    rc = {
      "rules_version": "SCENARIO_RULES v1.3",
      "status": "DRAFT_NOT_FROZEN",
      "source_package": {"path": "proj_r6/data/package_light.json", "package_id": pkg["package_id"],
                         "schema_version": pkg["schema_version"], "revision_date": pkg["revision_date"],
                         "file_sha256": hashlib.sha256(pkg_bytes).hexdigest()},
      "code_reference": {"tag": "round11-frozen", "commit": "5eab1b27a91d1b271ec11f632e0231249172cfe8", "python_version_generator": "3.13.5"},
      "units": pkg["units"],
      "fleet_common": {k: cfg[k] for k in ["drones_per_truck_initial", "truck_drone_slots", "truck_recovery_channels"]},
      "kinematics": {"truck_speed_m_s": cfg["truck_speed_m_s"], "drone_speed_m_s": cfg["drone_speed_m_s"]},
      "payload": {"drone_payload_limit_kg": cfg["drone_payload_limit_kg"], "weights_already_scaled_x0_8": True,
                  "rescale_at_runtime": False, "multi_parcel_sorties": True, "max_total_onboard_mass_kg": cfg["drone_payload_limit_kg"]},
      "operation_times_s": {k: cfg[k] for k in ["prepare_s", "launch_s", "recovery_s", "handover_s", "ground_service_s",
                                                 "air_service_s", "failure_confirmation_s"]} | {"swap_s": cfg["swap_s"]},
      "energy": {
        "battery_kwh": Ecap, "reserve_fraction": cfg["reserve_fraction"], "E_min_kwh": cfg["reserve_fraction"] * Ecap,
        "beta_cruise": cfg["beta_cruise"], "beta_hover": cfg["beta_hover"],
        "range0_m_formula": "R0(m) = range_empty_m - range_slope_m_per_kg * m, 0<=m<=4",
        "range_empty_m": cfg["range_empty_m"], "range_slope_m_per_kg": cfg["range_slope_m_per_kg"],
        "fly_energy_formula": "E_fly(d,m) = beta_cruise * E_cap * d / R0(m)",
        "hover_endpoint_powers": "P_0 = 60*E_cap/hover_min_empty, P_ref = 60*E_cap/hover_min_ref [kW]",
        "hover_min_empty": cfg["hover_min_empty"], "hover_min_ref": cfg["hover_min_ref"], "payload_ref_kg": cfg["payload_ref_kg"],
        "hover_power_formula": "P_hover(m) = beta_hover * (P_0 + (P_ref - P_0) * m / payload_ref_kg) [kW]  (linear in power; identical to round11 config.py:137 hover_power)",
        "hover_energy_formula": "E_hover(tau,m) = P_hover(m) * tau / 3600",
        "energised_drone_stages": {"L": "hover(launch_s, mass)", "CRUISE": "fly", "SERVICE": "hover(air_service_s, pre-release mass)",
                                   "FAILED_ARRIVAL": "0 (confirmation 0 s)", "WAIT_AIRBORNE": "hover(actual wait, actual mass)",
                                   "R": "hover(recovery_s, actual mass)", "ON_TRUCK/READY/P/U/SWAP": "0"},
        "landed_wait_or_landed_recovery_allowed": False, "land_and_wait": False,
        "independent_ground_shutdown_wait_allowed": False,
        "hard_floor": "every recorded drone energy >= E_min - tolerance_energy_kwh at all times, incl. end of R and all contingency/ground-finish paths",
        "cruise_only_usable_range_note": "0.9*R0(m) is a pure-cruise upper bound only",
      },
      "x_nominal_cross_gate": {"applies_to": "X nominal cross-truck sorties published before execution only",
                               "check_point": "energy at end of nominal success-branch R",
                               "formula": "E_endR >= E_min + max(0.05*E_cap, E_hover(90 s, 0 kg))",
                               "value_kwh": cfg["reserve_fraction"] * Ecap + max(0.05 * Ecap, 60 * Ecap / cfg["hover_min_empty"] * 90 / 3600),
                               "extra_90s_time_buffer": False, "is_global_physics": False},
      "replenishment": {"mode": "swap_only", "swap_mode": True, "onboard_battery_per_drone_at_start": 1,
                        "spare_full_batteries_per_truck": cfg["spare_batteries"], "spares_occupy_drone_slots": False,
                        "swap_consumes_spare_of": "actual carrier truck at swap time", "removed_battery_reusable_as_spare": False,
                        "inventory_reset_on_cross_truck_or_replan_or_clone": False,
                        "swap_location": "initial depot or legal customer stop while truck parked; driver task; before P; serial with G/P/R/U",
                        "on_truck_charging": False, "airborne_charging": False},
      "cost": {"diesel_l_100km": cfg["diesel_l_100km"], "diesel_cny_l": cfg["diesel_cny_l"], "maintenance_cny_km": cfg["maintenance_cny_km"],
               "driver_cny_h": cfg["driver_cny_h"], "driver_includes_final_return": True,
               "electricity_cny_kwh": cfg["electricity_cny_kwh"], "depot_efficiency": cfg["depot_efficiency"],
               "electricity_formula": "C_elec = electricity_cny_kwh / depot_efficiency * sum_b (E_b_start - E_b_end) over every battery used (onboard + swapped)",
               "vehicle_charging_cost_terms": 0.0, "overtime_cost": None, "infeasible_penalty_cny": None,
               "full_precision_required": True, "tolerance_cost_cny": cfg["tolerance_cost_cny"]},
      "shift": {"H_rule": "H_case = T_ref_case + shift_slack_s, constants below, common to S/R/X and all finishing paths",
                "shift_slack_s": cfg["shift_slack_s"], "hard": True, "soft_h": False, "soft_h_switch_in_ground_finish": False},
      "failure_model_main": {"type": "hidden_count_uniform_without_replacement", "K_values": [1, 2], "K_probs": [0.5, 0.5],
                             "population": "all static air-eligible customers incl. nominal ground orders", "N_lt_2": "N=0 -> F empty; N=1 -> F = {that customer}",
                             "generator_version": pkg["experiment_protocol"]["failure_generator_version"],
                             "environment_rng_seed": pkg["experiment_protocol"]["environment_rng_seed"],
                             "sampling_order": pkg["experiment_protocol"]["sampling_order"],
                             "draw": "rng=random.Random(seed); K=rng.choice((1,2)); F=rng.sample(sorted_eligible,K)",
                             "P_single": "3/(2N)", "P_pair": "1/(N(N-1))", "observation": "actual air arrival only",
                             "resample_on_observed_count_or_benefit": False, "shared_world_S_R_X": True},
      "failure_model_sensitivity": {"type": "independent_bernoulli", "p": 0.2, "hash_key": "(generator_version, case_id, seed, parcel_id)",
                                    "comparable_to_main": False},
      "planning_probability": {"main_objective": "J = C0 + 3/(2N)*sum_i Q_i + 1/(N(N-1))*sum_{i<j} I_ij ; Q_i=C_i-C0 ; I_ij=C_ij-C_i-C_j+C0 ; no truncation",
                               "sampled_estimator": "J_hat = 1/(2*M1)*sum C(single_r) + 1/(2*M2)*sum C(pair_r)",
                               "M1": None, "M2": None, "M_note": "fixed on dev seeds before any test run; null => code must refuse to run",
                               "scenario_rng": "SHA256(compact_UTF8_JSON(['tdr-plan-scenarios-v1.1', case_id, base_algorithm_seed])) -> random.Random; independent of environment seeds",
                               "shared_by": ["S", "X"], "double_failure_revealed_sequentially": True,
                               "recovery_conditional_update": "eq.(5)-(6); after 1 observed failure P(K=2)=2/3; after 2 => 0",
                               "planner_may_know": "distribution only, never K, F or environment seed"},
      "budget": {"nominal_full_evaluations_per_strategy": 1000, "R_nominal": "x_R == x_S (no nominal search)",
                 "recovery_full_evaluations_per_recovery_process": 1000, "recovery_wallclock_s_per_process": cfg["recovery_time_limit_s"],
                 "includes": ["initialisation", "catalog", "MILP candidate verification", "main search", "contingency/ground finish", "scenario sub-evaluations"],
                 "separate_sub_ledgers_or_top_ups": False, "per_episode_total": "sum over recovery processes (not capped at 1000)",
                 "simultaneous_failures": "failures revealed within tolerance_time_s are batched into one process, ordered by customer_id",
                 "decision_latency_s": cfg["decision_latency_s"], "audit_counts_must_equal_ledger": True},
      "planning_scope": pkg["config"]["planning_scope"],
      "recovery_policy": cfg["recovery_policy"],
      "failure_semantics": cfg["failure_semantics"],
      "terminal_return_policy": cfg["terminal_return_policy"],
      "launch_operations_authoritative": {k: v for k, v in cfg["launch_operations"].items()
                                          if k not in ("charging_while_driving", "ready_drone_may_charge_while_legally_parked", "ready_drone_may_charge_while_driving")},
      "waiting_operations": cfg["waiting_operations"],
      "tolerances": {k: cfg[k] for k in ["tolerance_cost_cny", "tolerance_time_s", "tolerance_energy_kwh"]},
      "seeds": {"tune": "101-110", "dev": ["1-10", "2001-2010"], "history_test_forbidden": ["1001-1010", "3001-3030"],
                "final_test": "4001-4030 run once", "base_algorithm_seed": 20261111,
                "nominal_plan_reuse": "one verified nominal plan per (case, strategy, algorithm seed) reused for all 30 environment seeds; R reuses S"},
      "ignored_package_fields": [
        "config.energy_reference.reference_payload_kg/empty_range_m/reference_payload_range_m/empty_hover_min/reference_payload_hover_min/energy_scale (30 kg heavy drone)",
        "config.launch_operations.charging_while_driving / ready_drone_may_charge_while_legally_parked / ready_drone_may_charge_while_driving",
        "config.charging_operations.* (all)", "config.slot_ac_kw / truck_ac_kw / truck_initial_ac_kwh / slot_efficiency / aux_efficiency / charge_ready_delay_s",
        "config.truck_count / drone_count (overridden by case_fleet)", "config.truck_launch_recovery_channels (duplicate of truck_recovery_channels)",
        "config.smoke_customer_limit", "model_notes.* (historical metadata)",
        "experiment_protocol.environment_seed_values / repetitions_per_case / nominal_plan_policy (overridden by rules section 8)",
        "algorithm_experiment_protocol.* run counts / statuses (historical)", "data/package.json (full 3.9688 kWh package, forbidden)"],
      "cases": cases,
    }
    # kept semantic booleans from energy_reference
    rc["energy"]["successful_air_service_charged_at_pre_release_payload"] = cfg["energy_reference"]["successful_air_service_charged_at_pre_release_payload"]
    rc["energy"]["failed_arrival_charges_no_nonexistent_successful_service"] = cfg["energy_reference"]["failed_arrival_charges_no_nonexistent_successful_service"]

    import random
    GEN = pkg["experiment_protocol"]["failure_generator_version"]
    def gen_F(cid, seed):
        c = next(x for x in pkg["cases"] if x["case_id"] == cid)
        elig = sorted(("c%03d" % m[0], "p%03d" % m[0]) for m in c["customers"] if m[3] <= cfg["drone_payload_limit_kg"] + 1e-12)
        enc = json.dumps([GEN, cid, seed], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        rng = random.Random(int.from_bytes(hashlib.sha256(enc).digest(), "big"))
        k = rng.choice((1, 2)) if len(elig) >= 2 else len(elig)
        return sorted(e[1] for e in rng.sample(elig, k)) if k > 0 else []
    # ---- v1.2 additions ----
    for cid in cases:
        hp = H_SRC / cid / "nominal_plan.json"
        cases[cid]["H_source_file_sha256"] = hashlib.sha256(hp.read_bytes()).hexdigest()
        cases[cid]["H_source_path"] = "code-round11-frozen/proj_r6/r6/results/round11_tune/R11/nominal/S/%s/nominal_plan.json" % cid
        cases[cid]["H_status"] = "USER_CONFIRMED 2026-11-14 12:30 (hard); still needs feasibility witness under v1.3 (acceptance T-H)"
    rc["status"] = status
    rc["code_reference"]["role"] = "parameter provenance only; result metadata must record the actual run commit and whether the worktree is clean"
    rc["implementation_ids"] = {"energy_model": "light_round11_hover_power_linear", "failure_generator": GEN,
        "posterior_main": "hidden_count_1or2_uniform_wor_posterior_v1", "posterior_sensitivity": "independent_bernoulli_posterior_v1",
        "planning_scenarios": "tdr-plan-scenarios-v1.1 (seed salt string kept unchanged)", "unknown_id_policy": "raise_error_no_default_fallback"}
    rc["energy"]["hover_interpolation_status"] = "USER_CONFIRMED 2026-11-14 12:30: keep round11 code (linear in power); GPT time-interpolation suggestion declined; not a modelling change"
    rc["energy"]["hover_power_kw_check"] = {"0kg": 4/3, "1kg": 1.5, "2kg": 5/3, "3kg": 11/6, "4kg": 2.0}
    lo = rc["launch_operations_authoritative"]
    lo["manual_driver_operations"] = ["G", "P", "R", "U", "SWAP"]
    lo["driver_event_type_for_swap"] = "SWAP (single canonical id; legacy 'W' must be mapped explicitly)"
    rc["replenishment"]["inventory_debit_rule"] = ("new_state_spares = previous_cut_state_spares - swaps newly completed between the two cut times and not yet debited; "
        "exactly one debit event per swap; an in-progress swap across a cut keeps reserved/completed status; full energy only after swap completes")
    pp = rc["planning_probability"]
    pp["recovery_conditional_update"] = ("posterior from revealed success/failure customer-id sets: w_k(h) = q_k*C(N-f-s,k-f)/C(N,k) / sum_l q_l*C(N-f-s,l-f)/C(N,l); "
        "P(K=2|f=1,s) = 2(N-s-1)/(3N-2s-3); 2/3 holds only for f=1,s=0 (test case); f=2 => remaining failure prob 0; NOT a fixed 2/3 rule")
    pp["local_branch_weight"] = "P(F_rem ∩ L = B | h) = sum_k w_k(h) * C(n-m, k-f-|B|) / C(n, k-f), n=N-f-s, L ⊆ unrevealed, illegal binomials = 0"
    pp["conditional_scenario_sampling"] = ("draw k ~ w_k(h); then draw k-f failures uniformly without replacement from ALL unrevealed air-eligible customers "
        "(incl. ground-delivered-but-unrevealed); n=0 => no sampling; zero denominator => raise error, never silently reset prior")
    pp["observation_record"] = "first actual air arrival per customer, deduplicated; success counted at arrival (not at end of 60 s service); ground delivery never updates s"
    pp["sensitivity_posterior"] = "independent Bernoulli: separate entry point; unrevealed customers keep p; never use the 1-or-2 posterior"
    pp["M1"] = m1; pp["M2"] = m2
    pp["M_note"] = "placeholders; fixed on dev seeds (101-110 tune / 1-10, 2001-2010 dev) in a separate DRAFT config; null => code must refuse to run formal tests"
    pp["planner_may_know"] = "public distribution + revealed history; logical inference from revealed history (e.g. K=2 after two failures) is allowed; never unrevealed K/F or anything that reconstructs the test world"
    b = rc["budget"]
    b["simultaneous_failures"] = ("batch only observations at the same actual event time (identical simulated timestamp); collect all successes and failures at that time, "
        "update state and posterior together, trigger exactly one recovery process (one 1000-eval budget); customer_id orders records only; "
        "tolerance_time_s is for numerical verification only and never reveals future events")
    rc["strategy_mapping"] = {"S": {"nominal_source": "S", "recovery_policy": "S"}, "X": {"nominal_source": "X", "recovery_policy": "X"},
                              "R": {"nominal_source": "S", "recovery_policy": "X", "nominal_search_evaluations": 0}}
    rc["warm_start"] = {"status": "USER_CONFIRMED 2026-11-14 12:30", "X_reads_independent_S_search_result": False,
                        "X_same_truck_phase_within_own_1000": True, "common_deterministic_initial_constructor_S_and_X": True,
                        "shared_init_must_be_preregistered_and_budgeted": True}
    rc["statistics"] = {"saving_definition": "g = (C_S - C_X)/C_S per pair; C_S = S actual full cost same world; six maps equal weight",
        "decomposition": "g_SR=(C_S-C_R)/C_S, g_RX=(C_R-C_X)/C_S on the common S/R/X valid pair set",
        "pair_sets": {"S_X_main": "pairs where both S and X have legal full cost", "S_R_X_decomposition": "pairs where all of S,R,X have legal full cost",
                      "report_per_map": "kept count and exclusion reasons"},
        "empty_map": "if a map has no valid pair, the six-map equal-weight cost metric is NOT_COMPUTABLE; never silently average five maps",
        "completion_rate": "full = verified COMPLETED_ONLINE + COMPLETED_CONTINGENCY; online rate reported separately",
        "confidence_level": 0.95, "ci_sides": "two-sided", "bootstrap": {"method": "stratified paired percentile (resample env seeds within map, then six-map equal weight)",
        "replicates": 10000, "rng": "numpy.random.default_rng(seed)", "seed": 20261114},
        "sign_test": {"type": "exact two-sided binomial", "tie_threshold_cny": 1e-4, "ties": "excluded from sign test only; report wins/losses/ties/effective n; all-ties => no test",
                      "mean_and_bootstrap": "use raw differences of all pairs incl. ties"},
        "holm_family": "six per-map S-X comparisons, alpha=0.05", "mcnemar": "exact, on completion; report both discordant counts",
        "unpriced_episodes": "reported first as rates; cost statistics stated as conditional on the pair set"}
    rc["information_isolation"] = {"full_config_holder": "experiment manager / hidden-world simulator only",
        "planner_view": "whitelist below; produced by experiment manager; recorded hash planner_view_sha256",
        "manager_only_keys": ["seeds", "failure_model_main.generator_version", "failure_model_main.environment_rng_seed", "failure_model_main.sampling_order",
                              "failure_model_main.draw", "failure_model_sensitivity.hash_key", "generator_check_samples", "statistics"],
        "side_channels_blocked": ["algorithm RNG must not derive from environment seed (derive from algorithm seed, case, phase, public history only)",
            "hidden_failure_parcels / air_hidden / true K / paths or logs containing the env seed never enter planner state, scoring or planner-readable logs",
            "caches never keyed on true unrevealed F; key = public history, state, remaining spares, strategy permission, probability model, recovery version, training scenario set",
            "posterior functions accept only revealed success/failure ids + distribution params, never a HiddenWorld object; lookahead uses regenerated conditional worlds"],
        "acceptance": "fix public state, algorithm RNG state and budget; vary only the unrevealed failure set; committed actions must be identical until the first differing observation"}
    rc["generator_check_samples"] = {"python": "3.13.5", "samples": {cid: {str(sd): gen_F(cid, sd) for sd in (1, 2, 3)} for cid in cases}}
    # planner whitelist view
    view = {k: rc[k] for k in ["rules_version", "units", "fleet_common", "kinematics", "payload", "operation_times_s", "energy", "x_nominal_cross_gate",
                               "replenishment", "cost", "shift", "planning_probability", "budget", "planning_scope", "recovery_policy", "failure_semantics",
                               "terminal_return_policy", "launch_operations_authoritative", "waiting_operations", "tolerances", "strategy_mapping",
                               "warm_start", "implementation_ids"]}
    view["failure_distribution_public"] = {k: rc["failure_model_main"][k] for k in ["type", "K_values", "K_probs", "population", "N_lt_2", "P_single", "P_pair", "observation"]}
    view["cases_public"] = {cid: {k: v for k, v in c.items() if k in ("n_customers", "N_air_eligible", "truck_count", "drone_count", "depot_xy_m", "customers_sha256", "H_case_s")} for cid, c in cases.items()}
    rc["information_isolation"]["planner_view_sha256"] = hashlib.sha256(canon(view)).hexdigest()
    rc["information_isolation"]["planner_view_sha256"] = hashlib.sha256(canon(view)).hexdigest()
    return rc, view
