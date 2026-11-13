"""Capture the recovery state at each failure event (first N events) for a case/seed, both configs."""
import sys, json, os, pickle
ROOT='/workspace/thesis/audit/proj'
sys.path.insert(0, ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld, TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate

OUT='/workspace/thesis/proj/outputs'
CONF={'spec':('data/package.json','nominal_r3m03'),
      'light':('data/package_light.json','nominal_lightR1000')}

def setup(conf):
    pk, nd = CONF[conf]
    pkg=json.load(open(pk)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
    return pkg,phys,alg,nd

class Stop(Exception): pass

def capture(conf, case, seed=None, forced=None, n_events=1, strat='X'):
    pkg,phys,alg,nd=setup(conf)
    inst=load_instance(pkg,case)
    if conf=='light': phys=phys.for_case(pkg.get('case_fleet'),case)
    plan,ncost,H=load_case_nominal(inst, Path(OUT)/nd/case)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    if forced:
        import random,zlib
        air=sorted(p for s in plan.sorties.values() for p in s.air)
        rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode()))
        world=TestWorld(inst,case,tuple(rng.sample(air,min(forced,len(air)))))
    else:
        world=HiddenWorld(inst,case,seed)
    events=[]
    orig=simulate.initial_recovery
    def hook(new_plan,state2,inst_,phys_,strategy,ground_required,**kw):
        events.append(dict(cut=dict(last),new_plan=new_plan.clone(),state=state2,gr=set(ground_required),kw=dict(kw)))
        if len(events)>=n_events: raise Stop()
        return orig(new_plan,state2,inst_,phys_,strategy,ground_required,**kw)
    simulate.initial_recovery=hook
    otr=simulate.truncate
    last={}
    def tr(plan_,tl,inst_,phys_,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
        last.update(t_cut=t_cut,t_fail=t_fail,drone=failed_drone); return otr(plan_,tl,inst_,phys_,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=prev_state)
    simulate.truncate=tr
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    try:
        ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strat,alg,rngs,recovery_eval_budget=1000)
    except Stop:
        pass
    finally:
        simulate.initial_recovery=orig; simulate.truncate=otr
    return inst,phys,alg,H,events
