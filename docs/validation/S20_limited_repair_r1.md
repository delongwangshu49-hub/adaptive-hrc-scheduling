# S20 三项P2有限修复验证与r3审阅候选

2026-10-20；PR194 / LOG267—LOG268。候选 **S20-20261020-limited-repair-r3**；**LIMITED_REPAIR_VERIFIED_WITH_LIMITS / OWNER_REVIEW_PENDING / PENDING_FREEZE / NOT_PUBLISHED**。三项P2在本候选中修复并通过下列验证，负责人尚未验收、再冻结或批准本候选发布。原r2接受/冻结、`step-S20-r2`实际发布及失败历史保持。

## 具体修复

依据[事前协议](../experiments/S20_limited_repair_protocol_r1.md)落实[发布后审阅](S20_post_release_audit_r1.md)的有限范围：

| 原发现 | 本候选实际处理 | 当前状态 |
| --- | --- | --- |
| S20-AUDIT-01 | `ModelAnchor.check_prefix`从受权帧重放自身名义决策/内生时间，精确比对完整事件、状态和观察；建候选及独立审计两处调用，重建trace模型观察摘要 | 修复且所列验证通过，待负责人审阅 |
| S20-AUDIT-02 | 审计入口先验设置；要求实际结束以内全部0.25h时隙，包括丢包记录；允许非网格提前结束 | 同上 |
| S20-AUDIT-03 | 保存检查器必须显式接收调用方可信`ProjectionContract`，绑定配置/方法/设置/目标/声明预算，验证方法枚举和候选固定模式 | 同上 |

新增保存格式`S20-PROJECTION-EVIDENCE-r2`含契约副本，必须与独立外部契约一致；旧r1可在提供可信契约且满足全部修订检查时复验。调用方式增加必填关键字`expected=`；研究runner及原消费者已同步，省略参数会拒绝。可信契约来自调用方配置/设计行，不能从待审文件建立。本地旧数据复验采用原冻结r2目录建立契约。

未改变物理输入、提案选择、真实安全盾、观察参数、D目标或尾部积分。r3仅修改1个运行模块、3个研究脚本、1个原测试并新增1个回归测试文件，另新增版本化配置/清单与审阅文档。全部数值设计和行ID保持，r3外层身份绑定新来源；不得把同一稳定行ID的旧运行重新标为r3运行。

## 实际验证

| 检查 | 结果与范围 |
| --- | --- |
| 完整源码测试 | **905项通过，394.761s** |
| 新构建隔离wheel测试 | **905项通过，395.852s** |
| 锁文件、Ruff、格式、sdist/wheel构建、两环境依赖 | 全部通过；209个Python文件格式核验 |
| 新增回归 | 10项；含四方法、旧/新格式、自身名义演进、全丢包、0.625h提前结束正例与未送达事实/读回变造/缺帧/方法及契约错配反例 |
| 原B保存证据 | **20组、32候选**通过修订检查器；先核对原回执及逐运行artifact摘要，可信契约绑定原冻结manifest，非新实际运行 |
| 原承诺前缀 | 2组通过，候选及分数与原件相同；739事件截至25.94728222222222h旧实际前缀内插到26h，非新完整生产或完整历史投影审计 |
| 新注册1h扩展开发 | **23条（D3+B20）**执行/因果/尾部审计通过；B20在线及保存投影重建通过，各次声明预算内 |
| 新旧开发内容比较 | 23条配置/执行快照/决策/尾部的规范JSON内容全部相同，保留数值类型；格式和压缩文件字节不混称相同 |
| 新legacy兼容 | **4条**双审计及预算内，事件/决策解压字节与原r2各方法完全相同 |
| 版本迁移 | 6物理描述符、数值参数和全部正式/开发/tune行与r2相同；4份新JSON显式LF；243项来源运行前后摘要相符 |

下面7个原审阅目标反例文件在修订检查器下全部拒绝；删末帧原已拒绝，其余原绕过路径现被封堵。预算used字段诊断变造另属已说明的检查范围，未冒列为本次拒绝的第八项或独立计时认证。

| 原目标文件/变造 | 实际拒绝原因 |
| --- | --- |
| remove_all_frames | PROJECTION_PUBLIC_SAMPLE_COVERAGE |
| remove_frames_and_set_zero_missing | PROJECTION_SETTINGS_BINDING |
| remove_terminal_frame | PROJECTION_PUBLIC_SAMPLE_COVERAGE |
| alter_method | PROJECTION_METHOD_BINDING |
| invalid_method | PROJECTION_METHOD |
| alter_model_observation_digest | PROJECTION_MODEL_OBSERVATION_BINDING |
| injected-unobserved-fact-projection | PROJECTION_UNAUTHORIZED_MODEL_EVOLUTION |

原审阅/原验证文件保持历史时点；本报告为新增当前回执。本轮原始日志、新运行完整保存资料、运行前后清单与辅助复验脚本在`.local/s20-repair-20261020/`单独封存，旧运行资料仍在原目录；[机器报告](S20_limited_repair_r1.json)登记确切SHA256和逐运行摘要。

## 保留与后续边界

检查前875个既有文件中，仅9项获授权实现/治理文件变化，其余866项保持原字节；18历史M原字节保持、规范内容仍等于HEAD。原r2的43项封包文件、索引及zip摘要核对通过；历史治理字节仍完整保留。源码/文档当前r3身份与旧r2来源分别记录，不称旧来源仍代表修订实现。

正式设计仍636条（A/C64、D12、B560）全部未执行，tune/新Kit/本轮远端CI均0。仅本机Windows源码和隔离wheel检查，无新完整生产链或工业认证。S19B已接受限制、支承通过、工业G2保持。

沿`main`、HEAD保持`154f5b413013b3e428a87d84dfd15a482702097b`；未创建分支/worktree/子代理、未写Git、未发布或启动S21。[r3确切候选](../experiments/S20_freeze_candidate_r3.md)及文件索引供负责人统一审阅，最终接受/冻结与发布分别由负责人决定。
