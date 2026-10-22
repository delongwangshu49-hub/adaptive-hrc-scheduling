<!-- G03 public technical derivative; original controlled document retained. -->

# P03.2 动态订单、人员及版本目录契约

> 2026-10-22；公开技术摘编。当前契约为P03.2-CONTRACT-r3；六项修订已在离线范围核验，动态消费者尚未实现。

2026-10-22；身份 `P03.2-DYNAMIC-CATALOG-r2`，从属[共用契约](interaction_contract_r3.md)。动态目录及下述适配全部为后续P04–P06要求，未实施。当前选定源码为P01-S20-r4-2d12e84b；旧数值、冻结配置、工艺与研究域保持。

## 1 冻结输入、增量及重建

initial_config_sha256始终指向原冻结输入C0，run_spec_sha256绑定新运行实际规格；两者不随新单/人员变动。catalog_version从0开始，D0为C0的逻辑目录规范投影及模板/资格/容量版本。每个实际提交Delta使用版本v→v+1，含delta_id、request_id/digest、kind、accept_sequence、实际sim_h、old/new catalog hash、对象清单/生成配方摘要、read_set_hash、state_revision_before/after和前缀关联。登记、可用性/禁新增变化均入Delta；普通执行revision增长不必增长目录版本。

H0=SHA256(canonical(D0))；Delta payload不含其new_hash本身，H(v+1)=SHA256(canonical({previous_hash:H(v), version:v+1, delta:payload}))。此为增量链身份，不冒称等于完整配置摘要；另存materialized_catalog_sha256=SHA256(canonical(D(v+1)))。模板与叶字段的canonical版本由RunSpec绑定；保留完整初始目录、每条已提交Delta、事务提交标记、内容摘要及周期快照。独立重建从C0按连续版本/链/实际生效序应用，逐项比对象及完整投影摘要，再核事件/命令/读回/Kit身份。缺、乱序、篡改、重复版本或修改旧对象历史皆拒绝，快照不能替代缺失前缀。

未来事件在尚未应用/交付时存在于隔离请求队列，只在已授权事件消费端可见；候选/规划器按observation的catalog_version与event_count重建**当时已交付**投影，不能读取最新真值目录或整个未来Delta日志。Kit可能先准备实体，未发布前隔离、无生产可用性；两图按各自采样版本显示年龄。新目录到达未等于新观察交付。

## 2 真新订单及生成身份

ORDER_CREATE的order_id首次登记，不在初始或历史目录；quantity是正整数产品件数。每件生成独立product_id、components、core_activities、operations、lots及BOM需求、实体映射和生产状态；ID由命名空间及稳定件号生成，不能以数组下标重排改变旧ID。受支持模板SR-W1/v1、SR-W2/v1分别绑定选定配方/工艺/阶段/人机模式与映射摘要；受支持不表示任意模板可编辑。当前运行对哪套模板消费者和资格能闭环须在后续能力注册表列明；缺消费者/模板参数拒绝 `TEMPLATE_UNSUPPORTED` / `TEMPLATE_INCOMPLETE`，不能静默降为另一产品。

新增payload包含order_id、template_id/revision/hash、quantity、due_sim_h、priority(NORMAL/URGENT)、material_plan_id及arrival_rule。due_sim_h须严格晚于该单实际登记时刻；若未来到期时交期已失效则 `DUE_PASSED`，不自动改交期。IMMEDIATE/AT_SIM_H是订单到达请求时刻，材料实际到货另由material_plan引用的受控到货事实驱动。加急使用同一ORDER_CREATE且priority=URGENT，不能先把未来新ID塞入初始池；E14要求首次登记ID，E06要求到达观察后对至少一项未承诺安排有真实紧迫性影响，保留承诺与原单进度。

生成是确定性事务：验证配方/数量/依赖/限额→生成完整逻辑对象及BOM需求→提交Delta/到达事实→观察交付→按物料/场地释放实体与任务。登记时只增加需求，库存、实际到货、质量放行、几何位置与设备容量不凭空增加。SCENE_PENDING只表示准备中；Kit映射/读回完整且实体占位合法后才可生产。失败回滚未发布准备对象，已提交逻辑订单保持WAITING_SCENE或明确失败，不删目录假装未接纳。每次实例化生成scene_entity_id/domain_id/template_revision/catalog_version绑定，拒绝重复或错误run对象。

累计登记产品数count_registered单调，完成/取消不减；当前开放业务件数count_open、等待件数count_queued、物理在制count_wip和各place/material容量独立。RunSpec配置max_open_products、max_queued_products、max_wip_products、max_lifetime_products与位置容量/库存来源；这些是明示受测上限，不能用max_wip=3拒绝第4累计产品。超开放/排队/寿命限额在接纳/应用两次核对，拒绝 `QUEUE_LIMIT` / `LIFETIME_LIMIT`，不部分接受quantity。物理场地满时已登记产品排队 `WAITING_SPACE`，不占用不存在位置；后续实际转入WIP时再原子占位。E21的至少4累计件是未来准入、排队和实例化见证，性能/实测上限在P03.3设计、P04/P05校准，本文不虚构测量。

取消沿用原取消/清理服务的受控语义并扩展动态ID查询；已耗材料/工时/成本、载荷、在制品、异常和剩余订单保持。取消后只有清理/外退/交接等合法尾段可继续，不可继续该单新增生产；结果区分CANCELLED_WITH_RESIDUAL、清理完成和正常产品接收。

## 3 人员登记、离岗、缺勤和返回

PERSON_ARRIVE创建初始目录外person_id，包含qualification_evidence_id及资格/有效期、parameter_template_id/hash、calendar_id/hash及可用窗、initial_f、arrival_location和scene_reference。资格及模板必须在受支持注册表可核；initial_f∈[0,cap]、E从首次实际到岗时的0开始，来源是本次新人员基线，不向过去补零。参数沿用P02 person模型，不能以新人名义改原人员疲劳速率。资格有效到实际动作末端，日历/位置/Kit读回齐备前WAITING_BOUNDARY或拒绝，不能进入候选班组。

PERSON_RETURN引用已登记同ID且当前离岗/缺勤者，不携带initial_f或替换参数/资格。返回前从最后已知F/E按已声明OFF_SHIFT区间积分（突发缺勤初始安全保持期间按真实活动积分），再核资格/日历/实际入口位置及Kit身份；不重置F/E或新建替身ID。资格过期必须经独立受控资格更新版本后再申请，不在本步新增资格编辑器。不存在ID拒绝UNKNOWN_PERSON，在岗重复返回拒绝PERSON_STATE；同ID重试仍返回原回执。

PERSON_DEPART是计划减员。应用时立即设dispatch_eligible=false和departure_requested_h，目录记录DEPARTURE_PENDING；自此禁新增常规分派及新增承诺。已STARTED动作继续到模型允许的合法停点，或由真实交接服务转给合格且实际到位者。交接需承诺冲突/释放记录、原/新班组、实际读回及载荷所有权，不能抹去旧command或替换原工时采样。必要收尾/交接动作必须显式标 `DEPARTURE_SERVICE` 并合法核验，不能借此继续新生产。无合法交接则WAIT/HOLD、不伪报已离岗；真正离开时记录DEPARTED、关闭在岗区间。未启动的未来承诺无法履行时保留原承诺记录，追加由已观察不可用事实证明的 `COMMITMENT_BLOCKED/RELEASED`，不得静默删掉。

现有可复用的HANDOVER/RESTORE仅限已核验手工作业单元的合法边界：原/新人员共同交接0.1h，再由新人员RESTORE 0.1h，须核对完整0.2h资格、日历、F及原工装持有。它不提供任意阶段安全替班，也不能直接替代机器人隔离/停机、吊载或紧急缺勤时的安全保持；其他情形无已核验服务则HOLD并列后续必要适配。原模型及证据见[人员模型](model_summary.md)与[阶段表](model_summary.md)，本步不扩大原通过范围。

PERSON_ABSENT是突发不可用：在安全事实阶段禁新增派工，受影响已开始动作按阶段规则进入EXCEPTION/HOLD或可验证安全终止；不得强迫其完成危险动作，不清资源锁、支承、载荷、尝试或历史。不需人员在场即可保持的机器人段也须有安全核验事实，不能默认全部完成。实际离开/安全接管后才关闭在岗统计区间，缺勤起点另记，从此实际可用人时为0；安全保持期间仍记录真实在场/活动和成本。恢复由受控RETURN/交接/设备恢复服务重核，不能通过移除旧person绕过。

REST_REQUEST独立：同一在岗人员仍在目录，资格/日历不变；在合法边界进入REST并保留位置/资源持有规则，不替代离岗、缺勤或新人员到岗。休息可能等待，F下降及E正积分按原方程，不写成零成本或F/E重置。

统计保存逐人presence_intervals、availability_intervals、activity_intervals及资格版本：在岗时间是实际presence半开区间并集，可用人时=presence∩日历有效窗∩非缺勤/非禁用；工作、等待、REST、OFF_SHIFT分别积分。E_i=∫F_i(t)dt不递减，peak_i保留全部已定义历史；新人之前为NOT_IN_CATALOG而非0，离岗后OFF_SHIFT的F/E保留但不可用人时为0。共同窗的总曝光/峰值与在岗劳动曝光分开报告，动态平均分母显式，禁止删除离岗者、给新人补历史0或增加空分母制造改善。货币成本政策见寿命契约。

## 4 运行中版本与承诺适配

现有OnlinePolicy身份由run/epoch/config摘要构成，变化会清pending、committed和checkpoint相关状态；现有Command验证要求config摘要等于当前配置；后端/审计/场景初始集合均固定。这些不是动态能力，详见[源码表](p032_source_map.tsv)。直接改配置并换hash会破坏旧执行身份，继续沿用旧hash会谎报配置，两种都不能实施。

P04须增加独立CatalogContext和按版本解析器：冻结config身份+dynamic_catalog_version/hash+observed_prefix_identity并列；运行主身份run/epoch不变。旧STARTED命令、原readback、不可撤销承诺保留原admitted_catalog_version及依赖摘要。对旧命令的完成/异常按其接纳视图重建验证，再把实际状态变化并入当前投影；不可把旧config摘要强改为最新、不得对旧事件重新签名。新命令同时绑定当前**已观察**目录及state_revision，动态ID从对应投影解析。

目录提交先计算受影响对象及依赖闭包；只失效涉及变化的未承诺候选/缓存后缀，保存invalidated_keys/reason/old/new版本和前后受保护摘要。无关缓存若要跨版复用，必须重核其依赖闭包并生成新的采用记录；未证无关则可保守失效全部未承诺缓存，但不能清运行/承诺。未来承诺保持义务；资格失效、缺勤、取消导致不可履行时只能用可追的业务事实追加blocked/release及重规划，不能以hash变化整体清空。历史prefix只追加，原摘要对应原前缀继续有效。

适配覆盖配置生成/准入、domain/contracts/schema、后端索引及库存/位置、planning_input与候选重放、OnlinePolicy、执行/因果/决策审计、IsaacAdapter/场景/读回、GUI/CLI、保存快照/重建和统计。新schema有单独版本/消费者清单；旧S18准入及固定旧审计解释器原样保留，另立新来源/影响身份。不得通过放松原S18固定15人/旧636输入校验把动态扩展混入旧协议；工业G2依旧OPEN，模拟模板资格不变成工业资格。

## 有限修订：场景版本与缓存集合

SceneReference是不可变客户端输入，SceneBinding是服务端应用产物；后者才包含实际提交的catalog_version。到岗请求跨无关目录增长或同刻串行应用时，按依赖读集复核，保留原请求，由应用端分别生成实际v→v+1的场景绑定；客户端不得预填或修改实际版本。未就绪仍WAITING_BOUNDARY，不以生成逻辑绑定代替真实Kit读回。

缓存失效集合必须包含所有受影响的未承诺键，允许保守扩展到其他已知未承诺键；不得包含未知键或已承诺/在执行保护对象。reused_keys明确实际采用/复用集合，须是已知幸存键的子集；重核集合覆盖这些真正复用键，单纯保留但未采用的键不冒称已复用，之后要采用时再核验。全部未承诺缓存被保守清除时不再要求重核已经失效的键，原命令/前缀/承诺保护规则保持。
