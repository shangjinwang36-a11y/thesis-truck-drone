import json,sys
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1])
for case in ['C50','R50','RC50','C100','R100','RC100']:
    inst=load_instance(pkg,case)
    plan,cost,H=load_case_nominal(inst,root/case)
    ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H)
    tl=ev.timeline
    nair=sum(len(s.air) for s in plan.sorties.values())
    print(case,'cost',round(ev.cost,1),'air',nair,'/',len(inst.customers),'sorties',len(plan.sorties),'H',round(H),'finish',{k:round(v) for k,v in tl.truck_finish.items()},'visits/truck',{k:len(v) for k,v in plan.routes.items()}, 'sorties/drone',{d:len(s) for d,s in plan.drone_sorties.items()})
    print('   breakdown',{k:round(v,1) for k,v in ev.cost_breakdown.items()}, 'q_total',round(tl.q_total,2),'waits',sum(tl.waits.values()) if tl.waits else 0)
