"""由原规范数据包生成轻型机/换电配置数据包（第三轮）。原 data/package.json 不改动。

包裹质量规则（统一、可复现）：所有包裹质量 × 0.8（比例缩放）。原最大 5.0 kg → 4.0 kg，
分布形状（相对大小、比例）保持不变；不做截断。生成时报告：原 >4 kg 的包裹数、
缩放后实际数值发生变化的包裹数（= 全部）。
用法: python scripts/make_light_package.py [--trucks100 8] [--out data/package_light.json]
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

SCALE = 0.8
CASES50 = ["C50", "R50", "RC50"]
CASES100 = ["C100", "R100", "RC100"]


def build(trucks100: int = 8, trucks50: int = 5) -> tuple[dict, dict]:
    root = Path(__file__).resolve().parents[1]
    pkg = json.loads((root / "data" / "package.json").read_text(encoding="utf-8"))
    out = copy.deepcopy(pkg)
    cfg = out["config"]
    cfg.update({
        "profile": "light",
        "swap_mode": True, "swap_s": 60.0, "spare_batteries": 4,
        "truck_count": trucks50, "drone_count": 2 * trucks50, "drones_per_truck_initial": 2,
        "truck_drone_slots": 3,
        "drone_payload_limit_kg": 4.0, "payload_ref_kg": 4.0,
        "battery_kwh": 0.50, "reserve_fraction": 0.20,
        "drone_speed_m_s": 60.0 / 3.6,
        # R_use(m)=18000-1500m (到 20% 应急电量) -> 外推到 0% 的 R0(m)=R_use/0.8
        "range_empty_m": 22500.0, "range_slope_m_per_kg": 1875.0,
        "hover_min_empty": 22.5, "hover_min_ref": 15.0,
        "slot_ac_kw": 0.0, "truck_ac_kw": 0.0, "truck_initial_ac_kwh": 0.0,
    })
    out["case_fleet"] = {c: {"truck_count": trucks100, "drone_count": 2 * trucks100} for c in CASES100}
    out["case_fleet"].update({c: {"truck_count": trucks50, "drone_count": 2 * trucks50} for c in CASES50})
    rep = {"scale": SCALE, "cases": {}}
    for case, mani in zip(out["cases"], out["case_manifest"]):
        over = sum(1 for r in case["customers"] if r[3] > 4.0 + 1e-12)
        for r in case["customers"]:
            r[3] = round(r[3] * SCALE, 10)
        tot = sum(r[3] for r in case["customers"])
        mani["total_mass_kg"] = tot
        mani["base_data_sha256"] = None
        rep["cases"][case["case_id"]] = {
            "n": len(case["customers"]), "orig_over_4kg": over, "changed": len(case["customers"]),
            "orig_max": max(r[3] for r in pkg["cases"][out["cases"].index(case)]["customers"]),
            "new_max": max(r[3] for r in case["customers"]), "new_total_kg": tot}
    out["package_id"] = pkg.get("package_id", "tdr") + "-light"
    out["model_notes"] = list(out.get("model_notes", [])) if isinstance(out.get("model_notes"), list) else out.get("model_notes")
    out["light_config_notes"] = {
        "weights": f"all parcel masses x {SCALE} (max 5.0 -> 4.0 kg)",
        "swap": "battery swap at slot replaces on-truck charging; 60 s driver task before P; 4 spare full batteries per truck",
        "energy": "E_cap=0.5 kWh (assumption), reserve 20%, R_use(m)=18000-1500m, hover to 0%: 22.5 min empty / 15 min at 4 kg",
    }
    return out, rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trucks100", type=int, default=8)
    ap.add_argument("--out", default="data/package_light.json")
    a = ap.parse_args()
    out, rep = build(a.trucks100)
    root = Path(__file__).resolve().parents[1]
    path = root / a.out
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (path.with_suffix(".weights_report.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
