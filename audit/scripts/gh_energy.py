import sys
exec(open('gh_nofrag.py').read().split("np_=cap['np']")[0])
st=cap['st']; np_=cap['np']; fs=cap['kw']['frag_sid']
a,k=cap['trargs']; t_cut,t_fail,failed_sid,parcel,drone=a[2:7]
print('t_fail',t_fail,'t_cut',t_cut,'delay',t_cut-t_fail,'frag in plan',fs in np_.sorties)
fr=np_.sorties.get(fs)
e_cut=st.drone_energy[drone]
mass=sum(inst.parcel_mass[p] for p in (fr.air+fr.handover)) if fr else None
ph=phys.hover_power(mass) if mass else None
print('energy at cut',e_cut,'E_min',phys.e_min,'mass',mass,'hover kW',ph)
if ph:
    print('energy at fail',e_cut+ph*(t_cut-t_fail)/3600,'hover seconds to E_min from fail',(e_cut+ph*(t_cut-t_fail)/3600-phys.e_min)/ph*3600)
# which truck is the launch truck and distance
if fr:
    print('launch truck',fr.launch_truck,'start_pos',fr.start_pos,'truck pos',{k:v for k,v in st.truck_start_pos.items() if k==fr.launch_truck})
    import math
    tp=st.truck_start_pos[fr.launch_truck]; print('dist truck-drone m',math.hypot(tp[0]-fr.start_pos[0],tp[1]-fr.start_pos[1]),'truck speed',phys.truck_speed_m_s)
