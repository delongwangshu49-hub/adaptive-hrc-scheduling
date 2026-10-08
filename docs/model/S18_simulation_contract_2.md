# S18-PROD-2.0 仿真生产契约

2026-10-08；S18-SIM-APPROVAL-001 / SR01—SR08授权下实施，当前IMPLEMENTATION_IN_PROGRESS。本文定义新版消费者；不改写获批提案/假设字节，也不宣称V01—V08已全部满足。

## 准入与身份

`SIMULATION_RESEARCH_ONLY`只能与`S18-PROD-2.0`、`S18-PROD-SPEC-2.0`及`S18-SIM-A1`组合。配置核对实际批准、原md/json摘要、SR-W1/SR-W2既有v1产品、W-B/W-T组件/抽象接头/过程/夹具/输出版本及全部消费者版本。工业事实单独保持`NOT_ESTABLISHED` / `OPEN`，工业用途、旧版本混入、缺Q假设映射、摘要漂移与工业PASS伪装均拒绝。

批准输入副本随隔离wheel携带，原字节保留。原日历、cap、恢复/工作/等待率、设备/夹具、B=2、运输速度/几何、BOM、其他核心单位和RP/SC/SH/WV由摘要绑定的既有四种配置模板逐项核对；双产品原FG1/FG2交替路线保留。旧S15线格式、实例、Schema和内容摘要保持，旧结构Schema明确拒绝新版。

## 分支、人员与资源

W-B/W-T各有独立H六单位及HR三单位Operation/绑定。基础工时H=3h、HR=2h和原κ保持。后继等待实际选择的完整分支，不能要求两种模式均执行、混段或跳卸载。首装夹原子创建`ModeAttempt`并承诺定义、版本、班组、准备修订和完成单位。中断/结构取消保持HOLD、已发生材料/负荷/驻留与资源；无结构自动返修、自动切模式或断段重启。

H的WELD-J2/FIX-J2，HR的R1/FIX-J2按`activity/attempt/revision`持有；同产品两框不能共享产品级owner。机器人结束仍持有，实际卸载完成才释放。角色与具名人员通过显式RoleBinding分离；H枚举W1/W2，HR人工阶段为OP1，无人机器人阶段不占持续监护角色。机器人启动前必须实际退出J2；运行/异常持有期间禁止入站走行，已有入站走行也阻止机器人启动。

仅模型停点允许H的W1/W2交班。完整交接为双人0.1h HANDOVER及接替人0.1h RESTORE，工作负荷按原率积分，开始前保护原0.2h日历/cap。两段中夹具持续持有，跳恢复、无交班换人、零成本或不到位均拒绝。非焊接核心活动首次具名派工建立ActivityCrew，后续单位保持班组；新活动可从原资格池选择，不复制资格，不免费改变已承诺班组。WALK/空返/REST/材料准备和实际接收继续用原规则。

## 生产联合与对照

`simulation_joint`从已送达完整事件前缀和独立执行/因果审计出发，生成覆盖约定未来窗口的完整Schedule。窗口包含全活动顺序/开始时隙、具名班组、模式、显式REST及真实物流/占位/人因；已观察事实和已承诺工作保留。未来到货、修复、质量和接收许可仍UNKNOWN，不预测成实际PASS。

每个候选由生产执行器作隔离预演，再由独立S10与因果审计重建整个前缀和完整窗口。评价只用窗口内实际模型完成的共同核心活动和人因积分，未完成不使用名义完工时间，不因H有更多单位而奖励H。保留当前方案的局限：只为开发机制验证，不保证全局最优、实时性能或正式A/D效果。

四通道为ADAPTIVE_JOINT、FIXED_H、FIXED_HR、NO_OBSERVATION_UPDATE。共同预算在运行前保存机会时刻、每次/累计调用、迭代、修复试次与墙钟上限；实际消耗和未用额度记录。无更新仅从保留锚点及自身名义演进提案；当前反馈只用于时钟/回执绑定和实际安全拒绝，不参与评分或拒绝后重搜。超预算候选不执行。完整原始非派工检查点WAIT保留；扩展记录在同一前缀用下一提案取代闭合标记，避免重复前缀，不修改原事件或削弱审计严格递增规则。

## Isaac与证据边界

现有USD场景实际执行具名走行、装夹、退出、隔离加工、停机确认、进入卸载和交班。定义/阶段/资源owner/停机状态从场景属性读回并与实际人员/载荷/支承证据绑定。焊接本体为已批准符号定时过程，不验证热过程、焊缝质量、焊枪路径或工业安全距离；工业资格保持未建立。

开发实跑已出现：顶框试图进入底框占用的J2共用落点时，实际生产几何检查拒绝TRANSPORT_COLLISION。该失败保留；不挪动落点、清空底框或变更冻结几何。合法连续链先完成/卸载/移出底框再进入顶框；逻辑驻留许可不替代物理可行性。新版全部验收仍按SR07 V01—V08及相应实际见证判断，不用此说明或旧S15/C04证据替代未通过出口。

## 消费者入口

- 领域/边界/Schema：`domain/production.py`、`contracts/production.py`、`production_admission.py`、`schemas/production_simulation/`。
- 生成/映射/保护原值：`build_simulation_production.py`、`production_mapping.py`及随包批准/原值输入。
- 执行/走行/交班/审计：`production_backend.py`、`production_handover.py`、`production_navigation.py`、`production_checker.py`。
- 规划/联合/控制/因果：`planning/production.py`、`algorithms/simulation_joint.py`、`algorithms/joint_production.py`、`control/simulation_joint_policy.py`、`control/production_loop.py`、`control/production_decisions.py`。
- Kit：`backends/production_isaac_adapter.py`与`sim/isaac/scene/production_port.py`、`production_receiver.py`。旧消费入口仍明确拒绝新版。

成果验收、确切发布、正式A/D与后续步骤另审；当前无Git/远端发布、资产下载或环境升级。
