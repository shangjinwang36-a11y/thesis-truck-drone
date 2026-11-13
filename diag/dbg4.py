import os
import sys
a=sys.argv[1:]
sys.argv=['x',a[0],a[1],a[2],a[3],os.environ.get('NOM','/workspace/thesis/proj/outputs_summary/nominal2'),'150']
DR=a[4]
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
    print('TRUNC t_cut',t_cut,'t_fail',t_fail,'failed',failed_parcel,failed_drone,failed_sid)
    for st in tl.drone_stages[DR]:
        if st.end>t_cut-200 and st.start<t_cut+50: print('   stage',st.kind,round(st.start,2),round(st.end,2),st.sid if hasattr(st,'sid') else '',st.truck, 'parcel',getattr(st,'parcel',None))
    return orig(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state)
simulate.truncate=tr
exec(open('multi_fail.py').read())
