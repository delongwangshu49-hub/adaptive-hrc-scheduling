# S19B-4：B3 实际试用与演示交接

2026-10-14；PR182 / LOG249。当前 **B3_ACTUAL_TRIAL_AND_DEMONSTRATION_AUTHORIZED**。

负责人明确要求创建S19B-4，不创建新分支，在新对话继续完成第四步：**由AI用简中完成完整任务，再切英语检查展示路径**。接手后直接实施并留证，不重复等待B3启动许可。旧文档的“B3未启动/另审”是旧时点，不能覆盖本次授权。创建/接收实际回执另存 `.local/s19b-4-handoff-20261014/`，本文件不预写成功。

## 工作目录与保持边界

沿用 `D:\7023p`、现有main与全部未提交成果，HEAD `aab9ca848eec6816717f2929a8217f642c3bc2bd`。不创建分支、worktree或子代理，不暂存、提交、打标签或推送。Windows命令显式使用 `C:\Program Files\PowerShell\7\pwsh.exe`，Git只读设 `GIT_OPTIONAL_LOCKS=0`。

保持全黑、黑白灰极简方角、B1简中/英语、中央真实Kit原生子窗口自动铺满。保持生产输入/工时/路线/落点/手位/支承运动、2.4m、0.02h/对、观察隔离与既有预算。工业G2仍OPEN/NOT_ESTABLISHED；整步验收、发布及S20—S28另审。

已接收兼容修订保留。固定承载架、收存托片、可重配横杆继续 **OWNER_DECISION_RETAIN_FOR_DEMONSTRATION / TECHNICAL_OPEN_NOT_FIXED / NON_BLOCKING_FOR_DEMO**。不修复、隐藏或改称全部整改完成；原510对象与碰撞/可见性保留。临时模型原生审阅面板仅英语，不替代B1双语桌面。

## 已有成果及确切封包

先读[步骤卡](S19B.md)、[B2最终审阅](../validation/S19B_B2_r2.md)、[B2机器摘要](../validation/S19B_B2_r2.json)、[控制契约](../sim/S19B_B2_control_contract_r1.md)、[桌面入口](../../desktop/s19b/README.md)。B1及模型背景可沿[S19B-3交接](S19B_3_handoff.md)索引查看。

B2当前是 **B2_MINIMAL_CONTROL_VERIFIED_WITH_LIMITS / OWNER_REVIEW_PENDING / NOT_APPROVED / NOT_PUBLISHED**。输入/确认启动、有序停止、持久幂等与同一运行重连已在所列范围验证；首条停止在启动受理前持久拒绝。24桌面契约、11实际后端输入/启动负例、8组真实Qt/CPU/中央Kit及验证程序实际exit0通过，源码/隔离wheel各862项。

完整正常CPU和Kit各436有效工序、272.35047973655236h、接收1；4402事件/2072决策严格比较、执行/决策独立重建PASS。六个最终运行各121捕获源码/输入与B2最终字节一致。AI在实际交互桌面已确认启动/有序停止至55.49042307430556h、接收0、双审计/完整Kit关闭/实际退出0；这不是完整订单完成或B3任务，也不是负责人人工验收。

| 封包 | 原位置与摘要 |
| --- | --- |
| 最终94文件B2-r2 | `.local/s19b-b2-review-20261014-r2/S19B-20261014-B2-r2-review.zip` |
| zip SHA256 | `c6fd81162e48e21bd54fe4605ec7b1e33641b5f95bf6b0d482c2ba920a74b1b7` |
| manifest SHA256 | `31e4996e7c45b93d916134c51f2aae62ea2e2cb5e83b79de508ac792279125be` |
| 中间89文件B2-r1 | `.local/s19b-b2-review-20261014/S19B-20261014-B2-r1-review.zip`；SHA256 `aaae2b9fb618bb188d5819b22042197132ff08fa2050736843603aae83a08779` |

原zip、manifest、失败及旧封包保持不可变。本次交接前94成员全部核对一致；本次治理追加会使AGENTS、步骤卡、日志与台账相对封包出现预期差异，不能据此重写旧清单或声称94个工作文件仍完全一致。交接快照和差异见本地回执。新的B3证据/候选另建新目录与身份。

## 新对话直接完成的任务

1. 核对实际工作目录、main、现有成果与当前桌面/进程状态，阅读步骤卡完整B3出口。开始前明确可重复的任务输入、成功条件、证据和对照口径。既有B2测试作为基线，不重新命名为B3。
2. 在真实交互工作台使用**简体中文**完成一次新的完整任务。以已验证SR-W1单件为代表，输入并检查草稿/有用校验反馈，明确确认启动，等待实际初始化，检查中央真实Kit、订单/动作/实际原因与只读定位/相机。运行到实际产品接收1，查看完成、两审计、保存证据与真实退出，再通过历史只读核对。同一个新身份贯穿，不能把有限前缀或有序停止的接收0称作完整成功。
3. 然后切换**English**，核查输入/确认、运行/完成、原因、定位/相机、证据与历史等展示路径，语言切换保持草稿、身份、输入摘要及保存事实。完整生产结束后实时定位不可用是正确边界；如展示需要英语实时场景，可新建独立英语演示运行并留证，不能伪造已退出运行仍在线。形成可复现的英语展示顺序与截图/实际结果。
4. 按步骤卡检查前端开关与规定负载的语义/性能对照要求。复用已有可信证据并明确缺口；需要新增时先声明输入/负载/测量口径与比较条件，保持生产/观察/预算。不得借S19A性能指标或单次主观流畅宣称B3正式性能已通过。
5. 在授权边界内完成必要的本阶段界面修订及针对性回归；发现冻结生产/模型或新增控制能力问题时保留具体证据与范围，不静默扩展。整合B3任务、英语展示、语义/性能结果、失败/限制和确切候选，交负责人审阅。AI实际操作与负责人手工体验/整步验收严格分别登记。

## 真实入口与验证线索

根CPU `.venv`；隔离Qt `desktop/s19b/.venv`；Isaac现有 `D:/Dev/tools/isaac-sim-6.1`。本地 `.local/s19b-desktop-settings.json` 已配置简中/Isaac。正常入口 `scripts/start_s19b.ps1`；核心界面 `desktop/s19b/src/s19b_desktop/app.py`，默认 `control_mode=True`。不向根环境或Kit安装Qt。

现有实际交互桌面上次留在已停止/实际退出状态；先实时观察，不依赖旧窗口句柄/坐标。需要新运行时等待旧后端实际退出，再确认新草稿和新run_id。PowerShell启动的进程有时处于不可见会话，必须确认用户交互桌面上真实窗口。已有本地启动器 `.local/s19b-b2-dev-20261014/B2ReviewLauncher.exe` 可经Computer Use启动，启动器自身退出不代表Qt没有打开。

原生桌面操作先读computer-use技能，使用其 `@oai/sky` / node_repl 工作流；每次从实际窗口/截图/UIA状态操作。cua_repl原生接口在本机禁用。截图必须来自真实桌面/Kit渲染；Qt普通控件截图可能缺GPU子窗口，不冒称完整桌面。自动Qt测试与AI原生桌面试用分别记载，均不等同物理输入法候选/负责人手工验收。

| B2现有证据 | 本地路径 |
| --- | --- |
| 最终8组控制 | `.local/s19b-b2-ui-final-r4/b2-ui-verification.json` |
| 验证程序exit0 | `.local/s19b-b2-dev-20261014/ui-final-r4-exit.json` |
| 完整正常双后端 | `.local/s19b-b2-full-normal-r2/b2-ui-verification.json` |
| 严格比较与独立重建 | `.local/s19b-b2-dev-20261014/full-normal-parity-final.json` |
| 六运行来源/保留检查 | `.local/s19b-b2-dev-20261014/source-and-preservation-final.json` |
| 11后端负例 | `.local/s19b-b2-backend-negatives-final/verification.json` |
| 源码/wheel完整检查 | `.local/s19b-b2-dev-20261014/full-check-r2.log` |
| 实际桌面运行 | `.local/s19b-runs/S19B-ac701028200a4570840fce50a09cd707` |
| 实际桌面图 | `docs/sim/images/s19b/b2-r2/owner-native-desktop.png`、`owner-stopped-desktop.png`、`owner-initializing-unknown.png` |

完整正常CPU `.local/s19b-b2-full-normal-r2/runs/S19B-535246c14fab41a7a1662b2fec30b6de`；Kit `.local/s19b-b2-full-normal-r2/runs/S19B-a9afff148fd6447e81996149951c0b8a`。旧紧急模型链4400事件/2070决策与B2链不同，分别保留。

功能验证脚本 `scripts/verify_s19b_b2_ui.py`（含 `--full-normal`）和桌面contracts可用于必要复验，但不能替代新的B3实际任务。`scripts/compare_production_chain.py`支持B2封存sources/report与新run_id的严格比较。新输出目录不得覆盖既有记录。

## 重要限制与失败保留

- 可用控制为确认启动、有序停止、核对重连/恢复已有连接；暂停/继续/重置/运行中插单改单/通用取消继续禁用。停止在派工边界禁止新增并处理已启动动作；不是工业急停、硬实时、暂停或杀进程。close_display仅旧检查点显示生命周期。
- 初始化前/断连/损坏/缺失/旧身份显示未知，不从窗口或进程存在推断生产正常。单run永久worker-claim，不在原目录重启崩溃worker；退出后只读历史不能称恢复生产。
- Kit完整关闭返回后helper显式退出，跳过6.1RC解释器/插件最终收尾；不是普通解释器退出修复。所有exit必须有实际观察回执。
- B2实际桌面曾遇到Kit初始化118线程Suspended，受权恢复同一bootstrap后完成；根因未知，不能称已修复。旧PID101332已退出，不复用旧PID恢复脚本，避免误操作其他进程。原诊断/回执 `.local/s19b-b2-dev-20261014/bootstrap-resume-receipt.json` 保留；遇新异常先查本次身份和实际状态。
- 初轮前端管道丢失worker exit1、恢复摘要格式差异、非法首条停止及中间来源不一致等失败均保留。部分旧工具返回exit1虽内部JSON通过，不称完整验证程序exit0；最终8组有独立父进程实际exit0，完整双后端各实际exit0另记。

本次当前对话只整理和派发交接；B3实施、实际结果及最终审阅由S19B-4完成。收到交接后直接继续工作，不以“准备就绪”结束已授权任务。
