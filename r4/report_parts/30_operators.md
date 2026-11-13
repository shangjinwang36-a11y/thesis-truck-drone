- **RECOVERY_RETARGET**（在当前最优计划上重选接机车/点；S 只能原放飞车，X 可任意车；同频率同评价数）：forced M=3 消融 Δ/C_S：spec 1.42%→1.31%，light2 0.16%→0.12%，**无增益**。
- **X 专用 cross_ops**（`cross_ops.py`，仅当失败航次被≠原放飞车的车接回时才触发 → S 恒不触发；占用 X 同一份 1000 评价预算；无配额/惩罚）：
  LAUNCH_TRUCK_RELEASE（原放飞车不再等机后，K1/K2 剩余纯地面访问重新定位）、TRUCK_TASK_SWAP（K1/K2 互换地面访问）、FAILED_PARCEL_GROUND_REASSIGN（交接票在接机车上的地送位置重排）。
  消融（forced M=3，8 seeds×C50/R50/RC50）：spec 5.52→5.42（Δ/C_S 1.42%→1.39%）；light2 0.55→0.55（完全相同）；解除门控(S/X 都能用)spec 5.63、light2 0.68。主实验：spec 0.59→0.54，light2 0.45→0.43，light1 0.98→0.98。**无可测收益。**
- 原因：恢复阶段包裹保管链固定（车上的票只能由该车送，交接票只能由接机车送），"把别车的地面客户搬给另一辆车"几乎不可行；X 真正多出的自由度只有"选哪辆车接机"，已由 MILP/目录覆盖。
- 代码保留且默认关闭（`cross_ops`、`recovery_retarget`、`cross_ops_gate`），论文中可作"算子消融：专用算子无额外收益，优势来自接机车选择本身"的负结果。
