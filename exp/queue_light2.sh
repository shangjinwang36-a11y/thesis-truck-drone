#!/bin/bash
cd /workspace/thesis/exp
while [ ! -f queue_r3.done ]; do sleep 10; done
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
N=1000
$P run_exp_light.py --out $O/lt_main_nom$N --nominal $O/nominal_light$N --budget 1000 --decision milp --workers 7 > lt_main_nom$N.log 2>&1
$P run_exp_light.py --out $O/lt_main7_nom$N --package data/package_light_7trucks.json --nominal $O/nominal_light7_$N --budget 1000 --decision milp --cases C100,R100,RC100 --workers 7 > lt_main7_nom$N.log 2>&1
$P run_exp_light.py --out $O/lt_forced3_nom$N --nominal $O/nominal_light$N --budget 1000 --decision milp --forced 3 --workers 7 > lt_forced3_nom$N.log 2>&1
$P run_exp_light.py --out $O/lt_forced5_nom$N --nominal $O/nominal_light$N --budget 1000 --decision milp --forced 5 --workers 7 > lt_forced5_nom$N.log 2>&1
$P run_exp_light.py --out $O/lt_main_k5_nom$N --nominal $O/nominal_light${N}_k5 --budget 1000 --decision milp --cases C100,R100,RC100 --workers 7 > lt_main_k5_nom$N.log 2>&1
N=5000
$P run_exp_light.py --out $O/lt_main_nom$N --nominal $O/nominal_light$N --budget 1000 --decision milp --workers 7 > lt_main_nom$N.log 2>&1
$P run_exp_light.py --out $O/lt_main7_nom$N --package data/package_light_7trucks.json --nominal $O/nominal_light7_$N --budget 1000 --decision milp --cases C100,R100,RC100 --workers 7 > lt_main7_nom$N.log 2>&1
echo ALLDONE > queue_light.done
