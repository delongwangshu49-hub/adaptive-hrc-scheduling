# 项目进度日志

本文件记录可以公开的研究决策、实施状态、检查证据和下一步工作。日期采用 UTC+08:00；历史准备记录依据项目讨论整理到日，不补造精确时刻。私人身份、来源文件位置、原始对话、机器配置和敏感运行日志不在此记录。

本文件当前版本为 0.2.1，更新于 2026-09-30。项目范围与路线已确认；实施阶段 P0 至 P5 均未验收。负责人已认可治理基线 v0.2.0，并启动 S00；本次 v0.2.1 首发快照仍待单独验收和上传批准。工作状态、人工决定和远端状态分别记录。

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

研究范围和路线仍为 CONFIRMED，依据 PR008、PR009；逐步审批上传要求来自 PR011，治理认可与 S00 启动见 PR012，仓库配置确认见 PR013。S00 本地文件及指定检查已完成，等待本次快照人工审阅；其他步骤未实施。

| 步骤 | 工作 | 工作状态 | 人工验收 | 上传许可 | 发布状态 |
| --- | --- | --- | --- | --- | --- |
| S00 | 治理基线与仓库首次发布 | VERIFIED（本地检查） | PENDING_REVIEW | PENDING_APPROVAL | NOT_PUBLISHED |
| S01 | 开发环境与依赖复现 | NOT_STARTED | NOT_REQUESTED | NOT_REQUESTED | NOT_PUBLISHED |
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

首发包包括八个文件，配置已确认，完整清单见 [S00 步骤卡](docs/steps/S00.md)。当前没有根项目 Git 仓库、远端地址、提交或标签，相应字段保持空值。工作清单见 [公开总纲](README.md#步骤化路线图)。

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

## 下一步

1. 审阅已封存的八文件完整差异、内容摘要、本地检查证据及拟执行操作。
2. 取得负责人对确切 S00 快照的人工验收，以及创建 public 仓库和首次推送的明确批准。
3. 获批后首次初始化 main，创建空远端，提交并推送获批文件和步骤标签；核验真实远端，交付回执。任何实质变化重新审阅。
4. 本任务仅开展 S00；后续 S01 需另行启动。未获首发批准时保留本地成果。

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
