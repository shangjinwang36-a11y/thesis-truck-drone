# T08a / T02-C：失败返航修复记录

Codex CLI 会话 id：未创建。实际请求模型 `gpt-6-astra`，推理 `high`；命令在初始化阶段报 `failed to initialize in-process app-server client: Read-only file system (os error 30)`。本记录不声称已获得额外 CLI 独立审查。原独立审查会话为 `01a1d742-9864-7d61-9ed5-6ccf65db6187`。

## 修法与范围

- `proj_r6/src/tdr/schedule.py:140`：保存各航次接机车/通道可用时刻及 SERVICE 开始时的失败返航需求。
- `schedule.py:370`：使用原调度的 `max(ready, t_arr, channel_free)`，包括前序回收/交接；与本机名义到达分开，防止把等本机成功服务的时间错算为通道占用。
- `schedule.py:619`：统一失败返航需求。失败在 SERVICE 开始揭示，以当前全部载重巡航；到达为 `stage.start + distance / drone_speed`；悬停为 `max(0, rec_ready - arrival) + recovery_s`，回收后要求 E_min。landed 仅扣巡航且余电非负；resumed 服务免查，后续未揭示服务仍查。
- `schedule.py:652`：将到场需求折算为该阶段末端的等价约束并纳入 `_swap_pass`。未起飞航次电量不足则换电后重新调度；已换电仍不足/已起飞则拒绝。失败返航是假设分支，不重复扣入名义能耗或成本。
- `proj_r6/src/tdr/evaluate.py:209`：事后核验复用同一能量规则。
- `proj_r6/src/tdr/verify.py:108`：加入相同返航规则。未添加按 strategy 分支。
- 按用户允许的最低范围完成起飞前换电接入；充电 LP 的优化约束未扩展，充电模式仍由最终 evaluate/verify 返航检查约束。

## 测试

新增 `proj_r6/tests/test_t08a_fix_failure_return.py:1`，9 个测试函数、参数展开为 21 项：

- 4 kg、直返 2 km、起始 0.17 kWh，等待 120 秒后只剩 0.020 kWh；名义送货仍高于 0.05。
- 前序回收和交接导致通道/司机不可用；不能把本机名义送货延迟算作通道等待。
- 起飞前换电可解、已起飞不可换电，S/R/X 的 evaluate 与 verify 结论一致。
- 即使分配器漏查，evaluate 与 verify 仍产生相同 FAIL_RETURN。
- landed 非负边界、悬停 E_min 边界、统一能量容差；低电量降落可行。
- resumed 服务免查、后续未揭示服务继续检查；不会因已揭示服务强制换电或拒绝。

全量首跑为 14 failed、255 passed、3 skipped。失败均涉及旧夹具对新规则的前提，作以下明确更新，未修改历史计划文件：

- `proj_r6/tests/test_t02c_failure_return.py:29`：round11 的 R/RC 历史计划不再断言全部可行；明确核验满电仍不足的拒绝原因、verify 一致性和真实返航缺口。C50/C100 仍断言可行。
- `proj_r6/tests/test_invariants_audit.py:111`：round3 的 R50-X、R100、RC100 明确断言 SERVICE 失败返航缺口；其他历史计划继续检查完整回放与成本。
- `proj_r6/tests/test_cross_robust.py:45`：跨车裕度单测使用明确的 0.06/0.10 kWh 回收端点，保留路线、资源和客户归属，以分别检查 0.075 裕度和 90/300 秒额外悬停边界；不再依赖已被更早检查拒绝的旧计划能量账本。
- `proj_r6/tests/test_round4.py:274`：承诺动作回归夹具明确使用 beta_hover=beta_cruise=0.5，保留完整回放通过和约 545.5 秒第二次失败断言，并新增名义可行断言。
- `proj_r6/tests/test_round6.py:214`：保管链回归夹具明确使用 beta_hover=0.5，保留 363.6756 秒截断、跨车后继链、保管与恢复可行全部断言。

新增测试单跑：21 passed。相关旧测试修正后逐项通过。最终指定全量：**269 passed、3 skipped、48 warnings，47.57 秒，退出码 0**。warnings 为已有 TestWorld 带构造函数的收集提示。

复现命令：

```bash
cd /workspace/thesis-hub/dev/proj_r6
/workspace/thesis-hub/review/venv/bin/python -m pytest -q -n 6 --dist loadfile
```

## 文件边界

schedule.py / evaluate.py 保持 CRLF，verify.py 和被修改测试保持 LF。未改 simulate.py、recovery.py；未 commit/push；未运行 1001–1010、2001–2010、3001–3030、4001–4030 种子；未修改 `/workspace/thesis-hub/code` 或 `code-round11-frozen`。
