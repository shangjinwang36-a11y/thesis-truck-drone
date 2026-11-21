"""Finite visible dual-rendezvous / existing-air repartition construction.
No world, no evaluator/solver/RNG. Priority uses original p*Q and wait proxy only;
acceptance still requires one paid whole-plan evaluation and unmodified J/SC/H.
"""
import math,itertools,heapq
from collections import Counter
from .joint_air_promote import air,identity,body_covers

def terminal_inventory(q,phys):
 out={f't{i+1}':0 for i in range(phys.truck_count)};where={}
 for i in range(phys.drone_count):
  d=f'd{i+1}';chain=q.drone_sorties.get(d,[]);t=q.visits[q.sorties[chain[-1]].rec_vid].truck if chain else phys.home_truck(d);out[t]=out.get(t,0)+1;where[d]=t
 return out,where

def orders(ids,inst,start):
 ids=tuple(ids)
 if len(ids)<=4:return list(itertools.permutations(ids))
 xy={p:(inst.customer(inst.parcel_to_customer[p]).x,inst.customer(inst.parcel_to_customer[p]).y)for p in ids};out=[ids,ids[::-1]]
 for first in [min(ids),min(ids,key=lambda p:(math.dist(start,xy[p]),p))]:
  seq=[first];left=set(ids)-{first}
  while left:
   z=min(left,key=lambda p:(math.dist(xy[seq[-1]],xy[p]),p));left.remove(z);seq.append(z)
  out.append(tuple(seq))
 return list(dict.fromkeys(out))

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 from .moves import air_energy,air_time,sortie_start,ground_candidates
 from .expected_cost import _failure_cost
 dg=diag if diag is not None else {};dg.update(raw_total=0,raw_examined=0,blocks=0,partition_count=0,heap_remaining=0,heap_cap=512,policy_rejected=0,energy_rejected=0,terminal_slot_rejected=0,body_nodes=0,body_unexpanded_branches=0,whole_plans_yielded=0,unsupported_large_union=0,unsupported_primary_launch_in_block=0)
 if timeline is None or any(s.started for s in p.sorties.values()):dg['missing_visible_timeline_or_started']=1;return
 dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in p.visits.items()};states=[];heap=[]
 def road(r):return sum(math.dist(a,b)for a,b in zip([dep]+[xy[v]for v in r],[xy[v]for v in r]+[dep]))
 for t,route in sorted(p.routes.items()):
  for u,v in zip(route,route[1:]):
   if len(p.visits[u].ground)!=1 or len(p.visits[v].ground)!=1:continue
   extra=(p.visits[u].ground[0],p.visits[v].ground[0]);one=[s for s in p.sorties.values()if s.rec_vid==u and not s.handover];two=[s for s in p.sorties.values()if s.rec_vid==v and not s.handover]
   for a,b in itertools.product(one,two):
    if a.sid==b.sid:continue
    if a.launch_vid in(u,v)or b.launch_vid in(u,v):dg['unsupported_primary_launch_in_block']+=1;continue
    union=tuple(dict.fromkeys([*a.air,*b.air,*extra]));n=len(union)
    if n>8:dg['unsupported_large_union']+=1;continue
    if sum(inst.parcel_mass[x]for x in union)>2*phys.drone_payload_limit_kg+1e-9:continue
    sk=p.clone();sk.remove_visit(u);sk.remove_visit(v);save=road(route)-road(sk.routes[t]);dg['blocks']+=1
    eligible=[rv for rv in sorted(sk.visits)if rv not in(a.launch_vid,b.launch_vid)]
    Q={(pid,rv):ground_candidates(sk,inst,phys,pid,receipt_vid=rv)[0].proxy for pid in union for rv in eligible}
    tables={};oldrisk=p_fail*(_failure_cost(p,inst,phys,a)+_failure_cost(p,inst,phys,b));oldwait=sum(float(timeline.wait_by_sortie.get(sid,0))for sid in(a.sid,b.sid))
    def table(s,group):
     key=(s.sid,group)
     if key in tables:return tables[key]
     start=sortie_start(inst,sk,s);paths=orders(group,inst,start);ans=[]
     for rv in eligible:
      if not allow_cross and sk.visits[rv].truck!=s.truck:continue
      legal=[]
      for seq in paths:
       en=air_energy(inst,phys,start,list(seq),xy[rv])
       if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
       dur=air_time(inst,phys,start,list(seq),xy[rv]);wait=max(0,float(launch_order.get(s.sid,0))+dur-float(timeline.visit_arr.get(rv,0)));risk=p_fail*(phys.wage_per_s*phys.handover_s+sum(Q[x,rv]for x in seq));legal.append((phys.wage_per_s*wait+risk,dur,en,tuple(seq)))
      if legal:
       score,dur,en,seq=min(legal);ans.append((score,rv,seq,en,dur))
     ans.sort();tables[key]=ans;return ans
    for mask in range(1,(1<<n)-1):
     g1=tuple(union[i]for i in range(n)if mask>>i&1);g2=tuple(union[i]for i in range(n)if not(mask>>i&1))
     if any(sum(inst.parcel_mass[x]for x in g)>phys.drone_payload_limit_kg+1e-9 for g in(g1,g2)):continue
     aa=table(a,g1);bb=table(b,g2)
     if not aa or not bb:continue
     constant=-save*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)-oldrisk-phys.wage_per_s*oldwait
     ix=len(states);states.append(dict(u=u,v=v,a=a.sid,b=b.sid,extra=extra,A=aa,B=bb,const=constant,seen={(0,0)}));heapq.heappush(heap,(constant+aa[0][0]+bb[0][0],ix,0,0));dg['partition_count']+=1;dg['raw_total']+=len(aa)*len(bb)
 dg['heap_remaining']=len(heap)
 while heap and dg['raw_examined']<512:
  score,ix,i,j=heapq.heappop(heap);st=states[ix];aa=st['A'];bb=st['B'];dg['raw_examined']+=1
  for ni,nj in[(i+1,j),(i,j+1)]:
   if ni<len(aa)and nj<len(bb)and(ni,nj)not in st['seen']:st['seen'].add((ni,nj));heapq.heappush(heap,(st['const']+aa[ni][0]+bb[nj][0],ix,ni,nj))
  _,r1,g1,en1,du1=aa[i];_,r2,g2,en2,du2=bb[j]
  if r1==r2:dg['same_rendezvous_rejected']=dg.get('same_rendezvous_rejected',0)+1;continue
  u,v=st['u'],st['v'];q=p.clone();q.visits[u].ground.remove(st['extra'][0]);q.visits[v].ground.remove(st['extra'][1]);mapping={u:r1,v:r2};affected=[]
  for s in q.sorties.values():
   changed=False
   if s.rec_vid in mapping:s.rec_vid=mapping[s.rec_vid];changed=True
   if s.launch_vid in mapping:s.launch_vid=mapping[s.launch_vid];changed=True
   if s.launch_vid is not None:s.truck=q.visits[s.launch_vid].truck
   if s.launch_truck is not None:s.launch_truck=s.truck
   if changed:affected.append(s.sid)
  q.sorties[st['a']].air=list(g1);q.sorties[st['b']].air=list(g2);q.remove_visit(u);q.remove_visit(v)
  cross=any(s.truck!=q.visits[s.rec_vid].truck for s in q.sorties.values())
  if not allow_cross and cross:dg['policy_rejected']+=1;continue
  if any(air_energy(inst,phys,sortie_start(inst,q,s),s.air,xy[s.rec_vid])>phys.e_cap-phys.e_min+phys.energy_tol for s in q.sorties.values()):dg['energy_rejected']+=1;continue
  for k in range(phys.drone_count):q.drone_sorties.setdefault(f'd{k+1}',[])
  covers={};seen=set();emitted=0
  def stock_ok(z):
   stock,_=terminal_inventory(z,phys)
   if max(stock.values())>phys.truck_drone_slots:dg['terminal_slot_rejected']+=1;return False
   return True
  original_valid=not q.validate_structure(inst,phys)
  def available():
   if original_valid:yield q.clone()
   yield from body_covers(q,inst,phys,launch_order,limit=3 if original_valid else 4,node_cap=512,diagnostic=covers)
  measured_nodes=0;measured_branches=0
  for z in available():
   now=covers.get('nodes',0);branches=covers.get('unexpanded_branches',0);dg['body_nodes']+=now-measured_nodes;dg['body_unexpanded_branches']+=branches-measured_branches;measured_nodes=now;measured_branches=branches
   sig=identity(z)
   if sig in seen:continue
   seen.add(sig)
   if not stock_ok(z):continue
   emitted+=1;dg['whole_plans_yielded']+=1;assert air(z)==air(p)|set(st['extra'])
   yield z,dict(kind='DUAL_RECOVERY_AIR_REPARTITION',parcels=list(st['extra']),old_visits=[u,v],new_rendezvous=[r1,r2],sorties=[st['a'],st['b']],affected_sorties=affected,air_groups=[list(g1),list(g2)],original_air_repartitioned=bool((set(p.sorties[st['a']].air)&set(g2))or(set(p.sorties[st['b']].air)&set(g1))),real_cross=cross,proxy=score,body_cover_index=emitted-1,body_catalogue=dict(dict(node_cap=512,whole_cover_limit=4),**covers),terminal_inventory=terminal_inventory(z,phys)[0])
   if emitted>=4:break
  dg['body_nodes']+=covers.get('nodes',0)-measured_nodes;dg['body_unexpanded_branches']+=covers.get('unexpanded_branches',0)-measured_branches
 dg['heap_remaining']=len(heap);dg['unexpanded_raw_geometries']=max(0,dg['raw_total']-dg['raw_examined']);dg['catalogue_cap_reached']=bool(heap and dg['raw_examined']>=512)
