import json, sys, statistics as st, math
from scipy import stats as sps
def tci(df):
    return sps.t.ppf(0.975, df)
def agg(path, label=''):
    R = json.load(open(path + '/results.json'))
    cases = ['C50','R50','RC50','C100','R100','RC100']
    out = {}
    def stat(rows):
        n_tot = len(rows)
        ok = [r for r in rows if r['status_S']=='COMPLETED_VERIFIED' and r['status_X']=='COMPLETED_VERIFIED']
        d = [r['cost_S']-r['cost_X'] for r in ok]
        o = dict(n_env=n_tot, n_ok=len(ok), n_invalid_S=sum(r['status_S']!='COMPLETED_VERIFIED' for r in rows),
                 n_invalid_X=sum(r['status_X']!='COMPLETED_VERIFIED' for r in rows))
        if len(d) >= 2:
            m = st.mean(d); sd = st.stdev(d); hw = tci(len(d)-1)*sd/math.sqrt(len(d))
            o.update(mean=m, sd=sd, lo=m-hw, hi=m+hw)
        elif d:
            o.update(mean=d[0], sd=0, lo=d[0], hi=d[0])
        o['X_better'] = sum(1 for x in d if x > 1e-6); o['same'] = sum(1 for x in d if abs(x) <= 1e-6)
        o['X_worse'] = sum(1 for x in d if x < -1e-6)
        o['mean_S'] = st.mean([r['cost_S'] for r in ok]) if ok else None
        o['mean_X'] = st.mean([r['cost_X'] for r in ok]) if ok else None
        o['nf_mean'] = st.mean([r['nfail_X'] for r in rows if r.get('nfail_X') is not None]) if rows else None
        nR = sum(r['n_R_X'] for r in rows); nC = sum(r['n_cross_X'] for r in rows)
        nF = sum(r['nfail_X'] or 0 for r in rows)
        o['X_R'] = nR; o['X_cross'] = nC; o['X_cross_share_of_R'] = nC / nR if nR else None
        o['X_fail_events'] = nF; o['X_cross_per_fail'] = nC / nF if nF else None
        o['S_cross'] = sum(r['n_cross_S'] for r in rows)
        # restrict to envs with >=1 failure
        dd = [r['cost_S']-r['cost_X'] for r in ok if (r['nfail_X'] or 0) >= 1]
        o['n_with_fail'] = len(dd)
        if len(dd) >= 2:
            m = st.mean(dd); sd = st.stdev(dd); hw = tci(len(dd)-1)*sd/math.sqrt(len(dd))
            o['mean_fail_only'] = m; o['sd_fail_only'] = sd; o['lo_fail_only'] = m-hw; o['hi_fail_only'] = m+hw
            o['X_better_f'] = sum(1 for x in dd if x > 1e-6); o['same_f'] = sum(1 for x in dd if abs(x)<=1e-6); o['X_worse_f'] = sum(1 for x in dd if x < -1e-6)
        return o
    for c in cases:
        rows = [r for r in R if r['case']==c]
        if rows:
            o = stat(rows); o['nominal_cost'] = rows[0]['nominal_cost']; o['nominal_air'] = rows[0]['nominal_air']; o['n_cust'] = rows[0]['n_cust']
            out[c] = o
    out['ALL'] = stat(R)
    return out
if __name__ == '__main__':
    o = agg(sys.argv[1])
    json.dump(o, open(sys.argv[1] + '/summary_r2.json', 'w'), indent=1)
    for c, v in o.items():
        f = lambda k, p=2: (f"{v[k]:.{p}f}" if v.get(k) is not None else '-')
        print(f"{c:6s} nom={f('nominal_cost',1)} air={v.get('nominal_air','-')}/{v.get('n_cust','-')} ok={v['n_ok']}/{v['n_env']} meanS={f('mean_S',1)} meanX={f('mean_X',1)} "
              f"Δ={f('mean',3)}±{f('sd',3)} CI[{f('lo',3)},{f('hi',3)}] X better/same/worse={v['X_better']}/{v['same']}/{v['X_worse']} "
              f"failΔ={f('mean_fail_only',3)} n={v['n_with_fail']} cross={v['X_cross']}/{v['X_R']}(fails {v['X_fail_events']}) S_cross={v['S_cross']}")
