# T08a-5b：统一恢复能量预筛与默认候选数

Codex CLI 会话 id：`01a1d76a-dbff-73f2-9cde-aeb8b0f9c34d`（CODEX_THREAD_ID）；模型：`gpt-6-astra`，推理：`high`（本次用户提供的启动信息）。本记录为当前会话的修复与测试结果，未另行嵌套调用 Codex。

输入：独立审查会话 `01a1d742-9864-7d61-9ed5-6ccf65db6187`，`/workspace/thesis-hub/review/codex/t08a_review_1to5b.log` 末尾 222443f（5b）意见。

- `proj_r6/src/tdr/recovery.py:190,290,1037,1064`：目录开关说明同步；能量预筛移到保护段和尾部分流之前，删除仅针对非 S 的尾部筛选条件；initial_recovery 默认 milp_top_k=10，传入目录的 drop_energy_tail 仅由 energy_screen 决定。S 的全部候选从保护段产出，故仅删除尾部 strategy 条件不足以修复运行时行为。开关关闭仍沿用原有排序与保护段；开启时三策略共用原有估计成本阈值 `<1e4`，没有新增策略分支。
- `proj_r6/src/tdr/recovery_milp.py:198`：solve_recovery_milp 默认 top_k=10。除此处默认值之外，该文件与 HEAD 完全相同，包含 H4 的其他车辆追加候选逻辑。
- `proj_r6/tests/test_t08a_fix_recovery_uniform.py:67,90,111`：新增 11 项参数化测试。手工两客户案例通过真实 run_episode→initial_recovery→目录构造→MILP 调用点，monkeypatch 捕获 S/R/X 实际绑定参数；覆盖 top_k=10/3、开关关/开及两个直接调用默认值。MILP 接口仅接收 top_k，目录接收对应的 drop_energy_tail；没有为测试新增生产接口。到达 MILP 时用哨兵异常结束，无需运行无关优化。目录行为测试使用近/远候选和 guard_n=0/1/40，验证保护段、尾部、其他车辆都服从同一筛选规则。测试隔离全局 ACTIVE 配置。
- `proj_r6/tests/test_round11.py:1,68`：原测试明确要求 S 开启预筛后仍保留高惩罚条目，与本次统一要求冲突。改为检查 S/R/X 均过滤高惩罚候选、同车候选一致、R/X 结果一致，同时保留未筛选目录包含高惩罚条目的验证。

修复前，新回归在合法手工案例上为 `6 failed, 5 passed`：开关开启时目录实际收到 False/False/True；默认 top_k 为 6；S 候选绕过筛选。修复后新增回归为 `11 passed in 0.38s`。

首次全量运行：`1 failed, 281 passed, 3 skipped, 48 warnings in 54.78s`，唯一失败是上述 round11 旧语义断言。同步后按相同命令复跑：

```bash
cd proj_r6 && /workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

最终全量结果：`282 passed, 3 skipped, 48 warnings in 54.28s`，退出码 0。warnings 均为既有 TestWorld 带构造函数导致的收集提示。未单跑已知存在顺序依赖的 test_round6 测试。

换行检查：recovery.py 保持 1260 个 CRLF、无裸 LF；recovery_milp.py 保持 LF；simulate.py 与 HEAD 逐字节相同。`git -c core.whitespace=cr-at-eol diff --check` 通过（默认 diff --check 会把现有 CRLF 中的 CR 误报为行尾空白）。

仅修改 dev 工作区，未 commit/push，未修改 code 或 code-round11-frozen，未运行用户禁止的实验种子；新增 episode 测试使用固定失败包裹和算法随机数种子 42。预筛仍是既有估计成本阈值，不改变其代理模型含义；H4 允许最终候选数大于基础 top_k，按定案保留。本次不涉及其余审查项。
