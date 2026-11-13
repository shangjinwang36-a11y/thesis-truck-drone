import json, sys, collections
sys.path.insert(0,'/workspace/thesis/exp')
from agg import agg
O='/workspace/thesis/proj/outputs/'
CASES=['C50','R50','RC50','C100','R100','RC100','ALL']
def stopped(path):
    R=json.load(open(path+'/results.json'))
    out={}
    for c in CASES:
        rows=[r for r in R if c=='ALL' or r['case']==c]
        if not rows: continue
        out[c]=(sum(r['status_S']!='COMPLETED_VERIFIED' for r in rows), sum(r['status_X']!='COMPLETED_VERIFIED' for r in rows), len(rows),
                sorted(set(r['status_S'] for r in rows)|set(r['status_X'] for r in rows)))
    return out
def show(name,path):
    try: a=agg(path); s=stopped(path)
    except Exception as e:
        print('##',name,'MISSING',e); return
    print('##',name,'(部分完成)' if len(json.load(open(path+'/results.json')))<(60 if 'r3m_forced5' not in name else 30) else '')
    print('| 算例 | 名义成本 | 名义空送 | 环境对 ok/总 | STOPPED S/X | 平均成本S | 平均成本X | Δ均值±sd | 95%CI | X好/同/差 | 跨车R/全部R(失败数) |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    for c in [c for c in CASES if c in a]:
        v=a[c]
        f=lambda k,p=2:(f"{v[k]:.{p}f}" if v.get(k) is not None else '-')
        air=f"{v['nominal_air']}/{v['n_cust']} ({100*v['nominal_air']/v['n_cust']:.0f}%)" if c!='ALL' else '-'
        nom=f"{v['nominal_cost']:.1f}" if c!='ALL' else '-'
        print(f"| {c} | {nom} | {air} | {v['n_ok']}/{v['n_env']} | {s[c][0]}/{s[c][1]} | {f('mean_S',1)} | {f('mean_X',1)} | {f('mean',2)}±{f('sd',2)} | [{f('lo',2)}, {f('hi',2)}] | {v['X_better']}/{v['same']}/{v['X_worse']} | {v['X_cross']}/{v['X_R']} (失败{v['X_fail_events']}) |")
    print()
if __name__=='__main__':
    for a in sys.argv[1:]:
        show(a, O+a)
