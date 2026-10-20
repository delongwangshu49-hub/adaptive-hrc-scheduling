# S20冻结成果：发布批准与确切范围 r1

2026-10-20；PR192 / LOG264；决定 **S20-PUBLISH-APPROVAL-001**。

负责人在[S20 r2限定验收与实际冻结](../experiments/S20_freeze_r2.md)后明确批准发布。状态为 **ACCEPTED_WITH_DOCUMENTED_LIMITS / FROZEN / APPROVED_FOR_PUBLICATION**；实际远端与CI回执另留本地，不预记发布或检查通过。

接受对象为`S20-20261019-design-r2`，43项候选封包SHA256为`3302b7f6d054e3e8040ca426b4c60ec28d7b157dac1e2df89d2b46fe70883750`，原索引SHA256为`9923e8a2bb6d68fa73b17de161664f66371b1b9347318f41ab624cab946f6dd4`。本次保留冻结协议、配置、全部输入、242项来源与原实际验证字节，追加发布治理、冻结决定、README入口及S19B卡中既有的PR188交接导航，并将治理历史中的5处工作区路径规范化为当前仓库，原文仍保存在原封包和发布前快照；原候选/回执内待审或未发布值保留其历史时点。

CPU研究域内三项扩展、有限确定性设计和既有开发验证随包发布；源码/隔离wheel各895项是此前实际本地结果，远端双平台结果以本次CI为准。正式设计636条（A/C 64、D 12、B 560）全部未执行，执行锁关闭；不以开发验证或本次发布声称方法优势、完整新增生产/Kit链或工业资格。原失败、S19B已接受限制、支承通过与工业G2边界保持，S21不启动。

目标为既有`origin`仓库`delongwangshu49-hub/adaptive-hrc-scheduling`的`main`，父提交`c8c1f74aa26111c6747b87d99f5730a24497f071`。创建单个提交及新注释标签`step-S20-r1`，原子推送main与标签；不强推、不移动旧标签、不创建分支/worktree/子代理。原始轨迹、完整日志与本地封包不上传。逐文件摘要、完整差异、实际提交、远端树及CI回执留在`.local/s20-publication-20261020/`；不为回填自身哈希追加上传。

## 确切发布文件

机器可读[批准范围](S20_publication_r1.json)与以下清单一致：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/experiments/S20_candidate_files_r1.json`
- `docs/experiments/S20_candidate_files_r2.json`
- `docs/experiments/S20_execution_plan_r1.md`
- `docs/experiments/S20_extension_approval_r1.json`
- `docs/experiments/S20_extension_implementation_r2.md`
- `docs/experiments/S20_freeze_candidate_r1.md`
- `docs/experiments/S20_freeze_candidate_r2.md`
- `docs/experiments/S20_freeze_r2.json`
- `docs/experiments/S20_freeze_r2.md`
- `docs/experiments/S20_parameter_register_r1.md`
- `docs/experiments/S20_parameter_register_r2.md`
- `docs/experiments/S20_preflight_r1.md`
- `docs/experiments/S20_scope_decisions_r1.md`
- `docs/experiments/S20_scope_decisions_r2.md`
- `docs/experiments/analysis_plan.md`
- `docs/experiments/analysis_plan_r2.md`
- `docs/experiments/protocol.md`
- `docs/experiments/protocol_r2.md`
- `docs/steps/S19B.md`
- `docs/steps/S20.md`
- `docs/steps/S20_handoff.md`
- `docs/validation/S20_design_validation_r1.json`
- `docs/validation/S20_design_validation_r1.md`
- `docs/validation/S20_extension_validation_r2.json`
- `docs/validation/S20_extension_validation_r2.md`
- `docs/validation/S20_publication_r1.json`
- `docs/validation/S20_publication_r1.md`
- `experiments/configs/s20_r1.json`
- `experiments/configs/s20_r2.json`
- `experiments/manifests/s20_extensions_r2.json`
- `experiments/manifests/s20_r1.json`
- `experiments/manifests/s20_r2.json`
- `experiments/manifests/s20_sources_r1.json`
- `experiments/manifests/s20_sources_r2.json`
- `scripts/run_s20_development.py`
- `scripts/run_s20_extension_development.py`
- `scripts/s20_design.py`
- `scripts/s20_extension_design.py`
- `src/adaptive_hrc_scheduling/algorithms/simulation_joint.py`
- `src/adaptive_hrc_scheduling/control/research_projection.py`
- `src/adaptive_hrc_scheduling/control/simulation_joint_policy.py`
- `src/adaptive_hrc_scheduling/research_objective.py`
- `src/adaptive_hrc_scheduling/research_tail.py`
- `tests/test_s20_design.py`
- `tests/test_s20_extensions.py`
