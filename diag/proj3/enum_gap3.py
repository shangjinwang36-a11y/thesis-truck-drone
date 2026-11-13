import sys,json,random,traceback,os
sys.path.insert(0,'src')
from pathlib import Path
from multiprocessing import Pool
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate
from tdr.experiment import load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
def one(a):
    nomdir,tag,case,k,seed,strategy,budget=a
    pkg=json.load(open('data/package.json'))
    phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    inst=load_instance(pkg,case)
    plan,cost,H=load_case_nominal(inst,Path(nomdir)/case)
    air=sorted(p for s in plan.sorties.values() for p in s.air)
    rng=random.Random(hash((case,k,seed))%10**6+seed*7919)
    failed=tuple(rng.sample(air,min(k,len(air))))
    world=TestWorld(inst,case,failed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    rec=dict(nom=tag,case=case,k=k,seed=seed,strategy=strategy,n_air=len(air),n_air_share=len(air)/inst.n,nominal_cost=nom_ev.cost)
    try:
        ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strategy,alg,rngs,recovery_eval_budget=budget)
        rec.update(status=ep.status,final=ep.evaluation.cost if ep.evaluation else None,n_replans=len(ep.replans)-1)
    except Exception: rec['error']=traceback.format_exc()[-300:]
    return rec
if __name__=='__main__':
    jobs=[]
    for nomdir,tag in [('outputs_summary/nominal2','orig'),('/workspace/thesis/diag/nomdirs/60','heavy60')]:
        for case in sys.argv[1].split(','):
            for k in (1,3,6):
                for seed in range(1,6):
                    for st in ('S','X'): jobs.append((nomdir,tag,case,k,seed,st,250))
    with Pool(int(os.environ.get('POOL','4'))) as p, open(sys.argv[2],'w') as f:
        for r in p.imap_unordered(one,jobs):
            f.write(json.dumps(r)+'\n'); f.flush()
