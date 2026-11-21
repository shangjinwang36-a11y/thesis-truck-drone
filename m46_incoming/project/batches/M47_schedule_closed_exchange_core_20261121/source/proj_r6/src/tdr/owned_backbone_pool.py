"""M42 NEW approximate whole ground-ownership + task/body/cut-window mechanism.
No evaluations/worlds/flags/RNG/budget objects. O(N^3+L*N^3*T) construction,
finite N ownership descents; not an exhaustive or equivalent search claim.
"""
import math,time
from .joint_air_promote import identity,air

def road_length(p,inst):
 dep=(inst.depot_x,inst.depot_y)
 def xy(v):
  c=inst.customer(p.visits[v].customer);return c.x,c.y
 return sum(sum(math.dist(a,b)for a,b in zip([dep]+[xy(v)for v in rt],[xy(v)for v in rt]+[dep]))for rt in p.routes.values())

def ownership_descent(p,inst,dg):
 """Exact route-distance deltas guide a finite approximate multi-block construction.
 Full ground visits really move across owners; ALL air tasks reconstructed later.
 """
 q=p.clone();dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in p.visits.items()};trucks=sorted(q.routes);moves=[];n=len(q.visits);dg.update(ownership_delta_queries=0,ownership_steps=0,ownership_step_upper=n)
 def at(rt,i):return xy[rt[i]]if 0<=i<len(rt)else dep
 for step in range(n):
  best=None
  for ai,a in enumerate(trucks):
   ra=q.routes[a]
   for b in trucks[ai+1:]:
    rb=q.routes[b]
    # Multi-ground-tail exchange changes whole subsequent ownership, not labels.
    for i in range(len(ra)+1):
     for j in range(len(rb)+1):
      if i==len(ra)and j==len(rb):continue
      if not any(q.visits[v].ground for v in ra[i:]+rb[j:]):continue
      before=math.dist(at(ra,i-1),at(ra,i))+math.dist(at(rb,j-1),at(rb,j));after=math.dist(at(ra,i-1),at(rb,j))+math.dist(at(rb,j-1),at(ra,i));dg['ownership_delta_queries']+=1
      key=(after-before,a,b,i,j)
      if after<before-1e-7 and(best is None or key<best):best=key
  if best is None:break
  delta,a,b,i,j=best;ra=list(q.routes[a]);rb=list(q.routes[b]);q.routes[a]=ra[:i]+rb[j:];q.routes[b]=rb[:j]+ra[i:]
  for t in[a,b]:
   for v in q.routes[t]:q.visits[v].truck=t
  moves.append(dict(source_a=a,source_b=b,cut_a=i,cut_b=j,road_delta_m=delta,moved_ground=sum(bool(q.visits[v].ground)for v in ra[i:]+rb[j:])))
  dg['ownership_steps']+=1
 return q,moves

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 from .resource_corridor_pool import build
 dg=diag if diag is not None else{};start=time.process_time();dg.update(algorithm='M42_APPROXIMATE_OWNERSHIP_AND_CUT_STABLE_COMPLETE_POOL',yielded=0,resource={})
 if any(s.started or s.handover for s in p.sorties.values()):return
 q,moves=ownership_descent(p,inst,dg);moved=[v for v in p.visits if p.visits[v].ground and p.visits[v].truck!=q.visits[v].truck];dg['moved_ground_visits']=len(moved);dg['ground_meters_before']=road_length(p,inst);dg['ground_meters_after_descent']=road_length(q,inst)
 # Even an already ownership-optimal route can gain a cut-compatible entire pool.
 for z,d in build(q,inst,phys,allow_cross,p_fail,dg['resource'],depot_lams=[0.]):
  changed=[v for v in z.visits if z.visits[v].ground and p.visits[v].truck!=z.visits[v].truck]
  d.update(construction='JOINT_OWNED_BACKBONE_CUT_STABLE_POOL',ownership_descent=moves,moved_ground_visits=changed,moved_ground_parcels=sorted(x for v in changed for x in z.visits[v].ground),parent_ground_meters=dg['ground_meters_before'],complete_candidate_ground_meters=road_length(z,inst),first_depot_ARC_lambda_zero=True,new_approximate_mechanism_not_equivalence=True)
  assert air(p)<=air(z);assert not any(s.launch_vid is None and s.lam!=0 for s in z.sorties.values());dg['yielded']+=1;yield z,d
 dg['CPU_s']=time.process_time()-start

def paid_joint_tail_candidates(q,descriptor,inst,phys,state,snapshot,dg):
 """Whole ground-tail ownership + L/R + actual body chains, ranked by paid Qi/Qij.
 No candidate exact risk evaluation occurs here. Physical/native gate mandatory.
 """
 from .multi_binding_skeleton import body_flow
 from .proposal_geometry import anchored_risk_delta
 from .moves import sortie_start,air_energy
 from .complete_joint import version
 if any(s.started or s.handover for s in q.sorties.values()):return []
 bindings=descriptor.get('body_bindings',[])
 if not bindings:return []
 qi={int(k):v for k,v in snapshot['sortie_Q'].items()};links=[tuple(z)for z in snapshot['pair_links']];pr=snapshot['p'];dep=(inst.depot_x,inst.depot_y);owners={}
 for w in bindings:owners.setdefault(w['layer'],{})[q.visits[w['rec']].truck]=w['rec']
 out=[];parentroad=road_length(q,inst)
 for layer,vs in sorted(owners.items()):
  ts=sorted(vs)
  for ai,a in enumerate(ts):
   for b in ts[ai+1:]:
    dg['joint_owned_tail_queries']=dg.get('joint_owned_tail_queries',0)+1;ra=q.routes[a];rb=q.routes[b];i=ra.index(vs[a]);j=rb.index(vs[b]);moved=[v for v in ra[i:]+rb[j:]if q.visits[v].ground]
    if not moved:continue
    z=q.clone();z.routes[a]=ra[:i]+rb[j:];z.routes[b]=rb[:j]+ra[i:]
    for t in[a,b]:
     for v in z.routes[t]:z.visits[v].truck=t
    for so in z.sorties.values():
     if so.launch_vid is not None:so.truck=z.visits[so.launch_vid].truck
     so.launch_truck=so.truck
     if so.launch_vid is None:so.lam=0.
    if body_flow(z,state,inst,phys)is None:continue
    if z.validate_structure(inst,phys,initial_carrier=state.drone_carrier):continue
    if not any(so.truck!=z.visits[so.rec_vid].truck for so in z.sorties.values()):continue
    valid=True;ds={}
    for sid,so in z.sorties.items():
     rv=z.visits[so.rec_vid];c=inst.customer(rv.customer);en=air_energy(inst,phys,sortie_start(inst,z,so),so.air,(c.x,c.y))
     if en>phys.e_cap-phys.e_min+phys.energy_tol:valid=False;break
     rt=z.routes[rv.truck];points=[(inst.customer(z.visits[v].customer).x,inst.customer(z.visits[v].customer).y)for v in rt[rt.index(rv.vid):]]+[dep]
     geo=sum(phys.wage_per_s*phys.ground_service_s+2*min(math.dist((inst.customer(inst.parcel_to_customer[x]).x,inst.customer(inst.parcel_to_customer[x]).y),pt)for pt in points)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)for x in so.air)
     ds[sid]=geo-qi[sid]
    if not valid:continue
    road=road_length(z,inst);pred=(road-parentroad)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)+anchored_risk_delta(q,z,snapshot,inst,phys)
    nb=[dict(w,drone=z.sorties[w['sid']].drone,launch_truck=z.sorties[w['sid']].truck,receive_truck=z.visits[z.sorties[w['sid']].rec_vid].truck,rec=z.sorties[w['sid']].rec_vid)for w in bindings];d=dict(descriptor,construction='PAID_Q_JOINT_GROUND_OWNERSHIP_BODY_CUT_WINDOWS',body_bindings=nb,resource_feedback_depth=1,paid_resource_seed_version=version(q),parent_ground_meters=parentroad,complete_candidate_ground_meters=road,moved_ground_visits=moved,moved_ground_parcels=sorted(x for v in moved for x in z.visits[v].ground),real_cross=sum(so.truck!=z.visits[so.rec_vid].truck for so in z.sorties.values()),approximate_risk_delta=pred,not_exact_candidate_J=True,first_depot_ARC_lambda_zero=True)
    out.append((pred,z,d))
 return sorted(out,key=lambda v:(v[0],version(v[1])))
