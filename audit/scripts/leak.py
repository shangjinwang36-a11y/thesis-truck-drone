import sys
from capture import *
import random,zlib
conf,cases,n,forced=sys.argv[1],sys.argv[2].split(','),int(sys.argv[3]),int(sys.argv[4])
tot=0;leaks=0;ep_with=0
for case in cases:
    for seed in range(1,n+1):
        pkg,phys,alg,nd=setup(conf); inst=load_instance(pkg,case)
        if conf=='light': phys=phys.for_case(pkg.get('case_fleet'),case)
        plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
        nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
        air=sorted(p for s in plan.sorties.values() for p in s.air)
        if forced:
            rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode()))
            failed=tuple(rng.sample(air,min(forced,len(air))))
            world=TestWorld(inst,case,failed)
        else:
            world=HiddenWorld(inst,case,seed); failed=tuple(world._HiddenWorld__failed)
        rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
        ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,'S',alg,rngs,recovery_eval_budget=300)
        obs={o.parcel_id for o in ep.observations if not o.air_delivery_available}
        served={st['parcel'] for seg in ep.segments for st in seg['stages'] if st['kind']=='SERVICE' and st.get('parcel')}
        # ground-delivered failed parcels are fine; leak = failed parcel air-served w/o observation
        lk=set(failed)&served-obs
        tot+=len(failed); leaks+=len(lk); ep_with+=bool(lk)
        print(conf,case,seed,ep.status,'failed',len(failed),'observed',len(obs),'leaked',sorted(lk),flush=True)
print('TOTAL failed',tot,'leaked',leaks,'episodes with leak',ep_with)
