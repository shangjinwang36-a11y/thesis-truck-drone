import io, json, sys, contextlib, os
sys.path.insert(0,'/workspace/thesis/exp')
import agg_r3
O='/workspace/thesis/proj/outputs/'
def tbl(name):
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf): agg_r3.show(name,O+name)
    return buf.getvalue()
def nom_table(tags, cases=('C50','R50','RC50','C100','R100','RC100')):
    lines=['| 名义解 | '+' | '.join(cases)+' |','|---|'+'---|'*len(cases)]
    for lab,tag in tags:
        cells=[]
        for c in cases:
            try:
                m=json.load(open(f'{O}{tag}/{c}/result.json'))
                n=50 if '50' in c else 100
                cells.append(f"{m['cost']:.1f} / {m['n_air_parcels']}票({100*m['n_air_parcels']/n:.0f}%) / {m['n_sorties']}航次 / 每航次{m['n_air_parcels']/max(1,m['n_sorties']):.1f}票 / 换电{int(m['cost_breakdown'].get('swaps',0))}")
            except Exception: cells.append('缺')
        lines.append(f'| {lab} | '+' | '.join(cells)+' |')
    return '\n'.join(lines)+'\n'
out=open('/workspace/thesis/exp/part_a_header.md').read()
out+='## A3. 主实验（6 算例×10 环境×S/X；MILP + roulette；恢复预算 1000）\n'
out+='### 名义预算 1000\n'+tbl('r3_main_nom1000')
out+='### 名义预算 5000\n'+tbl('r3_main_nom5000')
out+='''### 与 round2 对照（同口径 60 个环境）
| 设置 | round2 | 第三轮 |
|---|---|---|
| 名义1000：ALL Δ | 0.57±3.82 [-0.42,1.57]，X好/同/差 3/53/3，跨车 4/38 | 见上表 ALL 行 |
| 名义5000：ALL Δ | 1.57±7.71 [-0.43,3.58]，4/53/2，跨车 5/42 | 见上表 ALL 行 |
| 平均总成本 S/X（名义1000） | 483.5 / 482.9 | 466.3 / 465.6 |
| 平均总成本 S/X（名义5000） | 475.7 / 474.1 | 454.6 / 454.1 |
| STOPPED（名义1000/5000） | 各 1–2 个环境对 | S/X 合计 1/0 与 3/3 |
注：跨车"次/全部R"中全部 R 含名义计划里的回收；"失败"为有效失败事件数。
'''
out+='## A4. 强制失败敏感性（TestWorld，同一失败票集合给 S/X，6 个算例，10 个种子）\n'
for n in ('r3_forced3_nom1000','r3_forced5_nom1000','r3_forced3_nom5000','r3_forced5_nom5000'):
    out+='### '+n+'\n'+tbl(n)
out+='''round2 对照（仅 50 客户、名义1000）：M=3 ALL Δ=6.25±16.1 [0.24,12.27]，8/17/5，跨车 10/90，STOPPED 0/0；M=5 ALL Δ=7.90±24.3 [-1.34,17.14]，11/14/4，跨车 18/150，STOPPED 1/1。
'''
out+='## A5. 名义储备裕量（nominal_reserve_margin=0.03·E_cap）对 STOPPED 的影响（名义预算 1000）\n'
out+=nom_table([('margin=0','nominal_r3fd1000'),('margin=0.03','nominal_r3m03')])
out+='### 主实验\n'+tbl('r3m_main')
out+='### 强制 M=5（仅 50 客户算例）\n'+tbl('r3m_forced5')
if os.path.exists('/workspace/thesis/exp/part_b.md'): out+=open('/workspace/thesis/exp/part_b.md').read()
open('/workspace/thesis/changes_round3.md','w').write(out)
print(len(out))
