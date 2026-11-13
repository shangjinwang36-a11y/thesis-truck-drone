import pickle,json,os,sys
ROOT='/workspace/thesis/proj_r5d'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.evaluate import evaluate_plan
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
inst=load_instance(pkg,'RC100'); phys=phys.for_case(pkg.get('case_fleet'),'RC100')
d=pickle.load(open('/tmp/inv3.pkl','rb')); r=d['rec']
ev=evaluate_plan(r['plan'],inst,phys,r['state'],r['H'],'X'); print(ev.feasible,ev.violations)
pl=r['plan']; tl=ev.timeline
for d_ in ['d6','d7','d8','d12']:
    print(d_,[(sid,pl.sorties[sid].started,pl.sorties[sid].truck,pl.visits[pl.sorties[sid].rec_vid].truck,tl.rec_times.get(sid)) for sid in pl.drone_sorties.get(d_,[])], r['state'].drone_start.get(d_))
print(r['state'].t0, tl.truck_finish)
import copy
for i in range(3):
    e2=evaluate_plan(r['plan'].clone(),inst,phys,copy.deepcopy(r['state']),r['H'],'X'); print(i,e2.feasible,e2.violations[:2])
e3=evaluate_plan(r['plan'].clone(),inst,phys,copy.deepcopy(r['state']),r['H'],'X',allow_wait_repair=False); print('norepair',e3.feasible,e3.violations[:2])
