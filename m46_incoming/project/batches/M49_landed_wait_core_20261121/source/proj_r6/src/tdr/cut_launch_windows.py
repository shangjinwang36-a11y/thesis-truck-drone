"""Visible-cut complete launch and follow-on anchor closure. Pure construction.
No added air tickets or physical/policy exceptions. Original gate still mandatory.
"""
def close(plan,state,mode):
 q=plan.clone();changed=[];new_anchors={}
 for s in sorted(q.sorties.values(),key=lambda x:x.sid):
  if s.started or s.launch_vid is not None or s.truck not in state.truck_in_transit:continue
  # An unfinished return is still in transit. The original gate rejects a depot
  # launch in that state, so this anchor moves onto a remaining real visit.
  rt=q.routes.get(s.truck,[])
  if not rt:continue
  first=rt[0];s.launch_vid=first;s.mode='STOP';s.lam=0.
  if s.rec_vid==first:
   # Distinct genuine visits at the same real stop: arrival, P/L, flight, R.
   # Never insert before a committed first stop or pretend L and R one event.
   if s.truck not in new_anchors:new_anchors[s.truck]=q.add_visit(s.truck,q.visits[first].customer,pos=1,ground=[]).vid
   after=new_anchors[s.truck];s.rec_vid=after
   chain=q.drone_sorties[s.drone];i=chain.index(s.sid)
   for sid in chain[i+1:]:
    nxt=q.sorties[sid]
    if not nxt.started and nxt.truck==s.truck and nxt.launch_vid==first:nxt.launch_vid=after
    else:break
  changed.append(s.sid)
 return(q,dict(changed_tasks=changed,real_duplicate_recovery_visits=new_anchors,window_mode='STOP_AT_REAL_FUTURE_VISIT'))if changed else None
