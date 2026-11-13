import json,sys,glob,statistics as st,math
from collections import defaultdict
tag=sys.argv[1]; cps=[500,1000,1500,2000,3000,4000,5000]
T={'S':{}, 'X':{}}
for f in glob.glob(f'r6/nominal/{tag}/*_seed*/*/result.json'):
    p=f.split('/'); strat=p[3][0]; seed=p[3].split('seed')[1]; case=p[4]
    m=json.load(open(f))
    if m.get('status')!='FEASIBLE': continue
    T[strat][(case,seed)]=(m['best_trace'],m)
def at(tr,e):
    c=None
    for ev,cost,z in tr:
        if ev<=e: c=cost
        else: break
    return c
keys=sorted(set(T['S'])&set(T['X']))
print(f'## 收敛曲线 {tag}  配对 {len(keys)}  Δ=C_S−C_X（正=X好）')
print('evals | S均值 X均值 | Δ均值 ±CI95 Δ/C_S% 好/坏')
for e in cps:
    d=[];cs=[]
    for k in keys:
        a=at(T['S'][k][0],e); b=at(T['X'][k][0],e)
        if a is None or b is None: continue
        d.append(a-b); cs.append(a)
    if len(d)<3: continue
    xs=[at(T['X'][k][0],e) for k in keys if at(T['X'][k][0],e) is not None]
    print(f"{e:5d} | {st.mean(cs):7.2f} {st.mean(xs):7.2f} | {st.mean(d):6.2f} ±{1.96*st.stdev(d)/math.sqrt(len(d)):.2f} {100*sum(d)/sum(cs):5.2f} {sum(x>1e-6 for x in d)}/{sum(x<-1e-6 for x in d)} (n={len(d)})")
print('\n最终(预算末) 分算例')
by=defaultdict(list)
for k in keys:
    S=T['S'][k][1]; X=T['X'][k][1]
    by[k[0]].append((S['cost'],X['cost'],S['n_air_parcels']/(100 if '100' in k[0] else 50),X['n_air_parcels']/(100 if '100' in k[0] else 50),X['n_cross_sorties'],X['n_sorties'],S['n_sorties']))
tot=[]
for c,l in sorted(by.items()):
    d=[a-b for a,b,*_ in l]; tot+= [(a,b) for a,b,*_ in l]
    print(f"{c:5s} n={len(l)} Δ̄={st.mean(d):6.2f} Δ/C_S={100*sum(d)/sum(a for a,*_ in l):5.2f}% 好/坏={sum(x>1e-6 for x in d)}/{sum(x<-1e-6 for x in d)} 空送%S/X={100*st.mean(x[2] for x in l):.1f}/{100*st.mean(x[3] for x in l):.1f} 跨车航次X={st.mean(x[4] for x in l):.1f}/{st.mean(x[5] for x in l):.1f}")
d=[a-b for a,b in tot]
print(f"ALL n={len(d)} Δ̄={st.mean(d):.2f} sd={st.stdev(d):.2f} ±{1.96*st.stdev(d)/math.sqrt(len(d)):.2f} Δ/C_S={100*sum(d)/sum(a for a,_ in tot):.2f}% 好/坏={sum(x>1e-6 for x in d)}/{sum(x<-1e-6 for x in d)}")
