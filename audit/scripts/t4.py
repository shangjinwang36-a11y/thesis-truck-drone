from enum_event import *
inst,phys,alg,H,ev=capture('spec','C50',1,n_events=1)
rows,frag,res=enum_event(inst,phys,H,ev[0],'X',n_support=6,all_positions=True)
bad=[r for r in rows if r['status']=='INVALID_CUSTODY']
print(len(bad)); print(collections.Counter((r['ent']['kind'],r['ent']['pos'],r['ent']['ref'] if r['ent']['kind']=='support' else 'v') for r in bad).most_common(20))
print(bad[0]['viol'], bad[0]['ent'])
print('routes',{k:[(v,res.visits[v].customer,res.visits[v].ground) for v in vs] for k,vs in res.routes.items()})
print('frag',frag)
print({s.sid:(s.drone,s.truck,s.launch_vid,s.rec_vid,s.air,s.handover,s.started) for s in res.sorties.values()})
print('holder p027',ev[0]['state'].parcel_holder['p027'])
