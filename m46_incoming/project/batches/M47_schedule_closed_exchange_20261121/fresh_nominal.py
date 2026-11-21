from pathlib import Path
import sys,os
HERE=Path(__file__).resolve().parent
CORE=HERE.parent/'M47_schedule_closed_exchange_core_20261121'
sys.path.insert(0,str(CORE))
from research import *
ROOT=HERE
import gzip,random,pickle
from tdr.complete_joint import version
from tdr.joint_air_promote import air
from tdr import complete_joint as cj
from live_observer import LiveObserver


case=sys.argv[1];variant=sys.argv[2];assert case in ['C50','R50','RC50','C100','R100','RC100']and variant in ['new'];base=ROOT/('fresh_'+variant)/case
freeze=read(CORE/'EXPERIMENT_CORE_FREEZE.json');assert all(hashlib.sha256((CORE/n).read_bytes()).hexdigest()==h for n,h in freeze.items())
assert not base.exists(),'Do not overwrite scientific run'
for arm in'SX':
 arm_wall=time.perf_counter();arm_cpu=time.process_time();inst,phys,alg=setup(case,'M47',arm=='X');H=alg._nominal_reference_H;hcounts=Counter();model_counts=Counter();traces=[];slots=[];origin=cj.CurrentTransactions.choose
 def choose(self,p,e,lp,le,b,s):
  before={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')};used=b.used;v=version(p);res=origin(self,p,e,lp,le,b,s);after={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')};assert before==after;slots.append(dict(parent_version=v,parent_air=len(air(p)),used_before=used,used_after=b.used,RNG_unchanged=True,legacy_candidate_kept_eligible=True,selected=bool(res[2])));return res
 cj.CurrentTransactions.choose=choose;obs=LiveObserver(base/(arm+'_live'));obs.__enter__();path=base/(arm+'_RAW.jsonl.gz');path.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(path,'wt')as f:
  def rec(p,q,e,row):f.write(json.dumps(rr.clean(dict(type='transaction',parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),trace=dict(row))))+'\n')
  alg._current_joint_recorder=rec
  def profile(fr,event,value):
   if event=='call'and((fr.f_code.co_filename.endswith('/tdr/expected_cost.py')and fr.f_code.co_name in ['expected_j','recourse_terms','_failure_cost','_overlap','_consecutive'])or(fr.f_code.co_filename.endswith('/tdr/moves.py')and fr.f_code.co_name=='ground_candidates')):model_counts[fr.f_code.co_name]+=1
   if event=='return'and fr.f_code.co_name=='evaluate_plan'and fr.f_code.co_filename.endswith('/tdr/evaluate.py')and fr.f_locals.get('accepted'):
    assert Path(fr.f_code.co_filename).resolve()==(CORE/'source/proj_r6/src/tdr/evaluate.py').resolve();lo=fr.f_locals;assert lo['H']==H;obs.completed(lo['reason'],lo['plan'],value,lo['H']);hcounts[str(lo['H'])]+=1;f.write(json.dumps(rr.clean(dict(type='full',H=lo['H'],reason=lo['reason'],plan=plan_to_dict(lo['plan'],inst),visible_state=vars(lo['state']),evaluation=None if value is None else dict(feasible=value.feasible,cost=value.cost,violations=value.violations))))+'\n')
  with rr.audit_evaluations()as au,cap_physical(1000,reference_H=H)as en:
   sys.setprofile(profile)
   try:meta=rr.build_case_nominal(inst,phys,alg,base/arm,eval_budget=1000,cross_launch=arm=='X',two_phase_b=200,adopt_from=base/'S'if arm=='X'else None)
   finally:
    sys.setprofile(None);cj.CurrentTransactions.choose=origin;obs.__exit__(*sys.exc_info());dump(base/(arm+'_LEDGER.json'),dict(ledger=au.summary(),envelope=en.summary(),actual_H_counts=hcounts,pure_original_model_function_calls=model_counts,slots=slots,transactions=getattr(alg,'_current_joint_rows',[]),work=[w for ctl in getattr(alg,'_current_joint_controllers',[])for w in ctl.summaries()],terminal=getattr(alg,'_terminal_joint_records',[])))
 with gzip.open(base/(arm+'_PAID_TRAINING_EVIDENCE.pkl.gz'),'wb')as ef:pickle.dump(dict(receipts=getattr(alg,'_paid_training_receipts',{}),mature_air_sets=getattr(alg,'_mature_fullpool_air_sets',set())),ef)
 p=plan_from_dict(read(base/arm/'nominal_plan.json')['plan']);rows=getattr(alg,'_current_joint_rows',[]);survive=[]
 for r in rows:
  if r.get('cas'):
   assert r['parent_version']==r['evaluation_parent_version']==r['construction_current_version']==r['commit_observed_current_version']==r['commit_observed_evaluation_version'];assert r['child_version']==r['evaluation_child_version']==r['committed_child_version']==r['published_current_version'];assert r['H']==r['evaluation_H']==r['commit_actual_H']==H
   if set(r['parent_air_ids'])|set(r['new_air'])<=air(p):survive.append(r)
 out=dict(wall_s=time.perf_counter()-arm_wall,CPU_s=time.process_time()-arm_cpu,meta=meta,published_air=len(air(p)),actual_H_counts=hcounts,pure_original_model_function_calls=model_counts,transactions=rows,committed=sum(r.get('cas',False)for r in rows),surviving_transactions=survive,slots=slots,fresh_S_prepared_here=True,no_old_K1_plan_input=True,variant=variant,core=str(CORE),pid=os.getpid(),actual_loaded_evaluate=str(CORE/'source/proj_r6/src/tdr/evaluate.py'),core_hash=hashlib.sha256((CORE/'EXPERIMENT_CORE_FREEZE.json').read_bytes()).hexdigest())
 dump(base/(arm+'_RESULT.json'),out);print('FRESH',case,arm,meta['cost'],len(air(p)),'transactions',len(rows),'commits',out['committed'],'surviving',[(r['parent_air'],r['child_air'],r['new_air'])for r in survive],flush=True)
x=read(base/'X_RESULT.json');s=read(base/'S_RESULT.json');K=ROOT.parent/'K1_R10_S_warm_restore_20261120/K1';ka=len(air(plan_from_dict(read(K/'nominal/X'/case/'nominal_plan.json')['plan'])));opportunities=[r for z in [s,x]for r in z['surviving_transactions']if (variant=='control'or r['descriptor'].get('construction') in ['NONCONTIGUOUS_RETAINED_GROUND_POOL_ENERGY','PAID_Q_NONCONTIGUOUS_GROUND_BODY_POOL','PAID_TRAINING_ROBUST_JOINT_BODY_GROUND'])and r['parent_air']>=ka and r['child_air']>ka and r['J']<r['parent_J']and r['scenario']<=r['parent_scenario']]
detour=[r for r in x['transactions'] if r.get('descriptor',{}).get('construction')=='SCHEDULE_CLOSED_DETOUR_CROSS'];dump(base/'FORMAL_GATE.json',dict(passed=bool(opportunities),witnesses=opportunities,legacy_gate_unchanged=True,detour_transactions=detour,baseline_air=ka,published_S_air=s['published_air'],published_X_air=x['published_air'],no180_before_true_fresh_current_CAS=True,H_source='sealed_K1_S_H_s',not_X_own_H=True));print('FORMAL_GATE',bool(opportunities),flush=True)


