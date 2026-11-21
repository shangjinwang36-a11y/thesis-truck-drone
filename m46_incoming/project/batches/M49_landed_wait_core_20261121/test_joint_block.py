from research import *
import pytest,random,gzip
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX
from tdr.complete_joint import CurrentTransactions,version,complete
from tdr.joint_air_promote import air
from tdr.joint_block import geometries,single_projection
@pytest.fixture
def env():
 inst,phys,alg=setup('C50','M14',True);alg.joint_dual_recovery=False;phys.set_active();st=rr.initial_state(inst,phys);st.nominal_cross=True;H=alg._nominal_reference_H;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',rngs={'operator':random.Random(17)});ctx.scenario_on=True;b=Budget(32,None);s=SearchStats();ctx.live_budget=b;ctx.live_stats=s
 p=plan_from_dict(read(ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/diagnostics/visible_block_search/C50/WITNESS_1.json')['parent'])
 with cap_physical(32,reference_H=H):
  tok=_ACTIVE_CTX.set(ctx)
  try:
   e=eval_counted(p,inst,phys,st,H,'JOINT_BLOCK_TEST_PARENT',s,b);assert e.feasible;yield p,e,ctx,b,s
  finally:_ACTIVE_CTX.reset(tok)
def test_two_sortie_contiguous_block_full_customer_air_and_real_cover(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);t=ctl.offer(p,e,b,s);assert t
 assert len(t.row['new_air'])==2 and t.row['all_parent_air_preserved'] and complete(t.q,c.inst)
 d=t.row['descriptor'];u,v=d['old_visits'];r=p.routes[p.visits[u].truck];assert r.index(v)==r.index(u)+1
 assert len(d['sorties'])==2 and set(d['sorties'])<=set(d['affected_sorties'])
 assert not t.q.validate_structure(c.inst,c.phys);assert all(t.row['gates'].values());assert t.qe._actual_H==c.H
 assert set(t.q.drone_sorties)=={f'd{i+1}'for i in range(c.phys.drone_count)}
def test_joint_ticket_one_paid_evaluation_and_final_atomic_CAS(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);before=b.used;t=ctl.offer(p,e,b,s);assert t and b.used==before+1;before=b.used;out=t.cas(p,e,t.q,t.qe);assert out and b.used==before and version(out[0])==t.child and out[1]is t.qe;assert t.cas(p,e,t.q,t.qe)is None
def test_joint_stale_parent_and_child_air_mutation_reject_without_evaluate(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);t=ctl.offer(p,e,b,s);q=t.q.clone();qe=eval_counted(q,c.inst,c.phys,c.state,c.H,'JOINT_BLOCK_TEST_NEW_CURRENT',s,b);before=b.used;assert t.cas(q,qe,t.q,t.qe)is None and b.used==before
 t.q.sorties[t.row['descriptor']['sorties'][0]].air.reverse();assert t.cas(p,e,t.q,t.qe)is None
def test_joint_constructor_no_extra_RNG_and_finite_original_bounds(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);before=c.rngs['operator'].getstate();ctl.offer(p,e,b,s);assert c.rngs['operator'].getstate()==before;row=ctl.rows[-1];d=row['descriptor']['body_catalogue'];assert d['node_cap']==512 and d['cover_limit']==4
 assert not ctl.offer(p,e,Budget(0,None),s)
def test_samecar_generator_shared_not_X_only():
 inst,phys,alg=setup('C50','M13',False);phys.set_active();st=rr.initial_state(inst,phys);st.nominal_cross=False;H=alg._nominal_reference_H;b=Budget(32,None);stats=SearchStats();seen=set();items=[]
 with cap_physical(32,reference_H=H):
  for line in gzip.open(ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/diagnostics/strong_core_control/C50/S_CURRENT.jsonl.gz','rt'):
   p=plan_from_dict(json.loads(line)['current']);v=version(p)
   if v in seen:continue
   seen.add(v);e=eval_counted(p,inst,phys,st,H,'SHARED_BLOCK_TEST_PARENT',stats,b);assert e.feasible
   dg={};q_d=next(geometries(p,inst,phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},False,dg),None)
   if q_d is None:continue
   q,d=q_d;assert not d['real_cross'] and complete(q,inst)and air(p)<air(q);qe=eval_counted(q,inst,phys,st,H,'SHARED_BLOCK_TEST_CHILD',stats,b)
   if qe.feasible:items.append((q,d));break
 assert items,'Public S has a real physical legal same-car construction, not just an X-only branch'

def test_viable_mature_candidate_never_pays_extra_joint_offer(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);before=b.used;old=c.rngs['operator'].getstate();assert ctl.choose(p,e,p,e,b,s)==(e,p,None);assert b.used==before and ctl.work is None and c.rngs['operator'].getstate()==old

def test_dead_trial_handoff_uses_complete_current_not_partial_trial(env):
 p,e,c,b,s=env;ctl=CurrentTransactions(c);old=b.used;qe,q,t=ctl.choose(p,e,None,None,b,s);assert t and b.used==old+1 and len(air(q))==len(air(p))+2 and t.parent==version(p);assert t.cas(p,e,q,qe)
