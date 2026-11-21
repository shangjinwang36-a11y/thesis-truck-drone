from research import *
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.simulate import initial_run_state,collect_segment
from tdr.verify import verify_plan
from tdr.complete_joint import version
from tdr.joint_dual import terminal_inventory
from bill import bill
from process_state import record
record('independent_dual_witness');w=read(ROOT/'diagnostics/remaining_visible_RC100/WITNESS_1.json');r=w['row'];inst,phys,alg=setup('RC100','M14',True);phys.set_active();H=alg._nominal_reference_H;p=plan_from_dict(w['parent']);q=plan_from_dict(w['child']);st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True;b=Budget(2,None);stats=SearchStats();ctx.live_budget=b;ctx.live_stats=stats;tok=_ACTIVE_CTX.set(ctx)
try:
 with rr.audit_evaluations()as au,cap_physical(2,reference_H=H)as en:
  try:
   es=[eval_counted(z,inst,phys,st,H,'INDEPENDENT_DUAL_WITNESS',stats,b)for z in[p,q]];assert all(e.feasible for e in es);J=[expected_j(e.cost,z,inst,phys,failure_prob(alg))for e,z in zip(es,[p,q])];SC=[scenario_score(z,e,ctx)for e,z in zip(es,[p,q])];assert J[1]<J[0]and SC[1]<SC[0];tl=es[1].timeline;end=max([*tl.truck_finish.values(),*[a.end for ss in tl.drone_stages.values()for a in ss]]);seg=collect_segment(q,tl,inst,phys,0,end,initial_run_state(q,inst,phys));rp=rr.verify_replay(inst,phys,[seg],H,'X');parts=bill([rr.clean(seg)],phys,H);vp=verify_plan(inst,st,q,'X',phys,H);assert rp.ok and vp.ok and rp.delivered==inst.n and abs(sum(parts.values())-es[1].cost)<1e-7
   out=dict(source='Offline visible current diagnostic only; NOT qualifying fresh production proof',parent_version=version(p),child_version=version(q),row=r,parent_plan=w['parent'],child_plan=w['child'],costs=[e.cost for e in es],J=J,fixed_SC=SC,H=H,completion=max(tl.truck_finish.values()),min_all_stage_energy=min(x for ee in tl.drone_energy.values()for x in ee),parts=parts,replay=rr.clean(rp),scheduler=rr.clean(vp),custody_violations=tl.custody_violations,terminal_inventory=terminal_inventory(q,phys)[0],segments=[rr.clean(seg)])
   dump(ROOT/'DUAL_OFFLINE_WITNESS_INDEPENDENT_AUDIT.json',out)
  finally:dump(ROOT/'diagnostics/DUAL_WITNESS_AUDIT_LEDGER.json',dict(ledger=au.summary(),envelope=en.summary()))
finally:_ACTIVE_CTX.reset(tok);record('independent_dual_witness',True,dict(calls=au.summary()['accepted_calls']))
print('DUAL_WITNESS_AUDIT',out['costs'],J,SC,'minE',out['min_all_stage_energy'])
