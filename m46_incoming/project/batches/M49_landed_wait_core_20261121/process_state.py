from pathlib import Path
import os,json,datetime,fcntl
ROOT=Path(__file__).resolve().parent

def record(stage,finish=False,details=None):
 now=datetime.datetime.now().astimezone().isoformat();pid=os.getpid();fn=ROOT/'diagnostics'/f'PROCESS_{stage}.json'
 if finish:
  z=json.loads(fn.read_text());z.update(finished_Asia_Shanghai=now,running=False,details=details);fn.write_text(json.dumps(z,ensure_ascii=False,indent=2)+'\n')
 else:fn.write_text(json.dumps(dict(stage=stage,pid=pid,ppid=os.getppid(),running=True,started_Asia_Shanghai=now),ensure_ascii=False,indent=2)+'\n')
 with (ROOT/'state.lock').open('w')as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);z=json.loads((ROOT/'state.json').read_text());active=[x for x in z.get('active_processes',[])if x['pid']!=pid]
  if not finish:active.append(dict(pid=pid,stage=stage))
  z.update(status='EVIDENCE_STAGE_ACTIVE',phase=active[0]['stage'] if active else 'evidence_step_completed_research_continues',active_processes=active,pid=active[0]['pid']if active else None,research_terminated=False,updated_Asia_Shanghai=now)
  for f in [ROOT/'state.json',ROOT.parent.parent/'state.json']:f.write_text(json.dumps(z,ensure_ascii=False,indent=2)+'\n')
