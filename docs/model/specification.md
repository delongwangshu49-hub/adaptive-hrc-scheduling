# 完整钢建筑模块调度：下一版模型规格

版本 C03-0.3；2026-10-02；研究规格FROZEN_WITH_GAPS（PR069），C04/C05已实现合成代码见证。历史管道代码继续对应[S09 r2管道规格](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/blob/step-S09-r2/docs/model/specification.md)。PR067选钢体系；专属规范入口为[产品与生产规则](selected_steel.md)、[活动](steel_process.tsv)、[逐边](steel_edges.tsv)、[模式](steel_modes.tsv)。

## 领域对象和状态责任

Order引用必需Product集合；Product持续保存位置、版本、BOM谱系、质量状态及完成量。Component/Material、Activity、Attempt、WorkUnit、Move、Reservation、Residency、Qualification、QualityRecord与Person分开。纯逻辑前序不制造物料，检查不消耗产品，MOVE不重复生成实体；同一活动返修创建新attempt，旧尝试不可覆盖。

拟定Product主状态为RELEASED、IN_PROCESS、BLOCKED、QUALITY_HOLD、CANCEL_PENDING、QUARANTINED、READY、RECEIVED；地点与状态正交，QUALITY_HOLD不表示产品离开bay。Activity状态为NOT_READY、READY_TO_START、RUNNING、PAUSED_AT_CHECKPOINT、WAITING_RELEASE、FAILED、COMPLETED、CANCELLED；READY_TO_START也不保证资源原子获得成功。

## 可核验约束

R01身份/BOM守恒；R02逐边、质量与等待许可；R03同输出模式资格；R04具名班组及独立角色；R05设备/工装/地点容量；R06工作面相容；R07劳动、驻留与释放分离；R08真实MOVE载荷/路线及预留；R09合法停点、进度/准备保存；R10逐人保护及班次；R11质量/有限返修；R12齐套及变体；R13事件与取消清场；R14非预知观测；R15完整READY/接收；R16同刻次序及幂等消费；R17评价集合/窗口；R18版本与缺失资格拒绝。每条独立定义与正反见证见[验证设计](../validation/building_witnesses.md)，不能用实现许可函数定义其真值。

## 决策变量和目标口径

对未承诺工作单元选择模式m、合格角色映射x、资源/位置r、开始s与顺序π；选择合法停点后的休息长度和交班。已完成记录、不可中断段、悬吊移动和有效预留属于执行承诺，不参与任意破坏。角色/模式只在共同输出成立的边界切换。工作包时长来自固定模式与逐人状态倍率，不按人数线性除工时。

区间用半开[s,e)，任一资源的占用和预留容量总和不超限；同产品位置唯一，但MOVE允许源/目的保守双预留。后继开始不得早于所有适用完成/释放记录，缺失或UNKNOWN不能用0替代。等待时界已到但质量未知仍阻塞。

在线主目标候选为已观察未取消订单的加权预测拖期；D分别约束或比较总累计暴露与最大个人暴露，共同个体cap不变。后续实验采用词典序或权重扫描需在S20冻结，不在C03伪称最佳权重已知。离线完整窗口另报未完成/取消、清场和占位，不能删除失败样本降低目标。参数单位及方程见[参数](parameters.md)和[人因](fatigue.md)。

## 准入与工程边界

产品尺寸/套件为A，时间/负荷为E；G1/G2/G4/G5/G6/G7工业证据未关闭，特别是HR-seq默认DISABLED。可呈交研究规格供负责人裁定，但不能宣称工业执行规格已冻结或开始A实验。研究冻结与工业资格各有状态。

C04—C05按一个[修复栏目](../repair_plan.md)处理旧资产依赖；S10独立检查与指标已获PR077授权并形成本地候选，S11—S28仍未实施，按[逐步路线](../roadmap.md)分别授权。PR071已授权并实施C04/C05本地改造；实际支持和限制见建筑执行验证。

C04/C05实际实现、入口、受测范围与保留HOLD见[建筑执行验证](../validation/building_execution.md)。本文件的研究规格不因代码通过而升级工业资格。
