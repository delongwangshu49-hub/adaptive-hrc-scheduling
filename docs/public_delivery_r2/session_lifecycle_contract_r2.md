<!-- G03 public technical derivative; original controlled document retained. -->

# P03.2 连续接单、等待计量与会话终止契约

> 2026-10-22；公开技术摘编。当前契约为P03.2-CONTRACT-r3；六项修订已在离线范围核验，动态消费者尚未实现。

2026-10-22；身份 `P03.2-SESSION-r2`，从属[共用契约](interaction_contract_r3.md)。此处是后续连续驱动适配要求；现有production_loop会OPERATIONS_COMPLETE/NO_PLAN_FOUND/STALLED退出，旧start/stop控制不具备本契约能力。

## 1 状态机及持续输入

STARTING→RUNNING_OPEN↔WAITING_INPUT；显式CLOSE_INPUT后进入DRAINING；全部义务结束才COMPLETED。RUNNING_OPEN中仍有未来已接纳输入但暂无可执行动作时为WAITING_BOUNDARY，不伪称等待无订单。WAITING_INPUT仅表示暂无业务工作且接单仍开，保持同run/epoch/引擎/命令恢复身份、历史、F/E和物理持有。空队列不会COMPLETED，不重新start，不以拼接运行实现连续。

接收线程/消息通道持续可写；生产worker作为唯一事务写者在有限节拍取队列并回执，既不等GUI单步也不在Kit主线程执行重规划。持续模式下当前工作推进，输入在下一个合法边界消费。simulation_rate决定单调墙钟与sim_h推进，boundary_poll_wall_s控制最长取消息间隔，idle_step_h为等待时最大仿真步；均为RunSpec有限正数、后续校准，显示为仿真节拍而非物理实时保证。单步可作另行声明的诊断辅助；旧stop永不作为pause或resume。

每步取最早的完成/到货/未来请求/日历/保护/预算/idle_step边界，按共用契约排序；不能一次长跃过可能收到输入的墙钟窗口。等消息可阻塞到最早墙钟心跳但不能忙循环；WAITING_INPUT仍推进时间，不无限无记账地留在同一sim_h。纯UI缩放/筛选/选中不能提交业务或改变仿真时钟。

## 2 等待期间时钟、F/E和成本

采用 `ADVANCE_METERED`，RunSpec明示session_until_h、wall_budget_s、idle_step_h、simulation_rate及cost_policy_id/hash。暂空等待时sim_h继续按节拍递增，累计idle_sim_h和idle_wall_s；同一时间段只计一次。预算/日历/保护和已接纳未来输入仍按边界处理，不能为了保留会话冻结F、跳过班次或把显示时钟重置。有限预算到达如实截尾，保留等待原因，不自动判全部生产正常退出。

在岗可用但无生产活动为WAIT（F按wait_rate积分），已进入合法休息为REST，班外/已离岗为OFF_SHIFT（按recovery_rate恢复）；始终以原building_human积分模型保留E=∫Fdt、峰值及活动区间，跨日历、恢复至0和保护边界分段。离岗或班外F恢复不等于删E，新人从实际登记到岗时开始定义。WAIT触及cap则保护转为合法REST/保持并记录，不能把cap夹紧继续WAIT。已有未释放负载/工作不能在空队列判断时改成普通WAIT。

成本政策 `PRESENCE_LABOUR-r2` 为拟新增公开统计投影：劳动成本=Σ wage_i×实际在岗区间（含WAIT/REST及在岗班外，离岗后不计劳动费）；另按原模型资源占用/设备费率计费，安全HOLD不因没有新任务免除成本，offshift曝光仍计E但与劳动费区分。若原模型成本粒度不同，P04须保留legacy_cost及该投影，不能覆盖旧实验数值。cost_policy_hash、费率、币种及所有有费/无费区间保存，独立重算。未提供费率拒绝启动，不能默补0；持续等待有有限预算及显式可见费用。

离线算例：人员在h=10时F=.2、E=.3，WAIT速率.01/h至12，F=.22、E=.72；h=12–14 OFF_SHIFT恢复.05/h，F=.12、E=1.06。若10–12在岗、之后离岗，wage=10/小时，则该段劳动费20，presence和availability都不向过去扩展。此为契约解析值，非新生产测量。

## 3 关闭接单后排空

CLOSE_INPUT只在交互模式有意义，应用时持久写close_accept_sequence，禁止**新接纳**ORDER_CREATE/PERSON_ARRIVE；同ID重试仍可查询原回执。fence之前已ACCEPTED的未来新单/到岗保留，到合法时刻应用或按原过期/冲突规则终结；不以关闭为由抹掉。已有人员RETURN、计划离岗/缺勤、故障/维修、取消、休息等排空必要动作仍可接纳并完整审计；不得借RETURN创建新ID或借维修增单。关闭请求幂等，不能再开接单；需要新会话则显式新run，不能把它当E20延续。

DRAINING要等待所有接纳请求成为APPLIED/REJECTED、所有订单得到终局、在执行动作/在制/物理持有/清理/外退得到合法结果、应收产品真实RECEIVED、最终事件和观察已交付、执行/因果/保存检查结束。取消允许在一般会话中以独立合法取消结果结清，不伪称该产品RECEIVED；E20成功要求所有受理单完成接收，因此含取消残余的运行不算E20完成链。未来请求未到期、材料未到、异常/HOLD或交接未清均不能COMPLETED；预算到达截尾，无法恢复显式DRAIN_BLOCKED，不无限静默挂住。

COMPLETED需要intake_closed=true、pending_requests=0、open_obligations=0、running=0、holds=0、expected_receipts全部具备、最终审计与持久保存成功；完成事务与输入接纳在同一写者序列上封口，进入任一终态后只允许查询原回执，新变更拒绝SESSION_TERMINAL。process_exit_code=0在进程真正退出后另记。COMPLETED和exit0不能互相推断；未确认退出为UNKNOWN。固定协议仍按冻结集合/窗口的旧规则终止，完成和截尾分列，不继承交互的空队列等待。

## 4 Stop、截尾、异常与断连

STOP_REQUEST沿旧有序停止含义：禁止新接纳业务/新派工，排已STARTED到允许边界，保留承诺、HOLD及未完成订单；终态STOPPED或STOP_BLOCKED，并列剩余义务，不记COMPLETED、不允许resume本run。仅允许持有者安全终止和落证据所需控制；对预期会新增动作才能完成的排空业务，不承诺stop后还能完成。

sim截止为WINDOW_CENSORED，wall预算为WALL_CENSORED，turn/search/计算预算分别记录budget_kind及limit；不能把无候选/搜索用尽当订单完成。FAULT/Kit异常/进程崩溃为FAILED，最后完整prefix和可能已接纳但应用未知请求保持UNKNOWN。未收到确认不补造APPLIED；恢复读取同一日志/ID，不自动重放外部命令。CLI和GUI退出/断连不默认stop；生产可按原RunSpec继续到关闭或预算，UI明确数据显示年龄和UNKNOWN。运行控制进程失联的实际处置必须由worker持久策略决定，不能由显示层猜测。

所有终态保存reason、last_committed_event_id/hash、last_observation_id、catalog_version/hash、state_revision、open/pending/running/holds清单、最终sim_h/wall时间、F/E/成本区间、审计状态、保存状态及实际exit回执。停止/预算/异常的残余有据可查。此处不提供完整P03.3容量/布局/E20事前输入协议，不开启P04实现或新的生产/Kit运行。

## 有限修订：积分、成本覆盖与模式绑定

REST和OFF_SHIFT都按恢复方程积分至F=0为止，恢复后的剩余时间曝光增量为0；工作、等待和实际HOLD按其声明活动速率积分，累计E连续不重置。离线核验必须同时接受正确恢复并拒绝把REST写成疲劳上升的轨迹，保持原P02数值参数。

PRESENCE_LABOUR-r2明确person_template_ids：包含全部初始人员模板和该运行允许新到岗的参数模板。rates非空、每个已声明模板恰有一个有限非负费率；缺失、重复或未知模板分别拒绝，不把缺失补0，显式0费率仍可被准确记录。新人员模板也须在已声明集合并有唯一费率，不能绕过启动时成本绑定。legacy_resource_cost_source_sha256必须等于RunSpec.initial_config_sha256，设备/资源成本沿用该冻结C0的原费用规则，独立重算时解析同一输入；本步不修改原费用模型或原实验数字。

SessionFinal保存run_id、epoch和run_spec_sha256，核验者须取得对应完整RunSpec并验证摘要/身份，禁止仅相信终态里自报的模式。所有COMPLETED共用无未结请求/业务/运行/HOLD、所需接收齐备及审计/保存通过条件；只有交互生产及交互回放另外要求intake_closed=true，固定模式保持原集合完成语义。未绑定规格或错run/epoch/摘要的终态拒绝。
