import sys,random,json,time; sys.path.insert(0,'.')
from drv import *
from tdr.plan import ground_only_plan
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr.moves import *
def descent(case, budget=1000, topk=4, seed=1, phys_over=None, accept_worse=False):
    inst,phys,alg=setup(case,phys_over)
    st=initial_state(inst,phys); rng=random.Random(seed)
    plan=ground_only_plan(inst); ev=evaluate_plan(plan,inst,phys,st,None); used=1
    n=len(inst.customers); fails=0
    while used<budget and fails<60:
        gp=[p for v in plan.visits.values() for p in v.ground]
        p=rng.choice(gp)
        base=plan.clone(); remove_parcel(base,p)
        acs=air_candidates(base,inst,phys,p,max_new=topk,state=None)[:topk]
        # also try ground re-insertion alternatives? skip
        best=None
        for ac in acs:
            if used>=budget: break
            c=base.clone()
            if not apply_air(c,inst,p,ac): continue
            e=evaluate_plan(c,inst,phys,st,None); used+=1
            if e.feasible and (best is None or e.cost<best[0].cost): best=(e,c)
        if best and best[0].cost<ev.cost-1e-9: ev,plan=best; fails=0
        else: fails+=1
    air=sum(len(s.air) for s in plan.sorties.values())
    return dict(case=case,cost=round(ev.cost,1),air=air,share=round(air/n,2),evals=used,sorties=len(plan.sorties)),plan,ev
if __name__=='__main__':
    for c in sys.argv[1:]:
        t=time.time(); o,_,_=descent(c); o['wall']=round(time.time()-t); print(json.dumps(o),flush=True)
