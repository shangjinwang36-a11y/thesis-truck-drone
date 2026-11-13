#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4b
cd /workspace/thesis/proj_r4b
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r4.py; L=/workspace/thesis/r4
run(){ name=$1; budget=$2; alg=$3
 $P $R --name grid1_$name --package data/package.json --nominal outputs/nominal_r3fd1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --budget $budget --alg-json "$alg" --workers 8 > $L/grid1_$name.log 2>&1; }
run dfrac_small 1000 '{"destroy_fraction_min":0.05,"destroy_fraction_max":0.15}'
run dfrac_big 1000 '{"destroy_fraction_min":0.2,"destroy_fraction_max":0.5}'
run sa_hot 1000 '{"sa_initial_worse_fraction":0.03}'
run sa_cold 1000 '{"sa_initial_worse_fraction":0.003}'
run b3000_init300 3000 '{"recovery_init_eval_budget": 300}'
run b3000_rt 3000 '{"recovery_retarget": true}'
echo done > $L/grid2.done
