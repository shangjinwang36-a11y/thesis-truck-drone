import json,sys,collections,re,statistics,dataclasses
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import moves
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1]); case=sys.argv[2]; sample=int(sys.argv[3])
inst=load_instance(pkg,case)
plan,cost,H=load_case_nominal(inst,root/case)
st0=initial_state(inst,phys)
base=evaluate_plan(plan,inst,phys,st0,H)
print('base finishes',{k:round(v) for k,v in base.timeline.truck_finish.items()},'H',round(H))
ground=[p for p in inst.parcel_mass if moves.parcel_delivery(plan,p)[0]=='G']
import random; random.Random(1).shuffle(ground)
rows=[]
for p in ground[:sample]:
    for c in moves.air_candidates(plan,inst,phys,p,max_new=30,near_visits=8):
        q=plan.clone(); moves.remove_parcel(q,p)
        if not moves.apply_air(q,inst,p,c): continue
        ev=evaluate_plan(q,inst,phys,st0,H)
        tl=ev.timeline
        rec=dict(p=p,kind=c.kind,status=ev.status,viol=(ev.violations or [''])[0][:60],cost=ev.cost)
        if tl:
            over=max(tl.truck_finish.values())-H
            rec['over']=over; rec['waits']=sum(tl.waits.values()) if tl.waits else 0.0
            rec['maxwait']=max(tl.waits.values()) if tl.waits else 0.0
            rec['nwaits']=len(tl.waits or {})
            # relaxed charging
        rows.append(rec)
cnt=collections.Counter(r['status'] for r in rows); print(cnt)
hx=[r for r in rows if r['status']=='INFEASIBLE_RESOURCE']
print('H_EXCEEDED rows',len(hx),'with waits>0',sum(1 for r in hx if r.get('waits',0)>1),'median over',statistics.median(r['over'] for r in hx) if hx else None)
print('maxwait==3600 count',sum(1 for r in hx if abs(r.get('maxwait',0)-3600)<1))
print('sample',hx[:5])
en=[r for r in rows if r['status']=='ENERGY_INFEASIBLE']
print('energy infeasible',len(en),'with waits>0',sum(1 for r in en if r.get('waits',0)>1),'sample',en[:3])
json.dump(rows,open('/workspace/thesis/diag/probe2_%s.json'%case,'w'))
