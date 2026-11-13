#!/bin/bash
# usage: sweep.sh tag 'json'
tag=$1; ao=$2; b=${3:-1000}
cd /workspace/thesis/proj
for c in C50 R50 RC50 C100 R100 RC100; do /workspace/thesis/venv/bin/python /workspace/thesis/diag/drv3.py $c $b "$ao" > /tmp/sw_${tag}_$c.json 2>&1 & done
wait
