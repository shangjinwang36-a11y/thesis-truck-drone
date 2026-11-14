# T08a：S_SEED 兜底能量预筛参数补传

- 目标：仅修复 bece4c6 遗漏的 S_SEED 目录 drop_energy_tail 参数。
- 输入：独立审查会话 01a1d776-5a9f-7b33-97fd-fbaafce94fe2，t08a_review_6_fix.log 末尾。
- 输出：recovery.py 最小补丁、test_t08a_fix_s_seed_energy_screen.py、同名 reports 记录。
- 验收：真实兜底路径遵循预筛开关；默认 False 行为不变；指定全量 pytest 通过；保持 CRLF，不新增 strategy 分支。
- 负责人：当前 Codex CLI 会话 01a1d78b-e11b-7d90-bf8e-00d6ca078411（用户提供 gpt-6-astra / high 启动信息）；不嵌套调用 Codex。
- 状态：完成。新增 3 项回归通过；指定全量 pytest 为 285 passed、3 skipped、48 warnings（80.62s，退出码 0）。
