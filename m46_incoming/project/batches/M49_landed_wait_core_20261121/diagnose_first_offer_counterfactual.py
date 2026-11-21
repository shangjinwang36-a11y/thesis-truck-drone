"""Paid diagnostic intervention, not a deployable production policy or witness.
First paid joint offer is assessed normally; keep/discard only changes its return.
After that observation both arms return legacy unchanged. No old plan input.
"""
from research import *
import gzip,hashlib
from process_state import record
from tdr import complete_joint as cj
from tdr.joint_air_promote import air
mode=sys.argv[1]
assert mode in ('keep','discard')
case='RC100';stage='first_offer_counterfactual_'+mode
base=ROOT/'diagnostics/first_offer_counterfactual'/mode
assert not base.exists(),'Never overwrite recorded experiment'
base.mkdir(parents=True)
record(stage)
inst,phys,alg=setup(case,'M14',False);H=alg._nominal_reference_H
origin=cj.CurrentTransactions.choose;slots=[];fired=False;meta=None;failure=None
sources=[ROOT/'research.py',ROOT/'diagnose_first_offer_counterfactual.py',*sorted((ROOT/'source/proj_r6/src/tdr').glob('*.py'))]
dump(base/'SOURCE_FREEZE.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources})
with gzip.open(base/'CURRENT.jsonl.gz','wt')as raw:
 def intervene(self,p,e,lp,le,b,s):
  global fired
  before=b.used;v=cj.version(p);rng={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')}
  had=len(self.rows)
  if not fired:
   out=origin(self,p,e,lp,le,b,s)
   if len(self.rows)>had:
    fired=True
    dump(base/'INTERVENTION.json',dict(mode=mode,used_before=before,used_after=b.used,parent=plan_to_dict(p,inst),legacy=None if lp is None else plan_to_dict(lp,inst),offer=dict(self.rows[-1]),original_selected=out[2]is not None,only_return_intervened=True))
    if mode=='discard':out=(le,lp,None)
  else:out=(le,lp,None)
  assert rng=={k:r.getstate()for k,r in self.ctx.rngs.items()if hasattr(r,'getstate')}
  row=dict(parent_version=v,parent_air=len(air(p)),used_before=before,used_after=b.used,selected=out[2]is not None,fired=fired)
  slots.append(row);raw.write(json.dumps(rr.clean(dict(row=row,current=plan_to_dict(p,inst))))+'\n');return out
 cj.CurrentTransactions.choose=intervene
 try:
  with rr.audit_evaluations()as au,cap_physical(1000,reference_H=H)as en:
   try:meta=rr.build_case_nominal(inst,phys,alg,base/'S',eval_budget=1000,cross_launch=False,two_phase_b=200,adopt_from=None)
   finally:dump(base/'LEDGER.json',dict(ledger=au.summary(),envelope=en.summary(),slots=slots,transactions=getattr(alg,'_current_joint_rows',[]),diagnostic_only=True))
 except BaseException as ex:
  failure=repr(ex);raise
 finally:
  cj.CurrentTransactions.choose=origin
  record(stage,True,dict(fired=fired,failure=failure))
p=plan_from_dict(read(base/'S/nominal_plan.json')['plan'])
old=read(ROOT.parent/'K1_R10_S_warm_restore_20261120/K1/nominal/S'/case/'nominal_plan.json')['plan']
ref=plan_from_dict(old)
ledger=read(base/'LEDGER.json')['ledger']
assert fired and len(getattr(alg,'_current_joint_rows',[]))==1
assert sum(x['used']for x in ledger['budgets']if not x['scenario_ledger'])<=1000
assert sum(x['used']for x in ledger['budgets']if x['scenario_ledger'])<=200
assert not ledger['unbudgeted_by_reason']
summary=dict(mode=mode,diagnostic_only=True,not_production_witness=True,meta=meta,published_air=len(air(p)),final_version=cj.version(p),exact_strong_control_plan=cj.version(p)==cj.version(ref),transactions=getattr(alg,'_current_joint_rows',[]),physical=sum(x['used']for x in ledger['budgets']if not x['scenario_ledger']),scenario=sum(x['used']for x in ledger['budgets']if x['scenario_ledger']),actual_execution_metrics='not run; nominal diagnostic only')
dump(base/'RESULT.json',summary)
print('COUNTERFACTUAL',mode,'air',len(air(p)),'cost',meta['cost'],'exact_strong',summary['exact_strong_control_plan'],'physical',summary['physical'],'scenario',summary['scenario'],flush=True)
