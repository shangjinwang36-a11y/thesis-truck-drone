import csv,sys,math,statistics as st
from scipy.stats import t as T, wilcoxon
def load(d):
    out={}
    for r in csv.DictReader(open(d+'/episodes.csv',encoding='utf-8-sig')):
        for k in 'SX':
            if r['cost_'+k]: out[(r['case_id'],r['environment_seed'],k)]=float(r['cost_'+k])
    return out
base=load(sys.argv[1])
for d in sys.argv[2:]:
    v=load(d); keys=[k for k in base if k in v]
    for strat in ('S','X','all'):
        ks=[k for k in keys if strat=='all' or k[2]==strat]
        df=[v[k]-base[k] for k in ks]   # 负=新版更好
        n=len(df); m=sum(df)/n; sd=st.stdev(df); hw=T.ppf(.975,n-1)*sd/math.sqrt(n)
        try: p=wilcoxon(df).pvalue
        except Exception: p=float('nan')
        print(f"{d} vs {sys.argv[1]} [{strat}] n={n} mean(new-old)={m:.3f} sd={sd:.3f} CI=({m-hw:.3f},{m+hw:.3f}) better/same/worse={sum(x<-1e-9 for x in df)}/{sum(abs(x)<=1e-9 for x in df)}/{sum(x>1e-9 for x in df)} wilcoxon_p={p:.3f}")
