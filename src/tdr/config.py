"""物理与算法配置：从数据包统一配置读取，不在代码中另设未登记默认值。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# 当前生效的车队布局（由 set_active(phys) 在评价/调度入口刷新；供只拿到计划、拿不到 phys 的辅助函数使用）
ACTIVE: dict[str, int] = {"dpt": 1, "n_drones": 5, "n_trucks": 5}


def home_truck(drone: str) -> str:
    return f"t{(int(drone[1:]) - 1) // max(1, ACTIVE['dpt']) + 1}"


def home_drones(truck: str) -> list[str]:
    k = max(1, ACTIVE["dpt"])
    i = int(truck[1:])
    return [f"d{(i - 1) * k + j + 1}" for j in range(k) if (i - 1) * k + j + 1 <= ACTIVE["n_drones"]]


def all_drones() -> list[str]:
    return [f"d{i + 1}" for i in range(ACTIVE["n_drones"])]


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
    # ---- 第三轮：轻型机 / 换电配置（默认值 = 原规范，行为不变）----
    swap_mode: bool = False             # True：取消车载充电，改为机位换电
    swap_s: float = 60.0                # 换电时长（司机人工动作，卡车停靠时进行，与 G/P/R/U 串行）
    spare_batteries: int = 4            # 每车随车满电备用电池块数（整班累计可换次数上限）
    payload_ref_kg: float = 30.0        # 能量模型的参考载荷上限（插值端点）
    range_empty_m: float = 28000.0      # R0(m)=range_empty_m - range_slope_m_per_kg*m（外推到 0% 的参考航程）
    range_slope_m_per_kg: float = 400.0
    hover_min_empty: float = 29.0       # 空载悬停至 0% 的分钟数
    hover_min_ref: float = 18.0         # 参考载荷悬停至 0% 的分钟数
    tolerance_cost_cny: float = 1e-4
    tolerance_time_s: float = 1e-3
    tolerance_energy_kwh: float = 1e-6
    # 第四轮：规范 fixed_wait_cap_s=null（不设固定等待上限）。None=按规范；数值=旧版“单访问累计等待上限”(秒)，仅作敏感性对照
    energy_wait_cap_s: float | None = None
    # 第五轮 v5 变体(b)：软 H(加班)。soft_h=True 时 H_EXCEEDED 不再是违规，超出 H 的每车时间按 overtime_mult×时薪的
    # 加班工资计价(基础工资已按 1× 计入，故附加 (mult-1)×)；默认 False(基线模型不变)。劳动法第44条(一)：不低于 150%。
    soft_h: bool = False
    # 第五轮 v6 变体(a)：降落等待。回收阶段无法带备用电量抵达任何车的在飞/失败机，可降落在其下一个/当前客户点，
    # 落地等待零能耗、回收不要求备用电量(E_min)，由合格车辆(S 仅原放飞车，X 任意车)到该点接回；默认关。
    land_and_wait: bool = False
    overtime_mult: float = 1.5

    # ---- derived ----
    @property
    def e_cap(self) -> float:
        return self.battery_kwh

    @property
    def e_min(self) -> float:
        return self.reserve_fraction * self.battery_kwh

    @property
    def energy_tol(self) -> float:
        """第三轮：全库唯一的能量比较容差(kWh)；与 E_min、0 电量、E_cap 比较一律用它。"""
        return self.tolerance_energy_kwh

    @property
    def p0(self) -> float:
        return self.battery_kwh / (self.hover_min_empty / 60.0)

    @property
    def p30(self) -> float:          # 参考载荷处的悬停功率（名称沿用旧版）
        return self.battery_kwh / (self.hover_min_ref / 60.0)

    def set_active(self) -> "PhysicalConfig":
        ACTIVE["dpt"] = self.drones_per_truck_initial
        ACTIVE["n_drones"] = self.drone_count
        ACTIVE["n_trucks"] = self.truck_count
        return self

    def home_truck(self, drone: str) -> str:
        """无人机开局所在卡车：d1..d_k 按每车 drones_per_truck_initial 分配."""
        return f"t{(int(drone[1:]) - 1) // max(1, self.drones_per_truck_initial) + 1}"

    def home_drones(self, truck: str) -> list[str]:
        k = max(1, self.drones_per_truck_initial)
        i = int(truck[1:])
        return [f"d{(i - 1) * k + j + 1}" for j in range(k)
                if (i - 1) * k + j + 1 <= self.drone_count]

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
        return self.beta_hover * (self.p0 + (self.p30 - self.p0) * m / self.payload_ref_kg)

    def reference_range_m(self, mass_kg: float) -> float:
        m = max(0.0, min(self.drone_payload_limit_kg, mass_kg))
        return self.range_empty_m - self.range_slope_m_per_kg * m

    def fly_energy_kwh(self, distance_m: float, mass_kg: float) -> float:
        return self.beta_cruise * self.battery_kwh * distance_m / self.reference_range_m(mass_kg)

    def hover_energy_kwh(self, seconds: float, mass_kg: float) -> float:
        return self.hover_power(mass_kg) * seconds / 3600.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PhysicalConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def for_case(self, case_fleet: dict[str, Any] | None, case_id: str) -> "PhysicalConfig":
        """按算例覆盖车队规模（light 配置：50 客户 5 车 10 机，100 客户 8 车 16 机）."""
        if not case_fleet or case_id not in case_fleet:
            return self
        import dataclasses
        return dataclasses.replace(self, **case_fleet[case_id])


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
    nominal_truck_starts: bool = False      # 第三轮：True 时车队>5 辆则分别从"5 车"与"满车队"两个初解起步(各用完整预算)取低成本者
    nominal_reserve_margin: float = 0.0     # 第三轮：名义规划多留的储备（占 E_cap 的比例，如 0.03）。只在构造名义解时抬高 E_min，
                                            # 运行与重规划仍用真实储备；目的：减少重规划后非失败机"差一点点"导致的 STOPPED
    nominal_start_trucks: int | None = None  # 第三轮：指定名义初解启用的车数(其余车保留空路线)；None=满车队
    nominal_final_descent_frac: float = 0.15  # 第三轮：名义预算末尾留出此比例做一次"转空送"下降收尾（0=关闭）
    max_search_rounds: int = 2000
    # 第四轮：恢复目标重定位算子（在“当前最优计划”上重选接机车/接机点；S 只可选原放飞车的停靠点，
    # X 可选任意车——同一算子、同一评价次数/频率，仅资格不同；X 的跨车重定位即“X 专用部分”）
    recovery_retarget: bool = False
    retarget_period: int = 10
    retarget_n: int = 2
    # 第四轮：X 专用跨车算子(见 cross_ops.py)；仅当失败航次被≠原放飞车的车接回时才会触发，S 恒不触发；同一份预算
    cross_ops: bool = False
    cross_period: int = 5
    # 第五轮：恢复目录候选(try_recovery_reassign)是在名义残余计划(base)上重建的，不含当前 ALNS 进展；
    # False=旧行为（优于当前解即替换当前解，会丢弃已有进展）；True=仅当优于全局最优时才采用（S/X 对称）
    reassign_adopt_only_if_best: bool = False
    # 第五轮：恢复初始化无可行解且违规来自别的在飞无人机时，联合重选这些在飞航次的接机车/点（S/X 对称）
    joint_inflight_retarget: bool = False
    # 第五轮 v4：机位感知恢复(目录估计成本按接机车机位占用惩罚 + SLOT_OVER 时提前排队航次的放飞访问)，S/X 对称
    slot_aware_recovery: bool = False
    # 第五轮 v7：未起飞航次的能量违规修复(联合重选/兜底中)：改回收点 / 丢掉最后空送客户给地面 / 整个航次转地面，S/X 同一规则
    unlaunched_repair: bool = False
    cross_n: int = 2
    crn_per_iteration: bool = False          # 共同随机数：按(种子,算例,重规划,轮次)重置随机流（S/X 对称）
    cross_ops_gate: bool = True              # False=对照：同车情形也启用（S、X 同等）
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
