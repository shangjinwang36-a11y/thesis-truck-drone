#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
run() { $PY r6/run_r6.py --name $1 --package data/package_light.json --nominal-S $2/S_seed$3 --nominal-X $2/X_seed$3 --budget $4 --workers 4 > r6/logs/$1.log 2>&1; }
run c3_tp_s13 r6/nominal/n3_tp 20261113 1000
run c3_tp_s14 r6/nominal/n3_tp 20261114 1000
run c3_tp_s15 r6/nominal/n3_tp 20261115 1000
run c3_full_s15 r6/nominal/n3_full 20261115 1000
run c3_tp_s13_rb3000 r6/nominal/n3_tp 20261113 3000
echo Q7DONE > r6/logs/queue7.done
