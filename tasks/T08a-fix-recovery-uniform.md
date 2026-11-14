# T08a-5b：统一恢复能量预筛与默认候选数

- 目标：只修复 222443f 的下游统一开关不对称和默认 top_k=6。
- 输入：独立审查会话 01a1d742-9864-7d61-9ed5-6ccf65db6187，t08a_review_1to5b.log 末尾。
- 输出：recovery.py、recovery_milp.py 修复；test_t08a_fix_recovery_uniform.py 运行时回归；同步旧 round11 断言；同名 reports 记录。
- 验收：S/R/X 共用能量筛选路径，默认 top_k=10，H4 其他车追加候选不变，指定全量 pytest 通过。
- 负责人：当前 Codex CLI 会话（gpt-6-astra，high）；按用户指示不嵌套调用 Codex。
- 状态：完成。新增 11 项回归通过；指定全量测试 282 passed、3 skipped、48 warnings（54.28s，退出码 0）。
