"""逐票强制转空送：对名义计划中的每个地送票，枚举全部转空候选(不限 max_new)，
完整评价，统计拒绝原因与成本变化。"""
import json,sys,collections,re,time
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
base=evaluate_plan(plan,inst,phys,st0,H)
print(case,'base cost',round(base.cost,2),'H',round(H))
def code(v):
    return re.split(r'[:@(]',v)[0]
tally=collections.Counter(); per_parcel={}
improve=0; n_try=0; deltas=[]
ground=[p for p in inst.parcel_mass if moves.parcel_delivery(plan,p) and moves.parcel_delivery(plan,p)[0]=='G']
t0=time.time()
for p in ground:
    cands=moves.air_candidates(plan,inst,phys,p,max_new=400,near_visits=12)
    best=None; stat=collections.Counter()
    for c in cands:
        q=plan.clone(); moves.remove_parcel(q,p); 
        if not moves.apply_air(q,inst,p,c):
            stat['APPLY_FAIL']+=1; continue
        ev=evaluate_plan(q,inst,phys,st0,H)
        n_try+=1
        if ev.feasible:
            stat['FEASIBLE']+=1; d=ev.cost-base.cost
            if best is None or d<best: best=d
        else:
            k=ev.status+':'+(code(ev.violations[0]) if ev.violations else '')
            stat[k]+=1
    tally.update(stat); per_parcel[p]=(len(cands),best,dict(stat))
    if best is not None: deltas.append(best)
print('ground parcels',len(ground),'candidates evaluated',n_try,'secs',round(time.time()-t0))
print('rejection tally',dict(tally))
nf=sum(1 for v in per_parcel.values() if v[1] is not None)
print('parcels with >=1 feasible candidate',nf,'; with improving (delta<0)',sum(1 for d in deltas if d<-1e-9))
ds=sorted(deltas)
if ds: print('best delta per parcel: min %.2f median %.2f max %.2f'%(ds[0],ds[len(ds)//2],ds[-1]))
print('parcels with 0 candidates',sum(1 for v in per_parcel.values() if v[0]==0))
json.dump({p:[v[0],v[1],v[2]] for p,v in per_parcel.items()},open(f'/workspace/thesis/diag/probe_{case}.json','w'))
