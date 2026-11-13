from dbg import *
from tdr import simulate as sim
o=sim.compute_cut
def cc(tl,t_fail,fd):
    t=o(tl,t_fail,fd)
    mid=[(d,st.sid,round(st.start,1),round(st.end,1)) for d,ss in tl.drone_stages.items() for st in ss if st.kind=='SERVICE' and d!=fd and st.start<t<st.end-1e-9]
    print('t_fail %.1f fd %s t_cut %.1f'%(t_fail,fd,t),'mid-service at cut:',mid); return t
sim.compute_cut=cc
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
