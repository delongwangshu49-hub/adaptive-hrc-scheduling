# S08 扰动与信息可见性规则

治理版本 0.10.1；2026-10-01。依据已接受的 S05 r2/r3 规格和 S06-1.1 契约，实现可独立测试的事件转换与观测投影。状态及发布边界见 [步骤卡](../steps/S08.md)，证据见 [验证摘要](../validation/events.md)。现有 S06 消息、Schema、样本及 S07 数值模块保持不变。

## 同刻协议与事件契约

安装包新增 `adaptive_hrc_scheduling.events` 与 `adaptive_hrc_scheduling.observation`，只依赖标准库。新增 dataclass 为进程内结果，不是新的 S06 跨进程消息。配置先经 S06 `loads`/`validate` 接受；快照入口还会复核当前状态和引用。

时刻 t 的集成顺序为：先积分及净加工推进至 t，完成/到库/释放，再按稳定 event_id 处理外生事件，随后共同保护、授权采样，最后派工。`ordered_tick` 固定五类顺序，同类按 ID 排序，拒绝重复 ID 和跨时刻批次。它只排序，不执行回调或循环。

`apply_events(config, snapshot, events)` 要求快照时钟恰等于全部外生事件时刻，且同刻完成已被调用方处理；仍 running 且剩余量为零会被拒绝。输入复用 `WorldEvent`/`HiddenScenario` 规则，同资源同刻的故障/修复输入拒绝。批次内部按 ID 执行，结果为不可变 `EventResult`，含新快照、实际应用 ID 和本次中断记录；原快照不变。调用方必须消费每个事件一次。相同输入重放相同结果，不表示把相同释放再次应用到已释放状态也合法。

释放仅改变 released 事实；取消只设置 cancelled，不删除阶段、物料、绑定、锁、疲劳、积分或实际到库时刻。同刻释放/取消依 ID 处理，释放不会清除已设置的取消标记，因此最终禁止正常生产。原料实体创建、派工和物料变换由 S09 集成承担。

| API | 已实现行为 | 调用边界 |
| --- | --- | --- |
| `phase_rule` | 解析有效加工工时及五段运输规则 | 不选 Q、不获取资源 |
| `advance_phase` | running 的已执行净时长扣减基础剩余量，抵达边界转 completed | 只推进单阶段；不积分、不搬料、不释放锁 |
| `apply_events` | 到达/取消、故障/修复、准备失效、阶段中断及锁止释放 | 先处理同刻完成，调用方保存历史及消费游标 |
| `restart_attempt` | 保留旧 failed 记录，返回 attempt+1 的新取样 work | 只在独立许可后的实际重启调用，不能作为派工许可 |
| `preparation_for` / `clear_preparation` | 服务组变更置无效、准备完成建立有效、最后机器人 work/取消退出后清除 | 调用方在对应实际边界替换机器人记录 |
| `restore_progress` | 已完成原准备但失效时分配新 restore_sequence，成本继承原准备 | 拒绝取消、资源故障、已有 running/paused restore；不获取资源 |
| `cancellation_tail` | 最近安全边界前必须保留的阶段序列及等待修复标记 | 不是立即开始许可或已经完成的清场 |
| `withdrawable_reservations` | 列出取消后在安全边界可撤的未占用预留 | 不移动物料、不撤站锁、不实际释放 |
| `offline_order_ids` | 按窗口内取消清单计算 J_eval | 只供离线端，不传给规划器 |

`advance_phase` 将浮点 `remaining_base_min * speed_multiplier` 作为此次声明的日历剩余时长；精确等于该值才完成，不用 epsilon 提前完成。更短推进按有理数差计算剩余量，跨完成时刻拒绝，调用方须切分。开始时界按 `started_min + elapsed_min <= at_min` 的前向浮点时钟检查，不用 `at_min - elapsed_min` 的舍入逆运算；更早的可表示时刻仍拒绝。暂停/故障时长不计净加工。重复分段仍使用浮点存储，不能据此声称任意分段逐位一致；疲劳 cap 继续由 S07 的严格比较独立保护，不借加工时间舍入放行超限。

## 故障、准备和成本保留

CUT/WELD.work 的当前尝试转 failed；中断记录保存丢弃的基础净进度，原始尝试、剩余量和已取样倍率保留。尚未实际重启的 failed 尝试遭遇重复故障不再次记损失。其他加工/运输/restore 转 paused，保持原尝试号、剩余量、倍率及 restore 序号。

修复只清除 failed 和 release_allowed，不自动恢复准备、续作、重取样或创建尝试。真正重做时调用 `restart_attempt`，使用当时绑定人员的 F；续作保留原倍率。restore 的完成不改变 work 剩余量和 attempt，不重复领取物料；中断 restore 续用原记录，不嵌套新 restore。

加工组必需资源故障使机器人准备失效，包括阶段间等待；机器人自身故障同样失效。准备失效与当前阶段中断分别计算：阶段使用其主动角色、声明的固定保持资源和实际占用锁；handoff 不再使用已释放的机器人。S06 要求机器人 work 保持有效准备，因此导致准备失效的组资源故障仍会中断该 work，不将此情况当作无关资源故障。改派即使仍在同站也必须重新建立对应组的准备。正常空闲和休息不调用失效转换。传输只按当前阶段所需资源和实际保持锁判断中断：rig 后来源站已释放，不再因其故障打断 move；feed 只在装配 setup 使用，已完成后不会继续阻断 work 或继承 align 的 restore。取消等待修复按剩余必要尾部及实际锁计算，已释放的运输人员/目标不再阻断 reset；固定工装解锁和吊载故障约束保留。

故障不清零 F 或 E。中断后释放相应非故障人员/机器人的 active 锁，释放人员转 wait；固定设备、工件/工位、在途吊机/路线及预留保持。绑定不随占用释放而解除。后续休息必须显式安排并由 S07 积分。当前快照必须如实提供占用与已完成事实，S08 不是完整历史合法性检查器。

固定工装 failure 缺少 `release_allowed` 会被契约拒绝。取消的 failed work 不重做；允许安全解锁才可进入清场，否则等修复。吊机故障不因 release_allowed=true 获得绕过移动/卸载的许可。

## 取消安全边界

| 当前或已完成事实 | 必须保留的后续 |
| --- | --- |
| 未开始、setup/align/restore 已结束且 work 未开始 | 无新生产后缀，按实际残件位置清场 |
| setup/align/restore 正在进行 | 到本阶段末尾，再清场；不启动 work |
| CUT/BRACKET/ASSEMBLE/WELD.work 正常执行或可续作暂停 | 当前 work 及必要 handoff，再清场 |
| work 已完成、handoff 未完成 | 保留 handoff；不能重复 work |
| INSPECT.work | 到本阶段末尾后清场 |
| preposition 进行中/已完成 | 完成当前 preposition（如需），再 reset；不开始 rig |
| rig/move/unload 已提交 | 保留原目标，依次完成剩余卸载及 reset |
| reset 或已经到库 | reset 仍保留；到库事实不回滚、不倒运 |

`cancellation_tail` 逐组给出最小阶段序列；取消覆盖全单，调用方须遍历全部组和残件。`cleanup_required` 是订单仍需清场审查的标志，不是清场已完成证明。

r2 允许一个 running/paused restore 与它挂起的 paused work 同时保留；取消边界选 restore，保留 work 历史及剩余量，不重新续作。其他同时活动的加工阶段仍拒绝。返回的 `CancellationTail.restore_sequence` 绑定具体恢复序号，避免已完成的旧 restore 抵消新的恢复成本。

首次在取消处理时计算尾部后，调用方必须保存该结果；后续阶段完成或故障时，将上一结果传入 `cancellation_tail(..., committed_tail=tail)`，只消去已完成阶段或因取消后 restart work 失效而放弃的生产尾部，重新核对实际修复等待。restore 完成后尾部保持空，不从仍保存的 paused work 重新推导正常后缀。该可选参数兼容首次调用，但持续处理取消的调用方须遵守此协议：S06 快照没有取消发生时刻或续作时间，不能仅从事后历史重建已承诺边界。结果来自可信执行适配器，不能由规划器任意构造；它仍不是派工许可，也不是新增 S06 消息。
对已到库订单仍可返回尚欠 reset。`withdrawable_reservations` 保留正在执行阶段、已 rig 未卸载或已占用目标的预留；撤空接收槽也不释放包含其他到料的站锁。

清场工艺继承 S05：备料/部分件按声明正时长 carry，取消 CUT/BRACKET 的必要 handoff 可去废料位；完整/部分模块按声明吊机循环到废料终端，在途件先完成原目标卸载。人员资格、物料位置、源位释放、废料位容量、每件独立处置以及清场/reset 的实际执行与积分，留给 S09 执行内核。这里没有把规则结果冒充资源分配或物料已经处置。

## 授权采样和接收

`ObservationGrant` 分别声明 order_ids、fatigue_ids、exposure_ids、availability_ids、execution_group_ids、material_ids 和是否接收历史事件。无隐含全量真值默认权限。`sample_observation` 只从当时快照复制被授权且已释放订单的数据，保存 sampled_min 与 received_min；交付不得早于采样。指定未来订单 ID 也不能使它提前可见。

授权执行组会显式公开其阶段历史（包括历史 sampled_f/倍率）、绑定、锁与必要准备记录；这项权限包含历史执行时间和状态信息，不能同时声称这些已授权字段仍为隐藏。它不自动公开当前人员 F/积分；当前疲劳、暴露、可用性各需独立授权。单独授权物料只公开其位置，不补齐整张库存表。可用性估计检查故障、占用及显式休息，但仍不是完整派工许可。

`ObservationPacket` 保存复制的观测值，没有活的 ExecutionSnapshot 引用。可延迟交付或不交付包以表达声明的延迟/缺失；S08 没有选择实验噪声分布、延迟水平或缺失概率。未来带噪适配器须另行声明测量规则，不得修改共同执行真值或读取未来实现。

`planning_view` 在接收端使用包账本，只纳入 received_min≤当前时间的消息。订单释放/取消/实际完成是累积事实，旧包后到不能撤回取消或真实到库；估计按采样时间、接收时间、包 ID 选新值。最新授权执行帧整帧保留，不能将不同时间的部分表拼成伪造完整快照。未收到新数据时保留已有带时间戳估计；收到的空字段/缺表仍表示未知，不是资源空闲或阶段未开始。

输出调用既有 `planning_input`，静态配置只含已观察订单及其工序和物料，保留已观察取消单供清场；公共资源、Q、模板目录按 S06 约定可见。调度器仅接收返回的 `PlanningInput`，不得接收 Configuration 全集、包队列、ExecutionSnapshot、HiddenScenario 或 OfflineEvaluation。输入真实性依赖可信执行适配器，Python dataclass 不提供对恶意进程的文件或内存隔离。

`online_order_ids` 从已接收的取消/释放事实形成 K_t；`offline_order_ids` 在离线端按共同窗口释放及取消清单形成 J_eval。窗口外取消不回溯删订单，抢先到库不改变取消分母。本步不实现目标评分、完整调度命令生成或研究指标核算。

## 稳定随机配对与集成职责

`paired_bits(seed, stream, entity_id, event_type, occurrence, attempt=...)` 使用带版本域的 JSON 身份元组和 SHA-256 返回 256 位确定性输入；不维护全局 RNG 游标。世界、加工、观测使用独立 stream；外生输入使用稳定实体/发生序号，加工使用稳定阶段执行 ID，重做显式改变 attempt，续作保持原身份。算法决策随机性独立，不得放入世界 key。相同 key 与调用顺序无关；这不是分布拟合或 S20 随机协议冻结。

S09 将负责事件日历、实际派工许可、资格与锁的原子获取、净加工/人员积分耦合、完成和物料转换、预留撤销执行、清场展开及死锁/排空判断。等待触 cap 时须用 S07 时界安排至少配置正休息，再重验；共同保护拒绝只向规划返回统一原因。后续隔离测试还须接入真实调度器，固定授权历史、算法随机状态及终止条件，检查拟派工非预知性。当前测试只验证转换和授权投影，不声称生产闭环、Isaac 或 A/D 实验已完成。
