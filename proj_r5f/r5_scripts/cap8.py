import sys, json, os, pickle
ROOT=os.environ.get('TDR_ROOT','/workspace/thesis/proj_r5c'); sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p, strat, out = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
ad=dict(pkg['algorithm_protocol']['default_parameters']); ad['reassign_adopt_only_if_best']=True; ad['joint_inflight_retarget']=True; ad['slot_aware_recovery']=os.environ.get('SLOT','1')=='1'
alg=AlgorithmConfig.from_dict(ad); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
orig=simulate.initial_recovery
def wrap(new_plan,state2,inst_,phys_,strategy,gr,**kw):
    pl=new_plan.clone()
    r=orig(new_plan,state2,inst_,phys_,strategy,gr,**kw)
    if r[0] is None:
        kk={k:v for k,v in kw.items() if k in ('H','extra_pool','frag_sid','rescue_evals','use_milp','joint')}
        pickle.dump(dict(plan=pl,state=state2,gr=gr,strategy=strategy,kw=kk),open(out,'wb'))
    return r
simulate.initial_recovery=wrap
w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom,H,phys,w,strat,alg,rngs,recovery_eval_budget=1000,max_replans=60)
print(ep.status, getattr(ep,'stop_reasons',None), [ (r.get('slot_relief_tries'),r.get('slot_relief_ok')) for r in [getattr(x,'init_counts',{}) or {} for x in getattr(ep,'replans',[])]][-3:])
