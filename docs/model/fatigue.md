# 钢模块逐人人因、日历和长工时规则

版本 C03-0.3；2026-10-02；研究规格FROZEN_WITH_GAPS（PR069），C04/C05已实现合成代码见证。参数唯一入口为[参数表](parameters.md)。F是合成状态，cap是模型保护线，E是累计状态暴露；不解释为临床疲劳或人体安全认证。

非休息段：F1=F0+aΔ，ΔE=Δ(F0+F1)/2。显式休息/离岗段u=min(Δ,F0/b)，F1=max(0,F0−bΔ)，ΔE=u(F0+max(0,F0−bu))/2；触零后面积0。全部区间连续覆盖共同窗口，空档不能隐式当休息。工作、监督、受约束等待、休息、离岗分开编码；机器人自主运行不决定人员状态，取决于该人的真实安排。

每位人员独立积分及保护。多角色人工工作单元耗时d=d0(1+κ max F_i,start)，该单元起点固定倍率；角色人数不线性提速，续作保留倍率和净剩余量。合格交班先保存已完成单元，0.1h同时占交出/接入人并积分，必要恢复0.1h，下一完整单元才用接入者F取样；不可中断单元中不得换人重取样。

逐人班次为每日0–4、4.5–8.5h的工作窗，午间及离岗明确恢复。人员在工作窗内仍需满足所有连续段及安全收尾的cap；工作窗外不允许新劳动，工艺等待可继续，需监督的等待则必须换合格值守。换天、故障、换产品不清零F或累计E。

工艺停点见[钢规格](selected_steel.md)。0.5h为合成基础单元，最大倍率1.4时单元0.7h；若该工艺没有合法0.5h单元，报告UNQUALIFIED_CHECKPOINT，不能数值切段。启动预测每个人到下一合法停点和必要安全尾部；不足则不启动。悬吊故障没有安全收尾路径时记录EMERGENCY_HOLD，不伪造可休息。

局部有理数见证H-D1：W1从F0=0.2开始，焊接基础0.5h、κ=0.5，实际0.55h、a=0.15，终F=0.2825，E=0.1326875 F·h；随后显式休息至T=2h，触零需1.4125h，恢复面积0.199515625，总E=0.332203125、终F=0。反例F0=0.75时同段实际0.6875h，终F=0.853125>0.8，必须在启动前拒绝。该局部算例尚不是完整建筑执行或D实验。

D以共同cap/人员集合/窗口报告ΣE、max E、逐人峰值及交付，不以平均掩盖个体。每个实际等待/休息/故障尾部均保留，取消样本也计算暴露。独立检查设计见[建筑见证](../validation/building_witnesses.md)。


## 现行 S09 r2 管道实现参考

以下原说明保留用于运行和回归；历史“本步/待审”只指原快照，不是建筑规范或当前批准状态。历史发布见LOG049，新领域见[总纲](../PROJECT_CHARTER.md)。

# S07 疲劳与恢复数值模型

治理版本 0.9.0；2026-10-01。依据已接受的 S05 r2 基线及 r3 补充、S06-1.1 类型实现。工作状态与验收边界见 [步骤卡](../steps/S07.md)，核对结果见 [检查摘要](../validation/fatigue.md)。参数继续使用配置中每位人员的 `WorkerParameters`、共同 `fatigue_cap`、`protective_rest_min` 和 `observation_window_min`，不新增另一份参数默认值。

实现为安装包的 `adaptive_hrc_scheduling.human_state`，仅使用标准库。它提供不可变数值结果，不产生事件、分配资源、创建尝试号或生成观测。现有 S06 Schema、序列化格式和 S05 原始示例不变。

## 方程与口径

时间为 min，活动率和恢复率为 min⁻¹，F 无量纲，暴露 E 为 min。所有参数仍是项目选择、合成假设或未校准值，不能据此推断人体安全或实验效果。

对非休息活动 l，持续 Δ≥0：

\[
F_1=F_0+a_l\Delta,\qquad
\Delta E=\Delta(F_0+F_1)/2.
\]

`work/collaborate/carry/supervise/wait` 分别取配置中的率。普通活动率允许零；wait 的率必须为正。无主动阶段且未安排休息时，调用方必须显式记录 wait；不能用 rest 替代。handoff 和 restore 按其阶段活动计入负荷。

显式 rest 使用 b>0，令 u=min(Δ,F₀/b)：

\[
F_1=\max(0,F_0-b\Delta),\qquad
\Delta E=u(F_0+F_1)/2.
\]

触零以后面积为零，不能将整段休息按两端点直接作梯形。状态上的历史 `exposure_min` 加上本段面积；故障、换任务、重做不隐式清零。零时长返回等值状态，不改变活动字段。

合法输入及轨迹要求 0≤F≤cap<1，cap>0。`evolve` 遇到超限抛出 `FatigueLimitError`，不返回裁剪后的状态。即使随后休息降回 cap 以下，中间超限仍拒绝。布尔冒充数值、非有限数、负时长、非法活动、非法参数或算术溢出均拒绝。

## 数值 API

| API | 输入与结果 | 职责边界 |
| --- | --- | --- |
| `evolve(state, parameters, activity, duration_min, cap)` | 新 WorkerState、本段积分、本段峰值（含起点） | 不推进仿真时钟、不自动休息 |
| `time_to_cap(fatigue, parameters, activity, cap)` | 恒定活动下首次接触 cap 的时长；无接触返回 None；已在 cap 返回 0 | 提供保护事件的数值时界，不调度事件 |
| `protective_rest(state, parameters, cap, minimum_min)` | 严格正时长的显式休息结果 | 执行器应传配置最短休息；休后重新检查，必要时继续休息 |
| `sample_phase(phase, parameters, fatigue, cap)` | 本次取样 F、固定倍率、整阶段净时长 | 用于首次启动或合法重做；不判定重做是否合法 |
| `remaining_duration(phase, parameters, progress, cap)` | 剩余基础量乘已存倍率 | 续作不接收当前 F；核对原 sample/倍率一致性 |
| `process_start_allowed(config, operation_id, mode_id, phase_id, state, ...)` | allowed 和统一原因码 | 仅加工阶段的疲劳数值保护，不是派工许可 |
| `evaluate_window(config, timelines, drained_min=...)` | 全员逐段轨迹、E_total、E_max、F_peak、截尾标志 | 核算提供的活动历史，不生成生产排程 |

配置先通过 S06 的 `loads`/`validate` 边界；阶段用 `resolve_process_phase` 取得实例工时覆盖及 restore 描述。函数仍校验直接接收的人员参数、状态和数值。内部结果 dataclass 不是新增跨进程消息，不写入 S06 JSON Schema。

```python
from adaptive_hrc_scheduling.domain.state import WorkerState
from adaptive_hrc_scheduling.human_state import evolve

# config 为已经通过 S06 校验的配置。
worker = next(r for r in config.resources if r.kind == "worker")
p = worker.worker_parameters
state = WorkerState(worker.id, p.initial_f, 0.0, "wait")
result = evolve(state, p, "rest", config.protective_rest_min, config.fatigue_cap)
```

## 阶段耗时、续作与重做

敏感阶段在实际起点取样：d=d₀(1+κF_start)，κ≥0。阶段内 F 继续变化，倍率固定；HR 的人机共享这一段 d，不叠加另一段机器工时。非敏感阶段 d=d₀，sample 为 None、倍率为 1，人的活动仍正常积分。

PhaseState 的剩余量以基础 min 表示：续作净时长为 `remaining_base_min * speed_multiplier`。`remaining_duration` 拒绝缺 sample、倍率不符、非敏感阶段带 sample、零/超额剩余量、failed/completed 状态或已有完成时间。它不负责中断事件合法性、尝试号递增、加工量扣减或历史状态转换；这些留给 S08/S09。

首次启动和重做通过 `sample_phase` 对完整 d₀重新取样。需要 restore 时，先积分 restore；新 work 再以恢复后的 F 取样。续作则继续使用中断前倍率，restore 只增加实际耗时、F 与 E。restore 继承实例原 setup/align 的成本及活动，不重新领取物料，也不改 work 的剩余量或尝试号。

## 可独立核对的保护

`process_start_allowed` 按已校验阶段的取消/安全边界推演：普通准备、align、restore、handoff 和 INSPECT.work 到当前阶段末尾；标记 `handoff_then_clear` 的 work 自动包含必要 handoff。`restore_required=True` 时自动在机器人 work 前加入 restore。调用者不能通过只传 work 而省去 handoff。

暂停记录可通过 progress 提供，核对工序/模式/阶段、组、实际 Q 和人员身份后使用原倍率与剩余量。机器人独立工作期间，绑定人员在这次保护预测中按 wait 计费；不假定其得到休息。若执行器安排其他活动，应另行逐段检查真实活动。

任一段超过共同 cap，返回 `allowed=False, reason="FATIGUE_PROTECTION"`；不向规划端回传隐藏 F、轨迹、违例位置或计算出的恢复时间。保护函数可在执行端使用当前真值，不构成规划层读取 ExecutionSnapshot 的权限。ObservedExecution 缺失仍是未知，观测生成与隔离留待 S08。

该保护只覆盖已知加工劳动路径，不处理未知阻塞时长、资源获取、机器人准备有效性的发现、资格许可、运输/取消清场路径展开或安全锁止事件。后续执行器须补齐这些路径并对真实活动调用共同数值检查，不能凭本函数返回 true 就宣布完整派工合法。等待触 cap 的事件需由执行器在数值时界触发，安排至少配置 τ_rest>0 的显式休息，随后重验。此处只实现时界与正时长休息计算，没有零时事件循环或自动回退器。

## 共同窗口和误差

`evaluate_window` 要求配置中的每位人员均提供精确连续的 [0,T_obs] 区间；空档、重叠、遗漏人员、提前截断、越过窗口或零长区间均拒绝。轨迹从配置 F₀ 和 E=0 开始，不能把一段运行中途记录冒作完整窗口。调用方必须显式提供等待及尾部。

`drained_min` 是外部已核实的生产/reset/取消清场排空时刻，不能填最终到库时间代替。其后至共同 T_obs 必须显式 rest；也允许早已进入休息的区间跨越排空时刻。窗口内未排空填 None，仍积分真实活动至 T_obs，返回 censored=True。该函数不验证排空事实或订单绩效，未来 S09/S10 承担这些职责。

E_total=ΣE_h，E_max=max E_h，F_peak=max_h,t F_h(t)。区间单调，峰值取两端且包含窗口起点；休息不删除既有峰值。三者独立返回，预算判断与优化留待后续步骤。

状态和面积使用 Python float。cap 判定另以标准库有理数对输入的二进制数精确比较，避免舍入掩盖极小超限，不设置容许超限的 epsilon。`time_to_cap` 必要时向下取相邻浮点数，确保返回时长可安全积分；最大偏差为一个相邻浮点间距。十进制书写的数学等式可能因输入二进制近似而保守拒绝，调用方应使用返回时界并重新检查，不以容差或裁剪绕过保护。超出有限浮点表示的时界或积分明确报错。

测试对原始 S05 见证使用 1e-10 min/F 的绝对核对容差，对 200 组独立 Decimal 方程核对使用 1e-14。容差仅用于证据比较，不用于允许 cap 超限，也不是双后端或实验统计误差标准。

C04/C05实际实现、入口、受测范围与保留HOLD见[建筑执行验证](../validation/building_execution.md)。本文件的研究规格不因代码通过而升级工业资格。
