"""Complete task/cargo/first-window/body/backbone reconstruction.
STOP first flights ride from the depot on their real home truck with their
real parcels. Optimistic energy profiles guide binding only; native complete
scheduling, swaps, custody, every-stage reserve/H and original J remain gates.
"""
import math,itertools
from collections import Counter
from .joint_air_promote import air,identity,body_covers

def first_window(q0,sid,truck,cargo,inst,phys,timeline,scalar=None):
 from .moves import air_energy,air_time
 if scalar is not None:air_energy,air_time=scalar
 depot=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in q0.visits.items()};positions={v:i for t,rt in q0.routes.items()for i,v in enumerate(rt)}
 so=q0.sorties[sid];rv=so.rec_vid;rec=xy[rv];candidates=[None]+[v for v in q0.routes.get(truck,[])if v!=rv and (q0.visits[rv].truck!=truck or positions[v]<positions[rv])];best=None
 for v in candidates:
  start=depot if v is None else xy[v];en=air_energy(inst,phys,start,cargo,rec)
  if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
  release=(0. if v is None else float(timeline.visit_arr.get(v,0.)))+phys.prepare_s+phys.launch_s;arrival=release+air_time(inst,phys,start,cargo,rec);wait=max(0.,float(timeline.visit_arr.get(rv,0.))-arrival);power=phys.hover_energy_kwh(1.,0.);excess=max(0.,en+power*wait-(phys.e_cap-phys.e_min));resync=max(0.,arrival-float(timeline.visit_arr.get(rv,0.)))+excess/max(power,1e-12)
  score=phys.wage_per_s*resync+phys.cost_depot_kwh*(en+power*wait)
  key=(score,v is None,-1 if v is None else v)
  if best is None or key<best[0]:best=(key,v,start,release,en)
 return best

def exact_pack(ids,pool,windows,q0,inst,phys,xy,timeline,air_energy,air_time):
 selection=tuple((None,w)for w in windows)
 groups={sid:[]for sid in ids};left=set(pool)
 while left:
  insertions=[]
  for parcel in sorted(left):
   choices=[]
   for sid,(_,w)in zip(ids,selection):
    g=groups[sid]
    if sum(inst.parcel_mass[x]for x in g)+inst.parcel_mass[parcel]>phys.drone_payload_limit_kg+1e-9:continue
    for at in range(len(g)+1):
     trial=g[:at]+[parcel]+g[at:];en=air_energy(inst,phys,w[2],trial,xy[q0.sorties[sid].rec_vid])
     if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
     olden=air_energy(inst,phys,w[2],g,xy[q0.sorties[sid].rec_vid])if g else 0.;arr=w[3]+air_time(inst,phys,w[2],trial,xy[q0.sorties[sid].rec_vid]);late=abs(arr-float(timeline.visit_arr.get(q0.sorties[sid].rec_vid,0.)));choices.append((phys.cost_depot_kwh*(en-olden)+phys.wage_per_s*late,sid,at))
   if not choices:insertions=[];break
   choices.sort();regret=choices[1][0]-choices[0][0]if len(choices)>1 else float('inf');insertions.append((-regret,-inst.parcel_mass[parcel],parcel,choices[0]))
  if not insertions:break
  _,__,parcel,(_,sid,at)=min(insertions);groups[sid].insert(at,parcel);left.remove(parcel)
 return groups,left

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2,exact_scope=None):
 from .moves import air_energy,air_time,sortie_start
 from .body_token_flow import frame
 from .joint_dual import terminal_inventory
 from .expected_cost import _failure_cost
 dg=diag if diag is not None else {};dg.update(blocks=0,frames=0,window_assignments=0,packing_rejected=0,topology_rejected=0,body_nodes=0,body_unexpanded_branches=0,yielded=0)
 if exact_scope is not None:air_energy,air_time=exact_scope.energy,exact_scope.time
 if timeline is None or any(so.started or so.handover for so in p.sorties.values()):return
 depot=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in p.visits.items()};positions={v:i for t,rt in p.routes.items()for i,v in enumerate(rt)};fleet=[f'd{k+1}'for k in range(phys.drone_count)];homes={t:[d for d in fleet if phys.home_truck(d)==t]for t in sorted(p.routes)};seen=set();raw=[]
 def road(rt):return sum(math.dist(a,b)for a,b in zip([depot]+[xy[v]for v in rt],[xy[v]for v in rt]+[depot]))
 for t,rt in sorted(p.routes.items()):
  for i in range(len(rt)):
   for j in range(i+3,len(rt)+1):
    block=tuple(rt[i:j])
    if any(len(p.visits[v].ground)!=1 for v in block):continue
    ids=tuple(so.sid for so in p.sorties.values()if so.rec_vid in block)
    if len(ids)<2 or len(ids)>len(fleet):continue
    extra=tuple(p.visits[v].ground[0]for v in block);pool=tuple(dict.fromkeys(extra+tuple(x for sid in ids for x in p.sorties[sid].air)))
    if sum(inst.parcel_mass[x]for x in pool)>len(ids)*phys.drone_payload_limit_kg+1e-9:continue
    retained=[v for v in sorted(p.visits)if v not in block]
    def valid_rec(v,w):return allow_cross or p.visits[v].truck==p.visits[w].truck
    nearest={v:min((w for w in retained if valid_rec(v,w)),key=lambda w:(math.dist(xy[v],xy[w]),w),default=None)for v in block}
    if any(w is None for w in nearest.values()):continue
    maps=[nearest]+[dict(nearest)|{v:w}for v in block for w in retained if valid_rec(v,w)and w!=nearest[v]]
    saving=road(rt)-road([v for v in rt if v not in block]);dg['blocks']+=1
    for mapping in maps:
     proxy=-saving*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)+sum(math.dist(xy[v],xy[mapping[v]])for v in block)*phys.c_km/1000
     raw.append((proxy,t,block,ids,extra,pool,mapping))
 dg['raw_frames']=len(raw)
 for proxy,t,block,ids,extra,pool,mapping in sorted(raw,key=lambda z:(z[0],z[1],z[2],tuple(z[-1].items()))):
  q0=p.clone();dg['frames']+=1
  for v,parcel in zip(block,extra):q0.visits[v].ground.remove(parcel)
  for so in q0.sorties.values():
   if so.launch_vid in mapping:so.launch_vid=mapping[so.launch_vid]
   if so.rec_vid in mapping:so.rec_vid=mapping[so.rec_vid]
   if so.launch_vid is not None:so.truck=q0.visits[so.launch_vid].truck
   if so.launch_truck is not None:so.launch_truck=so.truck
  for v in block:q0.remove_visit(v)
  if exact_scope is None:choose_window=lambda sid,truck,cargo:first_window(q0,sid,truck,cargo,inst,phys,timeline)
  else:
   exact_scope.bind_plan(q0)
   choose_window=lambda sid,truck,cargo:exact_scope.window(sid,truck,cargo,lambda:first_window(q0,sid,truck,cargo,inst,phys,timeline,scalar=(air_energy,air_time)))
  domains=[]
  for sid in ids:
   domain=[]
   for truck in homes:
    if not allow_cross and truck!=q0.visits[q0.sorties[sid].rec_vid].truck:continue
    w=choose_window(sid,truck,q0.sorties[sid].air)
    if w is not None:domain.append((truck,w))
   domains.append(domain)
  offers=[]
  for selection in itertools.product(*domains):
   trucks=tuple(x[0]for x in selection);counts=Counter(trucks)
   if any(counts[tr]>len(homes[tr])for tr in counts):continue
   windows=tuple(w for _,w in selection)
   compute_pack=lambda:exact_pack(ids,pool,windows,q0,inst,phys,xy,timeline,air_energy,air_time)
   groups,left=compute_pack()if exact_scope is None else exact_scope.packing(ids,pool,windows,compute_pack)
   if left or any(not groups[sid]for sid in ids):dg['packing_rejected']+=1;continue
   q=q0.clone();pins={};used=Counter();windows={};score=proxy;order=dict(launch_order)
   for sid,truck in zip(ids,trucks):
    w=choose_window(sid,truck,groups[sid])
    if w is None:break
    so=q.sorties[sid];so.air=groups[sid];so.truck=truck;so.launch_truck=truck;so.launch_vid=w[1];so.mode='ARC'if w[1]is None else'STOP';so.lam=0.;so.launch_priority=used[truck];d=homes[truck][used[truck]];used[truck]+=1;so.drone=d;pins[sid]=d;windows[sid]=w[1];order[sid]=w[3];score+=w[0][0]
   else:
    fr=frame(q,q,{},phys)
    if not fr['possible']:dg['topology_rejected']+=1;continue
    score+=p_fail*(sum(_failure_cost(q,inst,phys,q.sorties[sid])for sid in ids)-sum(_failure_cost(p,inst,phys,p.sorties[sid])for sid in ids))
    offers.append((score,trucks,q,pins,windows,groups,order))
  for score,trucks,q,pins,windows,groups,order in sorted(offers,key=lambda z:(z[0],z[1],tuple(-1 if v is None else v for v in z[4].values()))):
   if exact_scope is not None:exact_scope.bind_plan(q)
   dg['window_assignments']+=1;cover={};profile={sid:air_energy(inst,phys,sortie_start(inst,q,so),so.air,xy[so.rec_vid])for sid,so in q.sorties.items()}
   for z in body_covers(q,inst,phys,order,limit=4,node_cap=512,diagnostic=cover,required_first=pins,energy_profile=profile):
    sig=identity(z)
    if sig in seen:continue
    seen.add(sig);inventory,_=terminal_inventory(z,phys);assert air(z)==air(p)|set(extra)
    assert all(z.drone_sorties[d][0]==sid and z.sorties[sid].truck==phys.home_truck(d)for sid,d in pins.items());assert allow_cross or all(so.truck==z.visits[so.rec_vid].truck for so in z.sorties.values());dg['yielded']+=1
    yield z,dict(kind='MULTI_TASK_POOL_RECONSTRUCTION',construction='ENERGY_SYNCHRONIZED_INITIAL_WINDOWS',parcels=list(extra),old_visits=list(block),sorties=list(ids),new_rendezvous=[mapping[v]for v in block],air_groups=groups,initial_release={sid:z.sorties[sid].truck for sid in ids},initial_bodies=pins,launch_windows=windows,nondepot_first_flights=sum(v is not None for v in windows.values()),energy_profile_guides_binding_only=True,real_cross=any(so.truck!=z.visits[so.rec_vid].truck for so in z.sorties.values()),proxy=score,terminal_inventory=inventory,body_catalogue=dict(cover))
   dg['body_nodes']+=cover.get('nodes',0);dg['body_unexpanded_branches']+=cover.get('unexpanded_branches',0)
 dg['unexpanded_frames']=dg['raw_frames']-dg['frames']
