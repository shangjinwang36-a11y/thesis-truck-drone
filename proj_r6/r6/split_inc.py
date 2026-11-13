import json,sys,statistics as st
from collections import defaultdict
# 恢复段成本增量(完成运行的 cost − 该策略名义 cost)，按失败事件数分组，S/X 对照
files=sys.argv[1:]
g={'S':defaultdict(list),'X':defaultdict(list)}
for f in files:
    for r in json.load(open(f))['runs']:
        for s in 'SX':
            m=r.get(s); n=r.get(s+'_nominal')
            if not m or m.get('cost') is None or not n: continue
            k=min(m['n_fail_events'],4)
            g[s][k].append(m['cost']-n['cost'])
print('失败事件数 | S: n 均值增量/次失败 | X: n 均值增量/次失败')
for k in range(0,5):
    a=g['S'][k]; b=g['X'][k]
    if a or b: print(f"{k}{'+' if k==4 else ' '} | {len(a):3d} {st.mean(a) if a else float('nan'):7.2f} | {len(b):3d} {st.mean(b) if b else float('nan'):7.2f}")
