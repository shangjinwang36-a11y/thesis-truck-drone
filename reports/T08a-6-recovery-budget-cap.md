# T08a-6 恢复预算硬上限

基线：algo-innovation / 222443f。仅修改 dev 工作区，未 commit、未 push。

## 改动与证据

- `proj_r6/src/tdr/recovery.py`：移除联合重选、rescue、兜底的预算加额；联合重选在传入预算耗尽时直接返回；rescue 标记仅表示旧口径会触发 rescue。
- `proj_r6/src/tdr/simulate.py`：S/R/X 共用每轮恢复硬上限；初始化额度为 `min(recovery_init_eval_budget, main_limit)`，实际用量记回父预算，主循环额度为 `max(0, main_limit - 初始化已用)`。初始化和主循环共用墙钟起点。补充预算与墙钟审计，并为初始化失败的轮次保存 replan 统计。
- `proj_r6/r6/run_round2.py`：每个策略输出 `budget_audit`，汇总 `ep.replans[1:]`；没有回合记录时输出零值审计。
- `proj_r6/tests/test_round1.py`：按初始化与主循环合计不超过 150 更新断言，覆盖 S/R/X。
- `proj_r6/tests/test_t08a_recovery_budget_cap.py`：AST 检查预算不加额、无额外额度常量、无策略预算分支；验证零预算、小预算、初始化额度大于硬上限、墙钟耗尽、审计聚合及 CRLF。

删除位置（均为 222443f 的原始行号）：

| 文件 | 行号 | 删除内容 |
| --- | --- | --- |
| `proj_r6/src/tdr/recovery.py` | 683 | `JOINT_EXTRA_EVALS = 60` |
| `proj_r6/src/tdr/recovery.py` | 684 | `LAND_EXTRA_EVALS = 120` |
| `proj_r6/src/tdr/recovery.py` | 870 | 联合重选追加 60，并在条件满足时追加 120 |
| `proj_r6/src/tdr/recovery.py` | 1115 | rescue 追加 `rescue_evals` |
| `proj_r6/src/tdr/recovery.py` | 1210 | 兜底追加 24 |

全面检查 `recovery.py`、`recovery_milp.py`、`hybrid.py`、`simulate.py`、`alns.py`，未发现其他加额。`nominal.py` 未改动。

## 验证

执行命令：

```bash
cd /workspace/thesis-hub/dev/proj_r6
/workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

结果：**244 passed, 3 skipped, 48 warnings in 46.73s**，退出码 0。warnings 为 TestWorld 带构造函数的收集提示。

`recovery.py`、`simulate.py` 字节检查均无独立 LF；`git -c core.whitespace=cr-at-eol diff --check` 通过。未修改 code、code-round11-frozen。

硬上限可能使旧口径靠追加额度才找到解的轮次更早停止，这是本任务要求的行为。初始化失败现纳入 replan 记录，因此汇总的恢复次数和评价数也包含失败尝试；搜索和停止逻辑未因此改变。未运行正式实验或修改名义阶段预算。
