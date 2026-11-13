#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
run() { $PY r6/run_r6.py --name $1 --package data/package_light.json --nominal-S $2/S_seed$3 --nominal-X $2/X_seed$3 --workers 4 > r6/logs/$1.log 2>&1; }
run v2_b200_s13 r6/nominal/pipe_b200 20261113
run v2_full_s13 r6/nominal/nom2 20261113
run v2_b200_s14 r6/nominal/m_b200 20261114
run v2_full_s14 r6/nominal/m_full 20261114
run v2_b200_s15 r6/nominal/m_b200 20261115
run v2_full_s15 r6/nominal/m_full 20261115
echo Q4DONE > r6/logs/queue4.done
