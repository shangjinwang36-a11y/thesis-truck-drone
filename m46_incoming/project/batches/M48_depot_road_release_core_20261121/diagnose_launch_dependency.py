from research import *
import gzip
from process_state import record
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok
from tdr.complete_joint import version,complete
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.joint_dual_dependency import geometries
from tdr.joint_air_promote import air
stage='visible_C50_launch_dependency';record(stage);dest=ROOT/'diagnostics/launch_dependency/C50';assert not dest.exists();dest.mkdir(parents=True)
f=ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/preflight_fresh/C50/X_RAW.jsonl.gz';z=next(json.loads(x)for x in gzip.open(f,'rt')if json.loads(x)['type']=='transaction');p=plan_from_dict(z['parent']);old=plan_from_dict(z['child']);dump(dest/'VISIBLE_INPUT.json',z)
inst,phys,alg=setup('C50','M14',True);phys.set_active();H=alg._nominal_reference_H;st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True;b=Budget(1000,None);ss=SearchStats();ctx.live_budget=b;ctx.live_stats=ss;tok=_ACTIVE_CTX.set(ctx);dg={};rows=[];wins=[];start=time.perf_counter()
try:
 with rr.audit_evaluations()as au,cap_physical(1000,reference_H=H)as en,gzip.open(dest/'ALL_CANDIDATES.jsonl.gz','wt')as raw:
  try:
   ep=eval_counted(p,inst,phys,st,H,'DEPENDENCY_PARENT',ss,b);eo=eval_counted(old,inst,phys,st,H,'DEPENDENCY_OLD_COMMON',ss,b);assert ep.feasible and eo.feasible
   kp=plan_from_dict(read(ROOT.parent/'K1_R10_S_warm_restore_20261120/K1/nominal/X/C50/nominal_plan.json')['plan']);ek=eval_counted(kp,inst,phys,st,H,'DEPENDENCY_FROZEN_K1_REFERENCE',ss,b);kSC=scenario_score(kp,ek,ctx);pJ=expected_j(ep.cost,p,inst,phys,failure_prob(alg))
   for q,d in geometries(p,inst,phys,{sid:t[0]for sid,t in ep.timeline.launch_times.items()},True,dg,timeline=ep.timeline,p_fail=failure_prob(alg)):
    if b.evals_left()<=0:break
    e=eval_counted(q,inst,phys,st,H,'DEPENDENCY_JOINT',ss,b);gates=dict(physical=e.feasible,H=_within_makespan_cap(e,ctx),robust=_nominal_cross_intact(q,e,ctx),energy=_cross_energy_ok(q,p,e,ctx));J=expected_j(e.cost,q,inst,phys,failure_prob(alg))if e.feasible else None;r=dict(parent_version=version(p),child_version=version(q),parent_air=len(air(p)),air=len(air(q)),parent_cost=ep.cost,cost=e.cost,parent_J=pJ,J=J,gates=gates,descriptor=d,violations=e.violations,H=H,K1_cost=ek.cost,K1_SC=kSC)
    if all(gates.values())and J<pJ-alg.cost_tolerance_yuan:
     ps=scenario_score(p,ep,ctx);sc=scenario_score(q,e,ctx);r.update(parent_SC=ps,SC=sc)
     if ps is not None and sc is not None and sc<=ps+alg.cost_tolerance_yuan:
      wins.append(r);dump(dest/f'WITNESS_{len(wins)}.json',dict(row=r,parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),offline_only=True))
    rows.append(r);raw.write(json.dumps(rr.clean(dict(row=r,plan=plan_to_dict(q,inst))))+'\n')
    if wins and wins[-1]is r and d['primary_launch_dependency']and sc<=kSC+alg.cost_tolerance_yuan:break
  finally:dump(dest/'LEDGER.json',dict(ledger=au.summary(),envelope=en.summary(),catalogue=dg,candidates=len(rows),wins=len(wins),seconds=time.perf_counter()-start,no_hidden_world=True,offline_only=True))
finally:_ACTIVE_CTX.reset(tok);record(stage,True,dict(physical=b.used,wins=len(wins)))
print('DEPENDENCY_VISIBLE',len(rows),'wins',len(wins),'physical',b.used,'diag',dg,flush=True)
