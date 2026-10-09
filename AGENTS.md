# 仓库协作规则

2026-10-10现行静态外观验收与发布批准（PR167 / LOG223）：负责人通过最终设备/地面/打光效果并明确批准发布，要求README图片替换为最新版，决定S19A-STATIC-PUBLISH-APPROVAL-003。原15人物验收保持；已更新README全场及人物总览图片。静态成果ACCEPTED_WITH_DOCUMENTED_LIMITS / APPROVED_FOR_PUBLICATION，拟main单提交及新标签step-S19A-static-r1原子推送，实际回执与CI另核验。A2动作、A3视频及整步出口未完成，工业G2/后续边界保持，旧审阅与失败证据保持。[验收及确切发布范围](docs/validation/S19A_static_publication_r1.md)。以下旧状态按各自时点保留。


2026-10-10现行人物通过及对比度修订（PR166 / LOG221—LOG222）：负责人通过15人物静态外观，决定S19A-PEOPLE-VISUAL-ACCEPTANCE-002；要求集中调整CUT1承料色差、R1关节/控制柜、搬运车、手推车、测试托盘及场景打光/地面。已形成11张本次对照图和本地r2候选。深黑灰地面、浅工作区及四处橘黄条纹采用原地面UV改色，本轮新增几何0。现有1,313几何对象、728碰撞、已认可15人物属性/绑定保持，57回归及Kit完整关闭/退出0。修订效果VISUAL_REVIEW_PENDING / NOT_PUBLISHED；原图/失败证据保持，A2/A3剩余及工业G2/后续边界保持。[本次图片与回执](docs/validation/S19A_contrast_r2.md)。以下旧状态按各自时点保留。


2026-10-10现行整组静态外观（PR165 / LOG219—LOG220）：负责人改为集中完成拟调整内容后统一逐个图审，不再逐个暂停；保留人物建模并加强岗位/个体涂装。15人物、11设备和全场已形成44图及本地候选。原1,148几何对象、728碰撞体、15人身体尺寸/根位置/手位和实际障碍集合保持；57项回归通过，最终Kit完整关闭/退出0，首轮关闭异常保留。当前STATIC_BATCH_VERIFIED_WITH_LIMITS / BATCH_VISUAL_REVIEW_PENDING / NOT_PUBLISHED。A2动作未改，A3视频及整步验收未完成，S19B及后续未启动，工业G2保持。旧逐个暂停要求由本次明确纠正覆盖，原几何硬约束继续有效。[完整逐项图册与验证](docs/validation/S19A_static_batch_r1.md)。以下旧记录按各自时点保留。


2026-10-09现行W1图审通过与应用（PR164 / LOG218）：负责人通过W1静态外观，决定S19A-W1-VISUAL-ACCEPTANCE-001；已只应用W1。独立USD核对原1,148几何对象及15人物根位置/手位保持，与获批预览属性/材质一致，57项场景回归通过。P1、W2、Lop已分别生成图片，保持PREVIEW_PENDING / NOT_APPLIED。原尺寸硬约束和逐个体先图审后应用持续有效；A2/A3、整步验收及新发布仍未完成，S19B及后续未启动。[当前图片与回执](docs/validation/S19A_people_review_r1.md)。以下记录按各自时点保留。


2026-10-09现行S19A启动与逐个体图片审阅（PR161—PR163 / LOG215—LOG217）：S19 r2已实际限定验收、批准并发布，提交`5a69646fc3d4ed16cca0e6151dffe71b2447dae6`、标签`step-S19-r2`，CI双平台源码/隔离wheel各849项通过。负责人现授权S19A，并严格要求调整不得超出现有模型几何尺寸、每个个体先出图验收后落实。沿用main/目录，不建分支/worktree或子代理。当前W1独立A1预览及原路线方案为A1_REVIEW_PENDING / NOT_APPLIED；正式模型、碰撞、路径、手位、工时、容量和人因保持。工业G2 OPEN/NOT_ESTABLISHED；S19B及S20—S28未启动，新成果验收及确切发布另审。入口：[S19A步骤与图片审阅](docs/steps/S19A.md)。下方旧状态保留各自封存时点。


2026-10-09现行S19有限修复成果（PR160 / LOG214）：F1计划/延迟来源、F2严格类型缓存与F3正负零精确摘要在受测范围完成修复，GitHub README全面重写。新增25项，项目环境/隔离wheel各849项通过；原17组21,318行计划来源与指标复核通过。当前源码原5s/50ms窗口取得3候选/3缓存派工，带故障长预算诊断保持19未来承诺/110比较/3次合计0.75h延迟；两组事件/决策解压字节与原诊断一致。原包/完整长链和失败保持，本轮无新Kit/完整链。16文件候选S19-20261009-repair-r2为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；工业G2 OPEN/NOT_ESTABLISHED、后续未启动。入口：[有限修复审阅](docs/validation/S19_limited_repair_r2.md)。

2026-10-09现行有限修复授权（PR160 / LOG213）：负责人批准S19全审F1—F3有限本地修复，并新增GitHub README全面重写要求；沿用main/目录，不建分支/worktree或子代理。当前LIMITED_REPAIR_IN_PROGRESS；补充回归、源码/隔离wheel验证及新确切审阅包，原发布、冻结数值与历史证据保持。新快照验收/发布另审；工业G2 OPEN/NOT_ESTABLISHED，后续未启动。

2026-10-09现行S19发布后全量审阅（PR157—PR159 / LOG210—LOG212）：S19合并36文件已限定验收、批准并实际发布，提交`674f4fe1036615e80fca4520dacffc8182a8e4a4`、标签`step-S19-r1`，双平台源码/隔离wheel各824项通过。全审S19-1至S19-3并新跑67专项及生成检查，复现F1计划/延迟指标来源未完整绑定、F2缓存复用绕过严格类型两项P2，及F3正负零缓存导致精确摘要依赖调用顺序的P3。当前POST_RELEASE_REVIEW_FINDINGS_OPEN，不能认定逻辑无遗留；原批准、四项受测修复、全部长链与失败证据保持。仅审阅及必要治理，未修复源码、新发布或启动后续；工业G2 OPEN/NOT_ESTABLISHED保持。入口：[S19全量审阅](docs/validation/S19_post_release_audit_r1.md)。

2026-10-09现行S19-2合并成果（PR156 / LOG209）：四项问题在所列仿真范围完成修复与最终复验，候选S19-20261009-online-r2为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。同一351文件捕获源码的完整两订单及B+1双后端均全部接收，严格比较、独立执行/因果审计与Kit完整关闭/退出0通过；B+1原Bogie0阻挡未复现。源码/隔离wheel各824项通过。原5s/50ms前缀取得完整候选及实际派工，完整生产决策周期无5s超限，但50ms为协作退出且B+1 Kit最大反馈时延5.972s；非零未来承诺与实际延迟采用独立长预算诊断，均不构成硬实时或方法优势证明。原S19包及所有历史失败保持，新旧成果合并待确切验收/发布；冻结数值、工业G2 OPEN/NOT_ESTABLISHED和后续未启动保持。入口：[合并确切审阅](docs/validation/S19_online_r2.md)。

2026-10-09现行S19-2实施与复验（PR156 / LOG208）：性能缓存、独立增量审计、完整窗口保守初解、并发吊机扫掠准入及非零未来承诺已进入本地复验；源码/隔离wheel各822项通过。原5s/50ms真实前缀已有完整候选及实际派工证据，非零承诺采用单列长预算诊断；内部反馈校验/未来搜索分段及其限制见在线策略文档。第一轮统一源码复算发现未采用合法候选摘要未留存，已修复并保留失败；第二轮统一源码验证进行中。完整两订单/B+1最终双后端链尚未关闭，不作四项全部完成结论。现有成果继续挂起、未验收/未批准/未发布；原包、历史证据、冻结数值及工业G2 OPEN/NOT_ESTABLISHED保持，后续未启动。入口：[S19步骤](docs/steps/S19.md)。

2026-10-09现行S19-2交接授权（PR156 / LOG207）：负责人已知悉五项问题，要求现有S19成果及封包保留挂起，待前四项解决后汇总一并提交发布；明确仅做仿真，工业G2保持OPEN/NOT_ESTABLISHED，不开展工业落实。授权创建S19-2新对话，沿用当前目录/main、不建分支/worktree、ASTRA高思考强度，直接解决在线性能、B+1双后端差异/实际USD阻挡、最终源码完整长链验证和计划稳定性/未来承诺四项问题。当前LOCAL_CONTINUATION_AUTHORIZED，原候选未发布；原封包、摘要和失败证据保持，新旧成果最终合并形成确切审阅内容。S19A/S19B及S20—S28未启动。入口：[S19-2交接](docs/steps/S19_2_handoff.md)。

2026-10-09现行S19本地成果（PR155 / LOG206）：沿用已发布S18 r4基线，在线协作预算、完整候选缓存、版本失效、派工前再验证及承诺保护已完成有限实现；新增32项，源码/隔离wheel各806项通过。两订单及B+1完整链均完成接收并通过各自执行/因果审计，但B+1 Kit有3次5s超限和实际USD阻挡，严格轨迹一致性未成立；原五个Kit快速关闭报告缺返回回执，历史失败保留。最终源码有限窗口与长预算缓存诊断另列，不能替代原长链结果。候选S19-20261008-online-r1为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；工业G2 OPEN/NOT_ESTABLISHED，冻结数值保持。未执行新Git写入或启动S19A/S19B、S20—S28。入口：[S19审阅](docs/validation/S19_online_r1.md)。

2026-10-08现行发布与S19启动授权（PR153—PR155 / LOG202—LOG204）：S18修复r3已获限定验收及确切发布批准，原Windows CI超时证据保持；单文件CI时限修订r4已实际PUBLISHED，提交`d761df261dacd953db288e3ca55416b555255a4b`、标签`step-S18-simulation-r4`，双平台源码/隔离wheel各774项通过。负责人现授权创建“S19”新对话，沿用当前目录/main，不建分支/worktree，使用ASTRA高思考强度直接开展S19在线预算、回退与计划稳定性本地工作。S19为IMPLEMENTATION_AUTHORIZED；新成果验收及确切发布另审，S19A/S19B和S20—S28未启动。工业G2继续OPEN/NOT_ESTABLISHED，按已批准仿真研究域推进。入口：[S19步骤与交接](docs/steps/S19.md)。

2026-10-08现行修复成果（PR152 / LOG201）：负责人确认继续调度仿真研究；F1/F2已在受测仿真范围内一致修复。新增15项回归、源码/隔离wheel各774项通过；原16完整候选复验及原分数保持，原seed2实际策略保留有效候选且记1迭代/2试次。C1仿真研究域衔接已明确，工业G2继续OPEN/NOT_ESTABLISHED。候选S18-20261008-simulation-repair-r3为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；冻结数值及历史证据保持，后续未启动。入口：[S18 r3修复审阅](docs/validation/S18_simulation_repair_r3.md)。

2026-10-08现行工业G2结论及复检（PR151 / LOG198—LOG199）：公开证据研究已完成，22项一手来源及Q01—Q06矩阵可查；均未取得覆盖SR-W1/W2的关闭依据，工业G2保持OPEN / NOT_ESTABLISHED。S18-SIM-A1既有仿真批准/发布有效。结论后实际复检再次复现F1/F2两项P2，C1后续资格前置衔接仍待决定；源码/测试/冻结数值及原审阅保持，统一修复仍待负责人后续授意。本轮无Git写入或后续启动。入口：[G2证据结论](docs/research/S18_industrial_g2_evidence_r1.md)、[保留问题复检](docs/validation/S18_g2_followup_recheck_r1.md)。

2026-10-08现行交接授权（PR151 / LOG197）：负责人要求创建“S18-4”，沿用当前目录/main、不建分支/worktree、保持现有模型及思考强度选择，直接利用互联网公开资料开展工业G2检索与适用性核验。当前INDUSTRIAL_G2_EVIDENCE_WORK_AUTHORIZED，工业G2仍OPEN/NOT_ESTABLISHED，结论依实际证据。F1/F2及后续资格前置衔接问题保留，先完成G2工作再复检，待负责人后续授意统一修复；本次不修复实现或启动S19以后。交接：[S18-4](docs/steps/S18_4_handoff.md)。

2026-10-08现行发布与全量审阅（PR148—PR150 / LOG194—LOG196）：S18 r2已实际限定验收、批准并发布，提交`cd21aa0a26e53585b9bf8cc3a7b7b6900c428ac1`、标签`step-S18-simulation-r2`，双平台各源码/隔离wheel759项成功；原r1超时和标签保持。全量审阅S18-1至S18-3，新增100专项及生成检查通过，但复现F1班组修复异常丢失有效候选/漏记失败预算、F2候选班组与时段声明未绑定执行轨迹两项P2，当前POST_RELEASE_REVIEW_FINDINGS_OPEN，不能认定逻辑无遗留。获批仿真范围继续有效，工业G2 OPEN/NOT_ESTABLISHED不单独阻断该范围。本轮仅审阅/必要治理，未修复源码、执行新Git写入或启动后续；原封包/历史结果保持。入口：[S18全量审阅](docs/validation/S18_post_release_audit_r1.md)。

2026-10-08现行发布批准与预检发现（PR147 / LOG193）：负责人已明确批准87文件S18-20261008-simulation-publication-r1的具体提交/标签/atomic推送方案，记录S18-SIM-PUBLISH-APPROVAL-001。发布前复现F01：现行LF规范化改变四份获批CRLF JSON字节，导致SIM_APPROVED_INPUT_DRIFT；尚未暂存、提交、建标签或推送。原87批准与封包保持；拟仅对冻结.gitattributes增加四条原字节保留例外并形成88文件修订发布审阅，当前PROPOSED / DECISION_PENDING / NOT_IMPLEMENTED。工作区该冻结文件已按原摘要保持，源码/数值/工业边界与后续步骤不变。入口：[具体修订审阅](docs/validation/S18_simulation_publication_r1.md)。旧状态按各自封存时点保留。


2026-10-08现行限定验收（PR146 / LOG192）：负责人已批准85文件确切快照S18-20261008-simulation-r1，记录S18-SIM-ACCEPTANCE-001，成果ACCEPTED_WITH_DOCUMENTED_LIMITS；原封包、逐文件摘要及全部限制保持。原拟远端操作为空，本次不扩展为未列明的Git发布操作。具体main提交与step-S18-simulation-r1标签推送方案另形成确切发布审阅，当前DECISION_PENDING / NOT_PUBLISHED；无Git写入或后续启动。工业G2 OPEN/NOT_ESTABLISHED保持。入口：[实际验收](docs/validation/S18_simulation_acceptance_r1.json)。下方状态保留各自封存时点。


2026-10-08现行本地仿真成果（LOG191）：S18-SIM-APPROVAL-001的SR01—SR08已完成本地实现与V01—V08实际验证，候选S18-20261008-simulation-r1为SIMULATION_IMPLEMENTATION_VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。源码与隔离wheel各759项通过；最新SR-W1双产品、SR-W2及原WV01连续双后端链、严格比较和Kit正常退出通过；四共同8h通道及16个完整候选复验、实际反馈/交班、连续中断/取消HOLD和15个独立负例拒绝通过。213基线中11个获批消费者迁移、202个摘要保持，原数值与历史失败/封包不变。工业G2 OPEN/NOT_ESTABLISHED、符号焊接/合成质量接收及共用落点限制保持；未执行正式A/D、Git/远端写入或后续启动。成果验收及确切发布另审。入口：[确切审阅](docs/validation/S18_simulation_implementation_r1.md)。下文早期G2全域阻断与未迁移叙述按历史时点保留，当前获批仿真以本条及实际批准为准。


2026-10-08现行仿真范围批准与交接（PR145 / LOG189）：负责人已批准S18-SIM-SCOPE-20261008-r1的SR01—SR08及配套假设表，决定S18-SIM-APPROVAL-001；要求新对话S18-3沿用当前目录/main、不建分支/worktree，完成S18剩余本地实施、Kit验证和收尾，不调用子代理。仿真范围IMPLEMENTATION_AUTHORIZED，工业G2 OPEN/NOT_ESTABLISHED保持；不再以工业G2缺资料单独阻断已批准仿真。仅按具体条款修订冻结项，原数值/历史证据保持；内部子阶段不重复等待启动许可。V01—V08与完整双后端出口仍须实际通过；成果验收、确切发布和后续步骤另审。下方待审/全域阻断叙述保留历史时点，以本决定为准。 入口：[实际批准记录](docs/model/S18_simulation_scope_approval_r1.json)、[获批方案](docs/model/S18_simulation_scope_proposal_r1.md)。

2026-10-08现行范围提案（PR144 / LOG188）：负责人已授权编制具体S18仿真研究修订方案供审阅。S18-SIM-SCOPE-20261008-r1的SR01—SR08及配套假设表为PROPOSED / DECISION_PENDING / NOT_IMPLEMENTED；拟采用独立仿真研究准入并保留工业G2 OPEN。当前仅文档，未批准实质修订、未实施生产HR或改变冻结值，原39文件成果仍待验收。新完整口径和本地实施授权待本提案明确决定；Git发布及后续步骤未启动。入口：[具体方案](docs/model/S18_simulation_scope_proposal_r1.md)。

2026-10-08现行自适应成果（PR143 / LOG186—LOG187）：上一32文件有限成果获ACCEPTED_WITH_DOCUMENTED_LIMITS；新增条件C04反馈后逐动作联合重规划，75专项含于源码/隔离wheel各734项。八个自适应例与两个冻结对照保存记录双审计通过；搬运中R1故障改变未承诺焊接为H，装夹故障/取消截尾及晚卸载反向保持。213冻结文件保持，完整S18仍RESEARCH_BLOCKED_G2_OPEN；Q01—Q06、生产HR映射及Isaac全链出口未满。新39文件候选VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；无Git发布或后续启动。 入口：[当前审阅](docs/validation/S18_adaptive_control_r1.md)、[完整出口](docs/validation/S18_completion_exits.md)。

2026-10-08現行跨时刻成果（PR142 / LOG184—LOG185）：上一S18续接25文件成果已限定ACCEPTED_WITH_DOCUMENTED_LIMITS，未发布；本轮条件C04跨时刻无更新实际执行完成，65专项含于源码/隔离wheel各724项。九例实际执行/决策双审计及保存记录重建通过，四截尾保留；预算恰达实际完成误标已修正。213冻结文件、上一148项Python输入及旧封包/失败保持。候选S18-20261008-rolling-r1程序VERIFIED_WITH_LIMITS，完整研究RESEARCH_BLOCKED_G2_OPEN，新32文件快照ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。现行生产HR滚动联合、共同生产对照、资格及Isaac全链仍缺；实际HR禁用/A BLOCKED与门后设计保持。未执行Git发布或启动后续。入口：[S18跨时刻审阅](docs/validation/S18_rolling_control_r1.md)。

2026-10-08现行批准与继续（PR142 / LOG184）：负责人批准S18-20261007-continuation-r1有限成果并要求继续本地工作。原25文件封包保持、有限ACCEPTED_WITH_DOCUMENTED_LIMITS；原拟远端操作为空，未获Git发布授权。沿用main/目录，不建分支/worktree或子代理，继续跨时刻条件无更新执行与独立决策审计。G2 OPEN/实际HR禁用/A BLOCKED及其余冻结边界保持，不把批准当资格或完整S18验收。当前IMPLEMENTATION_IN_PROGRESS，新成果验收/确切发布另审，后续步骤未启动。

2026-10-07现行续接成果（PR140—PR141 / LOG182—LOG183）：S18-2完成全状态类别无更新的同刻条件控制、现行S15固定接口/联合拒绝边界及M01/M02具体门后设计。50专项含于源码/隔离wheel各709项，213冻结文件、原S17七例及S18九例保持；实际WALK执行/因果双审计PASS，无新Kit。负责人委托AI自主判断后，依据前置证据保持G2 OPEN/HR禁用/A BLOCKED，不删A或改时长/负荷。候选S18-20261007-continuation-r1程序VERIFIED_WITH_LIMITS，完整研究RESEARCH_BLOCKED_G2_OPEN；新快照ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。真实资格、生产HR/Isaac全链及滚动联合消融出口仍缺；未启动后续步骤。入口：[S18-2审阅](docs/validation/S18_continuation_r1.md)。

2026-10-07现行批准与续接（PR140 / LOG181）：负责人批准已交付S18条件程序有限成果并明确要求创建“S18-2”新对话，沿用现有main/目录、不建分支/worktree，直接完成S18剩余本地工作。原17文件封包保持；此决定不是完整S18验收、工业资格取得、具体研究范围替代裁定或Git/远端发布批准。G2 OPEN/HR禁用保持，继续推进资格核查、具体生产映射/冻结修订表、联合方法与完整状态消融及必要验证治理；真实研究准入仍受适用门控制。新成果验收和确切发布另审，S19—S28及S19A/S19B未启动。

2026-10-07条件程序成果（PR139 / LOG180）：S18准入拒绝与条件联合分支已有限验证，34专项、源码/隔离wheel各693项通过，213冻结文件及原S17七例保持。候选S18-20261007-branches-r1程序VERIFIED_WITH_LIMITS，整步RESEARCH_BLOCKED_G2_OPEN；ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。真实资格、现行生产HR映射及完整状态消融出口未满；合成分支不替代研究准入。成果验收与确切发布另审，S19—S28及S19A/S19B未启动。入口：[S18程序审阅](docs/validation/S18_joint_branches_r1.md)。

2026-10-07现行交接（PR138—PR139 / LOG178—LOG179）：S17 r2已实际限定验收、批准并发布，提交 `62c1c5393cb715b8089a93ee7ec658a0eb0e571d`、标签 `step-S17-r2`，双平台各源码/隔离wheel659项成功。负责人已授权沿用main/目录直接实施S18，不建分支/worktree或子代理。当前IMPLEMENTATION_IN_PROGRESS；G2仍OPEN，研究功能与A实验BLOCKED，先完成接口、拒绝门及条件程序机制验证。新成果验收与确切发布另审，S19—S28及S19A/S19B未启动。入口：[S18步骤卡](docs/steps/S18.md)。

2026-10-07有限修复成果（PR137 / LOG177）：S17 F1/F2及C1已完成限定本地修复，候选S17-20261007-r2为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。47专项、源码/隔离wheel各659项通过，原七例及213冻结文件保持；拒绝后30次LNS的1h续接双审计通过但保持WINDOW_CENSORED，非新全链/Kit。原r1发布及全部历史证据不变，成果验收与确切发布另审，后续未启动。入口：[S17 r2审阅](docs/validation/S17_limited_repair_r2.md)。

2026-10-07现行有限修复授权（PR137 / LOG176）：负责人已批准S17发布后F1/F2及C1必要契约处理、回归、说明、治理和新确切审阅包的有限本地修复。沿用现有main/目录，不建分支/worktree，保留r1发布及全部历史证据和冻结边界；当前LIMITED_REPAIR_IN_PROGRESS。新成果验收与确切发布另审，后续未启动。入口：[S17步骤卡](docs/steps/S17.md)。

2026-10-07现行发布后审阅（PR135—PR136 / LOG174—LOG175）：S17 r1已实际限定验收、批准并发布，提交 `c72912b653bda6801da5c4dd2fce01cffb3f3ba3`、标签 `step-S17-r1`，双平台各源码/隔离wheel641项成功。全审复现F1静态承诺初解、F2生产已观察拒绝过滤两项P2缺口，另有C1通用分数维度契约建议；当前POST_RELEASE_REVIEW_FINDINGS_OPEN。本轮仅审阅/必要治理，未实施修复或新发布，后续未启动。入口：[S17发布后审阅](docs/validation/S17_post_release_audit_r1.md)。

2026-10-07本地成果（PR134 / LOG173）：S17固定合法模式LNS及两个有限适配器已完成本地实现/验证，候选S17-20261007-r1为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。29专项、源码/隔离wheel各641项通过；六个同固定模式静态例无进一步收益，两条生产全链为前12窗口LNS后原EDD续接、独立执行/决策审计通过。213冻结文件保持，S16 r2实际发布补录PR133/LOG171。成果验收与确切发布另审，S18—S28及S19A/S19B未启动。入口：[S17审阅](docs/validation/S17_lns_r1.md)。

2026-10-07现行交接（PR133—PR134 / LOG171—LOG172）：S16 r2已实际限定验收、批准并发布，提交 `a3088770c2aec19143f0693d60be3a2013ce69cc`、标签 `step-S16-r2`，双平台各源码/隔离wheel612项成功。负责人已授权在现有main/目录直接实施S17固定合法模式LNS；当前IMPLEMENTATION_IN_PROGRESS，新成果验收与确切发布另审。不建分支/worktree，S18—S28及S19A/S19B未启动，原冻结域及所有历史限制/失败保持。入口：[S17步骤卡](docs/steps/S17.md)。

2026-10-07有限修复成果（PR132 / LOG170）：S16 F1—F3及C1已完成限定本地修复，候选S16-20261007-r2为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。源码及隔离wheel各612项、专项37项通过；原七例数值/结果及68组完整集合保持，213个冻结文件摘要不变。1.1参照只绑定独立抽象资源图，原r1发布与所有限制/失败证据保持。新成果验收及确切发布另审，后续步骤未启动。入口：[S16 r2审阅](docs/validation/S16_limited_repair_r2.md)。

2026-10-07现行有限修复授权（PR132 / LOG169）：负责人已批准S16发布后F1—F3及C1必要追溯、回归、治理和新确切审阅包的有限本地修复。沿用现有main/目录，不建分支/worktree，保留原r1发布及全部历史证据和冻结边界。当前LIMITED_REPAIR_IN_PROGRESS；新成果验收与确切发布另审，后续步骤未启动。入口：[S16步骤卡](docs/steps/S16.md)。

2026-10-07现行发布后审阅（PR130—PR131 / LOG167—LOG168）：S16 r1已实际限定验收、批准并发布，提交 `f8ea47cbac96e9663f35dae5a6434693d34f648c`、标签 `step-S16-r1`，双平台各源码/隔离wheel597项成功。全量审阅确认F1时间网格类型/反映射、F2资格标量解码、F3接收EDD及策略区分三组问题，并有布局版本追溯说明待澄清；当前POST_RELEASE_REVIEW_FINDINGS_OPEN。本轮仅审阅及必要治理，未实施修复或新Git/远端发布，后续步骤未启动；原冻结域、限制与历史证据保持。入口：[S16发布后审阅](docs/validation/S16_post_release_audit_r1.md)。

以下早期状态保留各自封存时点，现行发布及审阅结论以上文为准。

2026-10-07本地成果（LOG166）：S16静态匹配参照已完成限定实现与验证，候选S16-20261007-r1为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。源码及隔离wheel各597项、专项22项通过，四个极小完整可行集合吻合，B=2三件接收背压核验通过；S15 r4已发布事实与全部限制保持。验收/确切发布另审，后续步骤未启动。入口：[S16审阅](docs/validation/S16_reference_r1.md)。

2026-10-07现行补录（PR128 / LOG164）：S15 r4已实际限定验收、批准并发布，提交 `0bba728116797ecece3f6fcbee7109c8bf1624b1`、标签 `step-S15-r4`，双平台CI成功。原批准前候选状态保留历史时点；远端详细日志HTTP403，未提取远端测试条数。先前五文件治理已随r4发布，S19A/S19B仍仅规划认可、实施NOT_STARTED。

2026-10-07现行授权（PR129 / LOG165）：负责人明确创建本对话直接实施S16，沿用现有目录/main，不建分支或worktree。S16正在本地实现、验证及形成确切审阅包，验收和新快照发布另审，S17—S28及S19A/S19B未启动，原冻结规则与全部限制保持。入口：[S16步骤卡](docs/steps/S16.md)。

2026-10-06有限修复成果（PR127 / LOG163）：S15发布后F1—F4已完成限定修复；源码及隔离wheel各575项通过，原16场景及1条补充正常链均以统一捕获源码完成轻量/真实Kit比较、独立执行及决策因果审计，Kit正常退出。候选S15-20261006-r4为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；原r3发布与所有限制保持，未启动后续步骤。当前入口：docs/validation/S15_limited_repair_r4.md。

2026-10-06有限修复授权（PR127 / LOG162）：负责人已批准S15发布后审阅F1—F4及必要回归、说明、治理和新确切审阅包的有限本地修复。沿用当前main/目录，不建分支或worktree；修复成果验收及新快照发布另审，S16—S28及S19A/S19B未启动。r3既有发布事实和全部历史证据保持。

2026-10-05现行发布与CI预算修订（PR121 / LOG156）：负责人已批准S15 r2并推送提交`9d82b292a0a1c585b71bc7676b08f2bd417c9387`及`step-S15-r2`。Ubuntu两轮各564项通过；Windows两次第一轮564项通过、第二轮均因15分钟作业上限截断，r2为PUSHED_CI_TIMEOUT。仅将Windows CI上限改为25分钟、Ubuntu保持15分钟的r3本地候选已形成；源码/配方/测试与r2相同，尚未运行r3远端CI或获发布批准。见docs/validation/S15_ci_budget_r3.md；原限制及S16—S28边界保持。

2026-10-05现行发布与修复（PR120 / LOG155）：负责人已批准S15 r1限定成果及确切快照；提交`8d0b283deccba1631bc2c1d8f35e5abc8e9788a9`和`step-S15-r1`已推送，但两平台CI因配方CRLF/LF摘要不一致失败，状态PUSHED_CI_FAILED。仅换行兼容的本地r2修复已通过LF源码/隔离wheel各564项，候选S15-20261005-r2为VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。见docs/validation/S15_ci_repair_r2.md；原配方数值、证据和限制保持，新快照发布及S16—S28另审。

2026-10-05现行本地成果（LOG154）：S15限定矩阵16条严格同源码轻量/真实Kit比较与独立审计通过，Kit均正常退出；WV01实际满缓冲区第三件READY背压及三件接收通过，源码与隔离wheel各562项通过。候选S15-20261005-r1，VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。各例分批捕获源码及全部失败/原720 h截尾保持，详见docs/validation/S15_final_review_r1.md。验收、确切发布及S16—S28另审。

2026-10-05现行补充（PR119 / LOG143）：负责人已批准WV01（S15-WV-APPROVAL-001），仅新增B2_SUPPLEMENTAL_960三产品同时释放、960 h上限/840 h接收许可用例；其余RP/SC/SH参数和原720/240 h结果保持。须实际见证B=2占满时第三件在OUT1已READY受容量阻断及后续全部接收。S15仍IMPLEMENTATION_IN_PROGRESS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；验收、确切发布及S16—S28另审。

2026-10-05现行实施续接（LOG140—LOG141）：正常单产品真实Kit全链及有限故障/缺料用例严格同源码比较通过；三产品在720 h截尾且发现待命疲劳越限，保留INVALID。显式REST修复41项专项通过，完整重跑和其他矩阵继续。S15仍 **IMPLEMENTATION_IN_PROGRESS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**，不把局部通过或截尾当作S15完成；RP/SC/SH授权保持。见 docs/steps/S15.md。

2026-10-05实施续接（LOG137）：单产品真实Kit完成442/442及一次READY/接收，独立审计与正常退出通过；严格同源比較、多产品/B+1及干预矩阵仍在推进。返修、库存/在制取消目前仅有各自轻量有限证据。S15整体仍IMPLEMENTATION_IN_PROGRESS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED；继续PR117—PR118授权工作，不能将本检查点作为完成。详见docs/validation/S15_chain_checkpoint_r1.md。

2026-10-05现行补充（PR118 / LOG135）：负责人已批准 SH01（S15-SH-APPROVAL-001），仅 LINING 支承人工交接高度上限为2.45 m，其余RP/SC边界保持。继续S15本地实现与验证，成果验收、确切发布另审；完整链尚未通过。

2026-10-05现行交接授权（PR117 / LOG134）：负责人要求创建“S15-2”新对话，沿用当前目录/main，不创建分支或worktree，在新对话直接继续完成S15剩余本地实现、验证、必要治理和确切审阅包。RP01—RP08及SC01—SC04授权继续有效，不重复等待批准，不把机制检查点当作S15完成。验收、确切发布仍另审，S16—S28未启动。

2026-10-05现行实施检查点（LOG133）：支承机制 r2 的真实Kit 12组、同源码双端比较及实际障碍续接通过，正常退出；源码与隔离wheel各545项通过，包来源审计通过。本步27项含24条带载/60条空返有限通行检查。完整USD链仍167/436停滞、无READY/接收，S15保持 **IMPLEMENTATION_IN_PROGRESS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**；详见 docs/validation/S15_support_reconfiguration_r2.md。既有RP/SC授权继续有效。

2026-10-05现行实施检查点（LOG132）：SC01—SC04已实现并取得有限机制验证：真实Kit正常矩阵12组、105次重配及25次复用；同源码双端逐事件比较与独立审计通过，实际障碍续接见证通过，成功运行进程正常退出。最新源码543项、专项25项通过。完整S15仍 **IMPLEMENTATION_IN_PROGRESS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**，全链/干预/隔离wheel及确切成果包继续推进。原RP/SC批准有效，不重复等待裁定；详见支承有限验证记录。

2026-10-04现行补充（PR116 / LOG130）：负责人已批准 S15-SUPPORT-20261004-r1 的 SC01—SC04，决策 S15-SC-APPROVAL-001，要求实施并验证支承重配。按提案限定附件范围、P1/E1人员和新增工时推进；RP01—RP08批准继续有效，不再等待本项裁定。S15仍IMPLEMENTATION_IN_PROGRESS；成果验收、Git发布及S16启动未获授权。原提案及旧待审文字保留历史时点。

2026-10-04现行决定（PR115 / LOG127）：负责人已批准S15-RECIPE-20261004-r1的RP01—RP08及配套JSON确切数值，决策S15-RP-APPROVAL-001。允许按表限定扩展D01/D03并继续S15本地实现与验证，不再等待配方批准。D02/G2、D05/D06、HR禁用及其余冻结边界保持；成果验收与确切发布另审，S16—S28未启动。以下旧待决定文字保留历史时点。

当前入口：[S15步骤卡](docs/steps/S15.md)、[A/E研究配方待裁定稿](docs/model/S15_recipe_proposal_r1.md)。

2026-10-04现行状态（PR112—PR114 / LOG124—LOG126）：S14 r2已实际APPROVED / PUBLISHED，提交`a5105410b248fa95655c521a4bb07ab3142e93a1`、标签`step-S14-r2`，两平台CI成功；人工GUI体验验收未单独记录。S15本地实施已获授权；负责人现要求先提交具体A/E研究配方裁定。S15当前SPECIFICATION_DECISION_PENDING，配方未获批准，完整PRODUCTION保持阻断；成果验收、确切发布另审，S16—S28未启动。旧状态保留历史时点。

2026-10-04现行本地成果（PR111 / LOG123）：S14五项审阅问题已完成有限修复，候选 `S14-20261004-r2`，**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。源码及隔离wheel各518项通过，真实Kit 22组见证与独立事件审计通过并正常退出。材料实物互斥、WORLD去重、逐输入实际证据、修复后自动恢复已验证；完整PRODUCTION映射仍未实现并明确拒绝，不能用37活动参照图冒充生产实现。原r1已发布，旧证据/冻结域保持；S15未启动，本轮无Git写入。

2026-10-04现行授权（PR109—PR111 / LOG120—LOG122）：S14 r1已按确切批准发布，提交`d91d13e5aaf964b79aeb36fd0b035cfd566ce36f`、标签`step-S14-r1`，两平台CI成功。发布后审阅确认五项逻辑问题；负责人已批准这些问题及必要回归、说明、治理和新审阅包的有限本地修复。沿用main/现有目录，不建分支或worktree；r2另行验收和批准发布，不启动S15—S28。以下旧状态保留各自历史时点。

2026-10-04现行本地成果（PR108 / LOG119）：S14候选 `S14-20261004-r1` 已完成本步共用契约、运动学命令适配与有限合成见证，**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。源码及隔离wheel各509项通过，真实Kit 12组见证经独立事件审计通过并正常退出。生产资格/质量UNKNOWN、HR禁用、完整BOM与S15无重置全链未证明；外接收为独立合成端口。未启动S15—S28，未执行Git写入或远端发布。以下旧文字保留历史时点；当前入口见S14步骤卡。

2026-10-04现行决定（PR108 / LOG118）：负责人已批准S14-CONTRACT-20261004-r1的ML01—ML12限定修订，决策S14-ML-APPROVAL-001。允许按表修改D01/D03/D04所列项并继续S14共用契约、验证及适配；通过前置出口后进入适配主体，不再等待本表批准。D02/G2与HR禁用、D05顺序、D06元数据及其余冻结边界保持。S15—S28及新快照Git/远端写入仍未授权。以下待决定文字保留其历史时点。

2026-10-04现行状态（PR106—PR107 / LOG116—LOG117）：S13 r4已实际APPROVED / PUBLISHED，提交`c538a9a3b11ee345200f34c61fd92084ca7bb0e5`、标签`step-S13-r4`；负责人GUI体验验收未单独记录。S14已获明确本地启动授权，沿用当前main，不建分支/worktree。先完成前置契约具体修订表，ML01—ML12待对应冻结项决定，不能推定D01—D06全面解冻；通过共用契约出口后再实施适配主体。S15—S28及新快照Git/远端写入未授权。下方旧未发布/未启动文字保留历史时点。 [S14当前步骤](docs/steps/S14.md)。

2026-10-03现行本地成果（PR105 / LOG115）：S13四项审阅问题已完成有限修复，候选 `S13-20261003-r4` / `S13-TARGET-R5-2`，**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。静止吊机避障、操作全区间占用、载具/载荷同步与独立支承读回、旧入口命令已复核；463项源码及隔离wheel各通过，真实Isaac/目标与旧版GUI及L1/L2负载验证完成。原r3已按PR103发布，旧证据和冻结域保持；本版尚未提交上传，S14未启动。下方状态为历史时点；本版入口见S13步骤卡和验证报告顶部。


2026-10-03现行本地成果（LOG111，PR102授权）：S13第五版整改已形成候选 `S13-20261003-r3`，**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。目标主场景采用固定生产设备、两独立焊接站、人工叉运/推车与主CR1，具名人员任务关联、入料代表链、B=2成品槽和B+1实际搬出见证已验证；冻结旧配置及旧证据保持。工作区/隔离wheel各456项，最终目标24项专项、53行运输矩阵及真实Isaac/GUI/旧协议回归通过；三档30秒暖机、至少120秒测量、各10次重建完成。可靠真实帧时间仍不可得，工业能力及人工体验验收未获证明。未创建分支/worktree，未下载第三方资产、升级环境或执行Git写入，未启动S14—S28。下列旧状态保留其历史时点。

2026-10-03现行批准与交接授权（PR102 / LOG110）：负责人已同意S13-PLAN-20261003-r5及FACTORY-OPERATIONS-20261003-r2提案，要求创建“S13-4”新对话，沿用当前目录/main、不创建分支或worktree，并直接开始S13步骤整改。方案查阅与实施放行条件已满足，不再等待r5方案批准；下列待审/仅文档文字保留原时点。授权包含本步整改、必要验证、品质完善、治理及确切审阅包。未来总纲补丁的规划认可不等于启动S14—S28或解冻D01—D06。第三方资产下载、环境升级与Git暂存/提交/标签/推送/PR/附件仍未授权；整改成果验收与确切快照发布另审。

2026-10-03现行决定（PR100—PR101 / LOG108—LOG109）：负责人要求基于设备、人员、入料物流、成品缓冲及龙门吊覆盖问题，编写S13第五版整改规划和后续总纲补丁，交付治理文件检阅；本轮仅文档。S13-PLAN-20261003-r5尚待明确放行，不能沿用PR099的r4批准启动新增整改。r2原有验证证据及封包保持，人工验收、确切发布批准均未发生。不修改场景源码或冻结契约，不启动S14—S28，不创建新对话/分支/worktree，不执行Git或远端写入。下列旧授权与状态保留其历史时点，以本条为当前边界。

当前待审入口：`docs/sim/S13_revision_proposal_r5.md`；后续承接：`docs/PROJECT_CHARTER.md#factory-operations-patch`。

2026-10-03现行本地成果（LOG107）：PR099批准的S13 r4范围已形成本地r2候选`S13-20261003-r2`，验证与限制见`docs/validation/building_scene.md`，入口见`docs/sim/S13_trial_guide.md`。工作VERIFIED_WITH_LIMITS；人工验收、确切发布批准及远端发布均未发生。原r3/r4计划和历史封包保留；后续操作继续遵循下述边界，不能因完成本地验证而执行Git写入或启动S14。

2026-10-03现行批准与交接授权（PR099 / LOG105）：负责人已批准S13-PLAN-20261003-r4现行规划及总纲未来步骤补丁，明确要求创建“S13-3”新对话，沿用当前目录/main、不创建新分支或worktree，直接完成S13步骤内剩余增改、完善、验证、必要治理及确切审阅包。方案查阅与实施启动条件已满足，不再等待方案批准；下列待审/仅文档文字保留历史时点。未来步骤补丁获规划认可不等于启动S14—S28或解冻D01—D06。第三方资产下载、环境升级以及Git暂存/提交/标签/推送/PR/附件仍未授权；修订成果验收和确切快照发布另审。

2026-10-03当前决定（PR098 / LOG104）：负责人仅授权编写S13修改方案及后续步骤总纲补丁，交接与最后一次S13集中修改待稍后明确批准，修改成果验收及确切快照上传另行批准。不得将未来批准意向写为已获授权。本轮不修改场景源码或冻结契约，不创建新对话、分支或worktree，不执行Git/远端写入。PR095的原r3实施已形成本地r1候选，新增r4修改范围待审；下列旧状态保留历史时点。

当前方案入口：`docs/sim/S13_revision_proposal_r4.md`；未来承接见`docs/PROJECT_CHARTER.md`中的流程与布局补丁。

2026-10-03现行授权（PR095 / LOG099）：负责人已批准S13-PLAN-20261003-r3，要求创建“S13-2”新对话，沿用现有目录/main，不建分支或worktree，直接完成S13剩余本地实现、验证、品质打磨、必要治理及确切审阅包。方案查阅条件已满足，不再等待方案批准；以下待审/仅调研文字保留历史时点。S14—S28、第三方资产下载、环境升级与新Git/远端发布不在本次授权内。

## 范围与事实

2026-10-03现行补充（PR091—PR092）：S12 r2已实际验收、批准并发布，回执补录LOG094。负责人授权S13新对话沿用现有目录/main、不建分支/worktree，仅开展只读前期核查、官方来源/许可调研和必要本地方案治理。须先提交可审阅场地/模型资产方案并等待明确批准，才正式搭建；当前不得编写场景实现、下载/导入资产、安装升级或启动正式仿真。S14—S28及任何新Git/远端发布未授权；旧时点边界由本条覆盖，原记录保留。

PR093要求更新S13第二版计划书，补齐龙门吊、按实际负载判断并优化性能，各方面品质以优异化为导向。负责人查阅确认第二版后再开始S13；当前仍仅修订方案，不将“基本同意”或交付文件视为已完成该查阅条件。既有资产/环境/发布边界保持。

PR094要求纠正机器人与普通生产机器的概念混淆，覆盖六项设备、工装/工具、控制、人员责任和调度模式，提交第三版计划书。当前以r3为待审版本，查阅确认后再实施；r2意见不视为r3已确认。仅修改方案及必要治理，不修改领域契约或启动实现；优异品质与实测性能优化要求保持。

执行前读取 README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md 和当前步骤卡（S13前期方案为 docs/steps/S13.md，S12回执见 docs/steps/S12.md）；若本地有内部总纲，也应读取，但不得将其内容或位置复制到公开产物。负责人当前明确决定优先于既有文档建议。

现行研究对象为完整三维建筑模块的工厂生产，贯通结构、MEP/内装、质量放行与出厂就绪；管道仅为历史实现或有依据的子组件。研究范围为完整多资源自适应调度框架、A 状态依赖协作模式与排程联合决策、D 人因权衡；B 仅作稳健性检查，C 仅作恢复评价。Python 领域模型与轻量事件仿真、Isaac Sim 闭环、滚动状态感知 LNS 和严格匹配简化模型的 CP-SAT 参照是已确认路线。未实现和未验证事项保持计划语态。

只开展已授权步骤。PR069已验收C03 r2并限定冻结D01—D06；保留证据缺口与HR禁用。PR071授权的C04/C05及PR074有限修复已完成；PR075明确J2同产品双框可驻留、FIX-J2工装独占。C04/C05 r2已验收、批准并发布，PR076/LOG073补录实际回执。PR077明确在现有目录/main直接且仅开展S10本地实现、验证、必要治理与确切审阅包，不建分支/worktree。PR078已发布S10 r1；PR079全审及PR080有限修复后，S10 r2已验收、批准并发布，PR081/LOG080补录回执。PR082授权沿用现有main直接且仅实施S11、验证、必要治理与确切审阅包，不建分支/worktree。PR083已验收并发布S11 r1；PR084全审后，PR085仅授权三组问题及必要回归、说明、治理和新审阅包的有限本地修复；r2另行审阅。旧未授权/待审文字保留历史时点，现行决定覆盖旧边界。PR086补录S11 r2已验收、批准并发布；PR087授权现有main直接且仅开展S12本地实现、验证、必要治理及确切审阅包，不建分支/worktree。PR088补录S12 r1实际验收和发布；PR089完成性审阅后，PR090仅授权三类独立决策审计问题的有限本地修复及必要回归、说明、治理与新审阅包；r2另行审阅。S13—S28及S12新快照暂存/提交/标签/推送/PR/附件/远端名称/About修改未获授权；旧域验收不扩展为建筑域验收。

## 本地操作

Windows 开发命令使用 PowerShell 7。调用工具时显式选择已核验的 PowerShell 7 可执行文件；不使用 Windows PowerShell 5.1，不静默回退。机器上的具体安装路径只保留在本地配置。WSL 内 Linux 命令可使用 Bash。

本次纠偏沿用现有工作目录与 main，不创建额外工作分支或 worktree，不重置已有改动。历史S00首次初始化与新增工作分支不同；后续分支策略依届时授权处理。

文本使用 UTF-8 无 BOM；仓库文本换行由 .gitattributes 管理。仅对当前步骤做必要检查；保留实际失败和限制，不用自我断言替代证据。

## 逐步审阅与发布

每步本地完成并检查后，展示确切文件集合、完整差异、检查证据、限制、目标仓库、分支、标签和拟执行远端操作。负责人针对该快照明确批准后，才创建远端、推送、建 PR 或上传附件。文档认可、路线确认和启动步骤均不是首发批准。

本地保留 packet_id、逐文件内容摘要、实际批准和回执；精确暂存清单内文件，复核完整拟推送历史和提交署名。不得使用无选择的整目录上传。忽略规则不阻止强制加入，也不会清除已经跟踪或进入历史的内容。

批准后内容或目标发生实质变化，重新审阅；相同快照遇到网络失败，核对远端后可按原授权重试。不得强推覆盖历史；步骤标签不可移动，修订递增编号。

工作 VERIFIED、人工 ACCEPTED、上传 APPROVED、远端 PUBLISHED 分开记录。远端分支、提交、标签与必要检查均核验后才记录 PUBLISHED。S00 无 CI；CI 在 S02 建立，不能预写 CI 通过。

当前提交不能写入自身最终哈希。实际回执先本地留存并在对话交付，下次获批的公开日志补录；不为回填记录擅自追加上传。

## 公开边界与贡献

公开文件、差异、提交元数据及发布附件均须审查。不得含内部总纲、原始会话或提示词、参考材料原件、课程标识、个人路径、机器配置、凭据及完整原始日志。账号与提交身份只按明确批准的仓库配置和 Git 元数据使用；公开治理正文使用角色名及相对路径。

维护 PROGRESS_LOG.md 和当前步骤卡；出现实质性指令才追加 PROMPT_LEDGER.md。提示词记录是规范化语义摘要，不能冒称逐字原文。按实际记录负责人决策和 AI 辅助，不虚构人工编码、验收或实验贡献。

LICENSE 仅在具体许可选择获确认后添加；未确定时不得自动套用许可证。第三方资产的获取与再分发条件应独立核查。
