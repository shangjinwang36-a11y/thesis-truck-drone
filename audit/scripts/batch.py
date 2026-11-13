import sys, os, json, math, collections, time
from enum_event import *
from tdr.alns import Budget, SearchStats

def run(conf,case,seed,forced=None,nsup=8,evidx=0):
    inst,phys,alg,H,evs=capture(conf,case,seed,forced=forced,n_events=evidx+1)
    if len(evs)<=evidx: return None
    e=evs[evidx]; st=e['state']
    out=dict(conf=conf,case=case,seed=seed,forced=forced,t0=st.t0)
    rowsX,frag,res=enum_event(inst,phys,H,e,'X',n_support=nsup)
    launch=frag.launch_truck or frag.truck
    done=set(st.truck_done)
    elig=[r for r in rowsX if r['truck'] not in done]
    # trucks with empty route but not done (returning)
    ret=[t for t,rt in res.routes.items() if not rt and t not in done]
    out['launch']=launch; out['done']=sorted(done); out['returning']=ret
    def best(rs): 
        c=[r['cost'] for r in rs if r['cost'] is not None]; return min(c) if c else None
    out['bestS']=best([r for r in elig if r['truck']==launch])
    out['bestX_elig']=best(elig)
    out['bestX_cross_only']=best([r for r in elig if r['truck']!=launch])
    out['bestX_ret']=best([r for r in rowsX if r['truck'] in ret])
    out['n_opts']=collections.Counter((('S' if r['truck']==launch else 'X'),r['status']) for r in elig if True)
    out['reasons_cross']=collections.Counter((r['status'],r['viol'][:22]) for r in elig if r['truck']!=launch and r['cost'] is None)
    out['reasons_same']=collections.Counter((r['status'],r['viol'][:22]) for r in elig if r['truck']==launch and r['cost'] is None)
    # code's initial recovery
    for strat in ('S','X'):
        b=Budget(alg.recovery_init_eval_budget,None,start=time.perf_counter()); stt=SearchStats()
        kw=dict(e['kw']); kw.update(stats=stt,budget=b,rescue_evals=1000,use_milp=True,info={})
        opt,rs,cat=R.initial_recovery(e['new_plan'],st,inst,phys,strat,e['gr'],H=H,**{k:v for k,v in kw.items() if k not in('H','extra_pool') or k=='extra_pool'})
        out['code_'+strat]=opt.ev.cost if opt else None
        out['codetruck_'+strat]=opt.recovery_truck if opt else None
    return out
if __name__=='__main__':
    conf=sys.argv[1]; cases=sys.argv[2].split(','); seeds=range(1,int(sys.argv[3])+1)
    forced=int(sys.argv[4]) if len(sys.argv)>4 else None
    res=[]
    for c in cases:
        for s in seeds:
            try:
                o=run(conf,c,s,forced)
            except Exception as ex:
                print('ERR',c,s,repr(ex)[:200]); continue
            if o is None: print(c,s,'nofail'); continue
            res.append(o)
            print(c,s,'S*',o['bestS'] and round(o['bestS'],1),'X*',o['bestX_elig'] and round(o['bestX_elig'],1),'cross*',o['bestX_cross_only'] and round(o['bestX_cross_only'],1),'ret*',o['bestX_ret'] and round(o['bestX_ret'],1),'codeS',o['code_S'] and round(o['code_S'],1),'codeX',o['code_X'] and round(o['code_X'],1),o['codetruck_X'],'launch',o['launch'],flush=True)
    import pickle; pickle.dump(res,open(f'batch_{conf}_{"-".join(cases)}_{forced}_{os.environ.get("AUDIT_FIXCUST","0")}.pkl','wb'))
