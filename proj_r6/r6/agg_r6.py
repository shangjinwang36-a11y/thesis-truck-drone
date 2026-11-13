import json, sys, statistics as st, math
def ok(r): return r['status'].startswith('COMPLETED')
def agg(path, label=None):
    d=json.load(open(path)); runs=d['runs']; out=[]
    envs=sorted({r['case'] for r in runs})
    for env in envs+['ALL']:
        rs=[r for r in runs if env=='ALL' or r['case']==env]
        n=len(rs)
        pair=[r for r in rs if ok(r['S']) and ok(r['X'])]
        dl=[r['S']['cost']-r['X']['cost'] for r in pair]
        cs=[r['S']['cost'] for r in pair]
        m=st.mean(dl) if dl else float('nan'); sd=st.stdev(dl) if len(dl)>1 else float('nan')
        ci=1.96*sd/math.sqrt(len(dl)) if len(dl)>1 else float('nan')
        rel=100*sum(dl)/sum(cs) if cs else float('nan')
        eps=1e-6
        bt=sum(x>eps for x in dl); sm=sum(abs(x)<=eps for x in dl); wr=sum(x<-eps for x in dl)
        stS=sum(not ok(r['S']) for r in rs); stX=sum(not ok(r['X']) for r in rs)
        resX=sum((not ok(r['S'])) and ok(r['X']) for r in rs); resS=sum(ok(r['S']) and not ok(r['X']) for r in rs)
        def sh(k):
            f=sum(r[k].get('n_fail_rec',0) for r in rs); c=sum(r[k].get('n_fail_cross',0) for r in rs)
            return (100*c/f if f else float('nan')), f
        airS=100*sum(r['S']['n_air_final'] for r in pair)/max(1,sum(r['n_cust'] for r in pair)) if pair else float('nan')
        airX=100*sum(r['X']['n_air_final'] for r in pair)/max(1,sum(r['n_cust'] for r in pair)) if pair else float('nan')
        dn=[r['S_nominal']['cost']-r['X_nominal']['cost'] for r in pair if 'S_nominal' in r]
        nomS=sum(r['S_nominal']['cost'] for r in pair) if pair else float('nan')
        rpS=[r['S']['cost']-r['S_nominal']['cost'] for r in pair]; rpX=[r['X']['cost']-r['X_nominal']['cost'] for r in pair]
        xcross_nom=sum(r['X_nominal']['n_cross'] for r in pair)/max(1,len(pair))
        out.append(dict(dnom=(st.mean(dn) if dn else float('nan')),dnom_rel=(100*sum(dn)/nomS if dn else float('nan')),rpS=(st.mean(rpS) if rpS else float('nan')),rpX=(st.mean(rpX) if rpX else float('nan')),xcross_nom=xcross_nom,env=env,n=n,npair=len(pair),dmean=m,dsd=sd,ci95=ci,rel_pct=rel,better=bt,same=sm,worse=wr,
            stopS=stS,stopX=stX,rescueX=resX,rescueS=resS,crossX=sh('X')[0],nfX=sh('X')[1],crossS=sh('S')[0],airS=airS,airX=airX))
    return out
def show(path):
    print('##',path)
    print('env  n pair  Δmean  sd  ±CI95  Δ/C_S%  better/same/worse  stopS/stopX  rescueX/rescueS  crossX%(nfail) crossS%  air%S/X  | Δnom(S-X) Δnom/C_nomS%  recov-cost S/X  nomCross(X)')
    for o in agg(path):
        print(f"{o['env']:4s} {o['n']:3d} {o['npair']:3d} {o['dmean']:7.3f} {o['dsd']:6.3f} {o['ci95']:6.3f} {o['rel_pct']:6.2f} "
              f"{o['better']}/{o['same']}/{o['worse']}  {o['stopS']}/{o['stopX']}  {o['rescueX']}/{o['rescueS']}  {o['crossX']:5.1f}({o['nfX']}) {o['crossS']:4.1f}  {o['airS']:.1f}/{o['airX']:.1f} | {o['dnom']:7.2f} {o['dnom_rel']:6.2f}  {o['rpS']:6.2f}/{o['rpX']:6.2f}  {o['xcross_nom']:.1f}")
if __name__=='__main__':
    for p in sys.argv[1:]: show(p)
