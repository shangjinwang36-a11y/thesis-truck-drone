import sys,json
sys.path.insert(0,'/workspace/thesis/diag')
from drv2 import *
case=sys.argv[1]; ao=json.loads(sys.argv[2]) if len(sys.argv)>2 else None
o,res,inst,phys,alg=run(case,int(sys.argv[3]) if len(sys.argv)>3 else 1000,None,ao)
s=res.stats
print(o['cost'],o['share'],'iters',s.iterations,dict(s.eval_by_reason))
print('destroy',s.destroy_used,'repair',s.repair_used)
print('trace',[(a,round(b,1)) for a,b,c in s.best_trace])
