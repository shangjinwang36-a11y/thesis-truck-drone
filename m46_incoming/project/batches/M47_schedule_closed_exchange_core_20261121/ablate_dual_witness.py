from research import *
import itertools
from process_state import record
from tdr.alns import Budget,SearchStats,SolveContext,eval_counted,_ACTIVE_CTX,_within_makespan_cap,_nominal_cross_intact,_cross_energy_ok
from tdr.expected_cost import expected_j,failure_prob
from tdr.hybrid import scenario_score
from tdr.complete_joint import version
from tdr.joint_dual import orders,terminal_inventory
from tdr.joint_air_promote import body_covers
from tdr.moves import air_energy,air_time,sortie_start
stage='dual_component_ablations';record(stage);dest=ROOT/'diagnostics/dual_component_ablations';assert not dest.exists();dest.mkdir();w=read(ROOT/'diagnostics/remaining_visible_RC100/WITNESS_1.json');d=w['row']['descriptor'];p=plan_from_dict(w['parent']);q=plan_from_dict(w['child']);inst,phys,alg=setup('RC100','M14',True);phys.set_active();H=alg._nominal_reference_H;st=rr.initial_state(inst,phys);st.nominal_cross=True;ctx=SolveContext(inst,phys,alg,st,H,mode='nominal',strategy='X');ctx.scenario_on=True
prior=read(ROOT/'diagnostics/remaining_visible_RC100/LEDGER.json')['cumulative_physical']+read(ROOT/'diagnostics/DUAL_WITNESS_AUDIT_LEDGER.json')['envelope']['used'];b=Budget(1000-prior,None);ss=SearchStats();ctx.live_budget=b;ctx.live_stats=ss;tok=_ACTIVE_CTX.set(ctx);rows=[];seen=set();plans=[]
for rv in d['new_rendezvous']:
 z=q.clone()
 for sid,old in p.sorties.items():
  if old.rec_vid in d['old_visits']:z.sorties[sid].rec_vid=rv
  if old.launch_vid in d['old_visits']:z.sorties[sid].launch_vid=rv;z.sorties[sid].truck=z.visits[rv].truck
 plans.append(('COMMON_ANCHOR_KEEP_REPARTITION',z,dict(common_receiver=rv)))
a,bid=d['sorties'];extra=d['parcels']
for assign in itertools.product(range(2),repeat=2):
 g=[list(p.sorties[a].air),list(p.sorties[bid].air)]
 for x,ix in zip(extra,assign):g[ix].append(x)
 if any(sum(inst.parcel_mass[x]for x in group)>phys.drone_payload_limit_kg+1e-9 for group in g):continue
 choices=[]
 for sid,group in zip((a,bid),g):
  so=q.sorties[sid];rv=q.visits[so.rec_vid];c=inst.customer(rv.customer);start=sortie_start(inst,q,so);paths=orders(group,inst,start);end=(c.x,c.y);mnE=min(paths,key=lambda seq:(air_energy(inst,phys,start,list(seq),end),seq));mnT=min(paths,key=lambda seq:(air_time(inst,phys,start,list(seq),end),seq));choices.append(list(dict.fromkeys([mnE,mnT])))
 for x,y in itertools.product(*choices):
  z=q.clone();z.sorties[a].air=list(x);z.sorties[bid].air=list(y);plans.append(('DUAL_ANCHOR_KEEP_ORIGINAL_GROUPS',z,dict(assignment=list(assign),orders=[list(x),list(y)])))
try:
 with rr.audit_evaluations()as au,cap_physical(b.eval_limit,reference_H=H)as en:
  try:
   ep=eval_counted(p,inst,phys,st,H,'ABLATION_PARENT',ss,b);pJ=expected_j(ep.cost,p,inst,phys,failure_prob(alg));parentSC=None;order={sid:t[0]for sid,t in ep.timeline.launch_times.items()}
   for kind,z,desc in plans:
    for candidate in body_covers(z,inst,phys,order,limit=4,node_cap=512):
     sig=version(candidate)
     if sig in seen:continue
     seen.add(sig)
     if b.evals_left()<=0:break
     e=eval_counted(candidate,inst,phys,st,H,'ABLATION_COMPLETE',ss,b);gates=dict(physical=e.feasible,H=_within_makespan_cap(e,ctx),robust=_nominal_cross_intact(candidate,e,ctx),energy=_cross_energy_ok(candidate,p,e,ctx));J=expected_j(e.cost,candidate,inst,phys,failure_prob(alg))if e.feasible else None;SC=None
     if all(gates.values())and J<pJ-alg.cost_tolerance_yuan:
      if parentSC is None:parentSC=scenario_score(p,ep,ctx)
      SC=scenario_score(candidate,e,ctx)
     rows.append(dict(kind=kind,descriptor=desc,version=sig,cost=e.cost,J=J,SC=SC,parent_J=pJ,parent_SC=parentSC,gates=gates,accepted=bool(all(gates.values())and J<pJ-alg.cost_tolerance_yuan and SC is not None and parentSC is not None and SC<=parentSC+alg.cost_tolerance_yuan),violations=e.violations,plan=plan_to_dict(candidate,inst)))
  finally:dump(dest/'LEDGER.json',dict(ledger=au.summary(),envelope=en.summary(),prior_paid_physical=prior,cumulative_physical=prior+b.used,rows=rows,scope='Finite paired projections of the found complete plan, not proof of global ALNS unreachability or a new production budget.'))
finally:_ACTIVE_CTX.reset(tok);record(stage,True,dict(physical=b.used,rows=len(rows)))
assert prior+b.used<=1000
print('ABLATIONS',len(rows),'accepted',Counter(x['kind']for x in rows if x['accepted']),'Jbest',{k:min((x['J']for x in rows if x['kind']==k and x['J']is not None),default=None)for k in set(x['kind']for x in rows)},'physical',b.used)
