import json, math, statistics as st, collections, sys
from scipy import stats as sps
O='/workspace/thesis/proj/outputs/'
def nomin(n):
    out={}
    for c in ['C200','R200','RC200']:
        r=json.load(open(O+f'nominal_gh200_{n}_1000/{c}/result.json')); out[c]=r
    return out
for n in ('L2','L1'):
    nm=nomin(n)
    print(f'### 名义解 {n}')
    for c,r in nm.items(): print(f"- {c}: cost={r['cost']:.1f}, 空送 {r['n_air_parcels']}/200 ({r['n_air_parcels']/2:.0f}%), 航次 {r['n_sorties']}, 名义运行 {r['wall_s']:.1f}s, 评价次数 {r['eval_requests']}, verified={r['verified']}, H={r['H_s']:.0f}s, 换电 {r['cost_breakdown']['swaps']}")
    for tag in ('main','forced3'):
        name=f'gh200_{n}_{tag}'; R=json.load(open(O+name+'/results.json'))
        print(f'\n### {name}: {len(R)} 环境')
        print('| 算例 | ok/总 | STOPPED S/X | meanS | meanX | Δ均值±sd | 95%CI | 相对节省均值 | X好/同/差 | 跨车R/全部R | 失败总数 | 单环境 S+X 耗时均值(s) |')
        print('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for c in ['C200','R200','RC200','ALL']:
            rows=[r for r in R if c=='ALL' or r['case']==c]
            ok=[r for r in rows if r['status_S']=='COMPLETED_VERIFIED' and r['status_X']=='COMPLETED_VERIFIED']
            d=[r['cost_S']-r['cost_X'] for r in ok]; rel=[100*x/r['cost_S'] for x,r in zip(d,ok)]
            if len(d)>=2:
                m=st.mean(d);sd=st.stdev(d);h=sps.t.ppf(.975,len(d)-1)*sd/math.sqrt(len(d)); ci=f'[{m-h:.2f}, {m+h:.2f}]'; ms=f'{m:.2f}±{sd:.2f}'
            else: ci='-'; ms=('%.2f'%d[0]) if d else '-'
            sS=sum(r['status_S']!='COMPLETED_VERIFIED' for r in rows); sX=sum(r['status_X']!='COMPLETED_VERIFIED' for r in rows)
            wall=st.mean([(r.get('wall_S') or 0)+(r.get('wall_X') or 0) for r in rows])
            print(f"| {c} | {len(ok)}/{len(rows)} | {sS}/{sX} | {st.mean([r['cost_S'] for r in ok]) if ok else float('nan'):.1f} | {st.mean([r['cost_X'] for r in ok]) if ok else float('nan'):.1f} | {ms} | {ci} | {st.mean(rel) if rel else float('nan'):.3f}% | {sum(x>1e-6 for x in d)}/{sum(abs(x)<=1e-6 for x in d)}/{sum(x<-1e-6 for x in d)} | {sum(r['n_cross_X'] or 0 for r in rows)}/{sum(r['n_R_X'] or 0 for r in rows)} | {sum(r['nfail_X'] or 0 for r in rows)} | {wall:.0f} |")
        cnt=collections.Counter()
        for r in R:
            for s in 'SX':
                if r['status_'+s]!='COMPLETED_VERIFIED':
                    nt=' '.join(r.get('notes_'+s) or [])
                    for k in ['NO_FRAGMENT','SWAP_CANNOT_FIX','H_EXCEEDED','RESIDUAL_NOT_AVAILABLE']:
                        if k in nt: cnt[k]+=1
                    cnt['_total_'+s]+=1
        print('STOPPED 原因计数(按 notes 关键词,一条可含多个):',dict(cnt))
        ws=[(r.get('wall_S') or 0, r.get('wall_X') or 0) for r in R]
        print(f'单个 episode 运行时间: S 均值 {st.mean(w[0] for w in ws):.0f}s 最大 {max(w[0] for w in ws):.0f}s；X 均值 {st.mean(w[1] for w in ws):.0f}s 最大 {max(w[1] for w in ws):.0f}s')
    print()
