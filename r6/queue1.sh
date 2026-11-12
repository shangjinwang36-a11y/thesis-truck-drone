#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
for b in 200 400 600; do
  $PY r6/run_nominal.py --tag grid_b$b --seeds 1,2,3,4,5 --b $b --workers 4 > r6/logs/grid_b$b.log 2>&1
done
$PY r6/run_nominal.py --tag thr_X --seeds 1,2,3,4,5,6,7,8,9,10 --strats X --workers 4 > r6/logs/thr_X.log 2>&1
echo QDONE > r6/logs/queue1.done
