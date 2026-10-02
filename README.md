# 完整建筑模块的多资源自适应生产调度

研究钢框架、水泥板楼板基底、轻质围护和指定湿区的完整居住模块，从结构制造贯通MEP/内装、质量放行及出厂就绪。重点为A状态依赖模式与排程联合决策、D人因权衡；B仅反馈稳健性，C仅恢复评价。

**C04/C05建筑契约与轻量执行代码已实现并完成合成正反见证，本地阶段收尾已执行，快照待负责人审阅。** SR-W1/W2贯通结构、MEP/内装、7质量门与READY；默认研究输入仍因工艺证据UNKNOWN而HOLD，HR禁用。受控合成资格只测试程序分支，不是工业资格。S10独立检查器、调度算法、Isaac生产闭环与正式研究实验尚未实施；旧180项仅作为旧域回归。

| 阅读目的 | 入口 |
| --- | --- |
| 研究目标、范围与成功条件 | [研究总纲](docs/PROJECT_CHARTER.md) |
| 产品/BOM、工艺、资源、质量与模式门 | [钢专属规格](docs/model/selected_steel.md)及[模型约束](docs/model/specification.md) |
| 来源、估计与未解决缺口 | [证据台账](docs/research/production_evidence.md) |
| 组件/闭环与实施依赖 | [架构](docs/architecture.md)、[修复栏目](docs/repair_plan.md)、[S10—S28逐步路线](docs/roadmap.md) |
| 本次审阅与实际检查 | [C04—C05步骤卡](docs/steps/C04-C05.md)、[建筑验证](docs/validation/building_execution.md)、[进度日志](PROGRESS_LOG.md) |
| 选型历史和仓库命名候选 | [C02比较](docs/model/candidate_comparison.md)、[名称/About方案](docs/repository_migration.md) |

依[环境说明](docs/setup.md)安装固定Python和uv；Windows使用PowerShell7。仓库根目录运行：

```powershell
uv sync --locked --link-mode copy
uv run --locked python -m adaptive_hrc_scheduling
uv run --locked python -m unittest discover -s tests -v
```

包入口是安装自检。运行/检查边界见[开发说明](docs/development.md)，本轮本地CPU验证与远端CI分开，实际结果见步骤卡；未运行远端CI。负责人主导目标、选型、冻结与验收，AI在授权范围辅助核查、文档及后续实现，见[规范化决策记录](PROMPT_LEDGER.md)。

自有代码采用[MIT](LICENSE)，第三方原件/资产许可独立。本文仅为入口，版本C05-0.1，2026-10-02；本次无提交、推送或远端名称/About修改批准。

建筑合成见证：`uv run --locked --no-editable python scripts/run_building_witness.py --output .local/building-witness`。建筑Schema/样例校验：`uv run --locked --no-editable python scripts/build_building_contracts.py --check`。完整原始输出留本地。
