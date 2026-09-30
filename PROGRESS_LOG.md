# 项目进度日志

本文件记录可以公开的研究决策、实施状态、检查证据和下一步工作。日期采用 UTC+08:00；历史准备记录依据项目讨论整理到日，不补造精确时刻。私人身份、来源文件位置、原始对话、机器配置和敏感运行日志不在此记录。

本文件当前版本为 0.3.0，更新于 2026-09-30。项目范围与路线已确认；实施阶段 P0 至 P5 均未验收。S00 r1 与 r2 均已验收、批准并发布；S01 已获本地实施授权，确切快照仍待人工验收与上传批准。工作状态、人工决定和远端状态分别记录。

## 状态约定

| 维度 | 状态 | 含义 |
| --- | --- | --- |
| 工作 | NOT_STARTED / IN_PROGRESS / DRAFTED | 未开始 / 实施中 / 草稿形成 |
| 工作 | VERIFIED | 本地指定检查通过；不含尚未执行的远端检查 |
| 验收 | NOT_REQUESTED / PENDING_REVIEW / ACCEPTED / CHANGES_REQUESTED | 未提交审阅 / 待审阅 / 已验收 / 要求修订 |
| 上传许可 | NOT_REQUESTED / PENDING_APPROVAL / APPROVED | 未请求 / 待本步批准 / 确切快照获上传批准 |
| 发布 | NOT_PUBLISHED / PUSHED / PUBLISHED / FAILED | 未上传 / 已推送待核验 / 快照及必要检查通过 / 上传或检查失败 |
| 决策 | PROPOSED / CONFIRMED | 待定建议 / 已确认决定 |
| 追溯 | BLOCKED / SUPERSEDED | 受明确依赖阻碍 / 被后续记录替代 |

CONFIRMED 不等于 VERIFIED，VERIFIED 不等于人工验收，ACCEPTED 不自动包含上传许可。批准及远端核验齐备才称步骤发布完成。没有证据不填写测试通过、改善百分比、提交哈希或完成日期。

## 当前步骤台账

研究范围和路线仍为 CONFIRMED，依据 PR008、PR009；逐步审批上传要求来自 PR011，治理认可与 S00 启动见 PR012，仓库配置确认见 PR013。S00 首发的实际验收与上传批准见 PR014 和 LOG007；PR015、PR016 记录完成性审阅及有限修复授权；随后发生的 r2 批准见 PR017、LOG009。PR018 授权 S01 本地实施，未授权上传；S02—S28 未实施。

| 步骤 | 工作 | 工作状态 | 人工验收 | 上传许可 | 发布状态 |
| --- | --- | --- | --- | --- | --- |
| S00 | 治理基线与仓库首次发布（r1、r2） | VERIFIED | ACCEPTED | APPROVED | PUBLISHED |
| S01 | 开发环境与依赖复现 | VERIFIED | PENDING_REVIEW | PENDING_APPROVAL | NOT_PUBLISHED |
| S02 | 基础检查与持续集成 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S03 | Isaac Sim 最小运行验证 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S04 | 相关工作与研究假设核对 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S05 | 生产流程与数学规格冻结 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S06 | 数据对象与接口契约 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S07 | 疲劳与恢复模型 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S08 | 扰动与信息可见性规则 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S09 | 轻量执行内核 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S10 | 独立约束检查与指标核算 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S11 | 可行调度生成器与规则基线 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S12 | 轻量闭环与动态重调度 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S13 | 自建 Isaac Sim 工厂场景 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S14 | Isaac Sim 派工与反馈适配 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S15 | 双后端一致性与完整闭环验收 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S16 | CP-SAT 简化小规模参照 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S17 | 大邻域搜索骨架 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S18 | A 状态感知模式与排程联合决策 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S19 | 在线预算、回退与计划稳定性 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S20 | 实验协议、实例与参数冻结 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S21 | A 主对照与消融实验 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S22 | D 人因权衡实验 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S23 | B 反馈缺陷稳健性检查 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S24 | C 扰动恢复表现评价 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S25 | 整合论证与研究边界 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S26 | 可复现包与工程复核 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S27 | 项目报告与演示材料 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
| S28 | 版本归档与最终交付 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |

台账列示当前实际状态；r2 回执已在本次 S01 候选更新中补录，详见 [S00 步骤卡](docs/steps/S00.md)。S01 检查范围与待批操作见 [S01 步骤卡](docs/steps/S01.md)。工作清单见 [公开总纲](README.md#步骤化路线图)。

以下 LOG001—LOG008 保留各自记录时的事实和状态，其中“当前”“尚未”等词只指该条历史记录的时间；r1 与 r2 发布事实分别由 LOG007、LOG009 补录，S01 状态见 LOG010。

## 2026年9月25日 研究准备启动

- 记录编号：LOG001
- 记录类型：RETROSPECTIVE
- 状态：CONFIRMED
- 负责人行为：提出开展项目前置理解与准备的目标。
- 辅助工作：阅读所提供参考材料，整理调度、协作与闭环验证的基本要求。
- 结果：建立初始问题理解，尚未确定最终研究组合。
- 关联指令：PR001
- 证据边界：这是准备工作摘要，不构成代码、仿真或实验完成证据。

## 2026年9月30日 范围复核与研究问题收敛

- 记录编号：LOG002
- 记录类型：RETROSPECTIVE
- 状态：CONFIRMED
- 负责人行为：明确从零搭建；要求提高研究深度；要求重新核对参考材料；指出完整框架应统领子课题。
- 辅助工作：复核来源、比较研究方向、分析可行性和实验归因问题，并修订方案。
- 结果：从宽泛的疲劳调度方向收敛为完整系统下的研究安排；未选方向作为扩展可能性保留。
- 关联指令：PR002 至 PR007
- 证据边界：候选贡献尚未通过完整文献查证与实验验证；不宣称研究空白。

## 2026年9月30日 研究组合与技术路线确认

- 记录编号：LOG003
- 记录类型：RETROSPECTIVE
- 状态：CONFIRMED
- 负责人行为：确认一个完整框架、A 核心方法、D 人因分析，以及 B 稳健性检查、C 恢复评价的分工；随后认可技术路线。
- 辅助工作：将决策转换为生产模型、滚动调度、大邻域搜索、两种执行环境与阶段验收安排。
- 已确认路线：Python 领域模型与事件内核；Isaac Sim 闭环执行；状态感知大邻域搜索；CP-SAT 小规模参照；统一日志和独立检查。
- 关联指令：PR008、PR009
- 证据边界：兼容性与性能仍需 P0 验证，模型参数与实验预算仍需 P1 及试运行确定。

## 2026年9月30日 治理文档与公开记录初始化

- 记录编号：LOG004
- 记录类型：CURRENT
- 状态：DRAFTED
- 负责人行为：授权编写四类治理文档，区分本地内部文件与公开材料，要求公开脱敏与规范化记录，并保留实际的人类主导作用。
- 辅助工作：起草总纲、进度日志及指令语义记录，设置本地文件忽略规则。
- 公开产物：[公开总纲](README.md)、本日志、[规范化提示词记录](PROMPT_LEDGER.md)。
- 本地控制：内部总纲和阅读中间文件不进入拟发布集合。
- 文档检查：已检查 UTF-8 编码、结构化记录格式、文件与章节链接、公开内容敏感字段和 Git 忽略规则。此检查范围仅为治理文件，不包含仿真、算法测试或人工全文验收。
- 关联指令：PR010
- 验收状态：PENDING_REVIEW
- GitHub 状态：尚未创建远端、提交或推送；未来分享意向不计作已发布。

## 2026年9月30日 步骤化执行与逐次发布修订

- 记录编号：LOG005
- 记录类型：CORRECTION
- 文档版本：0.2.0
- 对应步骤：S00；当前仅形成治理文件修订。
- 工作状态：DRAFTED；人工验收 PENDING_REVIEW；上传许可 NOT_REQUESTED；发布 NOT_PUBLISHED。
- 负责人行为：指出阶段阐述过于笼统、遗漏外部工程操作；要求补入命名和仓库创建，并在每步完成后由负责人批准，再上传该步内容。
- 辅助工作：细分 S00—S28，补齐动作、产物、验收与公开范围；定义初始化、分支、提交身份、许可、CI、快照审批及发布回执。
- 决策区分：逐步审批上传是已明确的要求；仓库名、所有者、可见性和许可处置待定，文档内容待审阅。
- 公开产物：README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md；本地内部总纲同步修订。
- 文档检查：36 项检查通过，覆盖版本一致、步骤编号与前置关系、结构化记录、文件与章节链接、公开敏感字段及本地排除规则存在性。此结果仅验证治理文件，不代表人工验收、算法测试、仿真运行或远端发布通过。
- 关联指令：PR011。
- 更正范围：替代 LOG004 对应 v0.1.0 的粗粒度安排和原“下一步”列表；既有范围与路线确认继续有效。最终集中整理仅为归档，不取代逐步发布。
- 远端行为：本轮未创建仓库、未提交、未上传；本记录不能充当创建或推送授权。

## 2026年9月30日 S00 本地首发准备

- 记录编号：LOG006
- 记录类型：CURRENT；对应步骤 S00；文档版本 0.2.1。
- 负责人行为：认可治理基线 v0.2.0；要求启动 S00，沿用当前目录，不创建额外工作分支或 worktree；明确选定仓库所有者、短名、public、main、描述、MIT 和现有隐私提交身份。
- 辅助工作：复核治理文件；补齐协作规则、换行规则、MIT 许可和步骤卡；准备精确首发清单、完整差异及内容摘要。治理文件的增量修订为 v0.2.1，研究范围与技术路线未改变。
- 检查状态：68 项本地检查通过，其中忽略规则检查覆盖 70 个正反用例；验证编码换行、公开敏感模式、链接与记录、步骤一致性、精确八文件索引及候选 Git 文件树。既有 36 项检查仅对应 v0.2.0，不替代本次证据。
- 工作状态：VERIFIED（本地检查）；首发人工验收 PENDING_REVIEW；上传许可 PENDING_APPROVAL；发布 NOT_PUBLISHED。
- 公开产物：[S00 步骤卡](docs/steps/S00.md) 所列八个文件；内部总纲同步维护但不公开。
- 关联指令：PR012、PR013。PR012 对 v0.2.0 的认可不追溯改写 LOG004、LOG005 当时的待审状态；PR013 配置确认不构成首发上传批准。
- 限制：根项目未初始化，尚无提交、标签或远端；本步未运行仿真、算法或 CI。S01—S28 未开始。

## 2026年9月30日 S00 首发回执补录

- 记录编号：LOG007；记录类型：RECEIPT；步骤 S00，修订 r1。
- 负责人行为：对 S00-20260930-r1 的确切八文件快照，明确批准验收、首次初始化 main、创建 public 仓库及首发推送。
- 关联指令：PR014；工作 VERIFIED、人工 ACCEPTED、上传 APPROVED、发布 PUBLISHED。
- 实际提交：[c2d76841758a87d2add110a3342206ba4b194aab](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/commit/c2d76841758a87d2add110a3342206ba4b194aab)。
- 实际标签：[step-S00-r1](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/tree/step-S00-r1)；文件树 `16e0c59a3ac84c807be4d5db8a077f8ffc24e208`。
- 批准包 SHA-256：`119d332b7b3ee581104cadd9c1ba74d3fc0eabc5b3d34ee645cf527dfee6045f`。
- 核验时间：2026-09-30T22:42:48+08:00；18 项发布核验通过，八文件内容与批准快照一致；CI 在 S00 不适用，没有声称 CI 通过。
- 后续复核：23 项完成性核查通过；未发现会否定 r1 发布有效性的阻断问题。发现的工具保护和时间措辞问题按 LOG008 有限修正。
- 补录边界：此处记录已经发生的 r1 事实，不填入本次 r2 尚未产生的提交哈希或发布结果，不修改既有标签。

## 2026年9月30日 S00 有限修订

- 记录编号：LOG008；记录类型：CORRECTION；步骤 S00，修订 r2，文档版本 0.2.2。
- 负责人行为：要求核查 S00 完成性和逻辑问题，随后批准有限度修复；范围限于本地封存保护及治理状态表述。
- 辅助工作：封存生成器在已有包、审批或发布回执时拒绝写入；检查失败时不生成审批包。明确审批前快照的时间语义，补录 r1 回执，区分已发布 r1 与待审 r2。
- 检查：5 个本地工具保护回归用例通过，原始审批包与回执摘要不变；本次文档的链接、结构、状态、脱敏和精确变更范围随 r2 快照核验。原 r1 的 68 项检查不冒充本次检查。
- 公开变更：README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md、docs/steps/S00.md；内部总纲和封存工具修复仅本地保存。
- 工作 VERIFIED；本次人工验收 PENDING_REVIEW，上传 PENDING_APPROVAL，发布 NOT_PUBLISHED；关联 PR015、PR016。
- 范围未变：不修改研究方法、仓库配置、许可、既有提交或标签；不进入 S01。

## 2026年9月30日 S00 r2 回执补录

- 记录编号：LOG009；记录类型：RECEIPT；步骤 S00，修订 r2。
- 负责人行为：对 S00-20260930-r2 确切四文件快照验收并批准提交及推送；决定编号 S00-R2-APPROVAL-001；关联 PR017。
- 状态：VERIFIED / ACCEPTED / APPROVED / PUBLISHED。
- 批准包 SHA-256：`fba78a0e460dee8327321c71f58c454fb48568edcca49308613a5605c5c356e9`。
- 实际提交：[afb9770d5d7ba5e310d868ad3e933c3b8b524cac](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/commit/afb9770d5d7ba5e310d868ad3e933c3b8b524cac)；父提交 `c2d76841758a87d2add110a3342206ba4b194aab`；树 `ea221283aec9f8702dcc064cd0db6d64a427e0ec`。
- 实际标签：[step-S00-r2](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/tree/step-S00-r2)；标签对象 `ae82a3caec259947c81af45e3028ad03f1e0a4ac`。
- 核验时间：2026-09-30T23:01:26+08:00；21 项远端检查通过，精确四文件差异及完整八文件摘要与批准快照匹配。r1 提交及标签不变；S00 无 CI。
- 边界：这是已发生的 r2 回执，取代 LOG008 对现在状态的解释，不改写 LOG008 当时事实，不授予 S01 上传许可。

## 2026年9月30日 S01 环境与依赖复现

- 记录编号：LOG010；记录类型：CURRENT；步骤 S01，修订 r1；治理文档版本 0.3.0。
- 负责人行为：授权直接开展 S01 本地工作，沿用现有目录和 main，不新建分支或 worktree；要求环境重建与解释器隔离，维持逐步快照审批。关联 PR018。
- 辅助工作：核对干净基线及远端引用，建立 src 布局、依赖声明、锁文件、最小安装入口和两项标准库自检；核查官方资料及实际版本，补录 S00 r2 批准和真实回执。
- 轻量选择：CPython 3.12.13、uv 0.12.3、uv_build 0.12.3；当前运行依赖为空，包版本 0.1.0。构建工具版本是本步工程选择，不冒称负责人逐项指定。
- 版本边界：Isaac 候选安装为 6.1.0-rc.26，自带 Python 3.12.13；仅核验解释器入口与模块发现，未启动场景。6.0 兼容性检查环境不计作完整仿真环境。
- 检查：18 项环境命令成功；开发环境、独立源文件副本的非 editable 安装及独立 wheel 安装均通过两项自检；116 项快照检查通过，原 75 个 S00 本地证据文件摘要不变。范围和限制见本步卡；完整证据留本地。
- 工作 VERIFIED；人工 PENDING_REVIEW；上传 PENDING_APPROVAL；发布 NOT_PUBLISHED。
- 公开产物：本步卡的确切十二文件集合；机器配置、原始日志和审批材料仅本地留存。
- 限制：本步仅安装骨架，不含领域实现、实验或 CI；跨平台与 Isaac 场景兼容性未验证。S02—S28 未开始。

## 下一步

1. 审阅 S01-20260930-r1 的十二文件快照、完整差异、检查证据和限制。
2. 负责人对确切快照验收并批准上传后，才在现有 main 追加一个提交和新注释标签 step-S01-r1，并向既有远端推送这两个引用。
3. 核验远端提交、父提交、文件树、标签及实际检查状态，交付真实回执。S01 启动授权不含上述提交或上传操作，后续步骤仍需授权。

## 步骤记录与发布回执

每步建立 docs/steps/Sxx.md，用文字说明做了什么、如何检查和为何成立，并保留以下字段。这是格式模板，不是预生成的完成记录；未知字段填 null，不补造授权、哈希或时间。

```yaml
entry_id: null
step_id: null
revision: 1
date: null
entry_type: CURRENT
prerequisites: []
objective: null
human_decision: null
assistant_or_tool_work: null
artifact_refs: []
checks:
  local: []
  post_push_required: []
limitations: []
work_status: NOT_STARTED
acceptance:
  status: NOT_REQUESTED
  decision_ref: null
publication:
  packet_id: null
  approved_snapshot_digest: null
  file_manifest_ref: null
  target_repository: null
  target_branch: main
  intended_tag: null
  permitted_remote_actions: []
  approval_status: NOT_REQUESTED
  approval_decision_ref: null
  status: NOT_PUBLISHED
  commit_sha: null
  commit_url: null
  verified_tag: null
  remote_checks: []
  verified_at: null
prompt_record_refs: []
supersedes: []
next_action: null
```

本地审批证据保留实际授权的可追溯引用；公开版本只使用规范化编号和角色，不复制原始会话或私人身份。审批包摘要绑定本次快照；私有证据位置不能写入公开 file_manifest_ref。

当前提交不能写入自身最终哈希。真实回执先记本地账本并在对话交付；下次获批日志补入上一回执。本次步骤标签和 GitHub 提交页提供即时定位。最终回执如需另行公开，作为独立文档修订申请批准。

内容不变而网络上传失败时，核对远端后可重试原授权快照；内容变化、CI 修复、目标改变或回滚须新审阅包。已发布标签不移动；修订递增 revision，保留失败和更正记录。

只在实质指令、审阅修改、验收或上传授权实际发生时追加提示词记录；例行命令不逐条抄录。没有人工证据不填 ACCEPTED 或 APPROVED。实施、试验和审阅贡献按事实记录。
