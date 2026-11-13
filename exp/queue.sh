#!/bin/bash
cd /workspace/thesis/exp
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
# wait for chg nominals
while pgrep -f nom_phys >/dev/null; do sleep 5; done
while pgrep -f "r2_main1000_nom5000" >/dev/null; do sleep 5; done
$P run_exp.py --out $O/r2_chg10_100 --nominal $O/nominal_chg10 --budget 1000 --decision milp --cases C100,R100,RC100 --workers 5 --phys-json '{"slot_ac_kw":10,"truck_ac_kw":20,"truck_initial_ac_kwh":20}' > chg10_100.log 2>&1
$P run_exp.py --out $O/r2_main3000 --nominal $O/nominal_r2 --budget 3000 --decision milp --workers 5 > main3000.log 2>&1
$P run_exp.py --out $O/r2_main3000_nom5000 --nominal $O/nominal_r2_5000 --budget 3000 --decision milp --workers 5 > main3000_nom5000.log 2>&1
$P run_exp.py --out $O/r2_forced3_nom5000 --nominal $O/nominal_r2_5000 --budget 1000 --decision milp --forced 3 --cases C50,R50,RC50 --workers 5 > forced3_nom5000.log 2>&1
$P run_exp.py --out $O/r2_forced5_nom5000 --nominal $O/nominal_r2_5000 --budget 1000 --decision milp --forced 5 --cases C50,R50,RC50 --workers 5 > forced5_nom5000.log 2>&1
$P run_exp.py --out $O/r2_chg10_50 --nominal $O/nominal_chg10 --budget 1000 --decision milp --cases C50,R50,RC50 --workers 5 --phys-json '{"slot_ac_kw":10,"truck_ac_kw":20,"truck_initial_ac_kwh":20}' > chg10_50.log 2>&1
echo ALLDONE > queue.done
