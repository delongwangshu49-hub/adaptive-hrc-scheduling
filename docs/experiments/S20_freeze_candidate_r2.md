# S20 r2 冻结候选

2026-10-19；PR190。候选 **S20-20261019-design-r2**；当前 **IMPLEMENTATION_AND_DEVELOPMENT_VALIDATION_COMPLETE_WITH_LIMITS / OWNER_REVIEW_PENDING / PENDING_FREEZE**。源码与隔离wheel各895项通过；最终23条扩展开发运行、4条legacy兼容对照及补充保存证据核验通过。负责人验收/冻结待明确决定。

## 实际范围与入口

依据r1候选推荐和负责人批准，已补齐D评分、共同窗口尾部评价及B受权观察/因果审计接口。研究域仍为S18-SIM-A1、CPU批处理/前端关、既有产品与物理配方。原r1文件和21文件封包保留，不覆盖历史结果或已接受限制。

| 产物 | 当前入口 |
| --- | --- |
| 完整协议与失败/预算规则 | [协议r2](protocol_r2.md)，承接其中明确引用的r1共同规则 |
| 指标、分母、图表与不确定性 | [分析计划r2](analysis_plan_r2.md) |
| 参数与批准落实 | [参数r2](S20_parameter_register_r2.md)、[范围落实r2](S20_scope_decisions_r2.md) |
| 输入与来源 | [配置](../../experiments/configs/s20_r2.json)、[A/C清单](../../experiments/manifests/s20_r2.json)、[扩展清单](../../experiments/manifests/s20_extensions_r2.json)、[242项来源摘要](../../experiments/manifests/s20_sources_r2.json) |
| 实现责任与证据边界 | [三项扩展实现](S20_extension_implementation_r2.md) |
| 最终实际验证与确切摘要 | [验证报告](../validation/S20_extension_validation_r2.md)、[候选文件摘要](S20_candidate_files_r2.json) |

## r1→r2的实质变化

- D新增显式D_WEIGHTED_r1，保留legacy默认；共同窗人因在接收后通过源绑定REST/OFF_SHIFT派生评价账补齐，不改写实际事件，未完成不补零。
- B新增来源/送达/丢包/噪声绑定、假想模型后缀、真实安全盾和独立保存证据重建。首次缺包保持UNKNOWN；拒绝不额外重搜，无更新控制保留首锚点。
- B增加同0.25h公共采样接口的16条零扰动基线，消除与A逐决策更新机制的混淆。正式清单由620修正为 **636条：A/C 64、D 12、B 560**；所有正式行保持未运行。
- 扩展只接入CPU研究路径；原Kit/桌面能力及旧完整链按原来源保留，没有给新增功能标新Kit通过。原S19B问题不重启修复，支承通过决定保持。

## 最终审阅事项

本版拟冻结：r2协议/分析/参数、6个原配方描述符、A/C及D/B全部正式输入行、242项源码/资产/工具摘要、目标/观察/尾部接口版本、实际开发验证与所有明确限制。采用确定性有限设计和预定有限种子集合，不作随机工厂总体或工业资格推断。

最终状态由负责人针对本版确切摘要明确ACCEPTED/FROZEN后记录。S21实施和发布继续分别授权；本轮目标为既有仓库/main，标签为空，远端操作为空。无分支/worktree/子代理，不暂存、提交、推送或发布。

本版三项接口缺口已在获批CPU研究域内补齐，所列适用S20开发出口已有实际证据。建议负责人按本版范围限定接受并冻结；本地实现/验证通过不替代该决定，也不构成正式实验完成或方法优势。
