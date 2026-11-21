"""Strict current-incumbent atomic promotions in an EXISTING ALNS slot.
No epoch, selector label, RNG draw, extra budget or partial-plan patch.
"""
import hashlib,json
from collections import deque
from .joint_air_promote import air,identity,candidates

def version(p):
 # Exact physical plan identity: NEVER reuse rounded scenario/cache geometry.
 data=dict(case_id=p.case_id,routes=p.routes,visits={k:vars(v)for k,v in p.visits.items()},sorties={k:vars(v)for k,v in p.sorties.items()},drone_sorties=p.drone_sorties,next_vid=p.next_vid,next_sid=p.next_sid)
 return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def complete(p,inst):
 x=[a for v in p.visits.values()for a in v.ground]+[a for s in p.sorties.values()for a in s.air]
 return len(x)==len(inst.parcel_mass)and set(x)==set(inst.parcel_mass)
def enabled(ctx):return getattr(ctx.alg,'complete_joint_stage','interleaved')!='terminal'and ctx.mode=='nominal'and getattr(ctx,'scenario_on',False)and bool(getattr(ctx.alg,'complete_joint',False))
def bound(p,e,ctx):
 return bool(e is not None and e.feasible and complete(p,ctx.inst)and getattr(e,'_complete_plan_version',None)==version(p)and getattr(e,'_complete_reference_H',None)==ctx.H==ctx.makespan_cap==ctx.alg._nominal_reference_H)
def candidate_air_ok(parent,child,descriptor):
 pa=air(parent);qa=air(child)
 if descriptor['kind']=='PAID_TRAINING_COMPLETE_REBIND':return pa==qa and not descriptor.get('parcels')
 if descriptor['kind']=='SCHEDULE_CLOSED_DETOUR':return qa-pa==set(descriptor.get('parcels') or []) and len(qa-pa)==1
 return pa<qa
class Work:
 def __init__(self,p,e,ctx):
  if not bound(p,e,ctx):raise ValueError('Complete CURRENT plan/evaluation/H binding required')
  self.parent=p.clone();self.parent_version=version(p);self.ctx=ctx;self.state=repr(vars(ctx.state));self.H=ctx.H;self.diag={};self.pending=deque();self.held=None;self.exhausted=False;self.generated=0;self.evaluated=0;self.seen={identity(p)};self.feedback=None;self.feedback_turn=False
  if getattr(ctx.alg,'joint_dual_recovery',False):
   from .joint_dual import geometries
   from .expected_cost import failure_prob
   self.stream=iter(geometries(self.parent,ctx.inst,ctx.phys,{s:t[0]for s,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag,timeline=e.timeline,p_fail=failure_prob(ctx.alg)))
  elif getattr(ctx.alg,'joint_block',False):
   from .joint_block import geometries
   self.stream=iter(geometries(self.parent,ctx.inst,ctx.phys,{s:t[0]for s,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag))
  else:self.stream=iter(candidates(self.parent,ctx.inst,ctx.phys,{s:t[0]for s,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag,timeline=e.timeline))
  if getattr(ctx.alg,'joint_task_pool',False):
   import itertools
   from .joint_task_pool import geometries as multi_geometries
   from .expected_cost import failure_prob
   self.diag['multi_task_pool']={}
   self.stream=iter(itertools.chain(multi_geometries(self.parent,ctx.inst,ctx.phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag['multi_task_pool'],timeline=e.timeline,p_fail=failure_prob(ctx.alg)),self.stream))
  if getattr(ctx.alg,'joint_initial_release',False):
   import itertools
   from .joint_initial_release import geometries as release_geometries
   from .expected_cost import failure_prob
   self.diag['joint_initial_release']={}
   self.stream=iter(itertools.chain(release_geometries(self.parent,ctx.inst,ctx.phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag['joint_initial_release'],timeline=e.timeline,p_fail=failure_prob(ctx.alg)),self.stream))
  if getattr(ctx.alg,'energy_window_joint',False):
   import itertools
   from .energy_window_joint import geometries as energy_windows
   from .expected_cost import failure_prob
   self.diag['energy_window_joint']={}
   exact_scope=None
   if getattr(ctx.alg,'exact_pure_geometry',False):
    from .exact_geometry_scope import ExactGeometryScope
    self.diag['energy_window_joint']['pure_geometry_cache']={}
    exact_scope=ExactGeometryScope(self.parent,ctx.inst,ctx.phys,ctx.state,ctx.H,{sid:t[0]for sid,t in e.timeline.launch_times.items()},e.timeline,bool(ctx.state.nominal_cross),failure_prob(ctx.alg),self.diag['energy_window_joint']['pure_geometry_cache'])
   self.stream=iter(itertools.chain(energy_windows(self.parent,ctx.inst,ctx.phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag['energy_window_joint'],timeline=e.timeline,p_fail=failure_prob(ctx.alg),exact_scope=exact_scope),self.stream))
  if getattr(ctx.alg,'layered_global_pool',False):
   from .layered_global_pool import geometries as global_geometries
   from .expected_cost import failure_prob
   self.diag={'layered_global_pool':{}}
   self.stream=iter(global_geometries(self.parent,ctx.inst,ctx.phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},bool(ctx.state.nominal_cross),self.diag['layered_global_pool'],timeline=e.timeline,p_fail=failure_prob(ctx.alg)))
  # Only after an ORIGINAL mature full-pool CAS, not a free K1 pre-run.
  # S and X both keep the M46 rebind. X may prepend a detour cross that already
  # predicts an original-J gain; otherwise the X stream is the M46 stream.
  from .paid_training_joint_pool import geometries as training_joint
  self.diag['paid_training_joint']={}
  trained=training_joint(self.parent,e,ctx,self.diag['paid_training_joint'])
  closed=[]
  if bool(ctx.state.nominal_cross):
   from .schedule_closed_exchange import geometries as closed_exchange
   self.diag['schedule_closed_exchange']={}
   closed=closed_exchange(self.parent,e,ctx,self.diag['schedule_closed_exchange'])
  if closed or trained:
   import itertools
   self.stream=iter(itertools.chain(closed,trained,self.stream))
  if getattr(ctx.alg,'paid_recourse_feedback',False):
   from .paid_resource_feedback import ResourceFeedback as PaidFeedback
   self.diag['paid_recourse_feedback']={};self.feedback=PaidFeedback(ctx,self.diag['paid_recourse_feedback'])
 def next(self):
  def feedback_item():
   while True:
    item=self.feedback.next()
    if item is None:return None
    q,d=item;sig=identity(q)
    if sig in self.seen:continue
    self.seen.add(sig);self.generated+=1;self.feedback_turn=False
    from .proposal_geometry import refresh
    return q,refresh(q,d,self.ctx.inst)
  if self.feedback is not None and(self.feedback_turn or(self.exhausted and not self.pending and self.held is None)):
   item=feedback_item()
   if item is not None:return item
  item=self._base_next();self.feedback_turn=True
  if item is None and self.feedback is not None:return feedback_item()
  return item
 def _base_next(self):
  while True:
   if not self.pending:
    if self.exhausted:return None
    groups=[];key0=None
    while len(groups)<8 or key0 is not None:
     if self.held is not None:item=self.held;self.held=None
     else:
      try:item=next(self.stream)
      except StopIteration:self.exhausted=True;break
     q,d=item
     if d['kind']in('MULTI_TASK_POOL_RECONSTRUCTION','PAID_TRAINING_COMPLETE_REBIND'):key=(tuple(d['old_visits']),tuple(d['sorties']),tuple(d['new_rendezvous']),tuple((sid,tuple(g))for sid,g in d['air_groups'].items()))
     elif d['kind']=='DUAL_RECOVERY_AIR_REPARTITION':key=(tuple(d['old_visits']),tuple(d['sorties']),tuple(d['new_rendezvous']),tuple(tuple(x)for x in d['air_groups']))
     elif d['kind']=='TWO_RENDEZVOUS_BLOCK':key=(tuple(d['old_visits']),tuple(d['sorties']),d['new_rendezvous'],tuple(d['insert_positions']))
     else:key=tuple(d[k]for k in ['sortie','parcel','old_visit','new_rendezvous','kind','insert_position'])
     if d.get('initial_release'):key=key+(tuple(sorted(d['initial_release'].items())),)
     if key!=key0:
      if len(groups)>=8:self.held=item;break
      groups.append([]);key0=key
     groups[-1].append(item)
    for k in range(max((len(g)for g in groups),default=0)):
     for g in groups:
      if k<len(g):self.pending.append(g[k])
    if not self.pending:return None
   q,d=self.pending.popleft();sig=identity(q)
   if sig in self.seen:self.diag['duplicates']=self.diag.get('duplicates',0)+1;continue
   self.seen.add(sig);self.generated+=1
   from .proposal_geometry import refresh
   return q,refresh(q,d,self.ctx.inst)
 def summary(self):
  return dict(parent_version=self.parent_version,parent_air=len(air(self.parent)),generated=self.generated,evaluated=self.evaluated,pending_complete_offers=len(self.pending)+(self.held is not None),unexpanded_raw_geometries=max(0,self.diag.get('raw_total',0)-self.diag.get('raw_examined',0)),catalogue=dict(self.diag),stream_exhausted=self.exhausted,H=self.H,old_work_never_commits_as_new_current=True)
class Ticket:
 def __init__(self,p,e,q,qe,ctx,row):self.p=p;self.e=e;self.q=q;self.qe=qe;self.ctx=ctx;self.added=frozenset(row['new_air']);self.parent=row['parent_version'];self.child=version(q);self.state=repr(vars(ctx.state));self.H=ctx.H;self.row=row;self.done=False
 def valid(self,p,e,q=None,qe=None):
  q=self.q if q is None else q;qe=self.qe if qe is None else qe
  kind=self.row['descriptor']['kind']
  return bool(not self.done and p is self.p and e is self.e and version(p)==self.parent and bound(p,e,self.ctx)and repr(vars(self.ctx.state))==self.state and self.ctx.H==self.H and q is self.q and qe is self.qe and version(q)==self.child and bound(q,qe,self.ctx)and candidate_air_ok(p,q,self.row['descriptor'])and air(q)-air(p)==self.added and (kind=='PAID_TRAINING_COMPLETE_REBIND'or len(self.added)in(1,2)or(kind=='MULTI_TASK_POOL_RECONSTRUCTION'and self.added==frozenset(self.row['descriptor']['parcels'])and len(self.added)>=3)))
 def cas(self,p,e,q,qe):
  self.row['commit_observed_current_version']=version(p);self.row['commit_observed_evaluation_version']=getattr(e,'_complete_plan_version',None);self.row['commit_actual_H']=self.ctx.H
  if not self.valid(p,e,q,qe):self.row.update(cas=False,commit_rejected='STALE_CURRENT_OR_EVALUATION_OR_CHILD_H');return None
  result=q.clone();assert version(result)==self.child
  if self.row['descriptor']['kind']=='MULTI_TASK_POOL_RECONSTRUCTION':
   if not hasattr(self.ctx.alg,'_mature_fullpool_air_sets'):self.ctx.alg._mature_fullpool_air_sets=set()
   self.ctx.alg._mature_fullpool_air_sets.add(tuple(sorted(air(result))))
  self.done=True;self.row.update(cas=True,committed_child_version=version(result));return result,qe
class CurrentTransactions:
 def __init__(self,ctx):self.ctx=ctx;self.work=None;self.retired=[];self.rows=[];self.bank={};self.transitions=[]
 def current_work(self,p,e):
  if not bound(p,e,self.ctx):return None
  if self.work is None or self.work.parent_version!=version(p)or self.work.state!=repr(vars(self.ctx.state))or self.work.H!=self.ctx.H:
   if self.work is not None and self.work not in self.retired:self.retired.append(self.work)
   key=(version(p),repr(vars(self.ctx.state)),self.ctx.H)
   if key not in self.bank:self.bank[key]=Work(p,e,self.ctx)
   previous=self.work.parent_version if self.work is not None else None
   self.work=self.bank[key]
   self.transitions.append(dict(old_parent_version=previous,new_parent_version=version(p),new_parent_air=len(air(p)),reused_pending_parent=self.work.generated>0))
  return self.work
 def summaries(self):return[w.summary()for w in self.bank.values()]
 def offer(self,p,e,budget,stats):
  from .alns import eval_counted,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok
  from .expected_cost import expected_j,failure_prob
  if budget.evals_left()<=0:return None
  work=self.current_work(p,e)
  if work is None:return None
  item=work.next()
  if item is None:return None
  q,d=item;parentseal=version(p);pa=air(p)
  expected_new=set(d['parcels'])if d['kind']=='MULTI_TASK_POOL_RECONSTRUCTION'else None
  size_ok=(air(q)-pa==set(d['parcels']) and len(d['parcels'])==1)if d['kind']=='SCHEDULE_CLOSED_DETOUR'else (air(q)==pa)if d['kind']=='PAID_TRAINING_COMPLETE_REBIND'else (air(q)-pa==expected_new and len(expected_new)>=3)if expected_new is not None else len(air(q)-pa)==(2 if getattr(self.ctx.alg,'joint_block',False)else 1)
  if not complete(q,self.ctx.inst)or not candidate_air_ok(p,q,d)or not size_ok or q.validate_structure(self.ctx.inst,self.ctx.phys):raise ValueError('Unclosed current-parent promotion')
  qe=eval_counted(q,self.ctx.inst,self.ctx.phys,self.ctx.state,self.ctx.H,'CURRENT_PARENT_JOINT',stats,budget)
  if qe is None:return None
  work.evaluated+=1
  gates=dict(physical=qe.feasible,cap=_within_makespan_cap(qe,self.ctx),robust=_nominal_cross_intact(q,qe,self.ctx),energy=_cross_energy_ok(q,p,qe,self.ctx))
  parent_J=expected_j(e.cost,p,self.ctx.inst,self.ctx.phys,failure_prob(self.ctx.alg));snapshot=None
  if work.feedback is not None and qe.feasible:
   from .paid_recourse_feedback import capture_expected_j
   child_J,snapshot=capture_expected_j(qe.cost,q,self.ctx.inst,self.ctx.phys,failure_prob(self.ctx.alg))
  else:child_J=expected_j(qe.cost,q,self.ctx.inst,self.ctx.phys,failure_prob(self.ctx.alg))if qe.feasible else None
  row=dict(parent_version=parentseal,evaluation_parent_version=getattr(e,'_complete_plan_version',None),child_version=version(q),evaluation_child_version=getattr(qe,'_complete_plan_version',None),parent_air=len(pa),child_air=len(air(q)),new_air=sorted(air(q)-pa),parent_air_ids=sorted(pa),all_parent_air_preserved=pa<=air(q),complete_customers=len(q.assigned_parcels()),descriptor=d,parent_cost=e.cost,cost=qe.cost,parent_J=parent_J,J=child_J,gates=gates,H=self.ctx.H,evaluation_H=getattr(qe,'_actual_H',None),physical_used=budget.used,violations=qe.violations,cas=False,source='existing_complete_candidate_comparison_slot',construction_current_version=version(p))
  if snapshot is not None:row['paid_recourse_snapshot']=snapshot
  if work.feedback is not None:work.feedback.observe(q,qe,row,snapshot,d)
  self.rows.append(row);self.ctx.alg._current_joint_rows=getattr(self.ctx.alg,'_current_joint_rows',[])+[row]
  rec=getattr(self.ctx.alg,'_current_joint_recorder',None)
  if rec:rec(p,q,qe,row)
  ticket=Ticket(p,e,q,qe,self.ctx,row)
  if not all(gates.values())or not ticket.valid(p,e):row['eligible']=False;return None
  row['eligible']=True;return ticket
 def choose(self,p,e,legacy_plan,legacy_ev,budget,stats):
  from .alns import _better_air
  from .hybrid import scenario_score
  # Preserve mature feasible candidate slots; only close a physically dead trial.
  if getattr(self.ctx.alg,'joint_block_dead_trial_only',False)and legacy_ev is not None:return legacy_ev,legacy_plan,None
  t=self.offer(p,e,budget,stats)
  if t is None:return legacy_ev,legacy_plan,None
  row=t.row
  # Stricter monotone screen ONLY for this new transaction family. No change to
  # legacy full ALNS candidate/SA eligibility, original comparator or objective.
  if row['J']>=row['parent_J']-self.ctx.alg.cost_tolerance_yuan:row['not_selected']='NO_ORIGINAL_J_GAIN';return legacy_ev,legacy_plan,None
  old=scenario_score(p,e,self.ctx);new=scenario_score(t.q,t.qe,self.ctx);row.update(parent_scenario=old,scenario=new)
  if old is None or new is None or new>old+self.ctx.alg.cost_tolerance_yuan:row['not_selected']='SCENARIO_CAP_OR_NOT_BETTER';return legacy_ev,legacy_plan,None
  if not t.valid(p,e):row['not_selected']='STALE_BEFORE_COMPARE';return legacy_ev,legacy_plan,None
  if legacy_ev is not None and not _better_air(t.qe,t.q,legacy_ev,legacy_plan,self.ctx.alg,self.ctx):row['not_selected']='LEGACY_FULL_CANDIDATE_BETTER';return legacy_ev,legacy_plan,None
  row['selected']=True;return t.qe,t.q,t
