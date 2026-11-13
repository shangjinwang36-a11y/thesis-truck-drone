import sys,json,time,dataclasses,traceback
sys.path.insert(0,'src')
from pathlib import Path
from multiprocessing import Pool
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate, recovery
from tdr.alns import Budget, SearchStats
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
NOMDIR=sys.argv[1] if len(sys.argv)>1 else 'outputs_summary/nominal2'
BIGB=[1000,4000]
import os
NOEX=bool(os.environ.get('NOEX'))
POOL=int(os.environ.get('POOL','7'))
def one(args):
    case,seed,strategy,main_budget=args
    pkg=json.load(open('data/package.json'))
    phys=PhysicalConfig.from_dict(pkg['config'])
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    inst=load_instance(pkg,case)
    plan,cost,H=load_case_nominal(inst,Path(NOMDIR)/case)
    world=HiddenWorld(inst,case,seed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    rec={'case':case,'seed':seed,'strategy':strategy,'events':[]}
    orig=simulate.initial_recovery
    state={'n':0}
    def wrapped(new_plan,state2,inst_,phys_,strat,gr,**kw):
        state['n']+=1
        if state['n']==1 and not NOEX:
            ex={}
            for st in ('S','X'):
                t=time.time()
                kw2=dict(kw); kw2['budget']=Budget(10**7,None); kw2['stats']=SearchStats(); kw2['info']={}
                kw2['init_catalog_entries']=10**9; kw2['catalog']=None; kw2['rescue_evals']=0
                kw2['use_milp']=False
                opt,_,cat=orig(new_plan.clone(),state2,inst_,phys_,st,gr,**kw2)
                big={}
                if opt is not None:
                    from tdr.alns import optimize, SolveContext
                    for B in BIGB:
                        rr=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',1)
                        fs=kw['frag_sid']
                        ctx=SolveContext(inst=inst_,phys=phys_,alg=alg,state=state2,H=H,mode='recovery',
                            affected_drones={new_plan.sorties[fs].drone},affected_sorties={fs},ground_required=set(gr),
                            replan_index=1,rngs=rr,catalog=cat,frag_sid=fs)
                        sol=optimize(opt.plan.clone(),ctx,Budget(B,None),stats=SearchStats(),init_ev=opt.ev)
                        big[B]=sol.evaluation.cost if sol.evaluation is not None else None
                ex[st]=dict(big=big,cost=opt.ev.cost if opt else None,desc=opt.description if opt else None,
                            n=kw2['info'].get('n_catalog_entries'),residual=kw2['info'].get('residual_cost'),wall=round(time.time()-t,1))
            rec['exhaustive']=ex
        return orig(new_plan,state2,inst_,phys_,strat,gr,**kw)
    simulate.initial_recovery=wrapped
    try:
        ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strategy,alg,rngs,recovery_eval_budget=main_budget)
        rec['status']=ep.status; rec['final_cost']=ep.evaluation.cost if ep.evaluation else None
        rec['nominal_cost']=nom_ev.cost
        rec['n_fail']=len(ep.replans)-1
        rec['events']=[dict(idx=r.index,cost=r.cost,init=r.stats.get('init_cost'),res=r.stats.get('residual_cost'),src=r.stats.get('init_source'),desc=r.recovery) for r in ep.replans[1:]]
    except Exception as e:
        rec['error']=traceback.format_exc()[-400:]
    return rec
if __name__=='__main__':
    cases=sys.argv[2].split(',')
    budget=int(sys.argv[3]); out=sys.argv[4]
    seeds=range(1,11)
    jobs=[(c,s,st,budget) for c in cases for s in seeds for st in ('S','X')]
    with Pool(POOL) as p, open(out,'w') as f:
        for r in p.imap_unordered(one,jobs):
            f.write(json.dumps(r,ensure_ascii=False)+'\n'); f.flush()
