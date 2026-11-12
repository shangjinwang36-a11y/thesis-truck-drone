"""汇总：合并多个 pipeline json，输出 agg_r6 的表 + 符号检验(双侧精确) + 停止原因。用法: agg_r6b.py out_pooled.json in1.json in2.json ..."""
import json, sys, math
sys.path.insert(0,'r6')
import agg_r6
def sign_p(b,w):
    n=b+w
    if n==0: return float('nan')
    k=min(b,w); p=sum(math.comb(n,i) for i in range(0,k+1))/2**n*2
    return min(1.0,p)
out=sys.argv[1]; runs=[]
for p in sys.argv[2:]: runs+=json.load(open(p))['runs']
json.dump({'runs':runs},open(out,'w'))
agg_r6.show(out)
ok=lambda r:r['status'].startswith('COMPLETED')
pair=[r for r in runs if ok(r['S']) and ok(r['X'])]
d=[r['S']['cost']-r['X']['cost'] for r in pair]
b=sum(x>1e-6 for x in d); w=sum(x<-1e-6 for x in d)
print(f"sign test: better={b} worse={w} p={sign_p(b,w):.4f}  (n_pair={len(pair)}/{len(runs)})")
from collections import Counter
for s in 'SX':
    c=Counter(r[s]['status'] for r in runs if not ok(r[s])); print('STOPPED',s,dict(c))
