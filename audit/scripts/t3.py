from enum_event import *
import time
inst,phys,alg,H,ev=capture('spec','C50',1,n_events=1)
t=time.time()
rows,frag,res=enum_event(inst,phys,H,ev[0],'X',n_support=6,all_positions=True)
print(len(rows),time.time()-t)
import collections
print(collections.Counter((r['truck']==r['launch'],r['status']) for r in rows))
ok=[r for r in rows if r['cost'] is not None]
ok.sort(key=lambda r:r['cost'])
for r in ok[:8]: print(r['truck'],r['ent']['kind'],r['ent']['ref'],r['ent']['pos'],r['ent']['served'],round(r['cost'],2))
okS=[r for r in ok if r['truck']==r['launch']]; print('bestS',okS[0]['cost'] if okS else None)
print(collections.Counter(r['viol'][:30] for r in rows if r['cost'] is None).most_common(10))
