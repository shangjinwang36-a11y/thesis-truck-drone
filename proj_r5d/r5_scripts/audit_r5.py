"""第五轮审计与汇总: python audit_r5.py results/NAME.json [p]"""
import json, sys, math, statistics as st
from collections import defaultdict
sys.path.insert(0, '/workspace/thesis/r5')
from agg_r5 import agg, ok

def summarize(path, p=None):
    d = json.load(open(path)); runs = d['runs']
    print(f'## {path}  (runs={len(runs)})')
    print('env  n pair  Δmean±sd  ±CI95  Δ/C_S%  better/same/worse  stopS/stopX  air%S/X  crossX%(nfail)  fails/env  failrate(obs/attempt) ')
    for o in agg(path):
        rs = [r for r in runs if o['env'] == 'ALL' or r['case'] == o['env']]
        pair = [r for r in rs if ok(r['S']) and ok(r['X'])]
        nf = [r['S'].get('n_obs_fail', 0) for r in rs if 'n_obs_fail' in r['S']]
        na = sum(r['S'].get('n_obs_air', 0) for r in rs); nfs = sum(r['S'].get('n_obs_fail', 0) for r in rs)
        print(f"{o['env']:4s} {o['n']:3d} {o['npair']:3d} {o['dmean']:6.2f}±{o['dsd']:5.2f} {o['ci95']:5.2f} {o['rel_pct']:6.2f} {o['better']}/{o['same']}/{o['worse']} "
              f"{o['stopS']}/{o['stopX']} {o['airS']:.1f}/{o['airX']:.1f} {o['crossX']:5.1f}({o['nfX']}) {st.mean(nf) if nf else float('nan'):5.2f} {nfs}/{na}={nfs/max(1,na):.3f}")
    # 失败生成核对: S 与 X 的观察失败集合是否一致(同环境同失败标记)，及数量与 p
    mism = [(r['case'], r['seed'], r['S'].get('n_configured_fail'), r['X'].get('n_configured_fail')) for r in runs
            if r['S'].get('n_configured_fail') != r['X'].get('n_configured_fail')]
    print('configured_fail S!=X:', mism)
    if p is not None:
        cf = sum(r['S'].get('n_configured_fail', 0) for r in runs); ncust = sum(r['n_cust'] for r in runs)
        print(f'标记失败(全部客户) {cf}/{ncust}={cf/max(1,ncust):.3f} 目标 p={p}')
    # X 是否系统性不劣于 S
    pair = [r for r in runs if ok(r['S']) and ok(r['X'])]
    dl = [r['S']['cost'] - r['X']['cost'] for r in pair]
    worse = [(r['case'], r['seed'], round(r['S']['cost'] - r['X']['cost'], 2)) for r in pair if r['S']['cost'] - r['X']['cost'] < -1e-6]
    print(f'X 更差 {len(worse)}/{len(pair)}: {worse}')
    if len(dl) > 1:
        # 符号检验
        b = sum(x > 1e-6 for x in dl); w = len(worse); n = b + w
        from math import comb
        pv = sum(comb(n, k) for k in range(max(b, w), n + 1)) * 2 / 2 ** n if n else 1
        print(f'符号检验(忽略平局): better={b} worse={w} 双侧p≈{min(1,pv):.4f}')
    # 算子审计 (S 与 X 分别汇总所有重规划)
    for strat in 'SX':
        agg_ops = defaultdict(int); tot_main = 0; tot_it = 0; noimp = 0; nrep = 0; stag = []; stops = defaultdict(int)
        by_reason = defaultdict(int); gap = []
        for r in runs:
            s = r[strat]
            for rp in s.get('replan_audit') or []:
                nrep += 1
                for k, v in (rp.get('audit') or {}).items():
                    agg_ops[k] += v
                tot_main += rp.get('main') or 0; tot_it += rp.get('it') or 0
                stops[rp.get('stop')] += 1
                for k, v in (rp.get('by_reason') or {}).items(): by_reason[k] += v
                if rp.get('init_cost') is not None and rp.get('final_cost') is not None:
                    gap.append(rp['init_cost'] - rp['final_cost'])
                    if rp['init_cost'] - rp['final_cost'] < 1e-6: noimp += 1
        print(f'-- 审计[{strat}] 重规划数={nrep} 主搜索评价={tot_main} ALNS迭代={tot_it} 停止原因={dict(stops)} 搜索无任何改进(init=final)的重规划={noimp}/{nrep}  平均patch_back={st.mean(gap) if gap else float("nan"):.3f}')
        print('   评价按用途:', dict(sorted(by_reason.items(), key=lambda x: -x[1])))
        for kind in ('D', 'R'):
            ops = sorted({k.split(':')[1] for k in agg_ops if k.startswith(kind + ':')})
            print(f'   {kind}-算子: calls / empty / leftover / geom_none / infeasible / new_best / cur_improve / sa_accept / rejected')
            for o in ops:
                g = lambda m: agg_ops.get(f'{kind}:{o}:{m}', 0)
                print(f'     {o:28s} {g("calls"):6d} {g("empty"):5d} {g("leftover"):6d} {g("geom_none"):6d} {g("infeasible"):6d} {g("new_best"):5d} {g("cur_improve"):5d} {g("sa_accept"):5d} {g("rejected"):6d}')
        print('   次级算子:', {k: v for k, v in agg_ops.items() if k.split(':')[0] in ('polish', 'reassign', 'local_reorder')})
if __name__ == '__main__':
    if not (len(sys.argv) > 2 and sys.argv[2] == 'event'): summarize(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else None)

def event_level(path):
    """同状态同事件的逐事件配对：对每个 (case,seed)，取 S/X 历史一致(此前各重规划 init_cost/final_cost 全相同)的重规划。
    这些事件的起点状态、失败包裹完全相同，Δ_event = S.final_cost - X.final_cost 只反映恢复决策/搜索差异，不含轨迹分叉噪声。"""
    d = json.load(open(path)); rows = []
    for r in d['runs']:
        rs, rx = r['S'].get('replan_audit') or [], r['X'].get('replan_audit') or []
        for k in range(min(len(rs), len(rx))):
            a, b = rs[k], rx[k]
            if a['init_cost'] is None or b['init_cost'] is None: break
            # 到达该事件时的起点状态一致 <=> 前一重规划(或名义)的 final_cost 相同
            if k > 0 and abs(rs[k-1]['final_cost'] - rx[k-1]['final_cost']) > 1e-6: break
            rows.append((r['case'], r['seed'], k + 1, a['final_cost'], b['final_cost'], a['init_cost'], b['init_cost']))
            if abs(a['final_cost'] - b['final_cost']) > 1e-6: break   # 此后轨迹分叉
    return rows

def show_event(path):
    rows = event_level(path)
    print(f'## 逐事件配对(同状态同事件) {path}: 事件数={len(rows)}')
    dl = [r[3] - r[4] for r in rows]; cs = [r[3] for r in rows]
    first = [r for r in rows if r[2] == 1]
    def rep(lbl, rr):
        d = [x[3] - x[4] for x in rr]
        if len(d) < 2: return
        m = st.mean(d); sd = st.stdev(d); ci = 1.96 * sd / math.sqrt(len(d))
        print(f'  {lbl}: n={len(d)} Δ_event均值={m:.3f}±{sd:.3f} (95%CI ±{ci:.3f}) Δ/C_S={100*sum(d)/sum(x[3] for x in rr):.3f}%  X好/同/差={sum(x>1e-6 for x in d)}/{sum(abs(x)<=1e-6 for x in d)}/{sum(x<-1e-6 for x in d)}')
    rep('全部同状态事件', rows); rep('其中第1次失败事件', first)
    for c in sorted({r[0] for r in rows}): rep(f'  {c}', [r for r in rows if r[0] == c])
if __name__ == '__main__' and len(sys.argv) > 2 and sys.argv[2] == 'event':
    show_event(sys.argv[1])
