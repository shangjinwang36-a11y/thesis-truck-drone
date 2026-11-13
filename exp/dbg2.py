import sys; sys.argv=[sys.argv[0]]+sys.argv[1:]
from dbg import *
from tdr import recovery, simulate as sim
import collections
orig=recovery._first_feasible
cnt=collections.Counter()
def patched(cands,inst,phys,state,H,stats,budget):
    r=orig(cands,inst,phys,state,H,stats,budget)
    for x in r[3]: cnt[x[:70]]+=1
    return r
recovery._first_feasible=patched
case,seed,forced,strat=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
inst,plan,phys,ep,failed=run(case,seed,forced,strat)
print(ep.status, ep.notes[:1])
for k,v in cnt.most_common(12): print(v,k)
for rp in ep.__dict__.get('replans',[])[:6]: print(rp)
