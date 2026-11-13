import sys,json,os
sys.path.insert(0,'/workspace/thesis/proj/src'); os.chdir('/workspace/thesis/proj')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
case,seed,strat,nom=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4]
budget=int(sys.argv[5]) if len(sys.argv)>5 else 1000
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
alg.recovery_decision="milp"
inst=load_instance(pkg,case); plan,cost,H=load_case_nominal(inst,Path(nom)/case)
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,fs,fp,fd,prev_state=None):
    new,st,info=orig(plan,tl,inst,phys,t_cut,t_fail,fs,fp,fd,prev_state)
    print('TRUNC t_cut',round(t_cut,1),'t_fail',round(t_fail,1),fp,fd,'sid',fs,'energy',{d:round(e,2) for d,e in st.drone_energy.items()},'ac',{k:round(v,2) for k,v in st.truck_ac.items()})
    return new,st,info
simulate.truncate=tr
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
ep=simulate.run_episode(inst,plan,nom_ev,H,phys,HiddenWorld(inst,case,seed),strat,alg,simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0),recovery_eval_budget=budget)
print(ep.status, ep.evaluation.cost if ep.evaluation else None); import collections; print(collections.Counter(x.split(':')[0]+':'+x.split(':')[1][:30] if ':' in x else x[:30] for n in ep.notes for x in n.replace('INITIAL_RECOVERY_FAILED:','').split(',')))
for r in ep.replans: print(r.index,r.status,r.cost,{k:v for k,v in r.stats.items() if k in('init_source','residual_feasible','n_init_evals','final_cost','init_cost')})
