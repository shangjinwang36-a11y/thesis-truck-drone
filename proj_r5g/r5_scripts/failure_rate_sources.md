# 末端配送失败率文献依据（第五轮，2026-11-13 检索；逐条打开原文核对，未核对到的单独标注）

## A. 包裹物流“首次投递失败率”（地面末端）
1. Loqate《Fixing Failed Deliveries》报告 (https://www.loqate.com/media/bjgbpizl/fixing-failed-deliveries-final.pdf) —— 已下载 PDF 核对原文：
   “In the US, 8% of first-time deliveries fail, at an average cost of $17.20. In Germany, 7% … €14.69 … In the UK, it’s a 6% failure rate … £11.60”；另：“24% saying more than 1 in 10 orders aren’t delivered at the first attempt”。
2. FreightWaves / Modern Shipper, Brian Straight, 2022-07-11 (https://www.freightwaves.com/news/solving-for-last-mile-delivery-failures) —— 已打开核对：“8% of all last-mile deliveries have a failure rate on their first delivery attempt”（OneRail 说法）；同文：Home Delivery World Europe 会议上“heard the failure rate there was as much as 30%”（OneRail 创始人转述，属传闻性上界，非实证统计）。“the most common type of failed delivery is when the customer requires a signature … but then is not at the location”。
3. Lim, S.F.W.T., Jin, X., Srai, J.S. 等, “Do it right the first time: Vehicle routing with home delivery attempt predictors”, Production and Operations Management 2023, doi:10.1111/poms.13926 —— 摘要（搜索结果摘要页，Wiley 页面本次超时未全文打开）：“Up to 20% of all business-to-consumer deliveries fail on the first attempt.”（注：作者列表以出版页为准，引用前需再核对。）
4. SmartRoutes 博客汇总 (https://smartroutes.io/blogs/delivery-success-rates-key-stats-for-retail-and-ecommerce/) —— 已打开核对：“Globally, 8–20% of parcels fail to reach the recipient on the first attempt”；“Around 36% of failed first attempts occur because recipients are not home”（该博客转引 FreightWaves/HBR、Alexander Jarvis；二手来源，仅作佐证）。
5. arXiv:2404.02442（Data-driven Optimization for Drone Delivery Service Planning with Online Demand）引言 (https://arxiv.org/html/2404.02442) —— 已核对原文：“Failed first deliveries can account for up to 60% of all orders for a service provider (Song et al., 2009), the primary reason being the absence of the customer during package handover.”（对 Song et al. 2009 的转引，极端上界；未核对 Song 原文，不作为取值依据。）

小结：成熟市场的首次投递失败率约 6–8%（Loqate 三国数据），一般文献区间 8–20%，“最高 20%/30%”见于综述性/传闻性表述。

## B. 无人机配送的试点失败/中止（技术、天气、障碍；多数是“已飞但无法完成投递”的比例）
6. Operation Last Mile 白皮书 (https://www.updwg.org/wp-content/uploads/2020/11/Operation-Last-Mile-White-Paper_FINAL_6.1.20.pdf) —— 已下载核对：“During the 90 delivery flights, one flight was aborted due to wind instability.”（1/90 ≈ 1.1%，该航次重飞成功）。
7. Wing 澳大利亚 2017 试点：VentureBeat 转述 WSJ (https://venturebeat.com/business/alphabet-spinout-wings-drones-are-too-noisy-customers-say)：“drones are sometimes forced to land due to high winds and obstructions … touch down five times out of 2,000 deliveries”（0.25%）。（转述，WSJ 原文未核对。）
8. 日本偏远岛屿固定翼无人机送药示范 (https://pmc.ncbi.nlm.nih.gov/articles/PMC12022430/)：“62 patients … successful except for two patients whose drone deliveries were canceled because of strong winds.”（2/62 ≈ 3.2%）。
9. WeRobotics 秘鲁货运无人机试飞报告 (2017)：“44 complete flights … 93% of the flights were successful … three technical failures”（3/44 ≈ 6.8%，技术故障而非客户原因）。
10. 奥地利邮政 HEIDI 试点（ITA 技术评估报告 https://epub.oeaw.ac.at/ita/ita-projektberichte/2018-01.pdf）：“1000 test flights … functioning well from a technical point of view in 99% of the cases”（≈1% 技术失败）。
11. WeRobotics 多米尼加 2019 报告 (…/FINAL-WeRobotics-and-DR-Flying-Labs-Cargo-Drone-Field-Tests-for-Pfizer-2019.pdf)：“a number of aborted deliveries due to weather … none of the 101 flights … resulted in a crash”（未给次数/比例）。
12. 美团无人机（新浪财经 2025-06-23, https://finance.sina.com.cn/stock/t/2025-06-23/doc-infazvxp0067526.shtml）：“雷雨天气导致停运，或是单纯的空域管制，都有可能导致无人机外卖暂停服务，可靠性远不如人工配送”；自主处置“逼停”事件 49%；公开资料未披露失败率（搜索未发现）。

## C. 未找到/不能编造的部分
- **没有找到**公开、可核对的“无人机配送中因客户不在/降落点被占用而失败”的百分比（Wing/Zipline/Amazon/美团均未公开）。
- 无人机试点中“飞到但无法完成投递”的实测比例约 0.25%–7%（上列 6–10），主要是风/障碍/技术原因；这低于地面首次投递失败率。

## D. 对 p 取值的依据与如实说明
- p=0.10：落在 8–20% 的地面首次投递失败率区间内（Loqate 美国 8%，一般文献 8–20%），并且高于无人机试点实测 0.25–7%，作为“较乐观的现实上界”。
- p=0.20：对应文献“up to 20%”（Lim et al. 2023），代表“失败较多的城市/需签收/客户不在场景”。
- p=0.30：仅对应传闻性“as much as 30%”（FreightWaves 转述会议），**没有实证来源**，只能作为压力/敏感性情景，不得写成“现实失败率”。
- 论文中必须说明：p 是把地面“客户不在/无法交接”的失败率迁移到无人机末端交付（客户需在场取件/降落点可用），并非无人机实测值；实测无人机试点中止率更低（~1–7%）。结论应表述为对 p 的敏感性分析。
