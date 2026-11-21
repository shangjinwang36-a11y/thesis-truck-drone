"""Nominal real-body token propagation over the fixed visit/flight event DAG.
Necessary stock/precedence checks do not call a scheduler/evaluator. Cover labels
are alternatives, not free physical evaluations; actual energy/H/custody remain
paid full-plan gates. One topological linearization is enough for token topology:
unordered vertices have independent truck pools; all incoming R precede local L.
"""
from collections import defaultdict
import heapq

def home_stock(phys):
 s={f't{i+1}':0 for i in range(phys.truck_count)}
 for i in range(phys.drone_count):s[phys.home_truck(f'd{i+1}')]+=1
 return s

def frame(p,sk,mapping,phys):
 edges={v:set()for v in sk.visits};rec=defaultdict(list);launch=defaultdict(list);starts=home_stock(phys);stock=dict(starts)
 for t,r in sk.routes.items():
  dep=('DEPOT',t);edges[dep]=set()
  if r:edges[dep].add(r[0])
  for x,y in zip(r,r[1:]):edges[x].add(y)
 for so in p.sorties.values():
  if so.started or so.landed:return dict(possible=False,unsupported_started_or_landed=True)
  lv=mapping.get(so.launch_vid,so.launch_vid);rv=mapping.get(so.rec_vid,so.rec_vid)
  if rv not in sk.visits or(lv is not None and lv not in sk.visits):return dict(possible=False,missing_reference=True)
  lt=sk.visits[lv].truck if lv is not None else so.truck;rt=sk.visits[rv].truck;node=lv if lv is not None else('DEPOT',lt);edges[node].add(rv);launch[node].append(so.sid);rec[rv].append(so.sid)
 prefix_bad=[]
 for t,r in sk.routes.items():
  stock[t]-=len(launch[('DEPOT',t)])
  if stock[t]<0:prefix_bad.append(dict(truck=t,visit='DEPOT',after_L=stock[t],reason='NO_INITIAL_BODY'))
  for vid in r:
   before=stock[t];stock[t]+=len(rec[vid]);after_R=stock[t]
   if after_R>phys.truck_drone_slots:prefix_bad.append(dict(truck=t,visit=vid,before=before,after_R=after_R,reason='R_BEFORE_P_L_SLOT_OVER'))
   stock[t]-=len(launch[vid])
   if stock[t]<0:prefix_bad.append(dict(truck=t,visit=vid,after_L=stock[t],reason='BODY_PREFIX_NEGATIVE'))
 indeg={v:0 for v in edges}
 for vs in edges.values():
  for v in vs:indeg[v]+=1
 todo=[(repr(v),v)for v,k in indeg.items()if not k];heapq.heapify(todo);ordered=[]
 while todo:
  _,v=heapq.heappop(todo);ordered.append(v)
  for w in edges[v]:
   indeg[w]-=1
   if not indeg[w]:heapq.heappush(todo,(repr(w),w))
 cyc=len(ordered)!=len(edges);bad={t:n for t,n in stock.items()if n<0 or n>phys.truck_drone_slots}
 return dict(possible=not cyc and not bad and not prefix_bad,precedence_cycle=cyc,terminal_flow_bad=bad,terminal_flow=stock,prefix_bad=prefix_bad,topological_visits=ordered)

def truck_pair_domains(p,u,v,phys):
 out=defaultdict(set);ts=sorted(p.routes);home=home_stock(phys)
 for a in ts:
  for b in ts:
   st=dict(home)
   for so in p.sorties.values():
    lt=a if so.launch_vid==u else b if so.launch_vid==v else p.visits[so.launch_vid].truck if so.launch_vid is not None else so.truck
    rt=a if so.rec_vid==u else b if so.rec_vid==v else p.visits[so.rec_vid].truck
    st[lt]-=1;st[rt]+=1
   if all(0<=x<=phys.truck_drone_slots for x in st.values()):out[a].add(b)
 return dict(out)

def covers(p,inst,phys,launch_order,limit=4,node_cap=512,diagnostic=None):
 dg=diagnostic if diagnostic is not None else {};fr=frame(p,p,{},phys);dg.update(nodes=0,yielded=0,unexpanded_branches=0,node_cap=node_cap,cover_limit=limit,frame_possible=fr['possible'],frame=fr)
 if not fr['possible']:return
 rec=defaultdict(list);launch=defaultdict(list)
 for so in p.sorties.values():rec[so.rec_vid].append(so.sid);launch[so.launch_vid if so.launch_vid is not None else('DEPOT',so.truck)].append(so.sid)
 events=[]
 for node in fr['topological_visits']:
  t=node[1]if isinstance(node,tuple)else p.visits[node].truck
  events.extend(('R',sid,t)for sid in sorted(rec[node],key=lambda sid:(p.sorties[sid].rec_priority,sid)))
  events.extend(('L',sid,t)for sid in sorted(launch[node],key=lambda sid:(p.sorties[sid].launch_priority,sid)))
 fleet=[f'd{i+1}'for i in range(phys.drone_count)];pool={t:[]for t in p.routes};chains={d:[]for d in fleet};flight_body={};seen=set()
 for d in fleet:pool[phys.home_truck(d)].append(d)
 def dfs(i):
  if dg['nodes']>=node_cap or dg['yielded']>=limit:dg['unexpanded_branches']+=1;return
  dg['nodes']+=1
  if i==len(events):
   q=p.clone();q.drone_sorties={d:list(v)for d,v in chains.items()}
   for sid,d in flight_body.items():q.sorties[sid].drone=d
   if q.validate_structure(inst,phys):return
   sig=tuple((d,tuple(v))for d,v in sorted(q.drone_sorties.items()))
   if sig not in seen:seen.add(sig);dg['yielded']+=1;yield q
   return
  kind,sid,t=events[i]
  if kind=='R':
   dr=flight_body[sid];assert dr not in pool[t];pool[t].append(dr);yield from dfs(i+1);pool[t].remove(dr);return
  choices=sorted(pool[t],key=lambda d:(d!=p.sorties[sid].drone,len(chains[d]),d))
  for k,dr in enumerate(choices):
   if dg['nodes']>=node_cap or dg['yielded']>=limit:dg['unexpanded_branches']+=len(choices)-k;break
   pool[t].remove(dr);chains[dr].append(sid);flight_body[sid]=dr;yield from dfs(i+1);del flight_body[sid];chains[dr].pop();pool[t].append(dr)
 yield from dfs(0)
