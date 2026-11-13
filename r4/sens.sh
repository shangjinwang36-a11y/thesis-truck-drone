#!/bin/bash
while [ ! -f /workspace/thesis/r4/grid2.done ]; do sleep 10; done
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r5.py; L=/workspace/thesis/r4
declare -A PK NM
PK[spec]=data/package.json; NM[spec]=outputs/nominal_r3fd1000
PK[light1]=data/package_light_1drone.json; NM[light1]=outputs/nominal_L1_1000
PK[light2]=data/package_light.json; NM[light2]=outputs/nominal_lightR1000
run(){ n=$1; shift; $P $R --name $n "$@" --workers 8 > $L/$n.log 2>&1; }
for c in spec light1 light2; do
 base="--package ${PK[$c]} --nominal ${NM[$c]}"
 run sens_${c}_H900 $base --H-delta -900
 run sens_${c}_airM12 $base --pool air --mrange 1,2
 run sens_${c}_airM3 $base --pool air --forced 3
 run sens_${c}_allM3 $base --pool all --forced 3
 run sens_${c}_airM5 $base --pool air --forced 5
 run sens_${c}_allM5 $base --pool all --forced 5
done
base="--package data/package_light_fewtrucks.json --nominal outputs/nominal_Lfew_1000"
run sens_few_base $base
run sens_few_airM3 $base --pool air --forced 3
run sens_few_H900 $base --H-delta -900
echo done > $L/sens.done
