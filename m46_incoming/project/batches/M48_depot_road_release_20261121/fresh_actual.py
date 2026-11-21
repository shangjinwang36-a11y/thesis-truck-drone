from pathlib import Path
import sys,os,json,hashlib
HERE=Path(__file__).resolve().parent
SOURCE_ROOT=HERE.parent/"M48_depot_road_release_core_20261121"
M47_BATCH=HERE.parent/"M47_bounded_actual_20261121"
sys.path.insert(0,str(M47_BATCH))
sys.path.insert(0,str(SOURCE_ROOT))
from research import *
ROOT=HERE
CORE_FREEZE=read(SOURCE_ROOT/"EXPERIMENT_CORE_FREEZE.json")
def check_core():
    assert all(hashlib.sha256((SOURCE_ROOT/n).read_bytes()).hexdigest()==h for n,h in CORE_FREEZE.items())
K1_FROZEN=ROOT.parent/"K1_R10_S_warm_restore_20261120/K1"
from dataclasses import replace
from multiprocessing import Pool
from tdr.verify import verify_plan
from tdr.hidden_world import TestWorld
from tdr.simulate import initial_run_state,_state_record
from bill import bill
from finish_accounting import finish_candidate_calls
from initial_observer import observe_initializations

def _shift_inner(job):
    variant,case,arm,stream,seed,hmode=job
    assert stream == "dev", "M12 is development-only; real270701 worlds/driver not generated"
    folder=ROOT/variant/"executions"/hmode/stream
    dest=folder/f"{case}_{seed}_{arm}.json"
    assert not dest.exists(),"Each predeclared bounded job must execute fresh, never reuse a saved row"
    check_core()
    assert seed in (1001,1002) and arm in "SRX" and hmode=="own" and stream=="dev"
    inst,phys,alg=setup(case,variant)
    # MAIN is the ALNS budget. INIT stays alg.recovery_init_eval_budget (100).
    # A failed init may extend that init budget once by MAIN (original rescue).
    # Do not add INIT into MAIN or set an override that merges them.
    main_budget=alg.deterministic_recovery_eval_budget
    assert alg.recovery_init_eval_budget==100 and main_budget==1000
    assert alg.recovery_eval_budget_override is None
    raw=read(ROOT.parent/"M47_bounded_actual_20261121"/"M47_CANDIDATE"/"nominal"/("X" if arm=="X" else "S")/case/"nominal_plan.json")["plan"]
    hvariant="F2" if hmode=="common_F2" else variant
    if hmode == "frozen_K1":
        hvariant="frozen_K1_HS_original_numeric"
        H=read(K1_FROZEN/"nominal/S"/case/"nominal_plan.json")["H_s"]
    else:
        H=read(ROOT.parent/"M47_bounded_actual_20261121"/"M47_CANDIDATE"/"nominal"/"S"/case/"nominal_plan.json")["H_s"]
    assert hmode in ("own","common_F2","frozen_K1")
    assert hmode!="common_F2" or H==read(F2/"F2/nominal/S"/case/"nominal_plan.json")["H_s"]
    p=plan_from_dict(raw);pol="S" if arm=="S" else "X"
    from private_root import m20_s
    assert H==read(m20_s(case))["H_s"]==alg._nominal_reference_H
    import tdr.simulate as loaded_simulate,tdr.moves as loaded_moves
    assert Path(loaded_simulate.__file__).resolve()==(SOURCE_ROOT/"source/proj_r6/src/tdr/simulate.py").resolve()
    assert Path(loaded_moves.__file__).resolve()==(SOURCE_ROOT/"source/proj_r6/src/tdr/moves.py").resolve()
    # Existing recorded worlds only. Never sample or rewrite a same-seed witness.
    from private_root import witness as recorded_witness
    assert stream=="dev"
    witness=recorded_witness(case,seed)
    if not witness.is_file():
        raise FileNotFoundError("RECORDED_WORLD_WITNESS_MISSING:"+str(witness))
    saved=read(witness); flags=saved["flags"]
    if not isinstance(flags, list):
        raise ValueError("RECORDED_WORLD_WITNESS_FLAGS_NOT_A_LIST:"+str(witness))
    world=TestWorld(inst,case,tuple(sorted(flags)))
    from tdr.alns import Budget
    with rr.audit_evaluations() as startup_audit:
        ev=rr.evaluate_plan(p,inst,phys,rr.initial_state(inst,phys),H,"PRE_EXECUTION_NOMINAL_VERIFY",budget=Budget(1,None))
    dump(ROOT/variant/"startup_ledgers"/hmode/stream/f"{case}_{seed}_{arm}.json", startup_audit.summary())
    assert ev.feasible and verify_plan(inst,None,p,pol,phys,H).ok,(case,arm,H,ev.violations)
    start=time.perf_counter()
    with rr.audit_evaluations() as audit, finish_candidate_calls() as finish_counts:
        try:
            with observe_initializations(ROOT/variant/'observer/formal'/hmode/stream/f'{case}_{seed}_{arm}',world,inst,phys,alg) as observed_world:
                ep=rr.run_episode(inst,p,ev,H,phys,observed_world,pol,alg,rr.derive_rngs(alg.base_algorithm_seed,case,"recovery",0),recovery_eval_budget=main_budget,recovery_wall_s=None,cut_mode="snapshot",max_replans=inst.n,ground_finish=True)
        finally:
            dump(ROOT/variant/"live_ledgers"/hmode/stream/f"{case}_{seed}_{arm}.json",dict(ledger=audit.summary(),finish_candidates=dict(finish_counts)))
    elapsed=time.perf_counter()-start
    seg=rr.clean(ep.segments);obs=rr.clean(ep.observations)
    emergency=ep.ground_finish_verified
    paid=ep.ground_finish_cost if emergency else ep.evaluation.cost if ep.status=="COMPLETED_VERIFIED" else None
    replay=rr.verify_replay(inst,replace(phys,soft_h=True) if emergency else phys,seg,H,pol)
    parts=bill(seg,phys,H);ledger=audit.summary()
    row=dict(world_source=str(witness),world_source_sha256=hashlib.sha256(witness.read_bytes()).hexdigest(),nominal_source_sha256=hashlib.sha256((ROOT.parent/"M47_bounded_actual_20261121"/"M47_CANDIDATE"/"nominal"/("X" if arm=="X" else "S")/case/"nominal_plan.json").read_bytes()).hexdigest(),sync_proxy_mode=alg._sync_proxy_mode,loaded_source_hash=hashlib.sha256((SOURCE_ROOT/"source/proj_r6/src/tdr/simulate.py").read_bytes()).hexdigest(),loaded_moves_file=str(SOURCE_ROOT/"source/proj_r6/src/tdr/moves.py"),loaded_driver_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),H_source=hvariant,variant=variant,case=case,arm=arm,policy=pol,stream=stream,seed=seed,hmode=hmode,H=H,paid=paid,parts=parts,seconds=elapsed,status=ep.status,emergency=emergency,valid=replay.ok,delivered=replay.delivered,parcels=inst.n,delta=abs(replay.cost-paid) if paid is not None else None,min_energy=min(replay.min_energy.values(),default=None),calls=ledger["accepted_calls"],budget_extensions=[b.get("extensions",[]) for b in ledger["budgets"]])
    from tdr.complete_joint import version
    row.update(input_plan_version=version(p),actual_loaded_simulate=loaded_simulate.__file__,actual_loaded_moves=loaded_moves.__file__,nominal_role="X" if arm=="X" else "S",recovery_policy=pol,core_root=str(SOURCE_ROOT),execution_pid=os.getpid())
    check_core()
    dump(dest,dict(row=row,finish_candidates=dict(finish_counts),flags=sorted(flags),observations=obs,replay=replay,ledger=ledger,segments=seg,notes=ep.notes,replans=ep.replans))
    assert replay.ok and replay.delivered==inst.n and paid is not None and abs(paid-sum(parts.values()))<1e-7 and row["delta"]<1e-7,(dest,row)
    assert seg[0]["t0"]==0 and seg[0]["start"]==rr.clean(_state_record(initial_run_state(p,inst,phys),phys))
    assert all(o["air_delivery_available"]==(o["parcel_id"] not in flags) for o in obs)
    assert all(b["used"]==b["accepted_calls"]<=b["final_limit"] for b in ledger["budgets"])
    return row

def shift(job):
    variant,case,arm,stream,seed,hmode=job
    path=HERE/'fresh_processes'/f'{variant}_{case}_{seed}_{arm}.json'
    dump(path,dict(pid=os.getpid(),task_finished=False))
    from tdr.evaluation_audit import EvaluationAudit
    original=EvaluationAudit.record
    jp=HERE/'call_journals'/f'{variant}_{case}_{seed}_{arm}.jsonl';jp.parent.mkdir(parents=True,exist_ok=True)
    assert not jp.exists()
    def recorded(self,reason,budget,accepted):
        original(self,reason,budget,accepted)
        journal.write(json.dumps(dict(reason=reason,accepted=bool(accepted),budget_id=id(budget)if budget is not None else None,used=budget.used if budget is not None else None,limit=budget.eval_limit if budget is not None else None,scenario=bool(getattr(budget,'scenario_ledger',False))))+'\n');journal.flush()
    journal=jp.open('x');EvaluationAudit.record=recorded
    try:return _shift_inner(job)
    finally:
        EvaluationAudit.record=original;journal.close();dump(path,dict(pid=os.getpid(),task_finished=True))

def main():
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        row=shift(tuple(json.loads(sys.argv[2])));print(json.dumps(row),flush=True);return
    # The fixed controller creates state and runs preflight before any worker.
    from run_actual import main as control
    control()
if __name__=='__main__':main()
