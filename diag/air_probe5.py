import json,sys,collections
from pathlib import Path
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state, schedule_plan, stage_energy
from tdr import moves
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config'])
root=Path(sys.argv[1]); case=sys.argv[2]
inst=load_instance(pkg,case)
plan,cost,H=load_case_nominal(inst,root/case)
st0=initial_state(inst,phys)
ground=[p for p in inst.parcel_mass if moves.parcel_delivery(plan,p)[0]=='G']
cls=collections.Counter(); ex=[]
for p in ground:
    for c in moves.air_candidates(plan,inst,phys,p,max_new=30,near_visits=8):
        q=plan.clone(); moves.remove_parcel(q,p)
        if not moves.apply_air(q,inst,p,c): continue
        ev=evaluate_plan(q,inst,phys,st0,H)
        if ev.status!='ENERGY_INFEASIBLE': continue
        tl=schedule_plan(q,inst,phys,st0)   # no waits
        # per-sortie standalone energy (no charge): max single-sortie consumption
        single=0; hover_wait=0; 
        worst=None
        for d,stages in tl.drone_stages.items():
            # consumption per sortie from L..R inclusive
            cur=0; cs=None
            for stg in stages:
                if stg.kind in('L','CRUISE','SERVICE','WAIT','R'):
                    cur+=stage_energy(stg,phys)
                    if stg.kind=='WAIT': hover_wait+=stage_energy(stg,phys)
                    if stg.kind=='R':
                        single=max(single,cur); cur=0
        lim=phys.e_cap-phys.e_min
        k='single_sortie_exceeds' if single>lim+1e-6 else 'chain_cumulative'
        cls[k]+=1
        if len(ex)<3 and k=='chain_cumulative': ex.append((p,ev.violations[0][:200],single,lim))
        cls['wait_hover_energy_kwh_sum']+=hover_wait
print(dict(cls)); print(ex)
print('e_cap',phys.e_cap,'e_min',phys.e_min,'hover kW',phys.hover_power(1.0),'charge kW per slot',phys.slot_ac_kw*phys.slot_efficiency,'AC budget kwh',phys.truck_initial_ac_kwh)
