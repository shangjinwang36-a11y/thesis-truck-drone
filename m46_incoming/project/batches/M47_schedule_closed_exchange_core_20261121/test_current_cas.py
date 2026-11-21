from research import *
import pytest,gzip,random,inspect
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX
from tdr.complete_joint import CurrentTransactions,version,complete,bound,enabled
from tdr.joint_air_promote import air
@pytest.fixture
def env():
 inst,phys,alg=setup('RC100','M12',True);H=alg._nominal_reference_H;alg.joint_block=False;alg.joint_dual_recovery=False;phys.set_active();st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst=inst,phys=phys,alg=alg,state=st,H=None,mode='nominal',rngs={k:random.Random(17)for k in ['operator','destroy','accept']});ctx.scenario_on=True;b=Budget(32,None);stats=SearchStats();ctx.live_budget=b;ctx.live_stats=stats;p47=None
 with gzip.open(ROOT.parent/'M11_complete_incumbent_joint_air_20261121/M11/nominal_raw/RC100_S.jsonl.gz','rt')as f:
  for l in f:
   d=json.loads(l)
   if d['type']=='full_evaluation'and d['evaluation']['feasible']:
    p=plan_from_dict(d['plan'])
    if len(air(p))==47 and complete(p,inst):p47=p;break
 assert p47
 p52=plan_from_dict(read(ROOT.parent/'M11_complete_incumbent_joint_air_20261121/M11/nominal/S/RC100/nominal_plan.json')['plan']);assert len(air(p52))==52
 with cap_physical(32,reference_H=H):
  tok=_ACTIVE_CTX.set(ctx)
  try:
   e47=eval_counted(p47,inst,phys,st,H,'CAS_TEST_47',stats,b);e52=eval_counted(p52,inst,phys,st,H,'CAS_TEST_52',stats,b);assert e47.feasible and e52.feasible;yield p47,e47,p52,e52,ctx,b,stats
  finally:_ACTIVE_CTX.reset(tok)
def ticket(env):
 p,e,_,_,ctx,b,s=env;ctl=CurrentTransactions(ctx)
 for _ in range(12):
  t=ctl.offer(p,e,b,s)
  if t:return ctl,t
 pytest.fail('No legal fixture ticket')
def test_actual_parent_changes_47_to_52_and_paid_new_action_is_from52(env):
 p,e,n,ne,ctx,b,s=env;ctl=CurrentTransactions(ctx);w=ctl.current_work(p,e);before=b.used;ctl.offer(n,ne,b,s);assert ctl.work is not w and ctl.retired==[w];assert ctl.rows[-1]['parent_air']==52 and ctl.rows[-1]['parent_version']==version(n)==ne._complete_plan_version;assert b.used==before+1

def test_stale_old_ticket_cannot_overwrite_new52_current(env):
 p,e,n,ne,ctx,b,s=env;ctl,t=ticket(env);before=b.used;assert t.cas(n,ne,t.q,t.qe)is None;assert len(air(n))==52 and b.used==before;ctl.offer(n,ne,b,s);assert ctl.rows[-1]['parent_air']==52

def test_already_added_customer_not_overwritten_by_old_patch(env):
 p,e,_,_,ctx,b,s=env;ctl,t=ticket(env);q=t.q.clone();qe=eval_counted(q,ctx.inst,ctx.phys,ctx.state,ctx.H,'CAS_TEST_NEW_CURRENT_ALREADY_ASSIGNED',s,b);added=set(t.row['new_air']);assert added<=air(q);assert t.cas(q,qe,t.q,t.qe)is None;before=b.used;ctl.offer(q,qe,b,s);assert b.used==before+1 and not(added&set(ctl.rows[-1]['new_air']));assert added<=air(q)

def test_single_paid_evaluation_same_H_and_CAS_identity(env):
 p,e,_,_,ctx,b,s=env;ctl=CurrentTransactions(ctx);t=None
 for _ in range(12):
  old=b.used;t=ctl.offer(p,e,b,s);assert b.used==old+1
  if t:break
 assert t;before=b.used;out=t.cas(p,e,t.q,t.qe);assert out and b.used==before;assert t.row['parent_version']==t.row['commit_observed_current_version']==t.row['commit_observed_evaluation_version'];assert t.row['child_version']==t.row['evaluation_child_version']==t.row['committed_child_version'];assert t.row['H']==t.row['evaluation_H']==t.row['commit_actual_H'];assert t.cas(p,e,t.q,t.qe)is None

def test_stale_H_and_child_evaluation_mutation_rejected(env):
 p,e,_,_,ctx,b,s=env;ctl,t=ticket(env);ctx.H+=1;assert t.cas(p,e,t.q,t.qe)is None;ctx.H-=1;t.q.next_vid+=1;assert t.cas(p,e,t.q,t.qe)is None

def test_constructor_and_evaluation_do_not_consume_ALNS_RNG(env):
 p,e,_,_,ctx,b,s=env;ctl=CurrentTransactions(ctx);before={k:r.getstate()for k,r in ctx.rngs.items()};ctl.offer(p,e,b,s);assert before=={k:r.getstate()for k,r in ctx.rngs.items()}

def test_budget_exhaustion_no_extra_call_or_new_budget(env):
 p,e,_,_,ctx,b,s=env;ctl=CurrentTransactions(ctx);b.eval_limit=b.used;before=b.used;assert ctl.offer(p,e,b,s)is None and b.used==before and ctl.work is None

def test_bad_new_parent_never_filters_legacy_complete_candidate(env):
 p,e,n,ne,ctx,b,s=env;ctl=CurrentTransactions(ctx);before=b.used;out=ctl.choose(p,ne,n,ne,b,s);assert out==(ne,n,None)and b.used==before

def test_legacy_portfolio_and_recovery_untouched_no_epoch(env):
 p,e,_,_,ctx,b,s=env;ctx.alg.complete_joint_stage='interleaved';assert enabled(ctx);ctx.mode='recovery';assert not enabled(ctx)
 text=(ROOT/'source/proj_r6/src/tdr/alns.py').read_text();assert 'complete_epoch'not in text and 'destroy_ops.append("COMPLETE_JOINT")'not in text
 for name in ['moves.py','nominal.py','recovery.py','expected_cost.py','scenario_eval.py']:
  assert (ROOT/'source/proj_r6/src/tdr'/name).read_bytes()==(ROOT.parent/'K1_R10_S_warm_restore_20261120/source/proj_r6/src/tdr'/name).read_bytes()

def test_sub_rounding_geometry_change_is_different_exact_version(env):
 p,e,_,_,ctx,b,s=env;ctl,t=ticket(env);old=version(p);so=next(iter(p.sorties.values()));so.lam+=1e-8;assert version(p)!=old;assert t.cas(p,e,t.q,t.qe)is None

def test_return_to_old_exact_parent_retains_pending_seen_no_repeat(env):
 p,e,n,ne,ctx,b,s=env;ctl=CurrentTransactions(ctx);ctl.offer(p,e,b,s);first=ctl.work;seen=set(first.seen);ctl.current_work(n,ne);assert ctl.current_work(p,e)is first;ctl.offer(p,e,b,s);assert len(first.seen)==len(seen)+1 and len(ctl.bank)==2;assert ctl.transitions[-1]['reused_pending_parent']

def test_fixed_reference_H_is_actual_and_cache_identity_not_alias(env):
 from tdr.hybrid import score_horizon,scenario_key
 p,e,_,_,ctx,b,s=env;H=ctx.alg._nominal_reference_H;assert H==ctx.H==ctx.makespan_cap==e._actual_H==e._complete_reference_H;ctx.alg._independent_horizon=1.;assert score_horizon(e,ctx)==H;k=scenario_key(p,e,ctx,True);ctx.alg._nominal_reference_H=H+1;assert scenario_key(p,e,ctx,True)!=k;ctx.alg._nominal_reference_H=H
