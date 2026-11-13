import json,sys,collections
rows=[json.loads(l) for l in open(sys.argv[1])]
ev=[r for r in rows if 'per_truck' in r]
err=[r for r in rows if 'error' in r]
print('rows',len(rows),'events',len(ev),'errors',len(err),'no-failure',len(rows)-len(ev)-len(err))
gaps=[]
for r in ev:
    pt=r['per_truck']; L=r['launch']
    cl=pt[L]['cost']
    others=[(v['cost'],t) for t,v in pt.items() if t!=L and v['cost'] is not None]
    # best over catalog incl. residual: cost values for others contain RESIDUAL fallback (=S residual). find those with CATALOG/other-truck desc
    cross=[(v['cost'],t) for t,v in pt.items() if t!=L and v['cost'] is not None and v['desc'] and ('truck=%s'%t) in v['desc']]
    bestS=cl
    bestX=min([cl]+[c for c,_ in cross])
    gaps.append((r['nom'],r['case'],r['seed'],round(bestS,2),round(bestX,2),round(bestS-bestX,2),len(cross)))
g=collections.defaultdict(list)
for x in gaps: g[(x[0],x[1])].append(x)
for k,v in sorted(g.items()):
    print(k,'events',len(v),'X<S in',sum(1 for x in v if x[5]>1e-6),'gaps',[x[5] for x in v if x[5]>1e-6],'mean over events',round(sum(x[5] for x in v)/len(v),2))
