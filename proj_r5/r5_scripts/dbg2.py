import sys, json, os
ROOT='/workspace/thesis/proj_r5'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); nrep=int(sys.argv[4]) if len(sys.argv)>4 else 1
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate, alns
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
alg=AlgorithmConfig.from_dict(dict(pkg['algorithm_protocol']['default_parameters'])); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
TR={}
orig=alns.eval_counted
cur=[None]
def ec(plan_,inst_,phys_,state_,H_,reason,stats,budget):
    ev=orig(plan_,inst_,phys_,state_,H_,reason,stats,budget)
    TR[cur[0]].append((reason, None if ev is None else (round(ev.cost,3) if ev.feasible else None)))
    return ev
alns.eval_counted=ec
import tdr.local_reorder as lr, tdr.cross_ops as co
import tdr.simulate as sim
# eval_counted imported by name in other modules? patch them
for m in (alns, sim):
    pass
res={}
for st in 'SX':
    cur[0]=st; TR[st]=[]
    w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    ep=simulate.run_episode(inst,plan,nom,H,phys,w,st,alg,rngs,recovery_eval_budget=1000,max_replans=nrep)
    r=ep.replans[1]; print(st,r.stats.get('init_cost'),r.stats.get('final_cost'),r.stats.get('main_by_reason'))
a,b=TR['S'],TR['X']
print(len(a),len(b))
for i,(x,y) in enumerate(zip(a,b)):
    if x!=y: print('first diff at',i,x,y); print(' S ctx',a[max(0,i-3):i+6]); print(' X ctx',b[max(0,i-3):i+6]); break
else: print('no diff in common prefix')
import collections
for nm,t in (('S',a),('X',b)):
    best=None; tr=[]
    for i,(rs,c) in enumerate(t):
        if c is not None and (best is None or c<best-1e-9): best=c; tr.append((i,rs,c))
    print(nm,'improvement trace',tr[:25])
