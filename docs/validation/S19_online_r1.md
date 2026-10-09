# S19 在线预算、合法回退与计划稳定性：本地成果审阅

2026-10-09T03:27:51+08:00；PR155 / LOG206。候选 **S19-20261008-online-r1** 的本地状态为：**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。沿用现有 main，未创建分支/worktree、调用子代理或执行 Git 暂存、提交、标签、推送。继续获批 S18-SIM-A1 调度仿真研究，工业 G2 保持 OPEN / NOT_ESTABLISHED。

## 实现与适用边界

| 内容 | 当前行为 |
| --- | --- |
| 重排与停止 | 初始、周期、已交付扰动和恢复触发；构造前缀、滚动生成、修复、逐步回放和独立核验之间检查单调墙钟截止点；调用额度累计，不退还失败工作 |
| 最佳可行缓存 | 完整候选通过核验且未迟到才入缓存；修复异常保留此前已核验最佳候选；扰动清除旧后缀，当前缓存头部重新准入 |
| 派工保护 | 绑定配置/运行/epoch/观察完整摘要、修订号和仿真时刻；紧邻派工再次检查单命令和实际合法性；过期、暂停或无剩余预算返回 WAIT |
| 实际承诺 | 未来承诺窗口明确为 0 h；已接受工作从接受持续保护到实际释放。保留执行中动作、班组/模式承诺、所有权、材料预留、载荷、支承和驻留事实 |
| 回退与记录 | 使用当前合法规则动作或 WAIT。保留缓存命令原 PREPARE 原因；规则重试不冒充完整候选缓存命中；记录前后暂定计划、共同分母、变更及实际耗时 |

计时包含观察与输入构造、前缀检查、候选核验、回退、派工前再验证和回执。协作中止不能抢占单个 Python 调用，因而不是硬实时实现。`verification_seconds` 只表示候选核验；构造阶段的前缀检查仍计入搜索和周期总时间。未来非零承诺窗口不受支持，不能把暂定计划写成实体预留。

完整生产负载预声明决策预算 5 s、单次搜索 0.05 s、至多四次搜索，此后由实际事件驱动规则回退。这不是全生产周期持续联合搜索的证据。120 s / 110 s 是另列的长预算诊断，不替换 50 ms 的失败负载，也不构成 A/D 正式效果或工业能力结论。

## 实际验证

本机 Windows 源码 **806 项 / 641.405 s**、隔离 wheel **806 项 / 647.711 s**均通过，其中新增 32 项 S19 回归。锁文件、格式、静态检查、依赖与两类生成检查通过；344 份程序、测试和输入摘要在完整检查后保持。未运行新远端 CI。

| 实际运行 | 终点 h / 接收件数 | 完整链或窗口 | 保存记录独立审计 | 关闭返回 | 进程秒 |
| --- | --- | --- | --- | --- | --- |
| multiple_orders_delayed_supply-light | 553.929958333 / 2 | OPERATIONS_COMPLETE | PASS | True | 1852.596 |
| multiple_orders_delayed_supply-isaac | 553.929958333 / 2 | OPERATIONS_COMPLETE | PASS | False | 5736.015 |
| b_plus_one-light | 845.618333333 / 3 | OPERATIONS_COMPLETE | PASS | True | 4369.393 |
| b_plus_one-isaac | 845.618333333 / 3 | OPERATIONS_COMPLETE | PASS | False | 12022.661 |
| loaded_path_obstruction-light | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS | True | 41.588 |
| loaded_path_obstruction-isaac | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS | False | 155.081 |
| zero_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 3.692 |
| zero_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | False | 26.085 |
| overloaded_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 3.640 |
| overloaded_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | False | 25.894 |
| cache-port-light | 2.056870278 / 0 | DECLARED_CHECKPOINT | PASS | True | 19.670 |
| cache-port-isaac | 2.056870278 / 0 | DECLARED_CHECKPOINT | PASS | True | 129.972 |
| diagnostic-01 | 26.477448889 / 0 | WINDOW_CENSORED | PASS | 不适用（轻量续接） | 174.798 |
| final-pair-light | 24.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 38.424 |
| final-pair-isaac | 24.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 207.992 |
| graceful-loaded_path_obstruction-light | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS | True | 40.990 |
| graceful-loaded_path_obstruction-isaac | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS | True | 202.277 |
| graceful-zero_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 3.640 |
| graceful-zero_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 70.191 |
| graceful-overloaded_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 3.609 |
| graceful-overloaded_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS | True | 72.027 |

| 严格比较 | 实际状态 | 字段/记录不一致计数 | 双端执行 / 因果复审 |
| --- | --- | --- | --- |
| multiple_orders_delayed_supply | FAILED | 1 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| b_plus_one | FAILED | 46400185 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| loaded_path_obstruction | FAILED | 1 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| zero_budget | FAILED | 1 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| overloaded_budget | FAILED | 1 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| cache-port | PASS | 0 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| final-pair | PASS | 0 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| graceful-loaded_path_obstruction | PASS | 0 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| graceful-zero_budget | PASS | 0 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |
| graceful-overloaded_budget | PASS | 0 | ['PASS', 'PASS'] / ['PASS', 'PASS'] |

原两订单完整链严格比较唯一失败是关闭回执；事件和决策没有另报差异。B+1 的不一致计数包含首处分歧后序列错位导致的连带字段差异，不代表同等数量的独立问题。所有窗口终点是在阈值后的实际事件边界，不等同生产完成。

| 运行 | 周期数 | P50 / P95 / 最大 s | 周期超限数 | 最大反馈到决策 s |
| --- | --- | --- | --- | --- |
| multiple_orders_delayed_supply-light | 4092 | 0.314433 / 0.667138 / 1.497048 | 0 | 1.530297 |
| multiple_orders_delayed_supply-isaac | 4092 | 0.804474 / 1.485558 / 3.748309 | 0 | 9.603414 |
| b_plus_one-light | 6156 | 0.497682 / 0.964473 / 2.935449 | 0 | 2.988596 |
| b_plus_one-isaac | 6160 | 1.142101 / 1.891791 / 5.827052 | 3 | 14.250773 |
| loaded_path_obstruction-light | 235 | 0.099129 / 0.201950 / 1.522870 | 0 | 1.545695 |
| loaded_path_obstruction-isaac | 235 | 0.376752 / 0.515080 / 3.509430 | 0 | 7.589226 |
| zero_budget-light | 8 | 0.088309 / 0.098125 / 0.098125 | 8 | 0.103280 |
| zero_budget-isaac | 8 | 0.220105 / 0.258032 / 0.258032 | 8 | 0.706718 |
| overloaded_budget-light | 8 | 0.089955 / 0.097005 / 0.097005 | 8 | 0.101538 |
| overloaded_budget-isaac | 8 | 0.229848 / 0.252300 / 0.252300 | 8 | 0.655878 |
| cache-port-light | 59 | 0.073794 / 0.714301 / 5.797387 | 0 | 5.825164 |
| cache-port-isaac | 59 | 0.166148 / 1.473041 / 13.179261 | 0 | 17.264568 |
| diagnostic-01 | 54 | 0.159829 / 0.263705 / 39.876419 | 0 | 37.444610 |
| final-pair-light | 149 | 0.185420 / 0.222360 / 1.488509 | 0 | 1.493728 |
| final-pair-isaac | 149 | 0.474081 / 0.650417 / 3.695876 | 0 | 9.475842 |
| graceful-loaded_path_obstruction-light | 235 | 0.095107 / 0.200285 / 1.537797 | 0 | 1.561717 |
| graceful-loaded_path_obstruction-isaac | 235 | 0.383489 / 0.514763 / 3.500679 | 0 | 7.555914 |
| graceful-zero_budget-light | 8 | 0.088751 / 0.096738 / 0.096738 | 8 | 0.101843 |
| graceful-zero_budget-isaac | 8 | 0.221337 / 0.231307 / 0.231307 | 8 | 0.652702 |
| graceful-overloaded_budget-light | 8 | 0.086529 / 0.097274 / 0.097274 | 8 | 0.101538 |
| graceful-overloaded_budget-isaac | 8 | 0.222323 / 0.239142 / 0.239142 | 8 | 0.669358 |

两端 B+1 均实际见证：PRODUCT-1/2 占据 FG1/FG2，PRODUCT-3 于 746.5164726666667 h 在 OUT1 达到 READY，因容量等待至 840 h，三件于 845.6183333333332 h 均接收。两端各自执行/因果审计通过，但轨迹并不相同：Kit 为 13,141 条事件、6,160 个周期，轻量为 13,131 条事件、6,156 个周期。

首次决策差异发生在相同 OBS-92、92 条已观察事件和 0.02326388888888889 h：轻量端在 2.9354492 s 内实际派出 P1 WALK，Kit 端在 5.6660783 s 超限后 WAIT，随后两轮也超限 WAIT；三次均没有派工。Kit 最大周期 5.8270516 s，反馈到决策结束最大 14.2507735 s。三轮均为零候选试次、零候选核验调用，搜索阶段用时分别为 5.3965268/5.4036082/5.5426429 s；结合停止点位置，可判断预算消耗在进入候选试次前的准入/前缀构造阶段，但没有把其中单个函数另行计时。5 s 目标未全面达成，完整 B+1 严格轨迹一致性未成立。

B+1 Kit 还在 147.55846722222228 h 记录 `ACTUAL_EXECUTION:COLLISION:/World/Crane/Bogie0`，对应 PRODUCT-3.ST-C.04.DELIVER-1。异常期间实体、叉车、P1、GROUND-SPINE 和落点仍由原命令持有；147.6458005555556 h 重新准入，147.69502719166675 h 完成。该记录没有原命令的中途运动样本，不冒充带载中途证据；后者由专用障碍窗口提供。轻量端没有这项实际 USD 路径阻挡记录，不能仅将所有轨迹差异概括为三次预算 WAIT，也未独立证明该阻挡由早期 WAIT 导致。

| 长预算诊断 | 完整核验候选 | 缓存实际 STARTED | 独立重放 | 候选核验耗时 s |
| --- | --- | --- | --- | --- |
| cache-port-light | 2 | 4 | PASS | 5.101631 |
| cache-port-isaac | 2 | 4 | PASS | 11.555256 |
| diagnostic-01 | 2 | 13 | 未另列；驱动内核验及双审计 | 49.240444 |

缓存诊断的候选逐一从保存配置、观察、执行前缀和决策前缀重建后独立核验，并绑定候选摘要及实际缓存派工。准备前缀诊断从 24.477448888888887 h 续接至 26.477448888888887 h；不把前缀工作计为在线窗口新反馈。

| 运行 | 共同项累计 | 顺序逆序 / 模式 / 班组 / 提议开始变化 | 提议开始绝对时移 h |
| --- | --- | --- | --- |
| multiple_orders_delayed_supply-light | 0 | 0 / 0 / 0 / 0 | 0 |
| multiple_orders_delayed_supply-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| b_plus_one-light | 0 | 0 / 0 / 0 / 0 | 0 |
| b_plus_one-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| loaded_path_obstruction-light | 0 | 0 / 0 / 0 / 0 | 0 |
| loaded_path_obstruction-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| zero_budget-light | 0 | 0 / 0 / 0 / 0 | 0 |
| zero_budget-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| overloaded_budget-light | 0 | 0 / 0 / 0 / 0 | 0 |
| overloaded_budget-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| cache-port-light | 6 | 0 / 0 / 0 / 0 | 0.0 |
| cache-port-isaac | 6 | 0 / 0 / 0 / 0 | 0.0 |
| diagnostic-01 | 84 | 0 / 0 / 0 / 0 | 0.0 |
| final-pair-light | 0 | 0 / 0 / 0 / 0 | 0 |
| final-pair-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-loaded_path_obstruction-light | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-loaded_path_obstruction-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-zero_budget-light | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-zero_budget-isaac | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-overloaded_budget-light | 0 | 0 / 0 / 0 / 0 | 0 |
| graceful-overloaded_budget-isaac | 0 | 0 / 0 / 0 / 0 | 0 |

原两订单双端各有 636 次 WALK、651 次 DRIVE，最多三个同时运行命令；335 次候选步行派工受已有通道持有约束。B+1 两端各有 956 次 WALK，DRIVE 为 985/988 次，通道受占用的步行候选为 664/665 次。六份原覆盖抽取的资源所有权缺失计数均为 0。专用障碍两端各有 8 个实际带载中途状态样本，其中 4 个异常样本保持同一命令的载荷和资源所有权。这些为本次记录内状态/动作计数，不是独立重复实验或任意交叉口安全证明。

原始缓存窗口基线独立审计 PASS；13 项独立副本篡改均按预期拒绝：计划变化、承诺保护、观察锚点、隐瞒超限、反馈时间倒置、错误决策时延、错误观察时延、外来事件、非有限时刻、遗漏决策行、遗漏反馈行、错误周期汇总、错误反馈汇总。原记录保持。

规则回退通常只提出一个当前动作；可比较项为 0 不能解释为未来排程稳定。开始时移比较保留列表的提议时刻，缓存头部派工时绑定当前时刻的偏差另见实际决策/事件，不计作暂定列表变更；该指标不证明实际开始时刻稳定。状态样本和单次运行内的多个决策周期也不是独立实验重复。暂停/恢复见证针对控制器接口，未进行 GUI 人工体验验收，未把接口暂停当成工业停止能力。

## 计时解释与保留失败

反馈产生到首次观察、到决策结束分别测量，不能用单轮预算达标替代反馈延迟结论。首组完整 Kit 的 4,092 个周期最大为 3.7483093 s，但反馈到决策结束最大为 9.6034138 s；这两个量的起点不同。`elapsed_s` 包含驱动末尾的离线审计；进程墙钟还包含启动、导出和退出。分类计时、周期计时存在包含关系，不重复相加，未分类墙钟不擅自归因给渲染或物理。

受测为 Windows 11 build 26100，Core Ultra 9 275HX（24 核/24 线程）、31.7 GiB 内存、RTX 5070 Ti Laptop GPU，Isaac Sim 6.1、项目 Python 3.12.13、PowerShell 7.6.5。性能运行与工程测试串行，期间进行了轻量文件检查和文档工作，不声称机器独占或专用实时平台。Headless Kit 应用更新不是显示帧率，USD 运动学/读回不是动力学认证；无 1:1 墙钟配速结论。

保留以下实际开发证据，不以最终结果抹去历史失败：

- 首轮 25 项测试中 4 个失败、4 个错误：准备前缀条件未排除尚未结束的载具占用，诊断窗口/预算也不足。修正为实际底框到达 J2 且无运行命令的前缀，并明确区分诊断预算；原日志保留。
- 首次轻量测量因实例绑定的计时包装器不适用于执行器事务副本，导致事件错误和审计失败。改用按接收对象绑定的方法描述符；后续有/无计时探针的实际事件与决策一致性回归已随最终完整检查通过。
- 静态复查发现缓存丢失原 PREPARE 原因、规则重试误标为完整核验缓存、独立反馈审计缺少观察延迟和事件身份复核，均已修订并纳入相应回归/负例。随后补齐日志与实际决策的逐项覆盖、反馈事件集合和时延汇总重算；新增测量起始事件数，避免续接前缀被计入新反馈。
- 原主矩阵的五个 Kit 报告均在快速关闭前保存为 `closed=false`，进程退出码均为 0。原测量驱动显式启用 `fast_shutdown=True`，本机 SDK 的快速关闭路径会在 `close()` 内结束进程，故其后的 Python 关闭回执未执行。这些原报告和严格比较失败保留；后续 S19 入口显式关闭快速退出，实际验证完整扩展清理返回、`closed=true` 和进程退出码。原长链不能被重标为具有 Python 清理返回回执。
- B+1 首条保护摘要复算曾失败：审计将配置中整数坐标 12 解码为 12.0，改变了原字节摘要。现按已通过结构解码的保存配置重建原数值表示；实际状态、日志和摘要不改写。新增回归首跑有观察返回值的测试取值路径错误，修正后通过；双端原记录重审及13项负例重验均通过，原失败保留。
- 缓存候选的本地重放辅助脚本首跑误用只支持同质元组的通用解码器读取 `(任务ID, 整数序位)`，尚未进入候选核验即失败。改为显式恢复既有 Genes/Step/Schedule 结构后，双端各2个候选均核验有效并绑定原日志，各4次缓存实际派工；原失败日志保留，未修改公共契约解码器或候选原件。
- 主负载 50 ms 搜索未取得完整已核验候选；B+1 Kit 三次超过 5 s 后保持 WAIT，另有实际 USD 路径阻挡，原严格比较失败保留。零预算和 1 ms 负载用于验证不派非法/迟到动作及资源保持，不作为生产吞吐或预算达标结论。

## 源码与证据追溯

首组双订单完整链在第一次测量源码上执行；期间发现并修订了缓存原因/来源标签和独立审计记录问题，同时将主报告中的重复大日志改为独立日志摘要引用。首组原驱动、在线策略和审计脚本字节单独保留，不能重标为最终源码。该完整链未获得短预算完整候选，实际缓存分支覆盖另由后续诊断提供。

B+1 完整链使用第二组测量源码，已经包含缓存原因与来源标签修订。原带载障碍、零预算和 1 ms 窗口使用第三组源码，额外记录测量起始事件数、将独立暂停接口的周期起点移至观察构造前，并强化保存记录的完整性审计。缓存和续接诊断使用第四组源码，S19 的 Kit 入口进一步显式使用完整清理关闭；调度器和生产执行规则保持第三组语义。前两组从原点开始，可明确重建起始事件数为 0；续接诊断使用实际保存的前缀数。早期独立暂停行的周期分布不含其观察构造耗时，单列接口总耗时包含该部分，不将这个历史样本改写为最终计时边界。

测量结束后，仅将 Python 与新增在线配置的 CRLF 规范化为 LF，逐一核对 AST/JSON 等价，保留规范化前后摘要和原测量源码。四份获批原字节 JSON 不改变。四组分别保留完整的捕获源码集；严格比较使用逐项摘要匹配的审计模块，原窗口与第四组审计模块字节相同，驱动关闭配置不同。最终独立完整性审计另作用于所有原始记录。规范化后又修订独立审计的初始数值表示重建并新增回归，故最终审计脚本不能仅由换行等价证明替代；调度、执行和计时实现仍保持第四组语义，最终工程摘要单列。首组完整链保存记录复审使用修订前的审计脚本，其首条日志已有2个实际事件，保护锚点不依赖零事件初态重建；B+1重审和其余后续保存记录审计使用修订脚本，各自实际审计器摘要见机器结果。

机器结果中保存六个实际摘要映射：四组测量源码、准备前缀诊断的 85 文件子集，以及最终规范化源码。该 85 文件映射完全包含于第四组的 128 文件集合，重叠文件字节一致；不把较小映射描述为完整仓库快照。

最终规范化源码另执行两订单/延迟供料 20 h 阈值双后端窗口（两端实际在 24 h 事件边界结束），以及相同参数的带载障碍、零预算和 1 ms 三组双后端窗口。四组严格比较均通过；使用完整清理关闭的 Kit 均实际返回关闭回执并以退出码 0 结束。它们是有限窗口补充，不能给原完整链补写关闭回执，也不能覆盖 B+1 原轨迹差异。

基线 540 个受跟踪文件中，533 个未变更文件按既有 `.gitattributes` 的 Git 内容摘要保持；四份 `-text` 获批 JSON 保持原字节。工艺、时长、负荷、容量及历史证据未变。分支 main、HEAD 和空暂存区复核保持。

具体策略和复现入口见 [在线策略说明](../algorithms/online_policy.md)，机器结果见 [S19_online_r1.json](S19_online_r1.json)。源码/隔离 wheel、真实 Kit 和历史记录重验分别陈述；未运行的新远端 CI 不写为成功。既有符号焊接、合成质量/接收、共用落点及工业 G2 限制继续有效。

## 确切待审内容与拟发布操作

目标为[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)，分支 **main**，基线 `d761df261dacd953db288e3ca55416b555255a4b`。最终只读核查时远端 main 仍为该基线，既有 S18 r4 标签保持，拟新增标签尚不存在（2026-10-09T03:23:23+08:00）。拟新增不可移动的 annotated 标签 **step-S19-r1**，单个提交标题 `feat: add measured online budgets and protected scheduling fallback`。

拟审阅 **22 个文件**：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/algorithms/online_policy.md`
- `docs/steps/S19.md`
- `docs/validation/S19_online_r1.json`
- `docs/validation/S19_online_r1.md`
- `examples/online/cache_workload.json`
- `examples/online/limits.json`
- `examples/online/limits_diagnostic.json`
- `examples/online/limits_overload.json`
- `examples/online/limits_zero.json`
- `examples/online/workloads.json`
- `scripts/audit_online.py`
- `scripts/run_online_window.py`
- `scripts/verify_production_chain.py`
- `src/adaptive_hrc_scheduling/algorithms/simulation_joint.py`
- `src/adaptive_hrc_scheduling/control/online.py`
- `src/adaptive_hrc_scheduling/control/online_timing.py`
- `src/adaptive_hrc_scheduling/control/production_loop.py`
- `tests/test_online_budget.py`

本地审阅 ZIP 包含上述确切目标文件、逐文件 SHA-256 清单和相对基线的完整差异。review 元数据只用于审阅，不加入仓库；不公开原始会话、完整运行日志或含账号/主机标识的配置；仅列匿名受测平台摘要。不计划创建 PR、Release 或上传附件。

仅在负责人明确验收并批准该确切快照后，才拟精确暂存清单路径、核对规范化字节与既有署名，创建一个提交和新标签，执行非强制 `git push --atomic origin main step-S19-r1`。随后核验远端完整树、分支/标签和双平台必需 CI，通过后才记录 PUBLISHED。内容或远端基线变化时重新审阅，不强推。

当前仍为成果验收和确切发布待审。S19A、S19B、S20—S28 未启动，后续顺序和分别授权要求保持。
