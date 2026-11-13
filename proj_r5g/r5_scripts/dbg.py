import sys, json, os
ROOT='/workspace/thesis/proj_r5'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); strats=sys.argv[4] if len(sys.argv)>4 else 'SX'
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
alg=AlgorithmConfig.from_dict(dict(pkg['algorithm_protocol']['default_parameters'])); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
print('nominal',nom.cost,'H',H)
for st in strats:
    w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    ep=simulate.run_episode(inst,plan,nom,H,phys,w,st,alg,rngs,recovery_eval_budget=1000,max_replans=60)
    print('==',st,ep.status,ep.evaluation.cost,{k:round(v,1) for k,v in ep.evaluation.cost_breakdown.items()},{k:v for k,v in (ep.evaluation.counts or {}).items() if k in ('truck_finish',)})
    for r in ep.replans[1:]:
        print(r.index,'t=%.0f'%r.time_s,r.observed_parcels,'cost',round(r.cost,1),(r.recovery or '')[:200], {k:r.stats.get(k) for k in ('init_source','init_cost','final_cost','patch_back','milp_status','n_init_catalog_entries')})
    for o in ep.observations: 
        if not o.air_delivery_available: print('  FAIL',o.parcel_id,round(o.time_s),o.drone_id)
