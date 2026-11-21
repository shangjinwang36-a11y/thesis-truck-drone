#!/usr/bin/env python3
"""One fixed old-R10 rerun, never tuning. Persist each strategy's complete execution."""
from pathlib import Path
import argparse, dataclasses, hashlib, importlib.util, json, math, os, subprocess, sys, time, traceback
from multiprocessing import Pool
ROOT = Path(__file__).resolve().parents[1]
PROJ = ROOT / 'proj_r6'
sys.path.insert(0, str(PROJ/'src'))
sys.path.insert(0, str(PROJ/'r6'))
import run_round2 as legacy
from tdr.evaluation_audit import audit_evaluations
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.experiment import build_case_nominal, load_case_nominal, nominal_and_recovery, plan_to_dict
from tdr.evaluate import evaluate_plan, is_cross_sortie
from tdr.schedule import initial_state
from tdr.hidden_world import make_world, bernoulli_failure_flags
from tdr.simulate import derive_rngs, run_episode
from tdr.replay import verify_replay
CASES = ['C50','R50','RC50','C100','R100','RC100']
PACKAGE = PROJ/'data/package_light.json'

def serial(obj):
    if dataclasses.is_dataclass(obj):
        return {f.name:getattr(obj,f.name) for f in dataclasses.fields(obj)}
    if isinstance(obj, (set, frozenset)): return sorted(obj)
    if isinstance(obj, Path): return str(obj)
    if hasattr(obj,'__dict__'): return vars(obj)
    if hasattr(obj,'item'): return obj.item()
    raise TypeError(type(obj).__name__)

def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": repr(value)}
    if isinstance(value, (str,int,float,bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [clean(v) for v in value]
    return clean(serial(value))

def dump(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(clean(value),ensure_ascii=False,indent=1,allow_nan=False))
    tmp.replace(path)

def configs(case):
    package=json.loads(PACKAGE.read_text())
    phys,alg,ad,preset=legacy.configs(package,'R10')
    return package,load_instance(package,case),phys.for_case(package.get('case_fleet'),case),alg

def nominal(job):
    out,case=job;out=Path(out)
    pkg,inst,phys,alg=configs(case)
    base=out/'R10/nominal'
    record={'case':case,'physical':phys,'algorithm':alg,'algorithm_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    for strategy in ['S','X']:
        with audit_evaluations() as audit:
            t=time.perf_counter()
            meta=build_case_nominal(inst,phys,alg,base/strategy/case,eval_budget=1000,
                cross_launch=strategy=='X',two_phase_b=200,
                adopt_from=(base/'S'/case) if strategy=='X' else None)
        record[strategy]={'meta':meta,'evaluations':audit.summary(),'wall_s':time.perf_counter()-t}
        dump(out/'nominal_audit'/f'{case}_{strategy}.json',record[strategy])
    return record

def episode(job):
    out,case,seed=job;out=Path(out)
    assert seed in range(1001,1011)
    pkg,inst,phys,alg=configs(case)
    alg.recovery_eval_budget_override=1000
    nom_root=out/'R10/nominal'
    noms={s:load_case_nominal(inst,nom_root/s/case) for s in ['S','X']}
    H=noms['S'][2]
    prepared={s:nominal_and_recovery(s,noms['S'][0],noms['X'][0],bool(alg.x_adopt_s_if_cross)) for s in ['S','R','X']}
    row={'case':case,'seed':seed,'preset':'R10','p':.2,'failure_mode':'bernoulli','H_S':H,'H_X':noms['X'][2],
         'hidden_failure_parcels':sorted(bernoulli_failure_flags(case,seed,[c.parcel_id for c in inst.customers],.2))}
    for strategy,(plan,recovery_strategy) in prepared.items():
        path=out/'episodes'/case/str(seed)/f'{strategy}.json'
        start=time.perf_counter()
        ne=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
        row[strategy+'_nominal']={'cost':ne.cost,'H':H,'feasible':ne.feasible,
            'air':len({p for s in plan.sorties.values() for p in s.air}),
            'n_cross':sum(is_cross_sortie(plan,s) for s in plan.sorties.values())}
        if not ne.feasible:
            row[strategy]={'status':'NOMINAL_INFEASIBLE_UNDER_H','cost_fair':None,'violations':ne.violations}
            dump(path,{'summary':row[strategy]});continue
        world=make_world(inst,case,seed,'bernoulli',.2)
        try:
            with audit_evaluations() as audit:
                ep=run_episode(inst,plan,ne,H,phys,world,recovery_strategy,alg,
                    derive_rngs(alg.base_algorithm_seed,case,'recovery',0),
                    recovery_eval_budget=1000,recovery_wall_s=None,
                    cut_mode='snapshot',max_replans=len(inst.customers),ground_finish=True)
            online=ep.status=='COMPLETED_VERIFIED'
            emergency=ep.ground_finish_verified
            rep=ep.replay
            prefix_only=False
            if rep is None and ep.segments:
                rep=verify_replay(inst,phys,ep.segments,H,strategy=recovery_strategy)
                prefix_only=True
            violations=[v for v in (rep.violations if rep else []) if not(prefix_only and v.startswith('UNDELIVERED_FINAL:'))]
            fullcost=ep.evaluation.cost if online and ep.evaluation and rep and rep.ok else None
            fair=fullcost if online else ep.ground_finish_cost if emergency else None
            decision_times=[r.stats.get('decision_wall_s',r.stats.get('init_wall_s',0.)) for r in ep.replans[1:]]
            summary={'status':ep.status,'completion':'ONLINE_VERIFIED' if online else 'EMERGENCY_VERIFIED' if emergency else 'UNCOMPLETED',
                'cost':fullcost,'cost_fair':fair,'ground_finish_cost':ep.ground_finish_cost,
                'ground_finish_status':ep.ground_finish_status,'ground_finish_verified':emergency,
                'wall_s':time.perf_counter()-start,'notes':ep.notes,
                'n_observed_failures':sum(not o.air_delivery_available for o in ep.observations),
                'n_recovery_attempts':len(ep.replans)-1,'n_recovery_failed_init':sum(bool(r.stats.get('failed_initialization')) for r in ep.replans),
                'n_reported_search_evals':sum(r.stats.get('n_eval_requests',0) for r in ep.replans),
                'ground_finish_stats':ep.ground_finish_stats,'physical_violations':violations,
                'constraint_violation':bool(violations),'prefix_only_verification':prefix_only,
                'min_energy_kwh':min(getattr(rep,'min_energy',{}).values(),default=None),
                'wall_cap_armed':False,'max_decision_wall_s':max(decision_times,default=0.),
                'n_decisions_over_60s':sum(t>60 for t in decision_times),
                'evaluation_audit':audit.summary()}
            row[strategy]=summary
            dump(path,{'summary':summary,'episode':vars(ep),'independent_check':rep})
        except Exception:
            error=traceback.format_exc()
            row[strategy]={'status':'ERROR','completion':'UNCOMPLETED','cost_fair':None,'error':error,'wall_s':time.perf_counter()-start}
            dump(path,{'summary':row[strategy]})
    dump(out/'pairs'/f'{case}_{seed}.json',row)
    return row

def main():
    frozen=json.loads((ROOT/'round10_recheck/emin005/frozen_manifest.json').read_text())
    for relative, expected in frozen['frozen_source_sha256'].items():
        actual=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        if actual!=expected:
            raise RuntimeError(f'frozen source mismatch: {relative}')
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--phase',choices=['nominal','episodes','all'],default='all');a=parser.parse_args()
    out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
    if a.phase in ['nominal','all']:
        if (out/'nominal_build.json').exists():raise RuntimeError('refuse overwriting completed nominal run')
        print('NOMINAL',time.strftime('%Y-%m-%d %H:%M:%S %Z'),flush=True)
        with Pool(a.workers) as pool:
            records=list(pool.imap_unordered(nominal,[(str(out),c) for c in CASES]))
        records.sort(key=lambda r:CASES.index(r['case']));dump(out/'nominal_build.json',records)
        for r in records:print('NOMINAL_DONE',r['case'],r['S']['meta'].get('cost'),r['X']['meta'].get('cost'),flush=True)
        if any(not r[s]['meta'].get('verified') or not r[s]['meta'].get('verified_plan') for r in records for s in ['S','X']):
            raise RuntimeError('No feasible nominal; stop rather than invent another initialization')
    if a.phase in ['episodes','all']:
        if any((out/'episodes').glob('*/*/*.json')):raise RuntimeError('refuse duplicate formal episodes')
        print('EPISODES',time.strftime('%Y-%m-%d %H:%M:%S %Z'),flush=True)
        rows=[]
        with Pool(a.workers) as pool:
            for row in pool.imap_unordered(episode,[(str(out),c,s) for c in CASES for s in range(1001,1011)]):
                rows.append(row)
                with (out/'episodes.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False,default=serial)+'\n')
                print('PAIR_DONE',len(rows),row['case'],row['seed'],[(s,row[s]['status'],row[s].get('cost_fair')) for s in ['S','R','X']],flush=True)
        rows.sort(key=lambda r:(CASES.index(r['case']),r['seed']));dump(out/'episodes.json',rows)
        print('COMPLETE',time.strftime('%Y-%m-%d %H:%M:%S %Z'),len(rows),flush=True)
if __name__=='__main__':main()
