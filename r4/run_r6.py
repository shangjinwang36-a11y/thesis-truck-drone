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
ap.add_argument('--pool', default=None, choices=[None,'air','all'], help='失败候选池：air=仅名义空送客户；all=全部客户（配合 --forced 或 --mrange）')
ap.add_argument('--mrange', default=None, help='失败数从该范围随机，如 1,2（配合 --pool）')
ap.add_argument('--H-delta', type=float, default=0.0, help='H 的增量（如 -900 即 H 余量 1800→900）')
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
    import math
    from tdr.data import load_instance
    from tdr.experiment import load_case_nominal, episode_metrics
    from tdr.hidden_world import TestWorld, HiddenWorld
    from tdr.evaluate import evaluate_plan
    from tdr.schedule import initial_state
    from tdr import simulate
    from tdr.alns import Budget, SearchStats, SolveContext
    pkg, phys, alg = setup()
    inst = load_instance(pkg, case)
    phys = phys.for_case(pkg.get('case_fleet'), case)
    plan, ncost, H = load_case_nominal(inst, Path(args.nominal) / case)
    H = H + args.H_delta
    nom_ev = evaluate_plan(plan, inst, phys, initial_state(inst, phys), H, 'NOMINAL')
    air = sorted(p for s in plan.sorties.values() for p in s.air)
    allp = sorted(c.parcel_id for c in inst.customers)
    out = dict(case=case, seed=seed, nominal_cost=nom_ev.cost, n_cust=len(inst.customers), H=H)
    events = []
    side = {}
    orig_ir, orig_opt = simulate.initial_recovery, simulate.optimize

    def ir_hook(new_plan, state2, inst_, phys_, strategy, gr, **kw):
        side['args'] = (new_plan.clone(), state2, inst_, phys_, set(gr), dict(kw))
        return orig_ir(new_plan, state2, inst_, phys_, strategy, gr, **kw)

    def opt_hook(p, ctx, budget, **kw):
        res = orig_opt(p, ctx, budget, **kw)
        ev = dict(replan=ctx.replan_index, drone=None)
        try:
            f = res.plan.sorties[ctx.frag_sid] if res.plan is not None else None
            ev['costX'] = res.evaluation.cost if (res.evaluation is not None and res.evaluation.feasible) else None
            ev['initX'] = kw.get('init_ev').cost if kw.get('init_ev') is not None else None
            if f is not None:
                rv = res.plan.visits[f.rec_vid]
                lt = f.launch_truck or f.truck
                ev.update(drone=f.drone, launch_truck=lt, rec_truck=rv.truck, cross=(rv.truck != lt),
                          n_served=len(f.air), n_handover=len(f.handover))
                st = ctx.state
                fp = f.start_pos
                rc = inst.customer(rv.customer)
                def dist(a, b): return math.hypot(a[0]-b[0], a[1]-b[1]) if a and b else None
                ds = st.drone_start.get(f.drone)
                ev.update(t_fail=st.t0, H=ctx.H, remaining_s=(ctx.H - st.t0) if ctx.H else None,
                          d_launch_to_fail=dist(st.truck_start_pos.get(lt), fp),
                          d_rec_to_fail=dist(st.truck_start_pos.get(rv.truck), fp),
                          d_rec_point_from_fail=dist((rc.x, rc.y), fp),
                          drone_energy_frac=(ds.energy / phys.e_cap) if ds is not None else None,
                          n_trucks=len(st.truck_start_pos))
        except Exception as e:
            ev['feat_error'] = repr(e)[:200]
        # 同一状态、同一预算下 S 的恢复（仅用于逐事件对照，不影响真实 X 回合）
        try:
            np_, st2, inst_, phys_, gr, kwi = side['args']
            kwi = dict(kwi)
            kwi['stats'] = SearchStats(); kwi['budget'] = Budget(alg.recovery_init_eval_budget, None); kwi['info'] = {}
            optS, reasons, catS = orig_ir(np_.clone(), st2, inst_, phys_, 'S', gr, **kwi)
            ev['initS'] = optS.ev.cost if optS is not None else None
            if optS is not None:
                ctxS = SolveContext(inst=inst, phys=phys, alg=alg, state=st2, H=ctx.H, mode='recovery',
                                    affected_drones=set(ctx.affected_drones), affected_sorties=set(ctx.affected_sorties),
                                    ground_required=set(ctx.ground_required), replan_index=ctx.replan_index,
                                    rngs=simulate.derive_rngs(alg.base_algorithm_seed, case, 'recovery', ctx.replan_index),
                                    catalog=catS, frag_sid=ctx.frag_sid, strategy='S')
                bS = Budget(args.budget, None, start=time.perf_counter())
                kw2 = dict(kw); kw2['stats'] = SearchStats(); kw2['init_ev'] = optS.ev
                solS = orig_opt(optS.plan, ctxS, bS, **kw2)
                ev['costS'] = solS.evaluation.cost if (solS.evaluation is not None and solS.evaluation.feasible) else None
        except Exception as e:
            ev['side_error'] = repr(e)[:200]
        events.append(ev)
        return res
    simulate.initial_recovery, simulate.optimize = ir_hook, opt_hook
    t0 = time.perf_counter()
    if args.forced or args.pool:
        rng = random.Random(zlib.crc32(f'{case}:{seed}:{args.forced}:{args.pool}'.encode() if args.pool else f'{case}:{seed}:{args.forced}'.encode()))
        M = args.forced or rng.choice(tuple(int(x) for x in (args.mrange or '1,2').split(',')))
        cand = allp if args.pool == 'all' else air
        world = TestWorld(inst, case, tuple(rng.sample(cand, min(M, len(cand)))))
    else:
        world = HiddenWorld(inst, case, seed)
    rngs = simulate.derive_rngs(alg.base_algorithm_seed, case, 'recovery', 0)
    try:
        ep = simulate.run_episode(inst, plan, nom_ev, H, phys, world, 'X', alg, rngs,
                                  recovery_eval_budget=args.budget, cut_mode=args.cut_mode)
        out['X'] = dict(status=ep.status, cost=ep.evaluation.cost if (ep.status == 'COMPLETED_VERIFIED' and ep.evaluation) else None,
                        wall=time.perf_counter() - t0)
    except Exception as e:
        out['X'] = dict(status='ERROR', cost=None, error=repr(e)[:300])
    finally:
        simulate.initial_recovery, simulate.optimize = orig_ir, orig_opt
    out['events'] = events
    return out


if __name__ == '__main__':
    tasks = [(c, s) for c in args.cases.split(',') for s in range(args.seed0, args.seed0 + args.seeds)]
    tasks.sort(key=lambda t: -int(t[0][-2:] == '00' or t[0][-3:] == '200'))
    res = []; t0 = time.time()
    meta = dict(args=vars(args), start=time.strftime('%Y-%m-%d %H:%M:%S'))
    with Pool(args.workers) as p:
        for r in p.imap_unordered(task, tasks):
            res.append(r)
            print(r['case'], r['seed'], r['X']['status'], len(r['events']), f't={time.time()-t0:.0f}s', flush=True)
            json.dump(dict(meta=meta, runs=res), open(OUT / f'{args.name}.json', 'w'), indent=1, default=str)
    meta['end'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(dict(meta=meta, runs=res), open(OUT / f'{args.name}.json', 'w'), indent=1, default=str)
    print('DONE', time.time() - t0)
