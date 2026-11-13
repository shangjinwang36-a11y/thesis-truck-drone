#!/bin/bash
cd /workspace/thesis/exp
while [ ! -f queue_e.done ]; do sleep 20; done
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
$P run_exp_light.py --out $O/res_spec_main --package data/package.json --nominal $O/nominal_r3fd1000 --budget 1000 --decision milp --workers 7 > res_spec_main.log 2>&1
$P run_exp_light.py --out $O/res_spec_forced3 --package data/package.json --nominal $O/nominal_r3fd1000 --budget 1000 --decision milp --forced 3 --workers 7 > res_spec_forced3.log 2>&1
echo ALLDONE > queue_f.done
