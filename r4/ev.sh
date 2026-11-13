#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r6.py; L=/workspace/thesis/r4
declare -A PK NM
PK[spec]=data/package.json; NM[spec]=outputs/nominal_r3fd1000
PK[light1]=data/package_light_1drone.json; NM[light1]=outputs/nominal_L1_1000
PK[light2]=data/package_light.json; NM[light2]=outputs/nominal_lightR1000
for c in spec light1 light2; do
 $P $R --name ev_${c}_main --package ${PK[$c]} --nominal ${NM[$c]} --workers 4 > $L/ev_${c}_main.log 2>&1
done
for c in spec light1 light2; do
 $P $R --name ev_${c}_airM3 --package ${PK[$c]} --nominal ${NM[$c]} --pool air --forced 3 --workers 4 > $L/ev_${c}_airM3.log 2>&1
done
echo done > $L/ev.done
