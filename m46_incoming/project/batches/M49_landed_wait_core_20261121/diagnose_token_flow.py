from research import *
import gzip
from process_state import record
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok
from tdr.complete_joint import version,complete
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.joint_dual_dependency import geometries,dependent_states
from tdr.joint_air_promote import air,body_covers
from tdr.moves import ground_candidates
stage='C50_token_flow_evidence';record(stage);dest=ROOT/'diagnostics/token_flow/C50';assert not dest.exists();dest.mkdir(parents=True);z=read(ROOT/'diagnostics/launch_dependency/C50/VISIBLE_INPUT.json');p=plan_from_dict(z['parent']);dd=z['trace']['descriptor'];inst,phys,alg=setup('C50','M14',True);phys.set_active();H=alg._nominal_reference_H;st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True;prior=read(ROOT/'diagnostics/dependency_frame/C50/LEDGER.json')['cumulative_physical'];b=Budget(1000-prior,None);ss=SearchStats();ctx.live_budget=b;ctx.live_stats=ss;tok=_ACTIVE_CTX.set(ctx);dg={};rows=[];wins=[];start=time.perf_counter()
try:
 with rr.audit_evaluations()as au,cap_physical(b.eval_limit,reference_H=H)as en,gzip.open(dest/'ALL_CANDIDATES.jsonl.gz','wt')as raw:
  try:
   ep=eval_counted(p,inst,phys,st,H,'FRAME_PARENT',ss,b);kp=plan_from_dict(read(ROOT.parent/'K1_R10_S_warm_restore_20261120/K1/nominal/X/C50/nominal_plan.json')['plan']);ek=eval_counted(kp,inst,phys,st,H,'FRAME_K1_REFERENCE',ss,b);kSC=scenario_score(kp,ek,ctx);u,v=dd['old_visits'];a,bid=dd['sorties'];sa,sb=p.sorties[a],p.sorties[bid];union=tuple(dict.fromkeys([*sa.air,*sb.air,*dd['parcels']]));sk=p.clone();sk.remove_visit(u);sk.remove_visit(v);eligible=[rv for rv in sorted(sk.visits)if rv not in(sa.launch_vid,sb.launch_vid)];Q={(x,rv):ground_candidates(sk,inst,phys,x,receipt_vid=rv)[0].proxy for x in union for rv in eligible};order={sid:t[0]for sid,t in ep.timeline.launch_times.items()};oldDG={'_allow_cross':True,'_exact_frame_screen':False};list(dependent_states(p,sk,inst,phys,sa,sb,u,v,union,eligible,Q,order,ep.timeline,.2,oldDG));dump(dest/'PRIOR_TOP8_EXACT_FRAME_DIAGNOSIS.json',oldDG)
   pJ=expected_j(ep.cost,p,inst,phys,failure_prob(alg));seen=set()
   for q,d in geometries(p,inst,phys,order,True,dg,timeline=ep.timeline,p_fail=failure_prob(alg)):
    if b.evals_left()<=0:break
    sig=version(q)
    if sig in seen:continue
    seen.add(sig);e=eval_counted(q,inst,phys,st,H,'FRAME_COMPLETE_JOINT',ss,b);gates=dict(physical=e.feasible,H=_within_makespan_cap(e,ctx),robust=_nominal_cross_intact(q,e,ctx),energy=_cross_energy_ok(q,p,e,ctx));J=expected_j(e.cost,q,inst,phys,failure_prob(alg))if e.feasible else None;r=dict(parent_version=version(p),child_version=sig,parent_air=len(air(p)),air=len(air(q)),parent_cost=ep.cost,cost=e.cost,parent_J=pJ,J=J,gates=gates,descriptor=d,violations=e.violations,H=H,K1_cost=ek.cost,K1_SC=kSC)
    if all(gates.values())and J<pJ-alg.cost_tolerance_yuan:
     ps=scenario_score(p,ep,ctx);sc=scenario_score(q,e,ctx);r.update(parent_SC=ps,SC=sc)
     if ps is not None and sc is not None and sc<=ps+alg.cost_tolerance_yuan:
      bare=q.clone();bare.drone_sorties={dr:list(vv)for dr,vv in p.drone_sorties.items()}
      for sid,so in bare.sorties.items():so.drone=p.sorties[sid].drone
      oldCoverDG={};oldCovers=list(body_covers(bare,inst,phys,order,limit=4,node_cap=512,diagnostic=oldCoverDG));r['old_body_catalogue']=dict(covers=len(oldCovers),diagnostic=oldCoverDG,new_labeling_in_old=version(q)in{version(x)for x in oldCovers})
      wins.append(r);dump(dest/f'WITNESS_{len(wins)}.json',dict(row=r,parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),offline_only=True))
    rows.append(r);raw.write(json.dumps(rr.clean(dict(row=r,plan=plan_to_dict(q,inst))))+'\n')
    if wins and wins[-1]is r and d['primary_launch_dependency']and sc<=kSC+alg.cost_tolerance_yuan:break
  finally:dump(dest/'LEDGER.json',dict(ledger=au.summary(),envelope=en.summary(),prior_paid_physical=prior,cumulative_physical=prior+b.used,catalogue=dg,candidates=len(rows),wins=len(wins),seconds=time.perf_counter()-start,all_inputs_saved=True,offline_only=True))
finally:_ACTIVE_CTX.reset(tok);record(stage,True,dict(physical=b.used,wins=len(wins)))
print('FRAME_VISIBLE',len(rows),'wins',len(wins),'physical',b.used,'cumulative',prior+b.used,'diag',dg,flush=True)
