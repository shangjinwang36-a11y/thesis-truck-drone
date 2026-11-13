import json, math, statistics as st, sys
from scipy import stats as sps
O='/workspace/thesis/proj/outputs/'
CASES=['C50','R50','RC50','C100','R100','RC100','C200','R200','RC200']
def ci(d):
    if len(d)<2: return (None,None)
    m=st.mean(d); h=sps.t.ppf(.975,len(d)-1)*st.stdev(d)/math.sqrt(len(d)); return (m-h,m+h)
def pct(x): return '-' if x is None else f'{x:.2f}'
def block(name):
    R=json.load(open(O+name+'/results.json'))
    ok=[r for r in R if r['status_S']=='COMPLETED_VERIFIED' and r['status_X']=='COMPLETED_VERIFIED']
    def line(label,rows):
        if not rows: return f'| {label} | 0 | - | - | - | - |'
        d=[r['cost_S']-r['cost_X'] for r in rows]; rel=[100*(r['cost_S']-r['cost_X'])/r['cost_S'] for r in rows]
        lo,hi=ci(rel)
        return f"| {label} | {len(rows)} | {st.mean(d):.2f} | {st.mean(rel):.3f}% | {('[%.3f%%, %.3f%%]'%(lo,hi)) if lo is not None else '-'} | {100*sum(d)/sum(r['cost_S'] for r in rows):.3f}% |"
    print(f'#### {name}（相对节省 = (C_S−C_X)/C_S，成对环境）')
    print('| 范围 | n对 | Δ均值(元) | 相对节省均值 | 相对节省95%CI | 合计Δ/合计C_S |')
    print('|---|---|---|---|---|---|')
    for c in CASES:
        rows=[r for r in ok if r['case']==c]
        if rows or any(r['case']==c for r in R): print(line(c,rows))
    print(line('ALL',ok))
    cr=[r for r in ok if (r.get('n_cross_X') or 0)>0]
    print(line('ALL·仅 X 用过跨车接机的环境',cr))
    wf=[r for r in ok if (r.get('nfail_X') or 0)>0]
    print(line('ALL·仅发生≥1次失败的环境',wf))
    if cr:
        pe=[(r['cost_S']-r['cost_X'])/max(1,r['nfail_X']) for r in cr]
        pc=[(r['cost_S']-r['cost_X'])/r['n_cross_X'] for r in cr]
        pr=[100*(r['cost_S']-r['cost_X'])/r['cost_S']/max(1,r['nfail_X']) for r in cr]
        print(f"\n跨车环境 n={len(cr)}：每次失败事件平均 Δ={st.mean(pe):.2f} 元（=Δ/nfail_X），相对 C_S 每次失败 {st.mean(pr):.3f}%；每次跨车接机平均 Δ={st.mean(pc):.2f} 元；其中 X更好/同/差 = {sum(1 for r in cr if r['cost_S']-r['cost_X']>1e-6)}/{sum(1 for r in cr if abs(r['cost_S']-r['cost_X'])<=1e-6)}/{sum(1 for r in cr if r['cost_S']-r['cost_X']<-1e-6)}")
    else: print('\n无 X 跨车接机环境')
    print()
for n in sys.argv[1:]: block(n)
