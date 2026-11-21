"""Read-only diagnostic on the sealed M46 X terminal plans.

Does not write into fresh_new and does not start a search. At most four
native evaluations per map, charged to a local budget of 8.
"""
from pathlib import Path
import json, pickle, random, sys, time, types
HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "M47_schedule_closed_exchange_core_20261121"
SEAL = HERE.parent / "M46_paid_training_robust_joint_20261121"
sys.path.insert(0, str(CORE))
from research import *  # noqa: F401,F403
from tdr.alns import Budget, SearchStats
from tdr.complete_joint import candidate_air_ok, version
from tdr.expected_cost import expected_j, failure_prob
from tdr.joint_air_promote import air
from tdr.schedule_closed_exchange import geometries

rows = []
physical_cap = Budget(8, None)
for case in ["C50", "R50", "RC50", "C100", "R100", "RC100"]:
    inst, phys, alg = setup(case, "M47", True)
    phys.set_active()
    blob = pickle.loads((SEAL / f"fresh_new/{case}/X_live/normal_terminal_final.pkl").read_bytes())
    _ci, _cp, plan, ev, state, ref = blob
    assert alg._nominal_reference_H == ref
    ctx = types.SimpleNamespace(
        inst=inst, phys=phys, alg=alg, state=state, H=ref, makespan_cap=ref,
        mode="nominal", live_budget=physical_cap, live_stats=SearchStats(),
    )
    parent_version = version(plan)
    rng = random.getstate()
    empty = {}
    assert geometries(plan, ev, ctx, empty) == [] and empty["skip"] == "NO_ORIGINAL_MATURE_FULLPOOL_CAS"
    alg._mature_fullpool_air_sets = {tuple(sorted(air(plan)))}
    alg._schedule_closed_emitted = 0
    diag = {}
    tic = time.process_time()
    out = geometries(plan, ev, ctx, diag)
    cpu = time.process_time() - tic
    assert version(plan) == parent_version and random.getstate() == rng
    assert all(air(q) == air(plan) and candidate_air_ok(plan, q, d) for q, d in out)
    tried = []
    parent_j = expected_j(ev.cost, plan, inst, phys, failure_prob(alg)) if ev.feasible else None
    for q, desc in out:
        if physical_cap.evals_left() <= 0:
            break
        ee = rr.evaluate_plan(q, inst, phys, state, ref, "M47_CLOSED_EXCHANGE_DIAGNOSTIC", budget=physical_cap)
        child_j = expected_j(ee.cost, q, inst, phys, failure_prob(alg)) if ee.feasible and ee.cost is not None else None
        tried.append(dict(
            feasible=bool(ee.feasible),
            violations=list(ee.violations[:4]),
            cost=ee.cost,
            parent_cost=ev.cost,
            parent_J=parent_j,
            J=child_j,
            j_gain=None if child_j is None or parent_j is None else parent_j - child_j,
            cross=desc["real_cross"],
            air=len(air(q)),
            hover_s=desc["predicted_hover_s"],
            energy_kwh=desc["predicted_energy_kwh"],
            proxy_j_gain=desc["proxy_j_gain"],
            detour_yuan=desc["geometric_detour_yuan"],
        ))
    rows.append(dict(case=case, parent_air=len(air(plan)), parent_cost=ev.cost,
                     candidates=len(out), cpu_s=cpu, diag=diag, tried=tried))
    print(case, "candidates", len(out), "feasible", [t["feasible"] for t in tried],
          "j_gain", [None if t["j_gain"] is None else round(t["j_gain"], 3) for t in tried],
          "cpu", round(cpu, 3), flush=True)
out_path = HERE / "CLOSED_EXCHANGE_DIAGNOSTIC.json"
out_path.write_text(json.dumps(dict(rows=rows, native_budget_used=physical_cap.used, python=sys.version), indent=1))
print("wrote", out_path, "native", physical_cap.used)
