# M49三阶段独立零native审计

**结论：调用/负结果证据PASS；1002完整条件后缀的原物理/账票PASS；两项必须纠正的口径及源共享性BLOCK。不能整体签PASS/晋升或进入actual。**
本阶段未重做M48结论，只引用其既有封存源与允许的原执行/可见快照。未搜索/优化/运行实际世界，新增审计native0。

## 一、两项关键纠正（需立即反馈Cursor）

### 1. 732.009659不是本见证同状态应急参考
M49输入及其完整prefix来自M48_RECOVERY RC100_1002_X，原cut3452.903818675321，nominal SHA ddad358a…；原执行实付为**685.4916957008995**。
732.0096592354022实际属于M48_M44_NOMINAL/历史M44_CURRENT的RC100_1002_X，其nominal SHA eaf8e7db…且cut3422.557501567223，连可见cut都不同，不能称“旧同状态应急”。
故601.364121对原同班应急的**条件**差额是84.12757468092127，不是130.645538。它仍不是新实际配送收益或同硬H资格双方案比较；没有把后续世界失败运行出来。

### 2. 不能将本见证归为X独有跨车收益；S共享范围待源码闭合
- 最终SELECTED_PLAN的全部航次按真实launch/rec访问均同车；完整prefix+suffix分别用原verify_replay的X和S策略检查都通过。不是跑了S搜索，不是S自然可达性/性能证据。
- 连首个可行INIT（第373次，费用601.5840995742682）按原recovery_is_cross资格检查也全同车，不能只凭X标签称跨车。
- sid130的字段truck仍写t2，但launch_truck=t7；rec_vid521实际在t7路线、visit.truck=t7，真实R动作actor=t7。这是残留字段，不是t7→t2真实回收。其p028经t7上的R后完成20秒U，再由t7地送，货权连续。
- 冻结verify.py:45-53只禁止S的真实跨车无人机回收；moves.py:419-432、466-505的共享ground_candidates枚举多车，由allowed_truck真实货权限定，并无“所有S地面访问只能原车”的普遍规则。TRUCK:t7上的p047不能直接改给t2，**S/X都不行**；DEPOT等可自由分配的合法基础动作则不能无据只禁S。
- 现在缺全航次land及rehome实际recovery源码/manifest和rehome运行脚本，无法检查新rehome的S分支到底按真实跨机体流限制，还是无据封掉共享地面重派。**此项source/共享范围BLOCK，不先断言已违规，但明确不接受“S所有rehome都禁”的规则。** 最终同车不自动证明生成器违规，也不自动赋予其X专属资格。不得为了造RX削S。

## 二、前两个land阶段：账与真实支持范围
两个包大小/SHA均逐字验证、安全隔离。每阶段各两个RC100原末INIT，分别1304次，共2608＋2608＝5216；不是还新跑了一组修前2608。RAW与receipt逐行index/reason/status/feasible/cost/首拒因及budget used/limit与RESULT ledger全部匹配，无denied。每阶段每seed无可行完整plan，MAIN未入、chosen/cost皆null，不报告费用差/零费用。

每个1304的原额度组成：INIT100＋一次rescue1000＋既有fallback24＋JOINT60＋LAND120。receipt中的上限序列100→1100→1124→1304。目录可能在用完上一上限前耗尽，所以某阶段实际条数不等于“新增额度”；不能把1304说成偷偷增加MAIN，也不能把后三项省略。

|阶段/seed|SWAP首拒|H首拒|P_CUSTODY|INVALID_STRUCTURE|总|
|---|---:|---:|---:|---:|---:|
|失败航次land1001|694|38|404|168|1304|
|失败航次land1002|726|578|0|0|1304|
|全航次land1001|401|271|464|168|1304|
|全航次land1002|653|651|0|0|1304|
这些是每次评价记录的**第一拒因**，不是全部潜在违规枚举。全航次阶段所有1304份/seed的sortie.landed均True，但仍有能量拒绝，不能说整个目录能量问题已全部解决。

仅用既有已付费首份candidate做原冻结schedule_plan逐段重建，未调用evaluate_plan/initializer/optimize/LP/actual；入口均设禁止保护、审计计数为0。独立确认：
- 1001失败片段是sid364/d14，首先能量失败的是另一架d13/sid378。一次合法换电后.5，经L/CRUISE/SERVICE/返程到.346325876；WAIT847.467365秒耗.313876802，到.032449074<.05。并非一段飞行超过满电。
- 1002失败片段sid130/d13，首先失败是d14/sid494。满电飞行服务完到.082964405；WAIT1266.505782秒耗.469076216，到-.386111810<.05，是等待链末预测余额，不是已经执行的负电量或单飞耗超电。
- 原land_and_wait已True、e_cap=.5/e_min=.05。全航次land首份计划只有landed位与前阶段不同；在原物理下WAIT/R零耗，但L/CRUISE/SERVICE、回收所需时间、U20、货权、机位均未免除。
- 全航次首计划原排程收敛且swap_msg空；t7 finish6077.182594/6244.435598 > H5911.709582。相同骨架仅行驶的finish4917.792535/5778.094923均低于H。超出来自该骨架剩余服务/会合/准备/换电等非行驶与时序等待，不证明无短骨架。
- 原源码在旧能量门失败后可能尚未安排所有后续必要swap；解除首能量门可继续暴露新的60秒换电等时序，不能假设land仅减能量、整表时间必定完全不变。

## 三、source与prefix证据边界
1. 已提供的第一阶段recovery.py与原M48全部AST相比，只有共享build_residual_candidate的一个受phys.land_and_wait and f.started保护的f.landed=True。在克隆cand上改未来等待标志，不改输入state、已付prefix、位置/保管或模型参数。
2. 用原147项M48 manifest仅替换这份源码hash，以原indent1+换行精确重建出的manifest SHA就是输入所载57a733f0…；因此第一阶段四类物理/价格/预算/配置等其余封存条目与原M48一致。重建件单独标为RECONSTRUCTED，不冒原包自带。
3. 第二阶段只给测试/日志，无实际recovery.py/manifest（声明be318000…）；rehome同样缺源码/manifest（声明ad479d32…）及实跑driver。测试源码中的S/X/关配置断言只是意图，不等于独立执行验证或完整源闭环，不能据此签它们所有正式物理门没改。
4. 两阶段及rehome的plan/state/H/源pickle hash一致（set字段显式规范化）；与已核M47原末INIT快照等价，且M48真实执行cut和对应最初GROUND_FINISH start的货权/能量/已送/电池/已发/已结束车逐项匹配。1001原执行有两段GROUND_FINISH，按1470.095684的第一段匹配，不错拿1577.974964的后一段。
5. 原M48两份被引用VISIBLE_CONTEXT.pkl本体未在本次包中，源pickle的SHA声明尚不能对本体独立回链；可见内容已按上项绑定，但完整inst/phys/alg/opts/greq可另补纯可见原件，不需任何flags。

## 四、rehome1002条件见证独立PASS，1001仍负例
- 原1002切点前所有segments原样＋SELECTED_SUFFIX_SEGMENT重放；start逐字段与原应急相同，无改prefix/传送/改货权。原X与S回放均100/100、无违规，H5911.709582085911，后缀结束5846.896271740921，完整链最小电量.053527854157392404。
- 原价格独立bill：driver349.0219734543964＋distance246.47867274945713＋electricity5.863474816124775＋overtime0＝**601.3641210199783**，与hard evaluation精确一致。suffix-only422.56360845845535不含已执行prefix，RESULT中invoice_matches_hard=False是该范围差异，不是通过放宽容忍修账。后缀自身最小电量.0934893不能替代完整链.053527854。
- 所有U维持20秒；机体/包裹保管、真实位置、库存/机位/电量均由原物理独立回放通过。选中air集合不含原effective_greq，且没有超出原可见plan的air任务池；snapshot字面air_ceiling=None没有被审计擅改为别的值。
- 1001无suffix。1304首拒分布H261/G_CUSTODY63/P_CUSTODY464/结构168/SWAP348。G63中p047由t7非法给t2是**51**次，另p025仍在d4却给t7地送6次、p011在t5却给t2六次，不能把全部63泛称p047。p047的真实holder=TRUCK:t7；不意味着所有换骨架都无解。
- 1002INIT1100有2次可行，第373首次601.584100；随后MAIN1000及硬核验1，共2101，含406次feasible评价不是406份独立执行。1001的1304加之本阶段3405，未另跑actual。

## 五、成本分账与未知
|范围|新增记录评价|
|---|---:|
|失败航次land两状态|2608|
|全航次land两状态|2608|
|rehome1001|1304|
|rehome1002|1100 INIT＋1000 MAIN＋1已付硬核验＝2101|
|M49三阶段合计|8621|
|本次独立审计|0 native（只读既有计划排程/原回放/账票）|
原M48旧7012、8诊断证据限制、40实际执行431857及所有历史unknown各自保留、不合并冒全研究归一总数。没有新“修前2608”、没有把硬核验1藏入MAIN，没有实际批startup。日志seconds是记录墙时不是完整CPU；没有可行plan的四个前阶段及rehome1001不造费用。

## 六、最小补件（无需任何新评价/搜索）
- 已执行全航次land的recovery.py与be318000…完整core manifest；若与第一阶段除该文件外还有差异，一并提供那些原冻结文件。
- 已执行rehome的recovery.py、ad479d32…完整core manifest及实际paid_rehome运行driver；所有S/X资格分支、地面/访问/接机重派实现要有正文。需要明确S只禁真实跨车无人机回收，而非一概禁一般地面重派；检查sid130的stale truck字段/资格判定。
- 原M48 RC1001001/009、1002/011两份VISIBLE_CONTEXT.pkl，或能逐字段校验inst/phys/alg/opts/greq的纯可见原件；不要flags/未来世界。
- 将732.009659的基线标签改正为不同名义/不同cut的历史参照；同一原班应急685.491696已可从现有原件纠正，不用重跑。

事实约束仅限上述模型/货权/H/共享/预算边界；不设计或实现下一算法，不干涉Cursor正在做的完整骨架研究。无新actual、无禁止世界读取/生成、无其他优化进程启动。
