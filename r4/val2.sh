#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r5.py; L=/workspace/thesis/r4
for v in sa_hot:'{"sa_initial_worse_fraction":0.03}' crn:'{"crn_per_iteration": true}'; do n=${v%%:*}; a=${v#*:}
 $P $R --name val2_spec_$n --package data/package.json --nominal outputs/nominal_r3fd1000 --alg-json "$a" --workers 4 > $L/val2_spec_$n.log 2>&1
 $P $R --name val2_light1_$n --package data/package_light_1drone.json --nominal outputs/nominal_L1_1000 --alg-json "$a" --workers 4 > $L/val2_light1_$n.log 2>&1
done
echo done > $L/val2.done
