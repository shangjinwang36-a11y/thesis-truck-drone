import sys; sys.path.insert(0,'.')
from drv import *
o,res,inst,phys,alg=run('C50',1000)
s=res.stats
print(o['cost'],'iters',s.iterations,'evals',s.eval_requests,dict(s.eval_by_reason))
print('destroy',s.destroy_used,'repair',s.repair_used,'fallback',s.destroy_fallback)
print('trace',s.best_trace[:30])
