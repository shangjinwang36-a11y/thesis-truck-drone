import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
from agg_r4 import agg
def row(name, path):
    if not os.path.exists(path): return f'| {name} | (未完成) |'
    rows = agg(path); a = [r for r in rows if r['env'] == 'ALL'][0]
    if a['n'] < 60: name += ' ⚠进行中(%d/60)' % a['n']
    return (f"| {name} | {a['npair']}/{a['n']} | {a['stopS']}/{a['stopX']} | {a['airS']:.1f}/{a['airX']:.1f} | {a['crossX']:.1f}% ({a['nfX']}) | "
            f"{a['dmean']:.2f}±{a['dsd']:.2f} | [{a['dmean']-a['ci95']:.2f}, {a['dmean']+a['ci95']:.2f}] | {a['rel_pct']:.2f}% | {a['better']}/{a['same']}/{a['worse']} |")
def percase(name, path):
    rows = [r for r in agg(path) if r['env'] != 'ALL']
    return f"{name}: " + ', '.join(f"{r['env']} {r['dmean']:.1f}({r['rel_pct']:.2f}%)" for r in rows)
H = '| 场景 | 配对/总 | STOPPED S/X | 空送占比 S/X | 失败恢复跨车占比(X) | Δ均值±sd | 95%CI | Δ/C_S | X好/同/差 |\n|---|---|---|---|---|---|---|---|---|'
if __name__ == '__main__':
    print(H)
    for a in sys.argv[1:]:
        n, p = a.rsplit('=', 1); print(row(n, p))
    print()
    for a in sys.argv[1:]:
        n, p = a.rsplit('=', 1)
        if os.path.exists(p): print(percase(n, p))
