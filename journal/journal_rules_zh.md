# 《Computers & Operations Research》投稿规范摘要（中文）

本文档是给毕业论文 / SCI 投稿准备用的格式与政策摘要。规范以期刊官方 Guide for Authors 为准；正文提取自 2024-04-15 的官方页面存档，开放获取费用与 Elsevier 生成式 AI 政策另行核自 2026-11-12 的官方页面。投稿前请再打开一次直播页面核对是否有更新。

- 期刊：Computers & Operations Research（ISSN 0305-0548，Elsevier / Pergamon）
- 官方指南：https://www.sciencedirect.com/journal/computers-and-operations-research/publish/guide-for-authors
- 本地全文：`/workspace/thesis/journal/guide_for_authors.md`
- 投稿系统：https://www.editorialmanager.com/CAOR/default.aspx
- 推荐模板：官方 LaTeX 类 `elsarticle`（本刊参考文献为著者-出版年制，请用 `elsarticle-template-harv.tex` + `elsarticle-harv.bst`）

---

## 1. 为什么选定这本期刊

在已核到「中科院期刊分区表 2025 年 3 月升级版」为大类 **2 区**、且确实刊发卡车–无人机协同配送 / 车辆路径论文的期刊里，COR 与本文的匹配度最好：它就是计算运筹学、车辆路径、数学启发式（matheuristic）、ALNS / MILP 这类工作的核心刊物。同档可备选的还有 *Computers & Industrial Engineering*（工程技术 2 区且为 Top，影响因子更高、相关论文也多，但网友反馈审稿明显更慢）以及 *IEEE Transactions on Intelligent Transportation Systems*、*Applied Soft Computing* 等。详细对照见同目录 `journals_comparison_zh.md`。

分区来源说明：中科院文献情报中心官方分区表网站通常需登录，本次未能直接打开官方表。下表数字来自多家公开聚合站对「2025 年 3 月升级版」的一致转载（LetPub、爱科学、Justscience、sci365 等）。2026 年 3 月另有「新锐期刊分区表」，口径不同，不能当作中科院升级版。

---

## 2. 稿件总体结构

期刊实行 **Your Paper Your Way**：初稿可以用单一 Word 或 PDF 投稿，版式不强制，但必须包含把内容讲清楚所必需的部分。录用前修改稿须提供可编辑源文件（Word 或 LaTeX）。

建议按指南中的要素组织（可按运筹学论文习惯微调，但标题层级要编号）：

1. 题名页（Essential title page information）
2. Highlights（强烈建议，单独文件）
3. Abstract
4. Keywords（紧接摘要之后）
5. Graphical abstract（可选，鼓励）
6. Introduction
7. 问题 / 模型 / Material and methods 或 Theory
8. 算法与计算实验（Results；可与 Discussion 合并）
9. Discussion（不要简单重复结果）
10. Conclusions（可独立成节，也可作为讨论的小节）
11. Appendices（如有：附录 A、B…；公式编号为 (A.1)、(B.1) 等）
12. Acknowledgements、Funding、CRediT、利益冲突、数据可用性、生成式 AI 声明
13. References

章节必须编号：1, 1.1, 1.1.1, 1.2…；摘要不编号。文内交叉引用要用编号，不要只写 “see the text”。每一级标题单独成行。

题名页必须包括：简明题名（尽量不用缩写和公式）；每位作者的名、姓与所属机构（用上标字母对应地址，含国家）；通讯作者及电子邮箱；若作者此后更换单位，可用“Present address”脚注，但完成工作的单位仍须保留为主要地址。

---

## 3. 摘要、关键词与 Highlights

**摘要（Abstract）**

- 必须提供简洁、如实的摘要：写明研究目的、主要结果和主要结论。
- 摘要常被单独转载，必须能独立成文。
- 尽量不要在摘要中引用文献；如必须引用，写作者与年份。
- 非常用缩写尽量不用；如必须使用，须在摘要中首次出现时给出定义。
- **官方指南未规定字数上限。** 不要自行写成“必须 250 词”。实际写作建议控制在约 200–250 词，并以投稿系统当时的提示为准。

**关键词（Keywords）**

- 紧接摘要之后，**最多 6 个**。
- 使用美式拼写；避免过于宽泛或复数形式，也避免把多个概念用 and / of 串在一起。
- 缩写须是本领域已通行的用法。关键词用于检索。

**Highlights（本刊可选，但强烈鼓励）**

- 3 至 5 条要点，概括创新结果及（如有）新方法。
- 每条最多 **85 个字符（含空格）**，指南另一处同时写了「或每条最多 20 个单词」。
- 必须作为单独的可编辑文件上传，文件名含 `Highlights`。
- 示例见 https://www.elsevier.com/highlights

**图形摘要（Graphical abstract）**：可选，鼓励。单独上传。最小约 531 × 1328 像素（高 × 宽），在 5 × 13 cm、96 dpi 屏幕上应可读。首选 TIFF、EPS、PDF 或 MS Office 文件。按 2026 年 6 月 Elsevier AI 政策，**图形摘要不得用通用生成式 AI 图像工具制作**，应使用正规科学绘图工具。

---

## 4. 参考文献体例

- **初稿**：体例不强制，但全文必须一致；须有作者、题名、刊名/书名、年份、卷期或文章号/页码；强烈建议提供 DOI。
- **正式体例（校样阶段也会按此排）**：**Harvard 著者–出版年制**（不是数字上标）。
  - 一位作者：Name (year) 或 (Name, year)
  - 两位作者：Name and Name (year)
  - 三位及以上：Name et al. (year)
  - 文中多条文献可按字母序再按年代，或按年代再按字母序。
  - 文后目录：先按作者姓氏字母序，再按年代；同一作者同一年用 2000a, 2000b。
- 期刊名按 *List of Title Word Abbreviations* 缩写。
- 每条正文引用必须出现在目录中，反之亦然。
- 数据引用在条目前列 `[dataset]`（正式出版时该标记不会印出）。
- LaTeX 请用 `elsarticle-harv.bst`，不要用编号式 `elsarticle-num.bst`。
- 投稿电子稿前，若使用 EndNote / Mendeley 等，须去掉域代码（field codes）。

示例（指南原文）：

> Van der Geer, J., Hanraads, J.A.J., Lupton, R.A., 2018. The art of writing a scientific article. Heliyon. 19, e00205. https://doi.org/10.1016/j.heliyon.2018.e00205.

---

## 5. 图表与公式

**图**

- 按文中出现顺序编号；图题（caption）含简短标题 + 说明，标题不要写在图里面。
- 图内文字尽量少，但符号和缩写必须在图题中解释。
- 初稿可将图放在正文相应段落旁（不要一律堆到文末），图题紧跟图下。
- 字体尽量统一：Arial/Helvetica、Times New Roman/Times、Symbol、Courier。
- 注明该图是单栏、1.5 栏还是双栏。
- 单张图文件超过 10 MB 须单独上传。
- 格式与分辨率：
  - 矢量图：EPS 或 PDF（嵌入字体或把文字转为图形）
  - 彩色/灰度照片：TIFF 或 JPG，至少 300 dpi
  - 位图线条图：至少 1000 dpi
  - 线划与半色调混合：至少 500 dpi
  - 不要用 GIF、BMP、PICT、WPG 等屏幕优化格式
- 彩色图：录用后在线彩色免费；指南写明印刷也可彩色且不另收费。
- 不要把图做成无法编辑的低分辨率截图。

**表**

- 必须作为可编辑文本，不能做成图片。
- 按出现顺序编号；表注放在表体下方。
- 避免竖线和单元格底纹；不要与正文结果简单重复。

**公式**

- 作为可编辑文本提交，不要截成图。
- 简单式子尽量随文；小分式可用斜线（X/Y）。变量原则上用斜体。
- 需要单独成行并在文中引用的公式须连续编号。

**视频等**：单个文件建议不超过 150 MB，合计不超过 1 GB。

---

## 6. 生成式 AI 使用声明（务必遵守）

本刊 Guide for Authors（2024 年存档表述）与 Elsevier 2026 年 6 月更新的《Generative AI policies for journals》需一并遵守；若两者细节有出入，以更新后的出版社政策及投稿时直播指南为准。

**写作过程**

- AI 可以辅助提高可读性和语言，但不能替代作者自己的分析、判断和原创贡献。
- 必须有人工审阅和把关。作者对全部内容负责。
- **不得把 AI 工具列为作者或共同作者，也不得把 AI 当作作者来引用。**
- 若在写作过程中使用了生成式 AI / AI 辅助技术，须在正文参考文献之前单列一节，标题为：
  - `Declaration of Generative AI and AI-assisted technologies in the writing process`
    （2026 年政策也可写为 *Declaration of generative AI and AI-assisted technologies in the manuscript preparation process*）
- 推荐句式：

  > During the preparation of this work the author(s) used [NAME OF TOOL / SERVICE] in order to [REASON]. After using this tool/service, the author(s) reviewed and edited the content as needed and take(s) full responsibility for the content of the publication.

- 仅用于检查拼写、语法、标点或普通文献管理功能的基础工具，不必声明。
- 若没有需要披露的事项，不必增加此节。
- 若 AI 用于研究过程本身（算法设计、代码、数据分析等），应写在 Methods 中，说明工具名称、版本与用途，而不是只写在上述声明里。

**2026 年 6 月政策中的补充要点（官方页面）：**

- 允许：整理文献、帮助组织结构、改进作者已写文字的语言与清晰度、对照指南做完整性检查、在人工把关下制作说明性示意图（流程图等，须在图题和总声明中披露工具与版本）。
- 数据可视化仅当输出忠实来自真实数据、方法可复现时可使用 AI 辅助，并在 Methods 中说明。
- 禁止：在缺乏作者实质性智力贡献的情况下直接生成章节；伪造或篡改数据、结果或参考文献；用 AI 生成或改动原始实验图像。
- 禁止用通用生成式 AI 图像工具做图形摘要。
- 作者应保留所用工具、提示与修改痕迹，以备编辑要求时提供。
- 审稿人和编辑不得把稿件上传到外部 AI 工具。

对本论文的实际含义：文献检索与语言润色可以声明；算法与实验代码若有 AI 辅助，应写进方法部分；所有参考文献必须人工核验，不得出现虚构条目。

官方政策：https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals

---

## 7. 其他必交声明与政策

- **利益冲突**：即使没有也要声明 `Declarations of interest: none`；另填期刊的 Declaration of Interest 表，两处信息须一致。
- **作者贡献**：通讯作者须按 **CRediT** 14 种角色列出每位作者的贡献（Conceptualization, Data curation, Formal analysis, Funding acquisition, Investigation, Methodology, Project administration, Resources, Software, Supervision, Validation, Visualization, Writing – original draft, Writing – review & editing）。通常在投稿系统中填写，也可在正文中列出。
- **投稿声明**：未一稿多投；除摘要、讲座或学位论文等允许情形外未曾正式发表；全体作者同意投稿。稿件可能经过 Crossref Similarity Check 查重。预印本（含投稿时可选择在 SSRN 发布）一般不视为先行发表。
- **资金**：按指南格式列出资助机构与编号；无资助可写 “This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors.”
- **致谢**：放在参考文献之前的独立节，不要放在题名页。
- **研究数据**：本刊要求在合适情况下共享支撑论文的数据，也可包括软件、代码、模型、算法等；投稿时需提供数据可用性说明。建议把代码与算例数据放到可引用的仓库并在文中引用。
- **语言**：英文，美式或英式均可，但不要混用。
- **审稿**：单盲（single anonymized）；编辑初审后通常至少两位独立审稿人。
- **推荐审稿人**：可提供若干潜在审稿人及机构邮箱；不要推荐近三年合作者、同事、有利益冲突者或现任编委；注意地域与其他多样性。是否邀请由编辑决定。
- **校样**：录用后一般请在两天内在线改校样；此阶段不得大幅改动内容。

---

## 8. 开放获取与费用

来源：期刊官方 Open access options 页面（2026-11-12 读取）。

| 选择 | 费用 | 说明 |
| --- | --- | --- |
| 订阅出版（Subscription） | 无 APC | 默认途径。录用稿（accepted manuscript）机构知识库开放须遵守 **36 个月** 禁运期；正式出版 PDF 不得自行传到 ResearchGate 等平台。 |
| 金色 OA | **USD 3,260**（不含税） | 可选。CC BY / CC BY-NC / CC BY-NC-ND。是否 OA **不影响** 审稿与录用。部分高校可能有 Elsevier 协议减免，以投稿系统报价为准。 |

通讯作者在订阅途径下可获得 50 天免费分享链接（Share Link）。

---

## 9. 模板与本地文件

Elsevier **没有**为本刊提供必须使用的官方 Word 专用模板。官方支持中心说明：用 Word 按 Guide for Authors 准备即可，版式保持简单，避免文本框和复杂分栏。CRediT 角色在 Editorial Manager 中填写。

官方 LaTeX 模板已下载（CTAN，Elsevier article class / CAS 模板包）：

| 路径 | 说明 |
| --- | --- |
| `/workspace/thesis/journal/elsarticle.zip` | 官方 `elsarticle` 包装压缩包（CTAN，2026-01-09） |
| `/workspace/thesis/journal/elsarticle/elsarticle-template-harv.tex` | **本刊应使用的哈佛体例稿件模板** |
| `/workspace/thesis/journal/elsarticle/elsarticle-harv.bst` | 配套 BibTeX 样式 |
| `/workspace/thesis/journal/elsarticle/doc/elsdoc.pdf` | 官方类文件说明 |
| `/workspace/thesis/journal/els-cas-templates.zip` | Elsevier CAS 单栏/双栏附加模板（CTAN） |
| `/workspace/thesis/journal/guide_for_authors.md` | 指南正文（来自官方页面存档） |
| `/workspace/thesis/journal/sources/` | 存档 HTML、开放获取页面原文 |

使用提示：`elsarticle.cls` 需由 `latex elsarticle.ins` 生成，或直接使用 TeX Live / Overleaf 中已安装的 `elsarticle`。初稿不必先排成期刊最终双栏版式。所有源文件须放在同一目录（不要用子文件夹），否则 Editorial Manager 无法编译。
