# 研究结果与再生

这组材料包含固定情景的比较结果、动态人员与订单记录、取消物料账和同观察双域导出。运行身份、来源版本、实际生命周期及评价窗口分别保留。当前为本地 G07 候选，尚未发布；克隆命令适用于包含本目录的候选源码或后续经批准发布的版本。

## 重算结果

从项目根目录运行，使用Python3.12.13、uv0.12.3；PowerShell7示例：

```powershell
uv venv --python 3.12.13 .local/results-env
uv pip install --python .local/results-env/Scripts/python.exe -r analysis/p07/requirements.txt
& .local/results-env/Scripts/python.exe analysis/p07/reproduce.py replay --figures --output .local/results-demo
```

输出目录须不存在或为空。12份压缩输入来自已保存运行的测量特征；再生会重算固定指标、配对、动态人员分母/费用、取消物料/已耗资源账和图表，并使用与正式分析相同的数值门禁。原E20已提取链按独立来源参考核对，双域保存件按摘要与同观察契约核验；它不重新执行原生产或Kit过程。

复现过程禁止打开原私有`.local`档案，只允许指定输出目录与当前解释器环境。历史路径仅作来源定位。分析工具使用独立的纯算术模块，函数与原运输/占位实现的AST一致，不依赖未随包分发的历史研究脚本。

## 图表与数据

| 内容 | 查看图表 | 对应数据 |
| --- | --- | --- |
| 反馈与证据链 | [原生Mermaid架构](../../figures/p07/r3/P07-01-feedback.md) | [来源注册表](../delivery/p07_source_registry_r3.json) |
| 五情景、两方法 | [原值图](../../figures/p07/r3/P07-02-scenario-values.png) | [原值](../../results/p07/r3/summary.csv) · [45行配对指标](../../results/p07/r3/pairs.csv) |
| 资源与人员 | [资源甘特](../../figures/p07/r3/P07-03a-resource-gantt.png) · [全员疲劳](../../figures/p07/r3/P07-03b-all-person-fatigue.png) · [动态分母](../../figures/p07/r3/P07-03c-dynamic-denominators.png) | [逐人](../../results/p07/r3/people.csv) · [活动](../../results/p07/r3/activity.csv) · [动态人员](../../results/p07/r3/dynamic_people.csv) |
| 故障、急单与取消 | [响应时间线](../../figures/p07/r3/P07-04-response-timelines.png) · [取消尾段](../../figures/p07/r3/P07-04b-stock-cancellation.png) | [E20订单](../../results/p07/r3/e20_orders.csv) · [采用变化](../../results/p07/r3/e20_plan_changes.csv) · [取消账](../../results/p07/r3/cancellation_accounts.csv) · [物料去向](../../results/p07/r3/cancellation_materials.csv) |
| 四机制与计算账 | [四机制](../../figures/p07/r3/P07-05a-four-mechanisms.png) · [计算成本](../../figures/p07/r3/P07-05b-computation.png) | [阶段](../../results/p07/r3/stages.csv) · [机制](../../results/p07/r3/mechanisms.csv) · [计算账](../../results/p07/r3/costs.csv) |
| 甘特与场景域 | [三组导出清单](../../results/p07/r3/exports/manifest.json) | 各组目录包含gantt/scene-domain JSON、行/人员/设备CSV及原显示缓存 |

静态图同时提供300dpi PNG、可编辑SVG、PDF和来源sidecar，见[图表清单](../../figures/p07/r3/manifest.json)。资源图按预先选定的N/F/C代表制图，完整统计仍覆盖12单元。疲劳图显式保留恢复至0的折点，并核对图线积分与相同窗口E。

当前五情景的末次非取消产品接收时刻在两方法间相同；多数配对没有收益，U的共同窗总暴露差约−0.001013F·h，不能推断普遍优势。四机制中的两个HR格引用N/H的EDD运行，不增加独立样本。P043两个人员检查点窗口不同，不作跨案例方法效果。完整数字及单位见[指标定义](../metrics/p07_metrics_definition_r3.md)。

取消STOCK账按物料类型和单位列available/consumed/converted/scrapped/returned，保留原720h截尾。已耗人时仅统计命令可归属的实际人员区间，搬运按实际root/resume链去重；未分配的等待/休息不摊给取消单。没有原货币策略时金额仍为UNKNOWN。末态清理核对不制造精确清理完成时刻，也不替代原WIP/J3剩余完成问题。

## 来源与验证

- [输入与来源](../delivery/p07_source_registry_r3.json)、[结论索引](../delivery/claim_evidence_r3.tsv)、[需求绑定](../delivery/feedback_metric_binding_r3.json)连接运行、配置、目录、窗口、数值和图表。
- [正式数值核验](../../results/p07/r3/validation.json)检查独立区间积分、图线面积、动态分母扫描、汇总/配对、原E20参考、取消物料守恒、CSV/JSON及双域行分类。
- [最小输入清单](../../examples/reproduction/p07/r3/manifest.json)记录每项输入摘要。输入是可审的派生测量材料，不是原完整执行档案。
- [原失败与截尾](../../results/p07/r3/attempts.json)保留原四次尝试；[有限修复报告](../validation/P07_limited_repair_r1.md)保留本次修复及坏副本拒绝证据。

总甘特展示行为24680/2676/5241，其中完整计划展示行为1023/2046/2046，其余是实际事实、人员区间、标记或未安排记录。三维文件为保存的场景域数据，不表示新增原生渲染或同步截图。

软件与程序性方法参考：Timothy Kassis等（2026），[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065)。该引用用于工作流说明，项目结果由上述实际数据支持。
