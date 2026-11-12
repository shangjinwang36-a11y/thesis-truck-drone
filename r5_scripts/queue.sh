#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r5
cd /workspace/thesis/proj_r5
P=/workspace/thesis/venv/bin/python; R=/workspace/thesis/r5/run_r5.py; L=/workspace/thesis/r5
for p in 0.1 0.2 0.3; do
  n=l2_bern_p${p/./}
  $P $R --name $n --package data/package_light.json --nominal /workspace/thesis/proj/outputs/nominal_lightR1000 --failure-mode bernoulli --p $p --max-replans 60 --workers 6 > $L/$n.log 2>&1
done
echo done > $L/queue.done
