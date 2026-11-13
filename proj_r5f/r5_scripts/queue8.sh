#!/bin/bash
# 代码版本 v6 = proj_r5f (v5 + land_and_wait 变体；标志全关时与 v5 相同，故 v5 base/softH 结果即 v6 base/softH)
export TDR_ROOT=/workspace/thesis/proj_r5f
cd /workspace/thesis/proj_r5f
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
FIX='{"reassign_adopt_only_if_best": true, "joint_inflight_retarget": true, "slot_aware_recovery": true}'
run(){ n=$1; shift; $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --max-replans 60 --alg-json "$FIX" --workers 8 "$@" > $L/$n.log 2>&1; }
LAND='{"land_and_wait": true}'
COMB='{"land_and_wait": true, "soft_h": true, "overtime_mult": 1.5}'
run v6_l2_p02_land --p 0.2 --seeds 10 --seed0 1 --phys-json "$LAND"
run v6_l2_p02_comb --p 0.2 --seeds 10 --seed0 1 --phys-json "$COMB"
run v6_l2_p01_land --p 0.1 --seeds 10 --seed0 1 --phys-json "$LAND"
run v6_l2_p01_comb --p 0.1 --seeds 10 --seed0 1 --phys-json "$COMB"
echo done > $L/queue8.done
