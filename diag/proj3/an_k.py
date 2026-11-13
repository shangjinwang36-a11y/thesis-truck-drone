import json,sys,collections
R=collections.defaultdict(dict)
for l in open(sys.argv[1]):
    r=json.loads(l)
    if r.get('final') is None: continue
    R[(r['nom'],r['case'],r['k'],r['seed'])][r['strategy']]=r
g=collections.defaultdict(list)
for (nom,c,k,s),d in R.items():
    if len(d)==2: g[(nom,c,k)].append((d['S']['final']-d['X']['final'],d['S']['n_replans'],d['S']['n_air']))
for key,v in sorted(g.items()):
    ds=[x[0] for x in v]
    print(key,'n',len(v),'mean S-X',round(sum(ds)/len(ds),2),'nonzero',sum(abs(x)>1e-6 for x in ds),'pos',sum(x>1e-6 for x in ds),'neg',sum(x<-1e-6 for x in ds),'mean|d|',round(sum(abs(x) for x in ds)/len(ds),2),'replans',round(sum(x[1] for x in v)/len(v),1),'nair',v[0][2])
