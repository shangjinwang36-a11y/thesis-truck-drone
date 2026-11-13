import sys, json, os, random, zlib
ROOT='/workspace/thesis/proj'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import TestWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
def build(conf, case, seed, forced, strat, budget=1000, cut_mode='snapshot'):
    pk,nd={'spec':('data/package.json','outputs/nominal_r3fd1000'),'light':('data/package_light.json','outputs/nominal_lightR1000')}[conf]
    pkg=json.load(open(pk)); phys=PhysicalConfig.from_dict(dict(pkg['config'])).for_case(pkg.get('case_fleet'),case)
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters']); alg.recovery_eval_budget_override=budget; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
    inst=load_instance(pkg,case); plan,nc,H=load_case_nominal(inst,Path(nd)/case)
    nom=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'N')
    air=sorted(p for s in plan.sorties.values() for p in s.air)
    rng=random.Random(zlib.crc32(f'{case}:{seed}:{forced}'.encode())); failed=tuple(rng.sample(air,min(forced,len(air))))
    world=TestWorld(inst,case,failed)
    ep=simulate.run_episode(inst,plan,nom,H,phys,world,strat,alg,simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0),recovery_eval_budget=budget,cut_mode=cut_mode)
    return ep,inst,phys
if __name__=='__main__':
    conf,case,seed,forced,strat=sys.argv[1:6]
    cm=sys.argv[6] if len(sys.argv)>6 else 'snapshot'
    ep,inst,phys=build(conf,case,int(seed),int(forced),strat,cut_mode=cm)
    print(ep.status, ep.evaluation.cost if ep.evaluation else None, ep.notes[:3])
    if ep.replay: print(ep.replay.violations[:5])
    for r in ep.replans: print(r.index, round(r.time_s,1), round(r.t_cut,1), r.status, r.cost)
