from enum_event import *
from tdr.recovery_milp import solve_recovery_milp
inst,phys,alg,H,evs=capture('spec','C50',3,n_events=1)
e=evs[0]; res=R.prepare_residual(e['new_plan'],inst)
m=solve_recovery_milp(res,e['kw']['frag_sid'],inst,phys,e['state'],'X',e['gr'],top_k=6)
print(m.status,m.n_stops)
for en,ob in zip(m.entries,m.objective): print(en['truck'],en['kind'],en['ref'],len(en['served']),en['served'],round(ob,2))
