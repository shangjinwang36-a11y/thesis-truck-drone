"""Joint nominal depot-release/task-pool/backbone/real-body construction.
No hidden flags, evaluations, RNG, new prices, rescue actions or global deletion
restrictions. All selected reconstructed tasks are independent FIRST flights;
subsequent original flights are rebound over the same physical whole fleet.
"""
import itertools,math
from collections import Counter
from .joint_task_pool import geometries as task_skeletons
from .joint_air_promote import body_covers,air,identity
from .joint_dual import terminal_inventory

def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 from .moves import air_energy,air_time
 from .expected_cost import _failure_cost
 dg=diag if diag is not None else {};dg.update(task_skeletons={},skeletons=0,assignments=0,energy_rejected=0,body_nodes=0,body_unexpanded_branches=0,yielded=0,insufficient_initial_bodies=0)
 if timeline is None or any(s.started or s.handover for s in p.sorties.values()):return
 depot=(inst.depot_x,inst.depot_y);fleet=[f'd{k+1}'for k in range(phys.drone_count)];homes={t:[d for d in fleet if phys.home_truck(d)==t]for t in sorted(p.routes)};seen=set()
 for raw,desc in task_skeletons(p,inst,phys,launch_order,allow_cross,dg['task_skeletons'],timeline,p_fail,initial_release_tasks=True):
  dg['skeletons']+=1;ids=tuple(sid for sid in desc['sorties']if sid in raw.sorties)
  if len(ids)<2 or len(ids)>len(fleet):dg['insufficient_initial_bodies']+=1;continue
  # Complete repartition already used depot geometry. Here primary launch
  # ownership and concrete bodies are chosen jointly, never just edited labels.
  choices=[tuple(t for t in homes if allow_cross or t==raw.visits[raw.sorties[sid].rec_vid].truck)for sid in ids];offers=[]
  for trucks in itertools.product(*choices):
   counts=Counter(trucks)
   if any(counts[t]>len(homes[t])for t in counts):continue
   q=raw.clone();used=Counter();pins={}
   for sid,t in zip(ids,trucks):
    so=q.sorties[sid];so.truck=t;so.launch_truck=t;so.launch_vid=None;so.mode='ARC';so.lam=0.;so.launch_priority=used[t];d=homes[t][used[t]];used[t]+=1;so.drone=d;pins[sid]=d
   if any(air_energy(inst,phys,depot,q.sorties[sid].air,(inst.customer(q.visits[q.sorties[sid].rec_vid].customer).x,inst.customer(q.visits[q.sorties[sid].rec_vid].customer).y))>phys.e_cap-phys.e_min+phys.energy_tol for sid in ids):dg['energy_rejected']+=1;continue
   depot_counts=Counter(so.truck for so in q.sorties.values()if so.launch_vid is None)
   old_counts=Counter(so.truck for so in p.sorties.values()if so.launch_vid is None)
   exposure=sum(max(0,depot_counts[t]-old_counts[t])*phys.prepare_s for t in homes)
   for sid in ids:
    so=q.sorties[sid];rec=inst.customer(q.visits[so.rec_vid].customer);flight=air_time(inst,phys,depot,so.air,(rec.x,rec.y));release=depot_counts[so.truck]*phys.prepare_s+phys.launch_s;exposure+=max(0,release+flight-float(timeline.visit_arr.get(so.rec_vid,0)))
   proxy=desc['proxy']+phys.wage_per_s*exposure+p_fail*(sum(_failure_cost(q,inst,phys,q.sorties[sid])for sid in ids)-sum(_failure_cost(p,inst,phys,p.sorties[sid])for sid in ids))
   offers.append((proxy,trucks,q,pins))
  for proxy,trucks,q,pins in sorted(offers,key=lambda z:(z[0],z[1])):
   dg['assignments']+=1;cover={};order=dict(launch_order);order.update({sid:0. for sid in ids})
   for z in body_covers(q,inst,phys,order,limit=4,node_cap=512,diagnostic=cover,required_first=pins):
    inventory,_=terminal_inventory(z,phys)
    if max(inventory.values(),default=0)>phys.truck_drone_slots:continue
    sig=identity(z)
    if sig in seen:continue
    seen.add(sig)
    assert air(z)==air(p)|set(desc['parcels'])
    assert all(z.drone_sorties[d][0]==sid and z.sorties[sid].truck==phys.home_truck(d)for sid,d in pins.items())
    assert allow_cross or all(so.truck==z.visits[so.rec_vid].truck for so in z.sorties.values())
    out=dict(desc);out.pop('unbound_task_skeleton',None);out.update(construction='JOINT_INITIAL_RELEASE_TASK_BODY_BACKBONE',initial_release={sid:z.sorties[sid].truck for sid in ids},initial_bodies=pins,parallel_distinct_initial_bodies=len(pins),real_cross=any(so.truck!=z.visits[so.rec_vid].truck for so in z.sorties.values()),proxy=proxy,terminal_inventory=inventory,body_catalogue=dict(cover));dg['yielded']+=1
    yield z,out
   dg['body_nodes']+=cover.get('nodes',0);dg['body_unexpanded_branches']+=cover.get('unexpanded_branches',0)
