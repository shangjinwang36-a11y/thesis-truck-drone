from pathlib import Path
import os,sys,json,hashlib,time
os.environ.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",PYTHONUTF8="1")
ROOT=Path(__file__).resolve().parent
F2=ROOT.parent/"F1_sync_proxy_20261120"
J2=ROOT.parent/"J2_historical_R10_integrated_repair_20261120"
sys.path.insert(0,str(ROOT/"source/round10_recheck"))
import run_emin005 as rr
from collections import Counter
from tdr.experiment import plan_from_dict
from tdr.nominal_accounting import cap_physical
import tdr.nominal as nominal_module
from tdr.experiment import plan_to_dict

def planhash(p,inst):return hashlib.sha256(json.dumps(plan_to_dict(p,inst),sort_keys=True).encode()).hexdigest()

def read(p):return json.loads(Path(p).read_text())
def dump(p,x):rr.dump(p,x)
def setup(c,variant,cross=False,H=None):
    _,inst,phys,alg=rr.configs(c)
    alg._decision_counts=Counter();alg._permission_audit=Counter()
    alg._align_horizon=True;alg._nominal_permission=cross
    alg._search_mode="historical_R10";alg._independent_horizon=H
    alg._sync_proxy_mode="historical_R10_no_F2_proxy"
    alg.x_s_second_start=True;alg.x_adopt_s_nominal=False
    alg.x_adopt_s_if_cross=False;alg.x_same_truck_j_gate=True
    alg.x_cross_hs_cap=True;alg.x_cross_from_start=True
    alg.complete_joint_stage="terminal"
    alg.joint_task_pool=False
    alg.joint_initial_release=False
    alg.energy_window_joint=False
    alg.layered_global_pool=(variant != "HCTRL")
    alg.paid_recourse_feedback=(variant != "HCTRL")
    alg.complete_joint=(variant != "HCTRL")
    alg.joint_block=(variant != "HCTRL")
    alg.joint_dual_recovery=(variant != "HCTRL")
    alg.joint_block_dead_trial_only=(variant != "HCTRL")
    alg._nominal_reference_H=read(ROOT.parent/"K1_R10_S_warm_restore_20261120/K1/nominal/S"/c/"nominal_plan.json")["H_s"]
    alg._independent_horizon=alg._nominal_reference_H
    alg.recovery_finalists=False
    alg._integrated_from_start=False
    assert abs(phys.e_min-.05)<1e-12 and alg.failure_prob==.2
    expected=read(F2/"F2/runtime"/f"{c}_S.json")["physical"]
    assert rr.clean(phys)==expected,(c,rr.clean(phys),expected)
    return inst,phys,alg

def nominal(c):
    for arm in "SX":
        dest=ROOT/"K1/nominal"/arm/c
        if dest.exists():raise RuntimeError(f"refusing overwrite {dest}")
        H=read(ROOT/"K1/nominal/S"/c/"nominal_plan.json")["H_s"] if arm=="X" else None
        inst,phys,alg=setup(c,"K1",arm=="X",H)
        dump(ROOT/"K1/runtime"/f"{c}_{arm}.json",dict(physical=phys,algorithm=vars(alg),H=H,adopt_from=str(ROOT/"K1/nominal/S"/c) if arm=="X" else None))
        start=time.perf_counter()
        traces=[]
        original=nominal_module.optimize
        def traced_optimize(plan,ctx,budget,*args,**kwargs):
            event=dict(initial_plan_sha=planhash(plan,inst),nominal_cross=ctx.state.nominal_cross,budget=budget.eval_limit,scenario_on=getattr(ctx,"scenario_on",False))
            result=original(plan,ctx,budget,*args,**kwargs)
            event.update(used=budget.used,cost=result.evaluation.cost if result.evaluation else None)
            traces.append(event);return result
        nominal_module.optimize=traced_optimize
        try:
            with rr.audit_evaluations() as audit, cap_physical(1000) as envelope:
                meta=rr.build_case_nominal(inst,phys,alg,dest,eval_budget=1000,cross_launch=arm=="X",two_phase_b=200,adopt_from=ROOT/"K1/nominal/S"/c if arm=="X" else None)
        finally:nominal_module.optimize=original
        ledger=audit.summary()
        dump(ROOT/"K1/nominal_audit"/f"{c}_{arm}.json",dict(meta=meta,ledger=ledger,seconds=time.perf_counter()-start,permissions=dict(alg._permission_audit),envelope=envelope.summary(),optimize_calls=traces))
        assert meta["verified"] and meta["verified_plan"] and not ledger["unbudgeted_by_reason"],(c,arm,meta,ledger)
        assert all(b["accepted_calls"]==b["used"]<=b["final_limit"] for b in ledger["budgets"])
        assert sum(b["used"] for b in ledger["budgets"] if not b["scenario_ledger"])<=1000
        assert sum(b["used"] for b in ledger["budgets"] if b["scenario_ledger"])<=200
        assert envelope.used==sum(b["used"] for b in ledger["budgets"] if not b["scenario_ledger"])
        if arm=="X":
            s=plan_from_dict(read(ROOT/"K1/nominal/S"/c/"nominal_plan.json")["plan"])
            assert any(t["initial_plan_sha"]==planhash(s,inst) and t["scenario_on"] and t["nominal_cross"] for t in traces),traces
            p=plan_from_dict(read(dest/"nominal_plan.json")["plan"])
            ev=rr.evaluate_plan(p,inst,phys,rr.initial_state(inst,phys),H,"NOMINAL")
            assert ev.feasible,(c,H,ev.violations)
        print("NOMINAL",c,arm,meta.get("cost"),flush=True)
    return c

def main():
    from multiprocessing import Pool
    files=[ROOT/"research.py",ROOT/"execute_recorded.py",ROOT/"protocol.json",*sorted((ROOT/"source/proj_r6/src/tdr").glob("*.py"))]
    dump(ROOT/"source_freeze.json",{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    with Pool(4) as pool:
        for c in pool.imap_unordered(nominal,rr.CASES):print("DONE",c,flush=True)
    dump(ROOT/"state.json",dict(phase="historical_S_warm_restore",status="six_map_nominals_verified",pid=None))
if __name__=="__main__":main()
