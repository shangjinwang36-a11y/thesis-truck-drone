import sys
sys.argv=['x','C50','6','3','S','/workspace/thesis/proj/outputs_summary/nominal2','250']
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
    print('TRUNC t_cut',round(t_cut),'failed_sid',failed_sid,failed_parcel,failed_drone)
    for s in plan.sorties.values():
        if s.started: print('  IN started',s.sid,s.drone,s.start_pos,s.start_time,'rec',s.rec_vid)
    new,st,info=orig(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state)
    for s in new.sorties.values():
        if s.started: print('  OUT started',s.sid,s.drone,s.start_pos,round(s.start_time),'rec',s.rec_vid,'air',s.air,'hand',s.handover)
    print('  inflight',info['inflight'])
    return new,st,info
simulate.truncate=tr
exec(open('multi_fail.py').read())
