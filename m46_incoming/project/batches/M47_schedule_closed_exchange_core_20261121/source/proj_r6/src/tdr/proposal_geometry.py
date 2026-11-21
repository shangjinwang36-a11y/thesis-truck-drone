"""Pure current-plan descriptor and paid-seed-anchored proposal proxy.
Approximate generation/ranking only, never original J, physical or budget gates.
"""
import math

def refresh(p,d,inst):
 from .complete_joint import version
 from .moves import sortie_start
 out=dict(d);out['geometry_plan_version']=version(p);out['air_groups']={sid:list(s.air)for sid,s in p.sorties.items()};out['real_cross']=sum(s.truck!=p.visits[s.rec_vid].truck for s in p.sorties.values());out.setdefault('construction_requested_depot_lambda_zero',out.get('first_depot_ARC_lambda_zero'));out['first_depot_ARC_lambda_zero']=all(s.launch_vid is not None or s.lam==0 for s in p.sorties.values());out['current_task_geometry']=[]
 for sid,s in sorted(p.sorties.items()):
  c=inst.customer(p.visits[s.rec_vid].customer)
  out['current_task_geometry'].append(dict(sid=sid,body=s.drone,body_order=p.drone_sorties[s.drone].index(sid),started=s.started,mode=s.mode,lam=s.lam,launch_vid=s.launch_vid,rec_vid=s.rec_vid,launch_truck=s.truck,receive_truck=p.visits[s.rec_vid].truck,launch_priority=s.launch_priority,rec_priority=s.rec_priority,launch_xy=list(s.start_pos)if s.started else list(sortie_start(inst,p,s)),rec_xy=[c.x,c.y],air=list(s.air)))
 if 'body_bindings'in out:out['body_bindings']=[dict(w,drone=p.sorties[w['sid']].drone,launch_truck=p.sorties[w['sid']].truck,receive_truck=p.visits[p.sorties[w['sid']].rec_vid].truck,launch=p.sorties[w['sid']].launch_vid,rec=p.sorties[w['sid']].rec_vid)for w in out['body_bindings']]
 return out

def tail_geo(p,sid,inst,phys):
 s=p.sorties[sid];rv=p.visits[s.rec_vid];rt=p.routes[rv.truck];points=[(inst.customer(p.visits[v].customer).x,inst.customer(p.visits[v].customer).y)for v in rt[rt.index(rv.vid):]]+[(inst.depot_x,inst.depot_y)]
 return sum(phys.wage_per_s*phys.ground_service_s+2*min(math.dist((inst.customer(inst.parcel_to_customer[x]).x,inst.customer(inst.parcel_to_customer[x]).y),pt)for pt in points)*(phys.c_km/1000+phys.wage_per_s/phys.truck_speed_m_s)for x in s.air)

def anchored_risk_delta(seed,q,snapshot,inst,phys):
 qi={int(k):v for k,v in snapshot['sortie_Q'].items()};assert set(qi)==set(seed.sorties)==set(q.sorties)
 dif={sid:tail_geo(q,sid,inst,phys)-tail_geo(seed,sid,inst,phys)for sid in qi};new={sid:max(0.,qi[sid]+dif[sid])for sid in qi};pr=snapshot['p']
 return pr*sum(new[s]-qi[s]for s in qi)+pr*pr*sum(min(new[int(a)],new[int(b)])-min(qi[int(a)],qi[int(b)])for a,b in snapshot['pair_links'])
