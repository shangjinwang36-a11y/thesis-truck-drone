# T08a：失败返航等待能量与起飞前换电

- 目标：仅修复 3cd1d21 / T02-C 的带货返航等待漏计、换电决策遗漏和 verify 不一致。
- 输入：独立审查会话 `01a1d742-9864-7d61-9ed5-6ccf65db6187`；`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log` 末尾。
- 输出：schedule/evaluate/verify 统一规则；`proj_r6/tests/test_t08a_fix_failure_return.py`；更新受该规则影响的旧测试前提；对应 reports 记录。
- 验收：等待车/通道耗电按失败直返到达计算；landed 仅要求巡航后非负；resumed 免除已揭示服务、后续服务仍查；未起飞可换电修复；S/R/X 同路径；指定全量 pytest 通过。
- 范围：按用户允许的最小方案接入惰性换电，不扩展充电 LP 的优化约束。
- 约束：只改 dev 工作区；不 commit/push、不改冻结目录、不运行禁用种子、保持原换行。
- 负责人：本次 Codex 工作区修复会话。
- 状态：修复完成。新增 21 项回归通过；指定全量 269 passed、3 skipped、48 warnings，用时 47.57 秒。额外 Codex CLI 已实际调用，但初始化因只读文件系统失败，未建立会话。
