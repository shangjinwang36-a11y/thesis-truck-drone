"""Paid-observation-only original recourse feedback; approximate proposal ranking.
No exact Q/J trial of an uncharged new plan. Capture merely observes the SAME
original expected_j invocation already made for a charged feasible candidate.
"""
import math
from collections import deque
from .complete_joint import version
from .joint_air_promote import air

def capture_expected_j(cost,plan,inst,phys,prob):
    from . import expected_cost as ec,moves
    if cost is None:return ec.expected_j(cost,plan,inst,phys,prob),None
    oldg,oldc,oldo=moves.ground_candidates,ec._consecutive,ec._overlap;proxies={};consecutive={};overlap={};calls=0
    def ground(p,*args,**kwargs):
        nonlocal calls
        result=oldg(p,*args,**kwargs)
        if p is plan:
            parcel=args[2] if len(args)>2 else kwargs['parcel'];assert parcel not in proxies;proxies[parcel]=result[0].proxy;calls+=1
        return result
    def cons(p,a,b):
        v=oldc(p,a,b)
        if p is plan:consecutive[tuple(sorted((a.sid,b.sid)))]=v
        return v
    def over(p,i,ph,a,b):
        v=oldo(p,i,ph,a,b)
        if p is plan:overlap[tuple(sorted((a.sid,b.sid)))]=v
        return v
    moves.ground_candidates=ground;ec._consecutive=cons;ec._overlap=over
    try:J=ec.expected_j(cost,plan,inst,phys,prob)
    finally:moves.ground_candidates=oldg;ec._consecutive=oldc;ec._overlap=oldo
    flights=[s for s in plan.sorties.values()if not s.started and s.air and s.rec_vid in plan.visits];Qi={s.sid:(0. if s.handover else phys.wage_per_s*phys.handover_s)+sum(proxies[x]for x in s.air)for s in flights};pairs=[]
    for i,a in enumerate(flights):
        for b in flights[i+1:]:
            pair=tuple(sorted((a.sid,b.sid)))
            if plan.visits[a.rec_vid].truck==plan.visits[b.rec_vid].truck and(consecutive.get(pair,False)or a.rec_vid==b.rec_vid or overlap.get(pair,False)):pairs.append(pair)
    single=prob*sum(Qi.values());coupling=prob*prob*sum(min(Qi[a],Qi[b])for a,b in pairs);assert abs(J-(cost+single+coupling))<1e-7
    return J,dict(plan_version=version(plan),p=prob,parcel_proxy=proxies,sortie_Q=Qi,pair_links=pairs,single=single,pair=coupling,original_ground_queries_observed=calls,additional_exact_Q_or_J_queries=0,capture_same_original_paid_J_call=True)

class PaidFeedback:
    def __init__(self,ctx,diag):self.ctx=ctx;self.diag=diag;self.seeds={};self.emitted=set();diag.update(paid_observations=0,exact_risk_trial_calls_added=0,geometry_descriptors_examined=0,geometry_energy_queries=0,complete_feedback_proposals=0,seed_versions=[]) 
    def observe(self,q,e,row,snapshot,descriptor):
        if not all(row['gates'].values())or snapshot is None:return
        assert snapshot['plan_version']==version(q) and snapshot['capture_same_original_paid_J_call'];self.diag['paid_observations']+=1;key=tuple(sorted(air(q)));old=self.seeds.get(key)
        if old is None or row['J']<old['row']['J']-1e-9:
            self.seeds[key]=dict(plan=q.clone(),ev=e,row=row,snap=snapshot,descriptor=dict(descriptor),queue=None);self.diag['seed_versions'].append(version(q))
    def descriptors(self,seed):
        p=seed['plan'];snap=seed['snap'];inst,phys=self.ctx.inst,self.ctx.phys;pr=snap['p'];qi={int(k):v for k,v in snap['sortie_Q'].items()};links=[tuple(z)for z in snap['pair_links']];old=snap['parcel_proxy'];owner={x:sid for sid,s in p.sorties.items()for x in s.air};parcels=sorted(owner);neighbors={sid:set()for sid in qi}
        for a,b in links:neighbors[a].add(b);neighbors[b].add(a)
        routes={t:[(inst.customer(p.visits[v].customer).x,inst.customer(p.visits[v].customer).y)for v in rt]+[(inst.depot_x,inst.depot_y)]for t,rt in p.routes.items()};geo={}
        for sid,s in p.sorties.items():
            t=p.visits[s.rec_vid].truck;idx=p.routes[t].index(s.rec_vid);points=routes[t][idx:]
            for x in parcels:
                c=inst.customer(inst.parcel_to_customer[x]);dist=min(math.dist((c.x,c.y),point)for point in points);geo[x,sid]=phys.wage_per_s*phys.ground_service_s+2*dist*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)
        def delta(changes):
            ids=set(changes);ds=pr*sum(changes.values());affected={tuple(sorted((a,b)))for a in ids for b in neighbors[a]};return ds+pr*pr*sum(min(qi[a]+changes.get(a,0.),qi[b]+changes.get(b,0.))-min(qi[a],qi[b])for a,b in affected)
        desc=[]
        for x in parcels:
            a=owner[x]
            if len(p.sorties[a].air)<=1:continue
            for b in sorted(p.sorties):
                if a==b:continue
                if sum(inst.parcel_mass[y]for y in p.sorties[b].air)+inst.parcel_mass[x]>phys.drone_payload_limit_kg+1e-9:continue
                desc.append((delta({a:-old[x],b:geo[x,b]}),'MOVE',x,'',a,b))
        for i,x in enumerate(parcels):
            a=owner[x]
            for y in parcels[i+1:]:
                b=owner[y]
                if a==b:continue
                ma=sum(inst.parcel_mass[z]for z in p.sorties[a].air)-inst.parcel_mass[x]+inst.parcel_mass[y];mb=sum(inst.parcel_mass[z]for z in p.sorties[b].air)-inst.parcel_mass[y]+inst.parcel_mass[x]
                if max(ma,mb)>phys.drone_payload_limit_kg+1e-9:continue
                desc.append((delta({a:-old[x]+geo[y,a],b:-old[y]+geo[x,b]}),'SWAP',x,y,a,b))
        self.diag.setdefault('descriptor_bounds',[]).append(dict(seed_version=version(p),air=len(parcels),flights=len(p.sorties),actual=len(desc),upper=len(parcels)*len(p.sorties)+len(parcels)*(len(parcels)-1)//2,ranking='approximate only: original paid Q/pair links plus roundtrip-to-visible-tail geometry, NOT exact candidate Q/J'))
        return deque(sorted(desc))
    def next(self):
        from .moves import air_energy,air_time,sortie_start
        inst,phys=self.ctx.inst,self.ctx.phys
        for seed in sorted(self.seeds.values(),key=lambda z:(z['row']['J']-z['row']['parent_J'],version(z['plan']))):
            if seed['queue']is None:seed['queue']=self.descriptors(seed)
            while seed['queue']:
                predicted,kind,x,y,a,b=seed['queue'].popleft();self.diag['geometry_descriptors_examined']+=1;p=seed['plan'];q=p.clone();q.sorties[a].air.remove(x)
                if kind=='SWAP':q.sorties[b].air.remove(y)
                def insert(sid,parcel):
                    so=q.sorties[sid];start=sortie_start(inst,q,so);c=inst.customer(q.visits[so.rec_vid].customer);end=(c.x,c.y);options=[]
                    for at in range(len(so.air)+1):
                        g=so.air[:at]+[parcel]+so.air[at:];self.diag['geometry_energy_queries']+=1;en=air_energy(inst,phys,start,g,end)
                        if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
                        dt=air_time(inst,phys,start,g,end);options.append((phys.cost_depot_kwh*en+phys.wage_per_s*dt,at,g))
                    if not options:return False
                    so.air=min(options)[2];return True
                if kind=='SWAP'and not insert(a,y):continue
                if not insert(b,x):continue
                # Removal can alter service/hover energy; both full affected legs stay native-gated.
                good=True
                for sid in [a,b]:
                    so=q.sorties[sid];c=inst.customer(q.visits[so.rec_vid].customer);self.diag['geometry_energy_queries']+=1
                    if air_energy(inst,phys,sortie_start(inst,q,so),so.air,(c.x,c.y))>phys.e_cap-phys.e_min+phys.energy_tol:good=False;break
                if not good:continue
                v=version(q)
                if v in self.emitted:continue
                self.emitted.add(v);assert air(q)==air(p);assert not q.validate_structure(inst,phys,initial_carrier={f'd{k+1}':phys.home_truck(f'd{k+1}')for k in range(phys.drone_count)})
                d=dict(seed['descriptor']);d.update(refinement='PAID_ORIGINAL_RECOURSE_CARGO_CIRCULATION',paid_seed_version=version(p),paid_seed_J=seed['row']['J'],paid_seed_H=self.ctx.H,approximate_risk_delta=predicted,move=dict(kind=kind,parcel=x,other=y,source=a,target=b),air_groups={sid:list(s.air)for sid,s in q.sorties.items()},risk_ranking_not_original_candidate_J=True);self.diag['complete_feedback_proposals']+=1;return q,d
        return None
