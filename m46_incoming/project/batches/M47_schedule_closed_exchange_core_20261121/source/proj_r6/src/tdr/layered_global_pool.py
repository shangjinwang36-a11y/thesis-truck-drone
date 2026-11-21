"""Whole-pool hierarchical backbone + layered real-body circulation.
NEW APPROXIMATE algorithm, not an equivalent cache or exhaustive catalogue.
No evaluator, worlds, flags, customer/seed identifiers, RNG or budget objects.
All complete proposals must subsequently pay original native/J/stream/H gates.
"""
import math,time
from collections import Counter
from .joint_air_promote import air,identity

def anchor_hierarchy(p,inst,include_support=False):
    xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y) for v,z in p.visits.items()}
    nested={}
    for t,rt in sorted(p.routes.items()):
        eligible=[v for v in rt if p.visits[v].ground]
        chosen=[];left=set(eligible)
        while left:
            # Heavy stops seed a geometric covering hierarchy; heuristic only.
            def rank(v):
                mass=sum(inst.parcel_mass[x] for x in p.visits[v].ground)
                separation=min((math.dist(xy[v],xy[w]) for w in chosen),default=mass)
                return (-separation,-mass,rt.index(v),v)
            v=min(left,key=rank);chosen.append(v);left.remove(v)
        nested[t]=chosen
    levels=max((math.ceil(math.log2(len(v))) for v in nested.values() if v),default=0)
    for level in range(1,levels+1):
        selected={t:set(v[:max(1,math.ceil(len(v)/(2**level)))]) if v else set() for t,v in nested.items()}
        if include_support:
            for t,rt in p.routes.items():selected[t].update(v for v in rt if not p.visits[v].ground)
        yield level,{t:[v for v in p.routes[t] if v in selected[t]] for t in p.routes}

def make_jobs(p,anchors,inst,phys,arc_mid=False):
    dep=(inst.depot_x,inst.depot_y);xy={v:(inst.customer(z.customer).x,inst.customer(z.customer).y) for v,z in p.visits.items()};jobs=[]
    for t,rt in sorted(anchors.items()):
        prior=None
        for layer,v in enumerate(rt):
            start=dep if prior is None else xy[prior];end=xy[v];mode='ARC'if prior is None or arc_mid else'STOP';lam=.5 if prior is not None and arc_mid else 0.;start=(start[0]+lam*(end[0]-start[0]),start[1]+lam*(end[1]-start[1]))
            for lane in range(len(phys.home_drones(t))):
                jobs.append(dict(index=len(jobs),mode=mode,lam=lam,truck=t,launch=prior,rec=v,receiver=t,layer=layer,lane=lane,start=start,end=end,road_s=math.dist(start,end)/phys.truck_speed_m_s))
            prior=v
    return jobs,xy

def pack(pool,jobs,inst,phys,order,dg):
    from .moves import air_energy,air_time
    groups={j['index']:[] for j in jobs};energies={k:0. for k in groups};scores={k:0. for k in groups};masses={k:0. for k in groups}
    def score(j,g):
        dg['energy_time_queries']+=1
        en=air_energy(inst,phys,j['start'],g,j['end']);dt=air_time(inst,phys,j['start'],g,j['end'])
        return en,phys.cost_depot_kwh*en+phys.wage_per_s*(phys.prepare_s+phys.launch_s+phys.recovery_s+max(0.,dt-j['road_s']))
    if order=='mass_first':todo=sorted(pool,key=lambda x:(-inst.parcel_mass[x],x))
    else:
        def angle(x):
            c=inst.customer(inst.parcel_to_customer[x]);return(math.atan2(c.y-inst.depot_y,c.x-inst.depot_x),-inst.parcel_mass[x],x)
        todo=sorted(pool,key=angle)
    for parcel in todo:
        offers=[];dg['packing_steps']+=1
        for j in jobs:
            k=j['index'];g=groups[k]
            if masses[k]+inst.parcel_mass[parcel]>phys.drone_payload_limit_kg+1e-9:continue
            for at in range(len(g)+1):
                trial=g[:at]+[parcel]+g[at:];en,sc=score(j,trial)
                if en>phys.e_cap-phys.e_min+phys.energy_tol:continue
                offers.append((sc-scores[k],k,at,en,sc))
        if not offers:
            dg.setdefault('packing_failures',[]).append(dict(parcel=parcel,mass=inst.parcel_mass[parcel],minimum_single_energy=min((air_energy(inst,phys,j['start'],[parcel],j['end'])for j in jobs),default=None),jobs=len(jobs),assigned=sum(len(g)for g in groups.values())))
            return None
        _,k,at,en,sc=min(offers);groups[k].insert(at,parcel);energies[k]=en;scores[k]=sc;masses[k]+=inst.parcel_mass[parcel]
    return groups

def match_endpoints(jobs,groups,inst,phys,dg):
    from scipy.optimize import linear_sum_assignment
    from .moves import air_energy,air_time
    q=[dict(j) for j in jobs]
    for layer,lane in sorted({(j['layer'],j['lane']) for j in jobs}):
        active=[j for j in jobs if(j['layer'],j['lane'])==(layer,lane) and groups[j['index']]]
        if len(active)<2:continue
        matrix=[];routes={}
        for a in active:
            row=[];g=groups[a['index']]
            for b in active:
                alternatives=[]
                for seq in (g,list(reversed(g))):
                    dg['energy_time_queries']+=1;en=air_energy(inst,phys,a['start'],seq,b['end']);dt=air_time(inst,phys,a['start'],seq,b['end'])
                    if en<=phys.e_cap-phys.e_min+phys.energy_tol:alternatives.append((phys.cost_depot_kwh*en+phys.wage_per_s*max(0.,dt-b['road_s']),tuple(seq)))
                best=min(alternatives) if alternatives else None;row.append(best[0] if best else float('inf'));routes[a['index'],b['index']]=best
            matrix.append(row)
        # The feasible identity assignment exists from packing, no exception fallback.
        ix,jx=linear_sum_assignment(matrix);dg['assignment_cells']+=len(active)**2
        for i,j in zip(ix,jx):
            a,b=active[int(i)],active[int(j)];best=routes[a['index'],b['index']];assert best is not None
            q[a['index']].update(rec=b['rec'],receiver=b['truck'],end=b['end']);groups[a['index']]=list(best[1])
    return q,groups

def close(p,anchors,jobs,groups,inst,phys):
    q=p.clone();q.sorties={};q.drone_sorties={f'd{k+1}':[] for k in range(phys.drone_count)}
    retained={v for rt in anchors.values() for v in rt}
    for v in list(q.visits):
        if v not in retained:q.remove_visit(v)
    carriers={t:list(phys.home_drones(t)) for t in sorted(q.routes)};bindings=[]
    for layer in sorted({j['layer'] for j in jobs}):
        layer_jobs=[j for j in jobs if j['layer']==layer];nextcarriers={t:list(v) for t,v in carriers.items()}
        for j in layer_jobs:
            d=carriers[j['truck']][j['lane']];g=groups[j['index']]
            if not g:
                assert j['truck']==j['receiver'];continue
            s=q.add_sortie(d,j['truck'],j['launch'],j['mode'],j['lam'],list(g),j['rec'],order=len(q.drone_sorties[d]));s.launch_truck=j['truck'];s.launch_priority=j['lane'];s.rec_priority=j['lane'];bindings.append(dict(sid=s.sid,drone=d,launch_truck=j['truck'],receive_truck=j['receiver'],launch=j['launch'],rec=j['rec'],layer=layer,lane=j['lane']))
            nextcarriers[j['receiver']][j['lane']]=d
        assert len({d for ds in nextcarriers.values() for d in ds})==phys.drone_count
        carriers=nextcarriers
    return q,bindings,carriers

def _base_geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2,include_support=False,arc_mid=False):
    dg=diag if diag is not None else {};start=time.process_time();dg.update(algorithm='APPROXIMATE_HIERARCHICAL_WHOLE_POOL',energy_time_queries=0,packing_steps=0,assignment_cells=0,descriptors_entered=0,packing_rejected=0,structural_rejected=0,yielded=0,raw_total=0,raw_examined=0,topologies=[])
    if any(s.started or s.handover for s in p.sorties.values()):return
    hierarchy=list(anchor_hierarchy(p,inst,include_support));dg['finite_descriptor_upper']=len(hierarchy)*2*(2 if allow_cross else 1);dg['hierarchy_levels']=len(hierarchy);dg['maximum_jobs']=phys.drones_per_truck_initial*sum(len(rt) for rt in p.routes.values());seen=set();oldair=air(p)
    for level,anchors in hierarchy:
        ground={x for rt in anchors.values() for v in rt for x in p.visits[v].ground};pool=set(inst.parcel_mass)-ground;extra=pool-oldair
        if len(extra)<3 or not oldair<=pool:continue
        jobs,xy=make_jobs(p,anchors,inst,phys,arc_mid);dg['topologies'].append(dict(level=level,ground=len(ground),air=len(pool),jobs=len(jobs),trucks=sum(bool(v) for v in anchors.values()),retained={t:list(v) for t,v in anchors.items()},visible_expected_nonfailed_pool=(1.-p_fail)*len(pool)))
        for order in ['mass_first','spatial_sweep']:
            dg['descriptors_entered']+=1;groups=pack(pool,jobs,inst,phys,order,dg)
            if groups is None:dg['packing_rejected']+=1;continue
            for cross in ([False,True] if allow_cross else [False]):
                js=[dict(j) for j in jobs];gs={k:list(g) for k,g in groups.items()}
                if cross:js,gs=match_endpoints(js,gs,inst,phys,dg)
                q,bindings,carriers=close(p,anchors,js,gs,inst,phys)
                errors=q.validate_structure(inst,phys,initial_carrier={f'd{k+1}':phys.home_truck(f'd{k+1}')for k in range(phys.drone_count)})
                if errors:
                    dg['structural_rejected']+=1;dg.setdefault('structural_errors',[]).append(errors);continue
                sig=identity(q)
                if sig in seen:continue
                seen.add(sig);assert air(q)==pool and oldair<=air(q);assert not any(s.handover for s in q.sorties.values());dg['yielded']+=1;dg['construction_CPU_s_so_far']=time.process_time()-start
                oldvisits=sorted(set(p.visits)-set(q.visits));ids=sorted(q.sorties)
                yield q,dict(kind='MULTI_TASK_POOL_RECONSTRUCTION',construction='WHOLE_POOL_LAYERED_BODY_CIRCULATION',support_corridor=include_support,ARC_mid_release=arc_mid,parcels=sorted(extra),old_visits=oldvisits,sorties=ids,new_rendezvous=[q.sorties[sid].rec_vid for sid in ids],air_groups={sid:list(q.sorties[sid].air) for sid in ids},hierarchy_level=level,packing_order=order,endpoint_matching=cross,all_old_air_preserved=True,all_original_flights_reconstructed=True,body_bindings=bindings,terminal_carriers=carriers,real_cross=sum(b['launch_truck']!=b['receive_truck'] for b in bindings),multi_truck=True,approximate_not_exhaustive=True,finite_descriptor_upper=dg['finite_descriptor_upper'])
    dg['construction_CPU_s']=time.process_time()-start;dg['raw_total']=dg['descriptors_entered'];dg['raw_examined']=dg['descriptors_entered']


def legacy_geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
    dg=diag if diag is not None else {};dg.update(algorithm='APPROXIMATE_FEASIBILITY_DIRECTED_WHOLE_POOL',variants=[],energy_time_queries=0,packing_steps=0,assignment_cells=0,descriptors_entered=0,packing_rejected=0,structural_rejected=0,yielded=0,raw_total=0,raw_examined=0,topologies=[],packing_failures=[],finite_descriptor_upper=0,maximum_jobs=phys.drones_per_truck_initial*sum(len(rt)for rt in p.routes.values()),hierarchy_levels=0)
    # Only proceed to a new physical-corridor family if the preceding COMPLETE
    # geometry catalogue could not close even one plan. No map/customer switch.
    for support,arc in [(False,False),(False,True),(True,False),(True,True)]:
        vd={};closed=0;dg['variants'].append(dict(include_support=support,ARC_mid_release=arc,diag=vd))
        for q,d in _base_geometries(p,inst,phys,launch_order,allow_cross,vd,timeline,p_fail,support,arc):
            closed+=1;dg['yielded']+=1;yield q,d
        for k in ['energy_time_queries','packing_steps','assignment_cells','descriptors_entered','packing_rejected','structural_rejected','raw_total','raw_examined']:dg[k]+=vd.get(k,0)
        dg['topologies']+=vd.get('topologies',[]);dg['packing_failures']+=vd.get('packing_failures',[]);dg['finite_descriptor_upper']+=vd.get('finite_descriptor_upper',0);dg['hierarchy_levels']=max(dg['hierarchy_levels'],vd.get('hierarchy_levels',0))
        if closed:dg['remaining_corridor_families_not_expanded']=4-len(dg['variants']);break
    dg['all_corridor_families_upper']=4*dg['hierarchy_levels']*2*(2 if allow_cross else 1)


def geometries(p,inst,phys,launch_order,allow_cross,diag=None,timeline=None,p_fail=.2):
 from .resource_corridor_pool import geometries as resource
 dg=diag if diag is not None else{};dg.update(algorithm='M41_INTERLEAVED_OLD_AND_RESOURCE_CORRIDOR',legacy={},resource={},families_exhausted=0)
 from .noncontiguous_pool import geometries as owned
 dg['owned']={}
 streams=[iter(owned(p,inst,phys,launch_order,allow_cross,dg['owned'],timeline,p_fail)),iter(legacy_geometries(p,inst,phys,launch_order,allow_cross,dg['legacy'],timeline,p_fail)),iter(resource(p,inst,phys,launch_order,allow_cross,dg['resource'],timeline,p_fail))]
 while streams:
  for stream in list(streams):
   try:yield next(stream)
   except StopIteration:streams.remove(stream);dg['families_exhausted']+=1
