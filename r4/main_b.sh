#!/bin/bash
while [ ! -f /workspace/thesis/r4/abl2.done ]; do sleep 10; done
export TDR_ROOT=/workspace/thesis/proj_r4b
cd /workspace/thesis/proj_r4b
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r4.py; L=/workspace/thesis/r4
A='{"cross_ops": true}'
$P $R --name mainB_spec_on --package data/package.json --nominal outputs/nominal_r3fd1000 --alg-json "$A" --workers 8 > $L/mainB_spec_on.log 2>&1
$P $R --name mainB_light2_on --package data/package_light.json --nominal outputs/nominal_lightR1000 --alg-json "$A" --workers 8 > $L/mainB_light2_on.log 2>&1
$P $R --name mainB_light1_on --package data/package_light_1drone.json --nominal outputs/nominal_L1_1000 --alg-json "$A" --workers 8 > $L/mainB_light1_on.log 2>&1
echo done > $L/mainB.done
