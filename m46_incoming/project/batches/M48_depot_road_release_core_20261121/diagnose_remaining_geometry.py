from research import *
import gzip,collections
from process_state import record
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok,_ACTIVE_CTX
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.complete_joint import version,complete
from tdr.joint_air_promote import air,body_covers
from tdr.joint_dual import geometries,terminal_inventory
stage='remaining_RC100_visible_evidence';record(stage);dest=ROOT/'diagnostics/remaining_visible_RC100';assert not dest.exists();dest.mkdir(parents=True)
first=read(ROOT/'diagnostics/dual_visible/RC100/LEDGER.json');audit0=read(ROOT/'diagnostics/SLOT_CAUSE_LEDGER.json');prior=first['envelope']['used']+audit0['envelope']['used'];left=1000-prior;assert left>0
inst,phys,alg=setup('RC100','M14',True);phys.set_active();H=alg._nominal_reference_H;st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True;b=Budget(left,None);stats=SearchStats();ctx.live_budget=b;ctx.live_stats=stats;tok=_ACTIVE_CTX.set(ctx);rows=[];wins=[];start=time.perf_counter();work=[]
with rr.audit_evaluations()as au,cap_physical(left,reference_H=H)as en,gzip.open(dest/'ALL_CANDIDATES.jsonl.gz','wt')as raw:
 try:
  z=read(ROOT/'diagnostics/dual_visible/RC100/VISIBLE_INPUT.json');p66=plan_from_dict(z['parent']);bad=plan_from_dict(z['old_common_child']);ep66=eval_counted(p66,inst,phys,st,H,'REMAINING_VISIBLE_PARENT66',stats,b)
  def check(p,e,q,d):
   if b.evals_left()<=0:return False
   qe=eval_counted(q,inst,phys,st,H,'REMAINING_VISIBLE_JOINT',stats,b)
   if qe is None:return False
   gates=dict(physical=qe.feasible,H=_within_makespan_cap(qe,ctx),robust=_nominal_cross_intact(q,qe,ctx),energy=_cross_energy_ok(q,p,qe,ctx));J=expected_j(qe.cost,q,inst,phys,failure_prob(alg))if qe.feasible else None;pJ=expected_j(e.cost,p,inst,phys,failure_prob(alg));r=dict(parent_version=version(p),child_version=version(q),parent_air=len(air(p)),air=len(air(q)),parent_cost=e.cost,cost=qe.cost,parent_J=pJ,J=J,gates=gates,descriptor=d,violations=qe.violations,H=H,physical_used=b.used)
   assert complete(q,inst)and air(p)<air(q)and len(air(q)-air(p))==2
   if all(gates.values())and J<pJ-alg.cost_tolerance_yuan:
    old=scenario_score(p,e,ctx);new=scenario_score(q,qe,ctx);r.update(parent_SC=old,SC=new)
    if old is not None and new is not None and new<=old+alg.cost_tolerance_yuan:wins.append(r);dump(dest/f'WITNESS_{len(wins)}.json',dict(row=r,parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),not_fresh_production=True))
   rows.append(r);raw.write(json.dumps(rr.clean(dict(row=r,plan=plan_to_dict(q,inst))))+'\n');return bool(wins and wins[-1]is r)
  # Causal geometry test only: release an actually present outbound body before
  # the independently proved intermediate stock peak. No stock/H relaxation.
  peaks=read(ROOT/'SLOT_CAUSE_INDEPENDENT_AUDIT.json')['peaks'];seen=set();order={sid:t[0]for sid,t in ep66.timeline.launch_times.items()}
  for truck,pk in peaks.items():
   if pk['peak']<=phys.truck_drone_slots:continue
   for interval in pk['active']:
    if interval['reason']!='ON_TRUCK_UNTIL_L_END':continue
    sid=interval['sid'];so=bad.sorties[sid];route=bad.routes[truck];at=route.index(so.launch_vid)
    for lv in route[:at]:
     for lam in([so.lam,0.,.25,.5,.75,1.]if so.mode=='ARC'else[so.lam]):
      q=bad.clone();q.sorties[sid].launch_vid=lv;q.sorties[sid].lam=lam;q.sorties[sid].truck=truck
      for candidate in body_covers(q,inst,phys,order,limit=4,node_cap=512):
       sig=version(candidate)
       if sig in seen:continue
       seen.add(sig)
       if max(terminal_inventory(candidate,phys)[0].values())>phys.truck_drone_slots:continue
       check(p66,ep66,candidate,dict(kind='SLOT_CAUSE_RELEASE_PROJECTION',released_sortie=sid,old_launch=so.launch_vid,new_launch=lv,lam=lam,original_common_block=z['old_trace']['descriptor'],not_new_dual_algorithm=True))
       if b.evals_left()<=0:break
  # Two visible strong-current hypotheses: exact frozen strong57 and first
  # saved >=58-air parent with best original J (no environment outcomes read).
  allp={}
  for line in gzip.open(ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/diagnostics/strong_core_control/RC100/X_CURRENT.jsonl.gz','rt'):
   d=json.loads(line);allp[d['row']['parent_version']]=d
  kair=read(ROOT.parent/'K1_R10_S_warm_restore_20261120/K1/nominal/S/RC100/result.json')['n_air_parcels'];selected=[]
  exact=next(d for d in allp.values()if d['row']['air']==kair);selected.append(exact)
  higher=[d for d in allp.values()if d['row']['air']>kair]
  if higher:selected.append(min(higher,key=lambda d:(d['row']['J'],d['row']['cost'])))
  for d in selected:
   if b.evals_left()<=0:break
   p=plan_from_dict(d['current']);e=eval_counted(p,inst,phys,st,H,'REMAINING_STRONG_PARENT',stats,b);assert e.feasible;dg={};work.append((p,e,iter(geometries(p,inst,phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},True,dg,timeline=e.timeline,p_fail=failure_prob(alg))),dg));dump(dest/f'VISIBLE_PARENT_{len(work)}.json',d)
  active=collections.deque(range(len(work)))
  while active and b.evals_left()>0:
   ix=active.popleft();p,e,stream,dg=work[ix]
   try:q,d=next(stream)
   except StopIteration:continue
   active.append(ix);sig=(version(p),version(q))
   if sig in seen:continue
   seen.add(sig);yes=check(p,e,q,d)
   if yes and d['original_air_repartitioned']:break
 finally:
  dump(dest/'LEDGER.json',dict(ledger=au.summary(),envelope=en.summary(),prior_paid_physical=prior,this_limit=left,cumulative_physical=prior+b.used,seconds=time.perf_counter()-start,candidates=len(rows),witnesses=len(wins),catalogues=[x[3]for x in work],scope='Remaining diagnostic allocation only; combined initial214+slot1+this<=1000, never production prep/extra optimizer calls.'))
  _ACTIVE_CTX.reset(tok);record(stage,True,dict(physical=b.used,cumulative_physical=prior+b.used,witnesses=len(wins)))
assert prior+b.used<=1000
print('REMAINING_VISIBLE',len(rows),'wins',len(wins),'physical',b.used,'cumulative',prior+b.used,flush=True)
