#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r5.py; L=/workspace/thesis/r4
$P $R --name crn_spec_f3 --package data/package.json --nominal outputs/nominal_r3fd1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --alg-json '{"crn_per_iteration": true}' --workers 4 > $L/crn_spec_f3.log 2>&1
$P $R --name crn_light1_f3 --package data/package_light_1drone.json --nominal outputs/nominal_L1_1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --alg-json '{"crn_per_iteration": true}' --workers 4 > $L/crn_light1_f3.log 2>&1
$P $R --name base_light1_f3 --package data/package_light_1drone.json --nominal outputs/nominal_L1_1000 --cases C50,R50,RC50 --seeds 8 --forced 3 --workers 4 > $L/base_light1_f3.log 2>&1
echo done > $L/crn.done
