# S18-4：工业G2公开证据工作交接

2026-10-08；PR151 / LOG197。负责人明确要求现在开展工业G2，利用现有互联网资料完成，创建“S18-4”新对话直接开始；沿用当前目录/main，不建分支或worktree，不改变现有模型和思考强度选择。当前授权为 INDUSTRIAL_G2_EVIDENCE_WORK_AUTHORIZED；不是预先认定工业G2已经关闭。

## 执行顺序和范围

1. 先读取AGENTS.md、README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md、docs/steps/S18.md及现行总纲；阅读本交接、S18全量审阅及原资格/钢体系/Q01—Q06说明。前置资料已在当前目录，无须用户重复提供。
2. 直接开始互联网搜索与来源核验。优先标准发布机构、工艺/设备原厂、制造商原始技术文件、可核实资格记录及原始研究。既有B01/B02/B03/B11等来源作检索入口，须实际打开并核查，不能只引用摘要或搜索片段。
3. 对Q01接头/材料/姿态、Q02两模式工艺及资格、Q03程序/夹具、Q04人员/隔离/监督、Q05同输出检验、Q06停点/异常/返修逐项建立“要求—来源—版本—适用范围—原文定位—项目对应—证据强度—结论/缺口”矩阵。区分通用标准、其他项目案例、可迁移依据与确实覆盖本项目的证据。广泛检索并交叉核验后再判断，不因旧文档写OPEN就停止。
4. 尽可能完成公开资料可支持的工业G2工作，提交逐项结论、确切来源和可审阅成果。只有实际适用证据齐备才判定关闭；网页资料不能证明的项目特定资格如实列缺口，不用研究批准、相似设备案例或新增仿真假设替代。资料不足时交付完整调查成果和剩余事项，不能把“完成检索”写为“取得资格”。
5. 工业G2证据工作形成结论后，复检下列保留问题，汇总受影响项和修复范围；按照负责人本次明确顺序，等待其后续授意才统一修复。不要在检索过程中顺手修复F1/F2或将规划衔接意见提前实施。

允许本步必要研究/证据/治理文档；不得伪造证书、适用性或签署记录。现有批准仿真仍可研究，工业执行权限不由搜索动作自动取得。不改变冻结产品/数值/模型规则来匹配找到的外部案例。无新Git暂存/提交/标签/推送/PR/附件、资产导入、环境升级或S19—S28/S19A/S19B启动；不调用子代理。Windows命令显式使用PowerShell7。

## 保留待复检、待授意修复清单

| ID | 现象与责任位置 | 已有证据 | 当前处理 |
| --- | --- | --- | --- |
| F1 / P2 | simulation_joint.py:295—306，CREW修复取自另一个随机模式；planning/production.py:117空min异常；simulation_joint_policy.py:227—231丢失有效候选，:86—87漏计失败修复 | 实际准备前缀24.439733333333333h；正常search seed2、CREW+START_SLOT实际异常；策略WAIT且schedule为空，预算记0迭代/1试次 | OPEN；G2工作后复检，待负责人授意统一修复 |
| F2 / P2 | simulation_joint.py:350—380，声明班组/开始时段未与执行命令绑定 | 全slots改为窗口终点+100h仍valid，14个受控核心命令提前执行；固定H声明W1改W2、原W1轨迹保持仍valid | OPEN；G2工作后复检，待负责人授意统一修复 |
| C1 / 规划交接待核对 | 总纲S18现行仿真例外，与S20资格门/S21工业G2旧前置的衔接不够明确；未安排工业G2实际补齐责任步骤 | 当前对话后续问答只读核对，PROJECT_CHARTER.md:354、457、474；原先提出专项位置仅是建议，未成为获批步骤 | 本次已明确在S18-4直接开展G2；仍需在结论后复核S20/S21前置表达，待授意统一处理 |

完整F1/F2结论和复现范围见[全量审阅](../validation/S18_post_release_audit_r1.md)及配套JSON。不得将当前授权解释为F1/F2修复批准；也不能把其修复推给S19后才承认S18完成。

## 基线、文件与证据

当前main/HEAD为`cd21aa0a26e53585b9bf8cc3a7b7b6900c428ac1`，标签`step-S18-simulation-r2`已发布；双平台各源码/隔离wheel759项实际通过。r1提交`adba1a890cf13b851cdd56fe9cc48a6500936f8c`及原超时/标签保持。工业G2目前OPEN / NOT_ESTABLISHED。

当前目录已有未提交的S18全量审阅/治理文件，须保留：AGENTS.md、README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md、docs/steps/S18.md、docs/validation/S18_completion_exits.md、docs/validation/S18_post_release_audit_r1.md/json；本交接追加到该状态，不重置、不重新克隆、不创建worktree。

S18审阅本轮100专项通过，新旧生成检查通过；220工程/327捕获输入、88批准blob、五旧包及六对双后端证据核对。冻结213中13明确获批变更/200保持。新审阅并未重跑完整759/wheel/CI/Kit。现有完整链是规则驱动，四联合对照为8h窗口；工业资格、符号焊接、合成质量/接收、共用J2落点和GUI限制保持。

公开入口：docs/model/selected_steel.md、docs/model/S18_qualification_decisions_r1.md、docs/model/S18_production_mapping_r1.md、docs/model/S18_simulation_scope_proposal_r1.md/json、docs/model/S18_simulation_scope_approval_r1.json、docs/validation/S18_completion_exits.md。原获批方案字节和历史审阅不覆写。

本地复现原件保持在原私有输出；前述审阅JSON记录证明文件摘要。新对话可按需读取当前对话、S18-1和S18-2历史，但无需等待再次启动许可。工业G2结论及其后的问题复检先交负责人，再按其授意统一修复。
