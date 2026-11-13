# 毕业论文项目评估报告（只读评估，未改动任何代码）

评估时间：2026-11-12（Asia/Shanghai）
项目副本：`/workspace/thesis/proj`（已按 cp936 重新解压，共 203 个文件；乱码的 `/workspace/thesis/project` 已删除）
虚拟环境：`/workspace/thesis/venv`（Python 3.11，`pip install -e .` 成功）

## 1. 论文问题与模型（通俗版）

- 研究对象：5 辆卡车 + 5 架无人机从同一仓库出发，给 50 或 100 个客户送货（共六张图 C50/R50/RC50/C100/R100/RC100，450 条客户记录）。卡车沿路送货，无人机可在卡车行驶轨迹上任意位置放飞，带 1 件或多件货去空送；每车 2 个机位。
- 随机事件：每个环境种子随机选 1–2 个客户为“不能空投”（无人机到了才知道）。失败的货留在机上，无人机必须找一辆卡车在某个客户点停车把它接回（R），卸货交接（U），再由卡车地送（G）。
- 比较的两种政策：S = 只能被原放飞车接回；X = 可被任意合格卡车接回（可跨车）。两者在同一隐藏环境下配对，比较全班成本（油耗/里程 + 电费 + 司机工时）。必须算上电量、载荷、充电、机位、班次时限 H，且无人机最终只能随卡车回库，不能自己飞回仓库。
- 算法（规范指定的唯一算法）：事件触发的 ALNS 数学启发式（6 种移除 + 2 种修复 + 模拟退火 + 连续放飞位置搜索 + 固定结构下的时序/充电 LP + 局部事件重排 MILP）。发生失败即重新规划（滚动重优化）。
- 规范要求的研究结论是“据实报告”：不预设 X 一定更好，同点回收多也是合法结论；论文创新性须由实验支撑。

## 2. 规范（268 KB txt，12 章 + 附录 A/B）结构

0 规则 / 1 资源与位置 / 2 放飞 / 3 隐藏失效 / 4 恢复与回收 / 5 S/X 实验与统计 / 6 能量与成本 / 7 唯一算法与默认参数 / 8-9 数据与核验 / 10-11 文献 / 12 软件合同（模块、9 条命令、输出文件、测试 A–H）/ 附录 A 数据 JSON / 附录 B 事件参考源码。

## 3. 实现完成度（对照规范）

代码：`src/tdr/` 共 19 个文件、约 5300 行；测试 `tests/` 约 730 行。

| 规范要求 | 状态 | 说明 |
|---|---|---|
| 数据提取 + 哈希校验（`extract`）、校验（`validate`） | 完成 | `validate` 实跑：ok=true，450 客户 |
| 隐藏环境 `customer-failure-v3-1`、信息隔离、到点揭示 | 完成 | `hidden_world.py`、测试通过 |
| 能量/充电/成本公式（0.85/0.90/0.90 口径） | 完成（电费单位 bug 已在审计中修） | 嵌在 `config/schedule/evaluate` |
| 名义计划（1000 次评价，核验后保存） | 完成 | 六图均生成；C50 实跑 13 s，成本 246.64 元，1000 次评价 |
| 固定结构时序 + 充电 LP | **部分** | 用“前向最早传播 + 缺口驱动等待修复 + 充电 LP（HiGHS linprog）”，不是规范的三阶段 LP（参考构序/成本/z） |
| 局部 MILP（≤6 事件重排） | **部分（替代实现）** | 用 ≤6 事件排列枚举，没有 scipy.milp |
| ALNS：6 移除、2 修复、权重、SA | 完成（有简化） | D2–D6 无锚点时回退 D1；修复排序用代理分数，目录有截断 |
| 连续放飞位置搜索（5 起点 + 步长细化） | 完成 | `alns.coordinate_polish` |
| 恢复构造（S/X、接机目录、继续配送子集） | 完成，但**“推倒重建”** | 见第 5 节 P0 |
| 独立重放核验 | 完成 | `replay.py`；重放成本与评价成本最大差 2.3e-13 元 |
| 随机流派生（SHA256） | 完成 | 与规范公式一致 |
| 输出文件（账本、审计、图） | 基本完成 | 缺 `summary.csv`、`initial_assignment.json`（现为 csv） |
| CLI：extract/validate/nominal/simulate/experiment/smoke | 完成 | 均可运行 |
| CLI：`replay`、`experiment --stability`、`--ablation`、`--resume` | **缺失** | `python -m tdr replay` 实测报 invalid choice；README 无该命令。消融开关（full/uniform_weights/no_coordinate_polish/no_local_mip）在 alns.py 有，但无命令入口；稳定性/重复实验靠临时脚本，仓库中无脚本 |
| 60 秒墙钟在线模式 | 部分 | 代码有 `wall_limit` 参数和 `--recovery-wall-s`，但**从未跑过正式 60 s 矩阵** |
| 规范 12.3 的模块文件名（domain/energy/resources/state/event_simulator/operators/continuous/schedule_lp/local_mip/cost 等） | 未按名拆分 | 功能分散在 plan/schedule/evaluate/moves/simulate 等文件，未做 pyproject 以外的“requirements-lock” |
| 测试 A–H | 大部分 | 见第 4 节；H 中的“完整主实验 + 逐回合重放”只以缩减预算做过 |
| 正式实验（6 图 × 10 种子 × S/X，默认预算，120 回合；稳定性 360；消融 480） | **未按规范默认预算运行** | 仅 250/1000 次评价的开发预算 120 回合 + 360 回合重复；稳定性/消融均非规范命令生成 |

## 4. 测试与冒烟结果（本次实跑）

- `pytest -q`：**30 passed, 2 skipped, 1 warning（6.7 s）**。跳过的 2 项是 `tests/test_acceptance.py` 中依赖 `outputs/nominal` 目录存在的用例（“run nominal first”），该目录在副本中不在 `outputs/` 下（只有 outputs_summary），不是失败。warning 是 `TestWorld` 类名被 pytest 误当测试类，无害。
- `python -m tdr smoke`：3.4 s，退出 0；SMOKE8 名义成本 84.52 元；S/X 均 `COMPLETED_VERIFIED`，成本均为 92.89 元（该夹具中 S=X，只能证明流程通）。
- `python -m tdr nominal --case C50`：13.1 s，1000 次评价，成本 246.64 元，核验通过（与 outputs_summary/nominal2/C50 的 246.64 一致，可复现）。
- `python -m tdr simulate --case C50 --environment-seed 1 --recovery-eval-budget 250`：S 成本 245.38、X 成本 259.62，均 `COMPLETED_VERIFIED`，重放无违规，每回合约 0.6 s；与 doc 05 预算阶梯表中 250 档数字完全一致（可复现）。

## 5. 已有结果与是否合理（均引自 outputs_summary）

- 名义计划（nominal2）：C50 246.64、R50 581.65、RC50 542.54、C100 406.17、R100 722.65、RC100 655.68 元，全部重放核验通过。
- fixed1000（1000 次评价/次重规划，120 回合）：116/120 `COMPLETED_VERIFIED`，4 个 `STOPPED_NO_FEASIBLE_SUFFIX`（R100 seed3、seed9 的 S 与 X）；配对 n=58，均值 Δ(S−X)=+0.283 元，标准差 9.83，95% 区间 [−2.30, +2.87]，正/零/负 = 8/41/9；最小 −21.84，最大 +62.22。
- fixed250：同样 116/120；Δ 均值 −0.477 元，区间 [−2.155, +1.201]。
- 3 个算法种子重复（repeats/repeats1000）：250 档环境级 Δ=−0.729 [−1.997, +0.538]；1000 档 +0.478 [−1.751, +2.707]。同环境换算法种子，成本标准差均值 2.57/2.09 元、最大 30.30/23.04 元（来自 doc 05）。
- 另据 episodes.csv 统计：60 个环境中约 27 个“实际没观察到空投失败”，这些环境 S=X 成本完全相同；非零差值只有 15（250 档）/17（1000 档）个环境。
- 合理性：核验链路（重放）通过，恢复后成本略高于名义计划（如 C50 名义 246.64，S 均值约 252）符合直觉；旧结果 main250 已被审计证明有错址交付等 bug，并已作废（doc 03 标注作废）。**结论上 S/X 无显著差异、符号随预算翻转，目前不能写成“X 优于 S”**。
- 注意：doc 04 第五节第 5 条写“R100 seed9 仅 S 停止”，与后来 status_counts（S、X 各停 2 个）不一致，文档有陈旧内容；README 提到 `outputs/` 目录，但交付副本只有 `outputs_summary/`。

## 6. 已知问题（doc 06 + 本人阅读）

按影响排序：

1. **P0 恢复“推倒重建”**：故障时把名义计划的未来基本清空，再用贪心重建（`recovery._skeleton`）。ALNS 平均要补回 10.4 元（250 档）/16.9 元（1000 档）的构造损失，个别环境达 50–106 元；恢复成本与“故障额外成本”混在一起无法分开解释。→ 应改为以名义残段为基座做局部修复。
2. **P0 S/X 比较被预算分配污染**：X 的接机目录更大，初始化吃掉更多评价，250 档下 S 有 39 轮 ALNS、X 仅 16 轮（245.38 vs 259.62），差异主要是搜索预算而非政策效应；1000 档两者追平（247.22 vs 245.76，C50 seed1 阶梯实测）。
3. **P1 搜索质量不稳**：代理分数忽略等待/充电/H；退火进度绑定评价预算，使预算改变算法行为，预算阶梯成本非单调（S：245.38→247.22→250.39→244.82）；10/71 次重规划被 2000 轮上限先截停；ALNS 新建空送目录仍有截断（近 6 访问、前 4 位置）。
4. **P2 评价器可行域偏窄**：时序充电是启发式、局部重排是枚举而非 MILP；R100 seed3/seed9 仍无可行恢复（`STOPPED_NO_FEASIBLE_SUFFIX`），未证明真的无解。
5. **规范符合度缺口**：缺 `replay`/`--stability`/`--ablation`/`--resume` 命令；未跑规范默认预算（60 s 或 1000 评价计数）下的正式 120 回合、稳定性 360 回合、消融 480 回合；README 自己也声明“不冒充正式结果”。
6. 其他：模块文件名与规范 12.3 不一致（功能齐但分散）；27/60 环境没有观察到失败，使有效样本变少（规范允许，但论文需解释）；无 git 仓库、无 requirements-lock。

## 7. 建议（不作重新设计，供决策参考）

1. 先别重写。现有代码已通过 30 项测试、重放核验可信，是可用的基础。把“是否追求规范默认预算的正式实验”作为首要决策。
2. 最值得优先做的 3 件事：(a) 把恢复改为“名义残段 + 局部修复”（P0-1）；(b) 把 S/X 的 ALNS 迭代数/预算拆分对齐（P0-2），否则无法下政策结论；(c) 补齐 `replay`、`--stability`、`--ablation`、`--resume` 命令并把当时的临时脚本入库，使全部结果可由命令复现。
3. 完成 (a)(b) 后再以 1000 次评价计数模式跑规范的 120 回合 / 360 稳定性 / 480 消融；60 s 墙钟模式作为在线可行性补充。
4. 论文表述：当前阶段只能写“S/X 差异在 10 环境样本下不显著、对搜索预算敏感”；不要引用 main250 的 +1.45 元；不要宣称算法最优或政策优劣。
5. 对只会少量代码的用户：由 AI 完成上述修改并生成可复现命令，用户主要负责读懂 docs 02/04/05/06、核对口径，答辩时说清“模型、算法、验证、局限”。

## 8. 复现命令（均已在本次评估中成功运行）

```
cd /workspace/thesis/proj
../venv/bin/pytest -q                      # 30 passed, 2 skipped
../venv/bin/python -m tdr smoke --package data/package.json --out /workspace/thesis/smoke_out
../venv/bin/python -m tdr nominal --package data/package.json --case C50 --out /workspace/thesis/run/nominal
../venv/bin/python -m tdr simulate --package data/package.json --case C50 --environment-seed 1 --strategy both --nominal /workspace/thesis/run/nominal --out /workspace/thesis/run/single --recovery-eval-budget 250
```
