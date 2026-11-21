"""M43 NEW bounded approximate retained-ground/task-pool/energy construction.
No exact risk/physics calls, no future flags, no budget/RNG use. Native gates required.
"""
import math,time
from .owned_backbone_pool import road_length
from .proposal_geometry import anchored_risk_delta,refresh

def reassign(p,anchors,inst,phys):
 q=p.clone();routes={t:list(rt)for t,rt in anchors.items()};dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in p.visits.items()};moves=[];n=sum(map(len,routes.values()))
 def at(rt,i):return xy[rt[i]]if 0<=i<len(rt)else dep
 for _ in range(n):
  best=None
  for a,ra in sorted(routes.items()):
   for i,v in enumerate(ra):
    if not p.visits[v].ground:continue
    remove=math.dist(at(ra,i-1),at(ra,i+1))-math.dist(at(ra,i-1),xy[v])-math.dist(xy[v],at(ra,i+1))
    for b,rb in sorted(routes.items()):
     if a==b:continue
     for j in range(len(rb)+1):
      delta=remove+math.dist(at(rb,j-1),xy[v])+math.dist(xy[v],at(rb,j))-math.dist(at(rb,j-1),at(rb,j));key=(delta,a,b,i,j,v)
      if delta < -1e-7 and(best is None or key<best):best=key
  if best is None:break
  delta,a,b,i,j,v=best;routes[a].pop(i);routes[b].insert(j,v);q.visits[v].truck=b;moves.append(dict(vid=v,old_owner=a,new_owner=b,retained_road_delta_m=delta))
 retained={v for rt in routes.values()for v in rt}
 for t,rt in q.routes.items():q.routes[t]=list(routes[t])+[v for v in rt if v not in retained]
 return q,routes,dict(moves=moves,step_upper=n,actual_retained_ground_reassigned=True,not_whole_truck_permutation=True)

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 from .resource_corridor_pool import build
 dg=diag if diag is not None else{};start=time.process_time();dg['algorithm']='M43_RETAINED_NONCONTIGUOUS_GROUND_POOL_ENERGY';dg['resource']={};count=0
 for q,d in build(p,inst,phys,allow_cross,p_fail,dg['resource'],depot_lams=[0.],anchor_optimizer=reassign,hover_aware=True,reserve_inventory=True):
  d.update(construction='NONCONTIGUOUS_RETAINED_GROUND_POOL_ENERGY',approximate_hover_and_spare_reservation=True,first_depot_ARC_lambda_zero=True,parent_ground_meters=road_length(p,inst),complete_candidate_ground_meters=road_length(q,inst));count+=1;yield q,refresh(q,d,inst)
 dg['yielded']=count;dg['CPU_s']=time.process_time()-start

def paid_candidates(q,descriptor,inst,phys,state,snapshot,dg):
 from .multi_binding_skeleton import body_flow
 from .moves import sortie_start,air_energy
 from .complete_joint import version
 if any(s.started or s.handover for s in q.sorties.values()):return []
 ts=sorted(q.routes);out=[];seen=set();before=road_length(q,inst);upper=0
 for ai,a in enumerate(ts):
  for b in ts[ai+1:]:
   ra=q.routes[a];rb=q.routes[b]
   # Two separated genuine blocks per truck, with a retained real stop between.
   for i in range(max(0,len(ra)-2)):
    for j in range(max(0,len(rb)-2)):
     for reverse in[False,True]:
      upper+=1;z=q.clone();aa=[i,i+2];bb=[j+2,j]if reverse else[j,j+2];moved=[ra[k]for k in aa]+[rb[k]for k in bb]
      if not all(q.visits[v].ground for v in moved):continue
      for x,y in zip(aa,bb):z.routes[a][x],z.routes[b][y]=rb[y],ra[x]
      if sorted(tuple(rt)for rt in z.routes.values())==sorted(tuple(rt)for rt in q.routes.values()):continue
      for t in[a,b]:
       for v in z.routes[t]:z.visits[v].truck=t
      for so in z.sorties.values():
       if so.launch_vid is not None:so.truck=z.visits[so.launch_vid].truck
       so.launch_truck=so.truck
      if body_flow(z,state,inst,phys)is None:continue
      if z.validate_structure(inst,phys,initial_carrier=state.drone_carrier):continue
      if not any(s.truck!=z.visits[s.rec_vid].truck for s in z.sorties.values()):continue
      valid=True
      for so in z.sorties.values():
       c=inst.customer(z.visits[so.rec_vid].customer)
       if air_energy(inst,phys,sortie_start(inst,z,so),so.air,(c.x,c.y))>phys.e_cap-phys.e_min+phys.energy_tol:valid=False;break
      if not valid:continue
      v=version(z)
      if v in seen:continue
      seen.add(v);road=road_length(z,inst);pred=(road-before)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)+anchored_risk_delta(q,z,snapshot,inst,phys);d=dict(descriptor,construction='PAID_Q_NONCONTIGUOUS_GROUND_BODY_POOL',resource_feedback_depth=1,paid_resource_seed_version=version(q),actual_noncontiguous_visits=moved,moved_ground_parcels=sorted(x for v in moved for x in z.visits[v].ground),parent_ground_meters=before,complete_candidate_ground_meters=road,approximate_risk_delta=pred,not_exact_candidate_J=True,not_whole_truck_route_permutation=True);out.append((pred,z,refresh(z,d,inst)))
 dg.setdefault('noncontiguous_catalogue',[]).append(dict(seed_version=version(q),finite_frames_entered=upper,structural_complete=len(out),formula='2*sum_{a<b} max(0,|ra|-2)*max(0,|rb|-2)',same_original_paid_snapshot=True))
 return sorted(out,key=lambda x:(x[0],version(x[1])))
