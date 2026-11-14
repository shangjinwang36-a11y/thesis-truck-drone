# T08a：S_SEED 兜底能量预筛参数补传

Codex CLI 会话 id：`01a1d78b-e11b-7d90-bf8e-00d6ca078411`（CODEX_THREAD_ID）；模型：`gpt-6-astra`，推理：`high`（用户提供的启动信息）。本记录为本次修复及测试结果，未嵌套调用 Codex。

输入：独立审查会话 `01a1d776-5a9f-7b33-97fd-fbaafce94fe2`，`/workspace/thesis-hub/review/codex/t08a_review_6_fix.log` 末尾对 bece4c6 的意见。

- `proj_r6/src/tdr/recovery.py:1239`：现有 S_SEED 兜底目录补传 `drop_energy_tail=energy_screen`。只改此调用；共用 RecoveryCatalog 的筛选逻辑，没有新增 strategy 分支，没有改既有兜底触发条件或预算。
- `proj_r6/tests/test_t08a_fix_s_seed_energy_screen.py:11`：新增 3 项参数化回归，覆盖开启、关闭及省略 energy_screen。手工近/远接机点通过真实 RecoveryCatalog 排序和筛选；候选构造器返回空列表，使真实 initial_recovery 在预算剩余且没有 S 资格解时走完兜底。验证 s_seed_used、两轮构造器调用、主目录与兜底的候选及顺序相同；开启时远点被过滤，关闭和默认时保留。测试不运行实验种子，不评价模拟候选成本。

默认配置结论：**R11c 的 recovery_energy_screen=False 下，本修复不改变算法行为。** 代码依据：`config.py:315` 默认 False，`simulate.py:958` 将该值转换为 bool 传给 initial_recovery；直接调用的默认也为 False（`recovery.py:1043`）。原兜底调用省略 drop_energy_tail，使用构造器默认 False（`recovery.py:188`）；修复后传入的仍为 False。目录在 `recovery.py:291` 仅在该值为真时过滤，所以默认候选集合、排序、后续评价和预算路径均保持不变。

复现及验证：修复前单跑新测试为 `1 failed, 2 passed in 0.35s`，唯一失败是开启预筛时兜底仍含 far，而主目录只有 near；修复后为 `3 passed in 0.33s`。

```bash
cd proj_r6 && /workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

全量结果：`285 passed, 3 skipped, 48 warnings in 80.62s (0:01:20)`，退出码 0。warnings 均为既有 TestWorld 带构造函数的收集提示。按要求使用 --dist loadfile，没有单跑已知存在顺序依赖的 test_round6 测试。`git -c core.whitespace=cr-at-eol diff --check` 通过。

边界：只修本次指定遗漏，测试用桩控制无法构造候选的前提，不声称覆盖整套恢复求解。recovery.py 保持 1261 个 CRLF、无裸 LF；simulate.py 与 HEAD 逐字节相同。仅修改 dev 工作区，未 commit/push，未修改 code 或 code-round11-frozen，未运行禁用种子。
