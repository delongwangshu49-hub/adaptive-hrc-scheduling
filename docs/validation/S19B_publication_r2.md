# S19B有限修复：限定接受与发布批准 r2

2026-10-16；PR187 / LOG257。负责人在审阅剩余问题对项目运行的影响后，决定略过继续修复并批准上传。决定 **S19B-PUBLISH-APPROVAL-002**，状态 **ACCEPTED_WITH_DOCUMENTED_LIMITS / APPROVED_FOR_PUBLICATION**。

接受已封存的 `S19B-20261016-limited-repair-r1`（374成员、1,895,801字节），ZIP SHA256 `d1a6aef86f9f24a7ea4e38dc3b359fe048974f278cd2da82cf9981ff6f28b9df`。原[审阅报告](S19B_6_repair_r1.md)保持封存时点，其待审/未发布状态由本次[批准记录](S19B_acceptance_r2.json)承接，不改写历史证据。

六项逻辑修复、关联显示重连隔离、CPU边界及短负载协议修订按披露范围接受。34桌面回归、11组真实控制、源码/隔离wheel各862项及8对严格比较通过；[证据摘要与摘要索引](S19B_6_repair_evidence_r1.json)可公开核对，原始轨迹和完整失败日志保留本地。

英语首回调321ms、零预算首对内存增量490MiB、Kit关闭挂起及新鲜度/覆盖限制作为**负责人已接受、此次发布不阻断的限制**保留；本轮不继续修复。性能配对1/7满足完整协议，FORMAL_PERFORMANCE_OPEN，不将批准上传改写为全部性能通过。支承为**没有问题、通过**，不属于剩余问题，后续不再反复。工业G2及S20—S28边界保持。

本次只有必要治理、README状态和证据摘要追加；修复源码/测试/协议及原审阅报告与获批包相同。新增交接/治理中的原始指令和机器路径仅作公开规范化，不改变决定内容；原字节仍在旧封包。原生产、几何和数值不变，22份旧封包不变。

沿现有main，父提交 `afced4c239ad82955b2649f5a001f0affda601b7`；单提交、新注释标签 `step-S19B-r2`，向既有origin原子推送main与标签。不强推或移动旧标签。逐文件原字节/Git摘要、完整差异、实际提交/远端树/CI回执另存 `.local/s19b-r2-publication-20261016/`；不预写成功，不为回填自身哈希追加提交。

## 确切发布文件

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `desktop/s19b/src/s19b_desktop/app.py`
- `desktop/s19b/src/s19b_desktop/i18n.py`
- `desktop/s19b/src/s19b_desktop/review.py`
- `desktop/s19b/tests/test_repairs.py`
- `docs/sim/S19B_6_repair_protocol_r1.md`
- `docs/sim/S19B_6_repair_validation_addendum_r1.md`
- `docs/steps/S19B.md`
- `docs/steps/S19B_6_handoff.md`
- `docs/validation/S19B_6_repair_evidence_r1.json`
- `docs/validation/S19B_6_repair_r1.md`
- `docs/validation/S19B_acceptance_r2.json`
- `docs/validation/S19B_publication_r2.md`
- `scripts/measure_s19b_ui.py`
- `scripts/measure_s19b_worker.py`
- `scripts/run_s19b_prototype.py`
- `scripts/verify_s19b_b2_ui.py`
- `scripts/verify_s19b_repair_replay.py`
