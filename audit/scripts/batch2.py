# effect of (a) delay-energy credit; (b) custody fix is via env AUDIT_FIXCUST
import sys,os,copy
from enum_event import *
def credit(inst,phys,e):
    st=e['state']; c=e['cut']; d=c['drone']
    fs=e['kw']['frag_sid']; fr=e['new_plan'].sorties[fs]
    mass=sum(inst.parcel_mass[p] for p in fr.air+fr.handover)
    cr=phys.hover_energy_kwh(max(0.0,c['t_cut']-c['t_fail']),mass)
    e2=dict(e); st2=copy.deepcopy(st)
    st2.drone_energy[d]=st.drone_energy[d]+cr
    if d in st2.drone_start: st2.drone_start[d].energy+=cr
    e2['state']=st2; return e2,cr
def best(rs,f=lambda r:True):
    c=[r['cost'] for r in rs if r['cost'] is not None and f(r)]; return min(c) if c else None
conf=sys.argv[1]; cases=sys.argv[2].split(','); n=int(sys.argv[3]); forced=int(sys.argv[4]) if len(sys.argv)>4 and sys.argv[4]!='0' else None
for case in cases:
    for seed in range(1,n+1):
        inst,phys,alg,H,evs=capture(conf,case,seed,forced=forced,n_events=1)
        if not evs: continue
        e=evs[0]; e2,cr=credit(inst,phys,e); done=set(e['state'].truck_done)
        out=[]
        for ee in (e,e2):
            rows,frag,res=enum_event(inst,phys,H,ee,'X',n_support=8)
            la=frag.launch_truck or frag.truck
            el=[r for r in rows if r['truck'] not in done]
            nx=sum(1 for r in el if r['truck']!=la and r['cost'] is not None); nxt=sum(1 for r in el if r['truck']!=la)
            out.append((best(el,lambda r:r['truck']==la),best(el,lambda r:r['truck']!=la),nx,nxt))
        print(conf,case,seed,'delay',round(e['cut']['t_cut']-e['cut']['t_fail'],1),'credit_kWh',round(cr,3),'| base S*,Xc*,feasX/allX',[None if v is None else (round(v,1) if isinstance(v,float) else v) for v in out[0]],'| credit',[None if v is None else (round(v,1) if isinstance(v,float) else v) for v in out[1]],flush=True)
