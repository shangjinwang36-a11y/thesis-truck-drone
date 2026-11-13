import sys,random,time,json; sys.path.insert(0,'.')
from drv import *
from tdr.plan import ground_only_plan
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr.moves import *
def greedy(case, start='ground', target=0.7, per_parcel=6, sample=20, seed=1, phys_over=None, maxsteps=200, log=True):
    inst,phys,alg=setup(case,phys_over)
    st=initial_state(inst,phys)
    rng=random.Random(seed)
    plan=ground_only_plan(inst)
    ev=evaluate_plan(plan,inst,phys,st,None)
    n=len(inst.customers)
    traj=[(0,round(ev.cost,1),round(ev.z,0))]
    snaps={'best':(ev.cost,plan.clone(),ev)}
    for step in range(maxsteps):
        air=sum(len(s.air) for s in plan.sorties.values())
        if air/n>=target: break
        gp=[p for v in plan.visits.values() for p in v.ground]
        # parcels that are ground
        cand_p=rng.sample(gp,min(sample,len(gp)))
        best=None
        for p in cand_p:
            base=plan.clone(); remove_parcel(base,p)
            acs=air_candidates(base,inst,phys,p,max_new=per_parcel,state=None)
            # keep top per_parcel by proxy + all EXTEND
            for ac in acs[:per_parcel]:
                c=base.clone()
                if not apply_air(c,inst,p,ac): continue
                e=evaluate_plan(c,inst,phys,st,None)
                if not e.feasible: continue
                if best is None or e.cost<best[0].cost-1e-9: best=(e,c,p,ac.kind)
        if best is None: break
        ev,plan=best[0],best[1]
        air=sum(len(s.air) for s in plan.sorties.values())
        traj.append((air,round(ev.cost,1),round(ev.z,0),best[3]))
        if ev.cost<snaps['best'][0]: snaps['best']=(ev.cost,plan.clone(),ev)
        if air/n>=0.6 and '60' not in snaps: snaps['60']=(ev.cost,plan.clone(),ev)
        if log: print(case,'air',air,f'{air/n:.0%}','cost',round(ev.cost,1),'sorties',len(plan.sorties),flush=True)
    return traj,plan,ev,inst,snaps,phys
if __name__=='__main__':
    case=sys.argv[1]
    tr,plan,ev,inst,snaps,phys=greedy(case,target=float(sys.argv[2]) if len(sys.argv)>2 else 0.7)
    json.dump(tr,open(f'greedy_{case}.json','w'))

    from tdr.verify import verify_plan
    from tdr.schedule import initial_state
    for k,(c_,p_,e_) in snaps.items():
        air=sum(len(s.air) for s in p_.sorties.values())
        r=verify_plan(inst,initial_state(inst,phys),p_,"NOMINAL",phys,None)
        print('VERIFY',case,k,'air',air,'cost',round(c_,1),'verify_ok',r.ok if hasattr(r,'ok') else r.to_dict(),flush=True)
    import os
    from tdr.experiment import plan_to_dict
    for k,(c_,p_,e_) in snaps.items():
        d=f'/workspace/thesis/diag/nomdirs/{k}/{case}'; os.makedirs(d,exist_ok=True)
        H=max(e_.timeline.truck_finish.values())+phys.shift_slack_s
        json.dump({"plan_id":f"{case}-g{k}","H_s":H,"algorithm_id":"greedy","plan":plan_to_dict(p_,inst)},open(d+'/nominal_plan.json','w'))
        json.dump({"cost":e_.cost,"z_s":e_.z,"breakdown":e_.cost_breakdown,"H_s":H},open(d+'/cost.json','w'))
