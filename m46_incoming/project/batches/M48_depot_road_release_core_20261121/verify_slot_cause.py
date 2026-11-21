from research import *
from tdr.alns import Budget,SearchStats,eval_counted
from tdr.joint_dual import terminal_inventory
from process_state import record
record('independent_slot_audit');z=read(ROOT/'diagnostics/dual_visible/RC100/VISIBLE_INPUT.json');inst,phys,alg=setup('RC100','M14',True);phys.set_active();p=plan_from_dict(z['old_common_child']);st=rr.initial_state(inst,phys);st.nominal_cross=True;H=alg._nominal_reference_H;b=Budget(1,None);s=SearchStats();intervals=[]
with rr.audit_evaluations()as au,cap_physical(1,reference_H=H)as en:
 try:
  e=eval_counted(p,inst,phys,st,H,'INDEPENDENT_SLOT_CAUSE',s,b);assert not e.feasible;tl=e.timeline
  for k in range(phys.drone_count):
   dr=f'd{k+1}';ontruck=phys.home_truck(dr);onstart=0.
   for sid in p.drone_sorties.get(dr,[]):
    so=p.sorties[sid];lt=tl.launch_times[sid];rt=tl.rec_times[sid]
    intervals.append(dict(drone=dr,truck=ontruck,start=onstart,end=lt[1],reason='ON_TRUCK_UNTIL_L_END',sid=sid));rec=p.visits[so.rec_vid].truck;intervals.append(dict(drone=dr,truck=rec,start=rt[0],end=rt[1],reason='REAL_R_CHANNEL',sid=sid));ontruck=rec;onstart=rt[1]
   intervals.append(dict(drone=dr,truck=ontruck,start=onstart,end=tl.truck_finish[ontruck],reason='ON_TRUCK_AFTER_LAST_R'))
  peaks={}
  for truck in p.routes:
   xs=[x for x in intervals if x['truck']==truck and x['end']>x['start']+1e-9];events=sorted([(x['start'],1)for x in xs]+[(x['end'],-1)for x in xs],key=lambda x:(x[0],x[1]));count=peak=0;when=0
   for t,delta in events:
    count+=delta
    if count>peak:peak=count;when=t
   peaks[truck]=dict(peak=peak,time=when,active=[x for x in xs if x['start']<=when+1e-8 and x['end']>when+1e-8])
  proof=dict(violations=e.violations,H=H,terminal_stock=terminal_inventory(p,phys)[0],peaks=peaks,intervals=intervals,classification='Real intermediate physical stock overlap, not terminal-stock excess or a demonstrated simulator bug; moving recoveries is a construction hypothesis, not permission to raise slots.')
  dump(ROOT/'SLOT_CAUSE_INDEPENDENT_AUDIT.json',proof)
 finally:dump(ROOT/'diagnostics/SLOT_CAUSE_LEDGER.json',dict(ledger=au.summary(),envelope=en.summary()))
record('independent_slot_audit',True,dict(calls=1));print({k:v for k,v in peaks.items()if v['peak']>phys.truck_drone_slots})
