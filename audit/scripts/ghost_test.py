import sys,json,os
ROOT='/workspace/thesis/audit/proj'
sys.path.insert(0, ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
OUT='/workspace/thesis/proj/outputs'
pk,nd='data/package_gh200_light1.json','nominal_gh200_L1_1000'
case,seed=sys.argv[1],int(sys.argv[2])
pkg=json.load(open(pk)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
for strat in 'SX':
    world=HiddenWorld(inst,case,seed)
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strat,alg,rngs,recovery_eval_budget=1000)
    print(case,seed,strat,os.environ.get('AUDIT_FIXGHOST'),ep.status,ep.evaluation.cost if ep.evaluation else None,ep.notes[:2])
