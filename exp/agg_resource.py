import sys, json
sys.path.insert(0,'/workspace/thesis/exp')
from agg import agg
from agg_r3 import stopped
import agg_c
O='/workspace/thesis/proj/outputs/'
LEVELS=[  # (标签, main目录, forced3目录)
 ('原规范 1机/车 重型 充电 (round3b代码, 名义无裕量)','res_spec_main','res_spec_forced3'),
 ('轻型 1机/车 换电','res_L1_main','res_L1_forced3'),
 ('轻型 2机/车 换电','ltD_main_nom1000','ltD_forced3_nom1000'),
 ('轻型 2机/车 车载充电','res_Lchg_main','res_Lchg_forced3'),
]
def row(label,name):
    try: a=agg(O+name); s=stopped(O+name)
    except Exception as e: return f'| {label} | {name} | (缺失 {e!r}) |'
    v=a['ALL']; f=lambda k,p=2:(f"{v[k]:.{p}f}" if v.get(k) is not None else '-')
    air=sum(a[c]['nominal_air'] for c in a if c!='ALL'); n=sum(a[c]['n_cust'] for c in a if c!='ALL')
    pc=sum(1 for c in agg_c.CASES if c in a)
    mp=agg_c.mean_pair(agg_c.load(name),'failed_delivery_delay_mean_s')
    d='-' if mp is None else f"{mp[0]:.0f}/{mp[1]:.0f}"
    return (f"| {label} | {name} | {100*air/n:.0f}% | {v['n_ok']}/{v['n_env']} | {s['ALL'][0]}/{s['ALL'][1]} | {f('mean')}±{f('sd')} | [{f('lo')}, {f('hi')}] | "
            f"{v['X_better']}/{v['same']}/{v['X_worse']} | {v['X_cross']}/{v['X_R']} ({100*v['X_cross']/max(1,v['X_R']):.1f}%) | {d} |")
for title,idx in (('主实验（名义失败由环境抽样）',1),('强制失败 M=3',2)):
    print('###',title)
    print('| 资源水平 | 结果目录 | 名义空送占比 | ok/总 | STOPPED S/X | Δ(S−X)均值±sd | 95%CI | X好/同/差 | X跨车R/全部R | 失败包裹时延 S/X(s) |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for L in LEVELS: print(row(L[0],L[idx]))
    print()
