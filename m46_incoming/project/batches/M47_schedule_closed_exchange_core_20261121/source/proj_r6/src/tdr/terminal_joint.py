"""Shared complete multi-sortie closure using ONLY otherwise unspent envelope.
Runs after existing publication selection/neighborhoods. No old plan load,
reserve, second initialization, RNG draw, or extra physical/scenario allowance.
"""
def close(plan,ev,ctx):
 from .nominal_accounting import _ACTIVE,remaining_limit
 from .alns import Budget,SearchStats,eval_counted,_ACTIVE_CTX,_better_air,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok,coordinate_polish
 from .complete_joint import CurrentTransactions,bound,version
 from .expected_cost import expected_j,failure_prob
 from .hybrid import scenario_score
 alg=ctx.alg;envelope=_ACTIVE.get()
 record=dict(stage='terminal_residual_complete_closure',strategy=ctx.strategy,permission=bool(ctx.state.nominal_cross),entry_version=version(plan),entry_budget_used=None if envelope is None else envelope.used,rows=[])
 alg._terminal_joint_records=getattr(alg,'_terminal_joint_records',[])+[record]
 if envelope is None:record['skip']='NO_GLOBAL_ENVELOPE';return plan,ev,0
 left=remaining_limit(envelope.limit);record['remaining_at_entry']=left
 if left<=0:record['skip']='NO_UNSPENT_PHYSICAL_BUDGET';return plan,ev,0
 b=Budget(left,None);ss=SearchStats();ctx.live_budget=b;ctx.live_stats=ss;ctx.scenario_on=True
 ctl=CurrentTransactions(ctx);alg._current_joint_controllers=getattr(alg,'_current_joint_controllers',[])+[ctl]
 token=_ACTIVE_CTX.set(ctx)
 try:
  if not bound(plan,ev,ctx):
   ev=eval_counted(plan,ctx.inst,ctx.phys,ctx.state,ctx.H,'TERMINAL_CURRENT_BIND',ss,b)
   if not bound(plan,ev,ctx):record['skip']='UNBOUND_OR_INFEASIBLE_PARENT';return plan,ev,b.used
  while b.evals_left()>0:
   before=b.used
   prior_rows=len(ctl.rows)
   qe,q,t=ctl.choose(plan,ev,None,None,b,ss)
   for row in ctl.rows[prior_rows:]:row['source']='terminal_remaining_envelope_full_candidate_comparison'
   if b.used==before:break
   if t is None:continue
   # Publication comparator remains unchanged, in addition to strict J/SC gates.
   if not _better_air(qe,q,ev,plan,alg,ctx):t.row['not_selected']='ORIGINAL_PUBLICATION_COMPARATOR';continue
   committed=t.cas(plan,ev,q,qe)
   if committed is None:continue
   plan,ev=committed;t.row.update(original_acceptance_accepted=True,published_current_version=version(plan))
   # Retain original best-triggered coordinate rule and cap, fully charged.
   if b.evals_left()>0:
    if alg.coordinate_light:p2,e2=coordinate_polish(plan,ctx,ss,b,base_ev=ev,cap=alg.coordinate_light_cap)
    else:p2,e2=coordinate_polish(plan,ctx,ss,b,base_ev=ev)
    if e2 is not None and _better_air(e2,p2,ev,plan,alg,ctx)and _within_makespan_cap(e2,ctx)and _nominal_cross_intact(p2,e2,ctx)and _cross_energy_ok(p2,plan,e2,ctx):
     oldJ=expected_j(ev.cost,plan,ctx.inst,ctx.phys,failure_prob(alg));newJ=expected_j(e2.cost,p2,ctx.inst,ctx.phys,failure_prob(alg));oldSC=scenario_score(plan,ev,ctx);newSC=scenario_score(p2,e2,ctx)
     if newJ<=oldJ+alg.cost_tolerance_yuan and oldSC is not None and newSC is not None and newSC<=oldSC+alg.cost_tolerance_yuan:plan,ev=p2,e2
  return plan,ev,b.used
 finally:
  record.update(used=b.used,final_version=version(plan),rows=ctl.rows,stats_audit=ss.audit,work=ctl.summaries(),envelope_after=envelope.summary())
  _ACTIVE_CTX.reset(token)
