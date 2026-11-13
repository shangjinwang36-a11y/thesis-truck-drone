#!/bin/bash
# 代码版本 v7 = proj_r5g (v6 + unlaunched_repair)。等 CPU 空闲再跑(避免与残留批次争抢)
while pgrep -f run_r5.py > /dev/null; do sleep 20; done
export TDR_ROOT=/workspace/thesis/proj_r5g
cd /workspace/thesis/proj_r5g
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
FIX='{"reassign_adopt_only_if_best": true, "joint_inflight_retarget": true, "slot_aware_recovery": true, "unlaunched_repair": true}'
run(){ n=$1; shift; $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --max-replans 60 --alg-json "$FIX" --workers 8 "$@" > $L/$n.log 2>&1; }
SOFT='{"soft_h": true, "overtime_mult": 1.5}'
COMB='{"land_and_wait": true, "soft_h": true, "overtime_mult": 1.5}'
run v7_l2_p02_softH --p 0.2 --seeds 10 --seed0 1 --phys-json "$SOFT"
run v7_l2_p02_comb --p 0.2 --seeds 10 --seed0 1 --phys-json "$COMB"
run v7_l2_p01_softH --p 0.1 --seeds 10 --seed0 1 --phys-json "$SOFT"
run v7_l2_p01_comb --p 0.1 --seeds 10 --seed0 1 --phys-json "$COMB"
for b in 11 21 31; do run v7_l2_p02_comb_b$b --p 0.2 --seeds 10 --seed0 $b --phys-json "$COMB"; done
echo done > $L/queue9.done
