from dbg import *
from tdr import simulate as sim
orig=sim.initial_recovery
def ir(new_plan,state2,inst,phys,strategy,gr,**kw):
    print('REPLAN t0=%.1f'%state2.t0,'frag',kw.get('frag_sid'),'gr',sorted(gr),'drone_energy',{d:round(e,4) for d,e in state2.drone_energy.items()})
    for sid,s in new_plan.sorties.items():
        if s.started: print('  started sortie',sid,s.drone,s.air,s.handover,'rec_vid',s.rec_vid)
    r=orig(new_plan,state2,inst,phys,strategy,gr,**kw); print('  ->', 'OK' if r[0] else 'FAIL'); return r
sim.initial_recovery=ir
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
print(ep.status)
