import sys,json,os,collections
ROOT='/workspace/thesis/audit/proj'
sys.path.insert(0, ROOT+'/src'); os.chdir(ROOT)
sys.argv=['x','RC200','6']
src=open('/workspace/thesis/audit/scripts/gh_nofrag.py').read().split("np_=cap['np']")[0]
exec(src)
sys.path.insert(0,'/workspace/thesis/audit/scripts')
from tdr import recovery as R
st=cap['st']; np_=cap['np']; gr=set(cap['gr']); kw=cap['kw']
frag=np_.sorties[kw['frag_sid']]
res=R.prepare_residual(np_,inst)
print('t0',st.t0,'frag',frag.drone,frag.truck,frag.rec_vid,frag.air,frag.handover)
reasons=collections.Counter(); ok=0; n=0
cat=R.RecoveryCatalog(res,frag,inst,'S',st,gr,phys=phys)
base,pool=R._skeleton(np_,inst)
for _ in range(300):
    es=cat.next_entries(1)
    if not es: break
    cands=R.build_residual_candidate(res,frag.sid,es[0],inst,phys,st,gr,'S')
    for cp in cands[:1]:
        ev=evaluate_plan(cp,inst,phys,st,H,'x'); n+=1
        if ev.feasible: ok+=1
        else: reasons[ev.status+':'+(ev.violations[0][:30] if ev.violations else '')]+=1
print('n',n,'ok',ok,reasons.most_common(8))
d='d9'
print('state energy',st.drone_energy.get(d),st.drone_start.get(d))
es=cat.next_entries(1)
cands=R.build_residual_candidate(res,frag.sid,{'truck':'t9','kind':'visit','ref':frag.rec_vid,'support':False,'served':[]},inst,phys,st,gr,'S')
print(len(cands))
if cands:
    ev=evaluate_plan(cands[0],inst,phys,st,H,'x'); print(ev.status,ev.violations[:2])
    from tdr.schedule import schedule_plan
    tl=schedule_plan(cands[0],inst,phys,st)
    for s_ in tl.drone_stages.get(d,[])[:6]: print(s_.kind,round(s_.start,1),round(s_.end,1),s_.mass,s_.sid)
print('--- residual itself')
from tdr.schedule import schedule_plan
ev=evaluate_plan(res,inst,phys,st,H,'x'); print(ev.status,ev.violations[:2])
tl=schedule_plan(res,inst,phys,st)
print({k:round(v) for k,v in tl.truck_finish.items() if v>H})
print([ (a for a in [])] and '')
print('attrs',[a for a in dir(tl) if not a.startswith('_')][:40])
print('swaps',tl.swaps,'msg',tl.swap_msg)
e=st.drone_energy['d9']
from tdr.schedule import stage_energy
for s_ in tl.drone_stages['d9'][:16]:
    if s_.kind=='SWAP': e=phys.e_cap
    e-=stage_energy(s_,phys)
    print(s_.kind,round(s_.start,1),round(s_.end,1),'m',round(s_.mass,2),'sid',s_.sid,'e',round(e,3))
print('plan d9 sorties',[(sid,np_.sorties[sid].started,np_.sorties[sid].air,np_.sorties[sid].handover,np_.sorties[sid].rec_vid) for sid in np_.drone_sorties['d9']])
print('=== H_EXCEEDED candidates')
cat2=R.RecoveryCatalog(res,frag,inst,'S',st,gr,phys=phys)
cnt=0
for _ in range(300):
    es=cat2.next_entries(1)
    if not es: break
    for cp in R.build_residual_candidate(res,frag.sid,es[0],inst,phys,st,gr,'S'):
        ev=evaluate_plan(cp,inst,phys,st,H,'x')
        if ev.violations and ev.violations[0].startswith('H_EXC'):
            tl2=ev.timeline; cnt+=1
            print(es[0]['truck'],es[0]['kind'],es[0]['ref'],es[0]['served'],'iterations',tl2.iterations,'finish>H',{k:round(v) for k,v in tl2.truck_finish.items() if v>H})
            if cnt==1:
                # show drone chains vs route order on t9
                for d_,sids in cp.drone_sorties.items():
                    print(d_,[(sid,cp.sorties[sid].truck,cp.sorties[sid].launch_vid,cp.sorties[sid].rec_vid,cp.sorties[sid].started) for sid in sids])
                print('t9 route',[(v,cp.visits[v].customer) for v in cp.routes['t9']])
            if cnt>=3: break
    if cnt>=3: break
