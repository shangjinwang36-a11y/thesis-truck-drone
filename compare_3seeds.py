import csv,math,statistics as st
from scipy.stats import t as T, wilcoxon
V={'round1':['fix1000','fix1000_s20261112','fix1000_s20261113'],'B':['B1000','B1000_s20261112','B1000_s20261113'],'A':['A1000','A1000_s20261112','A1000_s20261113']}
def load(dirs):
    d={}
    for p in dirs:
        for r in csv.DictReader(open(f'outputs/{p}/episodes.csv',encoding='utf-8-sig')):
            for k in 'SX':
                if r['cost_'+k]: d.setdefault((r['case_id'],int(r['environment_seed']),k),[]).append(float(r['cost_'+k]))
    return {k:v for k,v in d.items() if len(v)==3}
D={n:load(p) for n,p in V.items()}
def ci(x):
    n=len(x);m=st.mean(x);sd=st.stdev(x);hw=T.ppf(.975,n-1)*sd/math.sqrt(n);return n,m,sd,m-hw,m+hw
for n,d in D.items():
    sds=[st.stdev(v) for v in d.values()]
    envs={}
    for (c,e,k),v in d.items(): envs.setdefault((c,e),{})[k]=st.mean(v)
    dl=[x['S']-x['X'] for x in envs.values()]
    print(n,'groups',len(d),'mean cost S',round(st.mean(st.mean(v) for k,v in d.items() if k[2]=='S'),3),'X',round(st.mean(st.mean(v) for k,v in d.items() if k[2]=='X'),3),
      'mean within-env alg-seed std',round(st.mean(sds),3),'median',round(st.median(sds),3),'max',round(max(sds),3),'| env-level delta(S-X) n,mean,sd,lo,hi',[round(x,3) for x in ci(dl)])
for new in ('B','A'):
    for strat in ('S','X','all'):
        ks=[k for k in D['round1'] if k in D[new] and (strat=='all' or k[2]==strat)]
        df=[st.mean(D[new][k])-st.mean(D['round1'][k]) for k in ks]
        n,m,sd,lo,hi=ci(df)
        print(f"{new} vs round1 [{strat}] n={n} mean(new-old)={m:.3f} CI=({lo:.3f},{hi:.3f}) better/same/worse={sum(x<-1e-9 for x in df)}/{sum(abs(x)<=1e-9 for x in df)}/{sum(x>1e-9 for x in df)} wilcoxon_p={wilcoxon(df).pvalue:.3f}")
ks=[k for k in D['A'] if k in D['B']]
df=[st.mean(D['A'][k])-st.mean(D['B'][k]) for k in ks];n,m,sd,lo,hi=ci(df);print(f"A vs B [all] n={n} mean={m:.3f} CI=({lo:.3f},{hi:.3f})")
