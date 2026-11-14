# T08a：迁回放飞车时清除旧交接票地送

- 目标：仅修复 `_attempt_relocate` 改写接机点后保留旧交接票地送安排的问题。
- 输入：独立审查会话 `01a1d742-9864-7d61-9ed5-6ccf65db6187`，`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log`。
- 输出：`ground_finish.py` 最小补丁、`tests/test_t08a_fix_ground_finish_handover.py`、对应 reports 结果记录。
- 验收标准：已有 t2 地送的交接票迁回放飞车 t1 后唯一交付；无关地送和原始输入不变；指定全量 pytest 通过；不新增 strategy 分支，不运行禁用种子。
- 负责人：本次 Codex 工作区修复会话。
- 状态：修复与测试完成；额外 Codex CLI 调用因只读文件系统初始化失败，未取得独立复核结论。
