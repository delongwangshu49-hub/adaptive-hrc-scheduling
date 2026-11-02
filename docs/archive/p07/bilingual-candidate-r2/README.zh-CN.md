<h1 align="center">Adaptive HRC Scheduling</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">面向模块化建筑制造的动态人机协作调度与执行仿真。</p>

<p align="center">
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.12.13-555?labelColor=222" alt="Python 3.12.13"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-555?labelColor=222" alt="MIT License"></a>
  <a href="https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/delongwangshu49-hub/adaptive-hrc-scheduling/ci.yml?branch=main&label=CPU%20checks&color=555&labelColor=222" alt="Published main CPU checks"></a>
</p>

<p align="center"><a href="#快速开始">快速开始</a> · <a href="#系统架构">系统架构</a> · <a href="#研究结果">研究结果</a> · <a href="#已知限制与未完成目标">已知限制</a> · <a href="#文档">文档</a></p>

Adaptive HRC Scheduling 是一个用于生产调度、执行反馈和可复现分析的研究原型。它将任务前序、人员资格与疲劳、协作模式、设备、物料、搬运和空间约束放进同一生产模型。

<img src="docs/assets/readme/workbench-native-p051.jpg" alt="真实归档工作台：左侧为Isaac三维视口，右侧为执行甘特" width="100%">

实际归档的原生工作台窗口。原图、运行身份与采样范围见[图像来源](docs/public_validation/visual_provenance.json)。

## 项目状态

当前应用域为 **S18-SIM-A1 仿真研究**。CPU 工作流和可选的 Windows / Isaac 工作台使用独立环境。

| 范围 | 现有证据证明了什么 | 尚未完成的范围 |
| --- | --- | --- |
| 正常 CPU 参考案例 | 完成 436 项静态工序，1/1 产品实际接收 | 一个完整参考案例 |
| 连续动态 Kit 案例 | 观察终点 387.732 h 时，1 件接收、3 件未接收 | 动态全流程完成仍未证明 |
| 实时交付性能 | 已验证部分显示和请求功能路径 | 2 s 源龄目标未达；持续 4 Hz 未建立；10/s、50/s 负载资格不足 |
| 桌面阶段 | 关停问题后，按负责人批准的有限功能范围收口 | 原性能目标与更广泛验收仍未完成 |

[已知限制](#已知限制与未完成目标)列出剩余工作和有限收口的适用范围。

## 可以用它做什么

| 工作流 | 能力 |
| --- | --- |
| 描述生产 | 产品、工序、资格、日历、疲劳与恢复、设备、物料、搬运和占位 |
| 比较计划 | 在共同合法域与承诺保护条件下运行规则基线和自适应候选 |
| 应用变更 | 新单、急单、取消、设备故障与维修、人员离岗与返回，保留回执及目录历史 |
| 检查执行 | CPU 后端或可选 Isaac 工作台，分别呈现实际工序与已采用的未来计划 |
| 复现结果 | 产品、人员、资源与成本账，附来源摘要、独立核验和已保存双域导出 |

## 快速开始

先从保存数据重算结果。需要 **Python 3.12.13** 和 **uv 0.12.3**，无需 GPU、Isaac Sim 或新的生产运行。以下命令使用 PowerShell 7。

```powershell
git clone https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling.git
cd adaptive-hrc-scheduling
uv python install 3.12.13
uv venv --python 3.12.13 .local/results-env
uv pip install --python .local/results-env/Scripts/python.exe -r analysis/p07/requirements.txt
& .local/results-env/Scripts/python.exe analysis/p07/presentation.py replay --output .local/results-demo
```

输出目录请选择新目录。`.local/results-demo` 中包含原统计与双域导出，`presentation/` 中有九张按问题组织的数据表，`figures/` 中有四幅图。入口核对输入摘要、暴露积分、人员分母和展示数据，并拒绝读取原私有运行档案。Linux/macOS 的环境解释器路径为 `.local/results-env/bin/python`。

新的正常 CPU 参考案例使用：

```powershell
uv sync --locked --link-mode copy
uv run --locked python scripts/verify_production_chain.py --output .local/new-normal-cpu --backend light --simulation --products 1 --variant SR-W1 --scenario NORMAL --until-h 720
```

该命令执行完整案例。应同时检查保存终态、实际产品接收和独立审计。[生产与重建指南](docs/public_validation/reproduction.md)说明安装、保存件检查和分发范围。核心 wheel 提供运行时，离线分析输入与图表位于完整源码包。

### 可选 Windows 工作台

桌面应用使用 PySide6 / Qt WebEngine 和已打包 Web 资产。Isaac Sim 按[工作台指南](docs/public_workbench/usage.md)单独配置。

```powershell
uv sync --locked --project desktop/p051
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py --help
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py
```

<details>
<summary>正常生产与动态订单变更的归档画面</summary>

![完成正常CPU参考案例后的甘特归档](docs/assets/readme/cpu-normal-resources-p063.png)

正常单产品 CPU 参考案例完成 436 项静态工序，并实际接收产品。

![订单变更后的甘特归档](docs/assets/readme/dynamic-plan-p063.png)

动态检查点保留更新后的目录和完整计划，随后停止并保存。保存局部检查点不代表整单完成。两图保持原始字节，见[来源记录](docs/public_validation/visual_provenance.json)。

</details>

## 系统架构

调度器只消费已交付观察。目录历史保留初始配置及后续版本，执行命令按其接纳时的版本检查。

```mermaid
%%{init: {"theme":"base","htmlLabels":false,"themeVariables":{"background":"#111111","primaryColor":"#202020","primaryTextColor":"#f5f5f5","secondaryColor":"#444444","secondaryTextColor":"#f5f5f5","tertiaryColor":"#303030","tertiaryTextColor":"#f5f5f5","primaryBorderColor":"#808080","lineColor":"#808080","textColor":"#f5f5f5","fontSize":"16px"},"flowchart":{"htmlLabels":false,"useMaxWidth":true}}}%%
flowchart TB
    C["配置与运行中请求"] --> S["规则基线 / 自适应候选"]
    S --> V["合法域核验与承诺保护"]
    V --> E["CPU / Isaac 执行"]
    E --> O["已交付观察与目录历史"]
    O --> S
    O --> W["三维场景与工序甘特"]
    E --> A["事件与采用计划归档"]
    class C,O graphite
    class W,A slate
    classDef default fill:#202020,stroke:#808080,color:#f5f5f5
    classDef graphite fill:#303030,stroke:#909090,color:#f5f5f5
    classDef slate fill:#444444,stroke:#a0a0a0,color:#f5f5f5
    linkStyle default stroke:#808080
```

工作台分别呈现实际执行、已采用的未来计划、未安排任务与未知状态。显示故障不会自动重放业务请求。

```mermaid
%%{init: {"theme":"base","htmlLabels":false,"themeVariables":{"background":"#111111","primaryColor":"#202020","primaryTextColor":"#f5f5f5","secondaryColor":"#444444","secondaryTextColor":"#f5f5f5","tertiaryColor":"#303030","tertiaryTextColor":"#f5f5f5","primaryBorderColor":"#808080","lineColor":"#808080","textColor":"#f5f5f5","fontSize":"16px"},"flowchart":{"htmlLabels":false,"useMaxWidth":true}}}%%
flowchart LR
    A["保存的执行记录"] --> B
    B["独立核验与来源绑定"] --> C
    C["产品 / 人员 / 资源统计"] --> D
    D["数值与图表核对"] --> E
    E["CSV、图与双域导出"] --> F
    F["可追溯结论与再生输入"]
    class A,C,E graphite
    class B,D,F slate
    classDef default fill:#202020,stroke:#808080,color:#f5f5f5
    classDef graphite fill:#303030,stroke:#909090,color:#f5f5f5
    classDef slate fill:#444444,stroke:#a0a0a0,color:#f5f5f5
    linkStyle default stroke:#808080
```

暴露曲线保留恢复至零的折点；实际生命周期与共同评价窗分列，总展示行与完整计划行分别计数。

## 研究结果

材料覆盖五个固定情景、四个既有机制格、动态人员检查点和一次连续 Kit 归档。它们各有运行身份与观察窗口，属于确定性案例，不能合并为随机重复样本。

### 策略结果与计算代价

五情景中，ADAPTIVE 与 EDD 的末次实际接收时刻均相同。跨情景每方法共九个未取消且已接收的产品运行记录，全部迟交 **123.86 至 363.86 h**。

| 情景 | ΔΣE（F·h） | 原运行墙钟变化 | 缓存来源 STARTED |
| --- | ---: | ---: | ---: |
| N | 0 | +5.98% | 24 / 2031（1.18%） |
| H | 0 | +7.82% | 24 / 2036（1.18%） |
| F | 0 | +7.43% | 21 / 2032（1.03%） |
| U | −0.001013 | +57.29% | 29 / 2043（1.42%） |
| C | 0 | +2.19% | 24 / 1066（2.25%） |

N/H 为普通/较高初始疲劳，F 为故障维修，U 为急单，C 为取消。Δ 为共同 720 h 窗口内 ADAPTIVE 减 EDD；U 的相对暴露差为 −0.000419%。墙钟各只有一条原运行记录，不能据此认定因果开销或一般性能。缓存来源占比以全部已分类 STARTED 为分母，不是候选采用率。C 保留原截尾终态，取消产品不纳入交付比较。[原值与逐产品迟交](docs/public_results/README.md#策略与交付)。

### 协作分支省人时，交付收益取决于具体条件

<img src="figures/p07/r4/P07-R4-01-mechanism-contrast.png" alt="机制配对图：两种疲劳条件下分支人时均减少约68%，只有高初始疲劳下接收提前" width="100%">

顺序人机协作模式（HR）使对应分支人时减少约 **68%**。末次接收只在较高初始疲劳下提前 **22.07 h**，普通初始疲劳下没有改变。分支节省没有等比例传递为整单加速。

本图全员暴露采用共同 720 h 评价窗，包含实际生命周期结束后的派生恢复尾段；接收时刻来自实际事件。两个 HR 格复用 N/H 的 EDD 运行，这是协作模式对照，不是 ADAPTIVE 策略优势，也不增加独立样本。

### 进入计划后，还要看实际执行与接收

<img src="figures/p07/r4/P07-R4-02-order-event-chain.png" alt="同一E20运行四产品的注册、首次非服务STARTED、交期、接收或右截尾终点" width="100%">

E20 同一次 r14 运行中，两个普通新增产品从注册到首次非服务 STARTED 分别等待 **52.97 / 120.88 h**，急单等待 **24.38 h**。停止时仅 P1 接收；急单 P4 尚未接收，迟交下界为 **290.73 h**。

计划采用与注册共享仿真时间戳，不代表测得现实响应延迟为零。首次非服务 STARTED 可以包含搬运；虚线连接已观察事件，不表示持续加工。[逐产品事件与截尾说明](docs/public_results/README.md#订单响应)。

### 等待与初始疲劳解释了不同的暴露构成

<img src="figures/p07/r4/P07-R4-03-time-and-exposure.png" alt="普通EDD活动构成：WAIT占日历可用人时91.06%，占实际模型暴露68.98%" width="100%">

普通 EDD 的实际生命周期内，WAIT 占日历可用人时 **91.06%**、占模型暴露 **68.98%**。模型在 WAIT 中按 +0.02 F/h 累积疲劳，在 REST/OFF_SHIFT 中按 0.2 F/h 恢复。这些比例提示应检查等待安排和模型假设，不能单独证明生产瓶颈或真实生理负担。暴露分母包含实际恢复阶段。

<img src="figures/p07/r4/P07-R4-04-initial-fatigue-window.png" alt="十五人首日平均疲劳和新增暴露分解：99.02%的新增实际暴露发生于首24小时" width="100%">

N/H 的 EDD 配置仅初始 F 从 0.2 改为 0.6。实际全生命周期新增暴露 **63.81 F·h**，其中 **99.02%** 来自首 24 h。曲线保留全部区间端点和恢复至零折点，均值曲线积分乘 15 与逐人积分相符。两个贡献窗口长度不同，柱表示总暴露量，不是单位时间率。[活动账与窗口积分](docs/public_results/README.md#人员时间与暴露)。

### 动态人员与取消需要明确分母

| 问题 | 实际记录 | 解读 |
| --- | --- | --- |
| 还有多少可用人员时间？ | CPU 检查点中 W1 在场与可用均为 0.2597 h；普通人员分别为 6.1990 / 5.6990 h | 可用量取在场、日历、资格有效期与人员状态的交集，不等于未占用的空闲时间。相同分母的 13 人合并展示。 |
| 取消前已经消耗什么？ | 每运行退回 28 lot、STEEL 3.318 t，已耗 0.7473 人时和 96.10 m 搬运 | 空返 61.30 m 已含在搬运中；缺少货币策略参数的成本仍未知。 |

原 C 运行保持 720 h 截尾；最后一条已记录取消命令的完成时间不能证明精确清理耗时。[人员分组与取消资源账](docs/public_results/README.md#图表与数据)。

<details>
<summary>完整人员轨迹与资源所有权记录</summary>

![归档的十五人实际生命周期疲劳轨迹](figures/p07/r3/P07-03b-all-person-fatigue.png)

完整人员图支持检查首日均值之外的个体过程，保留恢复至零折点与原实际生命周期。

![代表运行中全部设备与工装的所有权区间](figures/p07/r3/P07-03a-resource-gantt.png)

所有权区间表示资源何时被持有，也保留某案例中没有持有区间的资源。它不等于持续加工时间，也不能建立瓶颈因果关系。[指标定义](docs/metrics/p07_metrics_definition_r3.md)。

</details>

## 已知限制与未完成目标

状态快照：**2026 年 11 月 2 日**。功能阶段收口与原始全项目目标使用不同的验收范围。

| 范围 | 仍存在的限制或有限收口边界 |
| --- | --- |
| 策略有效性 | 固定研究未建立 ADAPTIVE 的普遍优势。每方法九个未取消且已接收的产品运行记录全部迟交，唯一可分辨的总暴露差很小。 |
| 实时性能 | 2 s 源龄未达标，持续 4 Hz 未建立，稳段及 10/s、50/s 资格不足。桌面阶段按负责人批准的有限功能范围收口。 |
| 动态完成与 WIP | 原 E20 停止时仅 1/4 接收；WIP/J3 HOLD 的剩余完成未建立。正常完整 CPU 案例和已保存局部检查点不能填补这些缺口。 |
| 原生生命周期 | 加入异步截图屏障后，选定的保存/关闭路径通过；历史 621.01 驱动下 K01 根因仍 OPEN，本次并未修 SDK 或驱动。 |
| 手动操作与验收 | 手动 REST、负责人操作检查与最终联合验收仍待完成；P08/P09 未启动。 |
| 工业适用性 | 应用域仍为仿真研究。USD 运动学读回不能证明工业动力学或安全认证，工业 G2 仍 OPEN。 |
| 成本与测量 | 部分案例缺少货币策略；CPU 时间和峰内存未记录。未知值保留未知，不填零。 |
| 前端依赖 | 锁定工具链的 2026-11-01 审计仍记录一项 Vite high 依赖告警，本次未升级依赖；见[审计与部署范围](docs/public_validation/toolchain_advisories.md)。 |

[失败与修复记录](docs/public_validation/failures_and_repairs.md)、[桌面有限收口](docs/validation/P06_2_limited_scope_completion_r1.md)和[项目状态](docs/public_results/status.md)保留原验收边界与证据。

<details>
<summary>重要失败与后续修复的范围</summary>

| 记录 | 修复或收口 | 继续保留的事实 |
| --- | --- | --- |
| 原生关闭挂起 | 增加异步截图屏障，之后选定的原生关闭成功返回 | 原失败运行和历史驱动崩溃根因仍保留 |
| 保存计划引用检查 | 有限修复后拒绝错误版本、跨运行计划与空引用副本 | 修复未改变调度结果，也未删除原误通过证据 |
| P07 分析与导出 | 修复恢复至零的绘图折点、结果校验、取消账及展示行/计划行标签 | 旧结果、旧图和审阅发现仍可追溯 |
| 首次 G07 发布 | Git 换行归一化导致 108 个活动摘要失配，r2 用字节保全属性和回归修正导出 | r1 标签、失败检查与取消的 CI 保持 |

[P06 失败](docs/public_validation/failures_and_repairs.md) · [P07 修复](docs/validation/P07_limited_repair_r1.md) · [G07 发布记录](docs/validation/G07_publication_r1.md)。

</details>

## 开发与验证

与 CI 相同的 CPU 检查入口：

```powershell
uv run --locked --no-cache --no-editable --reinstall-package adaptive-hrc-scheduling python scripts/check.py
```

单独执行 P07 检查：

```powershell
uv run --locked python -m unittest discover -s tests -p 'test_p07*.py' -v
```

已发布基线为 `4158ba0` / `step-P07-r2`，其 Ubuntu/Windows 源码与隔离 wheel 四轮 CI 每轮 1273 项。前一版本地展示候选的源码/隔离 wheel 各 1276 项通过。本轮双语 README 修订使用独立的本地核验与包回执，**尚未发布**，不声称有新的远端 CI。见[当前候选记录](docs/delivery/g07_presentation_candidate_r2.json)。

```text
src/adaptive_hrc_scheduling/   生产模型、契约、调度与执行
scripts/                     生产、审计与桌面入口
desktop/p051/                Qt / React 工作台
sim/                         Isaac 场景与读回适配
analysis/p07/                离线分析、验证与图表
examples/reproduction/        配置与派生再生测量输入
docs/                        指南、模型定义与证据
```

反馈问题时请附版本、复现步骤、实际终态与相关日志。贡献应保留已有断言、失败记录与证据范围；通过 [GitHub Issues](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/issues) 讨论改动。

## 文档

详细指南目前使用简体中文；英文主 README 提供项目的英文入口。

| 主题 | 指南 |
| --- | --- |
| 安装与 CPU 执行 | [环境安装](docs/setup.md) · [生产与保存重建](docs/public_validation/reproduction.md) |
| 桌面交互 | [工作台操作](docs/public_workbench/usage.md) · [交互案例](docs/public_workbench/interaction_cases.tsv) |
| 模型与契约 | [生产规范](docs/model/specification.md) · [动态后端](docs/public_backend/README.md) · [共享交互契约](docs/public_delivery_r2/interaction_contract_r3.md) |
| 研究证据 | [结果与再生指南](docs/public_results/README.md) · [指标定义](docs/metrics/p07_metrics_definition_r3.md) · [公开输入清单](examples/reproduction/p07/r3/manifest.json) |
| 范围与来源 | [项目状态](docs/public_results/status.md) · [证据汇总](docs/public_validation/evidence_summary.json) · [图像来源](docs/public_validation/visual_provenance.json) |

## 许可

代码采用 [MIT License](LICENSE)。模型假设、图像来源与数据范围随对应证据文档提供。
