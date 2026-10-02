# S11 静态可行调度与合法规则

2026-10-02；实现接口S11-1.0，输入C04-1.0/C03-0.3。本步仅生成初始可见窗口的完整候选；动态反馈与中途重调度留S12。工业证据G1/G2/G4/G5/G6/G7仍未关闭，默认HR禁用。

## 输入、输出与使用

```python
from adaptive_hrc_scheduling.planning.decoder import Options, generate_plan

result = generate_plan(configuration, initial_observation, Options(rule="EDD"))
```

`initial_observation`须为t=0完整观测：全员初始F、零累计E、无已完成活动、无取消或未知状态、无资源故障/在途承诺。不能把中途状态缺项当作空闲；缺失或非初始状态明确INVALID_INPUT。API不接收HiddenScenario、实际快照或未来事件列表。配置中的未来独立订单产品在构建候选世界前投影掉，返回的`configuration`就是这份可见配置；指标只适用于该可见集合。如果同一已见订单仍含不可见必需成员，返回NO_PLAN_FOUND，防止截掉成员而宣称订单完成。

返回`Result`含status/reason、投影配置、初始观测、plan、完整trace、独立report、waits、assumptions、决策次数和实际wall_ms。只有FEASIBLE返回非空plan；失败保留实际候选前缀与等待诊断，但plan为None。完整配置/观测/计划/轨迹/报告必须一起留存，单独的预测时间不是证据。轨迹包含全部人员、活动、材料、质量、休息及驻留；不是仅有派工命令的动画。

| 状态 | 判定边界 |
| --- | --- |
| FEASIBLE | 可见完整产品全部READY、37活动/必需BOM/质量链完成，非空命令与完整轨迹通过S10独立检查；只证明给定合成条件下候选可行 |
| NO_PLAN_FOUND | 贪心次序受阻、缺事实/资格、预算/时间窗耗尽、独立核验失败等；不是数学无解 |
| INFEASIBLE | 仅对当前固定实例证明必需搬运中`实体质量+吊具质量>指定设备能力`，给出活动/实体与数值；不是通用不可行判定器 |
| INVALID_INPUT | 配置/观测/参数不合法或超出此静态入口支持范围 |

默认不会生成QUALITY_RESULT或PROCESS_RELEASE。研究配置UNKNOWN仍HOLD；即使方法资格给定，未知未来质量结果也不能默认PASS。合成正向测试须显式设置`Options(synthetic_gate_assumptions=True)`，且配置purpose必须为SYNTHETIC_TEST_ONLY。此时在检查劳动完成后假设质量PASS，在实际等待时限满足且资格有效后假设工艺释放，记录`S11-ASSUMPTION-*`候选事实及`SYNTHETIC_ALL_PASS_QUALITY_AND_PROCESS_RELEASE`标记。这是条件候选模型，不是工厂观测、未来情景读取或工业证明。不会假设RECEIVED来腾空OUT1。

## 生成与排序

每个决策点从DAG前序与当前attempt进度构造待派工集合，枚举启用且具方法资格的模式和具名、互异、未过期的角色绑定。续作保持已准备角色绑定，不免费换班或切模式。每个组合在独立的不可变快照副本上调用C05原子准入，检查日历/全员cap、设备/路线、齐套、质量祖先、工艺等待、实物位置、目标预留/驻留、工作面及已有承诺。拒绝探针不写入真实候选日志。只有全部约束满足的候选才能排序；不把紧交期放在合法性之前。

所有规则共同使用稳定平局键：产品ID、活动ID、模式ID、按声明角色次序排列的角色/人员ID元组；人员与活动枚举按ID排序。没有随机抽样或随机种子；同输入重复得到同命令、轨迹和诊断，墙钟时间除外。反转输入活动/边列表仍给出同一命令序列，证明没有沿用历史手工见证次序。

| 规则 | 排序定义 |
| --- | --- |
| EDD | 当前合法候选按产品due_h升序，再用共同平局键 |
| SPT | 按当前活动剩余主动单元的估计总时长升序，再用共同平局键；不是仅比较下一微单元 |
| FASTEST_MODE | 各活动内先选当前合法组合中估计剩余时长最小的模式/绑定，再跨活动按EDD与共同平局键排序 |

估计为Σ base_h·(1+κ·F)：当前已绑定角色取当前F；后续尚未绑定角色保守取该资格池当前最大F；不包含被动等待，不预测恢复/拥堵或未来资格。每个工作单元仍按实际起点F执行并重新检查cap和班界。模式一旦进入attempt保持承诺。默认HR禁用时FASTEST_MODE只能在现有合法模式内选择；另有显式合成HR资格的功能分支测试，不开展A收益实验。

每次最多枚举max_bindings个组合；超限不排序残缺集合，直接NO_PLAN_FOUND。max_decisions限制决策点数量，horizon_h限制候选仿真窗口。它们是确定性停止条件，不是S19墙钟预算控制；wall_ms只记录实际耗时，不宣称在线实时保证。

## 等待和失败证据

没有合法候选时，记录活动/模式/时刻/拒绝原因及等待关系：前序活动、具名人员、被占设备及owner、目的地及驻留owner、冲突工作面活动。它是可检查的等待关系边表，不宣称一般死锁证明。对疲劳受阻且空闲的人显式安排最小休息并计费；随后推进至已知运行完成、等待到期、休息结束或相关日历边界。没有已知进展事件时停止并返回NO_PLAN_FOUND。没有清空锁、虚构场地释放、删除在制品或省略质量门的解锁分支。

固定单产品实例足以覆盖从双框到完整模块；共享CR1、多人班界和双产品有限OUT1另有针对性验证。双产品用例可以保留一个READY模块占OUT1，使第二模块保持在F1并失败；这不被包装成全单完成或确证无解。贪心解码无回溯、无可行性完备保证，不是LNS或CP-SAT。

## S10最小接口适配

`check_run(config, trace, plan=plan, observation=obs, candidate_trace=True)`增加静态候选绑定检查，返回报告S10-1.2。原调用默认False，仍返回S10-1.1并保持非空计划缺绑定证据时INCOMPLETE。原独立R01—R18重建不导入规划器或执行器准入函数。

新检查将命令ID序列与消费表、命令活动/模式/attempt/单元/时刻/角色与UNIT_START/READY按序一一比对；从全员积分边界与已记录派工、显式休息和候选事实独立重建修订号，核对命令expected_revision及最终revision。此修订重建限无隐藏情景、无维修/交班服务的初始静态轨迹。还要求初始观测完整一致、非空候选、所有活动完成、全产品READY以及预测时刻等于重建READY。空计划、合法但未完成的前缀、孤立预测、漏/重复/错序命令、篡改角色/时刻/修订号/质量或缺日志均不能放行。原合法前缀PASS语义不变，但不能当作S11成功。

此适配只为S11完整候选核验，不替代S12“相同可见历史下策略行为一致”的动态非预知验证。没有接入Isaac闭环或外部调度适配器。

## 复现与实际验证

```powershell
uv sync --locked --no-editable --reinstall-package adaptive-hrc-scheduling --link-mode copy
uv run --locked --no-editable python -m unittest discover -s tests -p test_rule_planners.py -v
uv run --locked --no-editable python scripts/run_rule_planners.py --output .local/s11-cases --check
uv run --locked --no-editable python scripts/check.py
```

[合成输入清单](../../examples/rule_planners/cases.json)复用冻结C04生成器，仅描述本步测试参数；[摘要](../../examples/rule_planners/summary.json)不含完整原始日志或机器耗时。完整输入/候选/报告由脚本写入调用方本地目录。公开摘要含两变体×三规则共6个成功，以及研究HOLD、质量未假设、固定超载、短窗口和有限出厂位共5个失败病例。成功时间是合成回归结果，不与手工见证作算法收益结论。

专项34项方法覆盖上述正反例及输入顺序、重复确定性、准入不修改世界、先合法后优先、共同角色/班界/疲劳、默认HR门、条件模式分支、J2同产品双框与FIX-J2独占、未来产品隔离及订单成员保留。完整项目、独立wheel及工程检查的实际次数/耗时见[S11步骤卡](../steps/S11.md)。第一轮测试中的两处非法输入在夹具构造时提前抛错、一次跨配置ID比较失败均原样保留，修正测试入口和ID归一化后重跑；没有放宽生产约束换取通过。
