import sys,json,time,traceback,os
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
ORIG=simulate.initial_recovery
def one(a):
    nomdir,tag,case,seed=a
    pkg=json.load(open('data/package.json'))
    phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    inst=load_instance(pkg,case)
    plan,cost,H=load_case_nominal(inst,Path(nomdir)/case)
    world=HiddenWorld(inst,case,seed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    rec=dict(nom=tag,case=case,seed=seed)
    orig=ORIG
    class Stop(Exception): pass
    def wrapped(new_plan,state2,inst_,phys_,strat,gr,**kw):
        fs=kw['frag_sid']; frag=new_plan.sorties[fs]
        res=recovery.prepare_residual(new_plan.clone(),inst_)
        probe=recovery.RecoveryCatalog(res,frag,inst_,'X',state2,gr)
        launch=probe.launch_truck
        out={}
        for T in sorted(new_plan.routes):
            cat=recovery.RecoveryCatalog(res,frag,inst_,'X',state2,gr)
            g=cat._gen
            cat._gen=(e for e in g if e['truck']==T)
            kw2=dict(kw); kw2.update(budget=Budget(10**7,None),stats=SearchStats(),info={},init_catalog_entries=10**9,catalog=cat,rescue_evals=0,use_milp=False)
            opt,_,_=orig(new_plan.clone(),state2,inst_,phys_,'X',gr,**kw2)
            out[T]=dict(cost=opt.ev.cost if opt else None,n=kw2['info'].get('n_catalog_entries'),desc=opt.description if opt else None)
        rec.update(launch=launch,per_truck=out,n_air_frag=len(frag.air),t_fail=state2.t0)
        raise Stop()
    simulate.initial_recovery=wrapped
    try:
        simulate.run_episode(inst,plan,nom_ev,H,phys,world,'X',alg,rngs,recovery_eval_budget=10)
    except Stop: pass
    except Exception: rec['error']=traceback.format_exc()[-300:]
    return rec
if __name__=='__main__':
    jobs=[]
    for nomdir,tag in [('outputs_summary/nominal2','orig'),('/workspace/thesis/diag/nomdirs/60','heavy60')]:
        for case in sys.argv[1].split(','):
            if tag=='heavy60' and case not in('C50','R50','RC50'): continue
            for seed in range(1,11): jobs.append((nomdir,tag,case,seed))
    with Pool(int(os.environ.get('POOL','3'))) as p, open(sys.argv[2],'w') as f:
        for r in p.imap_unordered(one,jobs):
            f.write(json.dumps(r)+'\n'); f.flush()
