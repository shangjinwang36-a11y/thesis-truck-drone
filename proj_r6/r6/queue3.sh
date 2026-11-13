#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
$PY r6/run_nominal.py --tag m_b200 --seeds 20261114,20261115 --b 200 --workers 4 > r6/logs/m_b200.log 2>&1
$PY r6/run_nominal.py --tag m_full --seeds 20261114,20261115 --workers 4 > r6/logs/m_full.log 2>&1
# pipelines (merged recovery fix on)
run() { # name nomdir seed
  $PY r6/run_r6.py --name $1 --package data/package_light.json --nominal-S $2/S_seed$3 --nominal-X $2/X_seed$3 --workers 4 > r6/logs/$1.log 2>&1
}
run m_b200_s13 r6/nominal/pipe_b200 20261113
run m_full_s13 r6/nominal/nom2 20261113
for s in 20261114 20261115; do run m_b200_s${s:6} r6/nominal/m_b200 $s; run m_full_s${s:6} r6/nominal/m_full $s; done
echo Q3DONE > r6/logs/queue3.done
