import sys, json, pickle
sys.path.insert(0,'src')
from tdr import schedule, evaluate
orig = schedule.schedule_plan
cap=[]
def spy(plan, inst, phys, state=None, max_iter=14, waits=None):
    tl = orig(plan, inst, phys, state, max_iter, waits)
    if not tl.converged and not cap:
        cap.append((plan.clone(), inst, phys, state))
    return tl
evaluate.schedule_plan = spy
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import build_case_nominal
pkg=json.load(open('data/package_light.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
CASE=sys.argv[1]; inst=load_instance(pkg,CASE); phys=phys.for_case(pkg.get('case_fleet'),CASE)
build_case_nominal(inst,phys,alg,'r6/smoke/diag2',eval_budget=1000,cross_launch=True)
plan,inst,phys,state=cap[0]
print('cycle?',evaluate.has_wait_cycle(plan))
for s in plan.sorties.values():
    lt=plan.visits[s.launch_vid].truck if s.launch_vid else None
    print(s.sid,s.drone,'L',lt, plan.routes[lt].index(s.launch_vid) if lt else None, s.mode,'R',plan.visits[s.rec_vid].truck, plan.routes[plan.visits[s.rec_vid].truck].index(s.rec_vid), 'air',len(s.air))
print({d:plan.drone_sorties[d] for d in plan.drone_sorties})
for it in (5,10,14,22,40):
    tl=orig(plan,inst,phys,state,it)
    print(it,{k:round(v) for k,v in tl.truck_finish.items()}, tl.converged)
