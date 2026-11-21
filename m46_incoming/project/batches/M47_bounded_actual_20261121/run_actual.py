from pathlib import Path
import subprocess,sys,json,os,time,threading
from collections import deque
H=Path(__file__).resolve().parent;R=H.parent.parent
import sys as _sys
_sys.path.insert(0,str(H))
from private_root import private_root
private_root()
pending=deque(tuple(x)for x in json.loads((H/'FRESH_JOB_REGISTRATION.json').read_text())['jobs']);active=[];completed=[];failed=[];pause=threading.Event();started=time.time()
def dump(p,d):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2));t.replace(p)
def process(pid):
 try:
  s=Path(f'/proc/{pid}/stat').read_text();z=s[s.rindex(')')+2:].split();return dict(pid=pid,state=z[0],cpu_s=(int(z[11])+int(z[12]))/os.sysconf('SC_CLK_TCK'),resident_bytes=int(z[21])*os.sysconf('SC_PAGE_SIZE'))
 except FileNotFoundError:return dict(pid=pid,state='exited_during_snapshot')
def save():
 rows=[dict(job=j,process=process(p.pid))for p,j,l in active];state=json.loads((H/'state.json').read_text());state.update(phase='M41_bounded_actual_running'if active else('M41_actual_blocked'if failed else'M41_bounded_actual_complete_audit_pending'),pid=os.getpid()if active else None,optimizer_running=bool(active),actual_execution_running=bool(active),active_processes=([os.getpid()]+[p.pid for p,j,l in active])if active else[],actual_execution_started=True,actual_completed=len(completed),actual_failed=len(failed))
 for q in [H/'state.json',R/'state.json']:dump(q,state)
 dump(H/'FRESH_PROGRESS.json',dict(completed=completed,failures=failed,pending=list(pending),active=rows,wall_s=time.time()-started,no_stale_log_abort=True))
 with(H/'ACTUAL_PROCESS_SAMPLES.jsonl').open('a')as f:f.write(json.dumps(dict(unix_s=time.time(),active=rows))+'\n');f.flush()
while pending or active:
 while pending and len(active)<2 and not failed:
  job=pending.popleft();tag='_'.join(map(str,job));lp=H/'worker_logs'/f'{tag}.log';lp.parent.mkdir(exist_ok=True);log=lp.open('x');p=subprocess.Popen([sys.executable,str(H/'fresh_actual.py'),'worker',json.dumps(job)],stdout=log,stderr=subprocess.STDOUT);active.append((p,job,log));print('START',job,p.pid,flush=True)
 for p,job,log in list(active):
  code=p.poll()
  if code is not None:
   log.close();row=dict(job=job,pid=p.pid,exit_code=code);(failed if code else completed).append(row);active.remove((p,job,log));print('FINISH',len(completed),row,flush=True)
 save()
 if failed and not active:break
 if active:pause.wait(3.)
assert not failed,failed
