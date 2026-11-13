#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r5.py; L=/workspace/thesis/r4
base="--package data/package_light.json --nominal outputs/nominal_lightR1000"
run(){ n=$1; shift; nice -n 19 $P $R --name $n "$@" --workers 4 > $L/$n.log 2>&1; }
run sens_light2_H900 $base --H-delta -900
run sens_light2_airM12 $base --pool air --mrange 1,2
run sens_light2_airM3 $base --pool air --forced 3
run sens_light2_allM3 $base --pool all --forced 3
run sens_light2_airM5 $base --pool air --forced 5
run sens_light2_allM5 $base --pool all --forced 5
echo done > $L/sens_light2.done
