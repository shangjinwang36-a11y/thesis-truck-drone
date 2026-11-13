#!/usr/bin/env python3
"""第 12 轮汇总。等权、分层自助法和时间拆分都按第 11 轮的定义。"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "r6" / "results"
CASES = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
N_BOOT = 10000
BOOT_SEED = 20261111

# 图上的横轴。基准点 id 是 base，数值来自第 11 轮 3001–3010，不另跑。
FACTORS = {
    "p": [("p0", 0.0), ("p01", 0.1), ("base", 0.2), ("p03", 0.3), ("p04", 0.4)],
    "battery": [("bat08", 0.8), ("base", 1.0), ("bat12", 1.2)],
    "emin": [("base", 0.05), ("e075", 0.075), ("e100", 0.10)],
    "slack": [("sl30", 30), ("sl60", 60), ("base", 90), ("sl120", 120), ("sl180", 180)],
    "fleet": [("fleetm", -1), ("base", 0), ("fleetp", 1)],
    "budget": [("b100", 100), ("b250", 250), ("b500", 500), ("base", 1000), ("b2000", 2000)],
    "drones": [
        ("d1s2", "1/2"), ("d1s3", "1/3"), ("d1s4", "1/4"),
        ("d2s2", "2/2"), ("base", "2/3"), ("d2s4", "2/4"),
        ("d3s3", "3/3"), ("d3s4", "3/4"),
    ],
}


def fair(ep):
    if ep.get("cost_fair") is not None:
        return ep["cost_fair"]
    if ep.get("status") == "COMPLETED_VERIFIED" and ep.get("cost") is not None:
        return ep["cost"]
    return ep.get("ground_finish_cost")


def load_rows(spec_id: str):
    if spec_id == "base":
        rows = json.loads((RES / "round11_final" / "episodes.json").read_text())
        return [r for r in rows if 3001 <= int(r["seed"]) <= 3010]
    path = RES / "round12" / spec_id / "episodes.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _boot(case_rels):
    """case_rels[case] = list of (sr, rx, sx). 种子在案例内放回，三段用同一次抽样。"""
    rng = random.Random(BOOT_SEED)
    keys = [c for c in CASES if case_rels.get(c)]
    out = {k: [] for k in ("sr", "rx", "sx")}
    if not keys:
        return {k: (None, None, None) for k in out}
    for _ in range(N_BOOT):
        stats = {k: [] for k in out}
        for c in keys:
            pool = case_rels[c]
            draw = [pool[rng.randrange(len(pool))] for _ in range(len(pool))]
            for i, name in enumerate(("sr", "rx", "sx")):
                stats[name].append(sum(row[i] for row in draw) / len(draw))
        for name in out:
            out[name].append(sum(stats[name]) / len(stats[name]))
    result = {}
    for name, samples in out.items():
        samples.sort()
        result[name] = (samples[int(0.025 * N_BOOT)], samples[int(0.975 * N_BOOT)])
    return result


def summarize(rows):
    by = defaultdict(list)
    complete = {s: 0 for s in "SRX"}
    times = {s: {"wall": 0.0, "alns": 0.0, "milp": 0.0, "init": 0.0, "replay": 0.0} for s in "SRX"}
    cross = {}
    nominal_s = {}
    missing = []
    n = len(rows)
    for r in rows:
        cs = r["S_nominal"]["cost"]
        nominal_s[r["case"]] = cs
        cross[r["case"]] = r["X_nominal"].get("n_cross")
        fs, fr, fx = fair(r["S"]), fair(r["R"]), fair(r["X"])
        for name in "SRX":
            ep = r[name]
            if ep.get("status") == "COMPLETED_VERIFIED":
                complete[name] += 1
            for key, field in (("wall", "wall"), ("alns", "time_alns"), ("milp", "time_milp"),
                               ("init", "time_init"), ("replay", "time_replay")):
                times[name][key] += float(ep.get(field) or 0.0)
        if None in (fs, fr, fx) or cs is None:
            missing.append({"case": r["case"], "seed": r["seed"],
                            "S": r["S"].get("status"), "R": r["R"].get("status"),
                            "X": r["X"].get("status")})
            continue
        by[r["case"]].append(((fr - fs) / cs, (fx - fr) / cs, (fx - fs) / cs))
    per = {}
    acc = {"sr": [], "rx": [], "sx": []}
    for c in CASES:
        pairs = by.get(c) or []
        if not pairs:
            per[c] = None
            continue
        means = [sum(row[i] for row in pairs) / len(pairs) for i in range(3)]
        per[c] = {"n": len(pairs), "sr": means[0], "rx": means[1], "sx": means[2]}
        for name, val in zip(("sr", "rx", "sx"), means):
            acc[name].append(val)
    equal = {k: (sum(v) / len(v) if v else None) for k, v in acc.items()}
    ci = _boot(by)
    return {
        "n_rows": n,
        "n_priced": sum(len(v) for v in by.values()),
        "missing": missing,
        "complete": complete,
        "cross_by_case": cross,
        "cross_total": None if not cross else sum(cross.values()),
        "nominal_s": nominal_s,
        "per_case": per,
        "equal": equal,
        "ci": {k: list(v) if v[0] is not None else None for k, v in ci.items()},
        "times": times,
    }


def main():
    ids = ["base"]
    for pairs in FACTORS.values():
        for spec_id, _ in pairs:
            if spec_id not in ids:
                ids.append(spec_id)
    clean = {}
    for spec_id in ids:
        rows = load_rows(spec_id)
        clean[spec_id] = None if rows is None else summarize(rows)
    payload = {"factors": {k: [[a, b] for a, b in v] for k, v in FACTORS.items()},
               "specs": clean}
    dest = RES / "round12_summary.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(dest)
    for spec_id, rec in clean.items():
        if rec is None:
            print(f"{spec_id}: MISSING")
            continue
        eq = rec["equal"]
        ci = rec["ci"]["sx"]
        print(f"{spec_id}: n={rec['n_priced']} SX={eq['sx']} CI={ci} "
              f"SR={eq['sr']} RX={eq['rx']} cross={rec['cross_total']} "
              f"done={rec['complete']}")


if __name__ == "__main__":
    main()
