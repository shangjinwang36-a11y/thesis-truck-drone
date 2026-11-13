import sys, json, os
ROOT='/workspace/thesis/proj_r5'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); seeds=[int(x) for x in sys.argv[4].split(',')]
extra=json.loads(sys.argv[5]) if len(sys.argv)>5 else {}
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
ad=dict(pkg['algorithm_protocol']['default_parameters']); ad.update(extra)
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
print('base_seed default',ad.get('base_algorithm_seed'))
for bs in seeds:
    ad2=dict(ad); ad2['base_algorithm_seed']=bs
    alg=AlgorithmConfig.from_dict(ad2); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
    out=[]
    for st in 'SX':
        w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
        ep=simulate.run_episode(inst,plan,nom,H,phys,w,st,alg,rngs,recovery_eval_budget=1000,max_replans=1)
        r=ep.replans[1]; out.append((st,round(r.stats['init_cost'],2),round(r.stats['final_cost'],2)))
    print('seed',bs,out,flush=True)
