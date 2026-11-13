#!/bin/bash
# 代码版本 v5 = proj_r5d(commit round5e): v4 + 评价器机位账修复 + 软H加班变体(soft_h)
export TDR_ROOT=/workspace/thesis/proj_r5d
cd /workspace/thesis/proj_r5d
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
FIX='{"reassign_adopt_only_if_best": true, "joint_inflight_retarget": true, "slot_aware_recovery": true}'
run(){ n=$1; shift; $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --max-replans 60 --alg-json "$FIX" --workers 8 "$@" > $L/$n.log 2>&1; }
SOFT='{"soft_h": true, "overtime_mult": 1.5}'
run v5_l2_p02_base --p 0.2 --seeds 10 --seed0 1
run v5_l2_p02_softH --p 0.2 --seeds 10 --seed0 1 --phys-json "$SOFT"
run v5_l2_p01_base --p 0.1 --seeds 10 --seed0 1
run v5_l2_p01_softH --p 0.1 --seeds 10 --seed0 1 --phys-json "$SOFT"
echo done > $L/queue7.done
