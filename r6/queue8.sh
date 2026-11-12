#!/bin/bash
# soft-H(加班 1.5x) 变体完整流程：n3_tp(名义预算3000, 两阶段) 3 个名义种子, 恢复预算 1000, S/X 同参数
cd /workspace/thesis/proj_r6
PY=/workspace/thesis/venv/bin/python
run() { $PY r6/run_r6.py --name $1 --package data/package_light.json --nominal-S $2/S_seed$3 --nominal-X $2/X_seed$3 --budget $4 --workers 4 --phys-json '{"soft_h": true, "overtime_mult": 1.5}' > r6/logs/$1.log 2>&1; }
for s in 20261113 20261114 20261115; do run c4_soft_tp_s${s:6} r6/nominal/n3_tp $s 1000; done
for s in 20261113 20261114 20261115; do run c4_soft_full_s${s:6} r6/nominal/n3_full $s 1000; done
echo Q8DONE > r6/logs/queue8.done
