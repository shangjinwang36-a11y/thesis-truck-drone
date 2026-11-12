"""第六轮名义实验：light2 配置，S(同车)/X(允许名义跨车)，同预算同参数，多个算法种子.
用法: run_nominal.py --tag T --seeds 1,2,3 [--budget 1000] [--cases ...] [--workers 4] [--package data/package_light.json]"""
import argparse, json, os, sys, time
ROOT = '/workspace/thesis/proj_r6'
sys.path.insert(0, ROOT + '/src'); os.chdir(ROOT)
from pathlib import Path
from multiprocessing import Pool
ap = argparse.ArgumentParser()
ap.add_argument('--tag', required=True); ap.add_argument('--seeds', default='20261113')
ap.add_argument('--budget', type=int, default=1000)
ap.add_argument('--cases', default='C50,R50,RC50,C100,R100,RC100')
ap.add_argument('--package', default='data/package_light.json')
ap.add_argument('--workers', type=int, default=4); ap.add_argument('--strats', default='S,X')
ap.add_argument('--alg-json', default=None)
args = ap.parse_args()
OUT = Path(ROOT) / 'r6' / 'nominal' / args.tag


def task(t):
    case, strat, seed = t
    from tdr.config import PhysicalConfig, AlgorithmConfig
    from tdr.data import load_instance
    from tdr.experiment import build_case_nominal
    pkg = json.load(open(args.package))
    phys = PhysicalConfig.from_dict(pkg['config'])
    ad = dict(pkg['algorithm_protocol']['default_parameters'])
    if args.alg_json: ad.update(json.loads(args.alg_json))
    ad['base_algorithm_seed'] = seed
    alg = AlgorithmConfig.from_dict(ad)
    inst = load_instance(pkg, case); phys = phys.for_case(pkg.get('case_fleet'), case)
    d = OUT / f'{strat}_seed{seed}' / case
    t0 = time.time()
    try:
        m = build_case_nominal(inst, phys, alg, d, eval_budget=args.budget, cross_launch=(strat == 'X'))
    except Exception as e:
        m = dict(case_id=case, status='ERROR', error=repr(e)[:300])
    m.update(strat=strat, seed=seed, n_cust=len(inst.customers), wall=time.time() - t0)
    return m


if __name__ == '__main__':
    tasks = [(c, s, int(sd)) for sd in args.seeds.split(',') for c in args.cases.split(',') for s in args.strats.split(',')]
    tasks.sort(key=lambda t: -int(t[0][-3:] == '100'))
    OUT.mkdir(parents=True, exist_ok=True)
    res = []
    with Pool(args.workers) as p:
        for m in p.imap_unordered(task, tasks):
            res.append(m)
            print(m['case_id'], m['strat'], m['seed'], m.get('status'), round(m['cost'], 2) if m.get('cost') else None,
                  'cross', m.get('n_cross_sorties'), 'air', m.get('n_air_parcels'), f"{m['wall']:.0f}s", flush=True)
            slim = [{k: v for k, v in r.items() if k not in ('best_trace',)} for r in res]
            json.dump(slim, open(OUT / 'summary.json', 'w'), indent=1, default=str)
    print('DONE')
