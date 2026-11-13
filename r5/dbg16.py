import sys, json, os, dataclasses
ROOT='/workspace/thesis/proj_r5g'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p, strat = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
land=os.environ.get('LAND','1')=='1'; soft=os.environ.get('SOFT','0')=='1'
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkg=json.load(open('data/package_light.json')); cfg=dict(pkg['config']); cfg.update(land_and_wait=land, soft_h=soft)
phys=PhysicalConfig.from_dict(cfg)
ad=dict(pkg['algorithm_protocol']['default_parameters']); ad.update(reassign_adopt_only_if_best=True, joint_inflight_retarget=True, slot_aware_recovery=True, unlaunched_repair=True)
alg=AlgorithmConfig.from_dict(ad); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom,H,phys,w,strat,alg,rngs,recovery_eval_budget=1000,max_replans=60)
lt=sum(r.stats.get('unlaunched_tries',0) for r in ep.replans); lo=sum(r.stats.get('unlaunched_ok',0) for r in ep.replans)
print(case,seed,strat,'land',land,'soft',soft,ep.status,round(ep.evaluation.cost,2) if ep.evaluation is not None and ep.evaluation.cost else None,'landing tries/ok',lt,lo,'replans',len(ep.replans), [n[:90] for n in ep.notes[:3]])
