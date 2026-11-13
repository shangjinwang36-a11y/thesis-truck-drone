"""名义 n3_*: S/X 配对(同算例×名义种子), Δ=C_S−C_X；X<=S 成立比例、符号检验、跨车航次、空送占比；tp 另报阶段1共享解与阶段2改进"""
import json,glob,sys,math,statistics as st
sys.path.insert(0,'r6'); from agg_r6b import sign_p
tag=sys.argv[1]; T={'S':{},'X':{}}
for f in glob.glob(f'r6/nominal/{tag}/*_seed*/*/result.json'):
    p=f.split('/'); m=json.load(open(f))
    if m.get('status')=='FEASIBLE': T[p[3][0]][(p[4],p[3].split('seed')[1])]=m
ks=sorted(set(T['S'])&set(T['X']))
d=[T['S'][k]['cost']-T['X'][k]['cost'] for k in ks]; cs=[T['S'][k]['cost'] for k in ks]
b=sum(x>1e-6 for x in d); w=sum(x<-1e-6 for x in d)
print(f'## {tag}: n={len(ks)} Δ̄={st.mean(d):.2f} sd={st.stdev(d):.2f} ±{1.96*st.stdev(d)/math.sqrt(len(d)):.2f} Δ/C_S={100*sum(d)/sum(cs):.2f}%  X<=S(含平)={sum(x>=-1e-6 for x in d)}/{len(d)}  好/坏={b}/{w} 符号检验p={sign_p(b,w):.3f}')
print(f'  X跨车航次均值={st.mean(T["X"][k]["n_cross_sorties"] for k in ks):.1f}/总航次{st.mean(T["X"][k]["n_sorties"] for k in ks):.1f}; 空送占比 S/X={100*st.mean(T["S"][k]["n_air_parcels"]/(100 if "100" in k[0] else 50) for k in ks):.1f}/{100*st.mean(T["X"][k]["n_air_parcels"]/(100 if "100" in k[0] else 50) for k in ks):.1f}%')
print(f'  eval_requests S/X 均值={st.mean(T["S"][k]["eval_requests"] for k in ks):.0f}/{st.mean(T["X"][k]["eval_requests"] for k in ks):.0f}')
if 'tp' in tag:
    p1=[T['S'][k]['phase1_cost'] for k in ks]; assert all(abs(T['S'][k]['phase1_cost']-T['X'][k]['phase1_cost'])<1e-9 and T['S'][k]['phase1_evals']==T['X'][k]['phase1_evals'] for k in ks)
    print(f'  阶段1共享(S=X逐位相同): 均值 {st.mean(p1):.2f}, 结束于评价 {st.mean(T["S"][k]["phase1_evals"] for k in ks):.0f}; 阶段2 改进 S={st.mean(T["S"][k]["phase1_cost"]-T["S"][k]["cost"] for k in ks):.2f} X={st.mean(T["X"][k]["phase1_cost"]-T["X"][k]["cost"] for k in ks):.2f}')
    print(f'  阶段2后 X 比阶段1解更差(不应发生)的数量: {sum(T["X"][k]["cost"]>T["X"][k]["phase1_cost"]+1e-6 for k in ks)}')
for c in sorted({k[0] for k in ks}):
    kk=[k for k in ks if k[0]==c]; dd=[T['S'][k]['cost']-T['X'][k]['cost'] for k in kk]
    print(f'  {c:5s} n={len(kk)} Δ̄={st.mean(dd):7.2f} Δ/C_S={100*sum(dd)/sum(T["S"][k]["cost"] for k in kk):6.2f}% 好/坏={sum(x>1e-6 for x in dd)}/{sum(x<-1e-6 for x in dd)}  跨车X={st.mean(T["X"][k]["n_cross_sorties"] for k in kk):.1f}')
