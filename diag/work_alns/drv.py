import json,sys,time,dataclasses,random
sys.path.insert(0,'src')
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.nominal import build_nominal
from tdr.simulate import derive_rngs
def setup(case, phys_over=None, alg_over=None):
    pkg=json.load(open('data/package.json'))
    phys=PhysicalConfig.from_dict(pkg['config'])
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    if phys_over: phys=dataclasses.replace(phys,**phys_over)
    if alg_over:
        for k,v in alg_over.items(): setattr(alg,k,v)
    inst=load_instance(pkg,case)
    return inst,phys,alg
def run(case, budget=1000, phys_over=None, alg_over=None):
    inst,phys,alg=setup(case,phys_over,alg_over)
    rngs=derive_rngs(alg.base_algorithm_seed, inst.case_id,'nominal',0)
    t=time.time()
    res=build_nominal(inst,phys,alg,rngs,eval_budget=budget)
    ev=res.evaluation
    n=len(inst.customers)
    plan=res.plan
    air=sum(len(s.air) for s in plan.sorties.values())
    out=dict(case=case,budget=budget,over=phys_over,cost=round(ev.cost,2),air=air,share=round(air/n,3),
      sorties=len(plan.sorties),drones_used=len({s.drone for s in plan.sorties.values()}),wall=round(time.time()-t,1),
      bd={k:round(v,1) for k,v in ev.cost_breakdown.items()})
    return out,res,inst,phys,alg
if __name__=='__main__':
    case=sys.argv[1]; b=int(sys.argv[2]); po=json.loads(sys.argv[3]) if len(sys.argv)>3 else None
    o=run(case,b,po)[0]; print(json.dumps(o,ensure_ascii=False))
