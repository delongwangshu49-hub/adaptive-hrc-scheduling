# S18仿真发布F01字节保留修订审阅 r2

2026-10-08；候选`S18-20261008-simulation-publication-r2`，共88文件；**PROPOSED / DECISION_PENDING / NOT_IMPLEMENTED / NOT_PUBLISHED**。原87文件发布方案已获S18-SIM-PUBLISH-APPROVAL-001 / PR147明确批准；推送前复现F01，尚未暂存或执行发布。原85限定验收与87具体批准、两个原ZIP和摘要均保持。

## 唯一新增冻结修订：四份JSON原字节保留

现行`.gitattributes`属于213冻结基线，并以`* text=auto eol=lf`管理文本。获批假设JSON及实际范围批准JSON（各含docs与随wheel副本）为原始CRLF；规范化会改变实际摘要，使原代码的严格研究准入拒绝`SIM_APPROVED_INPUT_DRIFT`。此前87预检遗漏了这一规范化后运行检查，失败已在私有LF副本复现，未推送已知失败内容。

拟仅在原规则之后追加以下四个精确路径的`-text`，使Git存储和检出保留实际已批准的原始字节：

```gitattributes
docs/model/S18_simulation_scope_proposal_r1.json -text
docs/model/S18_simulation_scope_approval_r1.json -text
src/adaptive_hrc_scheduling/simulation_inputs/S18_simulation_scope_proposal_r1.json -text
src/adaptive_hrc_scheduling/simulation_inputs/S18_simulation_scope_approval_r1.json -text
```

这是对冻结文件`.gitattributes`的单文件限定例外，不改变其他文件的LF规则、Git身份/目标/发布机制或D06其他项。原213基线中11个SR消费者迁移保持；本提案若批准则另加这一治理文件，变为12项限定差异/201项摘要不变。当前主工作区仍为11/202，规则已按原摘要保持，候选规则仅在私有审阅包及拟发布副本存在。

冻结原摘要：`5c1c1102851d293908149f1dd73007ef5bae793ebeee9df86ba7af6a71c52616`；候选摘要：`02cf812485fcf8a5e0a1d8ba9cd28e1126f955bb04bfe6db82445a7afb2afd62`。四份JSON的字节、内容、引用/批准摘要、源码、算法、数值、BOM/角色/几何及工况均保持。仅新增原87包中的实际87批准/F01治理记录，并加入候选`.gitattributes`，形成88文件新快照；逐文件摘要、预期Git blob及与原87完整差异随包交付。

## 失败与修复验证

原87预期LF载荷：原假设JSON SHA256 `8f1f2ea6a4e9096c57d9f3d6fc882291231c0240f2b03c2a97a7a93ba9065bbd`变为LF SHA256 `2ca6ec296a3dfe2f35ecaec65e379b5f7f03c34f7add89e536e0f1dfd5b2225e`，严格准入失败。私有拟发布LF副本加四条候选例外后，原SHA保持，SR-W1/SR-W2独立准入均PASS。该拟发布副本的源码759项（264.444s）、隔离wheel759项（266.053s）及格式/依赖检查均已实际通过；此项单独验证并非借用主工作区原759+759。实际失败、修复后准入、导出输入及检查摘要随审阅包保存。

原220工程输入、六对双后端与Kit正常退出、Scope A1及工业OPEN/NOT_ESTABLISHED均保持；焊接符号化、合成质量/接收、共用落点碰撞、无单独GUI体验验收和无正式A/D结论保持。未启动后续步骤。

## 针对此88文件快照请求的确切决定与操作

一次决定应同时覆盖上述单文件四条冻结例外，以及本88文件快照的实施和具体发布：

1. 将本包中已审阅的`.gitattributes`候选写入工作区，逐文件核验88文件原始SHA和预期Git blob，核查main/基线/已有署名、现有origin及标签空缺。
2. 精确暂存manifest的88文件，复核路径集合、blob与完整差异；在现有main仅创建一个新提交，标题`Complete S18 approved simulation implementation`。
3. 建立annotated tag `step-S18-simulation-r1`并执行一次非强制atomic推送：`git push --atomic origin main refs/tags/step-S18-simulation-r1`。目标仍为`https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling.git`，基线仍为`62c1c5393cb715b8089a93ee7ec658a0eb0e571d`；无其他未推送历史。
4. 核验远端main/标签peeled commit及实际Windows/Ubuntu CI，在本地记录实际批准和回执；不擅自回填批准快照、追加提交、建PR/附件、强推、移动标签、创建branch/worktree、升级环境或启动后续。

当前该88文件修订尚未批准，主索引/提交/远端均未变。旧87批准不被撤销，也不自动覆盖新增冻结文件；依据仓库“批准后内容或目标发生实质变化，重新审阅”要求，需对本具体修订作出决定后才实施并发布。

---

以下为已获PR147批准的原87方案，保留其编制时点。原计划未执行，当前新增例外以本r2待审条款为准。

# S18仿真成果具体发布审阅 r1

2026-10-08；发布审阅包`S18-20261008-simulation-publication-r1`；状态**DECISION_PENDING / NOT_PUBLISHED**。负责人已限定验收原85文件`S18-20261008-simulation-r1`，记录`S18-SIM-ACCEPTANCE-001` / PR146 / LOG192。原包的拟远端操作为空；本稿首次列明具体Git操作，尚未执行或获得该操作计划的明确决定。

## 确切内容与已取得证据

发布候选共87文件：原85文件中的运行代码、生成资产、获批输入和验证记录保持；仅9个既有治理文件新增实际验收/发布待审事实，并新增本发布计划与实际验收JSON两文件。与原批准快照的专门差异、本次完整差异、逐文件原始字节SHA256及按`.gitattributes`规范化的预期Git blob ID均随本地包交付。原85文件ZIP、清单和所有旧包保持，不将发布计划视为已经批准。

最终220工程输入未变：源码与隔离wheel各759项通过；六对同捕获源码轻量/真实Kit链严格比较、独立执行/因果审计和正常退出通过；最新SR-W1双产品2/2、SR-W2 1/1、原WV01 3/3实际接收。四共同8h通道及16保存候选、实际反馈/交班、连续中断/取消HOLD和15个独立负例拒绝已验证。仅治理变化运行UTF-8/无BOM、公开边界、差异与摘要检查，不重跑未改变的长链或工程输入。

工业G2 OPEN/NOT_ESTABLISHED、符号焊接、合成外生质量/接收、J2共用落点碰撞和无单独GUI体验验收保持；没有工业安全/产能或正式A/D结论。S19—S28及S19A/S19B未启动。旧审阅文件的待审状态按封存时点保留，现行验收以实际验收记录及LOG192为准。

## 目标、身份与拟推送历史

- 现有目标仓库：`https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling.git`，remote `origin`；不创建或修改远端。
- 分支：现有`main`，基线`62c1c5393cb715b8089a93ee7ec658a0eb0e571d`。只读远端核验与本地HEAD一致；`origin/main..HEAD`无未推送提交。拟历史为该基线之后的一项清单内新提交，不附带其他本地历史。
- 提交身份：沿用已配置且已核对的Git署名；具体元数据保留在本地发布计划。拟提交标题为`Complete S18 approved simulation implementation`。
- 新建不可移动的annotated tag：`step-S18-simulation-r1`；只读远端核查未占用。批准后执行前再次核验，冲突时不移动标签或强推。
- 提交最终哈希在实际创建前未知，当前不预写。实际批准、提交/标签/远端及CI回执分别保存在本地，不擅自追加回填提交。

## 待明确批准的操作

1. 逐文件重验87文件原始字节摘要及预期Git blob；复核工作区额外变化、main/基线、现有身份和远端ref。实质变化或历史/ref冲突先交付新审阅，保持原批准包。
2. 仅暂存manifest列出的87个文件，复核完整暂存路径集合、逐blob、差异及署名；不使用`git add .`或无选择的整目录加入。
3. 在现有main创建一项新提交；建立`step-S18-simulation-r1` annotated tag，绑定该确切提交；不新建分支/worktree，不重置改动。
4. 对现有origin执行一次非强制atomic推送：`git push --atomic origin main refs/tags/step-S18-simulation-r1`。本项只更新`refs/heads/main`并创建该标签，不推送其他ref，不建PR、上传附件、改仓库名称/About或环境。
5. 核验远端main和标签（含peeled commit）绑定实际提交，检查该提交的Windows/Ubuntu CI并记录实际结果。未核验前不记录PUBLISHED或CI通过；原本地759+759不替代远端检查。若同快照仅遇网络失败，核对远端后依该确切授权重试；不得强推或移动标签。

原85文件批准不会授权发布计划之外的新内容。对本87文件发布审阅包的明确批准才覆盖上述暂存、提交、标签和这一次特定推送；仍不启动后续步骤或扩展工业资格。
