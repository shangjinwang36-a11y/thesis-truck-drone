from enum_event import *
inst,phys,alg,H,ev=capture('spec','C50',3,n_events=1)
e=ev[0]
rows,frag,res=enum_event(inst,phys,H,e,'X',n_support=10)
done=set(e['state'].truck_done)
ok=sorted([r for r in rows if r['cost'] is not None and r['truck'] not in done],key=lambda r:r['cost'])
for r in ok[:8]: print(r['truck'],r['ent']['kind'],r['ent']['ref'],r['ent']['pos'],r['ent']['served'],round(r['cost'],2))
print('launch',frag.launch_truck,'frag air',frag.air,'handover',frag.handover,'start_pos',frag.start_pos,'t0',e['state'].t0)
print({k:[(res.visits[v].customer,res.visits[v].ground) for v in vs] for k,vs in res.routes.items()})
b=ok[0]
# build best plan and print sortie summary
POS_OVERRIDE['pos']=b['ent']['pos']
cands=R.build_residual_candidate(res,frag.sid,b['ent'],inst,phys,e['state'],e['gr'],'X')
POS_OVERRIDE['pos']=None
for cp in cands:
    evl=evaluate_plan(cp,inst,phys,e['state'],H,'x')
    if evl.feasible and abs(evl.cost-b['cost'])<1e-6:
        print({k:[(cp.visits[v].customer,cp.visits[v].ground) for v in vs] for k,vs in cp.routes.items()})
        print({s.sid:(s.drone,s.truck,s.launch_vid,s.rec_vid,s.air,s.handover,s.started) for s in cp.sorties.values()})
        print(evl.cost_breakdown)
        break
# what the code's X final cost breakdown is
