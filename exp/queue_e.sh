#!/bin/bash
cd /workspace/thesis/exp
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
for v in L1:package_light_1drone Lchg:package_light_chg; do n=${v%%:*}; pk=${v##*:}
$P run_exp_light.py --out $O/res_${n}_main --package data/$pk.json --nominal $O/nominal_${n}_1000 --budget 1000 --decision milp --workers 7 > res_${n}_main.log 2>&1
$P run_exp_light.py --out $O/res_${n}_forced3 --package data/$pk.json --nominal $O/nominal_${n}_1000 --budget 1000 --decision milp --forced 3 --workers 7 > res_${n}_forced3.log 2>&1
done
echo ALLDONE > queue_e.done
