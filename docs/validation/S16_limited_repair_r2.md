# S16 r2 有限修复成果与确切审阅

2026-10-07；PR132 / LOG170，候选 **S16-20261007-r2**。**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。已完成负责人批准的F1—F3及C1必要追溯、回归和治理；新成果尚待负责人验收及确切发布批准。现有main/目录保持，无分支/worktree或子代理，S17—S28及S19A/S19B未启动。

原r1实际限定验收/批准/发布保持：提交 `f8ea47cbac96e9663f35dae5a6434693d34f648c`、annotated标签step-S16-r1，双平台各源码/隔离wheel597项，434树项/28文件远端摘要一致。实际回执与发布后审阅已在PR130—PR131、LOG167—LOG168补录；本轮封包含这部分先前未发布治理，不为补录单独上传。原[发布后审阅](S16_post_release_audit_r1.md)、失败、源码及封包原样保留历史意义，不能将r2修复成功反写为r1没有缺陷。

## 有限修复与证据

| 项 | 最终行为 | 反例/控制与结果 |
| --- | --- | --- |
| F1 网格类型/反映射 | tick_h只接受正有理字符串；验证、quantize及逆映射共用精确解析 | 数值0.1、整数1、布尔、Decimal/Fraction对象拒绝；字符串0.1/1/10/0.10完整小时反映射通过 |
| F2 原子资格与序列形状 | JSON对象/数组先验证，再转换不可变tuple；资格/前序保持原子字符串，角色/需求/班窗为二元素数组 | 标量WELD不再被拆成W/E/L/D；前序AB不拆成两ID；角色行WP不拆成资格/人员；合法数组及空序列往返保持 |
| F3 接收EDD/策略区分 | 从receive交期向全部前序传播，共享前序取最早due，保留窗外due；EDD合法替代按ID，FASTEST_MODE按短工时/cost/ID | 两独立设备/具名操作者的接收例：原EDD5，新EDD4、FASTEST4、手排/CP-SAT4，SPT仍5；超窗口交期和输入顺序回归通过 |
| C1 固定抽象图版本 | S16-STATIC-1.1及S16-ABSTRACT-GRAPH-1显式绑定；JSON必须携带版本/purpose/layout元数据 | 未携带元数据、显式旧1.0或将布局标记成真实S13版本均拒绝；完整实例摘要绑定抽象资源/角色/前序/工时与费用 |

策略区别另有独立单任务例：A_SLOW=2、Z_FAST=1、费用相同，EDD取A_SLOW目标2，FASTEST_MODE取Z_FAST目标1，CP-SAT最优1，完整可行集合5条。两规则计划均独立检查合法。该例仅证明不同已声明定义，不是正式A/D效果或速度优势。

原七例全部数值参数、CP-SAT状态/目标和原标签规则结果保持，原四个完整可行集合6/3/11/9与最优3/3/3/8保持；B=2三件目标17和B=3独立开发对照15保持。64个固定种子一般小例和4个双产品/输出驻留/FG容量/接收小例共68组，再次完成CP-SAT与独立笛卡尔枚举的完整集合/目标比较，结果逐项等于r1审阅；四产品集合0/26/0/2、可行目标10。不是只重读旧PASS，也没有调整输入数值求通过。

新增15项回归方法初版在未修复r1上实际检出14个失败子用例、2个错误（保留完整日志）；修复后专项 **37项通过**。完整源码 **612项/177.464s**，从sdist构建的独立wheel **612项/180.758s**通过；Ruff/格式、锁/依赖检查、构建及reference组锁导出/hash安装均通过。获测244文件摘要在检查后保持，213个生产/场景/模型/Schema/CI/依赖文件逐项与修复前一致。没有修改生产配方、完整领域契约、物理场景、工具版本、CI预算或增加运行依赖。

复现及精简证据：

```powershell
uv sync --locked --no-editable --reinstall-package adaptive-hrc-scheduling --link-mode copy
uv run --locked --no-editable python -m unittest discover -s tests -p test_cpsat_reference.py -v
uv run --locked --no-editable python scripts/run_cpsat_reference.py --output .local/s16-r2-cases --check --include-repair-witnesses
uv run --locked --no-editable python scripts/check.py
```

当前[原七例输入/摘要](../../examples/cpsat/summary.json)与[独立修复见证](../../examples/cpsat/repair_summary.json)采用1.1接口；旧1.0由原标签/封包复现，当前入口拒绝显式旧版，不静默迁移。完整映射/规则见[说明](../algorithms/cpsat_mapping.md)，机器摘要见[配套JSON](S16_limited_repair_r2.json)。全部原始日志、反例旧结果及修复前工作区副本只留本地。

## 限制与授权边界

结论仅覆盖明确合成静态整数域及受测反例/集合，不是任意输入全局正确性或完整动态建筑最优性。HR禁用、工业资格/质量UNKNOWN，F/E、cap、恢复/动态扰动/完整BOM/任意路径几何/异步反馈的双方省略保持。抽象图标记不是实际S13场地映射或新增几何能力；未实现S17物流/LNS承接。规则仍可能非最优、保守等待或NO_PLAN_FOUND；solver预算不含编码/检查，BUDGET_OR_SOLVER_STOP是合并原因，未承诺端到端实时能力。

原RP/SC/SH/WV及D01—D06其余冻结边界保持，S15合成质量/接收、有限USD/AABB/运动学、无单独GUI体验验收保持。原720h截尾/疲劳INVALID、WV01 r4首轮180分钟监督失败及全部原失败不重标。本轮无新Kit或远端CI；原r1双平台597项不转记为r2远端结果。新成果验收/确切发布另审，后续步骤未启动。

## 确切待审快照与拟发布操作

基线提交 `f8ea47cbac96e9663f35dae5a6434693d34f648c`，目标[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)、main、拟不可移动新标签step-S16-r2。共 **22文件**：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/cpsat_mapping.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/steps/S16.md`
- `docs/validation/S16_limited_repair_r2.json`
- `docs/validation/S16_limited_repair_r2.md`
- `docs/validation/S16_post_release_audit_r1.md`
- `examples/cpsat/cases.json`
- `examples/cpsat/repair_cases.json`
- `examples/cpsat/repair_summary.json`
- `examples/cpsat/summary.json`
- `scripts/run_cpsat_reference.py`
- `src/adaptive_hrc_scheduling/reference/baselines.py`
- `src/adaptive_hrc_scheduling/reference/cases.py`
- `src/adaptive_hrc_scheduling/reference/checker.py`
- `src/adaptive_hrc_scheduling/reference/domain.py`
- `tests/test_cpsat_reference.py`

逐文件原始/LF摘要、完整含新增文件差异及封包校验本地留存；保留修复前九份审阅治理和原批准/回执。公开集合不含内部总纲、原始会话/日志、机器路径/配置、凭据或参考原件。

负责人对该确切快照另行验收并批准发布后，拟仅精确暂存这22路径，复核全部拟推送历史和既有配置署名，创建一个有限修复提交和annotated step-S16-r2，非强制推送main与新标签，核验完整远端树/文件摘要/分支/标签及Windows/Ubuntu必要CI后才记录PUBLISHED。无新PR、附件、Release或仓库元数据操作；不启动后续步骤。批准前不执行这些Git/远端写入，当前提交自己的最终哈希不预写入自身。
