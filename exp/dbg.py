import sys, json, random, zlib, os
ROOT='/workspace/thesis/proj'; sys.path.insert(0, ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
def setup(pkgf='data/package_light.json', budget=1000):
    pkg=json.load(open(pkgf)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    alg.recovery_eval_budget_override=budget; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
    return pkg,phys,alg
def run(case,seed,forced,strat,nom='nominal_light1000',pkgf='data/package_light.json',budget=1000):
    pkg,phys,alg=setup(pkgf,budget)
    inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
    plan,ncost,H=load_case_nominal(inst,Path(ROOT+'/outputs/'+nom)/case)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    air=sorted(p for s in plan.sorties.values() for p in s.air)
    rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode()))
    failed=tuple(rng.sample(air,min(forced,len(air))))
    world=TestWorld(inst,case,failed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strat,alg,rngs,recovery_eval_budget=budget)
    return inst,plan,phys,ep,failed
if __name__=='__main__':
    case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
    inst,plan,phys,ep,failed=run(case,seed,forced,strat)
    print('failed',failed,'status',ep.status,'e_min',phys.e_min)
    for n in ep.notes[:8]: print('NOTE',n[:400])
