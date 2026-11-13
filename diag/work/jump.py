import sys; sys.path.insert(0,'.')
import greedy_air as g
from drv import *
tr,plan,ev,inst=g.greedy('R100',target=0.15,log=False)
print(tr[-6:])
print({k:round(v,1) for k,v in ev.cost_breakdown.items()})
tl=ev.timeline
print('truck_finish',{k:round(v) for k,v in tl.truck_finish.items()})
for sid,s in plan.sorties.items(): print(sid,s.drone,s.truck,s.launch_vid,s.rec_vid,s.air)
print([ (d,[(round(x.start),round(x.end),getattr(x,'kind',None)) for x in l][:12]) for d,l in list(tl.drone_stages.items())[:2]])
print(ev.waits if hasattr(ev,'waits') else '')
