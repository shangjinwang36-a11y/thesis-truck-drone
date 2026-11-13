from capture import *
import time
for seed in range(1,11):
    inst,phys,alg,H,ev=capture('spec','C50',seed,n_events=1)
    if not ev: print(seed,'no failure'); continue
    e=ev[0]; np_=e['new_plan']; st=e['state']
    frag=[s for s in np_.sorties.values() if s.started]
    print(seed,'t0',st.t0,'H',H,'frags',[(s.sid,s.drone,s.air,s.handover,s.launch_truck,s.truck,s.rec_vid) for s in frag])
    print(' routes',{k:len(v) for k,v in np_.routes.items()}, 'fixed_first',st.truck_fixed_first,'done',st.truck_done)
