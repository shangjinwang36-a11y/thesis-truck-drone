#!/bin/bash
cd /workspace/thesis/exp
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
$P run_exp_light.py --out $O/ltD_main_nom1000 --nominal $O/nominal_lightR1000 --budget 1000 --decision milp --workers 7 > ltD_main_nom1000.log 2>&1
$P run_exp_light.py --out $O/ltD_main7_nom1000 --package data/package_light_7trucks.json --nominal $O/nominal_lightR7_1000 --budget 1000 --decision milp --cases C100,R100,RC100 --workers 7 > ltD_main7_nom1000.log 2>&1
$P run_exp_light.py --out $O/ltD_forced3_nom1000 --nominal $O/nominal_lightR1000 --budget 1000 --decision milp --forced 3 --workers 7 > ltD_forced3_nom1000.log 2>&1
$P run_exp_light.py --out $O/ltD_forced5_nom1000 --nominal $O/nominal_lightR1000 --budget 1000 --decision milp --forced 5 --workers 7 > ltD_forced5_nom1000.log 2>&1
echo ALLDONE > queue_d.done
