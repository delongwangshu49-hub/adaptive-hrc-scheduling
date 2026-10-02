# C04-1.0 建筑契约与历史接口

2026-10-02；建筑契约已实现。`domain/building.py`定义十类不可变消息，`contracts/building.py`负责严格编解码及语义校验；生成器为`scripts/build_building_contracts.py`，产物为`schemas/building/`与`examples/building_contracts/`。运行时标准库，无新增锁定依赖。

时间h、率h⁻¹、暴露F·h、质量t、长度m；字段必填，无值为null。拒绝重复JSON成员、未知字段/版本、bool冒数值、非有限量、悬空引用、跨产品材料、错误角色及冻结DAG漂移。资格包含来源类别、状态与修订绑定；UNKNOWN不成为PASS，资格修订改变使既有绑定拒绝。源对象往返与生成物一致；Schema仅结构，Python语义校验仍必须执行。

| 消息 | 建筑实现与权限 |
| --- | --- |
| Configuration | 产品/BOM、组件、37活动/40边/39模式、逐人角色/日历、工作面/资源、资格/版本、参数来源 |
| PlanningInput | 仅已观察产品及其活动的静态投影和观测/预算；无未来订单及HiddenScenario |
| PlanningObservation | sampled/received/observed时刻、已见产品/进度/人员/不可用资源；缺失为null或部分表 |
| Plan | 待提交命令、预测就绪和INCOMPLETE/CANDIDATE；不写实绩 |
| DispatchCommand | ID、期望状态版本、活动/模式/attempt/单元与具名角色；执行时再原子核验 |
| ExecutionEvent | 稳定ID、实际时刻、实体/attempt、原因和结构化细节；历史不覆盖 |
| ExecutionSnapshot | 完整执行恢复状态、配置摘要、时界、物料/组件/产品、F/E、锁/驻留、事件/命令消费、延迟观测和服务承诺；含隐藏事实，不传规划器 |
| HiddenScenario | 执行专用外生事实；重复ID和同刻矛盾故障/修复拒绝 |
| OfflineEvaluation | 全产品/全人员窗口摘要、未完成/取消计数；明确不是S10独立绩效核算 |
| RunManifest | 配置摘要、规格/代码/种子、后端、终止状态、资格缺口与NOT_ESTABLISHED |

旧`S06-1.1`与建筑`C04-1.0`互不自动转换；旧源码、Schema、生成器和样例仍保留原入口，旧结果不能当建筑验收。新版字段不会塞入旧单人Allocation。C04-1.0已随r1发布；r2不改变字段、Schema或样例形状，收紧原冻结规则的语义校验。原先错误接纳的配置/恢复输入将被拒绝。

```python
from pathlib import Path
from adaptive_hrc_scheduling.domain.building import Configuration
from adaptive_hrc_scheduling.contracts.building import loads, dumps
config = loads(Configuration, Path("examples/building_contracts/configuration.json").read_text(encoding="utf-8"))
assert loads(Configuration, dumps(config)) == config
```

默认样例为RESEARCH_BLOCKED；受控测试夹具明确SYNTHETIC_TEST_ONLY，不能作为工业输入或模式收益依据。实际检查和限制见[建筑执行验证](validation/building_execution.md)。

## r2有限语义修复

配置必须保留冻结的7个质量门、5个等待/释放门、劳动单元、模式类别及必要设备；移动实体与落位数和单元时长一致，不能用null或空列表关闭必需门。恢复时核对产品/组件实际位置与驻留账的双向一致：稳定占位、搬运源位、目标预留、owner、预留标记及逐次落位进度必须匹配。J2按产品owner计容量，BUF按子框计数；FIX-J2设备锁独立检查。

此校验针对当前建筑执行表达与已列反例，不是S10从日志独立重建全部规则的检查器。执行/API边界见[建筑执行验证](validation/building_execution.md)。

## 历史 S09 r2 管道实现参考

以下原文只解释旧运行接口，历史批准不延伸到建筑域。

# S06 数据对象与接口契约

版本 `S06-1.1`，2026-10-01。本接口依据已接受的 S05 r2 基线及 r3 补充；发布事实见 LOG031。它定义数据、静态校验与序列化，尚无疲劳积分、事件推进、仿真或调度器。S06 候选状态见 [步骤卡](steps/S06.md)。

## 使用与验收边界

实现位于安装包的 `src/adaptive_hrc_scheduling/domain/` 与 `src/adaptive_hrc_scheduling/contracts/`，沿用项目包布局，不另建同名顶层 Python 包。Operation 是本版工序任务；Phase 是其模式内阶段。

```python
from pathlib import Path
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.contracts.codec import loads, dumps

config = loads(Configuration, Path("examples/contracts/toy.json").read_text(encoding="utf-8"))
assert loads(Configuration, dumps(config)) == config
```

`loads`、`dumps`、`validate` 是校验边界。直接构造 dataclass 不代表对象已被接受；发送或保存前须经过边界。所有对象 frozen，集合用 tuple；修改用新对象表达。解析、字段和语义错误统一为 `ContractError`，拒绝未知字段、遗漏字段、重复 JSON 成员、错误类型及未解析引用。整数不接受 bool、字符串或浮点数；实数不接受 bool、字符串、NaN、Infinity 或溢出。

公开 [schemas](../schemas/Configuration.schema.json) 为生成的 JSON Schema Draft 2020-12 **结构**契约；跨引用、DAG、资格、组身份等语义仍须调用 Python 校验，不能只通过 Schema 就宣称实例合法。Schema 与实例由 [生成入口](../scripts/build_contract_examples.py) 同源生成并在测试中逐字节比对。运行时仅用 Python 标准库，没有新增运行依赖。

## 配置与物料

| 对象 | 明确表达的语义 |
| --- | --- |
| Order | 稳定 ID、流程族、释放/交期、正权重、全部必需成品 ID |
| Operation / Mode / Phase | 工序 DAG、合法 H/R/HR 模式、阶段 DAG、正基础工时、主动角色、人员活动、耗时敏感性、重做/续作、取消边界 |
| Resource | 人员技能和参数；机器人能力/可达站点；单容量设备、独立工位、绑定夹具；有限分类缓冲、接收槽和显式无限终端 |
| Allocation | 显式枚举的 Q 元组；所需人员、机器人、设备、工位/夹具、吊机/路线引用；不用的角色为 null |
| Material | 单一生产者/消费者、件型、数量、可能存放位置、释放边界、运输方式；源工序也有显式 raw 输入 |
| TransferGroup / Route | 每件模块独立运输组、固定源/目标路线、五段正工时、目标工位/夹具；组内 rig/unload 使用同一元组 |

资源数不写死在模型中；主线吊机数为一。资格必须同时满足技能、设备/夹具位置和机器人能力/可达性。模式引用的 Q 是已经声明的相容集合，可省略不允许的协作配对；校验器不会给调度器扩充 Q。非空 Q 及无环图仅证明结构必要条件，不证明可调度或无死锁。

加工组、运输组的稳定 ID 分开。计划和执行绑定不能在阶段间换人或站点；ASSEMBLE 公共 setup 后可按模式增减机器人，WELD 模式切换保留原机器人；已选运输端点必须与已选源/目标加工站相符。`held_roles` 描述设备/工位保持规则；快照锁按同一 owner 的主动/保持占用取并集。目标汇合站的站锁由接收加工组持有，各接收槽另记，不能把每次入料误当成另一个加工站占位。

F3 校验按共同目标对每件输入的可达来源做互异匹配；来源和目标互异，目标无需同时属于来源候选集合。两个专用来源站加一个独立接收站可以合法。F3 每个模块输入有独立 TransferGroup，目标需足够有限接收槽，声明全部槽预约及等待最后 reset。备料 feed 用显式空间资源，全部输入由工序 input_ids 声明。执行时的原子领取、槽预约转占位、源位在 rig 后释放以及死锁检测属于后续执行内核；这里校验其结构及引用，不推进这些动作。

正常 pipe/bracket 输出必须进入有限分类 buffer，module 绑定生产站，raw/finished 对应声明用途的终端。无限终端的 accepted_materials 只能声明 raw、finished、scrap；快照中正常备料不能借原料/成品终端绕过缓冲。废料终端只用于明确 scrapped 状态。

装配和焊接的可切换模式须具有兼容 setup：比较实例 duration_overrides 生效后的时长、活动/主动角色、前序、准备标记及持有角色，拒绝同名但不同成本的公共前缀。

## 单位、ID 与 JSON

- 仿真时间和基础工时为 min，活动/恢复率为 min^-1，F 与 κ 无量纲，暴露积分为 min，容量为 count。每份独立消息声明 Units；PlanningInput 通过内部配置与观测声明单位。决策墙钟预算单独命名 `decision_budget_ms`。不会自动把秒当分钟转换。
- 输入 ID 为 ASCII，首字符字母，后续允许字母、数字、下划线、点、冒号和连字符，长度不超过 160。配置中资源、路线、元组、模式、订单、工序、物料、组的 ID 全局唯一；阶段 ID 在模式模板内局部唯一。
- 实际阶段身份由 `(operation_id, group_id, phase_id, attempt, restore_sequence)` 决定。`phase_execution_id` 对固定 JSON 元组生成 SHA-256 ID，避免分隔符歧义和长度溢出。续作保留身份；work 重做才递增 attempt；新 restore 递增 restore_sequence，其中断续作不增号。
- UTF-8 无 BOM、LF、键排序、两空格缩进、末尾换行；数组顺序保持不变。实数归一为有限 Python float，往返保证类型化数据语义相等，不承诺原始数字文本或任意精度十进制原样保留。摘要针对 `dumps(...).encode("utf-8")`；重新排列数组会改变摘要。
- RunManifest 的 code_revision 使用完整 40 位小写十六进制 Git 提交哈希，不用会移动的分支名或短哈希。仅 planned 结构样本允许 `example.uncommitted`。
- 每个字段必填；无值显式 null，不隐式补默认参数。`S06-1.1` 以外版本拒绝，未来语义或不兼容字段变更须新版本和迁移，不静默忽略。

## 状态、恢复与取消

ExecutionSnapshot 是执行真值，包含人员 F/积分/活动、资源故障及安全解锁标志、组绑定、阶段尝试/剩余基础工作量/已取样 F/倍率、机器人准备、物料位置、锁、预约、订单释放/取消/实际完成。PhaseState.allocation_id 保存该次历史执行的实际 Q，Binding 保存当前 Q。已完成的兼容 setup 可保留旧模式/Q；人员、设备、站位和夹具身份保持，不能改写历史以适配新模式。已启动后缀不得换模式，后缀开始不得早于公共前缀完成。完整资源、人员、订单和机器人表必须覆盖配置；阶段记录保留相关准备及尝试历史，物料表只列当前已存在实体。

`Preparation` 显式区分绑定身份与 `(operation, group, station, valid)`。运行中的机器人 work 需匹配有效准备；同站不同组也不能复用。当前组必需资源故障时不能保持有效标记。改派/故障/取消如何产生状态转换属于 S08/S09，S06 不伪称已经实现转换引擎。

`resolve_process_phase` 解析实例工时覆盖；restore 继承原 setup/align 的正时长、主动角色和人员活动，不受疲劳放大，仍有人员劳动口径。它只返回阶段描述，不启动恢复、不取物料、不修改 work 的进度/尝试号。执行快照中的 restore 必须有已完成的原准备记录，始终按 resume、attempt=1 表示；不支持递归 restore。CUT/WELD.work 为 restart，其他阶段为 resume；非敏感阶段不允许额外倍率，剩余基础净量不超过声明工时。敏感阶段保留取样 F 和倍率，后续 S07/S08 再实现与核对实际取样/积分时序。

取消通过订单标志、阶段 cancel_boundary 和独立 cleanup 派工请求表达。work 的必要 handoff、在途卸载/reset、已占用物料与故障解锁事实不能因取消从数据中省略。cleanup 命令在此层只请求处置指定物料，具体合格人员/路线获取、清场阶段展开及拒绝原因由后续执行器实现；它不是已完成的安全清场。固定工装 failure 必须显式提供 release_allowed；这不赋予吊机绕过修复/卸载的权限。

## 信息权限与消息

| 契约 | 内容与权限 |
| --- | --- |
| PlanningObservation | 已观察订单事实、资源估计、事件 ID，以及可空的 ObservedExecution；无隐藏场景、完整真值快照或 J_eval 字段 |
| PlanningInput | observation 加仅包含已观察订单的静态配置投影；保留已观察取消订单供清场；共同静态资源目录可见 |
| Plan | 引用本次观测、阶段安排及 Q、计划时段、原因；实际 C 与预测 Ĉ 分列；完整 K_t 覆盖，不能删除不利订单；D 的预测暴露与预算独立 |
| DispatchCommand | start/resume 的立即派工、正时长 rest/wait、指定物料 cleanup；计划安排不是实际开始证据 |
| ExecutionEvent | run/event ID、实际 sim_time、实体、阶段身份、前后状态码和原因；与执行快照配套，不用 planned 时间替代 actual |
| HiddenScenario | 外生释放/取消/故障/修复清单与场景种子；仅世界/离线端持有；同资源同刻矛盾故障/修复拒绝 |
| OfflineEvaluation | 共同窗口、离线场景、J_eval、实际完成及全体人员暴露、排空/截尾和预算违反；不含求解器打分入口 |
| RunManifest | 配置/场景/依赖锁摘要、代码修订、场景/决策种子、算法和后端、墙钟预算、共同 cap/窗口、暂停仿真策略及终止状态 |

`planning_input(config, observation)` 在入口验证授权时间戳，剔除未观察订单及其工序/物料。调度器未来只接收该投影，不能接收完整 Configuration、HiddenScenario、ExecutionSnapshot 或 OfflineEvaluation。加载器为核对引用可持有完整配置，这一权限不能传入决策层。单靠 Python 数据类型不能阻止任意代码读文件，观测授权真实性及执行隔离由 S08 及后续集成验证。

ObservedExecution 是授权的执行观测帧，含 sampled_min、received_min、阶段进度/实际 Q、当前绑定、锁、物料位置、预约和准备状态。要求 sampled_min≤received_min≤as_of_min，阶段开始/完成不晚于采样，订单/物料必须已进入授权视图，所有引用自洽。帧可缺省为 null，各表允许部分记录；缺失表示未知，不能当作资源空闲或阶段未开始。保留的阶段所依赖绑定及机器人 work 的准备记录须齐全。共享值类型不意味着可把 ExecutionSnapshot 整体传给规划器；观测生成、噪声/延迟、来源真实性和更新机制留待 S08。事件 ID 仅作追踪，不承担未声明的状态解析职责。

K_t 包含已观察释放且尚未观察取消的订单。已知完成仅使用实际 C，未完成 candidate 必须给 Ĉ；无法形成完整候选用 incomplete 并保留相应 null 条目。candidate 是候选数据状态，不意味着已验证排程可行。离线 J_eval 由共同窗口内释放且无取消请求的订单确定，窗口外取消不删订单；未完成记录 null，截尾不能写成最终绩效。S06 不计算目标、积分、最优值或算法效果。

评分成员资格与动作许可分开。已知完成订单仅能安排观测支持的剩余 reset；取消订单可保留已提交阶段的续作、work 后必要 handoff、已吊起物料的 move/unload/reset，以及已 preposition 的空载 reset。观测必须提供同组/同 Q/同模式的执行依据；续作保留当前阶段的尝试号，后续 handoff 使用自身尝试号，不继承 work 的重做次数；缺失依据、重复已完成收尾和新正常生产仍拒绝。这里验证的是候选收尾结构，计划未来阶段不等于立即允许派工；实际安全边界、失败解锁、先后次序和资源获取仍由执行器复核。cleanup 请求继续由执行器展开，未来预测必须计入其资源与暴露成本，不能因订单离开 K_t 而省略。

RunManifest 加载时，将 configuration_sha256 与传入配置的规范化 dumps SHA-256 比对。场景和依赖锁仅传摘要、未传内容，此边界只验证其摘要格式；未来运行归档须另行比对实际文件，不把格式通过称为完整性已验证。

## 1.0 到 1.1 的迁移

本修订新增必填 PhaseState.allocation_id、PlanningObservation.execution，并要求终端声明用途；所有顶层消息统一标识 S06-1.1，旧版本明确拒绝。调用方须从历史事实补入每阶段实际 Q，不能一律复制当前绑定；观测未知时显式填 null，不能猜造进度。终端用途按业务声明，重新生成配置及其摘要；旧快照和审阅证据不原地转换。生成器只迁移仓库手工样本，历史运行数据若不能恢复真实分配，应保留旧格式并标明不能自动迁移。

## S05 示例迁移

原 [toy_instance.json](../examples/toy_instance.json) 与 [structural_instance.json](../examples/structural_instance.json) 保持字节不变。新文件在 [examples/contracts](../examples/contracts/toy.json)，另有 [扩展配置](../examples/contracts/structural.json)。十类顶层契约均提供结构 Schema；两份配置及其余九类示例共十一份 JSON。事件和离线结果示例均是手工结构样本，未发生仿真；manifest 明确 planned，plan 明确 incomplete。

转换脚本只处理这两份已知规格样本，不是通用实例/实验生成器。T0 的订单数、人员资格、状态参数、工时、缓冲容量、交期/权重和 40 min 窗口保留；原执行见证及积分不复制进配置。工序局部名 C1/B1/A1/W1/I1/L1 对应 CUT/BRACKET/ASSEMBLE/WELD/INSPECT/LIFT；站点 CS1/PS1/AS1/WS1/IS1 对应原 Z_CUT/Z_PREP/Z_ASSEMBLE/Z_WELD/Z_INSPECT，设备/夹具随站点明确重命名。W1/W2 与 R1 保留，Z_FEED/Z_LIFT 对应 FEED_ROUTE/LIFT_ROUTE，备料缓冲对应 PIPE_BUFFER/BRACKET_BUFFER。

扩展样本展开三个不同 DAG、12 单、96 工序、52 个模式选择节点、6 人及 3 机器人，参数档和 F2/F3 工时覆盖保留。显式新增 raw 实体、稳定组 ID、Q 枚举、阶段模板及运输连接；原文自然语言相容规则被展开为可校验结构。原样本无额外人机配对排除；其他配置可限制 Q。取消清场成本和 restore 取自既定 S05 参数/语义，不凭空新增实验参数。

```powershell
uv run --locked --no-editable --reinstall-package adaptive-hrc-scheduling python scripts/build_contract_examples.py
uv run --locked --no-editable python scripts/build_contract_examples.py --check
uv run --locked --no-editable python scripts/check.py
```

首次修改源码后显式重装本地非 editable 包，避免使用 uv 的旧构建缓存。生成器无 `--check` 时只写 S06 示例与 Schema；不会修改 S05 输入。核验范围及限制见 [检查摘要](validation/contracts.md)。
