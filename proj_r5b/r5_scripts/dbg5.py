import sys, json, os, pickle
ROOT='/workspace/thesis/proj_r5b'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
case, seed, p = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); strat=sys.argv[4]
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import make_world
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate, recovery
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
ad=dict(pkg['algorithm_protocol']['default_parameters']); ad['reassign_adopt_only_if_best']=False
alg=AlgorithmConfig.from_dict(ad); alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
orig=simulate.initial_recovery
CAP={}
def wrap(new_plan,state2,inst_,phys_,strategy,gr,**kw):
    r=orig(new_plan,state2,inst_,phys_,strategy,gr,**kw)
    if r[0] is None: CAP.update(plan=new_plan,state=state2,gr=gr,kw=kw,strategy=strategy)
    return r
simulate.initial_recovery=wrap
w=make_world(inst,case,seed,'bernoulli',p); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom,H,phys,w,strat,alg,rngs,recovery_eval_budget=1000,max_replans=60)
print(ep.status)
np_,st=CAP['plan'],CAP['state']
frag=[s for s in np_.sorties.values() if s.started]
print('t0',st.t0,'H',H)
for s in np_.sorties.values():
    if s.started: print('started sortie',s.sid,s.drone,'launch_truck',s.launch_truck,'truck',s.truck,'rec_vid',s.rec_vid,'air',s.air,'hand',s.handover)
res=recovery.prepare_residual(np_,inst)
fs=CAP['kw'].get('frag_sid')
cands=recovery.build_residual_candidate(res,fs,None,inst,phys,st,CAP['gr'],strat)
for c in cands:
    ev=evaluate_plan(c,inst,phys,st,H,'DBG')
    print('cand feasible',ev.feasible,ev.violations[:3])
    tl=ev.timeline
    if tl is not None and not ev.feasible:
        for d,stages in tl.drone_stages.items():
            for stg in stages:
                if stg.sid in [s.sid for s in np_.sorties.values() if s.started]:
                    print(d,stg.kind,round(stg.start,1),round(stg.end,1),getattr(stg,'sid',None))
    break
print('---- d7 in candidates')
for ci,c in enumerate(cands):
    print('cand',ci)
    for sid in c.drone_sorties.get('d7',[]):
        s=c.sorties[sid]
        def idx(vid):
            v=c.visits.get(vid)
            if v is None: return None
            return (v.truck, c.routes[v.truck].index(vid) if vid in c.routes[v.truck] else None)
        print('  ',sid,'started',s.started,'truck',s.truck,'launch',s.launch_vid,idx(s.launch_vid) if s.launch_vid is not None else None,'rec',s.rec_vid,idx(s.rec_vid),'air',s.air, 'mode',s.mode)
    print('  validate',c.validate_structure(inst)[:2] if hasattr(c,'validate_structure') else '')
