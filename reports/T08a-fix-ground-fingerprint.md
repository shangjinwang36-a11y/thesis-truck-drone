# T08a：修复重复访问地送位置的情景缓存碰撞

额外 Codex CLI 会话 id：未建立。请求模型：`gpt-6-astra`，推理：`high`。实际调用 `codex exec -m gpt-6-astra -c 'model_reasoning_effort="high"' -s workspace-write -C /workspace/thesis-hub/dev`，因 `failed to initialize in-process app-server client: Read-only file system (os error 30)` 初始化失败，退出码 1。本记录是工作区修复与测试执行结果，不是额外独立审计通过结论。

原始独立审查会话：`01a1d742-9864-7d61-9ed5-6ccf65db6187`；来源：`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log` 末尾的 35cfe98（5a）意见。

- `proj_r6/src/tdr/hybrid.py:72`：`_fingerprint` 复用已有访问位置映射，ground 记录改为 `(车, 路线位置, 客户, 包裹元组)`。同客户重复访问的地送位置可区分，结构相同但访问 ID 不同仍使用同一缓存键。没有新增 strategy 分支，三策略继续使用原共用路径。
- `proj_r6/tests/test_t08a_fix_ground_fingerprint.py:17`：新增一个参数化回归测试，覆盖 `nominal_cross=False/True`。采用审查记录中的确定性三客户案例，两个计划实际完整评价可行，成本分别为 `7.807784866593134` 和 `8.512712495371337`。通过真实 `scenario_score` 写入同一缓存，并用 `cached_scenario_cost` 验证第二计划写入前不命中、写入后两计划各自读回正确情景分。固定无失败情景，情景分等于实际成本，不使用随机种子、不 mock 缓存。
- 同一测试验证 clone 和访问 ID 重编号可命中已有缓存；移除 live_budget 后调用 `scenario_score`，确保返回来自缓存而非重新计算。测试结束恢复全局车队配置，避免新增顺序依赖。

修复前运行新增测试：`2 failed in 0.37s`，失败均为第二计划错误命中第一计划的 `7.807784866593134`。修复后：`2 passed in 0.31s`。

全量验证命令：

```bash
cd proj_r6 && /workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

全量结果：`271 passed, 3 skipped, 48 warnings in 46.47s`，退出码 0。warnings 均为已有 TestWorld 带构造函数导致的收集提示。未单跑已知存在顺序依赖的 test_round6 测试。

`git diff --check` 通过。hybrid.py 保持 LF；simulate.py 和 recovery.py 与 HEAD 逐字节相同，保持 CRLF。仅修改 dev 工作区，没有 commit/push，没有修改 code 或 code-round11-frozen，没有运行禁用种子。其他审查项不在本次修复范围内。
