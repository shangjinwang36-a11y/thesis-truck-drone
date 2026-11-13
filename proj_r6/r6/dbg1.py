import sys, json
sys.path.insert(0,'src')
from pathlib import Path
from tdr.data import load_instance
from tdr.experiment import load_case_nominal
from tdr.config import PhysicalConfig
pkg=json.load(open('data/package_light.json')); inst=load_instance(pkg,'R100')
plan,_,H=load_case_nominal(inst, Path('r6/nominal/nom2/X_seed20261113/R100'))
for d in ('d8','d7','d16'):
    for sid in plan.drone_sorties.get(d,[]):
        s=plan.sorties[sid]; lv=plan.visits[s.launch_vid] if s.launch_vid else None
        rv=plan.visits[s.rec_vid]
        print(d,sid,'L',lv.truck if lv else None, plan.routes[lv.truck].index(lv.vid) if lv else None,'R',rv.truck,plan.routes[rv.truck].index(rv.vid),len(s.air))
