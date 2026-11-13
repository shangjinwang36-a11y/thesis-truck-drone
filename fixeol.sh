#!/bin/bash
# 原仓库 alns/recovery/simulate 为 CRLF；提交前还原，保证 diff 只含真实改动
cd /workspace/thesis/proj
for f in alns recovery simulate; do sed -i 's/\r$//; s/$/\r/' src/tdr/$f.py; done
