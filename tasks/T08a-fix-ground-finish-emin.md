# T08a：允许低于 E_min 的合法降落收尾

- 目标：只修复 T02-A 迁移候选预筛错误扣除 E_min 的问题。
- 输入：独立审查会话 `01a1d742-9864-7d61-9ed5-6ccf65db6187`，`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log` 末尾。
- 输出：`ground_finish.py` 最小修复、原 T02-A 测试修正、新增 `test_t08a_fix_ground_finish_emin.py`，以及对应 reports 记录。
- 验收标准：预筛只要求巡航后电量非负；完整评价分别检查悬停与降落电量；低电量原地降落可定价；零电量且无法抵达任何客户点为 UNPRICED；指定全量 pytest 通过。
- 约束：仅 dev 工作区、不 commit/push、不触碰冻结目录、保持换行、不新增 strategy 分支、不运行禁用种子。
- 负责人：本次 Codex 工作区修复会话。
- 状态：修复完成，指定全量测试为 248 passed、3 skipped；额外 Codex CLI 调用在初始化时因只读文件系统失败，未建立会话。
