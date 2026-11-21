"""Read-only initialization recorder. No hidden-world fields or future flags.
The simulator sees a world proxy that records only observations returned at
actual arrivals; constructors are passed their original visible arguments only.
"""
import gzip,json,pickle,hashlib
from pathlib import Path
from dataclasses import asdict
from contextlib import contextmanager
from unittest.mock import patch
from collections import Counter
from research import rr,plan_to_dict,dump
from tdr import simulate as sim,recovery as rec

class ObservationOnlyWorld:
 def __init__(self,world,known):self.__world=world;self.__known=known
 def observe_air_arrival(self,*a,**kw):
  ob=self.__world.observe_air_arrival(*a,**kw)
  if not ob.air_delivery_available:self.__known.add(ob.parcel_id)
  return ob
 def finish_episode(self):return self.__world.finish_episode()

@contextmanager
def observe_initializations(folder,world,inst,phys,alg):
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);known=set();rows=[];original_init=sim.initial_recovery;original_eval=rec.eval_counted;active=[None]
 def evaluate(cand,inst,phys,state,H,reason,stats,budget,*args,**kwargs):
  ctx=active[0]
  before=plan_to_dict(cand,inst) if ctx else None
  ev=original_eval(cand,inst,phys,state,H,reason,stats,budget,*args,**kwargs)
  if ctx is not None:
   row=dict(index=ctx['count']+1,reason=reason,plan=before,returned_plan=plan_to_dict(cand,inst),budget_used=budget.used,budget_limit=budget.eval_limit,budget_remaining=budget.evals_left(),evaluation=None if ev is None else dict(feasible=ev.feasible,status=ev.status,cost=ev.cost,z=ev.z,violations=list(ev.violations)))
   ctx['f'].write(json.dumps(rr.clean(row),ensure_ascii=False)+'\n');ctx['count']+=ev is not None
   if ev:ctx['taxonomy'].update(ev.violations)
  return ev
 def initial(plan,state,inst,phys,strategy,ground_required,*args,**kw):
  index=len(rows)+1;dest=folder/f'{index:03d}';dest.mkdir();budget=kw['budget'];true=sorted(known);effective=set(ground_required);assert set(true)<=effective
  opts={k:v for k,v in kw.items()if k not in ('stats','budget','catalog','info')}
  inp=dict(index=index,plan=plan_to_dict(plan,inst),state=asdict(state),strategy=strategy,H=kw.get('H'),true_greq=true,artificial_greq=sorted(effective-set(true)),effective_greq=sorted(effective),initial_budget=dict(used=budget.used,limit=budget.eval_limit,remaining=budget.evals_left(),wall_s=budget.wall_s if hasattr(budget,'wall_s')else None),options=opts,future_world_input=False)
  dump(dest/'INPUT.json',inp)
  # Only visible inputs and frozen configs; no world/proxy/audit object serialized.
  with open(dest/'VISIBLE_CONTEXT.pkl','wb')as f:pickle.dump((inst,phys,alg,plan,state,set(ground_required),opts),f)
  ctx=dict(count=0,taxonomy=Counter());active[0]=ctx
  try:
   with gzip.open(dest/'CANDIDATES.jsonl.gz','wt',encoding='utf8')as f:
    ctx['f']=f;out=original_init(plan,state,inst,phys,strategy,ground_required,*args,**kw)
  finally:active[0]=None
  info=kw.get('info',{});summary=dict(index=index,failed=out[0]is None,used=budget.used,limit=budget.eval_limit,remaining=budget.evals_left(),captured=ctx['count'],all_failure_reasons=dict(ctx['taxonomy']),info={k:v for k,v in info.items()if not k.startswith('_')},true_greq=true,artificial_greq=inp['artificial_greq'])
  assert ctx['count']==budget.used,(ctx['count'],budget.used)
  dump(dest/'RESULT.json',summary);rows.append(summary);dump(folder/'INDEX.json',rows)
  return out
 with patch.object(rec,'eval_counted',side_effect=evaluate),patch.object(sim,'initial_recovery',side_effect=initial):
  yield ObservationOnlyWorld(world,known)
