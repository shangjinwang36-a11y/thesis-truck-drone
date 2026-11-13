import sys, json
from multiprocessing import Pool
from dbg import *
def one(t):
    case,seed,forced,strat=t
    try:
        inst,plan,phys,ep,failed=run(case,seed,forced,strat)
        return t,ep.status,[n[:160] for n in ep.notes[:2]]
    except Exception as e:
        return t,'EXC',[repr(e)[:200]]
if __name__=='__main__':
    forced=int(sys.argv[1]); src=sys.argv[2]
    R=json.load(open(src)); tasks=[]
    for r in R:
        for s in 'SX':
            if r['status_'+s]!='COMPLETED_VERIFIED': tasks.append((r['case'],r['seed'],forced,s))
    print(len(tasks),'tasks')
    with Pool(7) as p:
        res=p.map(one,tasks)
    import collections
    c=collections.Counter(r[1] for r in res); print(c)
    for t,st,n in sorted(res):
        if st!='COMPLETED_VERIFIED': print(t,st,n)
