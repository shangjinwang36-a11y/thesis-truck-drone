"""NEW bounded approximate complete-pool construction, not an equivalent cache.
Only visible geometry/resources. Every full proposal remains native/J/scenario gated.
No evaluator, world, risk-model calls, RNG, or budget extension in this module.
"""
import math,time
from .layered_global_pool import anchor_hierarchy,make_jobs,close,match_endpoints
from .joint_air_promote import air,identity

def repair_backbone(p,anchors,inst,phys,dg):
 """Approximate directed corridor repair using only existing real ground visits.
 Not a proof of global infeasibility; finite at most |visits| additions per frame.
 """
 from .moves import air_energy
 dep=(inst.depot_x,inst.depot_y);anchors={t:list(v)for t,v in anchors.items()};repairs=[]
 for _ in range(len(p.visits)+1):
  jobs,xy=make_jobs(p,anchors,inst,phys);ground={x for rt in anchors.values()for v in rt for x in p.visits[v].ground};pool=set(inst.parcel_mass)-ground;blocked=[]
  for x in sorted(pool):
   possible=False
   for j in jobs:
    source=dep if j['launch']is None else xy[j['launch']]
    for lam in [0.,.5,1.]:
     st=(source[0]+lam*(j['end'][0]-source[0]),source[1]+lam*(j['end'][1]-source[1]));dg['backbone_singleton_queries']=dg.get('backbone_singleton_queries',0)+1
     if air_energy(inst,phys,st,[x],j['end'])<=phys.e_cap-phys.e_min+phys.energy_tol:possible=True;break
    if possible:break
   if not possible:blocked.append(x)
  if not blocked:return anchors,repairs
  retained={v for rt in anchors.values()for v in rt};unused=[v for v,z in p.visits.items()if v not in retained and z.ground]
  if not unused:return anchors,repairs
  # Retain a genuine omitted ground stop as an energy corridor, no depot teleport.
  x=min(blocked,key=lambda x:(-inst.parcel_mass[x],x));cx=inst.customer(inst.parcel_to_customer[x]);v=min(unused,key=lambda v:(math.dist((cx.x,cx.y),xy[v]),v));t=p.visits[v].truck;anchors[t].append(v);anchors[t].sort(key=p.routes[t].index);repairs.append(dict(blocked_parcel=x,retained_ground_visit=v,truck=t))
 raise AssertionError('Finite monotone backbone repair exceeded original visit count')

def build(p,inst,phys,allow_cross,p_fail,diag,depot_lams=None,anchor_optimizer=None,hover_aware=False,reserve_inventory=False):
 from .moves import air_energy,air_time
 start_cpu=time.process_time();dg=diag;dg.update(algorithm='APPROXIMATE_COMPLETE_RESOURCE_CORRIDORS',energy_queries=0,packing_steps=0,singleton_queries=0,descriptors=0,packing_failures=0,structural_failures=0,yielded=0,approximate_not_exhaustive=True)
 if any(s.started or s.handover for s in p.sorties.values()):return []
 oldair=air(p);dep=(inst.depot_x,inst.depot_y);result=[];seen=set();anchor_seen=set();L=0
 for support in [False,True]:
  hierarchy=list(anchor_hierarchy(p,inst,support));L=max(L,len(hierarchy))
  for level,anchors in hierarchy:
   anchors,repairs=repair_backbone(p,anchors,inst,phys,dg);dg.setdefault('backbone_repairs',[]).append(dict(level=level,support=support,steps=repairs,upper=len(p.visits)))
   sig=tuple((t,tuple(v))for t,v in sorted(anchors.items()))
   if sig in anchor_seen:continue
   anchor_seen.add(sig);ground={x for rt in anchors.values()for v in rt for x in p.visits[v].ground};pool=set(inst.parcel_mass)-ground
   if not oldair<=pool or len(pool-oldair)<3:continue
   framep=p
   if anchor_optimizer is not None:framep,anchors,meta=anchor_optimizer(p,anchors,inst,phys);dg.setdefault('retained_reassignment',[]).append(meta)
   template,xy=make_jobs(framep,anchors,inst,phys)
   # Real vehicle arc only; launch coordinate stays on its own actual ground arc.
   choices={j['index']:[dict(j,mode='ARC',lam=lam,start=( (dep if j['launch']is None else xy[j['launch']])[0]+lam*(xy[j['rec']][0]-(dep if j['launch']is None else xy[j['launch']])[0]),(dep if j['launch']is None else xy[j['launch']])[1]+lam*(xy[j['rec']][1]-(dep if j['launch']is None else xy[j['launch']])[1])))for lam in (depot_lams if j['launch'] is None and depot_lams is not None else [0.,.5,1.]) ]for j in template}
   tail={j['index']:[xy[v]for v in anchors[j['truck']][j['layer']:]]+[dep]for j in template}
   def options(k,g):
    out=[]
    for j in choices[k]:
     dg['energy_queries']+=1;en=air_energy(inst,phys,j['start'],g,j['end'])
     if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
     dt=air_time(inst,phys,j['start'],g,j['end']);arc=math.dist(dep if j['launch']is None else xy[j['launch']],j['end'])/phys.truck_speed_m_s;road=(1.-j['lam'])*arc
     if hover_aware:
      en+=phys.hover_energy_kwh(max(0.,road-dt),0.)
      if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
     # Explicit geometric approximation, NOT exact Q: original p and prices only.
     risk=p_fail*sum(phys.wage_per_s*phys.ground_service_s+2*min(math.dist((inst.customer(inst.parcel_to_customer[x]).x,inst.customer(inst.parcel_to_customer[x]).y),v)for v in tail[k])*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)for x in g)
     cost=phys.cost_depot_kwh*en+phys.wage_per_s*(phys.prepare_s+phys.launch_s+phys.recovery_s+max(0.,dt-road))+risk
     out.append((cost,j['lam'],en,j))
    return min(out,key=lambda z:z[:3])if out else None
   difficulty={}
   for x in sorted(pool):
    feasible=[]
    for j in template:
     z=options(j['index'],[x]);dg['singleton_queries']+=1
     if z:feasible.append(z[2])
    difficulty[x]=(len(feasible),-min(feasible,default=float('inf')),-inst.parcel_mass[x],x)
   for order in ['constrained_first','mass_first']:
    dg['descriptors']+=1;groups={j['index']:[]for j in template};jobs={j['index']:dict(j)for j in template};mass={k:0. for k in groups};scores={k:0. for k in groups};todo=sorted(pool,key=lambda x:difficulty[x]if order=='constrained_first'else(-inst.parcel_mass[x],x));ok=True
    estimates={k:0. for k in groups}
    def inventory_fit(k,energy):
     if not reserve_inventory or not phys.swap_mode:return True
     rem={(j['truck'],j['lane']):phys.e_cap for j in template};spares={t:phys.spare_batteries for t in anchors}
     for j in sorted(template,key=lambda z:(z['layer'],z['lane'],z['truck'])):
      en=energy if j['index']==k else estimates[j['index']]
      if en<=0:continue
      key=j['truck'],j['lane']
      if rem[key]-en<phys.e_min-phys.energy_tol:
       spares[j['truck']]-=1
       if spares[j['truck']]<0:return False
       rem[key]=phys.e_cap
      rem[key]-=en
     return True
    for x in todo:
     offers=[];dg['packing_steps']+=1
     for k,g in groups.items():
      if mass[k]+inst.parcel_mass[x]>phys.drone_payload_limit_kg+1e-9:continue
      for at in range(len(g)+1):
       trial=g[:at]+[x]+g[at:];z=options(k,trial)
       if z and inventory_fit(k,z[2]):offers.append((z[0]-scores[k],k,at,z[1],z[0],z[3],z[2]))
     if not offers:ok=False;dg['packing_failures']+=1;break
     _,k,at,lam,score,j,en=min(offers,key=lambda z:z[:5]);groups[k].insert(at,x);jobs[k]=dict(j);mass[k]+=inst.parcel_mass[x];scores[k]=score;estimates[k]=en
    if not ok:continue
    for cross in ([False,True]if allow_cross else[False]):
     js=[dict(jobs[k])for k in sorted(jobs)];gs={k:list(v)for k,v in groups.items()}
     if cross:js,gs=match_endpoints(js,gs,inst,phys,dict(energy_time_queries=0,assignment_cells=0))
     q,bindings,carriers=close(framep,anchors,js,gs,inst,phys);errs=q.validate_structure(inst,phys,initial_carrier={f'd{k+1}':phys.home_truck(f'd{k+1}')for k in range(phys.drone_count)})
     if errs:dg['structural_failures']+=1;continue
     sig=identity(q)
     if sig in seen:continue
     seen.add(sig);assert air(q)==pool and oldair<=air(q);dg['yielded']+=1
     descriptor=dict(kind='MULTI_TASK_POOL_RECONSTRUCTION',construction='WHOLE_POOL_RESOURCE_CORRIDOR_CIRCULATION',parcels=sorted(pool-oldair),old_visits=sorted(set(p.visits)-set(q.visits)),sorties=sorted(q.sorties),new_rendezvous=[q.sorties[s].rec_vid for s in sorted(q.sorties)],air_groups={s:list(q.sorties[s].air)for s in sorted(q.sorties)},body_bindings=bindings,terminal_carriers=carriers,real_cross=sum(z['launch_truck']!=z['receive_truck']for z in bindings),all_old_air_preserved=True,all_original_flights_reconstructed=True,hierarchy_level=level,include_support=support,backbone_energy_repairs=repairs,packing_order=order,endpoint_matching=cross,nondepot_arc_first=sum(s.launch_vid is None and s.lam>0 for s in q.sorties.values()),geometry_risk_is_approximate_not_original_Q=True)
     result.append((q,descriptor))
 dg['finite_descriptor_upper']=L*2*2*(2 if allow_cross else 1);dg['hierarchy_levels']=L;dg['pure_construction_CPU_s']=time.process_time()-start_cpu;return result

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 dg=diag if diag is not None else{};items=build(p,inst,phys,allow_cross,p_fail,dg)
 for q,d in items:yield q,d
