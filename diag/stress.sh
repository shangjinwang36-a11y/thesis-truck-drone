#!/bin/bash
# usage: stress.sh nomdir out
nom=$1; out=$2
for c in C50 R50 RC50; do for k in 3 6; do for s in $(seq 1 12); do for st in S X; do echo "$c $k $s $st"; done; done; done; done | xargs -P 6 -L1 bash -c "/workspace/thesis/venv/bin/python multi_fail.py \$0 \$1 \$2 \$3 $nom 150 2>&1 | tail -2 | tr '\n' ' ' | cut -c1-260 | sed \"s/^/\$0 \$1 \$2 \$3 | /\"; echo" > $out
