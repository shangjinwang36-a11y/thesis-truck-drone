import sys, json, collections
sys.path.insert(0,'src')
from tdr import evaluate
from tdr.schedule import stage_energy
orig = evaluate.evaluate_plan
samples=[]; kinds=collections.Counter()
def spy(plan, inst, phys, state=None, H=None, reason='', **kw):
    ev = orig(plan, inst, phys, state, H, reason, **kw)
    if ev.status=='ENERGY_INFEASIBLE' and ev.timeline is not None and 'SWAP_CANNOT_FIX' in ev.violations[0]:
        msg=ev.violations[0]; d=msg.split(':')[1].split('@')[0]; t=float(msg.split('@')[1].split(':')[0])
        stages=ev.timeline.drone_stages[d]
        # find stage at t, summarise the sortie stage energies
        sid=None
        for st in stages:
            if abs(st.start-t)<1e-6: kinds[st.kind]+=1
            if st.start<=t+1e-6 and st.sid is not None: sid=st.sid
        tot=collections.defaultdict(float)
        for st in stages:
            if st.sid==sid: tot[st.kind]+=stage_energy(st,phys)
        samples.append((reason,msg,dict(tot),len(plan.sorties[sid].air) if sid in plan.sorties else None, 0))
    return ev
evaluate.evaluate_plan = spy
import tdr.alns as A; A.evaluate_plan = spy
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import build_case_nominal
pkg=json.load(open('data/package_light.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
CASE=sys.argv[1]; inst=load_instance(pkg,CASE); phys=phys.for_case(pkg.get('case_fleet'),CASE)
build_case_nominal(inst,phys,alg,'r6/smoke/diag3',eval_budget=1000,cross_launch=(sys.argv[2]=='X'))
print('e_cap-emin', phys.e_cap-phys.e_min, 'kinds', kinds)
for s in samples[:8]: print(s)
import statistics
nw=[ (s[2].get('WAIT',0)) for s in samples]; print('n',len(samples),'mean wait energy',statistics.mean(nw) if nw else 0, 'frac with WAIT>0.02', sum(x>0.02 for x in nw)/max(1,len(nw)))
