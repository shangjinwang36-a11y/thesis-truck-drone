"""Visible simultaneous receiver/body-token/cargo closure, not another reorder operator.
All complete proposals use existing init Budget; never a second free search.
R uses X recovery permission. No map, customer-id, seed or future world branches.
"""
import math,re
from collections import defaultdict

def _energy(so,p,inst,phys,state):
 def xy(v):
  c=inst.customer(p.visits[v].customer);return c.x,c.y
 point=xy(so.launch_vid)if so.launch_vid in p.visits else state.truck_start_pos.get(so.truck,(inst.depot_x,inst.depot_y))
 mass=sum(inst.parcel_mass[x]for x in so.payload_ids);energy=0.
 for parcel in so.air:
  c=inst.customer(inst.parcel_to_customer[parcel]);nxt=(c.x,c.y);energy+=phys.fly_energy_kwh(math.dist(point,nxt),mass)+phys.hover_energy_kwh(phys.air_service_s,mass);mass-=inst.parcel_mass[parcel];point=nxt
 if so.rec_vid in p.visits:energy+=phys.fly_energy_kwh(math.dist(point,xy(so.rec_vid)),max(0.,mass))
 return energy

def body_flow(p,state,inst,phys):
 """Cover every unstarted task with real current/recovered bodies; loaded cargo locks body.
No cargo moves are invented: launch trucks/payloads remain fixed. The native evaluator
alone checks true times, swap inventory, channels, stock and energy for the full plan.
"""
 tokens={};chains={};before={s.sid:s.drone for s in p.sorties.values()if not s.started}
 for d,ds in state.drone_start.items():
  started=[p.sorties[sid]for sid in p.drone_sorties.get(d,[])if p.sorties[sid].started]
  chains[d]=[s.sid for s in started]
  if started:
   s=started[-1]
   if s.rec_vid in p.visits:tokens[d]=[p.visits[s.rec_vid].truck,s.rec_vid,ds.energy]
  elif ds.kind=='ON_TRUCK'and ds.truck in p.routes:tokens[d]=[ds.truck,None,ds.energy]
 locked={}
 for so in p.sorties.values():
  if so.started:continue
  owners={state.parcel_holder.get(x,'')for x in so.payload_ids}
  ds=[x.split(':',1)[1]for x in owners if x.startswith('DRONE:')]
  if len(set(ds))>1:return None
  if ds:locked[so.sid]=ds[0]
 def launch_key(s):
  r=p.routes.get(s.truck,[]);return(r.index(s.launch_vid)if s.launch_vid in r else-1,s.truck,s.sid)
 left=sorted([s for s in p.sorties.values()if not s.started],key=launch_key)
 while left:
  progress=False
  for so in list(left):
   r=p.routes.get(so.truck,[]);li=r.index(so.launch_vid)if so.launch_vid in r else-1;need=_energy(so,p,inst,phys,state)+phys.e_min;choices=[]
   for d,(truck,rv,en)in tokens.items():
    if truck!=so.truck or(so.sid in locked and locked[so.sid]!=d):continue
    if rv is not None and(rv not in r or r.index(rv)>li):continue
    if so.sid not in locked and state.drone_start[d].aboard:continue
    choices.append((en<need, max(0.,need-en),d!=so.drone,-en,d))
   if not choices:continue
   d=min(choices)[-1];en=tokens[d][2];so.drone=d;chains[d].append(so.sid)
   tokens[d]=[p.visits[so.rec_vid].truck,so.rec_vid,max(0.,en-_energy(so,p,inst,phys,state))]
   left.remove(so);progress=True
  if not progress:return None
 p.drone_sorties={d:jobs for d,jobs in chains.items()if jobs}
 return sorted(sid for sid,d in before.items()if p.sorties[sid].drone!=d)

def close(plan,ev,state,inst,phys,strategy,greq,frag_sid,all_affected=False):
 from . import task_binding_skeleton as single
 from .complete_joint import version
 q=plan.clone();original=version(q);named=set();trucks=set()
 for violation in getattr(ev,'violations',[]):
  m=re.match(r'(?:SWAP_CANNOT_FIX|ENERGY[^:]*):(d\d+)',violation)
  if m:named.add(m.group(1))
  m=re.match(r'(?:H_EXCEEDED|SLOT_OVER):(t\d+)',violation)
  if m:trucks.add(m.group(1))
 f=q.sorties.get(frag_sid)
 if f and f.rec_vid in q.visits:trucks.add(q.visits[f.rec_vid].truck)
 targets=[s.sid for s in q.sorties.values()if s.started and s.sid!=frag_sid and(all_affected or s.drone in named or(s.rec_vid in q.visits and q.visits[s.rec_vid].truck in trucks))]
 targets.sort(key=lambda sid:(q.sorties[sid].drone not in named,sid));changes=[]
 # All affected receiver/cargo bindings are assembled BEFORE this proposal is evaluated.
 for sid in targets:
  generated=single.candidates(q,state,inst,phys,strategy,greq,sid)
  item=next(generated,None)
  if item is not None:
   new,meta=item
   if new.sorties[sid]!=q.sorties[sid]:changes.append(dict(sid=sid,drone=q.sorties[sid].drone,receiver=meta['receiving_truck'],customer=meta['recovery_customer']))
   q=new
 changed_bodies=body_flow(q,state,inst,phys)
 if changed_bodies is None or not single._skeleton(q,state,inst,phys):return None
 if q.validate_structure(inst,phys,initial_carrier=state.drone_carrier):return None
 if version(q)==original:return None
 return q,dict(kind='SIMULTANEOUS_RECEIVER_CARGO_BODY_TOKEN_SKELETON',rebound_started=changes,body_changed_tasks=changed_bodies,parent_version=original,candidate_version=version(q))

def retained_seed(input_plan,opt,state,inst,phys,strategy,greq,frag_sid):
 from . import recovery as rec,task_binding_skeleton as single
 if frag_sid not in opt.plan.sorties:return None
 s=opt.plan.sorties[frag_sid]
 if s.rec_vid not in opt.plan.visits:return None
 v=opt.plan.visits[s.rec_vid];ent=dict(truck=v.truck,kind='support',support=True,ref=v.customer,served=list(s.air))
 base=rec.prepare_residual(input_plan,inst)
 for p in rec.build_residual_candidate(base,frag_sid,ent,inst,phys,state,greq,strategy,preserve_cross=True)[:1]:
  if not rec._air_parcel_set(p)<=rec._air_parcel_set(input_plan):continue
  out=close(p,opt.ev,state,inst,phys,strategy,greq,frag_sid,all_affected=True)
  if out:return out
 return None
