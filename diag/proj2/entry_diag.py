import sys,json,collections
sys.path.insert(0,'src')
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr import simulate, recovery
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
case,seed=sys.argv[1],int(sys.argv[2]); nomdir=sys.argv[3] if len(sys.argv)>3 else 'outputs_summary/nominal2'
pkg=json.load(open('data/package.json'))
phys=PhysicalConfig.from_dict(pkg['config']); alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
inst=load_instance(pkg,case); plan,cost,H=load_case_nominal(inst,Path(nomdir)/case)
world=HiddenWorld(inst,case,seed); rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
class Stop(Exception): pass
def wrapped(new_plan,state2,inst_,phys_,strat,gr,**kw):
    fs=kw['frag_sid']; frag=new_plan.sorties[fs]
    res=recovery.prepare_residual(new_plan.clone(),inst_)
    cat=recovery.RecoveryCatalog(res,frag,inst_,'X',state2,gr)
    print('launch',cat.launch_truck,'frag air',frag.air,'t_fail',round(state2.t0),'rec_vid(nominal)',frag.rec_vid,'on truck',res.visits[frag.rec_vid].truck if frag.rec_vid in res.visits else None)
    stats=collections.defaultdict(lambda: dict(n=0,built=0,feas=0,best=1e18,reasons=collections.Counter()))
    # residual
    c0=recovery.build_residual_candidate(res,frag.sid,None,inst_,phys_,state2,gr,'X')
    for c in c0:
        e=evaluate_plan(c,inst_,phys_,state2,H,'x'); print('RESIDUAL feasible',e.feasible,e.cost,e.violations[:2])
    for ent in cat._gen:
        T=ent['truck']; st=stats[T]; st['n']+=1
        cands=recovery.build_residual_candidate(res,frag.sid,ent,inst_,phys_,state2,gr,'X')
        if not cands: st['reasons']['NO_CAND']+=1; continue
        st['built']+=1
        ok=False
        for c in cands:
            e=evaluate_plan(c,inst_,phys_,state2,H,'x')
            if e.feasible: ok=True; st['best']=min(st['best'],e.cost); break
            st['reasons'][(e.violations[0] if e.violations else e.status)[:40]]+=1
        st['feas']+=ok
    shown=0
    for ent in recovery.RecoveryCatalog(res,frag,inst_,'X',state2,gr)._gen:
        if ent['truck']=='launch' or ent['truck']==cat.launch_truck: continue
        cands=recovery.build_residual_candidate(res,frag.sid,ent,inst_,phys_,state2,gr,'X')
        for c in cands[:1]:
            e=evaluate_plan(c,inst_,phys_,state2,H,'x')
            if not e.feasible and shown<6:
                shown+=1; print('SAMPLE',ent['truck'],ent['kind'],ent['ref'],ent['served'],'->',e.violations[:3])
    for T,st in sorted(stats.items()): print(T,'entries',st['n'],'built',st['built'],'feasible',st['feas'],'best',round(st['best'],2),dict(st['reasons'].most_common(4)))
    raise Stop()
simulate.initial_recovery=wrapped
try: simulate.run_episode(inst,plan,nom_ev,H,phys,world,'X',alg,rngs,recovery_eval_budget=10)
except Stop: pass
