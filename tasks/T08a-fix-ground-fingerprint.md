# T08a：修复重复访问地送位置的情景缓存碰撞

- 目标：仅修复 hybrid._fingerprint 的 ground 缺少路线位置问题。
- 输入：独立审查会话 01a1d742-9864-7d61-9ed5-6ccf65db6187 的 35cfe98（5a）意见。
- 输出：ground 四元组指纹、实际缓存读写回归测试、reports/T08a-fix-ground-fingerprint.md。
- 验收标准：两个实际可行且成本不同的计划不串用情景分；相同结构仍命中；指定全量 pytest 通过。
- 负责人：当前 Codex 编码会话。额外 Codex CLI 已调用，因只读文件系统初始化失败，未建立会话。
- 约束：只改 dev 工作区，保留原换行，不 commit/push，不运行禁用种子，不新增 strategy 分支。
- 状态：修复完成；新增测试修复前 2 failed、修复后 2 passed；指定全量 pytest 为 271 passed、3 skipped。额外 CLI 独立复核未能建立会话，详见报告。
