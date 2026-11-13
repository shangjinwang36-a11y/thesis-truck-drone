import sys
sys.argv=['x','R100','7','X','r6/nominal/nom2/X_seed20261113']
sys.path.insert(0,'/workspace/thesis/proj_r6/src')
from tdr import simulate
orig=simulate.truncate
def spy(plan, tl, inst, phys, t_cut, t_fail, failed_sid, failed_parcel, failed_drone, prev_state=None, T_truck=None, T_drone=None):
    r=orig(plan, tl, inst, phys, t_cut, t_fail, failed_sid, failed_parcel, failed_drone, prev_state, T_truck, T_drone)
    d='d8'
    print('t_fail',t_fail,'T_drone',T_drone and T_drone.get(d))
    for st in tl.drone_stages[d]: print('  ',st.kind,round(st.start),round(st.end),st.truck,st.sid)
    for sid in plan.drone_sorties[d]: print('  sortie',sid,tl.launch_times.get(sid),tl.rec_times.get(sid))
    print('  state carrier',r[1].drone_carrier.get(d), r[1].drone_start[d].kind, 'inflight',r[2]['inflight'])
    return r
simulate.truncate=spy
exec(open('r6/repro.py').read())
