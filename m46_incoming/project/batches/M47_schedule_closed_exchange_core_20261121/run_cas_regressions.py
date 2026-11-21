from research import *
import pytest,os
os.chdir(ROOT);calls=Counter();denied=Counter()
def profile(f,event,arg):
 if event=='return'and f.f_code.co_name=='evaluate_plan'and f.f_code.co_filename.endswith('/tdr/evaluate.py'):
  (calls if f.f_locals.get('accepted')else denied)[os.environ.get('PYTEST_CURRENT_TEST','setup')+'|'+str(f.f_locals.get('reason',''))]+=1
sys.setprofile(profile)
try:code=pytest.main(['-q','test_canonical_H.py','test_terminal_joint.py','test_joint_dual.py','test_joint_block.py','test_current_cas.py','test_actual_H_driver.py','test_nominal_accounting.py','source/proj_r6/tests/test_energy.py','source/proj_r6/tests/test_t02_channel_committed_launch.py','source/proj_r6/tests/test_t08a_fix_ground_fingerprint.py'])
finally:
 sys.setprofile(None);dump(ROOT/'diagnostics'/f'REGRESSION_CALLS_{time.time_ns()}.json',dict(exit_code=locals().get('code'),accepted=sum(calls.values()),denied=sum(denied.values()),per_test_reason=dict(calls),denied_per_test_reason=dict(denied)))
raise SystemExit(code)
