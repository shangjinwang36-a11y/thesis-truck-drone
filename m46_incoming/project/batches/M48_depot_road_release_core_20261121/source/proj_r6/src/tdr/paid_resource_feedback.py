"""Paid original physical/Q evidence jointly informs entire body corridors and receivers.
NEW incomplete proposal schedule. Never evaluate original risk or physics here.
"""
import math,re,time
from collections import deque
from .paid_recourse_feedback import PaidFeedback
from .complete_joint import version
from .joint_air_promote import air

class ResourceFeedback(PaidFeedback):
 def __init__(self,ctx,diag):
  super().__init__(ctx,diag);self.resource=deque();self.resource_seen=set();self.resource_turn=True;diag.update(paid_physical_observations=0,resource_proposals=0,resource_build_CPU_s=0.,receiver_pairs_examined=0,resource_geometry_queries=0)
 def observe(self,q,e,row,snapshot,descriptor):
  super().observe(q,e,row,snapshot,descriptor)
  if descriptor.get('resource_feedback_depth',0)>=1:return
  inst,phys=self.ctx.inst,self.ctx.phys;start=time.process_time();self.diag['paid_physical_observations']+=1;offers=[]
  bad={m.group(1)for v in row['violations']for m in [re.search(r'SWAP_CANNOT_FIX:(d[0-9]+)@',v)]if m};affected=bad or set(q.drone_sorties)
  from .moves import air_energy,sortie_start
  def append(z,kind,pred,bindings=None):
   v=version(z)
   if v==version(q)or v in self.resource_seen:return
   for so in z.sorties.values():
    c=inst.customer(z.visits[so.rec_vid].customer);self.diag['resource_geometry_queries']+=1
    if air_energy(inst,phys,sortie_start(inst,z,so),so.air,(c.x,c.y))>phys.e_cap-phys.e_min+phys.energy_tol:return
   if z.validate_structure(inst,phys,initial_carrier={f'd{k+1}':phys.home_truck(f'd{k+1}')for k in range(phys.drone_count)}):return
   assert air(z)==air(q);self.resource_seen.add(v);d=dict(descriptor);d.update(refinement=kind,resource_feedback_depth=1,paid_resource_seed_version=version(q),paid_resource_seed_physical_used=row['physical_used'],paid_resource_seed_J=row['J'],approximate_risk_delta=pred,not_exact_candidate_J=True,air_groups={s:list(so.air)for s,so in z.sorties.items()})
   if bindings is not None:d['body_bindings']=bindings
   from .proposal_geometry import refresh
   d=refresh(z,d,inst);offers.append((pred,kind,v,z,d))
  # Whole real-body chain changed together; native scheduling alone decides swaps/slots.
  for lam in [.5,1.]:
   z=q.clone()
   for so in z.sorties.values():
    if so.drone in affected:so.mode='ARC';so.lam=lam
   append(z,'PAID_COMPLETE_BODY_ENERGY_CORRIDOR',-1e6 if bad else 0.)
  bindings=descriptor.get('body_bindings',[])
  if snapshot is not None and bool(self.ctx.state.nominal_cross)and bindings:
   bysid={int(z['sid']):z for z in bindings};qi={int(k):v for k,v in snapshot['sortie_Q'].items()};links=[tuple(z)for z in snapshot['pair_links']];pr=snapshot['p'];dep=(inst.depot_x,inst.depot_y)
   def geo(so,rec):
    rv=q.visits[rec];rt=q.routes[rv.truck];points=[(inst.customer(q.visits[v].customer).x,inst.customer(q.visits[v].customer).y)for v in rt[rt.index(rec):]]+[dep]
    return phys.wage_per_s*phys.handover_s+sum(phys.wage_per_s*phys.ground_service_s+2*min(math.dist((inst.customer(inst.parcel_to_customer[x]).x,inst.customer(inst.parcel_to_customer[x]).y),pt)for pt in points)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)for x in so.air)
   ids=sorted(q.sorties)
   for i,a in enumerate(ids):
    for b in ids[i+1:]:
     aa,bb=bysid[a],bysid[b]
     if(aa['layer'],aa['lane'])!=(bb['layer'],bb['lane'])or q.visits[q.sorties[a].rec_vid].truck==q.visits[q.sorties[b].rec_vid].truck:continue
     self.diag['receiver_pairs_examined']+=1;z=q.clone();z.sorties[a].rec_vid,z.sorties[b].rec_vid=z.sorties[b].rec_vid,z.sorties[a].rec_vid
     from .proposal_geometry import anchored_risk_delta
     pred=anchored_risk_delta(q,z,snapshot,inst,phys)
     carriers={t:list(phys.home_drones(t))for t in sorted(z.routes)};z.drone_sorties={f'd{k+1}':[]for k in range(phys.drone_count)};newbindings=[]
     for layer in sorted({w['layer']for w in bindings}):
      after={t:list(v)for t,v in carriers.items()}
      for w in sorted((v for v in bindings if v['layer']==layer),key=lambda v:v['sid']):
       so=z.sorties[w['sid']];d=carriers[w['launch_truck']][w['lane']];receiver=z.visits[so.rec_vid].truck;so.drone=d;z.drone_sorties[d].append(so.sid);after[receiver][w['lane']]=d;newbindings.append(dict(w,drone=d,receive_truck=receiver,rec=so.rec_vid))
      assert len({d for vs in after.values()for d in vs})==phys.drone_count;carriers=after
     append(z,'PAID_Q_PAIR_RECEIVER_BODY_CIRCULATION',pred,newbindings)
  if snapshot is not None and bool(self.ctx.state.nominal_cross):
   from .noncontiguous_pool import paid_candidates as paid_joint_tail_candidates
   for pred,z,d in paid_joint_tail_candidates(q,descriptor,inst,phys,self.ctx.state,snapshot,self.diag):
    sig=version(z)
    if sig not in self.resource_seen:
     self.resource_seen.add(sig);offers.append((pred,'PAID_Q_JOINT_GROUND_OWNERSHIP',sig,z,d))
  self.resource.extend((z,d)for _,__,___,z,d in sorted(offers,key=lambda x:x[:3]));self.diag['resource_build_CPU_s']+=time.process_time()-start;self.diag.setdefault('resource_bounds',[]).append(dict(seed_version=version(q),flight_count=len(q.sorties),upper=2+len(q.sorties)*(len(q.sorties)-1)//2,queued=len(offers),uses_only_same_paid_snapshot=True,ranking='Approximate receiver geometry and paid original Qi/Qij topology; no candidate exact risk trial'))
 def next(self):
  if self.resource and self.resource_turn:
   self.resource_turn=False;self.diag['resource_proposals']+=1;return self.resource.popleft()
  item=super().next();self.resource_turn=True
  if item is not None:return item
  if self.resource:self.diag['resource_proposals']+=1;return self.resource.popleft()
  return None
