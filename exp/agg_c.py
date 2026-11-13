import json, sys, statistics as st, collections
sys.path.insert(0,'/workspace/thesis/exp')
from agg import agg
from agg_r3 import stopped
from scipy import stats as sps
import math
O='/workspace/thesis/proj/outputs/'
CASES=['C50','R50','RC50','C100','R100','RC100']
def load(name): return json.load(open(O+name+'/results.json'))
def ok(r): return r['status_S']=='COMPLETED_VERIFIED' and r['status_X']=='COMPLETED_VERIFIED'
def mean_pair(rows,key):
    a=[(r[key+'_S'],r[key+'_X']) for r in rows if ok(r) and r.get(key+'_S') is not None and r.get(key+'_X') is not None]
    if not a: return None
    return st.mean(x for x,_ in a), st.mean(y for _,y in a), len(a)
def fmt(v,p=1): return '-' if v is None else f'{v:.{p}f}'
def main_table(name,cases=CASES):
    R=load(name); a=agg(O+name); s=stopped(O+name)
    out=[f'## {name} (共{len(R)}条)',
         '| 算例 | 名义成本 | 名义空送 | ok/总 | STOPPED S/X | 均值S | 均值X | Δ均值±sd | 95%CI | X好/同/差 | 跨车R/全部R | 失败总数(均/环境) |','|---|---|---|---|---|---|---|---|---|---|---|---|']
    for c in cases+['ALL']:
        if c not in a or c not in s: continue
        v=a[c]; f=lambda k,p=2:(f"{v[k]:.{p}f}" if v.get(k) is not None else '-')
        nom=f"{v['nominal_cost']:.1f}" if c!='ALL' else '-'; air=f"{100*v['nominal_air']/v['n_cust']:.0f}%" if c!='ALL' else '-'
        out.append(f"| {c} | {nom} | {air} | {v['n_ok']}/{v['n_env']} | {s[c][0]}/{s[c][1]} | {f('mean_S',1)} | {f('mean_X',1)} | {f('mean')}±{f('sd')} | [{f('lo')}, {f('hi')}] | {v['X_better']}/{v['same']}/{v['X_worse']} | {v['X_cross']}/{v['X_R']} | {v['X_fail_events']} ({f('nf_mean')}) |")
    return '\n'.join(out)+'\n'
def metric_table(name,cases=CASES):
    R=load(name)
    out=[f'### {name}：服务/时间指标（仅 S、X 都 COMPLETED 的环境对；括号为 n）',
         '| 算例 | 失败包裹时延 S/X (s) | 时延 Δ(S−X) | makespan S/X (s) | z(无人机最晚入库) S/X (s) | 工时和 S/X (s) | 换电次数 S/X |','|---|---|---|---|---|---|---|']
    for c in cases+['ALL']:
        rows=[r for r in R if (c=='ALL' or r['case']==c)]
        d=mean_pair(rows,'failed_delivery_delay_mean_s'); mk=mean_pair(rows,'makespan_s'); z=mean_pair(rows,'z_s_metric')
        dr=mean_pair(rows,'driver_total_s'); sw=mean_pair(rows,'n_swaps')
        if mk is None: continue
        def two(t,p=1): return '-' if t is None else f"{t[0]:.{p}f}/{t[1]:.{p}f}"
        dd='-' if d is None else f"{d[0]-d[1]:+.1f} (n={d[2]})"
        out.append(f"| {c} | {two(d)} | {dd} | {two(mk)} | {two(z)} | {two(dr)} | {two(sw,2)} |")
    return '\n'.join(out)+'\n'
def stop_reasons(name):
    R=load(name); c=collections.Counter()
    import re
    for r in R:
        for s in 'SX':
            if r['status_'+s]!='COMPLETED_VERIFIED':
                t=' '.join(map(str,r.get('notes_'+s) or [])) + ' ' + str(r.get('stop_reason_'+s))
                kinds=[]
                if 'SWAP_CANNOT_FIX' in t:
                    # 负电量(已无法飞到)还是 R 余电不足
                    kinds.append('SWAP_CANNOT_FIX')
                for k in ('CHARGE_LP','H_EXCEEDED','RESIDUAL_NOT_AVAILABLE','NO_FRAGMENT','MAX_REPLANS','载荷'):
                    if k in t: kinds.append(k)
                c[('+'.join(kinds) or ('无记录' if not r.get('notes_'+s) else 'other'))]+=1
    return c
if __name__=='__main__':
    for n in sys.argv[1:]:
        print(main_table(n) if 'main7' not in n else main_table(n,['C100','R100','RC100']))
        print(metric_table(n) if 'main7' not in n else metric_table(n,['C100','R100','RC100']))
        print('STOPPED 原因分布(S+X 条数):',dict(stop_reasons(n)),'\n')
