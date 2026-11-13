#!/usr/bin/env python3
"""第 10 轮标签和第 11 轮在 3001–3030 上的配对差。

(C_X10 − C_X11) / C_S。C_S 用第 11 轮这份名义成本，同一张地图里是常数。
某一侧没有有限成本的种子不编一个数进去。
自助法在每张地图内部重抽种子，两列用同一次抽样。区间含 0 就不认为第 11 轮更好。
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
N_BOOT = 10000
BOOT_SEED = 20261111


def fair(ep):
    if not ep:
        return None
    if ep.get("cost_fair") is not None:
        return ep["cost_fair"]
    if ep.get("status") == "COMPLETED_VERIFIED" and ep.get("cost") is not None:
        return ep["cost"]
    return ep.get("ground_finish_cost")


def load(path: Path):
    rows = json.loads(path.read_text())
    out = {}
    for row in rows:
        if not (3001 <= int(row["seed"]) <= 3030):
            continue
        out[(row["case"], int(row["seed"]))] = row
    return out


def main():
    r10_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "r6/results/round12/r10_on_3001/episodes.json")
    r11_path = ROOT / "r6/results/round11_final/episodes.json"
    r10, r11 = load(r10_path), load(r11_path)
    by = defaultdict(list)
    dropped = []
    nominal_mismatch = []
    for key, row11 in sorted(r11.items()):
        row10 = r10.get(key)
        if row10 is None:
            dropped.append((key, "missing_r10"))
            continue
        c10, c11 = fair(row10.get("X")), fair(row11.get("X"))
        cs = (row11.get("S_nominal") or {}).get("cost")
        cs10 = (row10.get("S_nominal") or {}).get("cost")
        if cs10 is not None and cs is not None and abs(cs10 - cs) > 1e-6:
            nominal_mismatch.append((key[0], cs10, cs))
        if c10 is None or c11 is None or not cs:
            dropped.append((key, "unpriced", c10, c11))
            continue
        by[key[0]].append((c10 - c11) / cs)
    rng = random.Random(BOOT_SEED)
    keys = [c for c in CASES if by.get(c)]
    samples = []
    for _ in range(N_BOOT):
        stats = []
        for case in keys:
            pool = by[case]
            draw = [pool[rng.randrange(len(pool))] for _ in range(len(pool))]
            stats.append(sum(draw) / len(draw))
        samples.append(sum(stats) / len(stats))
    samples.sort()
    point = None
    if keys:
        point = sum(sum(by[c]) / len(by[c]) for c in keys) / len(keys)
    lo = samples[int(0.025 * N_BOOT)] if samples else None
    hi = samples[int(0.975 * N_BOOT)] if samples else None
    print(json.dumps({
        "n_priced_pairs": sum(len(v) for v in by.values()),
        "per_case_n": {c: len(by[c]) for c in CASES},
        "equal_weight": point,
        "ci95": [lo, hi],
        "ci_crosses_0": None if lo is None else lo <= 0 <= hi,
        "dropped": len(dropped),
        "nominal_mismatch_cases": sorted({c for c, _, _ in nominal_mismatch}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
