#!/bin/bash
cd /workspace/thesis/exp
P=/workspace/thesis/venv/bin/python
R=/workspace/thesis/r4/run_r4.py
for rt in false true; do
 $P $R --name abl1_spec_f3_rt$rt --package data/package.json --nominal outputs/nominal_r3fd1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --alg-json "{\"recovery_retarget\": $rt}" --workers 8 > /workspace/thesis/r4/abl1_spec_rt$rt.log 2>&1
 $P $R --name abl1_light_f3_rt$rt --package data/package_light.json --nominal outputs/nominal_lightR1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --alg-json "{\"recovery_retarget\": $rt}" --workers 8 > /workspace/thesis/r4/abl1_light_rt$rt.log 2>&1
done
echo done > /workspace/thesis/r4/abl1.done
