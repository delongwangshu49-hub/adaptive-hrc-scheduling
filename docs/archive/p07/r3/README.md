# Adaptive HRC Scheduling

**面向模块化建筑制造的动态人机协作调度与执行仿真。**

将任务前序、人员疲劳、协作模式、设备、物料和空间约束放进同一生产模型，根据执行反馈调整后续安排，并保存可独立核验的运行记录。

[![Python](https://img.shields.io/badge/Python-3.12.13-555?labelColor=222)](pyproject.toml)
[![License](https://img.shields.io/badge/License-MIT-555?labelColor=222)](LICENSE)
[![CPU checks](https://img.shields.io/github/actions/workflow/status/delongwangshu49-hub/adaptive-hrc-scheduling/ci.yml?branch=main&label=CPU%20checks&color=555&labelColor=222)](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/workflows/ci.yml)

[快速开始](#快速开始) · [工作台](#工作台) · [系统架构](#系统架构) · [研究结果](#研究结果) · [文档](#文档)

<a id="overview"></a>

## 可以用它做什么

- **描述生产系统。** 定义产品工序、人员资格与日历、疲劳累积和恢复，以及设备、物料、搬运路线和占位约束。
- **比较调度策略。** 在同一合法域中运行规则基线和自适应策略，区分候选安排、实际采用、执行结果及计算预算。
- **处理运行中变化。** 通过共享会话提交普通单、急单、取消、设备故障与维修、人员到离岗和返回，跟踪受理、生效与业务结果。
- **查看执行过程。** 使用 CPU 后端或 Isaac Sim，在工作台中对照三维场景、实际工序和未来计划。
- **复现分析。** 从保存的事件和状态生成逐产品、人员、资源及成本统计，核对图表、双域导出和结论的来源。

<a id="status"></a>

当前模型用于 **S18-SIM-A1 仿真研究**。CPU 分析与可选的 Windows / Isaac 工作台分开安装；应用范围和仍未达到的目标见[项目状态](docs/public_results/status.md)。

<a id="quickstart"></a>

## 快速开始

先用已保存的测量数据重算研究结果：无需 GPU、Isaac Sim 或重新运行生产。使用 **Python 3.12.13**、**uv 0.12.3**；下面是 PowerShell 7 命令。

```powershell
git clone https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling.git
cd adaptive-hrc-scheduling
uv python install 3.12.13
uv venv --python 3.12.13 .local/results-env
uv pip install --python .local/results-env/Scripts/python.exe -r analysis/p07/requirements.txt
& .local/results-env/Scripts/python.exe analysis/p07/reproduce.py replay --figures --output .local/results-demo
```

成功后，`.local/results-demo` 中包含统计 JSON/CSV、验证结果、双域导出和图表。入口会核对输入摘要、独立检查积分与人员分母，并拒绝读取原私有运行档案。输出目录请选择新目录。Linux/macOS 的环境解释器路径为 `.local/results-env/bin/python`。

| 接下来想做什么 | 入口 |
| --- | --- |
| 理解数据、指标和比较方法 | [研究结果与再生指南](docs/public_results/README.md) |
| 执行新的正常 CPU 生产案例 | [安装与生产复现](docs/public_validation/reproduction.md) |
| 使用 Isaac Sim 双图工作台 | [工作台安装与操作](docs/public_workbench/usage.md) |
| 检查保存件、目录及计划引用 | [保存重建与独立核验](docs/public_validation/reproduction.md#执行及重建) |

新的生产运行使用完整源码仓库和核心环境：

```powershell
uv sync --locked --link-mode copy
uv run --locked python scripts/verify_production_chain.py --output .local/new-normal-cpu --backend light --simulation --products 1 --variant SR-W1 --scenario NORMAL --until-h 720
```

该命令执行完整案例；结束状态、实际产品接收和独立审计共同决定结果。核心 wheel、分析材料和桌面依赖的分发范围见[安装说明](docs/public_validation/reproduction.md)。

<a id="showcase"></a>

## 工作台

<img src="docs/assets/readme/workbench-native-p051.jpg" alt="真实工作台运行截图：左侧为嵌入的Isaac三维场景，右侧为实时工序甘特，下方显示详情与回执" width="100%">

实际运行的原生窗口：左侧 Isaac 场景与右侧甘特共同呈现执行状态。截图的运行身份、版本和采样范围见[图像来源](docs/public_validation/visual_provenance.json)。

工作台提供参数配置、运行中请求、回执查看、停止保存和只读重建。Windows 环境使用 PySide6 / Qt WebEngine 和受测 Web 静态资产，Isaac Sim 单独配置：

```powershell
uv sync --locked --project desktop/p051
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py --help
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py
```

<details>
<summary>查看正常生产与动态变更的归档画面</summary>

![正常完整CPU案例的甘特归档](docs/assets/readme/cpu-normal-resources-p063.png)

正常单产品 CPU 案例完成436项静态工序并实际接收产品。图为已保存的只读甘特。

![运行中更新订单后的甘特归档](docs/assets/readme/dynamic-plan-p063.png)

动态案例展示订单变更后的目录与完整计划，并按原停止操作保存。局部检查点与完整生产终点分开评价。两图均保留原始字节，来源见[图像记录](docs/public_validation/visual_provenance.json)。

</details>

<a id="architecture"></a>

## 系统架构

同一生产契约连接模型、调度、后端和工作台。调度只消费已交付观察；动态目录保留初始配置和版本历史，实际命令按接纳时的版本核验。

```mermaid
%%{init: {"theme":"base","htmlLabels":false,"themeVariables":{"primaryColor":"#f2f2f2","primaryTextColor":"#171717","primaryBorderColor":"#777777","lineColor":"#777777","fontSize":"16px"},"flowchart":{"htmlLabels":false,"useMaxWidth":true}}}%%
flowchart TB
    C[配置与运行中请求] --> S[规则基线 / 自适应候选]
    S --> V[合法域核验与承诺保护]
    V --> E[CPU / Isaac 执行与读回]
    E --> O[已交付观察与目录版本]
    O --> S
    O --> W[三维场景与工序甘特]
    E --> A[事件、决策与采用计划归档]
    classDef default fill:#f2f2f2,stroke:#777777,color:#171717
    linkStyle default stroke:#777777
```

实际执行、已采用但尚未执行的计划、未安排任务和未知状态分别显示。显示故障不自动重放业务请求，归档读取保留原观察的时效语义。

```mermaid
%%{init: {"theme":"base","htmlLabels":false,"themeVariables":{"primaryColor":"#f2f2f2","primaryTextColor":"#171717","primaryBorderColor":"#777777","lineColor":"#777777","fontSize":"16px"},"flowchart":{"htmlLabels":false,"useMaxWidth":true}}}%%
flowchart LR
    A[保存的执行证据] --> B[独立审计与来源绑定]
    B --> C[逐产品 / 人员 / 资源统计]
    C --> D[数值与图表一致性核验]
    D --> E[CSV、图表与双域导出]
    E --> F[可追溯结论与再生输入]
    classDef default fill:#f2f2f2,stroke:#777777,color:#171717
    linkStyle default stroke:#777777
```

图表消费经过核验的测量数据。疲劳曲线保留恢复至零的折点；实际生命周期与共同评价窗口分列；甘特总展示行与完整计划行分别计数。

<a id="validation"></a>

## 研究结果

当前提供 N/H/F/U/C 五情景的两方法原值、45行配对指标和四机制格，以及动态人员、订单响应、取消实物账和计算成本。固定研究、动态交互案例及真实 Kit 记录保留各自运行身份和窗口。

<img src="figures/p07/r3/P07-02-scenario-values.png" alt="五个固定情景的两方法原值：准时接收比例、末次接收时刻、共同窗口总暴露与最大个人暴露" width="100%">

现有固定情景中，多数配对结果相同；急单情景的共同窗总暴露差约为 −0.001013 F·h。该研究集没有建立自适应方法的普遍优势。取消案例保持原截尾状态，E20原连续Kit案例仍为1件接收、3件未接收。

[浏览全部图表](docs/public_results/README.md#图表与数据) · [指标定义](docs/metrics/p07_metrics_definition_r3.md) · [来源与结论索引](docs/public_results/README.md#来源与验证)

<a id="docs"></a>

## 文档

| 主题 | 文档 |
| --- | --- |
| 入门与环境 | [安装](docs/setup.md) · [CPU生产与保存重建](docs/public_validation/reproduction.md) |
| 工作台与交互 | [操作指南](docs/public_workbench/usage.md) · [交互案例](docs/public_workbench/interaction_cases.tsv) |
| 模型与执行 | [生产规范](docs/model/specification.md) · [动态后端](docs/public_backend/README.md) · [共享契约](docs/public_delivery_r2/interaction_contract_r3.md) |
| 数据、图表与研究复现 | [结果指南](docs/public_results/README.md) · [指标定义](docs/metrics/p07_metrics_definition_r3.md) · [派生输入](examples/reproduction/p07/r3/manifest.json) |
| 验证与使用边界 | [当前状态](docs/public_results/status.md) · [既有执行证据](docs/public_validation/evidence_summary.json) · [失败与修复](docs/public_validation/failures_and_repairs.md) |

<a id="checks"></a>

## 开发与贡献

完整 CPU 检查使用与 CI 相同的入口：

```powershell
uv run --locked --no-cache --no-editable --reinstall-package adaptive-hrc-scheduling python scripts/check.py
```

分析工具还可独立运行定向测试：

```powershell
uv run --locked python -m unittest discover -s tests -p 'test_p07*.py' -v
```

```text
src/adaptive_hrc_scheduling/   模型、契约、调度与执行
scripts/                     生产、核验与桌面入口
desktop/p051/                Qt / React 工作台
sim/                         Isaac 场景与读回适配
analysis/p07/                离线分析、验证与图表
examples/reproduction/        合成配置与派生测量输入
docs/                        指南、模型与证据
```

问题反馈请附最小复现步骤、版本、实际状态和相关日志；改动应保留已有断言、失败记录及来源范围。通过 [GitHub Issues](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/issues) 讨论问题与改进，再提交附有验证结果的变更。

## 许可

代码采用 [MIT License](LICENSE)。模型假设、图像来源和数据适用范围随对应文档提供。
