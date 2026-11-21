from research import *
K1_FROZEN=ROOT.parent/"K1_R10_S_warm_restore_20261120/K1"
from dataclasses import replace
from multiprocessing import Pool
from tdr.verify import verify_plan
from tdr.hidden_world import TestWorld
from tdr.simulate import initial_run_state,_state_record
from bill import bill
from finish_accounting import finish_candidate_calls
from initial_observer import observe_initializations

def shift(job):
    variant,case,arm,stream,seed,hmode=job
    assert stream == "dev", "M12 is development-only; real270701 worlds/driver not generated"
    folder=ROOT/variant/"executions"/hmode/stream
    dest=folder/f"{case}_{seed}_{arm}.json"
    if dest.exists():
        row=read(dest)["row"];assert row["valid"] and row["delta"]<1e-7
        return row
    inst,phys,alg=setup(case,variant)
    alg.recovery_eval_budget_override=1000
    raw=read(ROOT/variant/"nominal"/("X" if arm=="X" else "S")/case/"nominal_plan.json")["plan"]
    hvariant="F2" if hmode=="common_F2" else variant
    if hmode == "frozen_K1":
        hvariant="frozen_K1_HS_original_numeric"
        H=read(K1_FROZEN/"nominal/S"/case/"nominal_plan.json")["H_s"]
    else:
        H=read((F2/"F2" if hvariant=="F2" else ROOT/hvariant)/"nominal/S"/case/"nominal_plan.json")["H_s"]
    assert hmode in ("own","common_F2","frozen_K1")
    assert hmode!="common_F2" or H==read(F2/"F2/nominal/S"/case/"nominal_plan.json")["H_s"]
    p=plan_from_dict(raw);pol="S" if arm=="S" else "X"
    # Existing recorded worlds only: no sampling/new-world generation.
    witness=J2/"J2/executions"/("own/dev" if stream=="dev" else "common_F2/verify270601")/f"{case}_{seed}_S.json"
    saved=read(witness); flags=saved["flags"]
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
                ep=rr.run_episode(inst,p,ev,H,phys,observed_world,pol,alg,rr.derive_rngs(alg.base_algorithm_seed,case,"recovery",0),recovery_eval_budget=1000,recovery_wall_s=None,cut_mode="snapshot",max_replans=inst.n,ground_finish=True)
        finally:
            dump(ROOT/variant/"live_ledgers"/hmode/stream/f"{case}_{seed}_{arm}.json",dict(ledger=audit.summary(),finish_candidates=dict(finish_counts)))
    elapsed=time.perf_counter()-start
    seg=rr.clean(ep.segments);obs=rr.clean(ep.observations)
    emergency=ep.ground_finish_verified
    paid=ep.ground_finish_cost if emergency else ep.evaluation.cost if ep.status=="COMPLETED_VERIFIED" else None
    replay=rr.verify_replay(inst,replace(phys,soft_h=True) if emergency else phys,seg,H,pol)
    parts=bill(seg,phys,H);ledger=audit.summary()
    row=dict(world_source=str(witness),world_source_sha256=hashlib.sha256(witness.read_bytes()).hexdigest(),nominal_source_sha256=hashlib.sha256((ROOT/variant/"nominal"/("X" if arm=="X" else "S")/case/"nominal_plan.json").read_bytes()).hexdigest(),sync_proxy_mode=alg._sync_proxy_mode,loaded_source_hash=hashlib.sha256((ROOT/"source/proj_r6/src/tdr/simulate.py").read_bytes()).hexdigest(),loaded_moves_file=str(ROOT/"source/proj_r6/src/tdr/moves.py"),loaded_driver_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),H_source=hvariant,variant=variant,case=case,arm=arm,policy=pol,stream=stream,seed=seed,hmode=hmode,H=H,paid=paid,parts=parts,seconds=elapsed,status=ep.status,emergency=emergency,valid=replay.ok,delivered=replay.delivered,parcels=inst.n,delta=abs(replay.cost-paid) if paid is not None else None,min_energy=min(replay.min_energy.values(),default=None),calls=ledger["accepted_calls"],budget_extensions=[b.get("extensions",[]) for b in ledger["budgets"]])
    dump(dest,dict(row=row,finish_candidates=dict(finish_counts),flags=sorted(flags),observations=obs,replay=replay,ledger=ledger,segments=seg,notes=ep.notes,replans=ep.replans))
    assert replay.ok and replay.delivered==inst.n and paid is not None and abs(paid-sum(parts.values()))<1e-7 and row["delta"]<1e-7,(dest,row)
    assert seg[0]["t0"]==0 and seg[0]["start"]==rr.clean(_state_record(initial_run_state(p,inst,phys),phys))
    assert all(o["air_delivery_available"]==(o["parcel_id"] not in flags) for o in obs)
    assert all(b["used"]==b["accepted_calls"]<=b["final_limit"] for b in ledger["budgets"])
    return row

def main():
    variant,stream,hmode=sys.argv[1:4]
    seeds=range(1001,1011) if stream=="dev" else range(read(ROOT/"protocol.json")["verification"]["samples_per_map"])
    state=read(ROOT/"state.json");state.pop("completed",None);state["current_progress_file"]=str(ROOT/variant/f"progress_{stream}_{hmode}.json");state.update(phase="complete_shift_experiments",pid=os.getpid(),worker_tasks=[variant,stream,hmode],log=str(ROOT/f"{variant}_{stream}_{hmode}.log"));dump(ROOT/"state.json",state)
    rows=[]
    arms=sys.argv[4] if len(sys.argv)>4 else "SRX"
    jobs=[(variant,c,a,stream,s,hmode) for c in rr.CASES for s in seeds for a in arms]
    # Schedule large cases first to avoid a slow tail, without changing a world or budget.
    jobs.sort(key=lambda j:("100" not in j[1],j[1],j[4],j[2]))
    with Pool(int(os.environ.get("TD_WORKERS","4"))) as pool:
        for row in pool.imap_unordered(shift,jobs):
            rows.append(row);print("VERIFIED",len(rows),len(jobs),row["case"],row["seed"],row["arm"],round(row["paid"],5),round(row["seconds"],2),flush=True)
            dump(ROOT/variant/f"progress_{stream}_{hmode}.json",dict(completed=len(rows),total=len(jobs),last=row))
    dump(ROOT/variant/f"rows_{stream}_{hmode}.json",rows)
    state.update(phase="shift_batch_completed",pid=None,completed=len(rows),next="paired equal-map analysis; do not promote automatically");dump(ROOT/"state.json",state)
if __name__=="__main__":main()
