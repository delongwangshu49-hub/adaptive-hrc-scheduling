# S14 Isaac派工与反馈接口设计

2026-10-04 r2有限修复接口：批次加工、转换、搬运共用ENTITY实物锁；WORLD仅首次领域接受才送执行端，端口副作用失败后须reset，不能继续派工或盲目重放。规划可为EXCEPTION承诺生成新ID的resume_of命令，原角色/尝试/单元及剩余时长保持。

`Readback.inputs`新增逐输入实体、实际坐标、实物数量（组件为null）、可见与支承读回，绑定外层run/epoch/command及采样时刻。轻量端标记LIGHT_EXECUTOR；USD端从实物读取。用料开工、执行采样及提交前检查位置/身份/可见性/数量/支承；缺证不能完成，K缺输入证据为INCOMPLETE、错误输入证据为INVALID。旧r1历史缺少该证据时不自动补造或升级。

当前只支持WITNESS_FRAGMENT机制配置。保留37活动图不构成生产模式/单元/时间/质量/等待映射；PRODUCTION在完整映射实现并验证前明确拒绝PRODUCTION_MAPPING_NOT_IMPLEMENTED，K亦独立拒绝。该保护没有实现或授权S15全链。

2026-10-04实施结果：接口主体已实现，源码/wheel各509项与真实Kit 12组见证通过；见[最终报告](../validation/S14_adapter.md)。下方“尚未实现”保留设计时点。

实际入口为 `backends/isaac_adapter.py`，Kit侧为 `sim/isaac/scene/logistics_port.py`。配置与域消息来自独立S14族。`dispatch`先事务准入及实际场景前检，STARTED不等于完成；`advance(seconds, playing=...)`由驱动提供仿真秒数，暂停不推进；`feedback`只消费执行端关联读回；`deliver`按观察到达时间送达。故障保持锁/在途实际样本，恢复命令携带resume_of和累计已执行时长，准备/装卸不重复计时。

USD端逐次读取现有碰撞包络、角色位置、设备属性、载具/货叉/吊钩/托盘及落位支承。完成须实际到位并摘离；WORK计时完成不会产生质量PASS。RECEIVE_EXTERNAL等待独立Receiver的run/epoch/command/product/receiptId及厂界外支承读回；无端口保持在途承诺，不伪造接收。真实见证使用独立合成接收夹具，未接真实企业系统。

复现入口：`python scripts/build_logistics_contracts.py --check`、`python scripts/check.py`；真实Isaac用已配置环境执行 `scripts/verify_logistics_isaac.py --output <新的本地输出目录>` 并由本地监督器核对退出/清理。不要把CPU受控端口测试、截图或渲染耗时当作真实工业能力或FPS。

2026-10-04现行决定（PR108 / LOG118）：负责人已批准S14-CONTRACT-20261004-r1的ML01—ML12限定修订，决策S14-ML-APPROVAL-001。允许按表修改D01/D03/D04所列项并继续S14共用契约、验证及适配；通过前置出口后进入适配主体，不再等待本表批准。D02/G2与HR禁用、D05顺序、D06元数据及其余冻结边界保持。S15—S28及新快照Git/远端写入仍未授权。以下待决定文字保留其历史时点。

2026-10-04；**DESIGN_ONLY / PRECONDITION_PENDING**。本文件是S14已授权范围内的接口盘点与设计，适配代码尚未实施。[契约决定稿](../model/material_logistics_extension.md)获批并通过[前置出口](../validation/material_logistics_contracts.md)后才进入主体。不得把现有S13排演驱动包装成已完成的生产闭环。

## 命令、场景和实际事件

| 动作 | 拟场景对象/已有接口 | 事实来源与必须核验项 | 可产生的新版反馈 |
| --- | --- | --- | --- |
| 接纳/拒绝/延后 | 新命令入口；现有TargetTrialScene没有生产dispatch | 校验版本、epoch、配置摘要、角色/资源/材料/位置、原子所有权；先记录命令摘要 | ACCEPTED只代表已接纳；REJECTED无生产副作用；DEFERRED表示未启动且无暗中占用 |
| 人员到位/准备 | 15名人员world position，`TargetScene.readback()` | 实际位置、合法路径与任务绑定；操作/监护角色持续可用 | STARTED需全前置满足；途中离位EXCEPTION，保留承诺 |
| 取料/挂接 | FORK/CART/CR1、源库位与载荷 | 身份、放行/数量、叉/托盘/吊钩相对支承、源/目标预留与容量 | 实际取料事件；未完成挂接不得移动，不以发命令返回成功代替 |
| 运动/障碍 | `actual_obstacles()`及USD位置/包络 | 实际当前障碍、路段锁、设备异常、承载同步；静止吊机也是障碍 | 位移事实或EXCEPTION；到达失败保持载荷与所有权 |
| 卸载/落位/释放 | 目标支承、载荷底面、持有者 | 实际目标包络内、稳定支承、退出/摘钩证据；不能仅比较规划终点 | 实际落位事件后变更位置；必要空返结束后释放设备 |
| 工序完成/质量 | 工作单元、实际执行进度、独立质量输入 | 原子工作单元结束与质量记录分别处理；S13场景操作标志无质量资格 | 工作COMPLETED不等于质量PASS；UNKNOWN保持HOLD |
| 成品转存/外接收 | FG1/FG2/DISPATCH、拟边界端口 | 源槽实际搬出落位；装载/移出与唯一接收回执相关联 | 内部到达只换位置；外部RECEIVED独立，不能由准备信号生成 |

现有`TargetScene.sync()`把排演状态写入USD，再由`readback()`读取世界位置及支承；这证明受测几何一致性，不是独立生产完成传感器。适配时实际事实只能由执行端提交，规划端不能传入actual位置/质量PASS。K还需核验事件与守恒。已有缓存按阶段更新；实时障碍变化须显式失效或当步重读，不能用过期包络通过新障碍。

## 身份与状态机

拟关联键为 `(run_id, epoch, command_id)`，携带config/布局摘要、product/activity/attempt/unit/mode、具名角色、payload摘要。事件另含唯一event_id、命令内单调seq、source、发生仿真时刻和观察到达仿真时刻。产品身份必须与活动配置一致，不接受只带sceneId的生产完成。

命令先进入ACCEPTED、REJECTED或DEFERRED。ACCEPTED经实际准入到STARTED，随后COMPLETED或EXCEPTION；异常后的恢复使用新命令并引用原承诺，不重放已完成单元。DEFERRED不自动重试；重新观察后以新命令ID申请。运行中阻塞属于已开始任务的事实，不能改成未开始DEFERRED以偷偷释放资源。REJECTED/COMPLETED为终态，终态重放返回原回执。EXCEPTION终结该命令的正常执行，但载荷、位置和物理持有持续存在，恢复命令才能合法接续。

同键同payload返回原回执；同键异payload拒绝。重置创建新epoch，旧命令/回调记录为过期且不改变新运行。不得仅清空去重集合而接受旧包。乱序事件按seq缓存、保留到达顺序供审计；缺口超过规定观察期限报告INCOMPLETE/需要重同步，不凭收到COMPLETED跳过STARTED和落位。重复event_id异payload必须报告冲突。过期反馈可以补审计，不能覆盖更新状态。

## 三种时间

领域统一小时：`occurred_sim_h`描述实际发生，`received_sim_h`描述进入观察层，规划只见已送达数据；墙钟使用独立单调计时测延迟/预算，UTC仅诊断。Kit时间以明确的单调仿真累计映射小时；暂停不推进生产时钟，重置由epoch隔离。诊断墙钟不可写作生产发生时刻；应用更新耗时不是FPS。合法旧事件可以晚到，负时间、非有限值或同epoch时钟回退须拒绝/进入同步故障。

## 两端及验证责任

共用新版消息由轻量执行器和Isaac执行端生产，由S12观察层消费；K根据原始事件重建，不能依赖适配器自身PASS。拟实现入口为`src/adaptive_hrc_scheduling/backends/isaac_adapter.py`，专项为`tests/test_isaac_adapter.py`；两者当前均未创建。旧`BuildingBackend.Receipt`的accepted/reason二值回执保留旧版语义，不能冒充上述完整异步生命周期。

测试顺序及真实场景负例见[验证清单](../validation/material_logistics_contracts.md)。S15全链及双后端成对实验仍未启动；S14只在本步授权内完成共用前置和适配证据，不预写后续闭环通过。
