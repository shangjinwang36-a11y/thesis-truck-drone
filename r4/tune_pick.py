"""调参选择：按 S、X 成本的平均值（不看 Δ）选最优；只比较所有设置下 S、X 都 COMPLETED 的公共环境."""
import json, sys, statistics as st, math
def ok(r): return r['status'].startswith('COMPLETED')
files = sys.argv[1:]
D = {}
for f in files:
    d = json.load(open(f)); D[f] = {(r['case'], r['seed']): r for r in d['runs']}
common = set.intersection(*[{k for k, r in v.items() if ok(r['S']) and ok(r['X'])} for v in D.values()])
print(f'公共环境数 {len(common)}')
print('文件 | 完成对数/总 | 公共环境 mean(S,X)成本 | S均 | X均 | Δ均(参考，不用于选择) | 评价数S/X')
rows = []
for f, v in D.items():
    n_ok = sum(1 for r in v.values() if ok(r['S']) and ok(r['X']))
    cs = [v[k]['S']['cost'] for k in common]; cx = [v[k]['X']['cost'] for k in common]
    m = (st.mean(cs) + st.mean(cx)) / 2
    ev = lambda s: st.mean([v[k][s].get('n_evals') or 0 for k in common])
    rows.append((m, f, n_ok, len(v), st.mean(cs), st.mean(cx), st.mean(cs) - st.mean(cx), ev('S'), ev('X')))
for m, f, a, b, s, x, dl, es, ex in sorted(rows):
    print(f'{f.split("/")[-1]:28s} {a}/{b}  mean={m:.3f}  S={s:.3f} X={x:.3f}  Δ={dl:.3f}  evals {es:.0f}/{ex:.0f}')
