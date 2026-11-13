import sys,os,pickle,json
ROOT='/workspace/thesis/proj_r5d'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from pathlib import Path
from tdr.config import PhysicalConfig, AlgorithmConfig
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.evaluate import evaluate_plan
from tdr import recovery, simulate
d=pickle.load(open(sys.argv[1],'rb'))
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
inst=load_instance(pkg,'C100'); phys=phys.for_case(pkg.get('case_fleet'),'C100')
plan,ncost,H=load_case_nominal(inst,Path('/workspace/thesis/proj/outputs/nominal_lightR1000')/'C100')
st=d['state']; np_=d['plan']; print('t0',st.t0,'H',H)
for s in np_.sorties.values():
    if s.started: print('started',s.sid,s.drone,'lt',s.launch_truck,'rec',s.rec_vid,'air',s.air)
from tdr.moves import drone_carriers
print(drone_carriers(np_,st), 'slots',phys.truck_drone_slots)
res=recovery.prepare_residual(np_,inst); fs=d['kw'].get('frag_sid')
cat=recovery.RecoveryCatalog(res,res.sorties[fs],inst,d['strategy'],st,d['gr'],phys=phys,guard_n=40,slot_aware=True)
import collections
c=collections.Counter()
for ent in cat.next_entries(30):
    for cd in recovery.build_residual_candidate(res,fs,ent,inst,phys,st,d['gr'],d['strategy'])[:2]:
        ev=evaluate_plan(cd,inst,phys,st,H,'DBG'); c[(ent['truck'],tuple(v.split('@')[0] for v in ev.violations[:2]))]+=1
for k,v in c.items(): print(v,k)
print('--- d7 retarget scan')
d7=[s.sid for s in res.sorties.values() if s.started and s.drone=='d7'][0]
base=recovery.build_residual_candidate(res,fs,None,inst,phys,st,d['gr'],d['strategy'])
print('nbase',len(base))
c2=collections.Counter()
for b in base[:2]:
    cat7=recovery.RecoveryCatalog(b,b.sorties[d7],inst,d['strategy'],st,d['gr'],phys=phys,guard_n=40,slot_aware=True)
    ents=cat7.next_entries(40); print('entries d7',len(ents),collections.Counter(e['truck'] for e in ents))
    for ent in ents:
        for cd in recovery.build_residual_candidate(b,d7,ent,inst,phys,st,d['gr'],d['strategy'])[:2]:
            ev=evaluate_plan(cd,inst,phys,st,H,'DBG'); c2[(ent['truck'],ev.feasible,tuple(v[:40] for v in ev.violations[:2]))]+=1
for k,v in sorted(c2.items(),key=lambda x:-x[1])[:15]: print(v,k)
print('--- all entries by truck / energy-ub status')
cat7=recovery.RecoveryCatalog(base[0],base[0].sorties[d7],inst,d['strategy'],st,d['gr'],phys=phys,guard_n=400,slot_aware=True)
ents=cat7.next_entries(400); print(len(ents),collections.Counter(e['truck'] for e in ents))
print([ (e['truck'],e['kind'],round(e.get('est',0))) for e in ents[:3]])
c3=collections.Counter()
for ent in [e for e in ents if e['truck']!='t4'][:30]:
    for cd in recovery.build_residual_candidate(base[0],d7,ent,inst,phys,st,d['gr'],d['strategy'])[:2]:
        ev=evaluate_plan(cd,inst,phys,st,H,'DBG'); c3[(ent['truck'],ev.feasible,tuple(v[:30] for v in ev.violations[:2]))]+=1
for k,v in sorted(c3.items(),key=lambda x:-x[1])[:10]: print(v,k)
