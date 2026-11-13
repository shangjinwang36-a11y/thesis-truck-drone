import sys,json,random,traceback,os
sys.path.insert(0,'/workspace/thesis/proj/src')
os.chdir('/workspace/thesis/proj')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate
from tdr.experiment import load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
case,k,seed,strategy=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
nomdir=sys.argv[5]; budget=int(sys.argv[6]) if len(sys.argv)>6 else 250
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
inst=load_instance(pkg,case); plan,cost,H=load_case_nominal(inst,Path(nomdir)/case)
air=sorted(p for s in plan.sorties.values() for p in s.air)
rng=random.Random(sum(map(ord,case))+seed*7919+k)
failed=tuple(rng.sample(air,min(k,len(air))))
world=TestWorld(inst,case,failed)
rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strategy,alg,rngs,recovery_eval_budget=budget)
print(ep.status,ep.notes[:6],'replans',len(ep.replans)-1,'cost',ep.evaluation.cost if ep.evaluation else None)
print('failed',failed)
