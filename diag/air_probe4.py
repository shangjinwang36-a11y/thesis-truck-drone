import json,sys,collections
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state, schedule_plan
from tdr import moves
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1]); case=sys.argv[2]
inst=load_instance(pkg,case)
plan,cost,H=load_case_nominal(inst,root/case)
st0=initial_state(inst,phys)
base=evaluate_plan(plan,inst,phys,st0,H)
print('BASE sorties:')
for s in plan.sorties.values(): print(' ',s.sid,s.drone,s.truck,'launch',s.launch_vid,s.mode,round(s.lam,2),'rec',s.rec_vid,'air',s.air,'ho',s.handover)
ground=[p for p in inst.parcel_mass if moves.parcel_delivery(plan,p)[0]=='G']
done=0
for p in ground[:20]:
    for c in moves.air_candidates(plan,inst,phys,p,max_new=30,near_visits=8):
        q=plan.clone(); moves.remove_parcel(q,p)
        if not moves.apply_air(q,inst,p,c): continue
        tl=schedule_plan(q,inst,phys,st0)
        if tl.iterations>=14 and done<2:
            done+=1
            print('\nCASE',p,c)
            new=[s for s in q.sorties.values() if p in s.air][0]
            print('new sortie',new)
            for k in (2,3,4,6,10,14):
                t=schedule_plan(q,inst,phys,st0,max_iter=k)
                print(' iter',k,{a:round(b) for a,b in t.truck_finish.items()})
            tl=schedule_plan(q,inst,phys,st0,max_iter=14)
            tr=new.truck
            print('route',tr,q.routes[tr])
            for sid,(a,b) in tl.rec_times.items():
                s=q.sorties[sid]
                if s.truck==tr or s.rec_vid in q.routes[tr]: print(' rec',sid,s.drone,'launch_vid',s.launch_vid,'rec_vid',s.rec_vid,round(a),round(b), 'launch', tl.launch_times.get(sid))
