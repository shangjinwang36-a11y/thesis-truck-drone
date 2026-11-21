import ast,inspect,textwrap,json
from types import SimpleNamespace as NS
from tdr.experiment import build_case_nominal,load_case_nominal,plan_to_dict,nominal_and_recovery
from tdr.plan import Plan

def horizon_assignments(reference,finish):
 tree=ast.parse(textwrap.dedent(inspect.getsource(build_case_nominal)))
 body=tree.body[0].body
 start=next(i for i,n in enumerate(body)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='derived_plan_z_plus_slack'for t in n.targets))
 subset=ast.Module(body=body[start:start+3],type_ignores=[])
 env=dict(ev=NS(timeline=NS(truck_finish={'t1':finish})),phys=NS(shift_slack_s=1800),alg=NS(_nominal_reference_H=reference))
 exec(compile(subset,'actual_export_assignments','exec'),env)
 return env['H'],env['derived_plan_z_plus_slack']

def test_export_uses_corresponding_fixed_S_H_not_X_finish():
 assert horizon_assignments(5911.709582085911,4141.709582085911)==(5911.709582085911,5941.709582085911)

def test_export_legacy_fallback_only_without_fixed_reference():
 assert horizon_assignments(None,20)==(1820,1820)

def test_actual_loader_roundtrip_never_substitutes_derived_X_value(tmp_path):
 p=Plan('UNIT');data=plan_to_dict(p,None)
 (tmp_path/'nominal_plan.json').write_text(json.dumps(dict(plan=data,H_s=9,derived_plan_z_plus_slack=39)))
 (tmp_path/'cost.json').write_text(json.dumps(dict(cost=123,H_s=9,derived_plan_z_plus_slack=39)))
 loaded,cost,H=load_case_nominal(None,tmp_path)
 assert H==9 and cost['cost']==123 and loaded.case_id=='UNIT'

def test_all_three_roles_use_original_nominal_recovery_design():
 s=Plan('S');x=Plan('X')
 for role,expected,policy in [('S',s,'S'),('R',s,'X'),('X',x,'X')]:
  actual,pol=nominal_and_recovery(role,s,x,False)
  assert actual.case_id==expected.case_id and pol==policy
  if role=='R':assert actual is not s

def test_execution_driver_uses_corresponding_S_H_for_all_roles():
 from research import ROOT
 text=(ROOT/'execute_recorded.py').read_text()
 assert 'K1_FROZEN/"nominal/S"/case/"nominal_plan.json"'in text
 assert '/"nominal/S"/case/"nominal_plan.json"'in text
 assert 'pol="S" if arm=="S" else "X"'in text
 assert 'raw=read(ROOT/variant/"nominal"/("X" if arm=="X" else "S")'in text
