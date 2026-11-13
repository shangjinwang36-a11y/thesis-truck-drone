import json, sys, os, statistics as st
sys.path.insert(0,'/workspace/thesis/exp')
from agg import agg
from agg_r3 import stopped
O='/workspace/thesis/proj/outputs/'
CASES=['C50','R50','RC50','C100','R100','RC100']
def nominal_table(name, cases=CASES):
    print('##',name)
    print('| 算例 | 卡车数 | 名义成本 | 空送客户/总数(占比) | 空投趟数 | 包裹/趟 | 名义换电次数 | 空送包裹(result.json) | 卡车km | 时长H(s) |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for c in cases:
        p=O+name+'/'+c
        if not os.path.exists(p+'/result.json'): continue
        r=json.load(open(p+'/result.json')); k=json.load(open(p+'/cost.json'))
        cfg=json.load(open(p+'/config_snapshot.json'))['physical']
        n=int(c.lstrip('RC'))
        na=r['n_air_parcels']
        print(f"| {c} | {cfg['truck_count']} | {r['cost']:.1f} | {na}/{n} ({100*na/n:.0f}%) | {r['n_sorties']} | {na/r['n_sorties']:.2f} | {k['breakdown'].get('swaps')} | {na} | {r['distance_km']:.1f} | {r['H_s']:.0f} |")
    print()
def show(name, cases=CASES, extra=None):
    path=O+name
    R=json.load(open(path+'/results.json'))
    a=agg(path); s=stopped(path)
    print('##',name,f'(共{len(R)}条)')
    print('| 算例 | 名义成本 | 名义空送 | ok/总 | STOPPED S/X | 均值S | 均值X | Δ均值±sd | 95%CI | X好/同/差 | 跨车R/全部R | 失败总数(均/环境) | 有失败环境Δ均值(n) |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for c in cases+['ALL']:
        if c not in a or c not in s: continue
        v=a[c]; f=lambda k,p=2:(f"{v[k]:.{p}f}" if v.get(k) is not None else '-')
        nom=f"{v['nominal_cost']:.1f}" if c!='ALL' else '-'
        air=f"{100*v['nominal_air']/v['n_cust']:.0f}%" if c!='ALL' else '-'
        print(f"| {c} | {nom} | {air} | {v['n_ok']}/{v['n_env']} | {s[c][0]}/{s[c][1]} | {f('mean_S',1)} | {f('mean_X',1)} | {f('mean')}±{f('sd')} | [{f('lo')}, {f('hi')}] | {v['X_better']}/{v['same']}/{v['X_worse']} | {v['X_cross']}/{v['X_R']} | {v['X_fail_events']} ({f('nf_mean')}) | {f('mean_fail_only')} (n={v['n_with_fail']}) |")
    stat=set()
    for r in R: stat|={r['status_S'],r['status_X']}
    print('状态集合:',sorted(stat)); print()
if __name__=='__main__':
    for n in ['nominal_light1000','nominal_light5000','nominal_light7_1000','nominal_light7_5000','nominal_light1000_k5','nominal_light5000_k5']:
        nominal_table(n)
    for n in ['lt_main_nom1000','lt_forced3_nom1000','lt_forced5_nom1000']: show(n)
    show('lt_main7_nom1000',['C100','R100','RC100'])
    show('r3m_forced5')
