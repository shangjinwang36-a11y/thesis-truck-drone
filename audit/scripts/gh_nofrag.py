import sys, json, os
ROOT='/workspace/thesis/audit/proj'
sys.path.insert(0, ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import evaluate_plan
from tdr.schedule import initial_state
from tdr import simulate
OUT='/workspace/thesis/proj/outputs'
pk,nd='data/package_gh200_light1.json','nominal_gh200_L1_1000'
case=sys.argv[1]; seed=int(sys.argv[2])
pkg=json.load(open(pk)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
world=HiddenWorld(inst,case,seed)
class Stop(Exception):pass
orig=simulate.initial_recovery; cap={}
def hook(new_plan,state2,inst_,phys_,strategy,gr,**kw):
    cap.update(np=new_plan.clone(),st=state2,kw=kw,gr=gr); raise Stop()
simulate.initial_recovery=hook
# also capture pre-truncate plan/timeline
otr=simulate.truncate
def tr(plan_,tl,*a,**k):
    cap['plan']=plan_.clone(); cap['tl']=tl; cap['trargs']=(a,k); return otr(plan_,tl,*a,**k)
simulate.truncate=tr
rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
try: simulate.run_episode(inst,plan,nom_ev,H,phys,world,'S',alg,rngs,recovery_eval_budget=1000)
except Stop: pass
np_=cap['np']; fs=cap['kw']['frag_sid']
print('frag_sid',fs,'in new_plan.sorties',fs in np_.sorties,'t0',cap['st'].t0)
a,k=cap['trargs']; print('args t_cut,t_fail,failed_sid,parcel,drone',a[2:8])
pl=cap['plan']; s=pl.sorties.get(fs); print('orig sortie',s)
d=s.drone if s else None
print('drone_sorties old',pl.drone_sorties.get(d),'new',np_.drone_sorties.get(d))
tl=cap['tl']
print('rec_times',tl.rec_times.get(fs),'launch',tl.launch_times.get(fs))
print('new sorties of drone',[np_.sorties.get(x) for x in np_.drone_sorties.get(d,[])])
