import sys
sys.argv=['dbg6','R50','4','S','/workspace/thesis/proj/outputs/nominal_r2','1000']
sys.path.insert(0,'/workspace/thesis/proj/src')
from tdr import recovery
o_bc=recovery.build_candidates
def bc(*a,**k):
    r=o_bc(*a,**k); print('build_candidates ->',len(r)); return r
recovery.build_candidates=bc
o_br=recovery.build_residual_candidate
def br(*a,**k):
    r=o_br(*a,**k); print('build_residual ->',len(r)); return r
recovery.build_residual_candidate=br
o_ff=recovery._first_feasible
def ff(cands,*a,**k):
    r=o_ff(cands,*a,**k); print('first_feasible: n',len(cands),'ok',r[0] is not None,'reasons',[x[:40] for x in r[3]][:3]); return r
recovery._first_feasible=ff
exec(open('dbg6.py').read())
