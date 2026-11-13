"""For one captured failure event: enumerate recovery options exhaustively (beyond the code's catalog),
evaluate each with the project's evaluator, and tally rejection reasons."""
import itertools, math, time, collections, sys
from capture import *
from tdr import recovery as R
from tdr.evaluate import evaluate_plan

POS_OVERRIDE={'pos':None}
_orig_ins=R._insert_support
def _ins(plan, inst, truck, customer, min_pos=0):
    if POS_OVERRIDE['pos'] is None: return _orig_ins(plan,inst,truck,customer,min_pos)
    return plan.add_visit(truck, customer, pos=POS_OVERRIDE['pos'], ground=[]).vid
R._insert_support=_ins

def enum_event(inst,phys,H,e,strategy='X',n_support=10,all_positions=True,verbose=False):
    new_plan=e['new_plan']; state=e['state']; gr=e['gr']; kw=e['kw']
    frag=next(s for s in new_plan.sorties.values() if s.sid==kw['frag_sid'])
    res=R.prepare_residual(new_plan,inst)
    launch=frag.launch_truck or frag.truck
    rem=[p for p in frag.air if p not in gr]
    subsets=[[]]+[rem[:k] for k in range(1,len(rem)+1)]+[[p] for p in rem[1:]]
    subsets=[list(x) for x in dict.fromkeys(tuple(s) for s in subsets)]
    subsets=subsets[:12]
    trucks=[launch] if strategy=='S' else sorted(res.routes)
    rows=[]
    fp=frag.start_pos
    for tk in trucks:
        route=res.routes.get(tk,[])
        done = tk in state.truck_done
        # existing visits
        entries=[]
        for vid in route:
            entries.append(dict(truck=tk,kind='visit',ref=vid,support=False,pos=None))
        # support visits
        cs=sorted(inst.customers,key=lambda c:math.hypot(c.x-fp[0],c.y-fp[1]))[:n_support]
        mp=state.truck_min_insert.get(tk,0)
        for c in cs:
            poss=range(mp,len(route)+1) if all_positions else [None]
            for i in poss:
                entries.append(dict(truck=tk,kind='support',ref=c.customer_id,support=True,pos=i))
        for en in entries:
            for sv in subsets:
                ent=dict(en); ent['served']=sv
                POS_OVERRIDE['pos']=en['pos']
                cands=R.build_residual_candidate(res,frag.sid,ent,inst,phys,state,gr,strategy)
                POS_OVERRIDE['pos']=None
                if not cands:
                    rows.append(dict(truck=tk,done=done,ent=ent,status='BUILD_FAILED',cost=None,viol=''));continue
                best=None; reasons=[]
                for cp in cands:
                    ev=evaluate_plan(cp,inst,phys,state,H,'AUDIT')
                    if ev.feasible:
                        if best is None or ev.cost<best[0]: best=(ev.cost,ev.z)
                    else: reasons.append((ev.status,ev.violations[0] if ev.violations else ''))
                rows.append(dict(truck=tk,done=done,ent=ent,status='OK' if best else reasons[0][0],
                                 cost=best[0] if best else None,viol=reasons[0][1] if (reasons and not best) else '', launch=launch))
    return rows,frag,res
