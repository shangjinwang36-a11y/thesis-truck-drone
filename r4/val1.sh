#!/bin/bash
cd /workspace/thesis/exp
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
$P run_exp_light.py --out $O/r4_val_spec_f5 --package data/package.json --nominal $O/nominal_r3fd1000 --budget 1000 --decision milp --forced 5 --cases C50,R50,RC50 --seeds 6 --workers 7 > /workspace/thesis/r4/val_spec_f5.log 2>&1
$P run_exp_light.py --out $O/r4_val_light_f5 --nominal $O/nominal_lightR1000 --budget 1000 --decision milp --forced 5 --cases C50,R50,RC50 --seeds 6 --workers 7 > /workspace/thesis/r4/val_light_f5.log 2>&1
echo done > /workspace/thesis/r4/val1.done
