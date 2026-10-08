# S18 工业 G2 公开证据与适用性结论

2026-10-08；PR151 / LOG198。研究基线为已发布 S18 simulation r2。**公开证据研究已完成并形成结论，工业 G2 仍 OPEN / NOT_ESTABLISHED；Q01—Q06 没有一项取得覆盖本项目的关闭依据。** 本次结果是已定位的工业要求、适用性核查和剩余证据清单，不是取得工业资格。既有 S18-SIM-A1 仿真批准及发布继续有效；冻结产品、数值和假设不变。

## 对象与判定方法

对象仅为 SR-W1/SR-W2 既有结构版本的底框 W-B、顶框 W-T，同输出人工 H 与人工装夹设定→隔离机器人焊接→确认停机人工卸载 HR-seq。同步危险区人机焊接、完整无人生产、新设备能力及新产品设计不在对象中。原资格要求见[钢体系规格](../model/selected_steel.md)和[Q01—Q06裁定稿](../model/S18_qualification_decisions_r1.md)。

当前 B-ST 的钢号、截面、板厚和节点仍为未知，R1/FIX-J2 未绑定实际工业设备/工装型号；S18-SIM-A1 的接头集合、过程与程序ID是研究假设。这使外部资格的覆盖范围无法与目标接头逐项匹配。结论依据实际查到的材料及这些目标缺项，不依据旧 OPEN 标签，也不声称全球或未公开档案中没有所需记录。

证据分为三类：标准/指南说明要求，其他产品或工厂记录说明工程存在，项目适用记录证明本目标满足要求。本次取得前两类，尚未取得第三类。相同接头族可能由既有适用评定覆盖，也可能存在获应用标准允许的 SWPS 采用或预评定路径；不能一律要求每个产品新做试验、两模式各有一份独立WPQR，更不能在缺目标参数时默认继承。

本项目未选工业制造地点、合同或适用法规体系。ISO、香港钢规、新加坡指南和AWS作为候选技术依据分别核对，不拼接成一个宣称已获采纳的合规体系。标准发布/确认状态按本次官方页面记录；收费全文、未读取表格和草案均不冒称已完整核验。

## 原工业线索重新核查

| 来源 | 实际核查及新增判断 | 对本项目的适用结论 |
| --- | --- | --- |
| B01 BCA指南 | 新取86页与既有原件摘要一致；视觉核对印刷p48、p65。p48同时强调工艺/工序/工装；p65把WPS/WPQR、人员、焊材及工装/框架检验明确列入生产QC | 支持机器人替代方向与资格清单，不给本接头或本产品资格 |
| B02 CSCEC产线 | 2024-06-28正文报告自动上下料、定位、焊接与视觉程序修正 | 其全自动上下料不直接证明本项目人工装卸HR-seq；无本接头评定附件 |
| B03 Kobelco报告 | 2024-03 §3.4/Table2使用32mm钢柱/贯通隔板试样、指定焊丝与温控，比较REGARC常规/新条件 | 不是H与HR对比，不能将力学结果、板厚或节拍移植到未知底/顶框 |
| B11 模块焊接方案 | 2024-04-10正文及AluHouse合作支持柔性工装、激光视觉及焊接程序/工艺库 | 工艺库推荐不等于适用WPS/WPQR，多机合作不等于同步人机安全资格 |

## 新找到的工业要求与资格路径

工艺方面，ISO15607/15609/15614定位了WPS内容、评定和适用范围，ISO15612定位了采用其他组织SWPS的受限路径。AWS D1.1 2025-AMD1官方预览区分预评定与资格章节，但未取得完整条件；本项目钢材/厚度/接头未定义，因此不能选定一个预评定条目宣称已通过。 [ISO15612官方范围](https://www.iso.org/standard/65971.html)、[AWS官方预览](https://pubs.aws.org/Download_PDFS/D1.1-D1.1M-2025-AMD1_PV.pdf)。

人员方面，ISO9606-1针对钢手工/部分机械化焊工，ISO14732:2025针对机械化/自动焊操作与调试。仅装卸者是否落入14732须根据其实际是否设置设备或调参判断；本项目OP1装夹/设定职责尚无工业分解。ISO14731的焊接质量协调也不自动决定机器人运行段是否允许OP1离岗。 [ISO9606-1](https://www.iso.org/standard/54936.html)、[ISO14732](https://www.iso.org/standard/82980.html)、[ISO14731](https://www.iso.org/standard/68893.html)。

机器人安全方面，ISO10218-2:2025面对完整应用和单元集成；OSHA指南支持任务级风险评估及措施验证。29CFR1910.147面对维护/检修危险能量控制，并有换班保护连续性要求，不能将所有正常装卸都认定必须LOTO，也不能用它给0.1h交班赋工业定值。J2的人员释放条件仍需具体安全方案证明。 [ISO10218-2](https://www.iso.org/standard/73934.html)、[OSHA应用指导](https://www.osha.gov/otm/section-4-safety-hazards/chapter-4)、[1910.147范围及换班条文](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147)。

检验方面，ISO5817为共同缺陷质量等级候选，ISO17635按材料/厚度/工艺和检验范围选NDT；其摘要明确质量等级不能直接解释为NDT接受等级。ISO17637支持目视检查方法范围，均不产生实际合格结果。香港2023钢规§14.3进一步提供WPS、工装、检验等待、批准返修及复验的可查条文。其小焊缝审批例外不等于取消WPS或项目G2要求；热过程/延迟检验也不能靠模拟时钟自动满足。未将任何外部等待或焊接数值写入模型。 [ISO17635](https://www.iso.org/standard/85705.html)、[香港钢规第14章](https://www.bd.gov.hk/doc/en/resources/codes-and-references/code-and-design-manuals/suos2011/SUOS2011_section_14.pdf)。

## ALUMIC 官方记录的边界

新取得屋宇署2023-12-21的 MiC21/2023 ALUMIC 原则性接纳函，7页扫描件逐页核对。函载到期为2028-12-21；这只描述函件期限，不断言当前全部条件和工厂证书持续满足。附录IV列有钢框架制造工厂；附录II/III要求遵循被接纳图样、试验及材料/方法条件。函第2页明确不能替代具体工程的审批与同意，工厂ISO9001要求也不是焊接程序资格证明。 [ALUMIC官方接纳函](https://www.bd.gov.hk/doc/en/resources/codes-and-references/mic/MIC0212023_IPA.pdf)。

结合制造方智能生产页面及B11，外部模块钢框架自动化的证据比仅有供应商宣传更完整。但公开函件没有交付SR-W1/W2两模式WPS/WPQR、机器人程序、停点或检验结果；本项目也没有证明采用ALUMIC图样或满足其条件。不能因供应商相同、名义尺寸近似、或者函件尚未到期，继承其资格。

## Q01 至 Q06 结论

| 要求 | 已定位依据 | 本项目剩余关键证据 | 结论 |
| --- | --- | --- | --- |
| Q01 接头范围 | B01/B03，G01–03/G15/G17 | 结构/接头/焊缝版本、材料板厚、姿态及范围包含关系 | OPEN |
| Q02 双模式工艺资格 | B01–03/B11，G01–04/G11/G15–17 | 适用标准体系、H/HR WPS及评定或获准采用路径与覆盖证明 | OPEN |
| Q03 程序和工装 | B01–03/B11，G07/G13/G15/G17–18 | 实际设备/程序/夹具版本、精度/可达与变更重验 | OPEN |
| Q04 人员与隔离 | B01/B11，G05–07/G12–15/G17 | 实际职责/资格、J2风险和防护验证、监督释放条件 | OPEN |
| Q05 检验及同输出 | B01–03/B11，G08–11/G15/G17–18 | 共同接受准则、检验计划及实际H/HR结果、框架检验 | OPEN |
| Q06 停点与异常 | B03，G03/G07/G13–15 | 工艺焊段/停点、中断恢复、换班与批准返修/复验 | OPEN |

完整“要求—URL/版本/定位—范围—本项目对应—证据/缺口—关闭资料”见[六项矩阵](S18_industrial_g2_matrix_r1.tsv)。提出的资料责任角色只是接续建议，尚无外部提供承诺、委派或现场验证。

## 来源清单

以下均于2026-10-08实际打开；访问范围与限制详见[来源台账](S18_industrial_g2_sources_r1.tsv)。

- **B01** [BCA PPVC Guidebook](https://isomer-user-content.by.gov.sg/338/b8a8e7e3-ff40-496c-8246-1a582efb88ca/ppvc_guidebook.pdf)；既有指南；86页；官方2017发布线索，非2026新版。定位：§4.2/4.2.1 印刷p48=PDF50；§4.2.2 p49=PDF51；§8.1.2 p65=PDF67。
- **B02** [RoboticPlus Automatic Modular Steel Frame Production Line for CSCEC](https://www.roboticplus.com/en/news/details/cate_id/61/id/495.html)；2024-06-28。定位：标题/日期及正文自动上下料、定位、焊接、程序生成段。
- **B03** [Kobelco Robotic Welding System with New Equipment for Steel Structures](https://www.kobelco.co.jp/english/r-d/technology-review/pdf/41_023-029.pdf)；Technology Review 41，2024-03，pp23–29。定位：§3.3/3.4，印刷p27=PDF5，Table 2；§4系统。
- **B11** [RoboticPlus Empowering Modular Construction Innovative Welding Solutions](https://www.roboticplus.com/en/news/details/cate_id/61/id/477.html)；2024-04-10。定位：正文1–4及AluHouse合作段。
- **G01** [ISO 15607:2019](https://www.iso.org/standard/71495.html)；2019-10；第2版，2025确认。定位：Abstract；Annex A/B/C仅目录描述。
- **G02** [ISO 15609-1:2019](https://www.iso.org/standard/75556.html)；2019-08；第2版，2025确认。定位：Abstract。
- **G03** [ISO 15614-1:2017](https://www.iso.org/standard/51792.html)；2017-06；第2版，2017-11纠正版；列有Amd1:2019；2022确认。定位：Abstract及Life cycle。
- **G04** [ISO 15612:2018](https://www.iso.org/standard/65971.html)；2018-06；第2版，2023确认。定位：Abstract。
- **G05** [ISO 9606-1:2012](https://www.iso.org/standard/54936.html)；2012-07；第2版，2023确认；DIS后继仍开发。定位：Abstract及Life cycle。
- **G06** [ISO 14732:2025](https://www.iso.org/standard/82980.html)；2025-06；第3版，替代2013。定位：Abstract及Life cycle。
- **G07** [ISO 10218-2:2025](https://www.iso.org/standard/73934.html)；2025-02；第2版，替代2011。定位：What is addressed / General information；不用页面异常FAQ修订描述。
- **G08** [ISO 5817:2023](https://www.iso.org/standard/80209.html)；2023-02；第4版。定位：Abstract。
- **G09** [ISO 17635:2025](https://www.iso.org/standard/85705.html)；2025-04；第4版，替代2016。定位：Abstract。
- **G10** [ISO 17637:2016](https://www.iso.org/standard/67259.html)；2016-12；第2版，2022确认。定位：Abstract。
- **G11** [ISO 3834-2:2021](https://www.iso.org/standard/81651.html)；2021-04；第3版，2026确认。定位：Abstract / General information。
- **G12** [ISO 14731:2019](https://www.iso.org/standard/68893.html)；2019-02；第3版，2024确认。定位：Abstract。
- **G13** [OSHA Technical Manual Section IV Chapter 4](https://www.osha.gov/otm/section-4-safety-hazards/chapter-4)；本轮现行网页；含2011/2012旧标准引文，不视作2025 ISO逐条解释。定位：§V safeguarding / §VII risk assessments / §VIII non-collaborative applications。
- **G14** [OSHA 29 CFR 1910.147](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147)；本轮现行官方条文。定位：(a)(2)范围；(d)/(e)隔离恢复；(f)(4)换班。
- **G15** [Hong Kong Code of Practice for the Structural Use of Steel 2011 2023 Edition](https://www.bd.gov.hk/doc/en/resources/codes-and-references/code-and-design-manuals/suos2011/SUOS2011_section_14.pdf)；2011钢规2023版，第14章，19页。定位：§14.3.1–3 p328；§14.3.4 p329；§14.3.6 pp330–333；Table14.2a/b。
- **G16** [AWS D1.1/D1.1M:2025-AMD1 official preview](https://pubs.aws.org/Download_PDFS/D1.1-D1.1M-2025-AMD1_PV.pdf)；2025版；2026-01-12 Amendment；2026-02第二次印刷。定位：封面/Abstract；目录Clause5 prequalification和Clause6 qualification；公开p1 Scope。
- **G17** [Buildings Department ALUMIC Letter of In-principle Acceptance MiC21/2023](https://www.bd.gov.hk/doc/en/resources/codes-and-references/mic/MIC0212023_IPA.pdf)；2023-12-21；函载到期2028-12-21；不据此宣称当前全部条件持续满足。定位：p1–2函；AppendixI p3，II pp4–5，III p6，IV p7。
- **G18** [AluHouse Smart Manufacturing](https://www.aluhouse.com/en/mic-smart-production.html)；网页无明确发布日期；核查2026-10-08；页脚年份非发布年。定位：Advanced Manufacturing Equipment / Steel MiC Line段。

## 检索与成果边界

检索覆盖原B01/B02/B03/B11、国际标准发布机构、香港结构钢与ALUMIC官方记录、制造方设施及SWPS/预评定替代路径，并针对研究产品标识和供应商WPS记录作定向补查。只采用实际打开的一手材料；论坛、AI生成工艺规程、商业标准转售摘要和搜索片段不作本项目资格证明。GB50661/50205官方域查询未获得可用发布机构正文，不据其推定条款或现行法律地位。

BCA多个URL的网页PDF读取失败，已通过直接HTTPS重新取得原官方资产并校验；另一监督指南链接404，未引用为已核验要求。Kobelco网页截图失败后用新取本地PDF视觉核对。访问失败、来源摘要及原始PDF摘要保存在[机器审阅](../validation/S18_industrial_g2_review_r1.json)。原件、扫描图、完整日志只留本地，不随自有代码许可再分发。

后续真正关闭G2的最短证据链是：先定义目标产品/接头和适用标准，再证明H/HR工艺的覆盖范围，随后绑定程序/夹具、人员/隔离、共同检验及合法停点。若目标设计不存在，继续搜索其他证书无法完成这个绑定；补入设计或调整研究边界须具体授权，不能由本次调研悄悄选材或改模。

本次未实施F1/F2修复、C1规划调整、工业用途放行、Git写入或S19以后步骤。完成本结论后按PR151顺序进行独立[问题复检](../validation/S18_g2_followup_recheck_r1.md)，再由负责人授意统一修复。成果为本地待审；拟远端操作为空，目标仍为现有仓库main，未拟新标签。
