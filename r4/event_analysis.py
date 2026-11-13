"""事件级条件分析（明确为“条件”统计，不是总体平均）。
对每个失败事件：在 X 回合的同一状态上，另跑一次 S 的恢复（同预算、同参数），saving = 成本(S 恢复后全班计划) − 成本(X 恢复后)。
cross = X 在该事件选了“非原放飞车”接机。"""
import json, sys, statistics as st, math
def q(xs, p):
    xs = sorted(xs); 
    if not xs: return float('nan')
    k = (len(xs) - 1) * p; f = int(k); c = min(f + 1, len(xs) - 1); return xs[f] + (xs[c] - xs[f]) * (k - f)
def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r
def spearman(a, b):
    if len(a) < 4: return float('nan')
    ra, rb = rank(a), rank(b); ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)); den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float('nan')
def load(paths):
    runs = []
    for p in paths: runs += json.load(open(p))['runs']
    return runs
def events(runs):
    out = []
    for r in runs:
        for e in r['events']:
            if e.get('costX') is not None and e.get('costS') is not None and 'launch_truck' in e:
                e = dict(e); e['case'] = r['case']; e['seed'] = r['seed']; e['sav'] = e['costS'] - e['costX']; e['pct'] = 100 * e['sav'] / e['costS']
                e['init_sav'] = (e['initS'] - e['initX']) if e.get('initS') is not None and e.get('initX') is not None else None
                out.append(e)
    return out
def summarize(name, paths):
    runs = load(paths); ev = events(runs)
    nenv = len(runs); env_cross = sum(1 for r in runs if any(e.get('cross') for e in r['events']))
    env_fail = sum(1 for r in runs if r['events'])
    cr = [e for e in ev if e['cross']]; nc = [e for e in ev if not e['cross']]
    print(f'### {name}: 环境 {nenv}，有失败的 {env_fail}，含≥1 次跨车恢复的 {env_cross} ({100*env_cross/max(1,nenv):.0f}% 的环境)；事件 {len(ev)}（跨车 {len(cr)}，同车 {len(nc)}）')
    def line(lbl, E):
        if not E: print(f'| {lbl} | 0 | | | | | | |'); return
        s = [e['sav'] for e in E]; p = [e['pct'] for e in E]
        print(f"| {lbl} | {len(E)} | {st.mean(s):.2f} | {st.median(s):.2f} | {q(s,.9):.2f} | {max(s):.2f} | {st.mean(p):.2f}% | {max(p):.2f}% | {sum(x>1e-6 for x in s)}/{sum(abs(x)<=1e-6 for x in s)}/{sum(x<-1e-6 for x in s)} |")
    print('| 事件集 | n | 平均省(元) | 中位数 | P90 | 最大 | 平均省/C_S | 最大省/C_S | 省/同/亏 |\n|---|---|---|---|---|---|---|---|---|')
    line('X 选跨车的事件', cr); line('X 选同车的事件', nc); line('全部事件', ev)
    return ev
def features(name, ev):
    cr = [e for e in ev if e['cross']]
    print(f'#### 跨车事件特征 vs 节省（{name}，n={len(cr)}；Spearman 秩相关，|ρ|<0.2 视为无关）')
    print('| 特征 | ρ(与节省元) | ρ(与节省%) |\n|---|---|---|')
    for k, lbl in [('d_launch_to_fail', '原放飞车到失败点距离(m)'), ('d_rec_to_fail', '接机车到失败点距离(m)'), ('d_rec_point_from_fail', '接机点距失败点(m)'),
                   ('remaining_s', '剩余时间 H−t_fail (s)'), ('drone_energy_frac', '失败机放飞时电量比'), ('n_served', '该航次已排空送票数'), ('n_handover', '交接票数')]:
        xs = [(e[k], e['sav'], e['pct']) for e in cr if e.get(k) is not None]
        print(f'| {lbl} | {spearman([a for a,_,_ in xs],[b for _,b,_ in xs]):.2f} | {spearman([a for a,_,_ in xs],[c for _,_,c in xs]):.2f} |')
    if len(cr) >= 6:
        cs = sorted(cr, key=lambda e: -e['sav']); top = cs[:max(3, len(cs)//3)]; rest = cs[len(top):]
        print(f'\n节省最大的前 1/3（n={len(top)}）vs 其余（n={len(rest)}）特征均值：')
        print('| 特征 | 前1/3 | 其余 |\n|---|---|---|')
        for k, lbl in [('sav','节省(元)'),('pct','节省%'),('d_launch_to_fail', '放飞车→失败点(m)'), ('d_rec_to_fail', '接机车→失败点(m)'), ('remaining_s', '剩余时间(s)'), ('drone_energy_frac', '电量比'), ('n_served','空送票数'),('n_handover','交接票数')]:
            a = [e[k] for e in top if e.get(k) is not None]; b = [e[k] for e in rest if e.get(k) is not None]
            print(f'| {lbl} | {st.mean(a):.2f} | {st.mean(b):.2f} |')
        print('\n节省最大的 5 个事件：')
        for e in cs[:5]:
            print(f"- {e['case']} s{e['seed']}：省 {e['sav']:.1f} 元 ({e['pct']:.1f}%)，放飞车 {e['launch_truck']}→接机车 {e['rec_truck']}，放飞车距失败点 {e['d_launch_to_fail']:.0f} m，接机车距 {e['d_rec_to_fail']:.0f} m，剩余 {e['remaining_s']:.0f} s，电量比 {e['drone_energy_frac']:.2f}")
if __name__ == '__main__':
    groups = {}
    for a in sys.argv[1:]:
        n, ps = a.rsplit('=', 1); groups[n] = ps.split(',')
    allev = []
    for n, ps in groups.items():
        ev = summarize(n, ps); allev += ev; print()
    if len(groups) > 1:
        print('## 合并（所有配置）'); 
        allev_ = allev
        cr = [e for e in allev_ if e['cross']]
        s = [e['sav'] for e in cr]; p = [e['pct'] for e in cr]
        if cr:
            print(f"跨车事件 {len(cr)}：平均省 {st.mean(s):.2f} 元，中位数 {st.median(s):.2f}，P90 {q(s,.9):.2f}，最大 {max(s):.2f}；占该班 C_S 平均 {st.mean(p):.2f}%，最大 {max(p):.2f}%；节省>0/=0/<0 = {sum(x>1e-6 for x in s)}/{sum(abs(x)<=1e-6 for x in s)}/{sum(x<-1e-6 for x in s)}")
        features('合并', allev_)
