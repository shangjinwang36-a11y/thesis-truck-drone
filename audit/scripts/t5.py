from enum_event import *
inst,phys,alg,H,ev=capture('spec','C50',1,n_events=1)
rows,frag,res=enum_event(inst,phys,H,ev[0],'X',n_support=6,all_positions=True)
x=[r for r in rows if r['truck']!=r['launch']]
c=collections.Counter((r['truck'],r['status'],len(r['ent']['served'])) for r in x)
for k,v in sorted(c.items()): print(k,v)
print('state truck_ac',ev[0]['state'].truck_ac, 'drone_energy',ev[0]['state'].drone_energy)
print('frag energy',ev[0]['state'].drone_start['d3'])
print([ (r['ent']['kind'],r['ent']['ref'],r['ent']['pos'],r['ent']['served'],round(r['cost'],1)) for r in x if r['cost'] is not None][:10])
