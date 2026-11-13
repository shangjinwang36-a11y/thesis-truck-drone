import json,sys,collections
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import moves
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1]); case=sys.argv[2]
inst=load_instance(pkg,case)
plan,cost,H=load_case_nominal(inst,root/case)
st0=initial_state(inst,phys)
ground=[p for p in inst.parcel_mass if moves.parcel_delivery(plan,p)[0]=='G']
it=collections.Counter(); st=collections.Counter()
ex=None
for p in ground[:20]:
    for c in moves.air_candidates(plan,inst,phys,p,max_new=30,near_visits=8):
        q=plan.clone(); moves.remove_parcel(q,p)
        if not moves.apply_air(q,inst,p,c): continue
        ev=evaluate_plan(q,inst,phys,st0,H)
        tl=ev.timeline
        if tl is None: continue
        over=ev.status=='INFEASIBLE_RESOURCE'
        it[(over,tl.iterations)]+=1
        if over and ex is None and tl.iterations<14: ex=(p,c,q,ev)
print(sorted(it.items()))
if ex:
    p,c,q,ev=ex; print(p,c,ev.violations[:3]); tl=ev.timeline
    for s in q.sorties.values(): print(s)
