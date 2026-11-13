import math,sys
from enum_event import *
conf,case,seed=sys.argv[1],sys.argv[2],int(sys.argv[3])
inst,phys,alg,H,evs=capture(conf,case,seed,n_events=1)
e=evs[0]; st=e['state']; np_=e['new_plan']; fs=e['kw']['frag_sid']; fr=np_.sorties[fs]
rows,frag,res=enum_event(inst,phys,H,e,'X',n_support=8)
fc=inst.parcel_to_customer[fr.handover[-1]]
print('failure customer',fc,'handover',fr.handover,'air rem',fr.air)
tally=collections.defaultdict(collections.Counter)
for r in rows:
    tally[r['truck']][(r['status'],r['viol'][:40])]+=1
for k,v in tally.items(): print(k,dict(v))
for r in rows:
    if r['truck'] in('t5','t2') and r['ent']['kind']=='support' and r['ent']['ref']==fc and r['ent']['served']==[]:
        print(r['truck'],r['ent']['pos'],r['status'],r['viol'],r['cost'])
