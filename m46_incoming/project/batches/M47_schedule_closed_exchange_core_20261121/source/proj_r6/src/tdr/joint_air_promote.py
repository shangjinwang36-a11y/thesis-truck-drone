"""Complete nominal air promotion plus rendezvous/backbone/body-path closure.
Pure construction. Same-car and cross-car use the same code with policy rights.
No started flight, hidden environment, new recovery action or evaluator here.
"""
import math

def air(p):return frozenset(x for s in p.sorties.values()for x in s.air)
def identity(p):
 from .hybrid import _fingerprint
 return(_fingerprint(p),tuple((d,tuple(v))for d,v in sorted(p.drone_sorties.items())))

def body_covers(p,inst,phys,launch_order,limit=4,node_cap=512,diagnostic=None,required_first=None,energy_profile=None):
 """Finite backtracking over ready flights AND real available body choices.
 Empty equal-home bodies are symmetric; nonempty histories are not collapsed.
 A capped catalogue, explicitly not an exhaustive physical-cover solver.
 """
 pins=dict(required_first or {});reserved={d:sid for sid,d in pins.items()}
 if len(reserved)!=len(pins)or any(sid not in p.sorties or p.sorties[sid].started or (p.sorties[sid].launch_vid is not None and (p.sorties[sid].mode!='STOP'or p.sorties[sid].launch_vid not in p.visits or p.visits[p.sorties[sid].launch_vid].truck!=p.sorties[sid].truck)) or p.sorties[sid].truck!=phys.home_truck(d)for sid,d in pins.items()):return
 dg=diagnostic if diagnostic is not None else {};fleet=[f'd{i+1}'for i in range(phys.drone_count)];pos={v:i for t,r in p.routes.items()for i,v in enumerate(r)};chains={d:[]for d in fleet};loc={d:(phys.home_truck(d),None)for d in fleet};seen=set();dg.update(nodes=0,yielded=0,unexpanded_branches=0,node_cap=node_cap,cover_limit=limit)
 residual={d:phys.e_cap for d in fleet};battery_requests={}
 def emit():
  q=p.clone();q.drone_sorties={d:list(v)for d,v in chains.items()}
  for d,v in chains.items():
   for sid in v:q.sorties[sid].drone=d
  key=identity(q)
  if key in seen or q.validate_structure(inst,phys):return None
  seen.add(key);return q
 def dfs(left):
  if dg['nodes']>=node_cap or dg['yielded']>=limit:dg['unexpanded_branches']+=1;return
  dg['nodes']+=1
  if not left:
   q=emit()
   if q is not None:dg['yielded']+=1;yield q
   return
  options=[]
  for sid in sorted(left,key=lambda sid:(launch_order.get(sid,float('inf')),sid)):
   s=p.sorties[sid];choices=[];empty_homes=set()
   for d in sorted(fleet,key=lambda d:(d!=s.drone,len(chains[d]),d)):
    t,rv=loc[d]
    if sid in pins and (pins[sid]!=d or chains[d]):continue
    if d in reserved and not chains[d]and sid!=reserved[d]:continue
    if t!=s.truck:continue
    if rv is not None and(s.launch_vid is None or pos[rv]>pos[s.launch_vid]):continue
    if not chains[d]:
     symmetry=(t,reserved.get(d))
     if symmetry in empty_homes:continue
     empty_homes.add(symmetry)
    choices.append(d)
   if energy_profile is not None:
    # Construction order only. These optimistic ledgers are NOT physical
    # certification, do not install SWAPs, and never bypass native evaluation.
    en=energy_profile[sid]
    choices.sort(key=lambda d:(residual[d]-en<phys.e_min-phys.energy_tol,battery_requests.get(s.truck,0)>=phys.spare_batteries if residual[d]-en<phys.e_min-phys.energy_tol else False,-residual[d],d!=s.drone,len(chains[d]),d))
   options.extend((sid,d)for d in choices)
  for index,(sid,d)in enumerate(options):
   if dg['nodes']>=node_cap or dg['yielded']>=limit:dg['unexpanded_branches']+=len(options)-index;break
   s=p.sorties[sid];before=loc[d];before_e=residual[d];before_b=dict(battery_requests)
   if energy_profile is not None:
    en=energy_profile[sid]
    if residual[d]-en<phys.e_min-phys.energy_tol:battery_requests[s.truck]=battery_requests.get(s.truck,0)+1;residual[d]=phys.e_cap
    residual[d]-=en
   chains[d].append(sid);loc[d]=(p.visits[s.rec_vid].truck,s.rec_vid)
   yield from dfs(left-{sid})
   chains[d].pop();loc[d]=before;residual[d]=before_e;battery_requests.clear();battery_requests.update(before_b)
 yield from dfs(set(p.sorties))

def candidates(p,inst,phys,launch_order,allow_cross,diagnostic=None,timeline=None,target_parcel=None):
 """Promote the ground parcel at a rendezvous, relocate its entire unexecuted
 visit operation block to an existing legal customer stop, then remove old
 ground detour and close all body paths. EXTEND or a new flight are both valid.
 """
 from .moves import air_energy,air_time,sortie_start
 dg=diagnostic if diagnostic is not None else {};raw=[];dep=(inst.depot_x,inst.depot_y)
 xy={v:(inst.customer(x.customer).x,inst.customer(x.customer).y)for v,x in p.visits.items()}
 def road(r):return sum(math.dist(a,b)for a,b in zip([dep]+[xy[v]for v in r],[xy[v]for v in r]+[dep]))
 if any(s.started for s in p.sorties.values()):return
 for sid,s in sorted(p.sorties.items()):
  ov=p.visits[s.rec_vid]
  if len(ov.ground)!=1 or s.launch_vid==ov.vid:continue
  parcel=ov.ground[0]
  if target_parcel is not None and parcel!=target_parcel:continue
  if inst.parcel_mass[parcel]>phys.drone_payload_limit_kg+1e-9:continue
  refs=[x for x in p.sorties.values()if x.launch_vid==ov.vid or x.rec_vid==ov.vid]
  route=p.routes[ov.truck];save=road(route)-road([v for v in route if v!=ov.vid]);baseproxy=-save*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)
  for rv in sorted(p.visits):
   if rv==ov.vid or rv==s.launch_vid:continue
   for kind in('EXTEND','NEW'):
    if kind=='EXTEND'and sum(inst.parcel_mass[x]for x in s.payload_ids)+inst.parcel_mass[parcel]>phys.drone_payload_limit_kg+1e-9:continue
    for ins in(range(len(s.air)+1)if kind=='EXTEND'else[0]):
     newair=list(s.air) if kind=='EXTEND' else []
     newair.insert(ins,parcel)
     proxy=baseproxy+math.dist(xy[ov.vid],xy[rv])*.00005+(0 if kind=='EXTEND'else phys.wage_per_s*phys.prepare_s)
     if timeline is not None:
      launch=float(launch_order.get(sid,0));arr=float(timeline.visit_arr.get(rv,0));duration=air_time(inst,phys,sortie_start(inst,p,s),newair,xy[rv]);oldwait=float(timeline.wait_by_sortie.get(sid,0));proxy+=phys.wage_per_s*(max(0,launch+duration-arr)-oldwait)
     raw.append((proxy,sid,parcel,ov.vid,rv,kind,ins))
 dg.update(raw_total=len(raw),raw_examined=0,policy_rejected=0,energy_rejected=0,body_covers=0,body_nodes=0,body_unexpanded_branches=0,whole_plans_yielded=0)
 for proxy,sid,parcel,oldv,rv,kind,ins in sorted(raw):
  dg['raw_examined']+=1;q=p.clone();s=q.sorties[sid];q.visits[oldv].ground.remove(parcel)
  for so in q.sorties.values():
   if so.rec_vid==oldv:so.rec_vid=rv
   if so.launch_vid==oldv:so.launch_vid=rv
   if so.launch_vid is not None:so.truck=q.visits[so.launch_vid].truck
   if so.launch_truck is not None:so.launch_truck=so.truck
  if kind=='EXTEND':s.air.insert(ins,parcel);added_sid=sid
  else:
   so=q.add_sortie(s.drone,s.truck,s.launch_vid,s.mode,s.lam,[parcel],rv);added_sid=so.sid
  q.remove_visit(oldv)
  cross=any(so.truck!=q.visits[so.rec_vid].truck for so in q.sorties.values())
  if not allow_cross and cross:dg['policy_rejected']+=1;continue
  if any(air_energy(inst,phys,sortie_start(inst,q,so),so.air,(inst.customer(q.visits[so.rec_vid].customer).x,inst.customer(q.visits[so.rec_vid].customer).y))>phys.e_cap-phys.e_min+phys.energy_tol for so in q.sorties.values()):dg['energy_rejected']+=1;continue
  covers={}
  for index,z in enumerate(body_covers(q,inst,phys,launch_order,diagnostic=covers)):
   assert air(z)==air(p)|{parcel}
   dg['whole_plans_yielded']+=1
   yield z,dict(kind='JOINT_AIR_PROMOTION_'+kind,parcel=parcel,sortie=sid,added_sortie=added_sid,old_visit=oldv,new_rendezvous=rv,insert_position=ins,cover_index=index,real_cross=cross,proxy=proxy,cover_catalogue=dict(covers))
  dg['body_covers']+=covers.get('yielded',0);dg['body_nodes']+=covers.get('nodes',0);dg['body_unexpanded_branches']+=covers.get('unexpanded_branches',0)
