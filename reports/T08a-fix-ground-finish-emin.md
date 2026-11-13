# T08a：允许低于 E_min 的合法降落收尾

额外 Codex CLI 会话 id：未建立。请求模型：`gpt-6-astra`，推理：`high`。实际调用 `codex exec --ephemeral -m gpt-6-astra -c 'model_reasoning_effort="high"' -s workspace-write -C /workspace/thesis-hub/dev` 并传入本项修复指令，初始化失败：`failed to initialize in-process app-server client: Read-only file system (os error 30)`，退出码 1。本记录为工作区修复与测试结果，不是独立审计通过结论。

原始独立审查会话：`01a1d742-9864-7d61-9ed5-6ccf65db6187`；来源：`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log` 末尾的 T02-A 意见。

- `proj_r6/src/tdr/ground_finish.py:160`：`_reachable_customers` 将直飞能耗上界由 `e0 - phys.e_min + phys.energy_tol` 改为 `e0 + phys.energy_tol`。保留真实 reserve_fraction，由完整评价执行非降落回收 ≥ E_min、降落 ≥ 0；同步修正文档。S/R/X 仍共用原路径，无新增 strategy 分支。
- `proj_r6/tests/test_t02a_ground_finish_emin.py:27`：对可行收尾 timeline 中每个 R 阶段结束后的电量进行检查；覆盖原电量和满电两种情况，满电案例必须包含非降落回收，返回成本必须来自已检查方案，避免空断言。
- `proj_r6/tests/test_t02a_ground_finish_emin.py:60`：零电量负例移至所有客户点之外，并证明到每个客户的巡航能耗均超过容差，因此确实无法合法收尾。
- `proj_r6/tests/test_t08a_fix_ground_finish_emin.py:10`：新增 0.025 和 0.0 kWh 两个参数案例。显式原地降落完整评价可行、回收后电量保持初值；同点悬停收尾不可行；原接机点不可达；自动迁移包含原地候选并返回不贵于手工降落方案的可行成本。允许搜索选择更便宜的其他合法降落点。

修复前运行新增回归与修正后的 T02-A 测试：`2 failed, 4 passed`，两个失败均为手工降落可行而自动返回 UNPRICED，复现审查问题。最终全量命令：

```bash
cd proj_r6 && /workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

结果：`248 passed, 3 skipped, 48 warnings in 45.03s`，退出码 0。warnings 均为现有 `TestWorld` 带构造函数导致的收集提示。未单跑已知有顺序依赖的测试。

`git diff --check` 通过。修改的已有文件保持 LF；`simulate.py`、`recovery.py` 与 HEAD 逐字节相同，保持 CRLF。仅修改 dev 工作区，没有 commit/push，没有修改 code 或 code-round11-frozen，没有运行禁用种子。新增测试使用现有静态 C50 计划构造确定性案例，不生成随机实验。

其他审查项不在本次范围内；额外 CLI 独立复核受上述初始化失败限制。
