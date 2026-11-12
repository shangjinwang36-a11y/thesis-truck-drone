"""物理与算法配置：从数据包统一配置读取，不在代码中另设未登记默认值。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PhysicalConfig:
    truck_count: int = 5
    drone_count: int = 5
    drones_per_truck_initial: int = 1
    truck_drone_slots: int = 2
    truck_recovery_channels: int = 1
    truck_speed_m_s: float = 25.0 / 3.0
    drone_speed_m_s: float = 15.0
    drone_payload_limit_kg: float = 30.0
    battery_kwh: float = 3.9688
    reserve_fraction: float = 0.1
    beta_cruise: float = 1.0
    beta_hover: float = 1.0
    ground_service_s: float = 50.0
    air_service_s: float = 60.0
    prepare_s: float = 30.0
    launch_s: float = 10.0
    recovery_s: float = 30.0
    handover_s: float = 20.0
    charge_ready_delay_s: float = 0.0
    slot_ac_kw: float = 2.0
    truck_ac_kw: float = 4.0
    truck_initial_ac_kwh: float = 4.0
    slot_efficiency: float = 0.90
    aux_efficiency: float = 0.85
    depot_efficiency: float = 0.90
    diesel_l_100km: float = 14.9
    diesel_cny_l: float = 8.57
    maintenance_cny_km: float = 0.40
    driver_cny_h: float = 105976.0 / 2088.0
    electricity_cny_kwh: float = 0.731012
    shift_slack_s: float = 1800.0
    tolerance_cost_cny: float = 1e-4
    tolerance_time_s: float = 1e-3
    tolerance_energy_kwh: float = 1e-6

    # ---- derived ----
    @property
    def e_cap(self) -> float:
        return self.battery_kwh

    @property
    def e_min(self) -> float:
        return self.reserve_fraction * self.battery_kwh

    @property
    def p0(self) -> float:
        return self.battery_kwh / (29.0 / 60.0)

    @property
    def p30(self) -> float:
        return self.battery_kwh / (18.0 / 60.0)

    @property
    def c_km(self) -> float:
        return self.diesel_cny_l * self.diesel_l_100km / 100.0 + self.maintenance_cny_km

    @property
    def cost_depot_kwh(self) -> float:
        return self.electricity_cny_kwh / self.depot_efficiency

    @property
    def cost_vehicle_kwh(self) -> float:
        return self.electricity_cny_kwh / (self.aux_efficiency * self.slot_efficiency)

    @property
    def wage_per_s(self) -> float:
        return self.driver_cny_h / 3600.0

    def hover_power(self, mass_kg: float) -> float:
        m = max(0.0, min(self.drone_payload_limit_kg, mass_kg))
        return self.beta_hover * (self.p0 + (self.p30 - self.p0) * m / 30.0)

    def reference_range_m(self, mass_kg: float) -> float:
        m = max(0.0, min(self.drone_payload_limit_kg, mass_kg))
        return 28000.0 - 400.0 * m

    def fly_energy_kwh(self, distance_m: float, mass_kg: float) -> float:
        return self.beta_cruise * self.battery_kwh * distance_m / self.reference_range_m(mass_kg)

    def hover_energy_kwh(self, seconds: float, mass_kg: float) -> float:
        return self.hover_power(mass_kg) * seconds / 3600.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PhysicalConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AlgorithmConfig:
    algorithm_id: str = "tdr_alns_v61"
    algorithm_variant: str = "full"
    base_algorithm_seed: int = 20261111
    destroy_operators: list[str] = field(default_factory=lambda: [
        "RANDOM_DEPENDENCY", "AFFECTED_SORTIE", "RENDEZVOUS_RESOURCE",
        "ENERGY_CHAIN", "SUPPORT_VISIT", "SORTIE_REGROUP"])
    repair_operators: list[str] = field(default_factory=lambda: ["GREEDY_PROXY", "REGRET2_PROXY"])
    destroy_fraction_min: float = 0.10
    destroy_fraction_max: float = 0.30
    operator_initial_weight: float = 1.0
    operator_min_weight: float = 0.1
    weight_segment_iterations: int = 25
    weight_reaction: float = 0.2
    score_global_best: float = 33.0
    score_current_improvement: float = 9.0
    score_other_accepted: float = 3.0
    score_rejected: float = 0.0
    repair_candidate_batch: int = 64
    repair_scan_limit: int = 512
    sa_initial_worse_fraction: float = 0.01
    sa_initial_acceptance_probability: float = 0.5
    sa_final_temperature_ratio: float = 0.01
    nominal_eval_budget: int = 1000
    nominal_air_bootstrap_eval_budget: int = 100
    recovery_wallclock_seconds: float = 60.0
    final_verification_reserve_seconds: float = 2.0
    deterministic_recovery_eval_budget: int = 1000
    # 第一轮修改（修复2）：恢复初始化（残段候选 + 接机目录枚举）单独记账，S/X 相同上限；
    # recovery 预算（250/1000...）只管 ALNS 主循环。
    recovery_init_eval_budget: int = 100
    # 变体开关（第二/三轮）：基线 = round1（"catalog" + "roulette"）
    recovery_decision: str = "catalog"      # "catalog"（基线） | "milp"（变体 B）
    operator_selector: str = "roulette"     # "roulette"（基线） | "qlearn"（变体 A）
    qtable_path: str | None = None          # 变体 A：已训练的 Q 表（JSON）
    qlearn_eval_epsilon: float = 0.05       # 变体 A 评价时的随机探索概率（Q 表冻结）
    # 第二轮修改：算法改进开关（全部默认开启；设为 False 即回到第一轮行为）
    air_promote_ops: bool = True            # 额外的 GROUND_TO_AIR 破坏 + AIR_FIRST 修复算子
    geometry_new_sortie_only: bool = True   # 仅当本轮新建了航次才评 5 个 λ 起点，否则只评继承 λ
    coordinate_light: bool = True           # ALNS 内的坐标细化：沿用已知评价、最多 coordinate_light_cap 次额外评价
    coordinate_light_cap: int = 12
    nominal_descent: bool = True            # 名义计划：成本驱动的"转空送"下降作为启动阶段
    nominal_descent_eval_budget: int = 200  # 下降阶段的评价上限（计入 1000 次名义总预算）
    nominal_two_start: bool = True          # 双起点：下降起点与块转换起点各跑一小段 ALNS，择优后用余下预算
    nominal_start_slice: int = 150          # 每个起点的试跑评价数（全部计入 1000 次总预算）
    max_search_rounds: int = 2000
    geometry_base_starts: int = 5
    coordinate_polish_every_alns_iterations: int = 10
    coordinate_extra_eval_cap: int = 40
    coordinate_initial_step: float = 0.25
    coordinate_shrink: float = 0.5
    coordinate_min_step: float = 0.001
    mip_period_rounds: int = 25
    mip_stagnation_rounds: int = 20
    mip_min_interval_rounds: int = 5
    mip_window_max_events: int = 6
    mip_online_time_limit_seconds: float = 2.0
    mip_node_limit: int = 1000
    cost_tolerance_yuan: float = 1e-4
    time_tolerance_seconds: float = 1e-3
    energy_tolerance_kwh: float = 1e-6
    decision_latency_seconds: float = 0.0
    # 运行预算覆盖（开发用；记录在运行元数据中）
    nominal_time_limit_s: float | None = None
    nominal_eval_budget_override: int | None = None
    recovery_eval_budget_override: int | None = None
    recovery_time_limit_override_s: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AlgorithmConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class SearchBudget:
    """一次求解调用的预算口径."""

    mode: str  # "nominal" | "recovery"
    eval_budget: int
    wallclock_s: float | None = None  # None 表示计数模式

    def is_wallclock(self) -> bool:
        return self.wallclock_s is not None


def load_package(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def configs_from_package(pkg: dict[str, Any]) -> tuple[PhysicalConfig, AlgorithmConfig]:
    phys = PhysicalConfig.from_dict(pkg["config"])
    alg = AlgorithmConfig.from_dict(pkg["algorithm_protocol"]["default_parameters"])
    return phys, alg
