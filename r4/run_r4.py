"""第四轮统一实验驱动：cases x seeds x {S,X}，全部回放核验；结果写 results/NAME.json（每次运行一行，不剔除任何运行）.
用法: run_r4.py --name N --package data/package_light.json --nominal outputs/nominal_lightR1000 [--forced M]
        [--cases C50,R50,RC50,C100,R100,RC100] [--seeds 10] [--budget 1000] [--alg-json '{...}'] [--phys-json '{...}']
        [--cut-mode snapshot] [--workers 7]
"""
import argparse, json, os, sys, time, random, zlib, re
ROOT = os.environ.get('TDR_ROOT', '/workspace/thesis/proj')
sys.path.insert(0, ROOT + '/src'); os.chdir(ROOT)
from pathlib import Path
from multiprocessing import Pool

ap = argparse.ArgumentParser()
ap.add_argument('--name', required=True); ap.add_argument('--package', required=True); ap.add_argument('--nominal', required=True)
ap.add_argument('--cases', default='C50,R50,RC50,C100,R100,RC100'); ap.add_argument('--seeds', type=int, default=10)
ap.add_argument('--seed0', type=int, default=1)
ap.add_argument('--forced', type=int, default=0); ap.add_argument('--budget', type=int, default=1000)
ap.add_argument('--alg-json', default=None); ap.add_argument('--phys-json', default=None)
ap.add_argument('--cut-mode', default='snapshot'); ap.add_argument('--workers', type=int, default=7)
ap.add_argument('--strats', default='S,X')
args = ap.parse_args()
OUT = Path('/workspace/thesis/r4/results'); OUT.mkdir(parents=True, exist_ok=True)


def setup():
    from tdr.config import PhysicalConfig, AlgorithmConfig
    pkg = json.load(open(args.package))
    cfg = dict(pkg['config'])
    if args.phys_json: cfg.update(json.loads(args.phys_json))
    phys = PhysicalConfig.from_dict(cfg)
    ad = dict(pkg['algorithm_protocol']['default_parameters'])
    if args.alg_json: ad.update(json.loads(args.alg_json))
    alg = AlgorithmConfig.from_dict(ad)
    alg.recovery_eval_budget_override = args.budget
    alg.recovery_time_limit_override_s = None
    alg.recovery_decision = 'milp'
    return pkg, phys, alg


def task(t):
    case, seed = t
    from tdr.data import load_instance
    from tdr.experiment import load_case_nominal, episode_metrics
    from tdr.hidden_world import TestWorld, HiddenWorld
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    from tdr import simulate
    pkg, phys, alg = setup()
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get('case_fleet'), case)
    plan, ncost, H = load_case_nominal(inst, Path(args.nominal) / case)
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, 'NOMINAL')
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    out = dict(case=case, seed=seed, nominal_cost=nom_ev.cost, nominal_air=len(air), n_cust=len(inst.customers))
    for strat in args.strats.split(','):
        t0 = time.perf_counter()
        if args.forced:
            rng = random.Random(zlib.crc32(f'{case}:{seed}:{args.forced}'.encode()))
            world = TestWorld(inst, case, tuple(rng.sample(air, min(args.forced, len(air)))))
        else:
            world = HiddenWorld(inst, case, seed)
        rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, 'recovery', 0)
        try:
            ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, strat[0], alg, rngs,
                                      recovery_eval_budget=args.budget, cut_mode=args.cut_mode,
                                      xmode=strat if len(strat) > 1 else None) \
                if 'xmode' in simulate.run_episode.__code__.co_varnames else \
                simulate.run_episode(inst, plan, nom_ev, H, phys, world, strat[0], alg, rngs,
                                     recovery_eval_budget=args.budget, cut_mode=args.cut_mode)
        except Exception as e:  # 记录而不隐藏
            out[strat] = dict(status='ERROR', cost=None, error=repr(e)[:300], wall=time.perf_counter() - t0)
            continue
        ok = ep.status == 'COMPLETED_VERIFIED'
        n_air = sum(1 for seg in ep.segments for st in seg['stages'] if st['kind'] == 'SERVICE' and st.get('parcel')) if ok else None
        stop_ctx = next((n for n in ep.notes if n.startswith('STOP_CONTEXT')), '')
        m = re.search(r'replan=(\d+)', stop_ctx)
        n_ev = sum(r.stats.get('n_eval_requests', 0) for r in ep.replans[1:])
        out[strat] = dict(status=ep.status, cost=ep.evaluation.cost if (ok and ep.evaluation) else None,
                          verified=ok, notes=ep.notes[:3], wall=time.perf_counter() - t0,
                          n_replans=len(ep.replans) - 1, stop_replan=int(m.group(1)) if m else None,
                          n_air_final=n_air, n_evals=n_ev,
                          replay_viol=(ep.replay.violations[:3] if ep.replay is not None and not ep.replay.ok else None),
                          **episode_metrics(ep))
    return out


if __name__ == '__main__':
    tasks = [(c, s) for c in args.cases.split(',') for s in range(args.seed0, args.seed0 + args.seeds)]
    tasks.sort(key=lambda t: -int(t[0][-2:] == '00' or t[0][-3:] == '200'))
    res = []; t0 = time.time()
    meta = dict(args=vars(args), start=time.strftime('%Y-%m-%d %H:%M:%S'))
    with Pool(args.workers) as p:
        for r in p.imap_unordered(task, tasks):
            res.append(r)
            ss = {k: (v['status'][:9] if isinstance(v, dict) else '') for k, v in r.items() if isinstance(v, dict)}
            print(r['case'], r['seed'], {k: (round(v['cost'], 2) if v.get('cost') else None) for k, v in r.items() if isinstance(v, dict)}, ss, f't={time.time()-t0:.0f}s', flush=True)
            json.dump(dict(meta=meta, runs=res), open(OUT / f'{args.name}.json', 'w'), indent=1, default=str)
    meta['end'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(dict(meta=meta, runs=res), open(OUT / f'{args.name}.json', 'w'), indent=1, default=str)
    print('DONE', time.time() - t0)
