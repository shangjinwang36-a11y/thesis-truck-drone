#!/bin/bash
# 代码版本 v2 = proj_r5b (reassign_adopt_only_if_best + apply_air 机位复核)
export TDR_ROOT=/workspace/thesis/proj_r5b
cd /workspace/thesis/proj_r5b
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
FIX='{"reassign_adopt_only_if_best": true}'
run(){ n=$1; shift; $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --max-replans 60 --alg-json "$FIX" --workers 8 "$@" > $L/$n.log 2>&1; }
run v2_l2_p02_b1 --p 0.2 --seeds 10 --seed0 1
run v2_l2_p01_b1 --p 0.1 --seeds 10 --seed0 1
run v2_l2_p03_b1 --p 0.3 --seeds 10 --seed0 1
for b in 11 21 31; do run v2_l2_p01_b$b --p 0.1 --seeds 10 --seed0 $b; done
for b in 11 21 31; do run v2_l2_p02_b$b --p 0.2 --seeds 10 --seed0 $b; done
echo done > $L/queue4.done
