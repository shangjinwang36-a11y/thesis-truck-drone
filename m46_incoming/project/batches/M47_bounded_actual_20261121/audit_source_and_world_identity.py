from pathlib import Path
import json,hashlib
H=Path(__file__).resolve().parent;C=H.parent/'M47_schedule_closed_exchange_core_20261121';sys_path_ready=str(H)
import sys as _sys
if sys_path_ready not in _sys.path:_sys.path.insert(0,sys_path_ready)
from private_root import k1_execution
reg=json.loads((H/'FRESH_JOB_REGISTRATION.json').read_text());core=json.loads((C/'EXPERIMENT_CORE_FREEZE.json').read_text());freeze=json.loads((H/'ACTUAL_EXECUTION_FREEZE.json').read_text());assert all(hashlib.sha256((C/n).read_bytes()).hexdigest()==v for n,v in core.items());assert all(hashlib.sha256((H/n).read_bytes()).hexdigest()==v for n,v in freeze.items());lookup={tuple(x['logical_job']):x for x in reg['exact_scope_details']};out=[]
for job in reg['jobs']:
 v,c,a,_,s,_=job;d=json.loads((H/v/'executions/own/dev'/f'{c}_{s}_{a}.json').read_text());r=d['row'];assert r['loaded_driver_hash']==freeze['fresh_actual.py'];assert r['loaded_source_hash']==core['source/proj_r6/src/tdr/simulate.py'];assert r['actual_loaded_moves']==str(C.resolve()/'source/proj_r6/src/tdr/moves.py');assert r['core_root']==str(C.resolve());assert r['world_source_sha256']==lookup[tuple(job)]['world_source_sha256'];world=Path(r['world_source']);assert hashlib.sha256(world.read_bytes()).hexdigest()==r['world_source_sha256'];base=k1_execution(c,s,a);old=json.loads(base.read_text());assert d['flags']==old['flags']and r['H']==old['row']['H'];out.append(dict(job=job,world_H_reference_exact=True,loaded_core_driver_exact=True))
(H/'SOURCE_WORLD_AND_FREEZE_AUDIT.json').write_text(json.dumps(dict(rows=out,core_items=len(core),execution_freeze_items=len(freeze),native_evaluations=0,all_original_worlds_same_as_K1=True,no_model_or_source_changes=True),indent=2));print('SOURCE_WORLD_FREEZE_PASS',len(out))
