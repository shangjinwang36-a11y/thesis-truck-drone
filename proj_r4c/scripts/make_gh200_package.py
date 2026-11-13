"""把 Gehring & Homberger 200 客户实例（C1_2_1, R1_2_1, RC1_2_1）转成本项目数据格式（试验用，round3d）。

转换规则（与现有 C/R/RC 50/100 算例的"外形"保持一致；注意：现有 6 个算例的原始转换方法在规范中并未给出，
我用 Solomon 100 客户实例做过仿射拟合，均不吻合（最大误差 6.9–12 km），因此无法"复刻"原转换，只能保持统计外形一致）：
  * 坐标：GH 坐标 0–140、仓库 (70,70) → 米：x_m = x*10000/70，仓库落在 (10000,10000)，范围正好 0–20000 m
    （与现有算例同为 20 km×20 km、仓库居中；客户数翻倍时面积不变，密度随客户数上升，和 50→100 一致）。
  * 时间窗、服务时间、车辆容量、GH 的需求量：全部忽略（本项目没有客户时间窗，地面服务固定 50 s，空送 60 s）。
  * 包裹质量：沿用现有算例的质量分布，按 200 客户等比放大——
      20% 0.2 kg, 30% 0.5 kg, 30% 1.0 kg, 12% 2.0 kg, 6% 3.0 kg, 2% 5.0 kg（即 40/60/60/24/12/4 个，总 202 kg），
    用 crc32(case_id) 为种子的随机排列分配给客户；再整体 ×0.8（轻型配置，上限 5.0→4.0 kg，总 161.6 kg），不截断。
  * 车队：200 客户 15 车（50→5、100→8、200→15，约 13 客户/车；建议值，不是文献规定值）；
    light2（默认）每车 3 槽、开局 2 架（30 机），light1 每车开局 1 架（15 机）；换电、E_min=0.10 与 package_light.json 相同。
用法: python scripts/make_gh200_package.py
"""
import copy, hashlib, json, random, zlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
SRC = {"C200": ("C1_2_1", "C"), "R200": ("R1_2_1", "R"), "RC200": ("RC1_2_1", "RC")}
MASS = [0.2] * 40 + [0.5] * 60 + [1.0] * 60 + [2.0] * 24 + [3.0] * 12 + [5.0] * 4
TRUCKS = 15


def parse(path):
    txt = path.read_text()
    rows = [l.split() for l in txt.split("CUST NO.")[1].splitlines()[2:] if l.strip()]
    return [(int(r[0]), float(r[1]), float(r[2])) for r in rows]


base = json.loads((root / "data" / "package_light.json").read_text(encoding="utf-8"))
cases, mani = [], []
for cid, (fname, fam) in SRC.items():
    p = root / "data" / "gh200" / f"{fname}.TXT"
    pts = parse(p)
    depot, cust = pts[0], pts[1:]
    assert depot[1:] == (70.0, 70.0) and len(cust) == 200
    masses = MASS[:]
    random.Random(zlib.crc32(cid.encode())).shuffle(masses)
    rows = [[i, round(x * 10000 / 70, 6), round(y * 10000 / 70, 6), round(m * 0.8, 10)] for (i, x, y), m in zip(cust, masses)]
    cases.append({"case_id": cid, "family": fam, "depot_xy_m": [10000.0, 10000.0],
                  "customer_columns": ["id", "x_m", "y_m", "mass_kg"], "customers": rows})
    mani.append({"case_id": cid, "n_customers": 200, "total_mass_kg": sum(r[3] for r in rows), "base_data_sha256": None,
                 "source_file_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "source_instance": fname})


def build(drones, name):
    out = copy.deepcopy(base)
    out["package_id"] = base["package_id"] + f"-gh200-{name}"
    out["cases"], out["case_manifest"] = cases, mani
    out["config"]["truck_count"] = TRUCKS
    out["config"]["drones_per_truck_initial"] = drones
    out["config"]["drone_count"] = drones * TRUCKS
    out["case_fleet"] = {c: {"truck_count": TRUCKS, "drone_count": drones * TRUCKS} for c in SRC}
    out["algorithm_experiment_protocol"] = copy.deepcopy(base["algorithm_experiment_protocol"])
    out["algorithm_experiment_protocol"]["main"]["case_ids"] = list(SRC)
    out["light_config_notes"] = dict(base["light_config_notes"], gh200=(
        "Gehring&Homberger 200-customer C1_2_1/R1_2_1/RC1_2_1 (SINTEF TOP); coords x*10000/70 (depot->(10000,10000)); "
        "time windows/service/demand ignored; masses from the 50/100-case distribution scaled to 200 (seeded shuffle) x0.8; "
        f"{TRUCKS} trucks, {drones} drone(s)/truck"))
    return out


for drones, name in ((2, "light2"), (1, "light1")):
    pkg = build(drones, name)
    (root / "data" / f"package_gh200_{name}.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
for m in mani:
    print(m["case_id"], m["source_instance"], m["total_mass_kg"], m["source_file_sha256"][:12])
