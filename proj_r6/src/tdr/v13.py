"""SCENARIO_RULES v1.3 kernel.

The experiment manager holds the full resolved config. Planners receive only the
whitelist view. Posterior, scenario and statistic functions never accept a
HiddenWorld object.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .v13_config import build_resolved_config, sha256_obj

DRAFT_RESOLVED_SHA256 = "18aa0b6b9fded9941174378899dd799b5d78e18cfa12a05d13f813e943c934ae"
DRAFT_PLANNER_VIEW_SHA256 = "1083a619336d186f36e4133a9616f8b4bb1bf27f2c2dafaedff59f7b63d7f748"

KNOWN_IMPLEMENTATIONS = {
    "energy_model": {"light_round11_hover_power_linear"},
    "failure_generator": {"customer-failure-v3-1"},
    "posterior_main": {"hidden_count_1or2_uniform_wor_posterior_v1"},
    "posterior_sensitivity": {"independent_bernoulli_posterior_v1"},
    "planning_scenarios": {"tdr-plan-scenarios-v1.1"},
}

FINAL_TEST_SEEDS = range(4001, 4031)
HISTORY_TEST_SEEDS = set(range(1001, 1011)) | set(range(3001, 3031))

# Driver-task id. Legacy "W" is mapped here and nowhere else.
DRIVER_EVENT_MAP = {"G": "G", "P": "P", "R": "R", "U": "U", "W": "SWAP", "SWAP": "SWAP"}


class ConfigError(RuntimeError):
    pass


class FormalRunRefused(ConfigError):
    pass


class HistoryError(ValueError):
    """Posterior denominator is zero: the history or the implementation is wrong."""


def canonical_driver_event(kind: str) -> str:
    if kind not in DRIVER_EVENT_MAP:
        raise ValueError(f"unknown driver event {kind!r}")
    return DRIVER_EVENT_MAP[kind]


def require_implementation(kind: str, impl_id: str) -> str:
    """Dispatch on a registered implementation id. Unknown ids raise; there is no default."""
    known = KNOWN_IMPLEMENTATIONS.get(kind)
    if known is None:
        raise ConfigError(f"unknown implementation kind {kind}")
    # planning_scenarios id in the JSON carries a parenthetical; the salt string is the id.
    token = impl_id.split(" (", 1)[0].strip()
    if token not in known and impl_id not in known:
        raise ConfigError(f"unknown implementation_id {kind}={impl_id}")
    return token


def verify_draft_config() -> tuple[dict, dict]:
    """Regenerate the null-M draft and refuse to continue if the hash moved."""
    cfg, view = build_resolved_config(None, None, "DRAFT_NOT_FROZEN")
    got = sha256_obj(cfg)
    if got != DRAFT_RESOLVED_SHA256:
        raise ConfigError(f"resolved_config hash {got} != registered {DRAFT_RESOLVED_SHA256}")
    vhash = sha256_obj(view)
    recorded = cfg["information_isolation"]["planner_view_sha256"]
    if vhash != DRAFT_PLANNER_VIEW_SHA256 or recorded != DRAFT_PLANNER_VIEW_SHA256:
        raise ConfigError(f"planner view hash {vhash}/{recorded} != registered {DRAFT_PLANNER_VIEW_SHA256}")
    ids = cfg["implementation_ids"]
    require_implementation("energy_model", ids["energy_model"])
    require_implementation("failure_generator", ids["failure_generator"])
    require_implementation("posterior_main", ids["posterior_main"])
    require_implementation("posterior_sensitivity", ids["posterior_sensitivity"])
    require_implementation("planning_scenarios", ids["planning_scenarios"])
    return cfg, view


def load_run_config(*, formal: bool, m1: int | None = None, m2: int | None = None,
                    status: str = "DRAFT_NOT_FROZEN") -> tuple[dict, dict, str]:
    """Load a config. Formal runs refuse null M1/M2 and any non-frozen status.

    Returns (resolved, planner_view, sha256).
    """
    verify_draft_config()
    if formal and (m1 is None or m2 is None):
        raise FormalRunRefused("M1/M2 are null; formal experiments are refused")
    if formal and status != "FROZEN":
        raise FormalRunRefused("formal experiments require a FROZEN config")
    if m1 is None and m2 is None:
        cfg, view = build_resolved_config(None, None, "DRAFT_NOT_FROZEN")
        return cfg, view, DRAFT_RESOLVED_SHA256
    if m1 is None or m2 is None or int(m1) <= 0 or int(m2) <= 0:
        raise ConfigError("M1 and M2 must both be positive integers")
    cfg, view = build_resolved_config(int(m1), int(m2), status)
    cfg["planning_probability"]["M_note"] = (
        f"chosen on tune seeds 101-110 only; M1={int(m1)} M2={int(m2)}; "
        "null draft remains the registered DRAFT hash"
    )
    # The view was built before the note rewrite. Rebuild the view fields that changed.
    view = dict(view)
    view["planning_probability"] = dict(cfg["planning_probability"])
    cfg["information_isolation"]["planner_view_sha256"] = sha256_obj(view)
    # The recorded hash is the manager's view, including the M note. The object
    # the planner is given is the whitelist: no generator version and no seed notes.
    return cfg, explicit_planner_whitelist(view), sha256_obj(cfg)


def assert_seed_allowed(seed: int, *, formal: bool) -> None:
    seed = int(seed)
    if seed in HISTORY_TEST_SEEDS:
        raise ConfigError(f"seed {seed} is a historical test seed and must not be used for tuning or version selection")
    if seed in FINAL_TEST_SEEDS and not formal:
        raise FormalRunRefused(f"seed {seed} is a final test seed; this run is not the frozen formal test")


def planner_view_forbidden_keys(view: dict, manager_only: Sequence[str]) -> list[str]:
    """Return manager-only keys that leaked into the planner view."""
    leaked = []
    for key in manager_only:
        top, _, rest = key.partition(".")
        if rest:
            block = view.get(top)
            if isinstance(block, dict) and rest in block:
                leaked.append(key)
        elif top in view:
            leaked.append(key)
    return leaked


def physical_kwargs_from_resolved(cfg: dict, case_id: str) -> dict:
    """Fields the light experiment is allowed to read. Heavy-drone defaults are not used."""
    energy = cfg["energy"]
    case = cfg["cases"][case_id]
    fleet = cfg["fleet_common"]
    op = cfg["operation_times_s"]
    cost = cfg["cost"]
    kin = cfg["kinematics"]
    if abs(float(energy["battery_kwh"]) - 0.5) > 1e-12:
        raise ConfigError("light experiment battery must be 0.5 kWh")
    if not cfg["replenishment"]["swap_mode"]:
        raise ConfigError("light experiment is swap-only")
    return {
        "truck_count": case["truck_count"],
        "drone_count": case["drone_count"],
        "drones_per_truck_initial": fleet["drones_per_truck_initial"],
        "truck_drone_slots": fleet["truck_drone_slots"],
        "truck_recovery_channels": fleet["truck_recovery_channels"],
        "truck_speed_m_s": kin["truck_speed_m_s"],
        "drone_speed_m_s": kin["drone_speed_m_s"],
        "drone_payload_limit_kg": cfg["payload"]["drone_payload_limit_kg"],
        "battery_kwh": energy["battery_kwh"],
        "reserve_fraction": energy["reserve_fraction"],
        "beta_cruise": energy["beta_cruise"],
        "beta_hover": energy["beta_hover"],
        "ground_service_s": op["ground_service_s"],
        "air_service_s": op["air_service_s"],
        "prepare_s": op["prepare_s"],
        "launch_s": op["launch_s"],
        "recovery_s": op["recovery_s"],
        "handover_s": op["handover_s"],
        "swap_s": op["swap_s"],
        "swap_mode": True,
        "spare_batteries": cfg["replenishment"]["spare_full_batteries_per_truck"],
        "payload_ref_kg": energy["payload_ref_kg"],
        "range_empty_m": energy["range_empty_m"],
        "range_slope_m_per_kg": energy["range_slope_m_per_kg"],
        "hover_min_empty": energy["hover_min_empty"],
        "hover_min_ref": energy["hover_min_ref"],
        "depot_efficiency": cost["depot_efficiency"],
        "diesel_l_100km": cost["diesel_l_100km"],
        "diesel_cny_l": cost["diesel_cny_l"],
        "maintenance_cny_km": cost["maintenance_cny_km"],
        "driver_cny_h": cost["driver_cny_h"],
        "electricity_cny_kwh": cost["electricity_cny_kwh"],
        "shift_slack_s": cfg["shift"]["shift_slack_s"],
        "tolerance_cost_cny": cfg["tolerances"]["tolerance_cost_cny"],
        "tolerance_time_s": cfg["tolerances"]["tolerance_time_s"],
        "tolerance_energy_kwh": cfg["tolerances"]["tolerance_energy_kwh"],
        "soft_h": False,
        "land_and_wait": False,
        "slot_ac_kw": 0.0,
        "truck_ac_kw": 0.0,
        "truck_initial_ac_kwh": 0.0,
        "charge_ready_delay_s": 0.0,
    }


def git_run_metadata(cwd: str | None = None) -> dict:
    """Actual executing commit and whether the worktree is clean. Not the historical reference commit."""
    def _run(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
    commit = _run(["git", "rev-parse", "HEAD"])
    dirty = bool(_run(["git", "status", "--porcelain"]))
    return {"run_commit": commit, "worktree_clean": not dirty, "code_reference_commit_role": "parameter provenance only"}


# ---------------------------------------------------------------------------
# Posterior. Signatures take revealed id sets and distribution parameters only.
# ---------------------------------------------------------------------------

def _binom(n: int, k: int) -> int:
    if k < 0 or n < 0 or k > n:
        return 0
    return math.comb(n, k)


def posterior_weights(n_eligible: int, n_fail: int, n_success: int,
                      q: tuple[float, float] = (0.5, 0.5)) -> tuple[float, float]:
    """w_k(h) for K in {1, 2}. Raises HistoryError when the denominator is 0."""
    n_rem = n_eligible - n_fail - n_success
    if n_fail < 0 or n_success < 0 or n_rem < 0 or n_eligible < 0:
        raise HistoryError("history or implementation error")
    terms = []
    for k, qk in ((1, q[0]), (2, q[1])):
        den = _binom(n_eligible, k)
        terms.append(0.0 if den == 0 else qk * _binom(n_rem, k - n_fail) / den)
    total = terms[0] + terms[1]
    if total == 0.0:
        raise HistoryError("history or implementation error")
    return terms[0] / total, terms[1] / total


def p_k2_given_one_failure(n_eligible: int, n_success: int) -> float:
    """P(K=2 | f=1, s) = 2(N-s-1)/(3N-2s-3). Equals 2/3 only when s=0."""
    w1, w2 = posterior_weights(n_eligible, 1, n_success)
    del w1
    return w2


def unrevealed_failure_probability(n_eligible: int, n_fail: int, n_success: int) -> float:
    """Failure probability of any one still-unrevealed air-eligible customer."""
    n_rem = n_eligible - n_fail - n_success
    if n_rem == 0:
        return 0.0
    w1, w2 = posterior_weights(n_eligible, n_fail, n_success)
    return w1 * max(0, 1 - n_fail) / n_rem + w2 * max(0, 2 - n_fail) / n_rem


def bernoulli_unrevealed_failure_probability(p: float, customer_id: str,
                                            revealed_failures: Iterable[str],
                                            revealed_successes: Iterable[str]) -> float:
    """Sensitivity posterior. Independent of history. Not the 1-or-2 formula."""
    if customer_id in set(revealed_failures):
        return 1.0
    if customer_id in set(revealed_successes):
        return 0.0
    return float(p)


def posterior_k_support(n_eligible: int, n_fail: int, n_success: int, *, observed: bool) -> tuple[int, ...]:
    """K values with positive posterior weight. Unobserved history is the prior {1, 2}."""
    if not observed:
        return (1, 2)
    w1, w2 = posterior_weights(n_eligible, n_fail, n_success)
    out = []
    if w1 > 0.0:
        out.append(1)
    if w2 > 0.0:
        out.append(2)
    return tuple(out)


def local_branch_support(n_eligible: int, n_fail: int, n_success: int, subset_size: int,
                         *, observed: bool) -> range:
    """Local failure counts that the posterior can still produce. K≤2, so b≥3 is out."""
    hi = 0
    revealed = n_fail if observed else 0
    for k in posterior_k_support(n_eligible, n_fail, n_success, observed=observed):
        hi = max(hi, k - revealed)
    return range(0, min(int(subset_size), hi) + 1)


def local_subset_probability(n_eligible: int, n_fail: int, n_success: int,
                             subset_size: int, failure_count_in_subset: int,
                             *, observed: bool) -> float:
    """P(F ∩ L = B) with no history, or P(F_rem ∩ L = B | h) once anything is observed.

    Illegal binomial coefficients are 0. Three or more simultaneous local failures have probability 0
    because K ≤ 2.
    """
    if failure_count_in_subset >= 3 or failure_count_in_subset < 0:
        return 0.0
    support = posterior_k_support(n_eligible, n_fail, n_success, observed=observed)
    if not observed:
        acc = 0.0
        for k in support:
            den = _binom(n_eligible, k)
            if den == 0:
                continue
            acc += 0.5 * _binom(n_eligible - subset_size, k - failure_count_in_subset) / den
        return acc
    n_rem = n_eligible - n_fail - n_success
    weights = dict(zip((1, 2), posterior_weights(n_eligible, n_fail, n_success)))
    acc = 0.0
    for k in support:
        den = _binom(n_rem, k - n_fail)
        if den == 0:
            continue
        acc += weights[k] * _binom(n_rem - subset_size, k - n_fail - failure_count_in_subset) / den
    return acc


def enumerate_local_world(n_eligible: int, n_fail: int, n_success: int, subset_size: int,
                          *, observed: bool) -> dict[int, float]:
    """Local-branch probabilities on the posterior support only. b≥3 is not a key."""
    return {b: local_subset_probability(n_eligible, n_fail, n_success, subset_size, b, observed=observed)
            for b in local_branch_support(n_eligible, n_fail, n_success, subset_size, observed=observed)}


def batch_opens_recovery(events: Sequence[dict]) -> bool:
    """A same-time batch opens one recovery only when it contains a new failure.

    An all-success batch updates history and does not consume recovery budget.
    """
    for ev in events:
        if ev.get("kind") == "failure":
            return True
        if ev.get("air_delivery_available") is False:
            return True
    return False


_PLANNER_VIEW_KEYS = (
    "rules_version", "units", "fleet_common", "kinematics", "payload", "operation_times_s",
    "energy", "x_nominal_cross_gate", "replenishment", "cost", "shift", "planning_probability",
    "budget", "planning_scope", "recovery_policy", "failure_semantics", "terminal_return_policy",
    "launch_operations_authoritative", "waiting_operations", "tolerances", "strategy_mapping",
    "warm_start", "implementation_ids", "failure_distribution_public", "cases_public",
)
_PLANNER_NOTE_KEYS = {
    "M_note", "generator_version", "environment_rng_seed", "sampling_order", "draw",
    "hash_key", "generator_check_samples", "python", "samples",
}


def explicit_planner_whitelist(view: dict) -> dict:
    """Planner-visible config. Generator version, check samples, and dev-seed notes are out."""
    clean: dict = {}
    for key in _PLANNER_VIEW_KEYS:
        if key not in view:
            continue
        value = view[key]
        if isinstance(value, dict):
            block = {}
            for ik, iv in value.items():
                if ik in _PLANNER_NOTE_KEYS or "seed" in ik.lower() or "generator" in ik.lower():
                    continue
                if isinstance(iv, str) and _dev_seed_note(iv):
                    continue
                block[ik] = iv
            clean[key] = block
        elif isinstance(value, str) and _dev_seed_note(value):
            continue
        else:
            clean[key] = value
    return clean


def _dev_seed_note(text: str) -> bool:
    markers = ("101-110", "1-10", "2001-2010", "4001-4030", "dev seed", "tune seed", "generator_version")
    low = text.lower()
    return any(m in low for m in markers)


def column_pool_key(case_id: str, allow_cross: bool) -> tuple:
    """Pool identity. The unrevealed failure set is not part of it."""
    return (str(case_id), bool(allow_cross))


def reset_planner_episode_state(alg) -> None:
    """Drop caches and column pools before an episode. Training scenarios are not hidden F."""
    for name in ("_column_pools", "_scenario_cache"):
        if getattr(alg, name, None) is not None:
            setattr(alg, name, {})


@dataclass
class ObservationRecord:
    """Public air-arrival record. Ground deliveries never enter it. First arrival per customer wins."""
    successes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def note_air_arrival(self, customer_id: str, *, failed: bool) -> bool:
        if customer_id in self.successes or customer_id in self.failures:
            return False
        (self.failures if failed else self.successes).append(customer_id)
        return True

    @property
    def f(self) -> int:
        return len(self.failures)

    @property
    def s(self) -> int:
        return len(self.successes)


def sample_conditional_failures(rng: random.Random, unrevealed_ids: Sequence[str],
                                n_eligible: int, record: ObservationRecord) -> list[str]:
    """Draw the remaining failures from every unrevealed air-eligible customer.

    The pool must include customers already delivered on the ground but not yet revealed by air.
    n = 0 draws nothing and does not divide. The true K is not an argument.
    """
    n_rem = n_eligible - record.f - record.s
    if n_rem == 0:
        return []
    if len(unrevealed_ids) != n_rem:
        raise HistoryError("history or implementation error")
    w1, w2 = posterior_weights(n_eligible, record.f, record.s)
    k = 1 if rng.random() < w1 else 2
    need = k - record.f
    if need <= 0:
        return []
    return list(rng.sample(sorted(unrevealed_ids), need))


# ---------------------------------------------------------------------------
# Planning objective and training scenarios.
# ---------------------------------------------------------------------------

def exact_j(c0: float, single_increments: Sequence[float], pair_interactions: Sequence[float],
            n_eligible: int) -> float:
    """J = C0 + 3/(2N) Σ Q_i + 1/(N(N-1)) Σ I_ij. Negative terms are kept."""
    n = int(n_eligible)
    if n < 2:
        raise ValueError("exact J needs N >= 2")
    return (float(c0)
            + (3.0 / (2.0 * n)) * sum(float(q) for q in single_increments)
            + (1.0 / (n * (n - 1))) * sum(float(v) for v in pair_interactions))


def j_hat(single_costs: Sequence[float], pair_costs: Sequence[float]) -> float:
    """Equal 1/2 weight on the single-failure mean and the pair-failure mean, even if M1 != M2."""
    if not single_costs or not pair_costs:
        raise ValueError("J_hat needs both a single-failure sample and a pair-failure sample")
    return 0.5 * (sum(single_costs) / len(single_costs)) + 0.5 * (sum(pair_costs) / len(pair_costs))


def scenario_rng(case_id: str, base_algorithm_seed: int) -> random.Random:
    """Isolated from every environment seed. Salt string is tdr-plan-scenarios-v1.1."""
    payload = json.dumps(["tdr-plan-scenarios-v1.1", case_id, int(base_algorithm_seed)],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    return random.Random(seed)


def training_scenarios(case_id: str, eligible_ids: Sequence[str], m1: int, m2: int,
                       base_algorithm_seed: int) -> tuple[list[frozenset], list[frozenset]]:
    """M1 uniform singletons and M2 uniform pairs. Shared by S and X. Independent draws."""
    if m1 <= 0 or m2 <= 0:
        raise ConfigError("M1/M2 must be positive before a scenario set is drawn")
    rng = scenario_rng(case_id, base_algorithm_seed)
    ids = sorted(eligible_ids)
    if len(ids) < 2:
        raise ValueError("training scenarios need at least two eligible customers")
    singles = [frozenset(rng.sample(ids, 1)) for _ in range(int(m1))]
    pairs = [frozenset(rng.sample(ids, 2)) for _ in range(int(m2))]
    return singles, pairs


RECOVERY_NOT_FOUND = "RECOVERY_NOT_FOUND"


def scenario_cost_or_flag(cost: float | None) -> float | str:
    """A scenario with no legal completion has no finite cost. Never 0 and never a penalty."""
    if cost is None:
        return RECOVERY_NOT_FOUND
    return float(cost)


# ---------------------------------------------------------------------------
# Energy, inventory, cache, budgets, permissions.
# ---------------------------------------------------------------------------

def x_nominal_cross_floor_kwh(e_min: float, e_cap: float, hover_energy_90s_empty: float) -> float:
    """E_min + max(0.05 E_cap, E_hover(90 s, 0 kg)). Not a truncated decimal."""
    return float(e_min) + max(0.05 * float(e_cap), float(hover_energy_90s_empty))


def electricity_cost_cny(refill_kwh: float, price_cny_per_kwh: float = 0.731012,
                         depot_efficiency: float = 0.9) -> float:
    return (float(price_cny_per_kwh) / float(depot_efficiency)) * float(refill_kwh)


@dataclass
class SwapLedger:
    """One debit per swap. An in-progress swap stays reserved and is not debited again."""
    completed: dict[tuple, str] = field(default_factory=dict)   # key -> truck
    reserved: dict[tuple, str] = field(default_factory=dict)

    def debit_completed(self, key: tuple, truck: str, spares: dict[str, float]) -> None:
        if key in self.completed:
            return
        if key in self.reserved:
            # Already debited when it was reserved.
            self.completed[key] = self.reserved.pop(key)
            return
        spares[truck] = spares.get(truck, 0.0) - 1.0
        self.completed[key] = truck

    def debit_reserved(self, key: tuple, truck: str, spares: dict[str, float]) -> None:
        if key in self.completed or key in self.reserved:
            return
        spares[truck] = spares.get(truck, 0.0) - 1.0
        self.reserved[key] = truck


def apply_swap_cut(spares: dict[str, float], ledger: SwapLedger, events: Sequence[dict]) -> dict[str, float]:
    """Apply swaps that completed or are in progress between two cuts.

    Each event is {key, truck, status: 'completed'|'reserved'|'open'}.
    'open' means the swap has not reached this cut and is not debited.
    Full energy is the caller's concern and is not applied here.
    """
    out = dict(spares)
    for ev in events:
        status = ev["status"]
        if status == "completed":
            ledger.debit_completed(ev["key"], ev["truck"], out)
        elif status == "reserved":
            ledger.debit_reserved(ev["key"], ev["truck"], out)
        elif status == "open":
            continue
        else:
            raise ValueError(status)
    return out


def cache_key(*, plan_fingerprint: tuple, public_history: tuple, state_fingerprint: tuple,
              spares: tuple, strategy: str, probability_model: str, recovery_version: str,
              scenario_set: tuple) -> tuple:
    """Never includes the true unrevealed failure set."""
    return (plan_fingerprint, public_history, state_fingerprint, spares,
            strategy, probability_model, recovery_version, scenario_set)


def plan_fingerprint(plan) -> tuple:
    """Routes, ground visits with their route index, launch and recovery locations."""
    routes = tuple((t, tuple(plan.route_customers(t))) for t in sorted(plan.routes))
    ground = []
    for truck in sorted(plan.routes):
        for idx, vid in enumerate(plan.routes[truck]):
            v = plan.visits[vid]
            ground.append((truck, idx, v.customer, tuple(v.ground)))
    air = []
    for s in plan.sorties.values():
        rec = plan.visits.get(s.rec_vid)
        launch = plan.visits.get(s.launch_vid) if s.launch_vid is not None else None
        air.append((s.drone, s.truck, s.launch_truck, None if rec is None else rec.truck,
                    None if rec is None else rec.customer,
                    None if launch is None else launch.customer,
                    tuple(s.air), tuple(s.handover), round(float(s.lam), 5)))
    return (routes, tuple(ground), tuple(sorted(air)))


def recovery_truck_allowed(strategy: str, launch_truck: str, candidate_truck: str, *, nominal: bool) -> bool:
    """S recovers only on the actual launch truck. X may use any truck, including in the nominal plan.

    A new ordinary sortie after recovery returns to its actual launch truck (enforced by the caller
    passing strategy 'S' for that sortie's return constraint).
    """
    if strategy == "S":
        return candidate_truck == launch_truck
    if strategy == "X":
        return True
    if strategy == "R":
        # R's nominal plan is S's. Recovery uses X's permission.
        if nominal:
            return candidate_truck == launch_truck
        return True
    raise ValueError(strategy)


def nominal_search_evaluations(strategy: str) -> int | None:
    """R does not search. S and X each have their own 1000. None means 'use the budget'."""
    if strategy == "R":
        return 0
    if strategy in ("S", "X"):
        return 1000
    raise ValueError(strategy)


class WarmStartForbidden(RuntimeError):
    pass


def reject_warm_start(strategy: str, *, reads_s_search: bool, same_truck_phase: bool,
                      common_constructor: bool) -> dict:
    """X must not read an independent S search. Same-truck phase and the common constructor are allowed.

    Both of those allowed paths are charged to X's own budget by the caller.
    """
    if strategy == "X" and reads_s_search:
        raise WarmStartForbidden("X must not read an independent S search result")
    return {"same_truck_phase_counts_in_own_budget": bool(same_truck_phase),
            "common_constructor_counts_in_own_budget": bool(common_constructor)}


@dataclass
class BudgetLedger:
    """One recovery process: init, catalog, MILP checks, search, scenarios and finish share 1000 and 60 s."""
    limit: int = 1000
    wall_s: float = 60.0
    used: int = 0
    by_reason: dict = field(default_factory=dict)
    wall_hits: int = 0
    _t0: float = field(default_factory=lambda: __import__("time").perf_counter())

    def elapsed(self) -> float:
        import time
        return time.perf_counter() - self._t0

    def charge(self, reason: str, n: int = 1) -> bool:
        if self.elapsed() >= self.wall_s:
            self.wall_hits += 1
            return False
        if self.used + n > self.limit:
            return False
        self.used += n
        self.by_reason[reason] = self.by_reason.get(reason, 0) + n
        return True

    @property
    def exhausted_reason(self) -> str | None:
        if self.wall_hits and self.elapsed() >= self.wall_s:
            return "WALL"
        if self.used >= self.limit:
            return "EVALS"
        return None


def batch_by_exact_time(events: Sequence[dict]) -> list[list[dict]]:
    """Group observations that share an identical simulated timestamp.

    A gap of 0.0005 s is two batches. customer_id orders records inside a batch only.
    """
    pending = sorted(events, key=lambda e: (e["time"], e.get("customer_id", ""), e.get("parcel_id", "")))
    batches: list[list[dict]] = []
    for ev in pending:
        if not batches or ev["time"] != batches[-1][0]["time"]:
            batches.append([ev])
        else:
            batches[-1].append(ev)
    for batch in batches:
        batch.sort(key=lambda e: (e.get("customer_id", ""), e.get("parcel_id", "")))
    return batches


# ---------------------------------------------------------------------------
# Statistics.
# ---------------------------------------------------------------------------

LEGAL_COMPLETION = ("COMPLETED_ONLINE", "COMPLETED_CONTINGENCY")


def is_legal_full_cost(status: str, cost: float | None) -> bool:
    return status in LEGAL_COMPLETION and cost is not None and math.isfinite(cost)


def completion_flags(status: str) -> dict:
    return {
        "full": status in LEGAL_COMPLETION,
        "online": status == "COMPLETED_ONLINE",
        "contingency": status == "COMPLETED_CONTINGENCY",
        "unpriced": status in ("NO_LEGAL_COMPLETION_FOUND", "HARD_CONSTRAINT_VIOLATION") or status not in LEGAL_COMPLETION,
    }


def _pair_rows(rows: Sequence[dict], keys: Sequence[str]) -> list[dict]:
    out = []
    for row in rows:
        if all(is_legal_full_cost(row[f"status_{k}"], row[f"cost_{k}"]) for k in keys):
            out.append(row)
    return out


def saving_decomposition(rows_one_map: Sequence[dict]) -> dict:
    """On the common S/R/X set, g_SX = g_SR + g_RX for every pair. Costs are actual full costs."""
    common = _pair_rows(rows_one_map, ("S", "R", "X"))
    sx = _pair_rows(rows_one_map, ("S", "X"))
    def pack(subset, which):
        packed = []
        for row in subset:
            cs, cr, cx = row["cost_S"], row.get("cost_R"), row["cost_X"]
            g_sx = (cs - cx) / cs
            item = {"seed": row["seed"], "g_sx": g_sx, "diff_sx": cs - cx}
            if which == "srx":
                item["g_sr"] = (cs - cr) / cs
                item["g_rx"] = (cr - cx) / cs
                item["g_sum"] = item["g_sr"] + item["g_rx"]
            packed.append(item)
        return packed
    return {"sx_main": pack(sx, "sx"), "srx": pack(common, "srx"),
            "n_sx": len(sx), "n_srx": len(common),
            "n_input": len(rows_one_map)}


def sign_test(differences: Sequence[float], tie_cny: float = 1e-4) -> dict:
    """Exact two-sided binomial on the sign. Ties drop out of the test only."""
    from scipy.stats import binomtest
    diffs = [float(d) for d in differences]
    wins = sum(1 for d in diffs if d > tie_cny)
    losses = sum(1 for d in diffs if d < -tie_cny)
    ties = len(diffs) - wins - losses
    n = wins + losses
    if n == 0:
        return {"wins": wins, "losses": losses, "ties": ties, "n_effective": 0,
                "pvalue": None, "tested": False, "mean_diff": (sum(diffs) / len(diffs) if diffs else None)}
    pvalue = float(binomtest(wins, n, 0.5, alternative="two-sided").pvalue)
    return {"wins": wins, "losses": losses, "ties": ties, "n_effective": n,
            "pvalue": pvalue, "tested": True,
            "mean_diff": sum(diffs) / len(diffs)}


def holm(pvalues: Sequence[float], alpha: float = 0.05) -> list[dict]:
    """Holm adjustment. Input order is preserved in the output."""
    indexed = sorted(enumerate(pvalues), key=lambda iv: iv[1])
    m = len(indexed)
    adj = [None] * m
    running = 0.0
    for rank, (idx, p) in enumerate(indexed):
        running = max(running, min(1.0, (m - rank) * float(p)))
        adj[idx] = running
    return [{"p": float(p), "p_holm": adj[i], "reject": adj[i] <= alpha} for i, p in enumerate(pvalues)]


def mcnemar_exact(b: int, c: int) -> dict:
    """Exact McNemar on the two discordant counts. b = S completed and X not, or the caller's order."""
    from scipy.stats import binomtest
    n = int(b) + int(c)
    if n == 0:
        return {"b": int(b), "c": int(c), "pvalue": None}
    # Test count b against n/2. Equivalent to testing either discordant cell.
    pvalue = float(binomtest(int(b), n, 0.5, alternative="two-sided").pvalue)
    return {"b": int(b), "c": int(c), "n_discordant": n, "pvalue": pvalue}


def stratified_paired_bootstrap(by_map: dict[str, Sequence[float]], *,
                                replicates: int = 10000, seed: int = 20261114) -> dict:
    """Resample environment-seed savings inside each map, then the equal-weight six-map mean.

    by_map values are the paired savings (or cost differences) already restricted to the pair set.
    An empty map makes the six-map metric NOT_COMPUTABLE.
    """
    import numpy as np
    if not by_map or any(len(v) == 0 for v in by_map.values()):
        return {"status": "NOT_COMPUTABLE", "mean": None, "ci_low": None, "ci_high": None,
                "empty_maps": [k for k, v in by_map.items() if len(v) == 0]}
    rng = np.random.default_rng(seed)
    names = list(by_map)
    arrays = [np.asarray(by_map[k], dtype=float) for k in names]
    point = float(np.mean([a.mean() for a in arrays]))
    draws = np.empty(replicates)
    for b in range(replicates):
        means = []
        for a in arrays:
            take = rng.integers(0, len(a), size=len(a))
            means.append(a[take].mean())
        draws[b] = float(np.mean(means))
    low, high = np.quantile(draws, [0.025, 0.975])
    return {"status": "OK", "mean": point, "ci_low": float(low), "ci_high": float(high),
            "replicates": replicates, "seed": seed, "n_maps": len(names)}


def six_map_report(per_map_rows: dict[str, Sequence[dict]]) -> dict:
    """Equal-weight report. A map with no S-X pair makes the cost metric NOT_COMPUTABLE."""
    sx_by_map = {}
    details = {}
    for name, rows in per_map_rows.items():
        dec = saving_decomposition(rows)
        details[name] = {
            "n_input": dec["n_input"], "n_sx": dec["n_sx"], "n_srx": dec["n_srx"],
            "exclusion": dec["n_input"] - dec["n_sx"],
        }
        sx_by_map[name] = [item["g_sx"] for item in dec["sx_main"]]
        # Identity on the triple set.
        for item in dec["srx"]:
            if abs(item["g_sx"] - item["g_sum"]) > 1e-9:
                raise AssertionError("g_SX must equal g_SR + g_RX on the common set")
    boot = stratified_paired_bootstrap(sx_by_map)
    full_rates = {}
    for name, rows in per_map_rows.items():
        if not rows:
            full_rates[name] = None
            continue
        flags = [completion_flags(r["status_S"]) for r in rows]  # reported per strategy by the caller
        full_rates[name] = None
    return {"bootstrap": boot, "maps": details, "sx_by_map": {k: list(v) for k, v in sx_by_map.items()}}


def algorithm_rng_seed(base_algorithm_seed: int, case_id: str, phase: str,
                       public_history: tuple, stream: str) -> int:
    """Derived from the algorithm seed, the case, the phase and the public history. Not from the environment seed."""
    payload = json.dumps(["tdr-v13-alg-rng", int(base_algorithm_seed), case_id, phase,
                          list(public_history), stream],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def planner_log_record(record: dict) -> dict:
    """Drop anything a planner must not see. Called before a log line is stored where the planner can read it."""
    banned = {"hidden_failure_parcels", "air_hidden", "true_K", "environment_seed",
              "generator_seed_formula", "K", "F"}
    return {k: v for k, v in record.items() if k not in banned and "hidden" not in k.lower()}


EPISODE_STATUSES = (
    "COMPLETED_ONLINE",
    "COMPLETED_CONTINGENCY",
    "NO_LEGAL_COMPLETION_FOUND",
    "HARD_CONSTRAINT_VIOLATION",
)


def classify_episode(*, verified_complete: bool, used_contingency_finish: bool,
                     hard_violation: bool, finish_cost: float | None) -> tuple[str, float | None]:
    """Map an execution outcome onto the four v1.3 statuses. The last two have no finite cost."""
    if hard_violation:
        return "HARD_CONSTRAINT_VIOLATION", None
    if verified_complete and not used_contingency_finish:
        return "COMPLETED_ONLINE", finish_cost
    if used_contingency_finish and finish_cost is not None:
        return "COMPLETED_CONTINGENCY", finish_cost
    if verified_complete and finish_cost is not None:
        return "COMPLETED_ONLINE", finish_cost
    return "NO_LEGAL_COMPLETION_FOUND", None
