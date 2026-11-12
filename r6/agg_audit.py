import json, sys, glob, re
from collections import defaultdict, Counter
tag = sys.argv[1]
A = {'S': defaultdict(Counter), 'X': defaultdict(Counter)}; REJ = {'S': Counter(), 'X': Counter()}
LI = {'S': [], 'X': []}; ITS = {'S': [], 'X': []}; EV = {'S': 0, 'X': 0}; N = Counter()
for f in glob.glob(f'r6/nominal/{tag}/*_seed*/*/result.json'):
    st = f.split('/')[3][0]
    m = json.load(open(f))
    if m.get('status') != 'FEASIBLE': continue
    N[st] += 1
    for k, v in (m.get('audit') or {}).items():
        for kk, vv in v.items(): A[st][k][kk] += vv
    for k, v in (m.get('reject') or {}).items():
        REJ[st][re.sub(r'^[A-Z_]+\|', '', k)] += v
    LI[st].append(m['last_improvement_iter'] / max(1, m['n_iterations'])); ITS[st].append(m['n_iterations']); EV[st] += m['eval_requests']
print(f'## 算子审计（{tag}，S/X 各 {N["S"]}/{N["X"]} 个名义解求和）')
print('算子 | S: calls/infeas/feas/best/acc | X: calls/infeas/feas/best/acc')
ops = sorted(set(A['S']) | set(A['X']))
for o in ops:
    row = []
    for st in 'SX':
        v = A[st].get(o, Counter()); c = v.get('calls', v.get('gen', 0))
        row.append(f"{c:4d}/{v.get('infeasible',0):4d}/{v.get('feasible',0):4d}/{v.get('best',0):3d}/{v.get('accepted',0):3d}")
    print(f'{o:22s} | {row[0]} | {row[1]}')
print('\n不可行原因（评价次数，按 reason|状态 合并）')
for st in 'SX':
    tot = EV[st]
    print(st, f'总评价 {tot}，不可行合计 {sum(REJ[st].values())} ({100*sum(REJ[st].values())/max(1,tot):.1f}%)')
    for k, v in REJ[st].most_common(6): print('   ', v, k)
print('\n最后一次改进所处迭代占比(均值)  S: %.2f  X: %.2f ；平均迭代数 S %.1f X %.1f' % (sum(LI['S'])/len(LI['S']), sum(LI['X'])/len(LI['X']), sum(ITS['S'])/len(ITS['S']), sum(ITS['X'])/len(ITS['X'])))
