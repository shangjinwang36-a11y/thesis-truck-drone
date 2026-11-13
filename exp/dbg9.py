from dbg import *
from tdr import recovery as R
orig=R.evaluate_plan if hasattr(R,'evaluate_plan') else None
import tdr.alns as A
# wrap eval_counted used in _first_feasible
of=R._first_feasible
def ff(cands,inst,phys,state,H,stats,budget):
    r=of(cands,inst,phys,state,H,stats,budget)
    if any('载荷' in x for x in r[3]):
        for c in cands:
            errs=c.validate_structure(inst,phys,initial_carrier=state.drone_carrier,holders=state.parcel_holder)
            for e in errs:
                if '载荷' in e:
                    sid=int(e.split()[1].rstrip(':')); s=c.sorties[sid]
                    print(e,'air',s.air,'hand',s.handover,'started',s.started,'drone',s.drone,'launch_truck',s.launch_truck,'truck',s.truck)
                    print('   masses',[(p,inst.parcel_mass[p]) for p in s.payload_ids])
        raise SystemExit
    return r
R._first_feasible=ff
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
