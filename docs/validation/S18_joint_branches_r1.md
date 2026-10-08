# S18 条件程序分支 r1：确切审阅

2026-10-07；PR139 / LOG180；候选 **S18-20261007-branches-r1**。

**程序成果VERIFIED_WITH_LIMITS；S18研究整步RESEARCH_BLOCKED_G2_OPEN；ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。** 当前沿用main和S17 r2已发布基线。此包是可审阅的条件程序里程碑，不是S18全部出口完成，不支持启动S19或正式A/D实验。

## 已实现与核验证据

`joint_lns.py`交付真实门拒绝/条件门、观测绑定、模式/具名班组/次序/延迟开始/显式休息的有限提案尾段、后缀破坏/约束修复及S17缓存/预算复用。正在执行、准备、材料、班组和实物驻留前缀保持；独立S10重建完整观测前缀+候选尾段，最终返回也检查。工业PASS标签不能替代适用产品/接头的审阅资格。算法和限定域见[方法说明](../algorithms/joint_modes.md)。

最终 **34项专项、源码693项/203.676s、隔离wheel693项/206.422s** 通过；锁依赖、Ruff、145文件格式、依赖相容、sdist→wheel及锁定reference组摘要安装通过。144现行Python输入摘要最终核对一致，213冻结文件未改。原S17七例公开summary逐字段与新私有重跑一致，逐轮重放通过：六合法目标3/3/5/8/17/15、不可修复例WAIT。没有环境升级、新Kit或新远端CI；S17双平台659项是实际发布回执，不能当本包远端证据。

## 机制、无收益与反向

全部公开机制均CONDITIONAL_C04_BRANCH_ONLY，以同一8h比较窗口审计，目标仅PRODUCT-1.W-B。同一配置内的联合/固定模式共用规则、cap、日历、负荷、绑定预算及搜索参数（seed18、4迭代、6修复试探/轮、30s协作墙钟）。工时和负荷数值保持原冻结夹具，不作正式效果结论。

| 条件例 | 本轮实际结果 | 含义与限制 |
| --- | --- | --- |
| 正常/无关TEST1故障 | HR-seq，目标3.9928861h；两例候选选择/数值一致 | 反馈可以不改变合法选择；等于固定HR，没有进一步收益 |
| 已观察R1故障/同域固定H | H，目标6.206065494h | 反馈确实改变模式；不是隐藏未来R1故障预测 |
| 卸载晚到岗，固定HR | 7.5h；机器人早结束但R1/FIX-J2/J2保持至实际卸载 | 局部加工加速被人员/日历等待抵消 |
| 同晚卸载，固定H | 6.225840079h | 固定HR反而晚；不同日历例不能与正常例混作算法效应 |
| 同晚卸载，有限联合搜索 | 仍HR、7.5h | 未找到更早H；无益/反向搜索结果完整保留 |
| 去疲劳排名部分开关 | HR；评分中人因分量为0，独立实际核验仍保留 | 当前仍使用实际完成时刻与安全状态，**不冒称完整去状态信息消融** |

具名班组状态改变、两框次序反转、显式休息与其时间/负荷、同历史异隐藏未来一致、运行/准备模式保持、机器人结束不伪释放、缺料/短窗、资格版本/字段、伪释放/错角色/陈旧命令及独立检查拒绝由34专项覆盖。机器可重跑记录见[机制摘要](../../examples/joint_modes/mechanisms.json)和[验证JSON](S18_joint_branches_r1.json)。这些是旧C04条件程序尾段；**没有把它们提升为S15完整生产、生产HR物流或Isaac闭环证据**。

## 实际失败与保留

首轮六机制因完成事件名称读取错误全部WAIT；改为已有ACTIVITY_COMPLETE/COMPLETED后通过。初版29专项有1失败/3错误（投影配置比较、Builder接口及S10诊断字段），真实日志保留；校正后最终34通过。初次新文件lint发现导入/同线语句并已格式化修正。晚卸载联合搜索未找到固定H的较早尾段不重标成功收益。

原S15 720h截尾/疲劳INVALID、WV01监督失败、S16反例及S17原回归失败/停止/短窗失败、r2 WINDOW_CENSORED均保持原身份；本包未重新标定或替换任何历史证据。

## 尚未满足的整步出口与裁定

真实G2同产品同接头资格及G5等适用工艺门未关闭。S15生产契约无HR-seq分段映射，尚无现行人员/设备位置、运输/准备、有限槽位与Isaac读回共同执行证据；对应扩展S10生产/决策审计、完整生产未来可行性和完整状态信息消融也尚未完成。**S18研究整步BLOCKED，不能完整验收或交接S19。** 具体Q01—Q06资格及M01—M02映射/冻结决定见[逐项裁定稿](../model/S18_qualification_decisions_r1.md)。本轮不解冻D02，不虚构资格、不改时间/负荷制造HR优势、不删除A。

RP/SC/SH/WV及D01—D06其余边界、工业UNKNOWN、合成质量/外接收、有限几何/运动学和GUI未单独体验验收保持。负责人贡献为S18启动/范围授权，AI辅助实现、验证与治理，不虚构人工编码、实验或验收。

## 确切文件与发布边界

本包17文件（含S17 r2实际回执及S18治理）如下；逐文件SHA-256、全部新增/修改差异及封签保存在本地审阅包，公开JSON列相同确切集合。

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/joint_modes.md`
- `docs/architecture.md`
- `docs/model/S18_qualification_decisions_r1.md`
- `docs/roadmap.md`
- `docs/steps/S17.md`
- `docs/steps/S18.md`
- `docs/validation/S18_joint_branches_r1.json`
- `docs/validation/S18_joint_branches_r1.md`
- `examples/joint_modes/mechanisms.json`
- `scripts/run_joint_mechanisms.py`
- `src/adaptive_hrc_scheduling/algorithms/joint_lns.py`
- `tests/test_joint_decisions.py`

目标为既有仓库main，基线62c1c5393cb715b8089a93ee7ec658a0eb0e571d；拟标签 **step-S18-branches-r1** 明确仅条件程序里程碑。当前拟执行远端操作为空，未暂存/提交/标签/推送/PR/附件。本程序成果的限定验收及任何确切发布需负责人针对本包分别批准；若批准，才按精确清单暂存、复核全部拟推送历史与署名、创建单一提交及新annotated标签、非强推main/新标签，核验远端树/摘要/对象和双平台CI。完整S18研究验收不在此条件程序包的主张内。
