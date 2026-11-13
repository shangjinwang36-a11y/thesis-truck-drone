from dbg import *
from tdr.schedule import stage_energy
pkg,phys,alg=setup(); case='C50'
inst=load_instance(pkg,case); phys=phys.for_case(pkg.get('case_fleet'),case)
plan,ncost,H=load_case_nominal(inst,Path(ROOT+'/outputs/nominal_light1000')/case)
ev=evaluate_plan(plan,inst,phys,initial_state(inst,phys),H,'NOMINAL')
tl=ev.timeline
print(ev.feasible, tl.drone_energy['d3'])
for i,st in enumerate(tl.drone_stages['d3']):
    print(st.kind,round(st.start,1),round(st.end,1),st.sid,'en=%.5f'%stage_energy(st,phys),'e_after=%.5f'%tl.drone_energy['d3'][i+1],st.mass)
