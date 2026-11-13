"""并行实验驱动：cases x seeds x S/X，全部回放核验。
用法: run_exp.py --out DIR --nominal DIR --budget N [--decision milp] [--cases C50,R50] [--seeds 10]
                 [--forced M] [--phys-json '{"slot_ac_kw":10,...}'] [--workers 7]
"""
import argparse, json, os, sys, time, csv, random, zlib
ROOT = os.environ.get('TDR_ROOT', '/workspace/thesis/proj')
sys.path.insert(0, ROOT + '/src')
os.chdir(ROOT)
from pathlib import Path
from multiprocessing import Pool

ap = argparse.ArgumentParser()
ap.add_argument('--out', required=True); ap.add_argument('--nominal', required=True)
ap.add_argument('--budget', type=int, default=1000)
ap.add_argument('--decision', default=None); ap.add_argument('--cases', default='C50,R50,RC50,C100,R100,RC100')
ap.add_argument('--seeds', type=int, default=10); ap.add_argument('--forced', type=int, default=0)
ap.add_argument('--phys-json', default=None); ap.add_argument('--workers', type=int, default=7)
args = ap.parse_args()


def setup():
    from tdr.config import PhysicalConfig, AlgorithmConfig
    pkg = json.load(open('data/package.json'))
    cfg = dict(pkg['config'])
    if args.phys_json:
        cfg.update(json.loads(args.phys_json))
    phys = PhysicalConfig.from_dict(cfg)
    alg = AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    alg.recovery_eval_budget_override = args.budget
    alg.recovery_time_limit_override_s = None
    if args.decision:
        alg.recovery_decision = args.decision
    return pkg, phys, alg


def task(t):
    case, seed = t
    from tdr.data import load_instance
    from tdr.experiment import load_case_nominal, run_episode_dir
    from tdr.hidden_world import TestWorld
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    from tdr import simulate
    pkg, phys, alg = setup()
    inst = load_instance(pkg, case)
    plan, ncost, H = load_case_nominal(inst, Path(args.nominal) / case)
    out = {}
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, 'NOMINAL')
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    for strat in ('S', 'X'):
        t0 = time.perf_counter()
        if args.forced:
            rng = random.Random(zlib.crc32(f'{case}:{seed}:{args.forced}'.encode()))
            failed = tuple(rng.sample(air, min(args.forced, len(air))))
            world = TestWorld(inst, case, failed)
            rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, 'recovery', 0)
            ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, strat, alg, rngs,
                                      recovery_eval_budget=args.budget)
            rec = [a for seg in ep.segments for a in seg['actions'] if a['kind'] == 'R']
            n_cross = sum(1 for a in rec if a.get('launch_truck') != a['actor'])
            out[strat] = dict(status=ep.status, cost=ep.evaluation.cost if ep.evaluation else None,
                              nfail=len(failed), n_R=len(rec), n_cross=n_cross,
                              verified=bool(ep.replay and ep.replay.ok), notes=ep.notes[:3],
                              wall=time.perf_counter() - t0)
        else:
            d = Path(args.out) / f'{case}_seed{seed:02d}_{strat}'
            r = run_episode_dir(inst, plan, ncost, H, phys, alg, seed, strat, d,
                                recovery_eval_budget=args.budget, make_figures=False)
            rows = list(csv.DictReader(open(d / 'recovery_ledger.csv'))) if (d / 'recovery_ledger.csv').exists() else []
            n_cross = sum(1 for x in rows if str(x['same_truck']).lower() != 'true')
            out[strat] = dict(status=r.get('episode_status'), cost=r.get('cost'),
                              nfail=r.get('observed_air_failure_count'), n_R=len(rows),
                              n_cross=n_cross, verified=r.get('episode_status') == 'COMPLETED_VERIFIED',
                              notes=[], wall=time.perf_counter() - t0)
    nom_air = sum(len(s.air) for s in plan.sorties.values())
    return dict(case=case, seed=seed, nominal_cost=nom_ev.cost, nominal_air=nom_air,
                n_cust=len(inst.customers), **{f'{k}_{s}': v for s in out for k, v in out[s].items()})


if __name__ == '__main__':
    Path(args.out).mkdir(parents=True, exist_ok=True)
    tasks = [(c, s) for c in args.cases.split(',') for s in range(1, args.seeds + 1)]
    # 长任务（100 客户）先发
    tasks.sort(key=lambda t: -int(t[0][-2:] == '00'))
    res = []
    t0 = time.time()
    with Pool(args.workers) as p:
        for r in p.imap_unordered(task, tasks):
            res.append(r)
            print(f"{r['case']} s{r['seed']:02d} S={r['cost_S']} X={r['cost_X']} st={r['status_S']}/{r['status_X']} "
                  f"nf={r['nfail_S']} t={time.time()-t0:.0f}s", flush=True)
            json.dump(res, open(Path(args.out) / 'results.json', 'w'), indent=1, default=str)
    print('DONE', time.time() - t0)
