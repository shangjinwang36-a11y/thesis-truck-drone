import csv, statistics as st, math, json
from scipy import stats as sps
srcs = {'box_fixed1000': '/workspace/thesis/proj/outputs_summary/fixed1000/episodes.csv',
        'box_B1000(MILP)': '/workspace/thesis/proj/outputs/B1000/summary.json',
        'cursor_formal': '/workspace/thesis/diag/cursor/formal/episodes.csv'}
import os
def rows_of(p):
    if p.endswith('.csv'): return list(csv.DictReader(open(p, encoding='utf-8-sig')))
    d = os.path.dirname(p) + '/episodes.csv'
    return list(csv.DictReader(open(d, encoding='utf-8-sig'))) if os.path.exists(d) else []
for k, p in srcs.items():
    R = rows_of(p)
    print('==', k, len(R))
    for c in ['C50','R50','RC50','C100','R100','RC100','ALL']:
        sub = [r for r in R if (c == 'ALL' or r['case_id'] == c) and r['status_S']=='COMPLETED_VERIFIED' and r['status_X']=='COMPLETED_VERIFIED' and r['cost_S'] not in ('', 'None')]
        if not sub: continue
        d = [float(r['cost_S'])-float(r['cost_X']) for r in sub]
        m = st.mean(d); sd = st.stdev(d) if len(d)>1 else 0; hw = sps.t.ppf(.975, len(d)-1)*sd/math.sqrt(len(d)) if len(d)>1 else 0
        print(f"{c:6s} n={len(sub)} meanS={st.mean(float(r['cost_S']) for r in sub):.1f} meanX={st.mean(float(r['cost_X']) for r in sub):.1f} Δ={m:.3f}±{sd:.3f} CI[{m-hw:.3f},{m+hw:.3f}] X+/0/-={sum(x>1e-6 for x in d)}/{sum(abs(x)<=1e-6 for x in d)}/{sum(x<-1e-6 for x in d)}")
