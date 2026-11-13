# 变体 B 修改日志：接机决策改用小型 MILP（HiGHS）

写给：代码基础薄弱、但要在论文里讲清楚“改了什么、为什么、效果如何”的同学。
代码：`/workspace/thesis/proj`，提交 `32f6459`（在第一轮 `654f5b6` 之上）。补丁：`/workspace/thesis/patch_B.patch`（`git diff 654f5b6 32f6459`）。
**开关**：默认**不变**（基线 = 第一轮 ALNS，`recovery_decision="catalog"`）；打开 B：命令行加 `--recovery-decision milp`（或 `AlgorithmConfig.recovery_decision="milp"`）。

## 1. 想解决什么
无人机失败后，需要决定三件事：**哪辆卡车来接这件失败包裹、在哪个停靠点/位置接、之后怎么在地面送达**（继续空送哪些余票）。第一轮是用“目录枚举 + 前 100 次评价挑最好”来选起点，再交给 ALNS 去改。B 把这一步换成一个**小的整数规划（MILP）**：残余的路线（其他卡车的名义路线）**固定不动**，只在“接机决策”这个小问题上求最优，再把前几个最优候选交给完整评价器核验，最好的当 ALNS 起点，ALNS 再优化其余部分。

## 2. S 和 X 的规则（和规范一致）
- **S**：只允许“原放飞卡车”接机（候选集合里只有那一辆车）。
- **X**：任意“可行”的卡车都可以（能量/时间上够得着的停靠点才进入模型）。
- 测试 `test_milp_entries_respect_s_and_x_rules` 检查：S 的所有候选都属原放飞车；X 的最优代理目标 ≤ S 的（X 的可选集合包含 S 的）。

## 3. 改了什么（文件 + 函数）
| 文件 | 内容 |
|---|---|
| `src/tdr/recovery_milp.py`（新） | `solve_recovery_milp(...)`：建模并用 `scipy.optimize.milp`（HiGHS）求解；`build_stops`、`_truck_timeline`、`_ground_cost` 生成每辆车的“可插入停靠点”与线性代价；用 **no-good 割** 依次求出前 K（默认 6）个不同的最优方案；每个方案变成一个“接机条目”（卡车、位置、继续空送子集）。 |
| `src/tdr/recovery.py` | `initial_recovery(..., use_milp, milp_top_k)`：候选顺序为 RESIDUAL →（MILP）→ CATALOG → REBUILD。MILP 条目走和目录候选**相同**的 `build_residual_candidate` 与 `evaluate_plan` 完整评价，所以**不会绕过任何可行性检查**。 |
| `src/tdr/simulate.py`、`config.py`、`cli.py`、`experiment.py`、`scripts/run_repeats.py` | 传开关、记录 `recovery_decision`、`milp_status`、`milp_wall_s`、`milp_surrogate_obj`、`milp_true_costs` 等统计、写入 `run_metadata.json`。 |
| `tests/test_variant_b.py`（新，4 个测试） | S/X 规则；B 的整局回放核验通过且不比残段候选差；默认仍是 catalog/roulette。 |

## 4. 重要的“诚实说明”（论文里别夸大）
MILP 用的是**线性代理模型**（把插入后的行驶/等待/地面送达代价近似为线性），**不是**对完整问题（含充电 LP、能量非线性等）的精确最优。所以准确的说法是：“在代理模型上精确求解，再用完整评价器对前 K 个解逐一核验并取最好”。为控制求解时间，对能量上够不到的停靠点做了剪枝，每辆车最多保留 12 个候选支持点，单次求解时限 3 秒（因此有少数 `FEASIBLE_LIMIT`，即时限内的可行解，不保证最优）。

代理模型好不好用的实测（1000 档批次，76 次重规划）：
- 代理排序第 1 的方案，在完整评价下就是（或并列）前 K 个里最好的：**56/76**；
- 它与真实最好之间的平均差：**0.46 元**，最大 6.80 元；
- 代理值与真实成本的 Spearman 相关（≥3 个有效候选的 65 次）平均 **0.71**。
- 求解状态：OPTIMAL 69 次、FEASIBLE_LIMIT 7 次；MILP 平均 0.28 秒/次，总计 21.5 秒（最大单次 5.7 秒）。

## 5. 测试
`pytest -q`：**47 passed, 2 skipped**（含 B 的 4 个测试；A 的 7 个测试也在内）。120/120 回合全部“完成并重放核验通过”（`outputs/B1000`）。

## 6. 对比运行：B 对第一轮（基线）
设置：1000 档、6 图 × 10 环境种子 × S/X，名义计划同 `outputs_summary/nominal2`。基线 = `outputs/fix1000`，B = `outputs/B1000`；另各做 2 个额外算法基种子（`*_s20261112`、`*_s20261113`）。

**单个算法种子（20261111）**
| 指标 | 第一轮 | B |
|---|---|---|
| 完成（S/X，共 60 环境） | 60 / 60 | 60 / 60 |
| 60 环境平均成本 S | 528.770 | 528.663 |
| 60 环境平均成本 X | 529.284 | 528.585 |
| Δ(S−X) 均值 / SD | −0.515 / 2.077 | **+0.078 / 0.785** |
| Δ 95% 区间 | [−1.051, +0.022] | [−0.125, +0.281] |
| Δ 正/零/负 | 1/52/7 | 3/56/1 |
| 重规划次数 | 78 | 76（轨迹不同） |
| ALNS 平均补回成本 | 4.00 | 4.25 |
| 最终 ≤ 残段候选 | 78/78 | 76/76 |
| 起点来源 | CATALOG 47 / RESIDUAL 29 / REBUILD 2 | MILP 51 / RESIDUAL 19 / REBUILD 6 |
| 墙钟 | 583 s | 595 s |

**逐环境配对（B − 第一轮，负 = B 更好）**
- 单种子：S：−0.107（区间 [−0.372, 0.159]，更好/相同/更差 = 4/53/3）；X：−0.699（[−1.306, −0.093]，12/46/2，Wilcoxon p=0.013）；合计 120 项：**−0.403**（[−0.733, −0.072]，16/99/5，p=0.012）。
- **3 个算法种子取平均**（每环境 × S/X 先对 3 个种子求平均，n=120）：S −0.174（[−0.402, 0.054]，p=0.063）；X **−0.493**（[−0.923, −0.062]，p=0.011）；合计 **−0.334**（[−0.575, −0.092]，19 更好/99 相同/2 更差，p=0.001）。
- 3 种子下的平均成本：S 528.973 → 528.799；X 529.200 → 528.707。环境层 Δ(S−X)：−0.227（[−0.625, +0.171]）→ **+0.092（[−0.031, +0.215]）**；Δ 的 SD 1.541 → 0.476。
- 同环境换种子的成本标准差（平均）：1.603（第一轮）→ 1.621（B），基本持平。

## 7. 解读
- B 的改进是**小而稳定**的：平均每个环境约少 0.33 元（约 0.06%），主要来自 X（跨车选项的搜索），**统计上显著**（120 项配对、3 种子），但幅度很小；绝大多数环境（99/120）与第一轮完全相同。
- B 还**缩小了 S/X 的系统性偏差**：第一轮 X 初始化吃亏（Δ<0），B 里 Δ 的均值 ≈ 0 且方差明显更小。这支持“第一轮里的 X 劣势主要是初始化候选覆盖不足”这一判断；但**不能因此得出 X 优于 S 的政策结论**（Δ 区间仍含 0）。
- B 对运行时间几乎没有影响（+2%，MILP 平均 0.28 秒）。

## 8. 遗留/未做
1. 线性代理模型不精确（见第 4 节）；没有做“代理模型 vs 完整模型最优”的穷举验证，只有上面 76 次重规划的排序一致性统计。
2. “X 的初始化包含 S 的全部候选”（X ⊇ S）仍未专门实现；B 缓解了但没有消除这个问题。
3. MAX_ROUNDS=2000 上限、60 秒墙钟矩阵、30 环境×5 种子矩阵、消融：未做。250 档未对 B 重跑。

## 9. 复现
```
cd /workspace/thesis/proj
../venv/bin/pytest -q tests/test_variant_b.py
../venv/bin/python -m tdr experiment --package data/package.json --nominal-dir outputs_summary/nominal2 \
   --cases all --seeds 10 --out outputs/B1000 --recovery-eval-budget 1000 --recovery-decision milp
../venv/bin/python scripts/run_repeats.py --budget 1000 --seed 20261112 --out outputs/B1000_s20261112 --recovery-decision milp
../venv/bin/python ../compare_variants.py outputs/fix1000 outputs/B1000   # 单种子配对比较
../venv/bin/python ../compare_3seeds.py                                      # 3 种子比较
```
