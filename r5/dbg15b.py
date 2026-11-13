import sys,os,pickle,json,dataclasses
ROOT='/workspace/thesis/proj_r5g'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr import recovery
case=sys.argv[2]; strat=sys.argv[3]
d=pickle.load(open(sys.argv[1],'rb'))
pkg=json.load(open('data/package_light.json')); pkg['config']['land_and_wait']=False; phys=PhysicalConfig.from_dict(dict(pkg['config']))
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
_,_,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/case)
st=d['state']; np_=d['plan']; fs=d['kw'].get('frag_sid')
res=recovery.prepare_residual(np_,inst)
print('started:',[(s.sid,s.drone,s.air,s.rec_vid,s.start_pos) for s in res.sorties.values() if s.started], 'frag',fs)
for s in [s for s in res.sorties.values() if s.started]:
    cs=recovery._landing_candidates(res,s.sid,inst,phys,st,d['gr'],strat,40)
    print('landing cands for',s.sid,s.drone,len(cs))
    for c in cs[:2]:
        ev=evaluate_plan(c,inst,phys,st,H,'L'); print('  ',ev.feasible,ev.violations[:2])
from tdr.alns import Budget, SearchStats
info={}
b=Budget(200,None)
opt,reasons,cat=recovery.initial_recovery(np_,st,inst,phys,strat,d['gr'],H=H,extra_pool=[],frag_sid=fs,stats=SearchStats(),budget=b,rescue_evals=1000,info=info,use_milp=True,joint=True,slot_aware=True,unlaunched=True)
print('RESULT',opt is not None,{k:v for k,v in info.items() if k.startswith(('joint','landing','slot'))}, reasons[:2])
print('---- trace')
orig=recovery.eval_counted
def tr(plan,inst_,phys_,state_,H_,reason,stats_,budget_):
    ev=orig(plan,inst_,phys_,state_,H_,reason,stats_,budget_)
    if ev is not None: print('EV',[ (s.sid,s.drone,s.landed) for s in plan.sorties.values() if s.started and s.landed], ev.feasible, ev.violations[:1])
    return ev
recovery.eval_counted=tr
info={}; b=Budget(200,None)
recovery.initial_recovery(np_,st,inst,phys,strat,d['gr'],H=H,extra_pool=[],frag_sid=fs,stats=SearchStats(),budget=b,rescue_evals=1000,info=info,use_milp=True,joint=True,slot_aware=True,unlaunched=True)
