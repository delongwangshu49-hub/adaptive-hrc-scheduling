# S19B-5：语义/性能对照与收尾交接

2026-10-14；PR183 / LOG251。当前 **SEMANTIC_PERFORMANCE_AND_CLOSEOUT_AUTHORIZED**，正式性能尚OPEN。

负责人要求整理现有内容，创建S19B-5、不创建新分支，直接在新对话完成第五步：验证前端开关及规定负载，形成成果包，再验收和批准发布，且不要遗漏先前修复。接手后直接完成本阶段实施、测量、修订及收尾，不重复等待启动授权，不仅回复“准备就绪”。**先形成确切可审阅成果包，再由负责人验收和批准具体发布方案**；本条不是对尚未形成的成果或Git操作的预先批准。创建/接收回执仅在实际发生后另存 `.local/s19b-5-handoff-20261014/`。

## 目录、状态与不可遗漏的保持范围

沿用 `D:\7023p`、现有main、全部未提交成果，HEAD `aab9ca848eec6816717f2929a8217f642c3bc2bd`。不创建分支、worktree或子代理，不暂存、提交、打标签、推送；确切发布批准前无Git写入。Windows命令显式 `C:\Program Files\PowerShell\7\pwsh.exe`，Git只读 `GIT_OPTIONAL_LOCKS=0`。

保持全黑黑白灰方角桌面、简中/English、中央真实Kit原生子窗口自动铺满及DPI/缩放/恢复。保持冻结生产输入/流程/工时/路线/落点/手位/支承运动/碰撞/观察隔离、既有预算、2.4m与0.02h/对。固定承载架、收存托片、可重配横杆为 **OWNER_DECISION_RETAIN_FOR_DEMONSTRATION / TECHNICAL_OPEN_NOT_FIXED / NON_BLOCKING_FOR_DEMO**；原510对象和可见性保留，不隐藏、不修改、不宣称全部支承修复。工业G2继续OPEN/NOT_ESTABLISHED，不开展工业落实，不启动S20—S28。旧“未启动/另审”条目按原时点保留，本次第五步授权覆盖其启动限制。

先读[步骤卡](S19B.md)、[B3审阅](../validation/S19B_B3_r1.md)、[B3机器摘要](../validation/S19B_B3_r1.json)、[529项证据绑定](../validation/S19B_B3_evidence_r1.json)、[B3协议](../sim/S19B_B3_protocol_r1.md)、[B2最终r2](../validation/S19B_B2_r2.md)、[B2控制契约](../sim/S19B_B2_control_contract_r1.md)、[桌面入口](../../desktop/s19b/README.md)。

## 修复与成果接续清单

| 范围 | 必须保留的修复/成果 | 核对入口 |
| --- | --- | --- |
| 步骤1/B1 | 三入口、真实Kit嵌入、同窗缩放/最小化恢复/专用相机；全黑方角；双语身份/时间/模式/新鲜度/实际原因；只读实体定位和集中证据；坏、缺失、陈旧、错身份不伪报成功 | [嵌入r2](../validation/S19B_prototype_r2.md)、[B1](../validation/S19B_B1_r1.md)、[反馈r1](../validation/S19B_B1_feedback_r1.md) |
| 紧急兼容修订 | 已验证有限兼容项，保持原完整单件和生产运动；原方案增加2.8m/0.04h及净增1044几何没有实施，不能混入当前成果 | [有限修复r2](../sim/emergency_scene_limited_repair_r2.md)、[交接取舍](emergency_scene_to_S19B_2_handoff_r1.md)；`sim/isaac/scene/target_scene.py`、`production_port.py`、`scene_correction.py` |
| B2输入/启动 | 草稿与确认；前后端独立校验输入/摘要/根目录；唯一持久worker claim；确认幂等、同ID不同内容/epoch/序号/状态拒绝；启动未受理前的停止必须持久拒绝，失败启动记录FAILED | [最终r2](../validation/S19B_B2_r2.md)、控制契约；保留24契约和11后端负例 |
| B2停止/重连 | 有序停止停止新增派工并处理在途事实，保留未完成/承诺与双审计；同PID/创建时间/句柄的同运行重连、不重放命令或另启动worker；前端断管后持久日志继续；历史只读 | [B2最终r2](../validation/S19B_B2_r2.md)及机器摘要 |
| B3相机 | 初始化仍复制World相机至显示相机；运行中更新属性到既有 `/S19B/ReviewCamera`，避免替换live spec引发RTX白屏。保留World预设和几何/生产 | `scripts/run_s19b_prototype.py`；B3白屏失败与最终Overview/Fork图均保持 |
| B3初始文案 | 新提交即清理旧完成/退出显示，标记提交并渲染控制，避免新运行初始化显示上次成功 | `desktop/s19b/src/s19b_desktop/app.py` |
| B3验证程序收尾 | 显式停止timer、close、deleteLater、DeferredDelete/processEvents与app.quit；完整正常分支也经共同清理 | `scripts/verify_s19b_b2_ui.py`；最后共同函数重构在成功r2验证之后，接手须核验当前精确版本，不能假称当时验证程序字节完全相同 |
| B3有限成本回放 | Windows内存句柄类型修订、离线大journal显式UTF8读取、按实际reason_fact原文长度选择负载；实际CPU清除旧标签/有序停止 | `scripts/verify_s19b_b3_replay.py`；仅离线显示压力，不扩大在线消息上限 |
| S19/S19A累计基线 | 已发布S19计划来源/严格类型缓存/正负零精确摘要，在线缓存/预算回退/承诺及B+1等修复，S19A路线方向/受限动作/手位、材质/导出相对依赖等均保留，不回退到旧失败源码 | 现有main/未提交累计成果、[S19有限修复](../validation/S19_limited_repair_r2.md)、[S19A完成发布](../validation/S19A_completion_publication_r1.md) |

暂停/继续/重置、运行中订单新增/修改与通用取消仍禁用；本次测量不顺带开放能力。Kit helper是在完整 `app.close` 返回后显式exit，跳过RC解释器最终收尾；不写成通常解释器退出问题已修复。审计超5秒无heartbeat时显示未知并关闭控制/定位，不写成实时保证。原因翻译覆盖、物理输入法/多屏、负责人人工操作验收仍有限；AI试用不代填人工验收。

## B3实际结果与不能冒用的证据

B3 **B3_ACTUAL_TRIAL_VERIFIED_WITH_LIMITS / FORMAL_PERFORMANCE_OPEN / OWNER_REVIEW_PENDING / NOT_APPROVED / NOT_PUBLISHED**。最终简中实际桌面Kit身份 `S19B-c88841d9568e4124abf9a09020a9ae4f`，路径 `.local/s19b-runs/`，436有效工序、272.35047973655236h、接收1、双审计/完整Kit关闭/Qt观察实际exit0，121捕获源码/输入匹配最终字节。切English查看同一身份、输入和历史，31保存文件字节保持；定位USD/状态摘要保持。另有独立英语完整运行和初次中文完整运行，中间源码差异和白屏如实保存。

新完整CPU `.local/s19b-b3-full-normal-cpu-r1/runs/S19B-645e48aae36b4c15a3d41acf6c4cea60` 与最终Kit同121源码。4402事件/2072决策严格比较和双方独立执行/决策重建PASS，时间等max差0、几何6.847300504375653e-14m，回执 `.local/s19b-b3-dev-20261014/final-same-source-parity.json` 与 `final-same-source-parity-exit.json`。

24桌面契约、8组Qt/CPU/中央Kit及验证程序实际exit0，源码/隔离wheel各862项；父进程实际退出文件见B3证据索引，不只看内部PASS。六个最终后端运行各121一致不代表当前验证脚本最后重构也已实际复跑。

`.local/s19b-b3-replay-r4/` 的40组长原因组合、zh/en/en/zh共800次Qt offscreen样本（250ms节奏）满足预声明控件50/250ms限值，P95最高9.74ms、max15.28ms、peak224804864B；不是实际GPU/在线前端开关成本，组合不是连续真实生产状态。历史10份规定负载报告各PASS但各9源码差异，见 `.local/s19b-b3-dev-20261014/historical-load-evidence.json`，不能替代最终前端负载验证。

保留全部原失败：旧B2基线对中间英语/最终中文严格比较因源码哈希失败；初次Qt内部8PASS但进程收尾-1073741819；初次全检uv缓存访问失败；回放r1/r2失败及r3错误排序；白屏图；系统错误窗口Computer Use读取审批超时、未读取/关闭记录。这些在B3审阅及529证据清单中可查，不删、不改失败为通过。最终检查本地UV_CACHE_DIR `D:\7023p\.local\s19b-uv-cache`。

## 第五步必须实际完成的对照和收尾

正式依据为[原选型对照条款](../sim/S19B_frontend_options_r1.md)“正式B3对照前”及现步骤卡，旧选型状态是历史。新对话先核对当前文件与真实进程、封存接收快照，再实施必要有界测量适配，直接执行：

1. **事前协议**：最终源码/场景/输入/案例/种子、原5s周期与50ms搜索预算、相机/渲染模式、刷新/分页/曲线/记录负载、测量时钟与进程树、预热/采样长度/重复数、ABBA配对顺序、失败/缺样处理和开销判据写成可审查协议，在测量前落盘。前端阈值不能事后按结果挑选，不借S19A1.50/1.65作为既定阈值。合理测量选择可自行落实，不重复请求阶段启动许可。
2. **前端开关**：先比较同一显示后端/同一场景渲染的前端开与关；另列原无头生产与新增显示运行方式的成本，分别归因，不能把渲染代价藏进UI开关。保留中央真实Kit和当前控制语义。固定决策回放可隔离显示成本，但还必须测真实在线预算生产，回放不能充作在线证明。
3. **规定负载矩阵**：已有两订单/延迟供应/物流冲突；B+1缓冲/接收；有限故障/反馈；零预算与过载预算负例，均用最终源码实际前端开关配对。参考原 `.local/s19-2-work-20261009/final4-{multiple_orders_delayed_supply,b_plus_one,loaded_path_obstruction,zero_budget,overloaded_budget}-{light,isaac}/report.json`，逐一核对配置/故障/预算定义，不只照名字新造近似场景。需要测量适配时保持生产/模型与默认界面能力边界。
4. **语义与时延**：命令/受理回执/事件、状态/观察、资源/人因约束、承诺、严格比较和独立执行/因果审计，完整结果及退出回执均留存。墙钟搜索可能改变候选；严格差异保留并定位，不能删除WAIT、降低数值精度、松比较器或换预算抹差异。分别报告调度周期/搜索、反馈时延、状态年龄、UI/Kit更新、CPU/内存/进程树、最大值/超限/停止响应/失败。原协作搜索与超限限制保持，不声称硬实时或方法优势。
5. **修订和最终源码闭环**：有界必要前端/测量修订可直接完成；不改冻结生产/模型或隐藏三类支承。针对变更执行必要回归、源码/隔离wheel及真实Kit验证，并核对最终采样捕获源码/输入与最终工作字节。程序真实exit和内部结果分别绑定，任何收尾变更不能借旧run冒充最终验证。
6. **累计成果包**：合并步骤1/B1/B2/紧急兼容/B3/本次第五步修复与限制，避免只封装最后新增文件。另建新包目录/新身份、逐文件manifest/SHA256、最终源码与证据清单、规定负载矩阵/预声明判据与实测/失败差异/语义及性能结论、可复现入口、剩余开放项和实际人工验收缺口。不重写任何旧包。先形成可审阅确切包，再向负责人提交整步验收与具体main提交/标签/推送方案；收到批准后才执行获批范围，实际发布与CI另核验，不预写成功。

## 封包与交接保全

| 封包/清单 | SHA256 |
| --- | --- |
| `.local/s19b-b3-review-20261014-r1/S19B-20261014-B3-r1-review.zip`，累计108文件 | `0d099100c7a0a56989654463fc42370384e2340a7b16274c35f2d5a6ed19b2a2` |
| 同目录 `review-manifest.json` | `7a4a94bb1b6fe8f44535a751bf08818abc4b3edbf3b9f8eb9ea97c228311571c` |
| `.local/s19b-b2-review-20261014-r2/S19B-20261014-B2-r2-review.zip`，最终94文件 | `c6fd81162e48e21bd54fe4605ec7b1e33641b5f95bf6b0d482c2ba920a74b1b7` |
| B2-r2 `review-manifest.json` | `31e4996e7c45b93d916134c51f2aae62ea2e2cb5e83b79de508ac792279125be` |
| `.local/s19b-b2-review-20261014/S19B-20261014-B2-r1-review.zip`，中间89文件 | `aaae2b9fb618bb188d5819b22042197132ff08fa2050736843603aae83a08779` |

六更早模型/原型/B1/全黑包摘要完整列于B3机器摘要preservation及本次 `.local/s19b-5-handoff-20261014/before-governance-preservation.json`。本次交接前108工作成员、529证据及上述旧包均实核一致。本次仅追加AGENTS、步骤卡、日志、台账四个治理成员，另建本交接文件；旧包/manifest不可变，104其他成员保持，四项差异按 `.local/s19b-5-handoff-20261014/preservation-check.json` 核对，不能声称追加后108工作成员仍全与旧包一致。此检查是交接时点快照，后续授权实现变更另记，不覆盖快照。

根CPU `.venv`、隔离Qt `desktop/s19b/.venv`、Isaac `D:/Dev/tools/isaac-sim-6.1`；入口 `scripts/start_s19b.ps1`，必要本地启动器 `.local/s19b-b2-dev-20261014/B2ReviewLauncher.exe`。接手重新观察当前交互桌面/进程，不沿用旧句柄，旧后端实际退出后新身份启动。不可见会话不作为用户桌面操作证据；不向根环境或Kit安装Qt。实际新对话创建后原对话仅写本地创建/接收回执，治理与测量全部由S19B-5继续，避免并发改写。
