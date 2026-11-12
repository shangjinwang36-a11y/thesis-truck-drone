#!/bin/bash
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
run() { # name nomdir seed budget
  $PY r6/run_r6.py --name $1 --package data/package_light.json --nominal-S $2/S_seed$3 --nominal-X $2/X_seed$3 --budget $4 --workers 3 > r6/logs/$1.log 2>&1; }
for s in 20261113 20261114 20261115; do run c3_full_s${s:6} r6/nominal/n3_full $s 1000; done
# 恢复预算 3 倍（S/X 相同）对照，仅 n3_full 种子13/14
run c3_full_s13_rb3000 r6/nominal/n3_full 20261113 3000
run c3_full_s14_rb3000 r6/nominal/n3_full 20261114 3000
while [ ! -f r6/logs/queue5.done ]; do sleep 15; done
for s in 20261113 20261114 20261115; do run c3_tp_s${s:6} r6/nominal/n3_tp $s 1000; done
echo Q6DONE > r6/logs/queue6.done
