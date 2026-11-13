#!/usr/bin/env python3
"""第 12 轮单因素队列。每个规格调用一次冻结预设 R11，不改搜索。

已经写完 episodes.json 的规格会跳过，所以中断后可以接着跑。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 顺序按审阅要求：先 p、电池、预算，再其余。基准点不在这里，它是第 11 轮 3001–3010。
SPECS = [
    ("p0", ["--p", "0", "--scenario-p", "0"]),
    ("p01", ["--p", "0.1", "--scenario-p", "0.1"]),
    ("p03", ["--p", "0.3", "--scenario-p", "0.3"]),
    ("p04", ["--p", "0.4", "--scenario-p", "0.4"]),
    ("bat08", ["--battery-scale", "0.8"]),
    ("bat12", ["--battery-scale", "1.2"]),
    ("b100", ["--budget", "100", "--phase2-frac", "0.2"]),
    ("b250", ["--budget", "250", "--phase2-frac", "0.2"]),
    ("b500", ["--budget", "500", "--phase2-frac", "0.2"]),
    ("b2000", ["--budget", "2000", "--phase2-frac", "0.2"]),
    ("e075", ["--reserve-kwh", "0.075"]),
    ("e100", ["--reserve-kwh", "0.10"]),
    ("sl30", ["--slack-s", "30"]),
    ("sl60", ["--slack-s", "60"]),
    ("sl120", ["--slack-s", "120"]),
    ("sl180", ["--slack-s", "180"]),
    ("fleetm", ["--truck-delta", "-1"]),
    ("fleetp", ["--truck-delta", "1"]),
    ("d1s2", ["--drones-per-truck", "1", "--slots", "2"]),
    ("d1s3", ["--drones-per-truck", "1", "--slots", "3"]),
    ("d1s4", ["--drones-per-truck", "1", "--slots", "4"]),
    ("d2s2", ["--drones-per-truck", "2", "--slots", "2"]),
    ("d2s4", ["--drones-per-truck", "2", "--slots", "4"]),
    ("d3s3", ["--drones-per-truck", "3", "--slots", "3"]),
    ("d3s4", ["--drones-per-truck", "3", "--slots", "4"]),
]


def _done(out: Path) -> bool:
    path = out / "episodes.json"
    if not path.exists():
        return False
    try:
        rows = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    return isinstance(rows, list) and len(rows) == 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-spec", default=None, help="start at this spec id, inclusive")
    ap.add_argument("--only", default=None, help="comma-separated spec ids")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    wanted = None if args.only is None else set(args.only.split(","))
    started = args.from_spec is None
    for spec_id, extra in SPECS:
        if not started:
            if spec_id == args.from_spec:
                started = True
            else:
                continue
        if wanted is not None and spec_id not in wanted:
            continue
        out = ROOT / "r6" / "results" / "round12" / spec_id
        out.mkdir(parents=True, exist_ok=True)
        if _done(out):
            print(f"SKIP {spec_id}", flush=True)
            continue
        cmd = [
            sys.executable, "-u", str(ROOT / "r6" / "run_round2.py"),
            "--phase", "all", "--preset", "R11",
            "--seed0", "3001", "--seeds", "10",
            "--workers", str(args.workers),
            "--out", str(out.relative_to(ROOT)),
            *extra,
        ]
        print("RUN " + " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=ROOT)
        if proc.returncode != 0:
            print(f"FAIL {spec_id} exit={proc.returncode}", flush=True)
            return proc.returncode
        if not _done(out):
            print(f"FAIL {spec_id} episodes.json is not 60 rows", flush=True)
            return 1
        print(f"OK {spec_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
