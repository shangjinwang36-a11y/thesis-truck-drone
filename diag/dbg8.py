import sys
sys.argv=['dbg6','R50','4','S','/workspace/thesis/proj/outputs/nominal_r2','1000']
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import simulate, recovery
O_IR=recovery.initial_recovery
def ir(plan,state,inst,phys,strategy,gr,**k):
    r=O_IR(plan,state,inst,phys,strategy,gr,**k)
    info=k.get('info',{})
    print('INFO',{x:info.get(x) for x in ('milp_status','milp_n_options','milp_surrogate_obj','milp_true_costs','n_catalog_entries','fallback_used','residual_feasible')})
    frag=[s for s in plan.sorties.values() if s.started]
    for s in frag:
        ds=state.drone_start.get(s.drone)
        print(' frag',s.sid,s.drone,'pos',s.start_pos,'E',round(state.drone_energy.get(s.drone,0),3),'air',s.air,'ho',s.handover)
    for t in plan.routes: print(' truck',t,'pos',state.truck_start_pos.get(t),'route',len(plan.routes[t]))
    return r
simulate.initial_recovery=ir
exec(open('dbg6.py').read())
