#!/bin/bash
cd /workspace/thesis/exp
export TDR_ROOT=/workspace/thesis/proj_r3spec
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
for N in 1000 5000; do
  NOM=$O/nominal_r3fd$N
  $P run_exp.py --out $O/r3_main_nom$N --nominal $NOM --budget 1000 --decision milp --workers 7 > r3_main_nom$N.log 2>&1
  $P run_exp.py --out $O/r3_forced3_nom$N --nominal $NOM --budget 1000 --decision milp --forced 3 --workers 7 > r3_forced3_nom$N.log 2>&1
  $P run_exp.py --out $O/r3_forced5_nom$N --nominal $NOM --budget 1000 --decision milp --forced 5 --workers 7 > r3_forced5_nom$N.log 2>&1
done
echo ALLDONE > queue_r3.done
