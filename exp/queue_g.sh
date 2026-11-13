#!/bin/bash
cd /workspace/thesis/exp
while [ ! -f queue_f.done ]; do sleep 20; done
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
for v in L2:package_gh200_light2 L1:package_gh200_light1; do n=${v%%:*}; pk=${v##*:}
$P run_exp_light.py --out $O/gh200_${n}_main --package data/$pk.json --nominal $O/nominal_gh200_${n}_1000 --budget 1000 --decision milp --cases C200,R200,RC200 --workers 7 > gh200_${n}_main.log 2>&1
$P run_exp_light.py --out $O/gh200_${n}_forced3 --package data/$pk.json --nominal $O/nominal_gh200_${n}_1000 --budget 1000 --decision milp --cases C200,R200,RC200 --forced 3 --workers 7 > gh200_${n}_forced3.log 2>&1
done
echo ALLDONE > queue_g.done
