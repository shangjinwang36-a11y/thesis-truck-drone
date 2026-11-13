import sys,json,time
sys.path.insert(0,'/workspace/thesis/diag')
from drv2 import *
if __name__=='__main__':
    case=sys.argv[1]; b=int(sys.argv[2]); ao=json.loads(sys.argv[3]) if len(sys.argv)>3 else None
    o,res,inst,phys,alg=run(case,b,None,ao)
    s=res.stats
    print(json.dumps(dict(case=case,b=b,ao=ao,cost=o['cost'],air=o['air'],share=o['share'],sorties=o['sorties'],iters=s.iterations,conv=s.counts.get('n_conversion_evals'),wall=o['wall'])),flush=True)
