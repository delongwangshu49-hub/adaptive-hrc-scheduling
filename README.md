<div align="center">

# Adaptive HRC Scheduling

**面向模块化建筑工厂的人机协作自适应调度研究**

从人员、设备与物料状态出发，联合选择协作模式与作业顺序，
在离散事件和 Isaac Sim 中执行，再用独立审计核对每一次决策。

[![CPU checks](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/workflows/ci.yml/badge.svg)](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A06B)](LICENSE)
[![Scope: Simulation Research](https://img.shields.io/badge/Scope-Simulation_Research-5662D3)](docs/model/S18_simulation_scope_proposal_r1.md)

[概览](#overview) · [当前阶段](#status) · [快速开始](#quickstart) · [工作原理](#architecture) · [验证与边界](#validation) · [文档导航](#docs)

</div>

<a id="overview"></a>

## 项目概览

本项目研究完整建筑模块制造中的自适应人机协同调度。系统把任务前序、人员资格与疲劳、机器人和设备、物料与空间约束纳入统一生产模型，通过离散事件与Isaac Sim执行反馈，在线调整尚未执行的任务、协作模式和资源安排，并保存可独立核验的运行依据。生产流程贯通结构制造、MEP、内装、质量放行与出厂接收。

当前交付围绕模型、协作模式、疲劳、故障、订单变化、真实执行环境、闭环算法、评价与报告推进，并加入运行中真新订单/人员变更、实时甘特及同权双视图要求。成果属于 **S18-SIM-A1 仿真研究域**，工业G2仍为OPEN。

<a id="status"></a>

## 当前阶段

**P03.3五项审阅问题已在设计/离线范围修复核验；G03-r2候选供审阅，上传待一次性授权。** 本地设计完成、负责人审阅、实现、生产验收及实际发布分别记录。下表描述本次候选内容，未预记新提交、标签或CI成功。

| 阶段 | 已完成范围 | 后续边界 |
| --- | --- | --- |
| P00–P02 | 需求/报告骨架、资产与版本选择、P01-INDEX-r2、P02-MODEL-r2及有限修订 | 最终整体技术/负责人验收另记 |
| P03.1 | 两条正常CPU/真实Kit完整历史链承接、资源/反馈映射及影响证明，审阅通过 | 历史充分部分未机械重跑 |
| P03.2 | 共用运行/事件、动态目录和连续会话契约；六项问题在离线范围修复 | 动态后端消费者待实现 |
| P03.3 | 同权双图布局、40展示字段来源、24案例协议、容量/工时设计；r2有限修复核验完成 | GUI/Kit新界面及动态案例未执行 |
| P04–P09 | 已明确动态后端→双图/连续生产→独立核验→结果/报告→联合验收路线 | 尚未启动 |

本次候选仅含README、公开技术文档/摘要及离线设计检查器；运行源码沿已发布的[step-S20-r4](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/tree/step-S20-r4)（`2d12e84b`）。其他未提交源码、旧研究部分运行及受控原件不随候选整树上传。详见[阶段摘要](docs/public_delivery_r2/stage_summary.md)与[路线](docs/public_delivery_r2/roadmap.md)。

## 能力与成熟度

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| 多资源生产模型 | 已有受测实现 | 前序、人员/资格/疲劳、设备/工装、物料、空间、在制与外部接收 |
| 规则与联合调度 | 已有受测实现 | 合法EDD等规则、LNS、在线预算/核验/缓存/回退；新五情景比较未全部完成 |
| CPU与Isaac闭环 | 已有受测实现/历史完整证据 | 命令接纳、真实读回、观察交付、决定与后续执行可追 |
| 独立核验 | 已有受测实现 | 执行/因果审计、候选重放、双后端比较；动态扩展另验 |
| 本地双语Qt/Kit工作台 | 已有历史原型 | S19B接受的启动/内存/关闭/覆盖限制保持；支承已通过 |
| 真新订单/人员、连续会话 | 契约设计完成 | GUI/CLI共享RunSpec、目录/版本/缓存、F/E与费用、关闭排空规则；待P04实现 |
| 实时甘特与同权布局 | 设计完成 | 默认三维/甘特同时可见1:1，稳定ID联动与数据年龄；待P05实现 |

三维与实时甘特**同等重要，默认同时可见、绘图区1:1（各45%–55%）**。宽屏左右、窄屏上下，支持分隔拖动、对称放大和恢复等分，运行中新普通单/急单、人员增减入口始终可达。后续E20在同一真实Kit会话验证原单执行→新普通单→真新急单→减员→含新人员增员→关闭接单→全部受理单完成接收/正常退出。当前是已批准方向及完成的技术设计，尚无新界面实际截图或生产通过结论。

<a id="quickstart"></a>

## 快速开始

CPU路径无需Isaac Sim或GPU。Python **3.12.13** 与 uv **0.12.3** 由项目固定；Windows使用 **PowerShell 7**。环境隔离详见[安装说明](docs/setup.md)。

```powershell
git clone https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling.git
cd adaptive-hrc-scheduling
uv python install 3.12.13
uv sync --locked --link-mode copy
uv run --locked python -I -m adaptive_hrc_scheduling
```

安装入口只输出包元数据；基础wheel没有运行依赖，生产/桌面入口需要完整源码仓库。以下是有效历史正常单件入口，新输出目录不可复用：

```powershell
uv run --locked python scripts/verify_production_chain.py --output .local/new-normal-cpu --backend light --simulation --products 1 --variant SR-W1 --scenario NORMAL --until-h 720
```

该命令运行默认正常生产，不能代表新动态接口或新的自适应五情景协议。查看输出中的`report.json`、事件/决定记录和审计；完整订单需完成/接收/退出证据，1小时检查点不能替代。P03候选准备未新跑上述生产命令。

已有双语工作台入口为`./scripts/start_s19b.ps1`，独立依赖、Kit连接及历史限制见[工作台说明](desktop/s19b/README.md)。真实Kit须使用独立安装的包装器及[环境隔离说明](docs/setup.md#isaac-sim-独立入口)，不能用CPU结果替代Kit。运行中新单/人员和双图新入口待后续交付。

检查离线设计包（只检查设计/人工夹具，不启动生产或GUI）：

```powershell
uv run --locked python scripts/verify_p033_design_r2.py --output .local/new-p033-design-check
```

完整CPU CI入口仍为：

```powershell
uv run --locked --no-cache --no-editable --reinstall-package adaptive-hrc-scheduling python scripts/check.py
```

它检查源码并构建分发包，在隔离wheel环境重复测试；CPU CI不包含Kit或负责人操作。本候选没有触发新远端CI。

<a id="architecture"></a>

## 工作原理

```mermaid
flowchart LR
    I[配置与工艺] --> O[已交付状态观察]
    O --> P[规则 / 联合计划]
    P --> V[候选核验与承诺保护]
    V --> E[CPU / Isaac执行]
    E -->|实际反馈| O
    P --> A[独立因果/执行审计]
    E --> A
```

调度器只使用已经交付的事实；候选、实际采用、命令和执行读回分别记录。无合法动作或预算不足时明确等待/回退，已发生载荷、占位和承诺保持。新动态目录在设计中与冻结C0分开绑定，旧命令按接纳版本核验；两图计划/实际数据将由版本化增量投影提供，显示操作只读。这部分扩展待P04/P05接通。

```text
src/adaptive_hrc_scheduling/  领域、契约、算法、规划与闭环
scripts/                      运行、审计与离线核验
sim/                          Isaac场景、接收与读回适配
desktop/s19b/                 已有Qt/Kit工作台
examples/                     配方、输入与预算
docs/public_delivery_r2/         当前公开候选的路线、契约、设计和证据摘要
```

<a id="validation"></a>

## 验证与边界

运行来源基线step-S20-r4的历史双平台源码/隔离wheel各905项通过，见[该次发布记录](docs/validation/S20_publication_r4.md)；这是历史版本结果。当前G03候选的新远端CI尚未运行，首页徽章显示目标分支工作流状态，不能视为此候选已通过。

| 本次承接/核对 | 结果与来源 |
| --- | --- |
| P03.1正常CPU/真实Kit历史链 | 各4402事件/2072决策、436有效工序、READY/RECEIVED各1、真实QT exit0；[历史摘要](docs/public_delivery_r2/historical_evidence_summary.json) |
| P03.2当前契约有限核验 | 417基线、47定向及33独立检查；六项问题在契约范围关闭 |
| P03.3离线设计 | 修订161项检查（含原24损坏夹具、41定向条件及12输入绑定），另32独立契约/来源核对；无新生产/Kit/Qt运行 |

[验证摘要](docs/public_delivery_r2/validation_summary.json)按历史/本地设计/未来实际验收分列；五项有限修复及其边界见[修复摘要](docs/public_delivery_r2/repair_summary.md)，负责人复审待定。新接口的E01–E24、同会话连续链、窗口/DPI/负载、保存重建和负责人操作仍待后续。候选吞吐/响应阈值与受测上限须在P04/P05校准后冻结；历史单件计时不能作为新双图性能保证。

S19B接受的限制、支承通过、S18-SIM-A1及工业G2 OPEN保持。USD运动学读回不等于工业动力学/安全认证；正式方法优势尚未建立。历史失败、截尾、未完成研究及未知退出保留，不为新路线补造成功。完整原始日志、私有配置和原始参考材料受控保存。

<a id="docs"></a>

## 文档导航

| 内容 | 入口 |
| --- | --- |
| 当前阶段与后续路线 | [阶段摘要](docs/public_delivery_r2/stage_summary.md) · [路线](docs/public_delivery_r2/roadmap.md) |
| 交互要求及验收协议 | [I01–I08](docs/public_delivery_r2/interaction_requirements_r2.tsv) · [E01–E24](docs/public_delivery_r2/interaction_case_protocol.md) |
| 模型与方法 | [模型承接](docs/public_delivery_r2/model_summary.md) · [生产规范](docs/model/specification.md) · [在线策略](docs/algorithms/online_policy.md) |
| 动态契约 | [共用](docs/public_delivery_r2/interaction_contract_r3.md) · [目录](docs/public_delivery_r2/dynamic_catalog_contract_r2.md) · [会话](docs/public_delivery_r2/session_lifecycle_contract_r2.md) |
| 双图与容量设计 | [布局](docs/public_delivery_r2/dual_view_layout_spec.md) · [时间线来源](docs/public_delivery_r2/timeline_source_spec.md) · [容量](docs/public_delivery_r2/capacity_estimate.md) |
| 历史来源与研究边界 | [S20-r4发布](docs/validation/S20_publication_r4.md) · [仿真范围](docs/model/S18_simulation_scope_proposal_r1.md) · [工业G2](docs/research/S18_industrial_g2_evidence_r1.md) |

## 贡献与许可

欢迎通过[Issues](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/issues)提供版本、复现步骤、预期/实际结果和脱敏错误摘要。代码、来源核查、实验及文档中的AI辅助按实际记录，不代替负责人操作或最终验收。

自有代码采用[MIT License](LICENSE)。第三方软件/资产遵循各自许可，来源见[资产登记](docs/sim/asset_register.tsv)。发布每次绑定经审阅的确切成果包，另行取得一次性上传授权。
