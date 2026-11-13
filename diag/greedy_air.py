"""手工构造高空送计划：从名义计划出发，每步在所有地送票×候选中选成本增量最小的可行转换(即使增量>0)，
记录 空送比例-成本 曲线."""
import json,sys
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import moves
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1]); case=sys.argv[2]; steps=int(sys.argv[3])
inst=load_instance(pkg,case)
plan,cost,H=load_case_nominal(inst,root/case)
st0=initial_state(inst,phys)
cur=evaluate_plan(plan,inst,phys,st0,H)
n=len(inst.customers)
def air(pl): return sum(len(s.air) for s in pl.sorties.values())
print(case,'start air',air(plan),'cost',round(cur.cost,2),flush=True)
curve=[(air(plan),cur.cost)]
for it in range(steps):
    best=None
    for p in [p for p in inst.parcel_mass if moves.parcel_delivery(plan,p)[0]=='G']:
        for c in moves.air_candidates(plan,inst,phys,p,max_new=10,near_visits=8):
            q=plan.clone(); moves.remove_parcel(q,p)
            if not moves.apply_air(q,inst,p,c): continue
            ev=evaluate_plan(q,inst,phys,st0,H)
            if ev.feasible and (best is None or ev.cost<best[0]): best=(ev.cost,q)
    if best is None: print('no feasible conversion left at air',air(plan)); break
    plan=best[1]; curve.append((air(plan),best[0]))
    print(' step',it+1,'air',air(plan),'cost',round(best[0],2),'sorties',len(plan.sorties),flush=True)
json.dump(curve,open(f'/workspace/thesis/diag/greedy_{case}.json','w'))
