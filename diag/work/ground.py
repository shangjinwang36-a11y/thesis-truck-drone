import sys; sys.path.insert(0,'.')
from drv import *
from tdr.plan import ground_only_plan
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
for c in ['C50','R50','RC50','C100','R100','RC100']:
    inst,phys,alg=setup(c)
    st=initial_state(inst,phys)
    p=ground_only_plan(inst)
    ev=evaluate_plan(p,inst,phys,st,None)
    print(c,'ground-only cost',round(ev.cost,1),{k:round(v,1) for k,v in ev.cost_breakdown.items() if k in('truck_km','c_km','c_driver','driver_s')})
