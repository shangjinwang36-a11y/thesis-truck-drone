import sys, json, statistics as st, math
sys.path.insert(0,'/workspace/thesis/r5')
from agg_r5 import agg, ok
from audit_r5 import event_level
def md(path, label, p=None, seeds=None):
    d=json.load(open(path)); runs=[r for r in d['runs'] if seeds is None or r['seed'] in seeds]
    json.dump(dict(meta=d['meta'],runs=runs),open('/tmp/_rep.json','w'))
    out=[f'#### {label}（{len(runs)} 运行，来源 `{path.split("/")[-1]}`）','| 算例 | 配对/总 | Δ均值±sd | 95%CI | Δ/C_S | X好/同/差 | STOPPED S/X | 空送% S/X | 跨车占比X(失败恢复数) |','|---|---|---|---|---|---|---|---|---|']
    for o in agg('/tmp/_rep.json'):
        out.append(f"| {o['env']} | {o['npair']}/{o['n']} | {o['dmean']:.2f}±{o['dsd']:.2f} | ±{o['ci95']:.2f} | {o['rel_pct']:.2f}% | {o['better']}/{o['same']}/{o['worse']} | {o['stopS']}/{o['stopX']} | {o['airS']:.1f}/{o['airX']:.1f} | {o['crossX']:.1f}%({o['nfX']}) |")
    nf=[r['S']['n_obs_fail'] for r in runs if 'n_obs_fail' in r['S']]; na=sum(r['S']['n_obs_air'] for r in runs); nfs=sum(r['S']['n_obs_fail'] for r in runs)
    cf=sum(r['S']['n_configured_fail'] for r in runs); nc=sum(r['n_cust'] for r in runs)
    out.append(f"失败/环境(S 侧)={st.mean(nf):.2f}；到达后失败率 {nfs}/{na}={nfs/max(1,na):.3f}；标记失败 {cf}/{nc}={cf/nc:.3f}（目标 p={p}）；S/X 标记不一致 {sum(r['S']['n_configured_fail']!=r['X']['n_configured_fail'] for r in runs)} 例。")
    pair=[r for r in runs if ok(r['S']) and ok(r['X'])]; dl=[r['S']['cost']-r['X']['cost'] for r in pair]
    b=sum(x>1e-6 for x in dl); w=sum(x<-1e-6 for x in dl); n=b+w
    from math import comb
    pv=min(1,2*sum(comb(n,k) for k in range(max(b,w),n+1))/2**n) if n else 1
    out.append(f"符号检验：X好 {b} / X差 {w}，双侧 p≈{pv:.3f}。")
    json.dump(dict(meta=d['meta'],runs=runs),open('/tmp/_rep.json','w'))
    rows=event_level('/tmp/_rep.json'); 
    def ev(lbl,rr):
        dd=[x[3]-x[4] for x in rr]
        if len(dd)<2: return
        sd=st.stdev(dd); out.append(f"逐事件配对[{lbl}]：n={len(dd)}，Δ_event={st.mean(dd):.3f}±{sd:.3f}（95%CI ±{1.96*sd/math.sqrt(len(dd)):.3f}），Δ/C_S={100*sum(dd)/sum(x[3] for x in rr):.3f}%，X好/同/差={sum(x>1e-6 for x in dd)}/{sum(abs(x)<=1e-6 for x in dd)}/{sum(x<-1e-6 for x in dd)}")
    ev('全部同状态事件',rows); ev('第1次失败',[r for r in rows if r[2]==1])
    return '\n'.join(out)
if __name__=='__main__':
    print(md(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv)>3 else None))
