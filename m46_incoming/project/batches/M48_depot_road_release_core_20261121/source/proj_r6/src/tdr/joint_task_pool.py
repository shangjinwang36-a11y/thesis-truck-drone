"""Nominal route-interval task-pool reconstruction, not two-ticket insertion.
Promote >=3 ground tickets together, repartition ALL incoming-flight air cargo;
close every incident L/R reference, real fleet paths and the full truck skeleton.
Pure visible construction; original complete paid J/stream0/2/H/robust gates remain.
"""
import math,itertools
from .joint_air_promote import air,identity,body_covers
from .joint_dual import terminal_inventory

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2,initial_release_tasks=False):
 from .moves import sortie_start,air_energy,air_time
 from .expected_cost import _failure_cost
 dg=diag if diag is not None else {};dg.update(raw_total=0,raw_examined=0,blocks=0,packing_rejected=0,body_nodes=0,body_unexpanded_branches=0,whole_plans_yielded=0,unsupported_primary_launch_in_block=0)
 if timeline is None or any(s.started for s in p.sorties.values()):return
 dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(s.customer).x,inst.customer(s.customer).y)for v,s in p.visits.items()};raw=[]
 def road(r):return sum(math.dist(a,b)for a,b in zip([dep]+[xy[v]for v in r],[xy[v]for v in r]+[dep]))
 for t,rt in sorted(p.routes.items()):
  for i in range(len(rt)):
   for j in range(i+3,len(rt)+1):
    block=tuple(rt[i:j])
    if any(len(p.visits[v].ground)!=1 for v in block):continue
    flights=[s for s in p.sorties.values()if s.rec_vid in block]
    if len(flights)<2 or any(s.handover for s in flights):continue
    if any(s.launch_vid in block for s in flights):dg['unsupported_primary_launch_in_block']+=1;continue
    extra=tuple(p.visits[v].ground[0]for v in block);pool=tuple(dict.fromkeys(extra+tuple(x for s in flights for x in s.air)))
    if sum(inst.parcel_mass[x]for x in pool)>len(flights)*phys.drone_payload_limit_kg+1e-9:continue
    retained=[v for v in sorted(p.visits)if v not in block];save=road(rt)-road([v for v in rt if v not in block]);dg['blocks']+=1
    def allowed(v,old):return allow_cross or p.visits[v].truck==p.visits[old].truck
    maps={v:min((q for q in retained if allowed(q,v)),key=lambda q:(math.dist(xy[v],xy[q]),q),default=None)for v in block}
    if any(v is None for v in maps.values()):continue
    variants=[maps]
    for old in block:
     for new in retained:
      if allowed(new,old)and new!=maps[old]:variants.append(dict(maps,**{})|{old:new})
    seen=set()
    for mapping in variants:
     sig=tuple(mapping[v]for v in block)
     if sig in seen:continue
     seen.add(sig)
     # Whole-truck detour savings and visible resynchronization exposure, not new rewards.
     prox=-save*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)+sum(math.dist(xy[v],xy[mapping[v]])for v in block)*phys.c_km/1000
     raw.append((prox,t,i,j,block,tuple(s.sid for s in flights),extra,pool,mapping))
 dg['raw_total']=len(raw);seen_plans=set()
 for prox,t,i,j,block,ids,extra,pool,mapping in sorted(raw,key=lambda z:(z[0],z[1],z[2],z[3],tuple(z[-1].items()))):
  dg['raw_examined']+=1;q=p.clone()
  for vid,parcel in zip(block,extra):q.visits[vid].ground.remove(parcel)
  affected=[]
  for s in q.sorties.values():
   if s.launch_vid in mapping:s.launch_vid=mapping[s.launch_vid];affected.append(s.sid)
   if s.rec_vid in mapping:s.rec_vid=mapping[s.rec_vid];affected.append(s.sid)
   if s.launch_vid is not None:s.truck=q.visits[s.launch_vid].truck
   if s.launch_truck is not None:s.launch_truck=s.truck
  for vid in block:q.remove_visit(vid)
  groups={sid:[]for sid in ids};left=set(pool)
  # Capacity/energy-constrained regret insertion across complete existing flight tasks.
  while left:
   offers=[]
   for parcel in sorted(left):
    choices=[]
    for sid in ids:
     s=q.sorties[sid];g=groups[sid]
     if sum(inst.parcel_mass[x]for x in g)+inst.parcel_mass[parcel]>phys.drone_payload_limit_kg+1e-9:continue
     start=dep if initial_release_tasks else sortie_start(inst,q,s);rec=xy[s.rec_vid];oldenergy=air_energy(inst,phys,start,g,rec)if g else 0.
     for at in range(len(g)+1):
      trial=g[:at]+[parcel]+g[at:];en=air_energy(inst,phys,start,trial,rec)
      if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
      duration=air_time(inst,phys,start,trial,rec);wait=abs(float(launch_order.get(sid,0))+duration-float(timeline.visit_arr.get(s.rec_vid,0)))
      score=phys.cost_depot_kwh*(en-oldenergy)+phys.wage_per_s*wait
      choices.append((score,sid,at))
    if not choices:offers=[];break
    choices.sort();regret=choices[1][0]-choices[0][0]if len(choices)>1 else float('inf');offers.append((-regret,-inst.parcel_mass[parcel],parcel,choices[0]))
   if not offers:break
   _,__,parcel,(_,sid,at)=min(offers);groups[sid].insert(at,parcel);left.remove(parcel)
  if left:dg['packing_rejected']+=1;continue
  for sid,g in groups.items():
   if g:q.sorties[sid].air=list(g)
   else:q.remove_sortie(sid)
  if not allow_cross and any(s.truck!=q.visits[s.rec_vid].truck for s in q.sorties.values()):continue
  for k in range(phys.drone_count):q.drone_sorties.setdefault(f'd{k+1}',[])
  if initial_release_tasks:
   # Unbound complete task skeleton: the caller jointly assigns initial real
   # bodies/launch trucks before any physical evaluation. No inherited body
   # cover is required or represented as a valid completed physical candidate.
   dg['whole_plans_yielded']+=1
   yield q,dict(kind='MULTI_TASK_POOL_RECONSTRUCTION',parcels=list(extra),old_visits=list(block),sorties=list(ids),new_rendezvous=[mapping[v]for v in block],air_groups={sid:groups[sid]for sid in ids},affected_sorties=sorted(set(affected)),proxy=prox,unbound_task_skeleton=True)
   continue
  cover={}
  # Original structural whole-fleet cover, not fictitious extra bodies or free batteries.
  for z in body_covers(q,inst,phys,launch_order,limit=4,node_cap=512,diagnostic=cover):
   inventory,_=terminal_inventory(z,phys)
   if max(inventory.values(),default=0)>phys.truck_drone_slots:continue
   sig=identity(z)
   if sig in seen_plans:continue
   seen_plans.add(sig)
   assert air(z)==air(p)|set(extra)
   oldrisk=sum(_failure_cost(p,inst,phys,p.sorties[sid])for sid in ids);newrisk=sum(_failure_cost(z,inst,phys,z.sorties[sid])for sid in ids if sid in z.sorties)
   dg['whole_plans_yielded']+=1
   yield z,dict(kind='MULTI_TASK_POOL_RECONSTRUCTION',parcels=list(extra),old_visits=list(block),sorties=list(ids),new_rendezvous=[mapping[v]for v in block],air_groups={sid:groups[sid]for sid in ids},old_air_repartitioned=any(set(p.sorties[sid].air)!=set(groups[sid])for sid in ids),affected_sorties=sorted(set(affected)),real_cross=any(s.truck!=z.visits[s.rec_vid].truck for s in z.sorties.values()),proxy=prox+p_fail*(newrisk-oldrisk),terminal_inventory=inventory,body_catalogue=dict(cover))
  dg['body_nodes']+=cover.get('nodes',0);dg['body_unexpanded_branches']+=cover.get('unexpanded_branches',0)
 dg['unexpanded_raw_geometries']=dg['raw_total']-dg['raw_examined']
