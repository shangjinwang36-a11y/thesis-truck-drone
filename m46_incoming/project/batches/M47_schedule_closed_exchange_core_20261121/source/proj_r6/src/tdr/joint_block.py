"""Visible nominal, two-rendezvous contiguous block closure; no evaluator/world.
Two existing flights receive two ground parcels together; all incident launch and
recovery references move atomically, then real whole-fleet paths are closed.
The bounded catalogue is NOT all physically possible joint reassignments.
"""
import math,itertools
from .joint_air_promote import air,body_covers,identity

def geometries(p,inst,phys,launch_order,allow_cross,diag=None):
 from .moves import air_energy,sortie_start,air_time
 dg=diag if diag is not None else {};dg.update(blocks=0,raw_total=0,raw_examined=0,energy_rejected=0,policy_rejected=0,body_nodes=0,body_unexpanded=0,yielded=0)
 if any(s.started for s in p.sorties.values()):return
 dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y)for v,z in p.visits.items()}
 def road(r):return sum(math.dist(a,b)for a,b in zip([dep]+[xy[v]for v in r],[xy[v]for v in r]+[dep]))
 raw=[]
 for t,route in sorted(p.routes.items()):
  for pos,(u,v)in enumerate(zip(route,route[1:])):
   if len(p.visits[u].ground)!=1 or len(p.visits[v].ground)!=1:continue
   ps=(p.visits[u].ground[0],p.visits[v].ground[0]);one=[s for s in p.sorties.values()if s.rec_vid==u];two=[s for s in p.sorties.values()if s.rec_vid==v]
   for a,b in itertools.product(one,two):
    if a.sid==b.sid:continue
    if any(sum(inst.parcel_mass[x]for x in s.payload_ids)+inst.parcel_mass[z]>phys.drone_payload_limit_kg+1e-9 for s,z in zip((a,b),ps)):continue
    dg['blocks']+=1;save=road(route)-road([x for x in route if x not in (u,v)])
    for rv in sorted(p.visits):
     if rv in(u,v,a.launch_vid,b.launch_vid):continue
     if not allow_cross and p.visits[rv].truck!=t:continue
     for ia,ib in itertools.product(range(len(a.air)+1),range(len(b.air)+1)):
      prox=-save*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)+.00005*(math.dist(xy[u],xy[rv])+math.dist(xy[v],xy[rv]))
      raw.append((prox,t,pos,u,v,a.sid,b.sid,rv,ia,ib))
 dg['raw_total']=len(raw)
 for prox,t,pos,u,v,sa,sb,rv,ia,ib in sorted(raw):
  dg['raw_examined']+=1;q=p.clone();ps=(p.visits[u].ground[0],p.visits[v].ground[0]);block={u,v}
  for vid,parcel in zip((u,v),ps):q.visits[vid].ground.remove(parcel)
  affected=[]
  for s in q.sorties.values():
   changed=False
   if s.rec_vid in block:s.rec_vid=rv;changed=True
   if s.launch_vid in block:s.launch_vid=rv;changed=True
   if s.launch_vid is not None:s.truck=q.visits[s.launch_vid].truck
   if s.launch_truck is not None:s.launch_truck=s.truck
   if changed:affected.append(s.sid)
  q.sorties[sa].air.insert(ia,ps[0]);q.sorties[sb].air.insert(ib,ps[1])
  q.remove_visit(u);q.remove_visit(v)
  cross=any(s.truck!=q.visits[s.rec_vid].truck for s in q.sorties.values())
  if cross and not allow_cross:dg['policy_rejected']+=1;continue
  if any(air_energy(inst,phys,sortie_start(inst,q,s),s.air,xy[s.rec_vid])>phys.e_cap-phys.e_min+phys.energy_tol for s in q.sorties.values()):dg['energy_rejected']+=1;continue
  detail={};seen=set()
  for z in body_covers(q,inst,phys,launch_order,limit=4,node_cap=512,diagnostic=detail):
   sig=identity(z)
   if sig in seen:continue
   seen.add(sig);dg['yielded']+=1
   assert air(z)==air(p)|set(ps)
   yield z,dict(kind='TWO_RENDEZVOUS_BLOCK',parcels=list(ps),old_visits=[u,v],new_rendezvous=rv,sorties=[sa,sb],affected_sorties=affected,insert_positions=[ia,ib],real_cross=cross,proxy=prox,body_catalogue=dict(detail))
  dg['body_nodes']+=detail.get('nodes',0);dg['body_unexpanded']+=detail.get('unexpanded_branches',0)
 dg['raw_unexpanded']=max(0,dg['raw_total']-dg['raw_examined'])

def single_projection(parent,desc,index,inst,phys,launch_order):
 """Exact one-block-component ablation, not a claim of all old ALNS reachability."""
 p=parent.clone();u=desc['old_visits'][index];rv=desc['new_rendezvous'];parcel=desc['parcels'][index];sid=desc['sorties'][index];p.visits[u].ground.remove(parcel)
 for s in p.sorties.values():
  if s.rec_vid==u:s.rec_vid=rv
  if s.launch_vid==u:s.launch_vid=rv
  if s.launch_vid is not None:s.truck=p.visits[s.launch_vid].truck
  if s.launch_truck is not None:s.launch_truck=s.truck
 p.sorties[sid].air.insert(desc['insert_positions'][index],parcel);p.remove_visit(u)
 yield from body_covers(p,inst,phys,launch_order,limit=4,node_cap=512)
