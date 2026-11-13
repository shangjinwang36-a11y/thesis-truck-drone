import json,collections,sys
f=sys.argv[1]
R=collections.defaultdict(dict)
for l in open(f):
    r=json.loads(l)
    if 'error' in r: continue
    R[(r['case'],r['seed'])][r['strategy']]=r
tot=collections.defaultdict(list)
for (c,s),d in sorted(R.items()):
    if len(d)<2 or d['S']['final_cost'] is None or d['X']['final_cost'] is None: continue
    tot[c].append((d['S']['n_fail'],d['S']['final_cost']-d['X']['final_cost']))
for c,v in tot.items():
    nz=[round(b,1) for _,b in v if abs(b)>1e-6]
    print(c,'n',len(v),'with>=1 fail',sum(1 for a,_ in v if a>0),'S!=X',len(nz),'mean',round(sum(b for _,b in v)/len(v),2),nz)
