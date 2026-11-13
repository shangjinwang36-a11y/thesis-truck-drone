#!/bin/bash
export TDR_ROOT=/workspace/thesis/proj_r4c
cd /workspace/thesis/proj_r4c
nice -n 19 /workspace/thesis/venv/bin/python /workspace/thesis/r4/run_r6.py --name ev_light2_airM3 --package data/package_light.json --nominal outputs/nominal_lightR1000 --pool air --forced 3 --workers 3 > /workspace/thesis/r4/ev_light2_airM3.log 2>&1
echo done > /workspace/thesis/r4/ev_light2.done
