"""Complete recovery-point, custody-handover and future body-chain binding + truck skeleton.
Visible inputs only. Used symmetrically only AFTER original initialization returns no
feasible plan, on that SAME remaining Budget, never an extra free K1 invocation.
All current mature operators and their original rules are untouched.
"""
import math
from collections import defaultdict

def _xy(inst,p,v):
 c=inst.customer(p.visits[v].customer);return c.x,c.y

def _skeleton(q,state,inst,phys):
 """Joint task/body/cargo precedences; build whole routes, not local visit swaps."""
 V=set(q.visits);edges=defaultdict(set);pred={v:set()for v in V};prior={v:float('inf')for v in V}
 def edge(a,b):
  if a in V and b in V and a!=b:edges[a].add(b);pred[b].add(a)
 transfer={}
 for so in q.sorties.values():
  if not so.started:edge(so.launch_vid,so.rec_vid)
  for p in so.handover:transfer[p]=(so.sid,so.rec_vid)
  if so.started and so.rec_vid in V:
   ds=state.drone_start.get(so.drone);en=ds.energy if ds else state.drone_energy.get(so.drone,phys.e_cap)
   mass=sum(inst.parcel_mass[p]for p in so.payload_ids)
   prior[so.rec_vid]=state.t0+max(0.,en-phys.e_min)/max(1e-9,phys.hover_power(mass))*3600.
 for jobs in q.drone_sorties.values():
  for sa,sb in zip(jobs,jobs[1:]):
   a,b=q.sorties[sa],q.sorties[sb]
   if not b.started:edge(a.rec_vid,b.launch_vid)
 for v in q.visits.values():
  for p in v.ground:
   if p in transfer:edge(transfer[p][1],v.vid)
 for so in q.sorties.values():
  if not so.started:
   for p in so.payload_ids:
    if p in transfer and transfer[p][0]!=so.sid:edge(transfer[p][1],so.launch_vid)
 for t,route in q.routes.items():
  fixed=max(int(state.truck_min_insert.get(t,0)or 0),int(t in state.truck_committed_first))
  for a,b in zip(route[:fixed],route[1:fixed]):edge(a,b)
  if fixed:
   for v in route[fixed:]:edge(route[fixed-1],v)
 # Propagate real precedence urgency. This ranks proposals, never changes J.
 for _ in range(len(V)):
  changed=False
  for a,bs in edges.items():
   val=min([prior[a]]+[prior[b]for b in bs])
   if val<prior[a]:prior[a]=val;changed=True
  if not changed:break
 route={t:[]for t in q.routes};pos={t:state.truck_start_pos.get(t,(inst.depot_x,inst.depot_y))for t in route};left=set(V)
 while left:
  ready=[v for v in left if not(pred[v]&left)]
  if not ready:return False
  v=min(ready,key=lambda v:(prior[v],math.dist(pos[q.visits[v].truck],_xy(inst,q,v)),q.visits[v].truck,v))
  t=q.visits[v].truck;route[t].append(v);pos[t]=_xy(inst,q,v);left.remove(v)
 q.routes=route
 return True

def candidates(plan,state,inst,phys,strategy,greq,frag_sid):
 from . import recovery as rec
 from .complete_joint import version
 frag=plan.sorties.get(frag_sid)
 if frag is None:return
 res=rec.prepare_residual(plan,inst);allowed=rec._air_parcel_set(plan);launch=frag.launch_truck or frag.truck
 trucks=[launch]if strategy=='S'else sorted(plan.routes)
 rem=[p for p in frag.air if p not in greq];served_choices=rec._continue_subsets(rem)
 ds=state.drone_start.get(frag.drone);energy=ds.energy if ds else state.drone_energy.get(frag.drone,phys.e_cap)
 point=frag.start_pos or(ds.pos if ds else(inst.depot_x,inst.depot_y));domains=[]
 for t in trucks:
  # Cross-body continuation may not conjure cargo onto a different truck.
  # Only same-host continuation, or a truly final current flight, is offered.
  later=[s for s in plan.drone_sorties.get(frag.drone,[])if s!=frag_sid and not plan.sorties[s].started]
  if t!=launch and later:continue
  for c in inst.customers:
   xy=(c.x,c.y);road=math.dist(state.truck_start_pos.get(t,(inst.depot_x,inst.depot_y)),xy)
   for served in served_choices:
    cur=point;mass=sum(inst.parcel_mass[p]for p in frag.payload_ids);en=0.;dt=0.
    for p in served:
     cc=inst.customer(inst.parcel_to_customer[p]);nxt=(cc.x,cc.y);d=math.dist(cur,nxt)
     en+=phys.fly_energy_kwh(d,mass)+phys.hover_energy_kwh(phys.air_service_s,mass);dt+=d/phys.drone_speed_m_s+phys.air_service_s;mass-=inst.parcel_mass[p];cur=nxt
    d=math.dist(cur,xy);en+=phys.fly_energy_kwh(d,max(0.,mass));dt+=d/phys.drone_speed_m_s
    earliest=max(state.t0,state.truck_start_time.get(t,state.t0),state.truck_ready_time.get(t,state.t0))+road/phys.truck_speed_m_s
    en+=phys.hover_energy_kwh(max(0.,earliest-state.t0-dt),max(0.,mass))
    # Full native evaluator remains authority; no diagnostic world or softened physics.
    domains.append((int(en>energy-phys.e_min+phys.energy_tol),phys.c_km*road/1000.+phys.wage_per_s*max(dt,earliest-state.t0),t,c.customer_id,tuple(served)))
 domains.sort();seen=set()
 for energy_rank,proxy,t,cust,served in domains:
  ent=dict(truck=t,kind='support',ref=cust,support=True,served=list(served))
  for q in rec.build_residual_candidate(res,frag_sid,ent,inst,phys,state,greq,strategy,preserve_cross=True)[:1]:
   if not rec._air_parcel_set(q)<=allowed:continue
   if not _skeleton(q,state,inst,phys):continue
   if q.validate_structure(inst,phys,initial_carrier=state.drone_carrier):continue
   v=version(q)
   if v in seen:continue
   seen.add(v)
   yield q,dict(kind='COMPLETE_RECOVERY_CUSTODY_BODY_AND_SKELETON',receiving_truck=t,recovery_customer=cust,continued_air=list(served),ranking_energy_deficit=bool(energy_rank),ranking_proxy_not_J=proxy,parent_version=version(plan),candidate_version=v)

def extend_after_failure(plan,state,inst,phys,strategy,greq,budget,stats,info,H,frag_sid,options):
 from . import recovery as rec,multi_binding_skeleton as multi
 from .complete_joint import version
 best=None;records=[];air_ceiling=rec._air_parcel_set(plan);seen=set()
 def consider(q,meta,reason):
  nonlocal best
  v=version(q)
  if v in seen or budget.evals_left()<=0:return None
  seen.add(v)
  ev=rec.eval_counted(q,inst,phys,state,H,reason,stats,budget,ground_required=greq)
  if ev is None:return None
  better=ev.feasible and(best is None or rec._recovery_prefers(ev,q,best.ev,best.plan,air_ceiling if strategy=='X'else None,options.get('new_air_penalty',0.),risk_p=options.get('risk_price_p',0.),inst=inst,phys=phys,state=state))
  records.append(dict(meta,reason=reason,budget_used=budget.used,feasible=ev.feasible,cost=ev.cost,z=ev.z,violations=ev.violations,original_objective_better=better))
  if better:
   so=q.sorties[frag_sid];rv=so.rec_vid;t=q.visits[rv].truck;best=rec.RecoveryOption(q,ev,reason,t,rv,len(so.air),list(so.handover))
  return ev
 for q,meta in candidates(plan,state,inst,phys,strategy,greq,frag_sid):
  if budget.evals_left()<=0:break
  ev=consider(q,meta,'COMPLETE_TASK_BINDING_SKELETON')
  if ev is not None and not ev.feasible and best is None and budget.evals_left()>0:
   joint=multi.close(q,ev,state,inst,phys,strategy,greq,frag_sid)
   if joint is not None and rec._air_parcel_set(joint[0])<=air_ceiling:consider(*joint,'SIMULTANEOUS_BINDING_SKELETON')
 info['binding_records']=records;info['binding_evals']=len(records)
 if best is not None:info.update(best_source=best.description,init_cost=best.ev.cost)
 return best


def offer_spare_initialization(opt,input_plan,state,inst,phys,strategy,greq,budget,stats,info,H,frag_sid,options):
 from . import recovery as rec,multi_binding_skeleton as multi
 from .complete_joint import version
 # Only pre-existing unused INIT capacity. Original full main budget is untouched.
 if budget.evals_left()<=0 or info.get('residual_feasible',False):return opt
 item=multi.retained_seed(input_plan,opt,state,inst,phys,strategy,greq,frag_sid)
 if item is None or version(item[0])==version(opt.plan):return opt
 q,meta=item
 ev=rec.eval_counted(q,inst,phys,state,H,'SPARE_INIT_SIMULTANEOUS_BINDING',stats,budget,ground_required=greq)
 if ev is None:return opt
 better=ev.feasible and rec._recovery_prefers(ev,q,opt.ev,opt.plan,rec._air_parcel_set(input_plan)if strategy=='X'else None,options.get('new_air_penalty',0.),risk_p=options.get('risk_price_p',0.),inst=inst,phys=phys,state=state)
 info['spare_joint_record']=dict(meta,budget_used=budget.used,feasible=ev.feasible,cost=ev.cost,z=ev.z,violations=ev.violations,original_objective_better=better)
 if not better:return opt
 so=q.sorties[frag_sid];rv=so.rec_vid;t=q.visits[rv].truck;info.update(best_source='SPARE_INIT_SIMULTANEOUS_BINDING',init_cost=ev.cost)
 return rec.RecoveryOption(q,ev,'SPARE_INIT_SIMULTANEOUS_BINDING',t,rv,len(so.air),list(so.handover))
