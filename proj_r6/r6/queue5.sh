#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
$PY r6/run_nominal.py --tag n3_full --seeds 20261113,20261114,20261115 --budget 3000 --workers 5 > r6/logs/n3_full.log 2>&1
$PY r6/run_nominal.py --tag n3_tp --seeds 20261113,20261114,20261115 --budget 3000 --b 600 --workers 5 > r6/logs/n3_tp.log 2>&1
echo Q5DONE > r6/logs/queue5.done
