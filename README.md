# 完整建筑模块的多资源自适应生产调度

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
