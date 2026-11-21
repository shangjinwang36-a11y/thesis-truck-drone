from research import *
import gzip
from process_state import record
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok,_ACTIVE_CTX
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.complete_joint import version,complete
from tdr.joint_air_promote import air
from tdr.joint_dual import geometries,terminal_inventory
case=sys.argv[1]if len(sys.argv)>1 else'RC100';stage='visible_dual_'+case;record(stage);dest=ROOT/'diagnostics/dual_visible'/case;assert not dest.exists();dest.mkdir(parents=True)
source=ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/preflight_fresh'/case/'X_RAW.jsonl.gz';input_=None
for line in gzip.open(source,'rt'):
 d=json.loads(line)
 if d['type']=='transaction'and any(x.startswith('SLOT_OVER')for x in d['trace']['violations']):input_=d;break
assert input_;dump(dest/'VISIBLE_INPUT.json',dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),parent=input_['parent'],old_common_child=input_['child'],old_trace=input_['trace'],hidden_world_not_loaded=True))
inst,phys,alg=setup(case,'M14',True);phys.set_active();H=alg._nominal_reference_H;st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True;b=Budget(1000,None);stats=SearchStats();ctx.live_budget=b;ctx.live_stats=stats;tok=_ACTIVE_CTX.set(ctx);dg={};rows=[];wins=[];start=time.perf_counter()
try:
 with rr.audit_evaluations()as audit,cap_physical(1000,reference_H=H)as envelope,gzip.open(dest/'ALL_CANDIDATES.jsonl.gz','wt')as raw:
  try:
   p=plan_from_dict(input_['parent']);old=plan_from_dict(input_['child']);ep=eval_counted(p,inst,phys,st,H,'DUAL_VISIBLE_PARENT',stats,b);eo=eval_counted(old,inst,phys,st,H,'DUAL_VISIBLE_OLD_COMMON',stats,b);assert ep.feasible
   oldstock,oldwhere=terminal_inventory(old,phys);dump(dest/'OLD_COMMON_DIAGNOSIS.json',dict(parent_air=len(air(p)),parent_J=expected_j(ep.cost,p,inst,phys,failure_prob(alg)),old_common_air=len(air(old)),old_common_feasible=eo.feasible,violations=eo.violations,terminal_stock=oldstock,terminal_bodies=oldwhere,H=H))
   stream=geometries(p,inst,phys,{sid:t[0]for sid,t in ep.timeline.launch_times.items()},True,dg,timeline=ep.timeline,p_fail=failure_prob(alg));seen=set()
   for q,desc in stream:
    if b.evals_left()<=0:break
    sig=version(q)
    if sig in seen:continue
    seen.add(sig);qe=eval_counted(q,inst,phys,st,H,'DUAL_VISIBLE_JOINT',stats,b)
    if qe is None:break
    gates=dict(physical=qe.feasible,H=_within_makespan_cap(qe,ctx),robust=_nominal_cross_intact(q,qe,ctx),energy=_cross_energy_ok(q,p,qe,ctx));J=expected_j(qe.cost,q,inst,phys,failure_prob(alg))if qe.feasible else None;pJ=expected_j(ep.cost,p,inst,phys,failure_prob(alg));row=dict(parent_version=version(p),child_version=sig,parent_air=len(air(p)),air=len(air(q)),parent_cost=ep.cost,cost=qe.cost,parent_J=pJ,J=J,gates=gates,descriptor=desc,violations=qe.violations,H=H,actual_H=qe._actual_H,physical_used=b.used)
    assert complete(q,inst)and air(p)<air(q)and len(air(q)-air(p))==2
    if all(gates.values())and J<pJ-alg.cost_tolerance_yuan:
     oldSC=scenario_score(p,ep,ctx);newSC=scenario_score(q,qe,ctx);row.update(parent_SC=oldSC,SC=newSC)
     if oldSC is not None and newSC is not None and newSC<=oldSC+alg.cost_tolerance_yuan:
      wins.append(row);dump(dest/f'WITNESS_{len(wins)}.json',dict(row=row,parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),not_fresh_production=True))
    rows.append(row);raw.write(json.dumps(rr.clean(dict(row=row,plan=plan_to_dict(q,inst))))+'\n')
    if wins and wins[-1]['descriptor']['original_air_repartitioned']:break
  finally:dump(dest/'LEDGER.json',dict(ledger=audit.summary(),envelope=envelope.summary(),seconds=time.perf_counter()-start,physical_used=b.used,catalogue=dg,candidates=len(rows),witnesses=len(wins),all_candidate_inputs_saved=True,no_hidden_world=True,not_fresh_production=True))
finally:_ACTIVE_CTX.reset(tok);record(stage,True,dict(physical=b.used,candidates=len(rows),witnesses=len(wins)))
print('DUAL_VISIBLE',case,len(rows),'wins',len(wins),'physical',b.used,'catalogue',dg,flush=True)
