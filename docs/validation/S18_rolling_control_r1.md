# S18跨时刻条件控制r1：实际执行与独立审阅

2026-10-08；PR142 / LOG184—LOG185；候选 **S18-20261008-rolling-r1**。

**本轮程序VERIFIED_WITH_LIMITS；完整S18 RESEARCH_BLOCKED_G2_OPEN；新快照ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。** PR142已限定验收上一25文件续接成果，原封包保持批准前时点；上轮拟远端操作为空，没有Git发布。本轮继续在现有main/目录工作，不建分支/worktree或子代理。

## 实际新增能力

FrozenTailPolicy在授权观测锚点上运行一次原联合搜索，封存带绝对时刻的DISPATCH/REST/ADVANCE程序。跨时刻Feedback只进入前缀/下一动作安全核验、当前命令版本及实际回执绑定；不进入重搜、修复、分数、接受或缓存。提前实际反馈只唤醒原ADVANCE，同一步继续原截止；错过原定开工、非法下一步或负回执即停止，不改时隙、模式或班组来伪装无状态对照。程序篡改、重复/错绑定回执及未确认先推进拒绝。

可信驱动让actual backend保管隐藏Scenario，policy只读capture授权Feedback与实际区间。Journal从0h记录完整准备及后续每次实际派工、休息、等待和停止；**原S10实际轨迹检查和原S12独立事件/决策重建均保持未改**。它们核对实际事件、具名角色、全部可见状态、人因、版本、时间和回执，不用提案预演代替实际执行。状态流和名义程序始终分开。

完整目标尾段及共同窗口都实际完成且双审计通过，才报告COMPLETED和实际完成时刻/ΣE/max E。完成前故障、取消或调用预算停止保留WINDOW_CENSORED，完整窗口分数null；不拿短窗口暴露当收益。预算恰在实际目标及共同窗口完成时耗尽，双审计通过后记CALL_BUDGET_EXIT_AFTER_COMPLETION；非法实际轨迹/因果缺项报INVALID_TRACE。完成W-B不是完整模块、READY或工业生产完成。

## 九个跨时刻机制

所有用例都是CONDITIONAL_C04_CROSS_TICK_FIXED_PROGRAM_EXECUTION；seed18、2轮、6修复试探/轮、30s协作搜索预算、目标PRODUCT-1.W-B及同一8h尾段窗口。正常与晚卸载使用各自既有明确合成日历；同例H/HR共用日历。原工时/负荷/保护线和实际执行语义不改。

| 用例 | 实际结果 | 审计与解释 |
| --- | --- | --- |
| 正常 | 目标3.9928861h；共同窗口至9.93322h | COMPLETED，执行/因果PASS |
| 无关TEST1故障 | 同正常实际分数及同名义程序；多一次提前唤醒 | COMPLETED，实际故障事件保留，不因无关反馈改计划 |
| 装夹中R1故障 | 2.4928861h停止；QUALITY_HOLD_UNRESOLVED | WINDOW_CENSORED，实际前缀/双审计PASS；J2驻留与R1故障保留，没有换模式或虚构质量 |
| 装夹中取消 | 2.4928861h停止；CANCELLED_OR_QUARANTINED | WINDOW_CENSORED，取消/耗料/历史保持，不算正常完成 |
| 晚卸载固定HR | 7.5h完成 | 加工结束后硬件/单元继续保持，7h实际卸载；双审计PASS |
| 同日历晚卸载固定H | 6.225840079h完成 | HR反而较慢，负结果保留；非正式算法效果 |
| 等待卸载时R1故障 | 7h停止；RESOURCE_FAILED:R1 | WINDOW_CENSORED，R1/FIX-J2/J2保持，未伪释放或实际卸载 |
| 仅一次调用 | 1.93322h停止；CALL_BUDGET | WINDOW_CENSORED，完整窗口分数null |
| 调用预算恰达实际完成 | 同正常分数与共同窗口 | COMPLETED / CALL_BUDGET_EXIT_AFTER_COMPLETION，实际事件和双审计支持，不误标截尾 |

九份完整实际轨迹/观测/决策/请求均留本地，重新从保存JSON解码后独立执行/因果复核再次PASS。公开[机器摘要](../../examples/joint_modes/rolling.json)只给结果、计数与摘要，不带完整原始日志；[验证JSON](S18_rolling_control_r1.json)列同证据。入口`scripts/run_joint_rolling.py --output <摘要路径> --raw-output <本地原始目录>`。方法见[跨时刻控制](../algorithms/joint_modes.md#pr142跨时刻无更新条件执行)。

## 检查、失败和历史保护

最终 **源码724项/242.896s、隔离wheel724项/240.697s** 均通过；本步65专项（上一50+新增15）包含在两轮。锁依赖、Ruff、153文件格式、依赖相容、sdist→wheel、锁定reference摘要安装均通过。152项Python输入在测试前/后摘要稳定，上一版148项原字节保持，仅新增4项Python文件。**213冻结文件摘要保持**；原S17/S18旧实现和例子未改，本轮没有额外把旧参考例重跑当新成果。

原17文件及25文件zip/manifest保持原封签摘要；25文件批准记录单独保存，未修改旧封包来补写批准。新32文件不能按旧摘要发布。初版12项有1条错误的“装夹失败应仍锁硬件”断言；实际C04失败按既有语义释放相关资源但保留J2/失败与质量阻断，测试修正，执行器未改。初lint及该失败记录保留。

首轮源码/隔离wheel各723项通过；随后增加预算恰达实际完成回归，旧驱动复现误标WINDOW_CENSORED。只修正实际完成分类，最终15专项与724/724通过；首轮成功、失败回归、原八份轨迹和重跑九份均保留。原S15截尾/INVALID/监督失败、S16反例、S17失败/WINDOW_CENSORED、S18原无收益/反向及早期失败均不重标。

## 剩余边界与准确出口

本轮完成的是条件C04无更新基线的跨时刻实际执行与审计。当前生产HR滚动联合自适应方法、共同域无更新生产对照、完整未来工厂可行性及Isaac HR阶段/位置读回**尚未实现/验证**；没有把旧C04底框尾段替代现行S15生产物流。上一现行S15固定WALK结果保持归属，没有新Kit或完整模块链。

Q01—Q06共同输出、接头/WPS、程序/夹具、人员/隔离、检验和合法停点证据仍缺。PR141自主判断和PR142批准均不构成G2资格；实际HR禁用、A BLOCKED、门后[M01/M02设计](../model/S18_production_mapping_r1.md)及适用门保持。完整S18及S19交接仍BLOCKED，不删除A或更换对象，不改时间/负荷制造优势。

RP/SC/SH/WV及其余D01—D06、工业UNKNOWN、合成质量/接收、有限几何/运动学和GUI体验未单独验收保持。没有资产下载、环境升级、正式A/D实验或新远端CI。负责人贡献为有限成果验收和续接授权，AI辅助实现/验证/治理，不虚构人工编码或实验。

## 确切32文件与发布边界

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/joint_modes.md`
- `docs/architecture.md`
- `docs/model/S18_production_mapping_r1.md`
- `docs/model/S18_qualification_decisions_r1.md`
- `docs/roadmap.md`
- `docs/steps/S17.md`
- `docs/steps/S18.md`
- `docs/validation/S18_continuation_r1.json`
- `docs/validation/S18_continuation_r1.md`
- `docs/validation/S18_joint_branches_r1.json`
- `docs/validation/S18_joint_branches_r1.md`
- `docs/validation/S18_rolling_control_r1.json`
- `docs/validation/S18_rolling_control_r1.md`
- `examples/joint_modes/continuation.json`
- `examples/joint_modes/mechanisms.json`
- `examples/joint_modes/rolling.json`
- `scripts/run_joint_continuation.py`
- `scripts/run_joint_mechanisms.py`
- `scripts/run_joint_rolling.py`
- `src/adaptive_hrc_scheduling/algorithms/joint_lns.py`
- `src/adaptive_hrc_scheduling/algorithms/joint_production.py`
- `src/adaptive_hrc_scheduling/algorithms/joint_rolling.py`
- `src/adaptive_hrc_scheduling/control/joint_rolling_loop.py`
- `tests/test_joint_decisions.py`
- `tests/test_joint_frozen_information.py`
- `tests/test_joint_production_boundary.py`
- `tests/test_joint_rolling.py`

逐文件SHA-256及相对实际HEAD的完整差异（含未跟踪文件）保存在本地manifest/complete.diff/封签包，原两个包保持。目标为[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)的main，基线62c1c5393cb715b8089a93ee7ec658a0eb0e571d，拟标签`step-S18-rolling-r1`仅本轮有限程序身份。**拟远端操作=[]，未暂存/提交/标签/推送/PR/附件。** 新成果验收及任何确切发布另审；新发布需针对本32文件摘要明确批准后才精确暂存、复核完整历史/署名、单提交+新annotated标签、非强推main/新标签，并核验远端树/摘要/对象及双平台CI。S19—S28/S19A/S19B未启动。
