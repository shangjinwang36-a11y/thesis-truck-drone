#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r5
cd /workspace/thesis/proj_r5
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
FIX='{"reassign_adopt_only_if_best": true}'
run(){ n=$1; shift; $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --max-replans 60 --alg-json "$FIX" --workers 6 "$@" > $L/$n.log 2>&1; }
run fix_l2_p01_s40 --p 0.1 --seeds 40
run fix_l2_p02_s10 --p 0.2 --seeds 10
run fix_l2_p03_s10 --p 0.3 --seeds 10
run fix_l2_p02_s40 --p 0.2 --seeds 40
echo done > $L/queue2.done
