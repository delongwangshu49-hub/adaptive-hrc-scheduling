# S16 r1 本地成果与确切审阅

2026-10-07；候选 **S16-20261007-r1**。**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。已完成总纲S16限定本地实现及验证，负责人尚未验收本成果或批准确切发布。前置S15 r4发布已补录PR128/LOG164，本步启动PR129/LOG165，本步成果LOG166。沿用main，不建分支/worktree，不调用子代理，不启动S17—S28及S19A/S19B。

## 实现及检查

显式静态整数输入、OR-Tools区间/前序/替代模式与具名设备/人员约束、班窗、固定物流费用及接收拖期/全任务makespan目标已实现。OUT1驻留与有限FG预留延续到实际store/receive结束；B+1及延迟接收有正反例。独立检查器不导入CP-SAT或调用编码器许可谓词，小时反映射另经同口径核验。完整映射、省略条件和整数化误差见[模型说明](../algorithms/cpsat_mapping.md)。

| 实例 | CP-SAT状态 | 独立核算目标 | 完整可行集合条数 |
| --- | --- | --- | --- |
| `TINY_UNARY` | OPTIMAL | 3 | 6 |
| `TINY_PRECEDENCE` | OPTIMAL | 3 | 3 |
| `TINY_BINDINGS` | OPTIMAL | 3 | 11 |
| `TINY_RECEIPT` | OPTIMAL | 8 | 9 |
| `BUFFER_B2` | OPTIMAL | 17 | — |
| `BUFFER_B3` | OPTIMAL | 15 | — |
| `INFEASIBLE_CAPACITY` | INFEASIBLE | — | — |

四个极小例的所有(替代,开始,结束)计划逐条等于独立笛卡尔枚举，最优目标等于手算3/3/3/8。B=2三件READY结束1/3/5，第三件在OUT1等待；许可8后前两件8—9接收完成，第三件最早9—10搬入、10—11接收，最优17。提前一tick搬入或忽略OUT1驻留均被独立检查拒绝。B=3为独立开发域对照最优15，不改变生产缓冲冻结值。

七例×EDD/SPT/FASTEST_MODE共21条同输入参照，18条完整计划独立检查通过，容量无解例三规则均NO_PLAN_FOUND；输入SHA-256逐条与CP-SAT一致。两设备绑定例规则目标5、CP-SAT3，仅说明合成局部选短工时不保证总费用最优，不作为正式A收益。真实零solver预算返回UNKNOWN且无value/bound/gap；回调停止返回FEASIBLE、value3/bound1/gap2/3，即便incumbent碰巧最优也不冒称已证明。截断枚举不标complete。

22项专项通过。统一入口源码 **597项/238.799 s**、从sdist构建的独立wheel **597项/226.410 s**均通过；Ruff/格式、依赖锁/检查、构建和reference组锁导出/摘要安装通过。捕获的242个源/测试/脚本/Schema/样例及环境声明文件在检查后逐项摘要不变。基础wheel另在无OR-Tools的独立环境导入成功，元数据无运行依赖，求解时明确报告缺reference依赖。

原始日志仅本地；机器摘要见[配套JSON](S16_reference_r1.json)，公开合成输入/摘要见[样例](../../examples/cpsat/summary.json)，命令见[S16步骤卡](../steps/S16.md)。本轮未运行新Kit或远端CI；S15本地575项与17对Kit、已发布双平台CI不转记为S16证据。

## 实际失败及限制

首轮20项专项中手算预期忽略WELD_B共享设备，1项失败；完整集合比较当时已经一致，修正手算2→3后保留首轮并复跑。首次完整源码597项中1项失败：新锁文件导致原未执行契约样例dependency_lock_sha256过期；重生成并确认只有该摘要字段改变后重跑通过。常规沙箱进程创建故障与文档路径缺失均保留本地诊断，未据此跳过本步。

只证明显式合成静态整数子域，不是完整建筑、连续时间或动态非线性人因最优值。F/E、cap、恢复、故障/取消、完整材料BOM、任意路径几何和异步反馈双方按映射一同省略；完整S11计划不直接拿来比较，输出PASS_S16_STATIC不伪造S10生产PASS。HR禁用，工业资格/质量UNKNOWN，合成质量/接收、有限USD/AABB/运动学、无单独人工GUI体验记录保持。RP/SC/SH/WV及D01—D06其余冻结边界保持；原720h截尾/疲劳INVALID、WV01 r4首轮180分钟监督失败及全部原失败不重标。solver时限不含编码/独立检查，规则无解不构成不可行证明，未验证Linux新运行或在线实时能力。正式实验、LNS与后续步骤未启动。

## 确切待审集合与拟发布操作

基线提交 `0bba728116797ecece3f6fcbee7109c8bf1624b1`；目标[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)，分支main，拟新不可移动标签step-S16-r1。共 **28文件**：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/cpsat_mapping.md`
- `docs/architecture.md`
- `docs/development.md`
- `docs/roadmap.md`
- `docs/setup.md`
- `docs/steps/S15.md`
- `docs/steps/S16.md`
- `docs/validation/S16_reference_r1.json`
- `docs/validation/S16_reference_r1.md`
- `examples/contracts/run_manifest.json`
- `examples/cpsat/cases.json`
- `examples/cpsat/summary.json`
- `pyproject.toml`
- `scripts/check.py`
- `scripts/run_cpsat_reference.py`
- `src/adaptive_hrc_scheduling/reference/__init__.py`
- `src/adaptive_hrc_scheduling/reference/baselines.py`
- `src/adaptive_hrc_scheduling/reference/cases.py`
- `src/adaptive_hrc_scheduling/reference/checker.py`
- `src/adaptive_hrc_scheduling/reference/cpsat.py`
- `src/adaptive_hrc_scheduling/reference/domain.py`
- `tests/test_cpsat_reference.py`
- `uv.lock`

逐文件原始/规范LF摘要、完整含新增文件差异、获测源码绑定及封包校验留在本地确切审阅包。该包不包含内部总纲、原始会话、参考原件、机器配置/路径、凭据或完整原始日志；公开提示记录仅规范化语义。S15封存审阅包和历史标签保持。

负责人对该快照明确验收及批准发布后，拟仅精确暂存这28路径，复核完整拟推送历史及既有配置署名，创建一个S16提交和annotated step-S16-r1标签，非强制推送main与新标签，核验远端完整树/摘要、分支/标签及Windows/Ubuntu必要CI后才记录PUBLISHED。无新PR/附件/Release、仓库元数据变更或后续步骤启动；获批前不执行上述Git/远端写入。提交自己的最终哈希不预写进当前快照。
