# S20 前置核查与继承矩阵

2026-10-19；PR189 / LOG259。状态：**PREFLIGHT_COMPLETE_WITH_DESIGN_GAPS**。本步推进规划已批准；最终冻结未批准。

核查在当前 main / `c8c1f74aa26111c6747b87d99f5730a24497f071` 完成，无 Git 写入。先保存 831 个现存文件原字节摘要，再执行只读身份、批准、源码/证据摘要及生成器准入核对。详细本地结果位于 `.local/s20-20261019/preflight.json`；公开结果由本步最终验证摘要承接。

| 前置 | 实际检查与继承结论 |
| --- | --- |
| S19 | 既有实际发布回执：`5a69646fc3d4ed16cca0e6151dffe71b2447dae6` / `step-S19-r2`，`S19-REPAIR-PUBLISH-APPROVAL-001`，限定接受；提交是当前 HEAD 祖先。F1—F3 修复与原轨迹按原报告范围承接，不重标为本步新完整链 |
| S19A | [实际整步接受](../validation/S19A_completion_acceptance_r2.json)，`S19A-COMPLETION-PUBLISH-APPROVAL-004`；既有实际发布回执 `aab9ca848eec6816717f2929a8217f642c3bc2bd` / `step-S19A-r1`，提交是当前 HEAD 祖先 |
| S19B | [实际接受](../validation/S19B_acceptance_r2.json)及 r2 发布回执，828 文件树与 CI 成功属于已发生历史；本轮不重新联网核验。11 项继承证据文件存在且 SHA256 全匹配；最近 228 项来源摘要与当前字节全部一致 |
| 场景/前端影响重验 | 复用 [S19B 证据索引](../validation/S19B_6_repair_evidence_r1.json)中的最终正常完整 CPU/Kit 严格比较及 B+1 比较、独立审计和实际退出证据；保持原运行范围。S20 未改生产/资产/界面，不需要重做 S19B 全矩阵；未声称 S20 新 64 运行已获 Kit 证明 |
| 仿真准入 | 实际调用 `approved_inputs()` 成功；六个 SR-W1/W2 × 1/2/3 产品生成配置通过现有 `validate`。14 类消费者身份由 ResearchProfile 绑定，工业 G2 保持 OPEN/NOT_ESTABLISHED |
| 冻结数值与物流 | 实际配置为 15 人、10 个设备条目（包含 2 工装）、成品 B=2、cap=0.8、原固定布局/路线/工时/负荷。旧文档“8 台设备”不等于 10 条含工装记录冲突。配置摘要、角色/日历、库位与生成器绑定进入候选 |
| 历史改动 | 18 个历史 M 文件逐项 `git hash-object --path` 与 HEAD 对象相同；未重写它们。其余接手治理文件差异保持。本轮原字节保护在收尾再次核对 |
| 工业与已接受限制 | 工业资格不升级；UI/内存/Kit关闭/覆盖限制保留非阻断性质，FORMAL_PERFORMANCE_OPEN。支承没有问题、通过，不再排查 |

冻结来源表的实际提交：S19 `5a69646fc3d4ed16cca0e6151dffe71b2447dae6`；S19A `aab9ca848eec6816717f2929a8217f642c3bc2bd`；S19B `c8c1f74aa26111c6747b87d99f5730a24497f071`。三者祖先关系均已通过本地 Git 只读核对。

## 消费者与能力映射

| 责任 | 当前入口 | S20 结论 |
| --- | --- | --- |
| 域/准入/Schema/生成 | `domain/production.py`、`production_admission.py`、`contracts/production.py`、`schemas/production_simulation/`、`scripts/build_simulation_production.py` | 沿用原批准输入与生成器；候选描述符重建后匹配实际配置摘要 |
| 执行/人员/物流/审计 | `production_backend.py`、`building_human.py`、`production_navigation.py`、`production_checker.py`、`control/production_decisions.py` | 不改执行语义；每新开发运行实际双审计，历史完整链按原身份复用 |
| 四通道共同预算 | `control/simulation_joint_policy.py`、`algorithms/simulation_joint.py` | 四方法有共同接口、调用机会与累计预算；种子为调用序号，不能直接传独立 solver seed |
| 在线策略 | `control/online.py` | S19 OnlinePolicy 有额外缓存/回退/承诺逻辑；不能在四通道比较中给它另加通道却宣称相同算法/预算。主候选明确使用 S18 四通道；S19 在线专项保持既有证据，不删其能力 |
| 观察 | `control/production_loop.py`、`control/production_ledger.py` | 主驱动写明 CURRENT_EVENT_PREFIX_ZERO_DELAY；ledger 可排序/缓冲不代表四通道已支持任意延迟、噪声、丢包实验 |
| Kit 与桌面 | `backends/production_isaac_adapter.py`、`sim/isaac/scene/production_port.py`、桌面源码 | 233 项继承生产/场景/前端/环境文件另列 SHA256；本步不改，不新跑 Kit；开发批处理与桌面展示隔离 |
| 简化参照 | `reference/`、`scripts/run_cpsat_reference.py` | 现有例均为已暴露静态开发见证；不当未见测试集、不与完整生产域混算 |

## 实际缺口及处理

- G01：生产评分为 `(-完成核心活动数, ΣE, maxE)` 字典序，无 D 可扫描权重接口。候选给出具体目标/权重设计，但不修改生产评分。
- G02：SimulationJointProblem 要求送达前缀与实际快照一致且 sampled=received；生产层噪声/延迟/缺失需要受权投影和独立因果审计适配。不能套用旧域 observation.py 冒充生产 B。
- G03：现有算法种子由调用序号产生，驱动外生情景确定。因此主候选采用有限情景全集，模型每格一次，不生成虚假独立种子重复。
- G04：主候选为 S18 四通道方法域，而非 S19 在线策略优越性实验；此范围选择在最终审阅中明确呈交。
- G05：生产完成可早于共同窗口退出。生命周期暴露可直接报告；共同 720h 的逐人尾部负荷不能假设为零，需要统一尾部规则/积分接口才能完成 D 扫描。当前缺口不伪装为 S19B 修复。

G01/G02/G05 使全 A/D/B/C 包尚不满足无条件冻结出口。S20 本轮完成候选设计、检查与开发验证后统一交负责人审阅，保留这三项明确的接口前置；不提前实施生产语义扩展，也不把删去 D/B 当整步完成。具体选项见 [范围决定候选](S20_scope_decisions_r1.md)。
