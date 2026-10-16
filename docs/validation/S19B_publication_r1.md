# S19B累计成果：限定验收与确切发布 r1

2026-10-16；PR184 / LOG253。负责人原文：“批准验收，允许发布，你指出的问题留待后续修复”。决定 **S19B-PUBLISH-APPROVAL-001**：S19B累计成果 **ACCEPTED_WITH_DOCUMENTED_LIMITS / APPROVED_FOR_PUBLICATION**。

## 验收范围与保留问题

接受140文件`S19B-20261015-fifth-step-r1`，ZIP SHA256 `05ccdca76899abaa23461c0b6f51daf413b93538ff2fec909cbfa68bdcf87ed8`，清单SHA256 `e015e78d1a63782913808bd9dc5f558b9e70ef5c8becbd4fa7554aa61c9ce9ad`。原[累计审阅](S19B_5_r1.md)、[机器结果](S19B_5_r1.json)、全部旧包和失败保持封存时点，当前验收以本页及[批准回执](S19B_acceptance_r1.json)为准。负责人作出验收决定不等于新增负责人人工操作测试。

15条生产、11对严格语义比较、30项审计、10次回放，以及布局修复后的补充验证按原范围接受。最终源码/隔离wheel各862项、24桌面契约、8组真实Qt/CPU/Kit检查及实际退出0保持；本轮只改治理，不重复运行长链。

**FORMAL_PERFORMANCE_OPEN保持。** 7/8原性能配对未满足或缺样；启动轮询峰值最高约1.277秒、短例样本不足/CPU边界误差及有限覆盖留待后续修复。布局补测仍有轮询超限；不把验收决定改写为技术问题关闭、全部性能达标或方法优势。三类支承技术OPEN/演示不阻断、工业G2 OPEN、2.4m、0.02h/对、原生产/观察/预算、RC关闭限制及未开放控制保持，S20—S28另审。

## 发布边界及实际回执

仅原140文件加必要验收治理：实现/测试/资产/协议/原审阅和3717证据索引字节保持；修改成员列于批准JSON。保持既有main，父提交`aab9ca848eec6816717f2929a8217f642c3bc2bd`；单提交、新注释标签`step-S19B-r1`，向origin原子推送main与标签。不强推、不移动旧标签、不建分支/worktree/子代理。全部文件原字节和Git归一化摘要、差异及发布封包保存在`.local/s19b-r1-publication-20261016/`。

本页记录实际批准与待执行发布，不预写推送或CI成功。提交后实际提交/远端引用/完整Git树核对和双平台CI日志另存该本地目录；不为回填自身哈希追加第二个提交。

## 确切发布文件

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `desktop/s19b/README.md`
- `desktop/s19b/pyproject.toml`
- `desktop/s19b/src/s19b_desktop/__init__.py`
- `desktop/s19b/src/s19b_desktop/app.py`
- `desktop/s19b/src/s19b_desktop/control.py`
- `desktop/s19b/src/s19b_desktop/embedded.py`
- `desktop/s19b/src/s19b_desktop/i18n.py`
- `desktop/s19b/src/s19b_desktop/model.py`
- `desktop/s19b/src/s19b_desktop/review.py`
- `desktop/s19b/tests/test_control.py`
- `desktop/s19b/tests/test_model.py`
- `desktop/s19b/tests/test_review.py`
- `desktop/s19b/uv.lock`
- `docs/PROJECT_CHARTER.md`
- `docs/roadmap.md`
- `docs/sim/S19B_5_offline_cache_addendum_r1.md`
- `docs/sim/S19B_5_offline_partition_addendum_r1.md`
- `docs/sim/S19B_5_protocol_r1.md`
- `docs/sim/S19B_5_protocol_r2.md`
- `docs/sim/S19B_5_protocol_r3.md`
- `docs/sim/S19B_5_protocol_r4.md`
- `docs/sim/S19B_B2_control_contract_r1.md`
- `docs/sim/S19B_B3_protocol_r1.md`
- `docs/sim/S19B_frontend_options_r1.md`
- `docs/sim/S19B_frontend_options_r2.md`
- `docs/sim/S19B_scene_support_issue_r1.md`
- `docs/sim/emergency_scene_correction_proposal_r1.md`
- `docs/sim/emergency_scene_investigation_r1.md`
- `docs/sim/emergency_scene_layout_connections_r1.json`
- `docs/sim/emergency_scene_limited_repair_r2.md`
- `docs/sim/emergency_scene_proposed_geometry_r1.json`
- `docs/sim/images/emergency-scene/r1/cart-frame.png`
- `docs/sim/images/emergency-scene/r1/cut-feed-material.png`
- `docs/sim/images/emergency-scene/r1/fixed-supports.png`
- `docs/sim/images/emergency-scene/r1/fixture-j2.png`
- `docs/sim/images/emergency-scene/r1/initial-overview.png`
- `docs/sim/images/emergency-scene/r1/offsite-ghosts.png`
- `docs/sim/images/emergency-scene/r1/p1-boot-deck.png`
- `docs/sim/images/emergency-scene/r1/parking-supports.png`
- `docs/sim/images/emergency-scene/r1/robot-base.png`
- `docs/sim/images/emergency-scene/r1/test-frame.png`
- `docs/sim/images/emergency-scene/r2/final.png`
- `docs/sim/images/emergency-scene/r2/initial.png`
- `docs/sim/images/emergency-scene/r2/mid-production.png`
- `docs/sim/images/s19b/b1-feedback-r1/actual-kit-frame.png`
- `docs/sim/images/s19b/b1-feedback-r1/actual-located-scene.png`
- `docs/sim/images/s19b/b1-feedback-r1/dark-kit-layout-en.png`
- `docs/sim/images/s19b/b1-feedback-r1/dark-kit-layout-zh.png`
- `docs/sim/images/s19b/b1-feedback-r1/dark-workbench-zh.png`
- `docs/sim/images/s19b/b1-feedback-r1/next-trial-layout.png`
- `docs/sim/images/s19b/b1-feedback-r1/owner-native-desktop.png`
- `docs/sim/images/s19b/b1-r1/b1-kit-location-en.png`
- `docs/sim/images/s19b/b1-r1/b1-kit-location-zh.png`
- `docs/sim/images/s19b/b1-r1/cpu-checkpoint-en.png`
- `docs/sim/images/s19b/b1-r1/history-zh.png`
- `docs/sim/images/s19b/b1-r1/kit-ui-frame.png`
- `docs/sim/images/s19b/b1-r1/location-scene.png`
- `docs/sim/images/s19b/b2-r1/owner-native-desktop.png`
- `docs/sim/images/s19b/b2-r1/owner-stopped-desktop.png`
- `docs/sim/images/s19b/b2-r2/owner-initializing-unknown.png`
- `docs/sim/images/s19b/b2-r2/owner-native-desktop.png`
- `docs/sim/images/s19b/b2-r2/owner-stopped-desktop.png`
- `docs/sim/images/s19b/b3-r1/camera-white-failure.png`
- `docs/sim/images/s19b/b3-r1/final-complete-en.png`
- `docs/sim/images/s19b/b3-r1/final-complete-zh.png`
- `docs/sim/images/s19b/b3-r1/final-confirm-zh.png`
- `docs/sim/images/s19b/b3-r1/final-history-en.png`
- `docs/sim/images/s19b/b3-r1/final-live-zh.png`
- `docs/sim/images/s19b/b3-r1/final-request-en.png`
- `docs/sim/images/s19b/b3-r1/live-fork-en.png`
- `docs/sim/images/s19b/closeout-r1/layout-en-scroll-to-start.png`
- `docs/sim/images/s19b/closeout-r1/layout-zh-top.png`
- `docs/sim/images/s19b/monochrome-r1/readonly-preview.png`
- `docs/sim/images/s19b/monochrome-r1/workbench-en.png`
- `docs/sim/images/s19b/monochrome-r1/workbench-zh.png`
- `docs/sim/images/s19b/prototype-r1/history-zh.png`
- `docs/sim/images/s19b/prototype-r1/kit-checkpoint-en.png`
- `docs/sim/images/s19b/prototype-r1/production-scene.png`
- `docs/sim/images/s19b/prototype-r1/workbench-en.png`
- `docs/sim/images/s19b/prototype-r1/workbench-zh.png`
- `docs/sim/images/s19b/prototype-r2-embedded/history-zh.png`
- `docs/sim/images/s19b/prototype-r2-embedded/kit-ui-frame.png`
- `docs/sim/images/s19b/prototype-r2-embedded/production-scene.png`
- `docs/sim/images/s19b/prototype-r2-embedded/workbench-en.png`
- `docs/sim/images/s19b/prototype-r2-embedded/workbench-zh.png`
- `docs/steps/S19A.md`
- `docs/steps/S19B.md`
- `docs/steps/S19B_2_handoff.md`
- `docs/steps/S19B_3_handoff.md`
- `docs/steps/S19B_4_handoff.md`
- `docs/steps/S19B_5_handoff.md`
- `docs/steps/emergency_scene_correction_handoff.md`
- `docs/steps/emergency_scene_to_S19B_2_handoff_r1.md`
- `docs/validation/S19B_5_evidence_r1.json`
- `docs/validation/S19B_5_r1.json`
- `docs/validation/S19B_5_r1.md`
- `docs/validation/S19B_B1_feedback_r1.json`
- `docs/validation/S19B_B1_feedback_r1.md`
- `docs/validation/S19B_B1_r1.json`
- `docs/validation/S19B_B1_r1.md`
- `docs/validation/S19B_B2_r1.json`
- `docs/validation/S19B_B2_r1.md`
- `docs/validation/S19B_B2_r2.json`
- `docs/validation/S19B_B2_r2.md`
- `docs/validation/S19B_B3_evidence_r1.json`
- `docs/validation/S19B_B3_r1.json`
- `docs/validation/S19B_B3_r1.md`
- `docs/validation/S19B_acceptance_r1.json`
- `docs/validation/S19B_monochrome_ui_r1.md`
- `docs/validation/S19B_prototype_r1.json`
- `docs/validation/S19B_prototype_r1.md`
- `docs/validation/S19B_prototype_r2.json`
- `docs/validation/S19B_prototype_r2.md`
- `docs/validation/S19B_publication_r1.md`
- `docs/validation/emergency_scene_investigation_r1.json`
- `docs/validation/emergency_scene_limited_repair_geometry_r2.json`
- `docs/validation/emergency_scene_limited_repair_parity_r2.json`
- `docs/validation/emergency_scene_limited_repair_r2.json`
- `docs/validation/emergency_scene_limited_repair_remaining_r2.json`
- `scripts/compare_production_chain.py`
- `scripts/inspect_s19b_scene_supports.py`
- `scripts/launch_s19b_kit.ps1`
- `scripts/measure_s19b_kit.ps1`
- `scripts/measure_s19b_ui.py`
- `scripts/measure_s19b_worker.py`
- `scripts/review_limited_model_repair.py`
- `scripts/run_s19b_prototype.py`
- `scripts/start_s19b.ps1`
- `scripts/verify_production_chain.py`
- `scripts/verify_s19b_b2_ui.py`
- `scripts/verify_s19b_b3_replay.py`
- `scripts/verify_s19b_prototype_ui.py`
- `sim/isaac/s19b_viewport.kit`
- `sim/isaac/scene/production_port.py`
- `sim/isaac/scene/scene_correction.py`
- `sim/isaac/scene/target_scene.py`
- `src/adaptive_hrc_scheduling/control/production_loop.py`
- `tests/test_orderly_stop.py`
