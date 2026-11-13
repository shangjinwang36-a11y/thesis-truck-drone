from dbg import *
from tdr import schedule
from tdr.schedule import stage_energy
orig=schedule._swap_pass
seen=[0]
def sp(tl,plan,phys,state,swaps):
    new,msg=orig(tl,plan,phys,state,swaps)
    if msg and seen[0]<int(os.environ.get("NSEEN","1")) and state.t0>float(os.environ.get("T0MIN","0")):
        seen[0]+=1
        d=msg.split(':')[1].split('@')[0]
        e=schedule._start_energy(state,d,phys)
        print('MSG',msg,'start e',e,'t0',state.t0)
        for st in tl.drone_stages[d]:
            en=stage_energy(st,phys); e-=en if st.kind!='SWAP' else 0
            print(st.kind,round(st.start,1),round(st.end,1),'sid',st.sid,'en=%.5f'%en,'e=%.5f'%e, getattr(st,'mass',None))
        for sid,s in plan.sorties.items():
            if s.drone==d: print('sortie',sid,s.started,s.air,s.handover,s.launch_vid,s.rec_vid, getattr(s,'start_pos',None))
    return new,msg
schedule._swap_pass=sp
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
