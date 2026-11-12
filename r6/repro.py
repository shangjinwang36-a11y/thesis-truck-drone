import sys, json, random
sys.path.insert(0,'/workspace/thesis/proj_r6/src')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
case, seed, strat, nomX = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
nomS = sys.argv[5] if len(sys.argv)>5 else nomX.replace('X_seed','S_seed')
pkg=json.load(open('data/package_light.json'))
phys=PhysicalConfig.from_dict(pkg['config']); ad=dict(pkg['algorithm_protocol']['default_parameters'])
alg=AlgorithmConfig.from_dict(ad); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
_,_,H=load_case_nominal(inst, Path(nomS)/case)
plan,_,_=load_case_nominal(inst, Path(nomX if strat=='X' else nomS)/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'N')
world=HiddenWorld(inst,case,seed); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom,H,phys,world,strat,alg,rngs,recovery_eval_budget=1000,cut_mode='snapshot')
print(ep.status, ep.evaluation.cost if ep.evaluation else None); print(ep.notes[:4])
