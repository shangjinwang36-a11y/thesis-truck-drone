#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4b
cd /workspace/thesis/proj_r4b
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r4/run_r4.py; L=/workspace/thesis/r4
run(){ n=$1; pk=$2; nom=$3; extra=$4; alg=$5
 $P $R --name abl2_${n} --package $pk --nominal $nom --cases C50,R50,RC50 --seeds 8 --forced 3 --alg-json "$alg" --workers 8 > $L/abl2_$n.log 2>&1; }
run spec_off data/package.json outputs/nominal_r3fd1000 x '{"cross_ops": false}'
run spec_on data/package.json outputs/nominal_r3fd1000 x '{"cross_ops": true}'
run spec_ungated data/package.json outputs/nominal_r3fd1000 x '{"cross_ops": true, "cross_ops_gate": false}'
run light_off data/package_light.json outputs/nominal_lightR1000 x '{"cross_ops": false}'
run light_on data/package_light.json outputs/nominal_lightR1000 x '{"cross_ops": true}'
run light_ungated data/package_light.json outputs/nominal_lightR1000 x '{"cross_ops": true, "cross_ops_gate": false}'
echo done > $L/abl2.done
