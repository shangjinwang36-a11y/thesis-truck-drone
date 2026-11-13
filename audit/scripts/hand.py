import math,sys
from enum_event import *
conf,case,seed=sys.argv[1],sys.argv[2],int(sys.argv[3])
inst,phys,alg,H,evs=capture(conf,case,seed,n_events=1)
e=evs[0]; st=e['state']; np_=e['new_plan']; fs=e['kw']['frag_sid']; fr=np_.sorties[fs]
d=fr.drone; E=st.drone_energy[d]; mass=sum(inst.parcel_mass[p] for p in fr.air+fr.handover)
ph=phys.hover_power(mass)
print('drone',d,'launch',fr.launch_truck,'E_now',round(E,3),'E_min',phys.e_min,'mass kg',round(mass,2),'P_h kW',round(ph,2))
print('max wait (immediate-R at failure pt) s = ',round(3600*(E-phys.e_min)/ph-phys.recovery_s,0))
fp=fr.start_pos
for k,rt in np_.routes.items():
    pos=st.truck_start_pos[k]; dist=math.hypot(pos[0]-fp[0],pos[1]-fp[1])
    t_direct=dist/phys.truck_speed_m_s
    first=st.truck_first_travel_s.get(k,0) if st.truck_fixed_first.get(k) else 0
    cust=[np_.visits[v].customer for v in rt]
    print(k,'done' if k in st.truck_done else '', 'route',cust,'dist_to_failpt m',round(dist),'direct drive s',round(t_direct),'fixed_first',st.truck_fixed_first.get(k),'first_travel',round(first))
