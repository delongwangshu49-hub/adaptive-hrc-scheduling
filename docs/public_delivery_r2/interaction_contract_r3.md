<!-- G03 public technical derivative; original controlled document retained. -->

# P03.2 共用运行、变更及多阶段回执契约 r3

> 2026-10-22；公开技术摘编。当前契约为P03.2-CONTRACT-r3；六项修订已在离线范围核验，动态消费者尚未实现。

2026-10-22；身份 `P03.2-CONTRACT-r3`；依据 本地步骤授权、[已批准规划](stage_summary.md)及[P03步骤卡](stage_summary.md)。本文件规定后续实现的行为。本步仅完成契约、源码承接与离线例子核验；动态消费者尚未实现，I/E生产验收尚未执行。P01/P02/P03.1原件及 S18-SIM-A1 / 工业G2边界保持。

规范文件共同生效：[动态目录](dynamic_catalog_contract_r2.md)、[会话寿命](session_lifecycle_contract_r2.md)、[逐字段表](p032_field_consumer_map_r2.tsv)、[机器字段定义](p032_contract_schema_r3.json)、[事件出口表](p032_event_routes_r2.tsv)、[现有源码与拟新增适配](p032_source_map.tsv)。JSON、TSV和本文不一致即契约检查失败；不能任选一种解释。模式、时刻与幂等例子及契约核验器由受控原件保存，其实际核验范围见[阶段摘要](stage_summary.md)。公开P03.3设计检查入口为 `python scripts/verify_p033_design_r2.py --output <新目录>`，仅检查设计及人工夹具，不能作为后端、调度、Kit或GUI验收。

## 1 统一入口和身份

GUI、CLI、固定研究和交互回放使用相同的解析、合法性、业务消费及执行接口；来源标签不能改变资格、保护或资源约束。RunSpec冻结后不得原地改写。其摘要覆盖 schema_version、run_id/epoch、mode、scenario、backend、method、budget_profile、初始配置/源码/模板目录摘要、初始订单和人员覆盖、固定事件清单、时钟/成本策略及容量配置。未知字段、未知枚举、非有限数、bool充当整数、重复ID和未绑定输入都拒绝。

RunSpec支持 `FIXED_PROTOCOL`、`INTERACTIVE_PRODUCTION`、`INTERACTIVE_REPLAY`。固定模式的 N/H/F/U/C及事件在启动前绑定；人工临时请求即使目标/时刻合法也拒绝 `PROTOCOL_LOCKED`。回放须有独立 run_id、原交互链摘要及映射，不改写原run，不混入固定样本。固定与交互都调用同一消费者；固定协议可预生成事件，但不能替代E13/E14/E20的真新输入。

方法只接受公开注册的 EDD / ADAPTIVE，profile绑定具体参数与实现摘要。动态事件后应有实际重新求解机会；触发、预算消耗及调用/候选/采用/派工分别记录。具体算法和预算选择属P04.1，P03.2不预选新目标或伪称自适应已响应急单。CPU/ISAAC共享语义，实际接纳时刻和人工墙钟允许不同，E11不要求整条动作逐字节相同。

所有sim_h单位为小时，UTC字段为带时区ISO8601，wall_elapsed_s为单调时钟秒；F为无量纲，E为F·h，质量t，尺寸m，成本为所选模型货币单位。schema定义具体叶字段及必填/条件必填。可空值仅用于明示未知；不能以0冒充未知时刻、F或曝光。ID是1–80位ASCII字母数字、点、下划线或连字符；新对象身份由run命名空间+对象ID+模板版本决定，不能复用历史ID。

## 2 请求接收和应用

ChangeRequest带run_id、epoch、request_id、producer_id/client_sequence、source、kind、target_id、payload、expected_catalog_version、expected_state_revision、expected_target_revision、time_rule、requested_sim_h及expires_sim_h。backend追加全局accept_sequence、received_sim_h/received_at_utc、内容摘要及读集。内容摘要为UTF-8 JSON（键排序、紧凑分隔、无NaN/Infinity、无重复键），不含服务端回执；实数域中的1与1.0规范化为同一摘要，整数域不接受1.0或bool。canonical版本必须入RunSpec，不复用历史codec摘要冒充新规范。

先校验结构、摘要与run/epoch；在**同run/epoch/request_id**范围查询持久幂等表，再校验当前目录/状态。相同内容返回原最新回执和原accept_sequence，不重新消费client_sequence、不重新应用；异内容拒绝 `IDEMPOTENCY_CONFLICT`。同producer新请求client_sequence必须严格增加；不同producer允许同序号，服务端按持久接收顺序串行分配accept_sequence。乱序新请求拒绝 `CLIENT_SEQUENCE_OLD`，不依靠文件名或GUI墙钟排序。网络超时是客户端UNKNOWN；重连先查原ID，不改ID重发业务。

接纳时 expected_catalog_version 和 expected_state_revision 必须等于该接纳边界已提交值，target_revision等于目标版本（新ID为0），否则拒绝 `CATALOG_STALE` / `STATE_STALE` / `TARGET_STALE`。这是一致性防护，不要求未来应用时全局state_revision仍相等：执行推进会改变全局revision。接纳后保存目标/模板/资格/资源依赖读集；到期重新核查目标版本及安全条件。无关目录增长可重基到最新目录并记录old/new及read_set_hash；目标、模板或资格条件冲突则拒绝 `TARGET_CONFLICT` / `DEPENDENCY_CHANGED`。不得默默改用户payload或将过期请求顺延。

`IMMEDIATE`不携带requested_sim_h，后端选择收到后的第一个合法事务边界；回执返回actual_applied_sim_h。`AT_SIM_H`必须有 requested_sim_h≥received_sim_h；等于当前时刻可入同刻队列。禁止客户端把旧显示时刻当立即。expires_sim_h为包含端点的最后允许应用时刻，必须不早于请求时刻/接纳时刻；在边界 t>expires 时拒绝 `EXPIRED`。等待资格/实体/合法交接可跨边界，但到期仍须终结拒绝并保留已发生事实。

每个请求原子落盘ACCEPTED后才进入应用队列；崩溃不能造成已应用却没有可恢复日志。多对象新单一批生成必须全有或全无；持久事务先准备、验证并写提交记录，提交前不对观察/规划暴露，提交后重启恢复只重建同一事务不再次生效。生产进程崩溃保持FAILED/UNKNOWN和原件；是否支持实际恢复运行须P06另验，本契约不授权重启E20会话。

## 3 同刻顺序和冲突

在t边界先积分[t_prev,t)，完成到t的实际完成/读回，再依次处理：安全事实（缺勤/故障）→禁新增/取消（离岗、取消、stop）→目录及就绪变化（新单、到岗/返回、维修、休息）→保护→观察交付→调度→派工。沿用现有completion/external/protection/observation/dispatch顺序，新增external内部排序必须在日志中标明。每组按accept_sequence升序；相同target的互斥外部变化同刻只允许优先组第一条应用，其余 `SAME_TICK_CONFLICT`，同一请求的后续业务交接不算第二次应用。

例如t=10同人ABSENT与RETURN，不论到达先后，ABSENT先应用、RETURN冲突拒绝；维修与故障同设备同刻按故障优先，不能观察出虚假恢复。故障已发生仍须落盘，即使订单同时取消；取消不能抹掉异常和载荷。对不同对象可顺序提交多个增量，每条old_version等于上条new_version、各增1；观察可在该批后交付，保存event_count和完整有序前缀摘要。请求“被收到”本身不向规划器泄漏未来业务字段。

关闭接单是接纳序列上的持久fence，详见寿命契约：不能用事件优先级跨过fence重新决定已接纳新单的有效性。stop优先阻止新派工，但不能删除同刻已完成读回；当无运行工作时也须落最终观察和原因。

## 4 回执和业务结果

合法服务端序列为 ACCEPTED→WAITING_BOUNDARY（可零次/多次）→APPLIED 或 REJECTED；也可结构/身份校验直接REJECTED。客户端SUBMITTED和UNKNOWN是发送/知识状态，不能伪造成服务端已受理或撤销APPLIED。APPLIED/REJECTED不可互转；后续发现损坏另写CORRECTION/FAILED事实及关联原ID，不改旧回执。每条服务端回执有receipt_id、receipt_sequence、request_digest、accept_sequence（未接纳时省略字段，禁止null）、sim/UTC时刻、reason、before/after版本、应用事件ID或拒绝定位，链式保存。

APPLIED表示该种变更的**业务门槛实际改变**，不统一等于“物理业务完成”：新单APPLIED是独立订单/产品/任务/BOM逻辑目录登记并形成到达事实；人员到岗APPLIED则必须资格、位置、Kit实际关联与观察所需读回齐备；计划离岗APPLIED是禁新增分派生效，后续DEPARTED为业务结果；缺勤APPLIED为不可分派与受影响动作异常/保持事实落盘。维修APPLIED为维修事实，设备恢复仍须检验；取消APPLIED为禁剩余新增工作，清理/外退另记。WAITING_BOUNDARY不得伪称人员已可用。

BusinessResult独立记录 REGISTERED/WAITING_MATERIAL/WAITING_SCENE/READY/STARTED/COMPLETED/RECEIVED、DEPARTURE_PENDING/DEPARTED、EXCEPTION/HOLD/RECOVERED、CANCEL_CLEANUP/CANCELLED_WITH_RESIDUAL等类型及原事件/观察/采用/命令/读回关联。每次显示都附run/epoch、catalog_version、state_revision、observation_id、event_prefix_hash、plan_version及年龄；缺失关联为UNKNOWN，不把候选当采用、预测当实际。P03.3负责完整双图字段布局/容量协议，P04/P05/P06负责真实接通与验收。

## 5 每类输入的闭环出口

[事件出口表](p032_event_routes_r2.tsv)逐项绑定新普通单/急单、登记到岗、离岗、缺勤、返回、休息、故障、维修、取消、关闭接单与stop：实际或拟新增消费者、拒绝、场景对象、观察、保存和独立核验。所有动态入口均标 `PLANNED_ADAPTER_NOT_IMPLEMENTED`；原有机制只承接表中限定部分。完整检查要求请求→事务/业务事件→Kit实体或明确N/A→交付观察→决策/采用→命令/读回（需要生产动作时）→结果/保存重建可追，不要求每个管理动作都强造派工。

未来E20仍须同一真实Kit run/epoch中原单已执行→真新普通单→真新急单→减员→含初始目录外人员增员→所有受理订单完成接收→关闭后排空正常退出；E21至少4累计产品准入/排队/实例化。本文例子不充当这些生产证据。双视图同权默认1:1和E01–E24原状态保持；本步不修改原需求/案例表为PASS。

## R01–R06 有限修订的共同解释

PERSON_ARRIVE只提交不含实际目录序号的scene_reference（domain_id、scene_entity_id、prim_path、template_revision）。服务端在实际应用事务中生成SceneBinding.catalog_version；等待或同刻无关目录事务不会要求改写已接纳payload。原始请求摘要和接纳序号保持，新场景绑定作为后发应用证据保存。

所有SessionFinal须绑定同run/epoch及完整RunSpec摘要，终态核验显式读取其mode：固定协议按冻结集合/窗口正常完成，不要求CLOSE_INPUT；INTERACTIVE_PRODUCTION和INTERACTIVE_REPLAY的COMPLETED须关闭接单并排空。ACCEPTED、WAITING_BOUNDARY和APPLIED回执必须有accept_sequence；接纳前REJECTED省略，接纳后REJECTED保留原序号；null不是合法线格式。
