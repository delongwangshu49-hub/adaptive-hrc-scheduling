# C04—C05 建筑执行验证

## r2有限修复的当前结果（PR074—PR075）

r1已按PR072验收并发布；下文原r1结果与失败记录保留其时点。r2只修复全审所列六项问题及必要集成边界，工作VERIFIED，人工PENDING_REVIEW，上传NOT_APPROVED，远端NOT_PUBLISHED；r2远端CI NOT_RUN。

完整CPU检查通过：项目249项（80.927s）、独立wheel249项（81.534s），均含69项建筑与180项旧域回归；新增18项修复回归。Ruff/格式、锁文件、依赖检查、wheel/sdist构建及建筑生成物一致性通过。

| 审阅项 | 修复与实际回归证据 |
| --- | --- |
| AUD-C05-01 | 必需质量/等待/释放门、模式、劳动单元和必要设备不可用null/空列表绕过；删除全部7种质量门及5种等待门的反例被拒绝 |
| AUD-C05-02 | INVALIDATE持久标记受影响attempt失效并撤销释放，逐级祖先和QUALITY_HOLD阻断新派工；已承诺搬运保留安全尾部；普通工作/等待失效、移动中失效及恢复均覆盖 |
| AUD-C05-03 | 恢复核对实物位置与占位/源位/目标预留双向一致；缺失、幽灵、错误owner/标记被拒绝；37活动边界、多段搬运中途、清场HOLD及外部接收的合法快照可恢复 |
| AUD-C05-04 | advance跨过新悬吊故障只推进至故障时刻并保留实际轨迹，粗/细粒度推进得到相同检查点；后续无安全路径不能继续 |
| AUD-C05-05 | 清场开始前核对源位和Q1，运行中把源/目标故障纳入依赖；故障Q1不允许落位，拒绝原子性及在途故障恢复通过 |
| AUD-C05-06 | 当前架构、单位、入口与发布状态同步；建筑契约采用h，旧数值核心通过适配器换算；历史封包不重写 |
| PR075 J2 | 同产品底/顶框可驻留，其他产品受容量1限制；FIX-J2仍独占，第二框不能同时使用工装 |

`advance(until_h)`现在返回Receipt：正常推进为accepted=True/ADVANCED；遇到新的EMERGENCY_HOLD时为accepted=False/EMERGENCY_HOLD_NO_SAFE_PATH，状态已提交到真实故障边界，time可能小于请求终点。调用方必须检查回执与实际time。已有HOLD时再请求向前推进仍抛ContractError；不会为满足请求终点推演无安全路径的未来。

质量修复也核对有效祖先；Q-POND局部返修不能解除其他上游失效。返修中遇到上游失效/取消时，已发生劳动和材料消耗保留，结束记录REPAIR_STOPPED并继续HOLD，不伪造返修完成。合法一次局部返修到READY的正向测试通过。

两变体正常链重跑后与r1公开摘要逐值一致：SR-W1为149.598500771668h、SR-W2为171.61789240458066h，均7个有效PASS；READY后1h外部接收，全部15人至240h的F/E/峰值一致，另用区间方程独立复核积分。Schema与样例未改，语义校验拒绝原先错误接纳的输入，契约仍为C04-1.0。

修复前14项新增测试实际失败（67个子用例失败、1个错误）；修复后最终18项通过。原始失败与中间复验留本地，未以删除旧测试达成通过。本次不提供全部可能输入的正确性证明，也不替代S10独立检查器。工业缺口、HR禁用、未知拆装修复/组件清场/悬吊安全路径HOLD保持。

## r1原始实现与验证记录（历史时点）

2026-10-02；契约C04-1.0；规格C03-0.3；范围为合成代码见证与必要回归。负责人尚未验收本轮快照，上传未批准。G1/G2/G4/G5/G6/G7及HR默认禁用保持。

## 实现和接口

`domain/building.py`提供Product/Component/Material、Activity/Mode/WorkUnit、Attempt、具名Role、质量/驻留、10类消息及完整恢复字段；`contracts/building.py`复用旧严格结构编解码机制，重建建筑语义。`building_human.py`明确将h、h⁻¹、F·h转换为旧数值核心的min单位后逐人积分；`building_backend.py`提供手工派工执行、原子锁、驻留、等待/质量、搬运、取消/清场、有限返修和观测队列。旧域源码接口、十类旧Schema与样例保留，不静默迁移。

执行接口为`BuildingBackend(config, scenario)`、`dispatch(command)`、`advance(until_h)`、`rest(person_ids, duration_h)`、`handover(activity_id, outgoing, incoming)`、`repair_quality(activity_id)`、`cleanup(product_id)`。`apply_event`是可信执行适配器的当前时刻事实入口，不能给规划器使用。`observe(delay_h, missing)`只返回到达的授权观测，未来队列用`deliver_observations()`提取。`checkpoint()`/`restore(config,text)`绑定完整配置摘要，保留时钟/单位锚点、当前与历史attempt、全部F/E、锁/驻留、物料、事件游标、已消费命令、观测队列及交班/返修/清场承诺；无随机抽样，随机游标明确为0。原始检查点含隐藏情景，只供执行/恢复。

同刻先完成、稳定落位和释放，再按event_id处理外生事实，最后可见观测/新派工。事件与命令ID分别幂等；拒绝派工保留拒绝日志和命令消费，但不提交部分物理变化。MOVE显式出现IN_TRANSIT，源位保留到落位；JOIN-IN按底框、顶框、柱批次逐次稳定落位，最终才合并三维实体。原材料入厂的KIT占PRE，CUT完成才创建可移动组件；配置中initial_location是制造后的初始地点，UNFABRICATED不占一份实体空间。

## 实际见证与规则映射

| 见证 | 实际核验 | 规则及适用边界 |
| --- | --- | --- |
| V01 | SR-W1/W2完整37节点、40边、7质量门到READY；删除/失效Q-FIN后不READY；外部接收才释放OUT1 | R01/R02/R15；仅SYNTHETIC_TEST_ONLY条件输入 |
| V02 | 双产品下游满位拒绝、保留F1/J3源位；迟接收后第二产品才可进入OUT1；拒绝前后物理快照相同 | R05/R07；并非通用无死锁证明 |
| V03 | 合成已批准D-E/W-P并行；撤相容许可则拒绝 | R06；G6工业布置仍未证 |
| V04 | 缺角色、同人填独立角色、资源原子性；全15人窗口与cap核对 | R04/R10；资格标签不代表职业证书 |
| V05 | 8+1≤12与12+1>12t；在途保留源/目的预留、落位释放源；组件和整模块独立移动 | R08/R01；真实质量/吊点/应急方案未知 |
| V06 | 等待到时无PROCESS_RELEASE仍阻塞；试验水/TEST1保留至排水卸载 | R02/R07；数值等待不等于材料资格 |
| V07 | H-D1有理数核对E=0.332203125、终F=0；高F与班末不足拒绝；交班两人0.1h及恢复0.1h；完成前一可表示时刻不提前完工 | R09/R10；工艺停点采用受控合成资格 |
| V08 | 蓄水FAIL后一次诊断/局部修复、替换套件与独立复验介质、重复防水等待/设置/蓄水/复检；原FAIL不覆盖；第二返修拒绝 | R11；拆装/结构返修方法未知则HOLD，未编造流程 |
| V09 | SR-W2新增BOM/支路与工作单元；支路料缺失只阻塞MEP-P；跨产品材料引用拒绝 | R12/R01 |
| V10 | 悬吊取消保留承诺并落位，清场需Q1/角色/真实1h搬运；吊机故障EMERGENCY_HOLD；重复消费拒绝；同刻完成后取消阻止READY | R13/R16；没有获准应急安全路径时禁止继续推进时间 |
| V11S | 双框→三维装配→F1驻留；更新夹具资格版本拒绝；恢复配置摘要、正在执行锁和锚点校验 | R01/R03/R18 |
| 信息与恢复补充 | 两种未来故障脚本在同可见历史给出相同观测；工作与搬运中途恢复得到同一检查点/观测；延迟与缺失保留 | R14接口隔离，尚非S12调度决策非预知证明 |
| 全员手算核对 | 全15人[0,240]连续覆盖；测试独立按分段方程复算F、E、峰值 | R10及R17口径局部核对，不是S10通用指标检查器 |

C04有20项契约测试；C05有31项执行测试。生成的10类Draft2020-12 Schema另经jsonschema 4.26.0结构验证，语义仍由Python边界负责。项目全套CPU与独立wheel结果以阶段收尾记录为准；旧180项单列为历史回归，不计建筑覆盖。

## 真实失败与修正

1. 默认执行器及Node内核在启动前出现setup refresh故障；显式PowerShell7受审执行通道可用。没有回退旧PowerShell。
2. 首次独立Schema验证命令遗漏UTF-8，在本机默认编码下读取中文JSON失败；显式UTF-8后通过。生成器文件句柄警告改为受控文本读取。
3. 首轮C05复验误用已消耗的TEST-SET材料；修复为独立REPAIR-TEST-KIT，不退还原材料、不跳过复验。原FAIL质量历史保留。
4. 交班0.1+恢复0.1的可表示结束点略晚于字面24.2；预测改用相同前向时界，测试推进实际结束点，未加容差提前释放。
5. 扩展测试首次遗漏validate导入，实际报NameError；修正后重跑。首轮静态检查的格式/未用名诊断经格式化与明确修正解决。

6. 收尾守恒复核发现CUT创建组件后还保留原料批次占位记录；移除已消费原料的驻留记录，并在既有V11S测试中断言该边界。此前结果未据此提升为已验收。

全部原始失败、成功日志、输入与检查点只本地保留；公开不附机器日志。

## 限制及NOT_RUN

默认RESEARCH_BLOCKED配置保持UNKNOWN，KIT拒绝，HR-seq禁用。SYNTHETIC_TEST_ONLY只让受控夹具验证条件分支；不是工业许可证、负责人对工艺的新批准或A实验输入。工业正常生产仍HOLD；代码测试通过不把资格缺口写成PASS。

Q-POND局部返修采用G7条件夹具并计诊断/修复/重试成本；未知拆装、未装配组件清场及悬吊故障安全路径保留HOLD。进程内观测投影不等于对任意恶意Python代码的安全沙箱。通用死锁检测、S10独立日志检查/绩效、S11调度、S12动态决策、Isaac生产闭环、CP-SAT/LNS、V12模式收益及A/D/B/C正式实验均NOT_RUN且未实施。各函数适用范围如上，不提供工业安全/人体效益结论。

## 复现

```powershell
uv run --locked --no-editable --reinstall-package adaptive-hrc-scheduling python scripts/build_building_contracts.py --check
uv run --locked --no-editable python -m unittest discover -s tests -p 'test_building*.py' -v
uv run --locked --no-editable python scripts/run_building_witness.py --output .local/building-witness
uv run --locked --no-editable python scripts/check.py
```

见证脚本按冻结顺序手工派工，只为特定代码见证选择下一个合法工作/休息时界，不实现通用策略生成器。输出目录包含原始执行状态，应保持本地；经审查摘要位于`examples/building_execution/`。
