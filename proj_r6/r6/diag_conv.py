import sys, json
sys.path.insert(0,'src')
from tdr import alns, schedule, evaluate
orig = schedule.schedule_plan
stats = {'n':0,'nonconv':0,'conv_100':0,'iters':[]}
seen=[]
def spy(plan, inst, phys, state=None, max_iter=14, waits=None):
    tl = orig(plan, inst, phys, state, max_iter, waits)
    if not tl.converged and evaluate.is_cross_sortie.__call__ and any(evaluate.is_cross_sortie(plan,s) for s in plan.sorties.values()):
        stats['nonconv']+=1
        tl2 = orig(plan, inst, phys, state, 200, waits)
        tl3 = orig(plan, inst, phys, state, 40, waits)
        stats.setdefault('growth',[]).append((round(max(tl.truck_finish.values())), round(max(tl3.truck_finish.values())), round(max(tl2.truck_finish.values()))))
        if tl2.converged:
            stats['conv_100']+=1; stats['iters'].append(tl2.iterations)
        else:
            stats['iters'].append(-1)
    stats['n']+=1
    return tl
evaluate.schedule_plan = spy
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import build_case_nominal
pkg=json.load(open('data/package_light.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
case=sys.argv[1]; inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
m=build_case_nominal(inst,phys,alg,'r6/smoke/diag_'+case,eval_budget=int(sys.argv[2]),cross_launch=True)
print(m['cost'], m['n_cross_sorties']); print(stats)
