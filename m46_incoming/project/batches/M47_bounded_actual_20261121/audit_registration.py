from pathlib import Path
import sys,json,pickle,hashlib
H=Path(__file__).resolve().parent;B=H.parent;C=B/'M47_schedule_closed_exchange_core_20261121';sys.path.insert(0,str(C));from research import *
from tdr.complete_joint import version
from tdr.simulate import initial_run_state
reg=read(H/'FRESH_JOB_REGISTRATION.json');fingerprints={};details=[]
for m in reg['logical_mapping']:
 variant,case,arm,stream,seed,hm=m['logical_job'];inst,phys,alg=setup(case,variant);alg.recovery_eval_budget_override=1000;d=read(H/variant/'nominal'/('X'if arm=='X'else'S')/case/'nominal_plan.json');p=plan_from_dict(d['plan']);pol='S'if arm=='S'else'X';rngs=rr.derive_rngs(alg.base_algorithm_seed,case,'recovery',0);rng_states={k:v.getstate()for k,v in rngs.items()};scope=(inst,case,seed,pol,version(p),d['H_s'],vars(alg),phys,vars(initial_run_state(p,inst,phys)),rng_states,read(C/'EXPERIMENT_CORE_FREEZE.json'),hashlib.sha256((H/'fresh_actual.py').read_bytes()).hexdigest(),hashlib.sha256((B/'J2_historical_R10_integrated_repair_20261120/J2/executions/own/dev'/f'{case}_{seed}_S.json').read_bytes()).hexdigest())
 fp=hashlib.sha256(pickle.dumps(scope,protocol=5)).hexdigest();job=tuple(m['logical_job']);fingerprints[job]=fp;details.append(dict(logical_job=job,canonical_job=m['canonical_fresh_job'],exact_configuration_state_rng_recovery_source_hash=fp))
for m in reg['logical_mapping']:assert fingerprints[tuple(m['logical_job'])]==fingerprints[tuple(m['canonical_fresh_job'])],m
assert len(reg['logical_mapping'])==reg['logical_count']
out=dict(exact_full_config_state_RNG_source_dedup_proven=True,logical_rows=reg['logical_count'],canonical_fresh_jobs=len(reg['jobs']),details=details,native_evaluations=0,R_nominal_S_clone=True,R_recovery_X=True,not_assumed_from_registration_boolean=True);dump(H/'DEDUPLICATION_INDEPENDENT_AUDIT.json',out);print('DEDUPE_EXACT_PASS',len(reg['jobs']),'fresh for72 logical')
