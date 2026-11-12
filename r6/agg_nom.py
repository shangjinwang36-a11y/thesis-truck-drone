import json, sys, statistics as st, math
from collections import defaultdict
tag = sys.argv[1]
rows = json.load(open(f'r6/nominal/{tag}/summary.json'))
by = defaultdict(dict)
for r in rows:
    if r.get('status') == 'FEASIBLE':
        by[(r['case_id'], r['seed'])][r['strat']] = r
print('## 名义解 S vs X (light2, 预算1000)  Δ=C_S−C_X')
print('case seed | C_S  C_X  Δ  Δ/C_S% | air%S/X | crossSorties X | verified S/X')
tot = []
percase = defaultdict(list)
for (case, seed), d in sorted(by.items()):
    if 'S' in d and 'X' in d:
        cs, cx = d['S']['cost'], d['X']['cost']; n = d['S']['n_cust']
        print(f"{case:5s} {seed:9d} | {cs:8.2f} {cx:8.2f} {cs-cx:7.2f} {100*(cs-cx)/cs:6.2f} | {100*d['S']['n_air_parcels']/n:4.1f}/{100*d['X']['n_air_parcels']/n:4.1f} | {d['X']['n_cross_sorties']:2d}/{d['X']['n_sorties']:2d} | {d['S']['verified']}/{d['X']['verified']}")
        tot.append((cs, cx)); percase[case].append((cs, cx))
print('\n每算例(跨算法种子均值)')
for c, l in percase.items():
    ds = [a - b for a, b in l]
    print(f"{c:5s} n={len(l)} meanΔ={st.mean(ds):7.2f} Δ/C_S={100*sum(ds)/sum(a for a,_ in l):5.2f}% worse={sum(x<0 for x in ds)}")
ds = [a - b for a, b in tot]
print(f"ALL n={len(ds)} meanΔ={st.mean(ds):.2f} sd={st.stdev(ds):.2f} ±CI95={1.96*st.stdev(ds)/math.sqrt(len(ds)):.2f} Δ/C_S={100*sum(ds)/sum(a for a,_ in tot):.2f}% better/worse={sum(x>1e-6 for x in ds)}/{sum(x<-1e-6 for x in ds)}")
