"""Shared complete-input fingerprint for registration and its zero-native audit.

INIT and MAIN stay separate fields. The rescue rule is the original one-time
extension of the init budget, not a merged budget.
"""
import hashlib
import pickle


def budget_contract(alg) -> dict:
    contract = dict(
        init_eval=alg.recovery_init_eval_budget,
        main_eval=alg.deterministic_recovery_eval_budget,
        rescue="one extension of the init budget by main_eval when init finds nothing",
        wall=None,
        override=alg.recovery_eval_budget_override,
    )
    if contract["init_eval"] != 100 or contract["main_eval"] != 1000 or contract["override"] is not None:
        raise AssertionError("recovery budgets drifted from INIT 100 and MAIN 1000")
    return contract


def complete_scope(inst, case, seed, pol, plan_version, h_s, alg, phys, initial_vars, rng_states, core, driver_hash, world_hash):
    return (
        inst, case, seed, pol, plan_version, h_s, vars(alg), phys, initial_vars,
        rng_states, core, driver_hash, world_hash, budget_contract(alg),
    )


def fingerprint(scope) -> str:
    return hashlib.sha256(pickle.dumps(scope, protocol=5)).hexdigest()
