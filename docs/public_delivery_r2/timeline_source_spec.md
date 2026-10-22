<!-- G03 r2 public technical derivative; controlled original and r1 retained. -->

# 时间线、双图共同身份及数据来源 r2

2026-10-22；`P03.3-TIMELINE-r2 / PLANNED_PROJECTION_NOT_IMPLEMENTED`。逐字段表见[timeline_field_source_map.tsv](timeline_field_source_map.tsv)。P03.2-CONTRACT-r3的32记录/223字段保持原身份，本文件的新展示字段另属P033投影，不能回写成既有schema字段。

## 事实、安排与候选

工序/订单行以order_id/product_id/activity_id/operation_id/attempt_id稳定关联；资源行以resource_id/person_id和真实占用半开区间关联。同一命令多角色资源同时展开，共用command_id；重试、返工及取消清理分别成行，避免覆盖旧尝试。未开始工序可为UNSCHEDULED，预测结束未知时省略端点并显示“未知”，不填0。STARTED到当前观察采样的实际段与之后预测尾段分开；最终实际完成只有COMPLETED及读回成立才闭合。完成、READY及RECEIVED是独立标记。

状态轴为ACTUAL / COMMITTED / TENTATIVE / UNSCHEDULED；方案轴为CANDIDATE / ADOPTED / SUPERSEDED。候选单独虚线泳道，永不画成实际采用；未来承诺独立边框。旧/新比较锁定两个plan_version和各自observation/prefix，显示任务顺序、模式、班组、起止变化及reason_event_ids。已执行实际段只能追加或标注独立修正，不能按新计划移动。候选失败仍可在详情审查，但无有效采用记录不进入ADOPTED层。

人员休息、离岗、缺勤、班外、资格失效和故障/维修为独立带状层；实际事件与预报的日历窗分样式。故障点来自已交付实际读回；未来维修计划仅能显示本观察已知的受控承诺并标预测，不能读隔离未来事件。人员F/E详情按PersonInterval重算；REST/OFF_SHIFT恢复、E连续，新人登记前显示NOT_IN_CATALOG。费用区分presence费和冻结C0资源费用，不能把离岗者删除或新人的过去补零。

## 每个快照的来源封套

两图各自保存run_id、epoch、run_spec_sha256、initial_config_sha256、catalog_version/hash、materialized_catalog_sha256、state_revision、observation_id、event_count、event_prefix_hash、plan_version、sampled_sim_h、received_sim_h、sampled_monotonic_s、rendered_monotonic_s和source_status。业务字段来自所绑定的已交付前缀和当时目录；不从最新真值/未交付Delta/未来请求读取。

wall_age_s=本进程rendered_monotonic_s−收到该快照时的本地单调时刻+接收时已核年龄。跨进程单调时钟不可直接相减；需同源计时或请求往返界定上下界，不足时显示AGE_UNKNOWN。sim_age_h=当前已交付观察时刻−该图sampled_sim_h；负值为身份/时钟错误。暂停/限速不混用墙钟年龄与sim年龄。

两图只有封套run/epoch及目录/状态/观察/前缀/plan版本和采样时刻全部相符时标SAME_OBSERVATION；Kit场景若先推进而甘特尚未接收，保留两套真实封套并标ASYNCHRONOUS和各年龄。即使来源相同也不声称物理与计划“原子同步”。错run/epoch的快照隔离拒绝，hash/序号缺口保持最后已验证快照并标STALE/CORRUPT，禁止默补空行。

SCENE_PENDING订单可以出现在逻辑队列行，但无SceneBinding和真实读回不得在三维标为在制就绪。PERSON_ARRIVE客户端只带SceneReference；应用端SceneBinding.catalog_version才为实际目录版本。旧命令完成按其CommandVersionBinding的接纳版本核验，不能因当前目录增长擦除旧线段。缓存保守invalidated_keys与实际reused_keys分别显示，只有真正跨版复用且重核才标“复用”。

## 缩放、详情和导出

工序/资源切换、订单/人员/设备筛选、时间缩放、当前时刻线、交期线与选中双图定位均为只读操作。交期来自该观察可见订单目录，未来单交期不能预画；当前线取观察sampled_sim_h并附年龄，不用GUI墙钟伪造生产进度。

详情保留输入→回执→Delta→事件→观察→候选/采用→命令→实际读回→结果的可用关联，纯管理动作不强造命令。导出冻结选择/筛选/时间窗、两图封套、行数据和未排对象清单，输出JSON/CSV及同运行图像；缺失/未知保留字段状态，图像不替代原始数据。导出只包含已交付前缀，不打开隔离未来请求队列；独立核验重建目录/人员区间、事件资源占用、采用及计划变化，再比导出行，不调用前端formatter作唯一真值。

## 承接点与实施出口

现有源定位S01–S20见p032_source_map.tsv，均仍是P03.2声明的受限旧消费者。P04拟增加VersionedTimelineProjection及增量cursor（prefix序号+hash）、版本化动态对象解析和采用记录；挂接S08/S11/S14的观察/决定出口，不在Kit主线程全读长日志。P05拟在旧desktop model/app和嵌入Kit上接双图/选择桥，P06另建原始轨迹重算器。新增模块/字段/缓存都尚未实现，最终路径与源码hash须由对应关口补绑定。

每次更新以已验证cursor连续增量推进；重连先查同身份持久日志/原request_id，断点缺失才加载带前缀证明的快照并补余量；快照本身不能替代缺失原始前缀。显示可合并刷新但业务账逐条保存，不丢终态或确认；大行集虚拟化，资源索引局部更新，吞吐与年龄按容量规范实测。

## R04/R05有限修订：两个绘制轴与资源关联

展示数据保持schedule_state与proposal_state两条独立轴，参考夹具相应为painted_schedule/painted_proposal。PLAN行不能把UNSCHEDULED/COMMITTED/TENTATIVE绘为ACTUAL，CANDIDATE不能绘为ADOPTED。历史实际前缀用独立FACT_PREFIX行，引用已经交付的事件/读回及前缀证明，即使旁边比较的方案尚为CANDIDATE也可正常显示原实际事实；不把候选安排的区间改标实际。旧painted_as字段不作为r2格式。

设备区间不能读取不存在的DispatchCommand.equipment。先以command_id关联CommandVersionBinding的接纳目录/依赖身份及该命令原事件；静态命令按operation_id在该接纳版本目录的Operation索引查equipment。服务命令从不可变command.service.operation查equipment，核operation.id与command.operation_id一致，不退回最新同名工序。人员来自command.roles[].person_id；目标/设备与人员集合来源分别保存。

equipment集合只是资源需求/关联，不等于实际占用已经发生。实际开始/完成来自ExecutionEvent.kind/occurred_sim_h/command_id及读回，跨完成的持有/释放由Operation.hold_device/release_device/hold_resources/release_resources与逐事件state.reservations/state.owners/state.running的实际变化重建；EXCEPTION/HOLD保留到明确合法释放，不按预测终点闭合。实际区间为半开区间，来源记录接纳目录版本/hash、operation/service摘要、事件序号/前缀与读回ID。动态目录增长不得把旧命令换解为最新工序或抹掉旧持有。
