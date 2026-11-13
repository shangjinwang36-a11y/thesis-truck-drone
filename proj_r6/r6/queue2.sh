#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
$PY r6/run_r6.py --name pipe_cf_nom2 --package data/package_light.json --nominal-S r6/nominal/nom2/S_seed20261113 --nominal-X r6/nominal/nom2/X_seed20261113 --workers 3 > r6/logs/pipe_cf_nom2.log 2>&1
while [ ! -f r6/nominal/pipe_b200/summary.json ] || ! grep -q '"X"' r6/nominal/pipe_b200/summary.json || [ $(grep -c '"strat"' r6/nominal/pipe_b200/summary.json) -lt 12 ]; do sleep 20; done
$PY r6/run_r6.py --name pipe_b200 --package data/package_light.json --nominal-S r6/nominal/pipe_b200/S_seed20261113 --nominal-X r6/nominal/pipe_b200/X_seed20261113 --workers 3 > r6/logs/pipe_b200_run.log 2>&1
echo Q2DONE > r6/logs/queue2.done
