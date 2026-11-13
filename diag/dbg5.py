import os
import sys
a=sys.argv[1:]
sys.argv=['x',a[0],a[1],a[2],a[3],os.environ.get('NOM','/workspace/thesis/proj/outputs_summary/nominal2'),'150']
DR=a[4]; P=a[5]
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
    new,st,info=orig(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state)
    print('TRUNC t_cut',round(t_cut,2),'t_fail',round(t_fail,2),'failed',failed_parcel,failed_drone,failed_sid,'inflight',info['inflight'])
    for sid,s in plan.sorties.items():
        if s.drone==DR:
            print('  PLAN',DR,'sortie',sid,'started',s.started,'launch',tl.launch_times.get(sid),'rec',tl.rec_times.get(sid),'air',s.air,'ho',s.handover,'truck',s.truck)
    for a in tl.actions:
        if a.kind in ('R','U') and a.info.get('drone')==DR and t_cut-300<a.end<t_cut+300: print('   ACT',a.kind,round(a.start,2),round(a.end,2),a.ref)
    print('  holder',P,st.parcel_holder.get(P))
    return new,st,info
simulate.truncate=tr
exec(open('multi_fail.py').read())
