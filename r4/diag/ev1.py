import sys, json, random, zlib, time
sys.path.insert(0,'/workspace/thesis/proj/src'); import os; os.chdir('/workspace/thesis/proj')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal, episode_metrics
from tdr.hidden_world import TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
pkgp, nomp, case, seed, forced = sys.argv[1:6]; forced=int(forced); seed=int(seed)
pkg=json.load(open(pkgp)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
alg=AlgorithmConfig.from_dict(dict(pkg['algorithm_protocol']['default_parameters']))
if os.environ.get('ALGJ'): [setattr(alg,k,v) for k,v in json.loads(os.environ['ALGJ']).items()]
alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,nc,H=load_case_nominal(inst,Path(nomp)/case)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
air=sorted(p for s in plan.sorties.values() for p in s.air)
log=[]
orig=simulate.optimize
def wrap(p,ctx,b,**kw):
    r=orig(p,ctx,b,**kw); log.append((ctx.strategy,ctx.frag_sid,p,kw.get("init_ev"),r)); print("  USED",{k:v for k,v in r.stats.destroy_used.items() if "XT" in k or "CROSS" in k or "RELEASE" in k or "SWAP" in k or "REASSIGN" in k or "RETARGET" in k}); return r
simulate.optimize=wrap
def show(pl, trucks):
    for k in trucks:
        print('   ',k,[(pl.visits[v].customer, 'g'+','.join(pl.visits[v].ground) if pl.visits[v].ground else '') for v in pl.routes.get(k,[])])
for strat in ['S','X']:
    rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode()))
    world=TestWorld(inst,case,tuple(rng.sample(air,min(forced,len(air)))))
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    log.clear()
    ep=simulate.run_episode(inst,plan,nom_ev,H,phys,world,strat,alg,rngs,recovery_eval_budget=1000)
    print(strat,ep.status,ep.evaluation.cost if ep.evaluation else None, [ (round(r.cost,1), r.__dict__.get("source") or str(list(r.__dict__.values())[-1])[:60]) for r in ep.replans[1:]])
    for (st,fs,p0,iev,r) in log:
        f=r.plan.sorties[fs]; rv=r.plan.visits[f.rec_vid]
        print('  replan frag',fs,'drone',f.drone,'launch',f.launch_truck,'rec truck',rv.truck,'init',iev.cost,'final',r.evaluation.cost)
        if '-v' in sys.argv and rv.truck!=f.launch_truck:
            print(' INIT'); show(p0,[f.launch_truck,rv.truck]); print(' FINAL'); show(r.plan,[f.launch_truck,rv.truck])
