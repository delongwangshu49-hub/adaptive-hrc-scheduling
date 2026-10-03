# 完整建筑模块的多资源自适应生产调度

2026-10-03现行本地成果（LOG111，PR102授权）：S13第五版整改已形成候选 `S13-20261003-r3`，**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。目标主场景采用固定生产设备、两独立焊接站、人工叉运/推车与主CR1，具名人员任务关联、入料代表链、B=2成品槽和B+1实际搬出见证已验证；冻结旧配置及旧证据保持。工作区/隔离wheel各456项，最终目标24项专项、53行运输矩阵及真实Isaac/GUI/旧协议回归通过；三档30秒暖机、至少120秒测量、各10次重建完成。可靠真实帧时间仍不可得，工业能力及人工体验验收未获证明。未创建分支/worktree，未下载第三方资产、升级环境或执行Git写入，未启动S14—S28。下列旧状态保留其历史时点。

现行入口：[目标试运行](docs/sim/S13_trial_guide.md)、[设备/物流裁定](docs/sim/S13_equipment_decisions.md)、[任务矩阵](docs/sim/S13_transfer_coverage.tsv)、[验证报告及20张新原图](docs/validation/building_scene.md)。旧六设备入口使用 `--legacy`，原33张图与封包保持。

2026-10-03现行批准与交接授权（PR102 / LOG110）：负责人已同意S13-PLAN-20261003-r5及FACTORY-OPERATIONS-20261003-r2提案，要求创建“S13-4”新对话，沿用当前目录/main、不创建分支或worktree，并直接开始S13步骤整改。方案查阅与实施放行条件已满足，不再等待r5方案批准；下列待审/仅文档文字保留原时点。授权包含本步整改、必要验证、品质完善、治理及确切审阅包。未来总纲补丁的规划认可不等于启动S14—S28或解冻D01—D06。第三方资产下载、环境升级与Git暂存/提交/标签/推送/PR/附件仍未授权；整改成果验收与确切快照发布另审。

2026-10-03当前规划审阅（PR101 / LOG109）：[S13第五版内部整改规划书](docs/sim/S13_revision_proposal_r5.md)及[后续总纲补丁](docs/PROJECT_CHARTER.md#factory-operations-patch)已形成待审稿。拟解决设备性质/配置、人机操作关联、人员路线、入料承载、有限成品缓冲和全任务吊运覆盖；生产契约与多订单闭环由后续步骤承接。本轮仅规划和治理，整改实施等待负责人明确放行。r2验证与封包保留，不代表本版问题已解决或成果已获验收。

2026-10-03现行修订成果（LOG107）：S13 r4授权范围已完成本地修订，候选`S13-20261003-r2`为**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。60×44 m供料带、37项工序覆盖、15人路线和T1—T4连续排演已实测；工作区/隔离wheel各432项回归及最终38项专项通过。入口：[试运行操作](docs/sim/S13_trial_guide.md)、[验证报告与33张实际截图](docs/validation/building_scene.md)、[工序覆盖](docs/sim/S13_process_coverage.md)、[当前步骤卡](docs/steps/S13.md)。L0/L1/L2同口径测量与各10次重置已完成；可靠实际渲染帧时间不可得，真实帧率目标未验证。没有Git写入、资产下载、环境升级或S14—S28实现。下列r1与方案待审文字保留历史时点，现行成果以本段为准。

2026-10-03现行批准与交接授权（PR099 / LOG105）：负责人已批准S13-PLAN-20261003-r4现行规划及总纲未来步骤补丁，明确要求创建“S13-3”新对话，沿用当前目录/main、不创建新分支或worktree，直接完成S13步骤内剩余增改、完善、验证、必要治理及确切审阅包。方案查阅与实施启动条件已满足，不再等待方案批准；下列待审/仅文档文字保留历史时点。未来步骤补丁获规划认可不等于启动S14—S28或解冻D01—D06。第三方资产下载、环境升级以及Git暂存/提交/标签/推送/PR/附件仍未授权；修订成果验收和确切快照发布另审。

2026-10-03方案审阅（PR098 / LOG104）：[S13第四版修改方案](docs/sim/S13_revision_proposal_r4.md)与[未来步骤总纲补丁](docs/PROJECT_CHARTER.md#process-layout-patch)已形成待审稿。供料/预处理空间、布局、人流物流和设备交接拟在S13集中修订，生产契约与完整闭环由后续步骤承接。本轮仅文档；交接、实施、验收与上传均未因此获批。原r1验证事实保持，不能替代修订版验收。

2026-10-03当前交付：S13原创建筑工厂场景已完成本地实现与验证，候选`S13-20261003-r1`待负责人验收及独立发布批准。入口见[S13步骤卡](docs/steps/S13.md)、[实际验证与18张截图](docs/validation/building_scene.md)、[场景映射/运行方法](docs/sim/scene_mapping.md)、[机器摘要](examples/building_scene/summary.json)和[资产登记](docs/sim/asset_register.tsv)。六类设备、完整模块、七区、R1六轴与龙门吊均有实际Isaac见证；420项CPU检查在工作区和隔离安装各通过一次。仅几何/运动学及基础接触检查，HR禁用、质量UNKNOWN、S14—S28未实施。以下阶段状态保留历史时点，以本段和当前步骤卡为准。

2026-10-03现行授权（PR095 / LOG099）：负责人已批准S13-PLAN-20261003-r3，要求创建“S13-2”新对话，沿用现有目录/main，不建分支或worktree，直接完成S13剩余本地实现、验证、品质打磨、必要治理及确切审阅包。方案查阅条件已满足，不再等待方案批准；以下待审/仅调研文字保留历史时点。S14—S28、第三方资产下载、环境升级与新Git/远端发布不在本次授权内。

2026-10-03状态补录：S12 r2已实际验收并发布（PR091 / LOG094）；S13仅获前期方案授权，正式搭建待负责人明确批准。见[S13方案](docs/sim/S13_scene_proposal.md)与[步骤卡](docs/steps/S13.md)。以下S12待审文字保留原封签时点，不能理解为实际发布失败。

研究钢框架、水泥板楼板基底、轻质围护和指定湿区的完整居住模块，从结构制造贯通MEP/内装、质量放行及出厂就绪。重点为A状态依赖模式与排程联合决策、D人因权衡；B仅反馈稳健性，C仅恢复评价。

**C04/C05 r2、S10 r2及S11 r2已验收并发布；S12 r1已验收并发布；r2为三类独立决策审计缺口的有限本地修复候选，另行验收与批准发布。** SR-W1/W2完整日志从原始事件独立重建，检查器不调用执行器许可函数或复用其派生PASS。默认研究输入仍因工艺证据UNKNOWN而HOLD，HR禁用；受控合成资格不是工业资格。S11已实现静态EDD/SPT/当前合法最快模式与完整轨迹核验；S12已实现观测驱动的单动作动态重排；Isaac生产闭环、LNS、CP-SAT与正式研究实验尚未实施；旧180项仅作旧域回归。

| 阅读目的 | 入口 |
| --- | --- |
| 研究目标、范围与成功条件 | [研究总纲](docs/PROJECT_CHARTER.md) |
| 产品/BOM、工艺、资源、质量与模式门 | [钢专属规格](docs/model/selected_steel.md)及[模型约束](docs/model/specification.md) |
| 来源、估计与未解决缺口 | [证据台账](docs/research/production_evidence.md) |
| 组件/闭环与实施依赖 | [架构](docs/architecture.md)、[修复栏目](docs/repair_plan.md)、[S10—S28逐步路线](docs/roadmap.md) |
| 本次审阅与实际检查 | [S12步骤卡](docs/steps/S12.md)、[轻量闭环核验](docs/validation/light_loop.md)、[S11步骤卡](docs/steps/S11.md)、[规则定义](docs/algorithms/rule_baselines.md)、[S10步骤卡](docs/steps/S10.md)、[独立检查](docs/validation/checker.md)、[C04—C05历史](docs/steps/C04-C05.md)、[进度日志](PROGRESS_LOG.md) |
| 选型历史和仓库命名候选 | [C02比较](docs/model/candidate_comparison.md)、[名称/About方案](docs/repository_migration.md) |

依[环境说明](docs/setup.md)安装固定Python和uv；Windows使用PowerShell7。仓库根目录运行：

```powershell
uv sync --locked --link-mode copy
uv run --locked python -m adaptive_hrc_scheduling
uv run --locked python -m unittest discover -s tests -v
```

包入口是安装自检。运行/检查边界见[开发说明](docs/development.md)，本轮本地CPU验证与远端CI分开，实际结果见步骤卡；C04/C05 r2、S10 r2及S11 r2双平台CI成功；S12 r1双平台CI成功；r2本地验证见步骤卡，r2远端CI未运行。负责人主导目标、选型、冻结与验收，AI在授权范围辅助核查、文档及后续实现，见[规范化决策记录](PROMPT_LEDGER.md)。

自有代码采用[MIT](LICENSE)，第三方原件/资产许可独立。本文仅为入口，版本S12-0.2，2026-10-02；本次仅获S12三类审计问题的有限修复、验证及审阅包授权，尚无r2暂存、提交、标签、推送或远端名称/About修改批准。

建筑合成见证：`uv run --locked --no-editable python scripts/run_building_witness.py --output .local/building-witness`。建筑Schema/样例校验：`uv run --locked --no-editable python scripts/build_building_contracts.py --check`。完整原始输出留本地。

S10复核与机器摘要：`uv run --locked --no-editable python scripts/run_building_checker.py --output .local/s10-checker`。全日志只留本地，公开摘要见[样例](examples/building_checker/summary.json)。

S11规则复现：`uv run --locked --no-editable python scripts/run_rule_planners.py --output .local/s11-cases --check`。完整候选轨迹留本地；公开[合成输入与摘要](examples/rule_planners/summary.json)明确区分FEASIBLE、NO_PLAN_FOUND和确证超载INFEASIBLE。

S12轻量闭环：`uv run --locked --no-editable python scripts/run_light_loop.py --output .local/s12-cases --check`。公开[合成反馈用例](examples/light_loop/cases.json)与[摘要](examples/light_loop/summary.json)区分完成、取消清场、质量/材料/故障等待和未完成；完整决策、观测、实际轨迹仅本地保存。
