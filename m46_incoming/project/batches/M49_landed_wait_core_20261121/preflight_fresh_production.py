from research import *
import gzip,random
from tdr.complete_joint import version
from tdr.joint_air_promote import air
from tdr import complete_joint as cj
from process_state import record
record("fresh_dual_"+sys.argv[1])
case=sys.argv[1]if len(sys.argv)>1 else'RC100';base=ROOT/'preflight_fresh'/case
assert not base.exists(),'Do not overwrite scientific run'
for arm in'SX':
 inst,phys,alg=setup(case,'M14',arm=='X');H=alg._nominal_reference_H;hcounts=Counter();traces=[];slots=[];origin=cj.CurrentTransactions.choose
 def choose(self,p,e,lp,le,b,s):
  before={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')};used=b.used;v=version(p);res=origin(self,p,e,lp,le,b,s);after={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')};assert before==after;slots.append(dict(parent_version=v,parent_air=len(air(p)),used_before=used,used_after=b.used,RNG_unchanged=True,legacy_candidate_kept_eligible=True,selected=bool(res[2])));return res
 cj.CurrentTransactions.choose=choose;path=base/(arm+'_RAW.jsonl.gz');path.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(path,'wt')as f:
  def rec(p,q,e,row):f.write(json.dumps(rr.clean(dict(type='transaction',parent=plan_to_dict(p,inst),child=plan_to_dict(q,inst),trace=dict(row))))+'\n')
  alg._current_joint_recorder=rec
  def profile(fr,event,value):
   if event=='return'and fr.f_code.co_name=='evaluate_plan'and fr.f_code.co_filename.endswith('/tdr/evaluate.py')and fr.f_locals.get('accepted'):
    assert Path(fr.f_code.co_filename).resolve()==(ROOT/'source/proj_r6/src/tdr/evaluate.py').resolve();lo=fr.f_locals;assert lo['H']==H;hcounts[str(lo['H'])]+=1;f.write(json.dumps(rr.clean(dict(type='full',H=lo['H'],reason=lo['reason'],plan=plan_to_dict(lo['plan'],inst),visible_state=vars(lo['state']),evaluation=None if value is None else dict(feasible=value.feasible,cost=value.cost,violations=value.violations))))+'\n')
  with rr.audit_evaluations()as au,cap_physical(1000,reference_H=H)as en:
   sys.setprofile(profile)
   try:meta=rr.build_case_nominal(inst,phys,alg,base/arm,eval_budget=1000,cross_launch=arm=='X',two_phase_b=200,adopt_from=base/'S'if arm=='X'else None)
   finally:
    sys.setprofile(None);cj.CurrentTransactions.choose=origin;dump(base/(arm+'_LEDGER.json'),dict(ledger=au.summary(),envelope=en.summary(),actual_H_counts=hcounts,slots=slots,transactions=getattr(alg,'_current_joint_rows',[]),work=[w for ctl in getattr(alg,'_current_joint_controllers',[])for w in ctl.summaries()],terminal=getattr(alg,'_terminal_joint_records',[])))
 p=plan_from_dict(read(base/arm/'nominal_plan.json')['plan']);rows=getattr(alg,'_current_joint_rows',[]);survive=[]
 for r in rows:
  if r.get('cas'):
   assert r['parent_version']==r['evaluation_parent_version']==r['construction_current_version']==r['commit_observed_current_version']==r['commit_observed_evaluation_version'];assert r['child_version']==r['evaluation_child_version']==r['committed_child_version']==r['published_current_version'];assert r['H']==r['evaluation_H']==r['commit_actual_H']==H
   if set(r['parent_air_ids'])|set(r['new_air'])<=air(p):survive.append(r)
 out=dict(meta=meta,published_air=len(air(p)),actual_H_counts=hcounts,transactions=rows,committed=sum(r.get('cas',False)for r in rows),surviving_transactions=survive,slots=slots,fresh_S_prepared_here=True,no_old_K1_plan_input=True)
 dump(base/(arm+'_RESULT.json'),out);print('FRESH',case,arm,meta['cost'],len(air(p)),'transactions',len(rows),'commits',out['committed'],'surviving',[(r['parent_air'],r['child_air'],r['new_air'])for r in survive],flush=True)
x=read(base/'X_RESULT.json');s=read(base/'S_RESULT.json');K=ROOT.parent/'K1_R10_S_warm_restore_20261120/K1';ka=len(air(plan_from_dict(read(K/'nominal/X'/case/'nominal_plan.json')['plan'])));opportunities=[r for z in [s,x]for r in z['surviving_transactions']if r['parent_air']>=ka and r['child_air']>ka and r['J']<r['parent_J']and r['scenario']<=r['parent_scenario']]
dump(base/'FORMAL_GATE.json',dict(passed=bool(opportunities),witnesses=opportunities,baseline_air=ka,published_S_air=s['published_air'],published_X_air=x['published_air'],no180_before_true_fresh_current_CAS=True));print('FORMAL_GATE',bool(opportunities),flush=True)

record("fresh_dual_"+case,True,dict(gate=bool(opportunities)))
