# T08a：迁回放飞车时清除旧交接票地送

额外 Codex CLI 会话 id：未建立。请求模型：`gpt-6-astra`，推理：`high`。实际调用 `codex exec --ephemeral` 后以 `failed to initialize in-process app-server client: Read-only file system (os error 30)` 退出。本记录为修复与测试执行结果，不是独立审计通过结论。

原始独立审查会话：`01a1d742-9864-7d61-9ed5-6ccf65db6187`；来源：`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log`。

- `proj_r6/src/tdr/ground_finish.py:186`：参照 `recovery.py`，在迁移候选克隆上清除当前航次 handover 包裹的全部旧 ground 安排，再交给现有 `_build` 安排到新回收点之后。S/R/X 共用原路径，无新增 strategy 分支。
- `proj_r6/tests/test_t08a_fix_ground_finish_handover.py:17`：新增两客户确定性回归测试，覆盖已有 t2 地送安排、跨车迁回放飞车 t1、唯一交付与回收后配送、保留无关地送及不修改输入。修复前测试失败并返回 UNPRICED；修复后成本为 `69.82890184248616`，单测通过。
- `proj_r6/tests/test_round11.py:19`：原测试六处硬编码种子 `1002` 改为允许的 `11`，断言不变，避免指定全量测试运行禁用种子。

全量执行命令：

```bash
cd proj_r6 && /workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

结果：`245 passed, 3 skipped, 48 warnings in 44.89s`，退出码 0。warnings 均为 `TestWorld` 带构造函数导致的测试类收集提示。

`git diff --check` 通过。修改文件保留 LF；未修改的 `recovery.py`、`simulate.py` 保持 CRLF。仅修改 dev 工作区，未 commit/push，未修改 code 或 code-round11-frozen，未执行禁用种子的实验或测试。

本次范围仅限交接票旧地送安排清理；原审查中的其他问题未处理。额外独立复核受上述 CLI 初始化失败限制。
