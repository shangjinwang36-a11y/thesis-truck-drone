import subprocess, sys, os, glob, json, shlex
R = '/workspace/thesis/r4/'; RES = R + 'results/'
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=R).stdout
def sens(pairs):
    return sh('python3 agg_sens.py ' + ' '.join(shlex.quote(f'{n}={RES}{f}') for n, f in pairs))
# 最大差距榜单
sys.path.insert(0, R)
from agg_r4 import agg
board = []
for f in sorted(glob.glob(RES + 'sens_*.json')) + [RES + 'main_spec.json', RES + 'main_light1.json', RES + 'main_light2.json']:
    try:
        rows = agg(f)
    except Exception:
        continue
    n = os.path.basename(f)[:-5]
    for r in rows:
        if r['npair'] >= 5:
            board.append((r['rel_pct'], r['dmean'], n, r['env'], r['npair']))
board.sort(reverse=True)
top = '\n'.join(f'| {i+1} | {n} | {e} | {m:.2f} | {p:.2f}% | {k} |' for i, (p, m, n, e, k) in enumerate(board[:12]))
allrows = [b for b in board if b[3] == 'ALL']
top_all = '\n'.join(f'| {n} | {m:.2f} | {p:.2f}% |' for p, m, n, e, k in allrows[:8])
S = lambda name: open(R + 'report_parts/' + name).read() if os.path.exists(R + 'report_parts/' + name) else ''
out = []
out.append(S('00_summary.md'))
out.append('\n## 2. 修复的 bug 与证据\n' + S('10_bugs.md'))
out.append('\n## 3. 修复前后对比（主实验：6 算例×10 环境×S/X；Δ=C_S−C_X）\n' + S('20_before_after.md'))
out.append('\n## 4. X 专用跨车算子与消融\n' + S('30_operators.md'))
out.append('\n## 5. 算法参数调优与 CRN\n' + S('40_tuning.md'))
out.append('\n## 6. 模型敏感性（全部场景）\n' + S('50_sens_intro.md'))
out.append(S('51_sens_tables.md') if False else '')
out.append('\n### 6.1 原规范（重型机，1 架/车，车载充电）\n' + sens([('基线 失败1–2次·池=全部', 'main_spec.json'), ('H余量900', 'sens_spec_H900.json'), ('池=空送 1–2次', 'sens_spec_airM12.json'),
    ('池=空送 M=3', 'sens_spec_airM3.json'), ('池=全部 M=3', 'sens_spec_allM3.json'), ('池=空送 M=5', 'sens_spec_airM5.json'), ('池=全部 M=5', 'sens_spec_allM5.json')]))
out.append('\n### 6.2 轻型 1 机/车 换电（用户已将标准配置定为 light2，本组队列按指示中途停止，仅保留已完成场景）\n' + sens([('基线', 'main_light1.json'), ('H余量900', 'sens_light1_H900.json'), ('池=空送 1–2次', 'sens_light1_airM12.json'),
    ('池=空送 M=3', 'sens_light1_airM3.json'), ('池=全部 M=3', 'sens_light1_allM3.json'), ('池=空送 M=5', 'sens_light1_airM5.json'), ('池=全部 M=5', 'sens_light1_allM5.json')]))
out.append('\n### 6.3 轻型 2 机/车 换电（**标准配置**：3 槽、2 架/车、换电；50 客户 5 车，100 客户 8 车）\n' + sens([('基线', 'main_light2.json'), ('H余量900', 'sens_light2_H900.json'), ('池=空送 1–2次', 'sens_light2_airM12.json'),
    ('池=空送 M=3', 'sens_light2_airM3.json'), ('池=全部 M=3', 'sens_light2_allM3.json'), ('池=空送 M=5', 'sens_light2_airM5.json'), ('池=全部 M=5', 'sens_light2_allM5.json')]))
out.append('\n### 6.4 少车配置：按用户指示取消（未运行；`package_light_fewtrucks.json` 与名义解 `nominal_Lfew_1000` 已备好，需要时可跑）')
out.append('\n### 6.5 最大差距榜单（所有场景，含分算例行；配对数≥5）\n| # | 场景 | 算例 | Δ均值(元) | Δ/C_S | 配对数 |\n|---|---|---|---|---|---|\n' + top)
out.append('\n全场景合计行 Δ/C_S 排名前 8：\n\n| 场景 | Δ均值(元) | Δ/C_S |\n|---|---|---|\n' + top_all)
out.append('\n## 7. 事件级条件分析（条件统计，不是总体平均）\n' + S('60_event_intro.md'))
evs = [(n, f) for n, f in [('light2 基线(60环境)', 'ev_light2_main.json'), ('light2 池=空送 M=3(仅50客户算例，30环境)', 'ev_light2_airM3_50.json')] if os.path.exists(RES + f)]
if evs:
    out.append('\n```\n' + sh('python3 event_analysis.py ' + ' '.join(shlex.quote(f'{n.replace(" ", "_")}={RES}{f}') for n, f in evs)) + '\n```')
out.append('\n## 8. 对 5% 目标的结论\n' + S('70_conclusion.md'))
out.append('\n## 9. 论文建议配置与叙事\n' + S('80_paper.md'))
out.append('\n## 10. 文件与复现\n' + S('90_repro.md'))
open(R + 'morning_report.md', 'w').write('\n'.join(out))
print('written', os.path.getsize(R + 'morning_report.md'))
