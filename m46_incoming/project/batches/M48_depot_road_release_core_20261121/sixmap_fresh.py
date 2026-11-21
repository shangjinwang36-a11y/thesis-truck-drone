"""One frozen six-map nominal batch; no in-batch tuning or executions."""
from pathlib import Path
import subprocess,sys,concurrent.futures,threading,json,os,datetime,hashlib
ROOT=Path(__file__).resolve().parent;CASES=['C50','R50','RC50','C100','R100','RC100'];lock=threading.Lock();rows={};freeze=json.loads((ROOT/'SOURCE_FREEZE.json').read_text())
def checked():assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in freeze.items())
def save():
 (ROOT/'SIXMAP_PROCESS.json').write_text(json.dumps(dict(controller_pid=os.getpid(),updated_Asia_Shanghai=datetime.datetime.now().astimezone().isoformat(),cases=rows),indent=2)+'\n')
def run(case):
 checked()
 with (ROOT/f'fresh_{case}.log').open('w')as log:
  p=subprocess.Popen([sys.executable,'-u',str(ROOT/'preflight_fresh_production.py'),case],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  with lock:rows[case]=dict(pid=p.pid,running=True);save()
  code=p.wait()
  with lock:rows[case].update(running=False,exit_code=code);save()
 checked();print('SIXMAP_CASE',case,'exit',code,flush=True);return code
checked()
with concurrent.futures.ThreadPoolExecutor(max_workers=3)as pool:
 codes=list(pool.map(run,CASES))
checked();print('SIXMAP_COMPLETE',codes,flush=True)
raise SystemExit(0 if all(x==0 for x in codes)else 1)
