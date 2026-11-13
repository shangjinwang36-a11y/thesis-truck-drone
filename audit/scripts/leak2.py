import sys
from capture import *
import random,zlib
conf,case,seed,forced='light','C50',5,5
pkg,phys,alg,nd=setup(conf); inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
air=sorted(p for s in plan.sorties.values() for p in s.air)
rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode())); failed=tuple(rng.sample(air,forced))
world=TestWorld(inst,case,failed)
rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,'S',alg,rngs,recovery_eval_budget=300)
print('failed',failed)
for o in ep.observations:
    if o.parcel_id in failed: print('obs',o.parcel_id,round(o.time_s,1),o.air_delivery_available)
for r in ep.replans: print('replan',r.index,round(r.time_s,1),'t_cut',round(r.t_cut,1))
for i,seg in enumerate(ep.segments):
    for st in seg['stages']:
        if st['kind']=='SERVICE' and st.get('parcel') in failed: print('seg',i,'SERVICE',st['parcel'],round(st['start'],1),round(st['end'],1),'seg t0,t1',round(seg['t0'],1),round(seg['t1'],1))
