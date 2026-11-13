#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4a
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r4.py; L=/workspace/thesis/r4
$P $R --name main_spec --package data/package.json --nominal outputs/nominal_r3fd1000 --workers 7 > $L/main_spec.log 2>&1
$P $R --name main_light2 --package data/package_light.json --nominal outputs/nominal_lightR1000 --workers 7 > $L/main_light2.log 2>&1
$P $R --name main_light1 --package data/package_light_1drone.json --nominal outputs/nominal_L1_1000 --workers 7 > $L/main_light1.log 2>&1
echo done > $L/main_a.done
