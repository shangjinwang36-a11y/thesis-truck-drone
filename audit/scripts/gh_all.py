import sys, json, os, re, math
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
class Stop(Exception):pass
def probe(pk,nd,case,seed,replan_target):
    pkg=json.load(open(pk)); phys=PhysicalConfig.from_dict(dict(pkg['config']))
    alg=AlgorithmConfig.from_dict(pkg['algorithm_protocol']['default_parameters'])
    alg.recovery_eval_budget_override=1000; alg.recovery_time_limit_override_s=None; alg.recovery_decision='milp'
    inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
    plan,ncost,H=load_case_nominal(inst,Path(OUT)/nd/case)
    nom_ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
    world=HiddenWorld(inst,case,seed)
    cap={}; cnt=[0]
    orig=simulate.initial_recovery; otr=simulate.truncate
    def tr(plan_,tl,inst_,phys_,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=None):
        cap.update(plan=plan_.clone(),tl=tl,t_cut=t_cut,t_fail=t_fail,fs=failed_sid,drone=failed_drone)
        return otr(plan_,tl,inst_,phys_,t_cut,t_fail,failed_sid,failed_parcel,failed_drone,prev_state=prev_state)
    def hook(new_plan,state2,*a,**kw):
        cnt[0]+=1
        if cnt[0]>=replan_target: cap.update(np=new_plan.clone(),st=state2,fs2=kw['frag_sid']); raise Stop()
        return orig(new_plan,state2,*a,**kw)
    simulate.truncate=tr; simulate.initial_recovery=hook
    rngs=simulate.derive_rngs(alg.base_algorithm_seed,case,'recovery',0)
    try: simulate.run_episode(inst,plan,nom_ev,H,phys,world,'S',alg,rngs,recovery_eval_budget=1000)
    except Stop: pass
    finally: simulate.truncate=otr; simulate.initial_recovery=orig
    if 'np' not in cap: return None
    fs=cap['fs']; np_=cap['np']; st=cap['st']; d=cap['drone']
    fr=np_.sorties.get(fs)
    first=cap['t_fail']
    for x in cap['tl'].actions:
        if simulate._ghost_action(x,d,cap['t_fail']): continue
        if x.kind in ('G','P','R','U','W') and x.start<cap['t_fail']<x.end: first=max(first,x.end)
    res=dict(delay=cap['t_cut']-cap['t_fail'],first_level_delay=first-cap['t_fail'],frag_present=fr is not None)
    old=cap['plan'].sorties[fs]; rt=cap['tl'].rec_times.get(fs)
    res['orig_rec_end_before_cut']=bool(rt and rt[1]<=cap['t_cut'])
    if fr is not None:
        mass=sum(inst.parcel_mass[p] for p in fr.air+fr.handover); ph=phys.hover_power(mass)
        e_cut=st.drone_energy[d]; e_fail=e_cut+ph*(cap['t_cut']-cap['t_fail'])/3600
        res.update(hover_margin_at_fail_s=(e_fail-phys.e_min)/ph*3600, hover_margin_at_cut_s=(e_cut-phys.e_min)/ph*3600)
    return res
if __name__=='__main__':
    rs=json.load(open(f'{OUT}/{sys.argv[1]}_main/results.json'))
    pk,nd={'gh200_L1':('data/package_gh200_light1.json','nominal_gh200_L1_1000'),'gh200_L2':('data/package_gh200_light2.json','nominal_gh200_L2_1000')}[sys.argv[1]]
    for x in rs:
        if x['status_S']=='COMPLETED_VERIFIED': continue
        m=re.search(r'replan=(\d+)',x['stop_reason_S'] or '')
        why=re.findall(r'INITIAL_RECOVERY_FAILED:([A-Z_]+)',x['stop_reason_S'] or '')
        r=probe(pk,nd,x['case'],x['seed'],int(m.group(1)) if m else 1)
        print(sys.argv[1],x['case'],x['seed'],why,{k:(round(v,1) if isinstance(v,float) else v) for k,v in (r or {}).items()},flush=True)
