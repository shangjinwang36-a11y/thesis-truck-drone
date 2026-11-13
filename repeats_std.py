import csv,json,statistics as st,sys,math
from scipy.stats import t as T
def new(dirs):
    data={}
    for d in dirs:
        for r in csv.DictReader(open(d+'/episodes.csv',encoding='utf-8-sig')):
            for k in 'SX':
                if r['cost_'+k]: data.setdefault((r['case_id'],int(r['environment_seed']),k),[]).append(float(r['cost_'+k]))
    return data
def old(path):
    data={}
    for r in json.load(open(path)):
        if r['cost'] is not None: data.setdefault((r['case'],r['env'],r['strategy']),[]).append(r['cost'])
    return data
def rep(data,name):
    sds=[st.stdev(v) for v in data.values() if len(v)==3]
    print(name,'n_groups',len(sds),'mean std',round(st.mean(sds),3),'median',round(st.median(sds),3),'max',round(max(sds),3))
    # env level delta mean over seeds
    envs={}
    for (c,e,k),v in data.items():
        if len(v)==3: envs.setdefault((c,e),{})[k]=st.mean(v)
    dl=[x['S']-x['X'] for x in envs.values() if 'S' in x and 'X' in x]
    n=len(dl);m=st.mean(dl);sd=st.stdev(dl);hw=T.ppf(.975,n-1)*sd/math.sqrt(n)
    print('   env-level delta n',n,'mean',round(m,3),'sd',round(sd,3),'CI',round(m-hw,3),round(m+hw,3))
rep(old('proj/outputs_summary/repeats1000/repeats.json'),'OLD 1000')
rep(new(['proj/outputs/fix1000','proj/outputs/fix1000_s20261112','proj/outputs/fix1000_s20261113']),'NEW 1000')
