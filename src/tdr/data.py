"""数据提取、校验与实例导入（第8章、12.5节）."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BEGIN_PKG = "===BEGIN_EMBEDDED_PACKAGE_JSON==="
END_PKG = "===END_EMBEDDED_PACKAGE_JSON==="
BEGIN_SRC = "===BEGIN_EVENT_DEMO_PYTHON==="
END_SRC = "===END_EVENT_DEMO_PYTHON==="

EXPECTED_PACKAGE_SHA256 = "99536ff49336b264289fa2bf1d7cc4abb82b26d93e1645f09c203cfdbc5ca6fb"
EXPECTED_SOURCE_SHA256 = "847814f835744ed3383f1c0b35b4752458ed9e90bd48e1a454c772a0a0aac437"


def canonical_json_sha256(obj: Any) -> str:
    """附录A规定的规范化哈希."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_from_spec(spec_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """从完整TXT中提取附录A JSON与附录B源码，写出数据包与reference/."""
    with open(spec_path, "r", encoding="utf-8", newline="") as f:
        spec_text = f.read()
    ia = spec_text.index(BEGIN_PKG) + len(BEGIN_PKG)
    ib = spec_text.index(END_PKG)
    raw_json = spec_text[ia:ib].strip("\n")
    package = json.loads(raw_json)

    ic = spec_text.index(BEGIN_SRC) + len(BEGIN_SRC)
    id_ = spec_text.index(END_SRC)
    source = spec_text[ic:id_].strip("\r\n") + "\n"

    pkg_hash = canonical_json_sha256(package)
    src_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

    out = Path(out_dir)
    (out / "cases").mkdir(parents=True, exist_ok=True)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    with open(out / "package.json", "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=1)
    for case in package["cases"]:
        with open(out / "cases" / f"{case['case_id']}.json", "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=1)
    with open(out / "reference" / "dynamic_events_v3.py", "w", encoding="utf-8", newline="") as f:
        f.write(source)
    (out / "reference" / "SOURCE_SHA256.txt").write_text(src_hash + "\n", encoding="utf-8")
    meta = {
        "package_sha256": pkg_hash,
        "package_sha256_expected": EXPECTED_PACKAGE_SHA256,
        "package_sha256_match": pkg_hash == EXPECTED_PACKAGE_SHA256,
        "source_sha256": src_hash,
        "source_sha256_expected": EXPECTED_SOURCE_SHA256,
        "source_sha256_match": src_hash == EXPECTED_SOURCE_SHA256,
        "schema_version": package.get("schema_version"),
        "package_id": package.get("package_id"),
        "n_cases": len(package.get("cases", [])),
        "n_customers": sum(len(c["customers"]) for c in package.get("cases", [])),
    }
    (out / "extract_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


@dataclass(frozen=True)
class Customer:
    customer_id: str  # c001
    parcel_id: str    # p001
    x: float
    y: float
    mass_kg: float


@dataclass(frozen=True)
class Instance:
    case_id: str
    family: str
    depot_x: float
    depot_y: float
    customers: tuple[Customer, ...]

    @property
    def n(self) -> int:
        return len(self.customers)

    def coords(self, cid: str) -> tuple[float, float]:
        c = self._by_id[cid]
        return c.x, c.y

    @property
    def _by_id(self) -> dict[str, Customer]:
        d = getattr(self, "_cache", None)
        if d is None:
            d = {c.customer_id: c for c in self.customers}
            object.__setattr__(self, "_cache", d)
        return d

    def customer(self, cid: str) -> Customer:
        return self._by_id[cid]

    def mass(self, cid: str) -> float:
        return self._by_id[cid].mass_kg

    def all_customer_ids(self) -> tuple[str, ...]:
        return tuple(c.customer_id for c in self.customers)

    @property
    def parcel_mass(self) -> dict[str, float]:
        d = getattr(self, "_pm", None)
        if d is None:
            d = {c.parcel_id: c.mass_kg for c in self.customers}
            object.__setattr__(self, "_pm", d)
        return d

    @property
    def parcel_to_customer(self) -> dict[str, str]:
        d = getattr(self, "_p2c", None)
        if d is None:
            d = {c.parcel_id: c.customer_id for c in self.customers}
            object.__setattr__(self, "_p2c", d)
        return d


def load_instance(pkg: dict[str, Any], case_id: str) -> Instance:
    for case in pkg["cases"]:
        if case["case_id"] != case_id:
            continue
        depot = case["depot_xy_m"]
        custs = []
        for row in case["customers"]:
            idx, x, y, m = row[0], row[1], row[2], row[3]
            custs.append(Customer(f"c{idx:03d}", f"p{idx:03d}", float(x), float(y), float(m)))
        custs.sort(key=lambda c: c.customer_id)
        return Instance(case_id, case["family"], float(depot[0]), float(depot[1]), tuple(custs))
    raise KeyError(f"case not found: {case_id}")


def validate_package(pkg: dict[str, Any]) -> dict[str, Any]:
    """按12.5(2)检查数据、配置与协议一致性."""
    errors: list[str] = []
    warnings: list[str] = []
    meta: dict[str, Any] = {"schema_version": pkg.get("schema_version")}

    if pkg.get("schema_version") != "tdr-6.1":
        errors.append(f"schema_version 应为 tdr-6.1，实际 {pkg.get('schema_version')!r}")
    cfg = pkg.get("config", {})
    light = cfg.get("profile") == "light"
    for key, expected in ([] if light else [
        ("truck_count", 5), ("drone_count", 5), ("truck_drone_slots", 2),
        ("truck_recovery_channels", 1), ("drone_payload_limit_kg", 30),
        ("battery_kwh", 3.9688), ("reserve_fraction", 0.1),
        ("ground_service_s", 50), ("air_service_s", 60), ("prepare_s", 30),
        ("launch_s", 10), ("recovery_s", 30), ("handover_s", 20),
        ("slot_ac_kw", 2.0), ("truck_ac_kw", 4.0), ("truck_initial_ac_kwh", 4.0),
        ("slot_efficiency", 0.9), ("aux_efficiency", 0.85), ("depot_efficiency", 0.9),
        ("electricity_cny_kwh", 0.731012), ("truck_speed_m_s", 25 / 3),
        ("drone_speed_m_s", 15), ("shift_slack_s", 1800),
    ]):
        got = cfg.get(key)
        if got is None or abs(float(got) - float(expected)) > 1e-12:
            errors.append(f"config.{key} 应为 {expected}，实际 {got!r}")

    if light:
        # 资源梯度变体（round3d）：每车开局 1 或 2 架；换电（默认）或沿用原规范的车载充电
        swap = bool(cfg.get("swap_mode"))
        if cfg.get("drones_per_truck_initial") not in (1, 2):
            errors.append(f"light config.drones_per_truck_initial 应为 1 或 2，实际 {cfg.get('drones_per_truck_initial')!r}")
        exp_list = [("battery_kwh", 0.5), ("reserve_fraction", 0.1), ("truck_drone_slots", 3),
                    ("drone_payload_limit_kg", 4.0),
                    ("ground_service_s", 50), ("air_service_s", 60), ("shift_slack_s", 1800),
                    ("electricity_cny_kwh", 0.731012), ("drone_speed_m_s", 60.0 / 3.6)]
        if swap:
            exp_list += [("swap_s", 60.0), ("spare_batteries", 4), ("slot_ac_kw", 0.0)]
        else:  # 轻型机 + 车载充电：充电参数与原规范相同
            exp_list += [("slot_ac_kw", 2.0), ("truck_ac_kw", 4.0), ("truck_initial_ac_kwh", 4.0),
                         ("slot_efficiency", 0.9), ("aux_efficiency", 0.85)]
        for key, expected in exp_list:
            got = cfg.get(key)
            if got is None or abs(float(got) - float(expected)) > 1e-9:
                errors.append(f"light config.{key} 应为 {expected}，实际 {got!r}")
    mass_cap = 4.0 if light else 30.0
    cases = pkg.get("cases", [])
    names = [c["case_id"] for c in cases]
    expected_names = ["C50", "R50", "RC50", "C100", "R100", "RC100"]
    gh200 = names == ["C200", "R200", "RC200"]  # round3d：200 客户试验包（Gehring&Homberger），不属于 450 客户标准包
    if gh200:
        expected_names = names
    if names != expected_names:
        errors.append(f"cases 名称顺序应为 {expected_names}，实际 {names}")
    total = 0
    total_mass = 0.0
    for case in cases:
        n_expected = int("".join(ch for ch in case["case_id"] if ch.isdigit()))
        rows = case["customers"]
        if len(rows) != n_expected:
            errors.append(f"{case['case_id']}: 客户数 {len(rows)} != {n_expected}")
        ids = [int(r[0]) for r in rows]
        if len(set(ids)) != len(ids):
            errors.append(f"{case['case_id']}: 客户ID重复")
        if sorted(ids) != list(range(1, n_expected + 1)):
            warnings.append(f"{case['case_id']}: 客户ID不是1..{n_expected}连续")
        mass = 0.0
        for r in rows:
            if len(r) != 4:
                errors.append(f"{case['case_id']}: 行 {r} 不是4列")
                continue
            for v in r[1:]:
                if not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
                    errors.append(f"{case['case_id']}: 非有限数值 {r}")
            m = float(r[3])
            if m <= 0 or m > mass_cap + 1e-9:
                errors.append(f"{case['case_id']}: 质量越界 {r}")
            mass += m
        total += len(rows)
        total_mass += mass
        mani = next((m for m in pkg["case_manifest"] if m["case_id"] == case["case_id"]), None)
        if mani is None:
            errors.append(f"{case['case_id']}: case_manifest 缺失")
        else:
            if mani["n_customers"] != len(rows):
                errors.append(f"{case['case_id']}: manifest 客户数不符")
            if abs(mani["total_mass_kg"] - mass) > 1e-6:
                errors.append(f"{case['case_id']}: manifest 总质量 {mani['total_mass_kg']} != {mass}")
            base_obj = case
            got = canonical_json_sha256(base_obj)
            if got != mani["base_data_sha256"]:
                warnings.append(f"{case['case_id']}: base_data_sha256 与按本实现重建的规范化对象不一致")
    if total != (600 if gh200 else 450):
        errors.append(f"总客户数应为{600 if gh200 else 450}，实际 {total}")
    exp_mass = (606.0 if gh200 else 454.5) * (0.8 if light else 1.0)
    if abs(total_mass - exp_mass) > 1e-6:
        errors.append(f"总质量应为{exp_mass}，实际 {total_mass}")

    ap = pkg.get("algorithm_protocol", {})
    dp = ap.get("default_parameters", {})
    if dp.get("algorithm_id") != "tdr_alns_v61":
        errors.append("algorithm_id 必须为 tdr_alns_v61")
    if ap.get("algorithm_id") != "tdr_alns_v61":
        errors.append("algorithm_protocol.algorithm_id 必须为 tdr_alns_v61")
    for k in ["destroy_operators", "repair_operators", "nominal_eval_budget",
              "recovery_wallclock_seconds", "base_algorithm_seed", "mip_window_max_events"]:
        if k not in dp:
            errors.append(f"algorithm_protocol.default_parameters 缺少 {k}")
    if dp.get("nominal_eval_budget") != cfg.get("nominal_candidate_evaluations"):
        errors.append("nominal_eval_budget 与 config.nominal_candidate_evaluations 不一致")
    if abs(float(dp.get("recovery_wallclock_seconds", 0)) - float(cfg.get("recovery_time_limit_s", 0))) > 1e-9:
        errors.append("recovery_wallclock_seconds 与 config.recovery_time_limit_s 不一致")
    if pkg.get("experiment_protocol", {}).get("failure_generator_version") != "customer-failure-v3-1":
        errors.append("failure_generator_version 必须为 customer-failure-v3-1")
    if not cfg.get("formal_experiments_enabled", False):
        warnings.append("formal_experiments_enabled=false")

    meta.update({
        "n_cases": len(cases),
        "n_customers": total,
        "total_mass_kg": total_mass,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    })
    return meta
