import json, sys, os
O='/workspace/thesis/proj/outputs/'
def reps(d):
    out=[]
    for l in open(d+'/replans.jsonl'):
        r=json.loads(l)
        if r['index']>0: out.append(r)
    return out
def classify(name, tol=1e-6):
    R=json.load(open(O+name+'/results.json')); rows=[]
    for r in sorted(R,key=lambda r:(r['case'],r['seed'])):
        if not (r['status_S']==r['status_X']=='COMPLETED_VERIFIED') or r['cost_X']<=r['cost_S']+tol: continue
        dS=O+f"{name}/{r['case']}_seed{r['seed']:02d}_S"; dX=dS[:-1]+'X'
        a,b=reps(dS),reps(dX)
        info=dict(case=r['case'],seed=r['seed'],dcost=r['cost_X']-r['cost_S'],nfail=r['nfail_X'],nrep_S=len(a),nrep_X=len(b))
        # 第一次重规划
        if a and b:
            sa,sb=a[0]['stats'],b[0]['stats']
            info.update(first_same_time=abs(a[0]['time_s']-b[0]['time_s'])<1e-6,
                init_S=sa.get('init_cost'),init_X=sb.get('init_cost'),
                final1_S=a[0]['cost'],final1_X=b[0]['cost'],
                init_X_le_S=(sb.get('init_cost') is not None and sa.get('init_cost') is not None and sb['init_cost']<=sa['init_cost']+tol),
                rec_S=a[0]['recovery'],rec_X=b[0]['recovery'])
            info['loss_stage']=('init' if not info['init_X_le_S'] else ('alns_first' if (b[0]['cost']>a[0]['cost']+tol) else ('later_replan' if len(a)>1 or len(b)>1 else 'none')))
        rows.append(info)
    return rows
if __name__=='__main__':
    for n in sys.argv[1:]:
        print('##',n)
        for i in classify(n): print({k:(round(v,3) if isinstance(v,float) else v) for k,v in i.items()})
