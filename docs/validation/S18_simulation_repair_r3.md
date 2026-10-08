# S18 simulation r3：两项修复成果与确切上传审阅

2026-10-08；PR152 / LOG201。候选 **S18-20261008-simulation-repair-r3** 为 **VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。F1/F2在本次受测调度仿真范围内完成修复；负责人确认继续仿真研究，工业G2保持OPEN/NOT_ESTABLISHED。本轮沿用现有main，未创建分支/worktree、调用子代理或执行Git写入。

## 修复及实际证据

| 项目 | 修复后的行为 | 验证 |
| --- | --- | --- |
| F1 班组与失败预算 | CREW依据保留模式生成；仅MODE变化时只联动确实改变模式的班组。局部修复异常成为有原因的失败试次，搜索保留合法初解；异常搜索出口按实际开始的工作记账 | CREW-only 40组模式/种子组合、MODE联动、不相关班组保持、失败后下一试次、失败保留初解和跨调用预算均通过；原真实前缀seed1通过，seed2实际策略保留候选且记1迭代/2试次 |
| F2 声明与执行绑定 | 独立核对实际核心命令的模式、班组、最早开始及交班接班人；既有承诺不可被元数据改写。每次重建观察复核派工选择 | 原班组/时段反例均拒绝；顺序/休息篡改、隐藏多命令、非有限时段拒绝；合法原轨迹、保持优先序的等价声明、实际停点交班和承诺模式控制通过 |
| C1 研究域衔接 | 按负责人明确决定，后续规划承接获批仿真域；资格前置在该域内落实为可追溯仿真准入及验证出口 | 总纲新增PR152范围说明；工业G2不改PASS，各后续步骤仍另行启动/验收/发布 |

ORDER是派工优先级，允许因不可行、物流或安全准备而产生不同于全序的实际先后；保持相同选择的等价优先级可以接受。REST是依序尝试、启动后消耗的休息请求，窗口末未能启动的请求可以保留，保护性休息仍由原规则决定。顺序/休息选择复核复用确定性派工器；模式/班组/时段/交班直接绑定与S10、因果审计分别执行，不声称派工器与复核器完全独立实现。物流辅助角色不套用核心工序班组声明。

新增 **15项回归** 通过；完整源码 **774项/421.488s**、隔离wheel **774项/419.195s** 通过。Ruff、格式、锁/依赖检查、构建和安装来源流程通过；24项旧生成资产及新仿真Schema/实例一致性通过。受测170工程输入摘要封存，原配置/数值/批准输入及历史证据保持。

四通道原 **16个完整候选** 经新核验逐一通过，分数与原保存记录一致；原ADAPTIVE_JOINT和FIXED_H反例前缀分别作为合法控制。新测试从公开配置实际执行到共同前缀，再验证2h后缀及合法停点交班，不依赖私有日志或伪造完成状态。完整原8h候选复验使用本地历史存档，未将其重标为新运行效果。

原seed2真实策略诊断使用300s单次预算，实际墙钟和核验成本见[机器结果](S18_simulation_repair_r3.json)；历史120s预算、已发布结果和冻结数值不变。增加逐决策复核会增加计算成本，S19性能尚未验证。本轮未新跑Kit、双后端完整生产链或正式A/D；执行内核、适配器及场景未改，原完整链仍只证明原捕获源码。初轮测试范围误套及历史候选误拒绝日志保留，最终修正后通过。

## 复现

```powershell
uv run --locked python -m unittest discover -s tests -p "test_simulation_joint_repair.py" -v
uv run --locked python scripts/build_production_contracts.py --check
uv run --locked python scripts/build_simulation_production.py --check
uv run --locked python scripts/check.py
```

旧[发布后审阅](S18_post_release_audit_r1.md)、[G2证据研究](../research/S18_industrial_g2_evidence_r1.md)和[修复前复检](S18_g2_followup_recheck_r1.md)原文/字节保留，按其历史时点解释；本报告给出当前修复状态。工业资格、符号焊接/合成质量接收、有限共同窗口及未完成正式实验等限制继续有效。负责人贡献为范围确认和修复授权，AI辅助实现、核验和治理；未发生新成果人工验收或上传批准。

## 确切待上传内容和拟操作

目标为[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)，分支 **main**，基线 `cd21aa0a26e53585b9bf8cc3a7b7b6900c428ac1`。远端main已只读核对与基线一致，本地无额外未推送提交；旧r1/r2标签保持。拟新增不可移动的annotated标签 **step-S18-simulation-r3**，单个提交标题 `fix: bind S18 simulation candidates and preserve repair budgets`。

共 **21文件**，包含尚未发布的既有审阅/G2成果及本次修复，均列入完整差异和逐文件SHA-256清单：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/research/S18_industrial_g2_evidence_r1.md`
- `docs/research/S18_industrial_g2_matrix_r1.tsv`
- `docs/research/S18_industrial_g2_sources_r1.tsv`
- `docs/steps/S18.md`
- `docs/steps/S18_4_handoff.md`
- `docs/validation/S18_completion_exits.md`
- `docs/validation/S18_g2_followup_recheck_r1.json`
- `docs/validation/S18_g2_followup_recheck_r1.md`
- `docs/validation/S18_industrial_g2_review_r1.json`
- `docs/validation/S18_post_release_audit_r1.json`
- `docs/validation/S18_post_release_audit_r1.md`
- `docs/validation/S18_simulation_repair_r3.json`
- `docs/validation/S18_simulation_repair_r3.md`
- `src/adaptive_hrc_scheduling/algorithms/simulation_joint.py`
- `src/adaptive_hrc_scheduling/control/simulation_joint_policy.py`
- `tests/test_simulation_joint_repair.py`

本地审阅ZIP包含这21个目标文件及review/manifest.json、review/full.diff；review目录仅用于审阅，不加入仓库。包不含原始会话、完整日志、参考PDF/图片、内部资料或机器配置；没有附件/Release/PR上传计划。完整差异以当前HEAD为基线，覆盖所有新增文件；另保留本次开始前的工作区副本，已有未提交成果不被覆盖。

待负责人针对该快照明确验收并批准后，拟仅精确暂存清单21路径，核对Git规范化内容和现有仓库署名，创建一个提交及上述annotated新标签，执行非强制 `git push --atomic origin main step-S18-simulation-r3`。随后核验远端完整树/文件摘要、分支/标签及两平台必需CI；均通过后才记PUBLISHED。远端若发生分叉或目标/内容实质变化，重新形成具体审阅，不强推。当前未暂存、提交、建标签或推送，后续步骤仍未启动。
