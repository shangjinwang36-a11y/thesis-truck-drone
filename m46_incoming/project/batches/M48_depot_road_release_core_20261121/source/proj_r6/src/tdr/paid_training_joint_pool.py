"""M46 NEW paid-training robust full-pool/receiver-window/body construction.
No feedback queue, native scheduler/evaluator/J/world/RNG/budget call. Every emitted
plan goes straight through the original Work->offer physical/J/stream/H/CAS slot.
Pure-cell memo scope is ONE immutable geometry frame, never a physical outcome.
"""
import math,time
from functools import lru_cache
from .joint_air_promote import air,identity
from .proposal_geometry import refresh

def assignment(matrix):
 # Exact min cost of THIS APPROXIMATE finite assignment matrix, O(T^2 2^T).
 dp={0:(0.,())};n=len(matrix)
 for row in matrix:
  nxt={}
  for mask,(value,path)in dp.items():
   for j,cost in enumerate(row):
    if mask>>j&1 or cost is None:continue
    m=mask|1<<j;z=(value+cost,path+(j,))
    if m not in nxt or z<nxt[m]:nxt[m]=z
  dp=nxt
  if not dp:return None
 return dp.get((1<<n)-1)

def pack_frame(p,anchors,inst,phys,allow_cross,p_fail,order,dg,contexts):
 from .layered_global_pool import make_jobs,close
 from .moves import air_energy,air_time
 jobs,xy=make_jobs(p,anchors,inst,phys);dep=(inst.depot_x,inst.depot_y);T=sorted(anchors)
 if not jobs:return None
 # Deliberately incomplete visible ground/service clock. No replication of native
 # crew channels, slots, LP, swap scheduling or physical success checks for free.
 arrival={};depart={};last={}
 for t,rt in anchors.items():
  clock=0.;prev=dep;last[t]=None
  for v in rt:
   clock+=len(phys.home_drones(t))*(phys.prepare_s+phys.launch_s)+math.dist(prev,xy[v])/phys.truck_speed_m_s;arrival[v]=clock;clock+=len(p.visits[v].ground)*phys.ground_service_s+len(phys.home_drones(t))*phys.recovery_s;depart[v]=clock;prev=xy[v]
 groups={j['index']:[]for j in jobs};selected={};layers={key:[j['index']for j in jobs if(j['layer'],j['lane'])==key]for key in sorted({(j['layer'],j['lane'])for j in jobs})};layerof={k:key for key,ids in layers.items()for k in ids};frame_cpu=time.process_time()
 # Every context is an exact already-paid nominal/training timeline. Changed
 # skeleton times remain ONLY a prefix-delta projection; native gates are intact.
 projected=[]
 for cp,tl,failed in contexts:
  oldprefix={};newprefix={}
  for target,plan,rr in [(oldprefix,cp,cp.routes),(newprefix,p,anchors)]:
   for truck,route in rr.items():
    clock=0.;point=dep
    for v in route:
     cc=inst.customer(plan.visits[v].customer);pt=(cc.x,cc.y);clock+=math.dist(point,pt)/phys.truck_speed_m_s;target[v]=clock;clock+=len(plan.visits[v].ground)*phys.ground_service_s;point=pt
  clocks={v:tl.visit_arr[v]+newprefix[v]-oldprefix[v]for route in anchors.values()for v in route if v in tl.visit_arr and v in oldprefix}
  if len(clocks)!=sum(map(len,anchors.values())):dg['incomplete_paid_context']+=1;return None
  projected.append((clocks,frozenset(failed)))
 @lru_cache(None)
 def option(k,g,target):
  j=jobs[k];b=jobs[target];dg['pure_cell_misses']+=1
  if not allow_cross and j['truck']!=b['truck']:return None
  start=dep if j['launch']is None else xy[j['launch']];finish=xy[j['rec']];end=xy[b['rec']];road=math.dist(start,finish)/phys.truck_speed_m_s;mass=sum(inst.parcel_mass[x]for x in g)
  def at(lam):return(start[0]+lam*(finish[0]-start[0]),start[1]+lam*(finish[1]-start[1]))
  def flight(lam,failed):
   point=at(lam);load=mass;en=0.;dt=0.
   for x in g:
    if x in failed:continue
    c=inst.customer(inst.parcel_to_customer[x]);nxt=(c.x,c.y);dist=math.dist(point,nxt);en+=phys.fly_energy_kwh(dist,load)+phys.hover_energy_kwh(phys.air_service_s,load);dt+=dist/phys.drone_speed_m_s+phys.air_service_s;load-=inst.parcel_mass[x];point=nxt
   dist=math.dist(point,end);en+=phys.fly_energy_kwh(dist,load);dt+=dist/phys.drone_speed_m_s;dg['pure_geometry_queries']+=1;return en,dt,max(0.,load)
  def base(clock):return(0. if j['launch']is None else clock[j['launch']]+len(p.visits[j['launch']].ground)*phys.ground_service_s+len(phys.home_drones(j['truck']))*phys.recovery_s)+(j['lane']+1)*(phys.prepare_s+phys.launch_s)
  candidates={0.,1.}
  if road>0 and phys.truck_speed_m_s<phys.drone_speed_m_s:
   for clock,failed in projected:
    def arrival(lam):return base(clock)+lam*road+flight(lam,failed)[1]
    target_time=clock[b['rec']]
    if arrival(0.)<target_time<arrival(1.):
     lo=0.;hi=1.
     for _ in range(16):
      mid=(lo+hi)/2
      if arrival(mid)<target_time:lo=mid
      else:hi=mid
     candidates.add(hi)
  offers=[]
  rt=anchors[b['truck']];tail=[xy[v]for v in rt[rt.index(b['rec']):]]+[dep];Q=phys.wage_per_s*phys.handover_s
  for x in g:
   c=inst.customer(inst.parcel_to_customer[x]);Q+=phys.wage_per_s*phys.ground_service_s+2*min(math.dist((c.x,c.y),pt)for pt in tail)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)
  for lam in sorted(candidates):
   evaluations=[]
   for clock,failed in projected:
    en,dt,load=flight(lam,failed);arr=base(clock)+lam*road+dt;hover=max(0.,clock[b['rec']]-arr);truckwait=max(0.,arr-clock[b['rec']]);en+=phys.hover_energy_kwh(hover,load)+phys.hover_energy_kwh(phys.launch_s,mass)+phys.hover_energy_kwh(phys.recovery_s,load);evaluations.append((en,hover,truckwait))
   if any(en>phys.e_cap-phys.e_min+phys.energy_tol for en,_,__ in evaluations):continue
   nominal=evaluations[0];worst=max(x[0]for x in evaluations);cost=phys.cost_depot_kwh*nominal[0]+phys.wage_per_s*(phys.prepare_s+phys.launch_s+phys.recovery_s+nominal[2])+p_fail*Q
   offers.append((cost,lam,dict(cost=cost,energy=worst,Q=Q,lam=lam,start=at(lam),end=end,rec=b['rec'],receiver=b['truck'],predicted_hover_s=max(x[1]for x in evaluations),predicted_truck_wait_s=nominal[2],observed_context_energies=[x[0]for x in evaluations])))
  return min(offers,key=lambda z:z[:2])[2]if offers else None

 def matched(key,trial):
  ids=layers[key];active=[k for k in ids if trial[k]]
  if not active:return 0.,{}
  cells={(a,b):option(a,tuple(trial[a]),b)for a in active for b in active};matrix=[[cells[a,b]['cost']if cells[a,b]is not None else None for b in active]for a in active];dg['assignment_matrices']+=1;solve=assignment(matrix)
  if solve is None:return None
  _,perm=solve;out={a:cells[a,active[perm[i]]]for i,a in enumerate(active)};value=sum(z['cost']for z in out.values());return value,out
 def total_score(choices):
  val=sum(z['cost']for z in choices.values())
  # Explicit geometric Qij approximation for simultaneous receiver lanes only.
  ks=sorted(choices)
  for i,a in enumerate(ks):
   for b in ks[i+1:]:
    if jobs[a]['layer']==jobs[b]['layer']and choices[a]['receiver']==choices[b]['receiver']:val+=p_fail*p_fail*min(choices[a]['Q'],choices[b]['Q'])
  return val
 def inventory_fit(choices):
  energy={d:phys.e_cap for t in T for d in phys.home_drones(t)};carriers={t:list(phys.home_drones(t))for t in T};spares={t:phys.spare_batteries for t in T}
  for layer in sorted({j['layer']for j in jobs}):
   after={t:list(ds)for t,ds in carriers.items()}
   for j in (j for j in jobs if j['layer']==layer):
    k=j['index']
    if k not in choices:continue
    z=choices[k];d=carriers[j['truck']][j['lane']]
    if energy[d]-z['energy']<phys.e_min-phys.energy_tol:
     if not phys.swap_mode:return False
     spares[j['truck']]-=1
     if spares[j['truck']]<0:return False
     energy[d]=phys.e_cap
    energy[d]-=z['energy'];after[z['receiver']][j['lane']]=d
   if len({d for ds in after.values()for d in ds})!=phys.drone_count:return False
   carriers=after
  return True
 ground={x for rt in anchors.values()for v in rt for x in p.visits[v].ground};pool=set(inst.parcel_mass)-ground;oldair=air(p)
 if not oldair==pool or not pool:return None
 if order=='mass_first':todo=sorted(pool,key=lambda x:(-inst.parcel_mass[x],x))
 else:
  # Bounded difficulty uses the SAME pure geometry cells, not paid/native trials.
  difficulty={x:sum(option(j['index'],(x,),j['index'])is not None for j in jobs)for x in sorted(pool)};todo=sorted(pool,key=lambda x:(difficulty[x],-inst.parcel_mass[x],x))
 score=0.
 for x in todo:
  best=None;dg['packing_steps']+=1
  for j in jobs:
   k=j['index'];g=groups[k]
   if sum(inst.parcel_mass[y]for y in g)+inst.parcel_mass[x]>phys.drone_payload_limit_kg+1e-9:continue
   for atidx in range(len(g)+1):
    trial=dict(groups);trial[k]=g[:atidx]+[x]+g[atidx:];sol=matched(layerof[k],trial)
    if sol is None:continue
    choices={a:z for a,z in selected.items()if layerof[a]!=layerof[k]};choices.update(sol[1])
    if not inventory_fit(choices):continue
    sc=total_score(choices);rank=(sc-score,k,atidx)
    if best is None or rank<best[0]:best=(rank,trial,choices,sc)
  if best is None:dg['packing_rejected']+=1;dg.setdefault('failed_frames',[]).append(dict(assigned=sum(map(len,groups.values())),pool=len(pool),reason='No finite approximate matching/inventory insertion; not native physical infeasibility'));return None
  _,groups,selected,score=best
 js=[]
 for j in jobs:
  z=dict(j);k=j['index']
  if k in selected:z.update(selected[k],mode='ARC')
  js.append(z)
 q,bindings,carriers=close(p,anchors,js,groups,inst,phys);errors=q.validate_structure(inst,phys,initial_carrier={d:phys.home_truck(d)for t in T for d in phys.home_drones(t)})
 if errors:dg['structure_rejected']+=1;return None
 assert air(q)==pool and oldair==air(q)
 dg['complete_constructed']+=1;dg['frame_CPU_s']+=time.process_time()-frame_cpu
 d=dict(kind='PAID_TRAINING_COMPLETE_REBIND',construction='PAID_TRAINING_ROBUST_JOINT_BODY_GROUND',parcels=sorted(pool-oldair),old_visits=sorted(set(p.visits)-set(q.visits)),sorties=sorted(q.sorties),new_rendezvous=[q.sorties[s].rec_vid for s in sorted(q.sorties)],air_groups={s:list(q.sorties[s].air)for s in sorted(q.sorties)},body_bindings=bindings,terminal_carriers=carriers,all_old_air_preserved=True,all_original_flights_reconstructed=True,approximate_not_exhaustive=True,packing_order=order,approximate_objective=score,approximate_clock_not_native_schedule=True,additional_exact_Q_or_J_calls=0,full_current_geometry_bound=True,operator_origin='DIRECT_PAID_TRAINING_ROBUST_RECONSTRUCTION',observed_training_contexts=len(contexts)-1,release_changed=sum(s.lam>0 for s in q.sorties.values()),predicted_max_hover_s=max((z['predicted_hover_s']for z in selected.values()),default=0.),real_cross=sum(s.truck!=q.visits[s.rec_vid].truck for s in q.sorties.values()),first_depot_ARC_lambda_zero=all(s.lam==0 for s in q.sorties.values()if s.launch_vid is None))
 return q,refresh(q,d,inst)


def geometries(p,e,ctx,diag):
 from .complete_joint import version
 from .noncontiguous_pool import reassign
 import copy
 start=time.process_time();dg=diag;dg.update(pure_geometry_queries=0,pure_cell_misses=0,assignment_matrices=0,packing_steps=0,packing_rejected=0,structure_rejected=0,complete_constructed=0,frame_CPU_s=0.,incomplete_paid_context=0,frames_entered=0,emitted=0)
 v=version(p);key=(v,ctx.H,repr(vars(ctx.state)));paid=getattr(ctx.alg,'_paid_training_receipts',{}).get(key,[])
 if tuple(sorted(air(p)))not in getattr(ctx.alg,'_mature_fullpool_air_sets',set()):dg['skip']='NO_ORIGINAL_MATURE_FULLPOOL_CAS';return []
 if len(paid)!=2 or any(z['nominal_version']!=v or z['H']!=ctx.H for z in paid):dg['skip']='NO_TWO_EXACT_PAID_TRAINING_CONTEXTS';return []
 if any(z['timeline']is None for z in paid):dg['skip']='PAID_TRAINING_HAS_NO_TIMELINE';return []
 if any(s.started or s.handover for s in p.sorties.values()):dg['skip']='NOT_INITIAL_COMPLETE_NOMINAL';return []
 contexts=[(p,e.timeline,frozenset())]+[(z['repair_plan'],z['timeline'],z['failed'])for z in paid];out=[];seen=set();frames=set()
 for optimize in [False,True]:
  fp,aa,meta=reassign(p,p.routes,ctx.inst,ctx.phys)if optimize else(p,{t:list(rt)for t,rt in p.routes.items()},dict(moves=[]))
  sig=tuple((t,tuple(rt))for t,rt in sorted(aa.items()))
  if sig in frames:continue
  frames.add(sig)
  for order in ['mass_first','constrained_first']:
   dg['frames_entered']+=1;item=pack_frame(fp,aa,ctx.inst,ctx.phys,bool(ctx.state.nominal_cross),ctx.alg.scenario_p,order,dg,contexts)
   if item is None:continue
   q,d=item;vv=version(q)
   if vv==v or vv in seen:continue
   seen.add(vv);d.update(paid_training_nominal_version=v,paid_training_H=ctx.H,paid_training_budget_positions=[z['scenario_budget_used']for z in paid],paid_training_repair_versions=[z['repair_version']for z in paid],ground_reassignment=meta,construction_current_version=v,same_original_paid_slot=True,parcels=[],original_mature_parent_air_preserved=True,feedback_chain=[],refinement_origin=None);out.append((q,refresh(q,d,ctx.inst)))
 dg.update(emitted=len(out),complete_pure_constructor_CPU_s=time.process_time()-start,finite_frame_upper=4,observed_training_contexts=len(paid),uses_only_exact_current_paid_evidence=True);return out
