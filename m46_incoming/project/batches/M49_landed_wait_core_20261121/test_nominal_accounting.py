from tdr.nominal_accounting import cap_physical, auxiliary_used, remaining_limit
from tdr.evaluation_audit import audit_evaluations
from tdr.evaluate import evaluate_plan
from tdr.alns import Budget
from tdr.config import PhysicalConfig
from tdr.data import Instance
from tdr.plan import Plan

def test_cap_includes_historical_unbudgeted_setup_and_excludes_separate_scenarios():
    inst=Instance("tiny","T",0.,0.,());phys=PhysicalConfig(truck_count=1,drone_count=1,drones_per_truck_initial=1);p=Plan("tiny");p.routes["t1"]=[]
    with audit_evaluations() as a,cap_physical(2) as cap:
        evaluate_plan(p,inst,phys,reason="NOMINAL")
        assert auxiliary_used()==1 and remaining_limit(20)==1
        b=Budget(5,None);evaluate_plan(p,inst,phys,reason="NOMINAL",budget=b)
        sc=Budget(3,None);sc.scenario_ledger=True
        evaluate_plan(p,inst,phys,reason="SCENARIO_RECOURSE",budget=sc)
        denied=evaluate_plan(p,inst,phys,reason="NOMINAL",budget=b)
        assert denied.status=="BUDGET_EXHAUSTED" and b.used==1 and cap.used==2 and cap.denied==1
        assert sc.used==1 and not a.summary()["unbudgeted_by_reason"]
        assert all(z["accepted_calls"]==z["used"] for z in a.summary()["budgets"])
    # Recovery/outside orchestration retains the exact original acceptance semantics.
    b=Budget(2,None);evaluate_plan(p,inst,phys,budget=b);assert b.used==1

def test_old_nominal_core_exact_except_accounting_debit():
    from pathlib import Path
    old=Path("/workspace/projects/失败无人机卡车配送_20261119/old_r10_emin005_delivery_20261116/proj_r6/src/tdr/nominal.py").read_text()
    import tdr.nominal as n
    actual=Path(n.__file__).read_text()
    # The old S path stays byte-identical; remove only the explicitly authorized
    # X/alt-start opt-in dispatch before asserting the inherited old-core body.
    actual=actual.replace('    if (cross_launch and alt_start is not None\n            and getattr(alg, "x_air_preserving_core", False)):\n        from .s_air_search import search\n        return search(inst, phys, alg, rngs, alt_start, makespan_cap,\n                      eval_budget if eval_budget is not None else alg.nominal_eval_budget)\n','')
    actual=actual.replace('        ctx.joint_fragment_enabled = bool(getattr(alg, "x_joint_fragment", False))\n','')
    actual=actual.replace('from .nominal_accounting import auxiliary_used\n    # Previously unbudgeted S re-evaluation belongs to this same B, not B+1.\n    budget2 = Budget(max(0, B - used1 - hold - auxiliary_used()), None)','budget2 = Budget(max(1, B - used1 - hold), None)')
    actual=actual.replace('    state.nominal_joint_air = bool(getattr(alg, "shared_joint_air", False))\n','')
    actual=actual.replace('if (not getattr(state, "nominal_joint_air", False) and any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values())):', 'if any(s.launch_vid == vid or s.rec_vid == vid for s in plan.sorties.values()):')
    actual=actual.replace('max_new=3, state=state if getattr(state, "nominal_joint_air", False) else None)[:3]', 'max_new=3, state=None)[:3]')
    assert actual==old
