from dbg import *
from tdr import simulate as sim
o=sim.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,fsid,fp,fd,prev_state=None):
    print('TRUNC t_fail %.1f cut %.1f fd %s sid %s'%(t_fail,t_cut,fd,fsid))
    for sid,s in plan.sorties.items():
        rt=tl.rec_times.get(sid)
        if rt and rt[1]>t_cut: 
            print('  sid',sid,s.drone,'launch_truck',s.launch_truck,'rec_vid',s.rec_vid,'truck',plan.visits[s.rec_vid].truck if s.rec_vid in plan.visits else None,'R start/end %.1f %.1f'%rt, 'arr', round(tl.drone_arrival.get(sid,-1),1),'visit_arr',round(tl.visit_arr.get(s.rec_vid,-1),1))
    return o(plan,tl,inst,phys,t_cut,t_fail,fsid,fp,fd,prev_state=prev_state)
sim.truncate=tr
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
