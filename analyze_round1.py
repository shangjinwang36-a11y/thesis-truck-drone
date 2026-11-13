import json,glob,csv,math,statistics as st,sys,os
from scipy.stats import t as T
def load_ep(d):
    out=[]
    for f in sorted(glob.glob(d+'/*_seed*_*/replans.jsonl')):
        run=f.split('/')[-2]; case,seed,strat=run.split('_')
        for l in open(f):
            r=json.loads(l)
            if r['index']>=1: out.append((case,int(seed[4:]),strat,r))
    return out
def patch(d):
    rows=load_ep(d); pb=[]; 
    for c,s,k,r in rows:
        bt=r['stats'].get('best_trace')
        if bt: pb.append((bt[0][1]-bt[-1][1],c,s,k,r))
    return pb
def stats_ci(deltas):
    n=len(deltas); m=sum(deltas)/n; sd=st.stdev(deltas) if n>1 else float('nan')
    hw=T.ppf(.975,n-1)*sd/math.sqrt(n) if n>1 else float('nan')
    return n,m,sd,m-hw,m+hw
def summ(d):
    ep=list(csv.DictReader(open(d+'/episodes.csv',encoding='utf-8-sig')))
    res={}
    res['complete_S']=sum(r['status_S']=='COMPLETED_VERIFIED' for r in ep)
    res['complete_X']=sum(r['status_X']=='COMPLETED_VERIFIED' for r in ep)
    dl=[float(r['delta']) for r in ep if r['delta'] not in ('',None)]
    res['pairs']=stats_ci(dl)
    res['pos_zero_neg']=(sum(x>1e-9 for x in dl),sum(abs(x)<=1e-9 for x in dl),sum(x<-1e-9 for x in dl))
    res['meanS']=st.mean(float(r['cost_S']) for r in ep if r['cost_S'] and r['cost_X'])
    res['meanX']=st.mean(float(r['cost_X']) for r in ep if r['cost_S'] and r['cost_X'])
    pb=patch(d)
    v=[x[0] for x in pb]
    res['patch']=(len(v),st.mean(v),st.median(v),max(v),sum(1 for x in v if abs(x)<1e-9))
    for k in ('S','X'):
        w=[x[0] for x in pb if x[3]==k]; res['patch_'+k]=(len(w),st.mean(w))
    # new-only stats
    rr=load_ep(d)
    mi={k:[r['stats'].get('n_main_iterations') for c,s,kk,r in rr if kk==k and r['stats'].get('n_main_iterations') is not None] for k in 'SX'}
    if mi['S']:
        res['main_iters']={k:(len(v),st.mean(v)) for k,v in mi.items()}
        res['init_evals']={k:st.mean([r['stats']['n_init_evals'] for c,s,kk,r in rr if kk==k]) for k in 'SX'}
        res['main_evals']={k:st.mean([r['stats']['n_main_evals'] for c,s,kk,r in rr if kk==k]) for k in 'SX'}
        import collections
        res['init_source']=dict(collections.Counter(r['stats'].get('init_source') for c,s,kk,r in rr))
        both=[(r['stats']['residual_cost'],r['stats']['final_cost']) for c,s,kk,r in rr if r['stats'].get('residual_cost') is not None and r['stats'].get('final_cost') is not None]
        res['final_le_residual']=(sum(f<=rc+1e-6 for rc,f in both),len(both))
        res['mean_final_minus_residual']=st.mean(f-rc for rc,f in both) if both else None
        res['stop_reasons']=dict(collections.Counter(r['stats'].get('stop_reason') for c,s,kk,r in rr))
    else:
        import collections
        res['stop_reasons_old']=None
        res['old_iters']={k:st.mean([r['stats'].get('n_alns_iterations',0) for c,s,kk,r in rr if kk==k]) for k in 'SX'}
        res['old_evals']={k:st.mean([r['stats'].get('n_eval_requests',0) for c,s,kk,r in rr if kk==k]) for k in 'SX'}
    return res
if __name__=='__main__':
    for d in sys.argv[1:]:
        print(d); 
        for k,v in summ(d).items(): print('  ',k,v)
