# tdr —— 无人机随机空中交付失效后的车机协同恢复（V6.1 实现）

本仓库是《无人机随机空中交付失效_V6_1_Codex完整实施规范_20261111.txt》的可运行实现，
算法标识 `tdr_alns_v61`，项目版本 1.0.0，输出 `schema_version="1.0.0"`。

> **审计返工状态**：已按两轮审计
> 《DeepSeek实现审计_问题证据与Codex返工要求_20261111》与
> 《搜索预算与重复实验调整建议_新版本核查_20261111》完成修复：
> 目的地交付、货物保管、机体承运、机位连续占位、冻结边界、道路运动连续性、全程独立重放核验
> （含"未到场即地送"反例）、充电等待、**接机目录持续展开（全部车辆×全部客户×非前缀继续子集）**、
> **受影响航次的恢复邻域**、统一预算（局部重排与初始化也扣账）、统计公式与成功率。
> 结果：`outputs/nominal2`（共同名义计划）、`outputs/fixed250` 与 `outputs/fixed1000`（恢复预算对照）、
> `outputs/budget_ladder`（250/1000/5000/20000 阶梯）、`outputs/repeats*`（3 个算法基种子的独立重复）。
> 原 `outputs/main250` 保留为**调试记录**，不再作为研究结论。
> 逐项处理见 `docs/04_审计修复报告.md`、`docs/05_搜索预算与重复实验报告.md`。

> **状态声明（四态区分）**
> - **方法计划**：V6.1 规范，已完整实现为本文档所述流程。
> - **代码已实现**：数据提取/校验、物理与能量、前向调度、充电 LP、名义计划、隐藏失效仿真、
>   S/X 恢复 ALNS、连续放飞位置搜索、局部事件重排、独立核验、批量实验、六类图形、CLI。
> - **测试已通过**：`pytest`（见 `tests/`），`smoke`（见下）。
> - **正式实验**：**未按规范默认 60 s 预算运行**。本仓库记录的 120 回合是**250 次评价/次重规划的
>   缩减预算开发运行**，用于验证代码与流程，不冒充规范定义的正式结果。

---

## 1. 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e .
# 或仅设置 PYTHONPATH=src
```

依赖：Python ≥3.11、NumPy、SciPy（HiGHS）、matplotlib；测试用 pytest。

## 2. 快速开始

```bash
# 1) 从规范 TXT 提取附录A 数据包与附录B 参考源码（校验 SHA256）
python -m tdr extract --spec <完整TXT路径> --out data

# 2) 校验数据包
python -m tdr validate --package data/package.json

# 3) 六图名义计划（每图 1000 次完整评价）
python -m tdr nominal --package data/package.json --case all --out outputs/nominal

# 4) 单环境 S/X 配对
python -m tdr simulate --package data/package.json --case C50 --environment-seed 1 \
    --strategy both --nominal outputs/nominal --out outputs/single --recovery-eval-budget 250

# 5) 批量实验（六图 × 10 种子 × S/X）
python -m tdr experiment --package data/package.json --nominal-dir outputs/nominal \
    --cases all --seeds 10 --out outputs/main250 --recovery-eval-budget 250

# 6) 8 客户开发夹具
python -m tdr smoke --package data/package.json --out outputs/smoke
```

`--formal` 仅用于标记正式运行；当前实现默认恢复预算为确定性计数模式（`deterministic_recovery_eval_budget`），
如要按规范 60 s 墙钟运行，使用 `--recovery-wall-s 60`（本仓库未执行该预算的正式实验）。

## 3. 主要输出

- `outputs/nominal/<case>/`：`nominal_plan.json`、`cost.json`、`verification.json`、`config_snapshot.json`、
  `initial_assignment.csv`、`nominal_route.png`、`nominal_gantt.png`
- `outputs/<batch>/<case>_seedNN_<S|X>/`：`run_metadata.json`、`public_events.jsonl`、
  `private_world_audit.json`、`actions.csv`、`parcel_ledger.csv`、`charging_ledger.csv`、
  `recovery_ledger.csv`、`drone_terminal.csv`、`replans.jsonl`、`cost.json`、`result.json`、
  `verification.json`、`route.png`、`gantt.png`、`energy.png`
- `outputs/<batch>/`：`episodes.csv`、`paired_results.csv`、`summary.json`、`status_counts.csv`、`paired_delta.png`

## 4. 实现与规范的对应关系

| 规范 | 实现 | 说明 |
|---|---|---|
| 第6章 能量/充电/成本 | `energy` 公式内嵌 `config.PhysicalConfig`、`schedule.py`、`cost` 分项 | 巡航/悬停/服务/L/R/等待逐段按真实载荷；仓库补电与车载充电两种电费 |
| 7.15 固定结构时序 | `schedule.py` 固定点前向调度 + 分阶段充电 LP（HiGHS linprog） | 用前向传播替代三阶段 LP；成本/能量按真实口径 |
| 7.9 局部事件重排 | `local_reorder.py` 窗口 ≤6 的确定性排列枚举 | 未实现 HiGHS 整数模型 |
| 7.8 连续位置 | `alns.coordinate_polish` 5 起点 + 逐维 ±h，h→1e-3，40 次上限 | 与规范一致 |
| 7.5 两个修复器 | `moves.repair_greedy` / `repair_regret2`（代理分数） | 惰性目录简化为“每票取最优候选” |
| 7.6 六个移除算子 | `alns.destroy` | D2—D6 无锚点时回退 D1 |
| 7.7 权重与 SA | `alns.optimize` | 33/9/3/0 奖励、25 轮分段、T0 与降温公式 |
| 7.11 随机流 | `simulate.derive_rngs` | `tdr_v61|seed|case|phase|replan|stream` 的 SHA256 前 8 字节 |
| 3.x 隐藏环境 | `hidden_world.HiddenWorld` | `customer-failure-v3-1`，到点揭示、幂等、审计后置 |
| 12.6 输出 | `experiment.py` | 账本/审计/汇总/图形 |
| 12.8 测试 | `tests/` | 见下 |

## 5. 已知简化（诚实声明）

1. **时序**：前向最早可行传播，不是规范的三阶段 LP；不保证时间维最优。
2. **局部 MILP**：以排列枚举替代 HiGHS 整数模型（窗口仍 ≤6）。
3. **恢复构造**：快照后“骨架 + 重建”未来；跨车回收只在恢复初始枚举中决策，ALNS 不改变已开始残段的回收车。
4. **正式预算**：未按 60 s 运行；所有结果均记录 `recovery_eval_budget`。
5. **S/X 差异**：10 种子样本下均值区间跨 0，不能宣称显著；详见 `docs/03_实验与结果分析.md`。

## 6. 结果摘要（两轮审计修复后）

| 项目 | 250 次/次重规划 | 1000 次/次重规划 |
|---|---|---|
| 完成并重放核验 | 116/120 | 116/120 |
| 配对 n | 58 | 58 |
| Δ 均值（S−X） | −0.477 元 | +0.283 元 |
| 95% 区间 | [−2.155, +1.201] | [−2.301, +2.867] |
| 错址 G / 行驶不符 | 0 / 0 | 0 / 0 |
| 重放-评价成本差 | 2.3e-13 | 2.3e-13 |

- 三算法基种子重复（360 回合/档）：250 档环境级均值 −0.729、区间 [−1.997, +0.538]；1000 档 +0.478、区间 [−1.751, +2.707]；同一环境算法重复标准差均值 2.1—2.6 元、最大 30 元。
- 预算阶梯（C50 seed1，250/1000/5000/20000）：接机覆盖从 8—12 个客户扩到 50 个、X 的接机车辆从 2 辆扩到 5 辆；成本不随预算单调下降。
- **结论边界**：S/X 差值在两档预算下变号且区间跨 0，不能宣称政策优劣；正式 60 秒在线矩阵与 30 环境×5 算法种子的正式矩阵尚未运行。

## 7. 测试

```bash
pytest -q
```

覆盖：数据哈希与 450 客户、能量公式、全地送成本与独立前向公式一致、空送转换可行性、
隐藏环境确定性与幂等、端到端失效恢复回合。

## 8. 目录

```
src/tdr/            实现包
tests/              pytest
data/               提取后的数据包与参考源码
configs/            预留
docs/               研究思路梳理、实现说明、实验分析
outputs/            nominal / main250 等运行结果
reference/          附录B 原样源码（由 extract 写入 data/reference）
```
