import sys,json,collections,os
sys.path.insert(0,'/workspace/thesis/proj/src')
from pathlib import Path
from multiprocessing import Pool
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate, recovery
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
ORIG=simulate.initial_recovery
def one(a):
    nomdir,case,seed=a
    os.chdir('/workspace/thesis/proj')
    pkg=json.load(open('data/package.json'))
    phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    inst=load_instance(pkg,case); plan,cost,H=load_case_nominal(inst,Path(nomdir)/case)
    world=HiddenWorld(inst,case,seed); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    out={}
    class Stop(Exception): pass
    def wrapped(new_plan,state2,inst_,phys_,strat,gr,**kw):
        fs=kw['frag_sid']; frag=new_plan.sorties[fs]
        res=recovery.prepare_residual(new_plan.clone(),inst_)
        res_c=recovery.build_residual_candidate(res,fs,None,inst_,phys_,state2,gr,'X')
        rc=None
        for c in res_c:
            e=evaluate_plan(c,inst_,phys_,state2,H,'x')
            if e.feasible: rc=e.cost; break
        cat=recovery.RecoveryCatalog(res,frag,inst_,'X',state2,gr,phys=phys_,guard_n=48)
        rows=[]
        for i,ent in enumerate(cat._gen):
            cands=recovery.build_residual_candidate(res,fs,ent,inst_,phys_,state2,gr,'X')
            c_=None
            for c in cands:
                e=evaluate_plan(c,inst_,phys_,state2,H,'x')
                if e.feasible: c_=e.cost; break
            rows.append((i,ent['truck'],c_,ent['est']))
        feas=[r for r in rows if r[2] is not None]
        out.update(case=case,seed=seed,launch=cat.launch_truck,n=len(rows),nfeas=len(feas),residual=rc)
        if feas:
            b=min(feas,key=lambda r:r[2]); out.update(best=b[2],best_rank=b[0],best_truck=b[1])
            bS=min([r for r in feas if r[1]==cat.launch_truck],key=lambda r:r[2],default=None)
            if bS: out.update(bestS=bS[2],bestS_rank_in_S=[r for r in rows if r[1]==cat.launch_truck].index(bS))
            # best within first 96
            f96=[r for r in feas if r[0]<96]
            if f96: out['best_in_96']=min(r[2] for r in f96)
            out['cross_feas']=sum(1 for r in feas if r[1]!=cat.launch_truck)
        raise Stop()
    simulate.initial_recovery=wrapped
    try: simulate.run_episode(inst,plan,nom_ev,H,phys,world,'X',alg,rngs,recovery_eval_budget=10)
    except Stop: pass
    return out
if __name__=='__main__':
    nom=sys.argv[1]
    jobs=[(nom,c,s) for c in sys.argv[2].split(',') for s in range(1,11)]
    with Pool(6) as p:
        for r in p.imap(one,jobs):
            if r: print(json.dumps(r),flush=True)
