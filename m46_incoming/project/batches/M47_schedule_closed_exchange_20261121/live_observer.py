"""Read-only receipts/checkpoints. Never a restart input or a watchdog."""
import os,time,json,pickle,hashlib,threading,math
from pathlib import Path
from tdr.evaluation_audit import EvaluationAudit
from tdr.complete_joint import version,Ticket,Work
import tdr.terminal_joint as terminal

def optional_cost(x):
 return None if x is None else(x if math.isfinite(x)else repr(x))

class LiveObserver:
 def __init__(self,path):
  self.path=Path(path);self.accepted=self.denied=self.completed_count=0;self.last_reason=None;self.original_record=EvaluationAudit.record;self.original_cas=Ticket.cas;self.original_close=terminal.close;self.original_work_init=Work.__init__;self.works=[];self.stop=threading.Event()
 def atomic_json(self,name,data):
  p=self.path/name;t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(data,allow_nan=False));t.replace(p)
 def emit(self,data):
  data.update(pid=os.getpid(),unix_s=time.time(),cpu_s=time.process_time());self.f.write(json.dumps(data,allow_nan=False)+'\n');self.f.flush()
 def snapshot(self):
  self.atomic_json('status.json',dict(pid=os.getpid(),accepted=self.accepted,denied=self.denied,completed=self.completed_count,last_reason=self.last_reason,cpu_s=time.process_time(),unix_s=time.time(),not_a_resume_checkpoint=True))
 def checkpoint(self,name,p,e,ctx):
  target=self.path/(name+'.pkl');tmp=target.with_suffix('.tmp')
  with tmp.open('wb')as f:pickle.dump((ctx.inst,ctx.phys,p,e,ctx.state,ctx.H),f)
  tmp.replace(target);self.emit(dict(event='paid_plan_checkpoint',kind=name,version=version(p),H=ctx.H,cost=None if e is None else optional_cost(e.cost),feasible=None if e is None else e.feasible));self.snapshot()
 def capture_construction(self):
  def freeze(x):
   if isinstance(x,dict):return {k:freeze(v)for k,v in list(x.items())}
   if isinstance(x,(tuple,list)):return [freeze(v)for v in list(x)]
   return x
  while not self.stop.wait(10.):
   self.atomic_json('construction.json',dict(pid=os.getpid(),cpu_s=time.process_time(),unix_s=time.time(),work=[dict(parent_version=w.parent_version,generated=w.generated,evaluated=w.evaluated,exhausted=w.exhausted,H=w.H,catalogue=freeze(w.diag))for w in list(self.works)],read_only=True))
 def __enter__(self):
  self.path.mkdir(parents=True,exist_ok=False);self.f=(self.path/'receipts.jsonl').open('x');self.emit(dict(event='observer_loaded',source=str(Path(__file__).resolve()),sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),schema='explicit_optional_cost_v1'));owner=self
  def recorded(audit,reason,budget,accepted):
   owner.original_record(audit,reason,budget,accepted)
   if accepted:owner.accepted+=1
   else:owner.denied+=1
   owner.last_reason=reason;owner.emit(dict(event='request',reason=reason,accepted=bool(accepted),budget_id=id(budget)if budget is not None else None,used=budget.used if budget is not None else None,limit=budget.eval_limit if budget is not None else None,scenario=bool(getattr(budget,'scenario_ledger',False))));owner.snapshot()
  def cas(ticket,p,e,q,qe):
   result=owner.original_cas(ticket,p,e,q,qe)
   if result is not None:owner.checkpoint('last_accepted_current',result[0],result[1],ticket.ctx)
   return result
  def close(p,e,ctx):
   result=owner.original_close(p,e,ctx);owner.checkpoint('normal_terminal_final',result[0],result[1],ctx);return result
  def init(work,*args,**kwargs):
   owner.original_work_init(work,*args,**kwargs);owner.works.append(work)
  EvaluationAudit.record=recorded;Ticket.cas=cas;terminal.close=close;Work.__init__=init;self.thread=threading.Thread(target=self.capture_construction,name='readonly_construction_monitor',daemon=True);self.thread.start();self.snapshot();return self
 def completed(self,reason,p,e,H):
  cost=None if e is None else optional_cost(e.cost)
  self.emit(dict(event='completed',reason=reason,version=version(p),H=H,feasible=None if e is None else e.feasible,cost=cost));self.completed_count+=1;self.snapshot()
 def catalogue(self,controllers):
  self.atomic_json('catalogues.json',dict(cpu_s=time.process_time(),unix_s=time.time(),work=[w for ctl in controllers for w in ctl.summaries()]))
 def __exit__(self,t,v,tb):
  self.stop.set();self.thread.join();Work.__init__=self.original_work_init;EvaluationAudit.record=self.original_record;Ticket.cas=self.original_cas;terminal.close=self.original_close;self.emit(dict(event='observer_closed',exception=None if t is None else t.__name__));self.snapshot();self.f.close()
