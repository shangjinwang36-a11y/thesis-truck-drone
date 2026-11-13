import sys
sys.argv=['x','C50','3','3','S','/workspace/thesis/proj/outputs_summary/nominal2','250']
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate
orig=simulate.truncate
def tr(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
    new,st,info=orig(plan,tl,inst,phys,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state)
    print('TRUNC t_cut',round(t_cut,1),'failed',failed_sid,failed_parcel,failed_drone,'inflight',info['inflight'])
    for sid,s in plan.sorties.items():
        if s.drone=='d5':
            print('  PLAN d5 sortie',sid,'started',s.started,'launch',tl.launch_times.get(sid),'rec',tl.rec_times.get(sid),'air',s.air,'ho',s.handover,'truck',s.truck, 'lvid',s.launch_vid)
    print('  holder p005',st.parcel_holder.get('p005'),'new d5 sorties',[(sid,new.sorties[sid].started) for sid in new.drone_sorties.get('d5',[])])
    return new,st,info
simulate.truncate=tr
exec(open('multi_fail.py').read())
