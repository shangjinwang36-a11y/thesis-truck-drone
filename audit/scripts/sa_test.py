import sys,os,time,json
from capture import *
from multiprocessing import Pool
conf=sys.argv[1]; cases=sys.argv[2].split(','); n=int(sys.argv[3])
def one(t):
    case,seed,strat=t
    pkg,phys,alg,nd=setup(conf); inst=load_instance(pkg,case)
    if conf=='light': phys=phys.for_case(pkg.get('case_fleet'),case)
    plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    world=HiddenWorld(inst,case,seed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strat,alg,rngs,recovery_eval_budget=1000)
    return (case,seed,strat,ep.status,ep.evaluation.cost if ep.evaluation else None,len(ep.replans)-1)
if __name__=='__main__':
    tasks=[(c,s,st) for c in cases for s in range(1,n+1) for st in 'SX']
    with Pool(8) as p: out=p.map(one,tasks)
    json.dump(out,open(f'/workspace/thesis/audit/scripts/sa_{conf}_{os.environ.get("AUDIT_SUFFIXSCALE","0")}.json','w'))
    d={}
    for c,s,st,status,cost,nr in out: d.setdefault((c,s),{})[st]=(status,cost,nr)
    import statistics as S
    dl=[v['S'][1]-v['X'][1] for v in d.values() if v['S'][1] and v['X'][1] and v['S'][0]==v['X'][0]=='COMPLETED_VERIFIED' and v['S'][2]>0]
    print(conf,'SUFFIXSCALE',os.environ.get('AUDIT_SUFFIXSCALE'),'n',len(dl),'meanΔ',round(S.mean(dl),2),'sd',round(S.pstdev(dl),2),'worse',sum(v<-1e-6 for v in dl),'sumneg',round(sum(v for v in dl if v<0),1))
