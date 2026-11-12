import sys, json, os
ROOT=os.environ.get('TDR_ROOT','/workspace/thesis/proj_r5b'); sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); orig_strat=sys.argv[4]
alt='S' if orig_strat=='X' else 'X'
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
ad=dict(pkg['algorithm_protocol']['default_parameters']); ad['reassign_adopt_only_if_best']=bool(int(os.environ.get('R5FLAG','0')))
alg=AlgorithmConfig.from_dict(ad); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
orig=simulate.initial_recovery
def wrap(new_plan,state2,inst_,phys_,strategy,gr,**kw):
    r=orig(new_plan,state2,inst_,phys_,strategy,gr,**kw)
    if r[0] is None:
        kw2=dict(kw); 
        from tdr.alns import Budget, SearchStats
        kw2['budget']=Budget(100,None); kw2['stats']=SearchStats(); kw2['info']={}
        r2=orig(new_plan,state2,inst_,phys_,alt,gr,**kw2)
        print(f'### STOP with {strategy}; same state with {alt}: opt={"FEASIBLE" if r2[0] is not None else None}', 'reasons',strategy,[x[:90] for x in r[1][:6]],'| alt reasons',[x[:90] for x in r2[1][:6]],flush=True)
    return r
simulate.initial_recovery=wrap
w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom,H,phys,w,orig_strat,alg,rngs,recovery_eval_budget=1000,max_replans=60)
print(case,seed,orig_strat,ep.status,ep.notes[:1])
