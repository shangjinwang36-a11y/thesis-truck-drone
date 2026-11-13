"""由 data/package_light.json（2 机/车 + 换电 + E_min 10%）派生资源梯度变体（round3d）。

  light1   : 每车开局 1 架（3 槽、换电不变）；50 客户 5 车 5 机，100 客户 8 车 8 机
  lightchg : 每车 2 架，取消换电，改回原规范的车载充电（slot 2 kW、车载 4 kW、初始预算 4 kWh、效率同原规范）
其余（轻型机、4 kg、E_min=0.10、车队、案例数据）与 package_light.json 完全相同。
用法: python scripts/make_light_variants.py
"""
import copy, json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = json.loads((root / "data" / "package_light.json").read_text(encoding="utf-8"))


def write(pkg, name):
    (root / "data" / name).write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")


p = copy.deepcopy(base)
p["package_id"] = base["package_id"] + "-1drone"
p["config"]["drones_per_truck_initial"] = 1
p["config"]["drone_count"] = p["config"]["truck_count"]
for c, f in p["case_fleet"].items():
    f["drone_count"] = f["truck_count"]
p["light_config_notes"] = dict(base["light_config_notes"], variant="1 drone per truck at start (3 slots, swap on); drone_count = truck_count")
write(p, "package_light_1drone.json")

q = copy.deepcopy(base)
q["package_id"] = base["package_id"] + "-chg"
q["config"].update({"swap_mode": False, "slot_ac_kw": 2.0, "truck_ac_kw": 4.0, "truck_initial_ac_kwh": 4.0})
q["light_config_notes"] = dict(base["light_config_notes"], swap="NOT USED in this variant: on-truck charging as in the original spec (slot 2 kW, truck budget 4 kWh initial, slot eff 0.9, aux eff 0.85); 2 drones/truck, 3 slots",
                               variant="light drone + charging instead of swap (2 drones/truck)")
write(q, "package_light_chg.json")
print("ok")
