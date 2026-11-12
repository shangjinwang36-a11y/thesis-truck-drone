import json,sys,statistics as st
sys.path.insert(0,'src')
from pathlib import Path
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.hidden_world import HiddenWorld
from tdr.evaluate import is_cross_sortie
pkg=json.load(open('data/package_light.json'))
# args: results.json nominalXdir nominalSdir
res=json.load(open(sys.argv[1])); nx=Path(sys.argv[2]); ns=Path(sys.argv[3])
cache={}; out={'cross':[], 'same':[]}; outS=[]
for r in res['runs']:
    c=r['case']
    if c not in cache:
        inst=load_instance(pkg,c); cache[c]=(inst,load_case_nominal(inst,nx/c)[0])
    inst,plan=cache[c]
    m=r.get('X'); n=r.get('X_nominal'); s=r.get('S'); sn=r.get('S_nominal')
    if not m or m.get('cost') is None or m.get('n_fail_events')!=1: continue
    F=set(HiddenWorld(inst,c,r['seed']).finish_episode().hidden_failure_parcels)
    sorts=[so for so in plan.sorties.values() if set(so.air)&F]
    if len(sorts)!=1: continue
    kind='cross' if is_cross_sortie(plan,sorts[0]) else 'same'
    out[kind].append((m['cost']-n['cost'], (s['cost']-sn['cost']) if s and s.get('cost') is not None and s.get('n_fail_events')==1 else None))
for k,l in out.items():
    xs=[a for a,_ in l]; ss=[b for _,b in l if b is not None]
    print(k,'n',len(xs),'X inc %.2f'%(st.mean(xs) if xs else float('nan')),'| S inc (same env, n=%d) %.2f'%(len(ss),st.mean(ss) if ss else float('nan')))
