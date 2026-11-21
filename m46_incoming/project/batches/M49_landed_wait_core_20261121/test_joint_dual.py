from research import *
import pytest,random,gzip,inspect
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX
from tdr.complete_joint import CurrentTransactions,version,complete
from tdr.joint_air_promote import air
from tdr.joint_dual import geometries,terminal_inventory
@pytest.fixture
def env():
 inst,phys,alg=setup('RC100','M14',True);phys.set_active();st=rr.initial_state(inst,phys);st.nominal_cross=True;H=alg._nominal_reference_H;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',rngs={'operator':random.Random(17)});ctx.scenario_on=True;b=Budget(32,None);ss=SearchStats();ctx.live_budget=b;ctx.live_stats=ss;w=read(ROOT.parent/'M14_dual_recovery_air_repartition_20261121/diagnostics/remaining_visible_RC100/WITNESS_1.json');p=plan_from_dict(w['parent'])
 with cap_physical(32,reference_H=H):
  tok=_ACTIVE_CTX.set(ctx)
  try:
   e=eval_counted(p,inst,phys,st,H,'DUAL_TEST_PARENT',ss,b);assert e.feasible;yield p,e,ctx,b,ss,w
  finally:_ACTIVE_CTX.reset(tok)
def test_real_complete_dual_repartition_and_all_fleet_paths(env):
 p,e,c,b,s,w=env;before=version(p);ctl=CurrentTransactions(c);t=ctl.offer(p,e,b,s);assert t and version(p)==before;assert version(t.q)==w['row']['child_version'];d=t.row['descriptor'];assert len(set(d['new_rendezvous']))==2 and d['original_air_repartitioned'];assert complete(t.q,c.inst)and air(p)<air(t.q)and len(air(t.q))==59
 assert len(t.q.drone_sorties)==c.phys.drone_count==16 and not t.q.validate_structure(c.inst,c.phys);stock,_=terminal_inventory(t.q,c.phys);assert sum(stock.values())==16 and max(stock.values())<=3;assert all(t.row['gates'].values())and t.qe._actual_H==c.H
 assert ctl.work.diag['heap_cap']==512 and d['body_catalogue']['whole_cover_limit']==4
def test_one_paid_dual_candidate_and_same_H_atomic_CAS(env):
 p,e,c,b,s,w=env;ctl=CurrentTransactions(c);used=b.used;t=ctl.offer(p,e,b,s);assert t and b.used==used+1;used=b.used;out=t.cas(p,e,t.q,t.qe);assert out and b.used==used;assert version(out[0])==t.child and out[1]is t.qe;assert t.cas(p,e,t.q,t.qe)is None
def test_new_dual_identity_never_overwrites_new_current_or_changes_RNG(env):
 p,e,c,b,s,w=env;ctl=CurrentTransactions(c);state=c.rngs['operator'].getstate();t=ctl.offer(p,e,b,s);assert state==c.rngs['operator'].getstate();q=t.q.clone();qe=eval_counted(q,c.inst,c.phys,c.state,c.H,'DUAL_TEST_NEW_CURRENT',s,b);used=b.used;assert t.cas(q,qe,t.q,t.qe)is None and b.used==used
 c.H+=1;assert t.cas(p,e,t.q,t.qe)is None
def test_viable_core_candidate_not_displaced_by_dual_fee(env):
 p,e,c,b,s,w=env;ctl=CurrentTransactions(c);used=b.used;assert ctl.choose(p,e,p,e,b,s)==(e,p,None)and b.used==used and ctl.work is None

def test_dual_samecar_capability_is_shared_not_X_only():
 inst,phys,alg=setup('RC100','M14',False);phys.set_active();st=rr.initial_state(inst,phys);st.nominal_cross=False;H=alg._nominal_reference_H;b=Budget(32,None);ss=SearchStats();seen=set();found=False
 with cap_physical(32,reference_H=H):
  for line in gzip.open(ROOT.parent/'M13_multi_sortie_structure_evidence_20261121/diagnostics/strong_core_control/RC100/S_CURRENT.jsonl.gz','rt'):
   p=plan_from_dict(json.loads(line)['current']);v=version(p)
   if v in seen:continue
   seen.add(v);e=eval_counted(p,inst,phys,st,H,'DUAL_SHARED_TEST_PARENT',ss,b);assert e.feasible
   dg={}
   for q,d in geometries(p,inst,phys,{sid:t[0]for sid,t in e.timeline.launch_times.items()},False,dg,timeline=e.timeline,p_fail=.2):
    assert not d['real_cross'] and complete(q,inst)
    qe=eval_counted(q,inst,phys,st,H,'DUAL_SHARED_TEST_CHILD',ss,b)
    if qe is None:break
    if qe.feasible:found=True;break
   if found or b.evals_left()<=0:break
 assert found,'S receives physically legal same-car dual/repartition capability'

def test_no_customer_literals_hidden_world_or_extra_evaluator_in_constructor():
 import tdr.joint_dual as md
 text=inspect.getsource(md)
 for bad in ["'p001'","'p079'",'read(','evaluate_plan','hidden_world','random.']:
  assert bad not in text
