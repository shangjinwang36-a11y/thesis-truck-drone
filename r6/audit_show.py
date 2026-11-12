import json, sys
def show(path):
    m = json.load(open(path))
    print('==', path.split('nominal/')[-1], 'cost', round(m['cost'],2), 'cross', m['n_cross_sorties'], 'iters', m['n_iterations'], 'last_improve_iter', m['last_improvement_iter'], 'evals', m['eval_requests'])
    for k, v in sorted(m['audit'].items()):
        c = v.get('calls', v.get('gen', 0))
        print(f"  {k:24s} calls={c:4d} freed0={v.get('freed0',0):3d} leftover={v.get('leftover',0):3d} infeas={v.get('infeasible',0):3d} feas={v.get('feasible',0):3d} best={v.get('best',0):3d} cur_imp={v.get('cur_improve',0):3d} acc={v.get('accepted',0):3d}")
    for k, v in sorted(m['reject'].items(), key=lambda x: -x[1])[:8]:
        print('  REJ', v, k)
    tr = m['best_trace']; print('  trace', [(a, round(b,1)) for a, b, _ in tr[::max(1,len(tr)//8)]], '-> final', round(tr[-1][1],1))
for p in sys.argv[1:]: show(p)
