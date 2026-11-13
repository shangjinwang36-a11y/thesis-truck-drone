import sys
sys.argv=['x','C50','3','3','S','/workspace/thesis/proj/outputs_summary/nominal2','250']
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
    print('TRUNC t_cut',t_cut,'t_fail',t_fail)
    for a in tl.actions:
        if a.kind in('R','U') and 1600<a.end<1800: print('   ',a.kind,a.actor,a.start,a.end,a.ref,a.info.get('drone'),a.info.get('parcels'))
    return orig(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state)
simulate.truncate=tr
exec(open('multi_fail.py').read())
