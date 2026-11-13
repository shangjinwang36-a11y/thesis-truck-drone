#!/bin/bash
cd /workspace/thesis/exp
export TDR_ROOT=/workspace/thesis/proj_r3m
P=/workspace/thesis/venv/bin/python
O=/workspace/thesis/proj/outputs
$P run_exp.py --out $O/r3m_forced5 --nominal $O/nominal_r3m03 --budget 1000 --decision milp --forced 5 --cases C50,R50,RC50 --workers 2 > r3m_forced5.log 2>&1
echo done > queue_m.done
