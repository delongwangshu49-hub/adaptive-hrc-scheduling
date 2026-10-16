2026-10-12当前接续（PR177 / LOG242）：本对话已实际开展全场类别盘点、有界动态调查与具体拟案；问题OPEN/NOT_FIXED，方案PROPOSED / OWNER_DECISION_PENDING / IMPLEMENTATION_NOT_AUTHORIZED。入口：[调查与10图](../sim/emergency_scene_investigation_r1.md)、[E01—E08及有限冻结例外](../sim/emergency_scene_correction_proposal_r1.md)、[机器摘要](../validation/emergency_scene_investigation_r1.json)。新增碰撞/附件范围/换装工时均待负责人明确裁定；不把1300静态候选筛查、原生连续诊断或旧B1认可当作实施批准。以下保留原交接时点。

# 紧急修正：悬浮、重叠漂浮问题交接

2026-10-12；PR177 / LOG241。负责人要求新建“紧急修正”对话，沿用当前目录/main，不创建新分支；交接现有问题，在新对话全量排查原因、拟定具体修正方案，报负责人批准后才实施，再提交审阅。当前 **FULL_SCENE_INVESTIGATION_AND_PROPOSAL_AUTHORIZED / IMPLEMENTATION_NOT_AUTHORIZED / OWNER_DECISION_PENDING**。不得把“紧急”当作跳过方案批准、冻结项核查或验收。

## 工作区与已知状态

HEAD为aab9ca848eec6816717f2929a8217f642c3bc2bd，分支main。保留全部未提交改动、原封包、原摘要与所有失败；不建worktree或子代理，不执行Git暂存、提交、标签、推送、PR或发布。Windows命令显式使用PowerShell7；现有根CPU、隔离桌面与Isaac环境保持，不安装新栈。

S19B最新B1反馈修订为B1_UI_FEEDBACK_VERIFIED_WITH_LIMITS / OWNER_REVIEW_PENDING / NOT_APPROVED / NOT_PUBLISHED，见[审阅](../validation/S19B_B1_feedback_r1.md)、[机器摘要](../validation/S19B_B1_feedback_r1.json)。暗色浅字、方角、中央原生真实Kit视口自适应与检查点后下一次草稿已受测；不能回退成独立场景窗口、静态图片或用界面遮挡隐藏场景缺陷。14组流程/19契约、CPU/两次Kit/验证程序exit0，各119捕获源码匹配。有限前缀、RC完整Kit关闭返回后显式helper退出/跳过解释器收尾、人工/多屏/正式语义性能未验收等边界保持。

工业G2 OPEN / NOT_ESTABLISHED；继续获批仿真研究域。B2/B3、运行中订单扩展、生产暂停/停止/重置、S20—S28与发布未启动。

## 现有证据与不能扩大之处

入口：[既有悬浮支承问题](../sim/S19B_scene_support_issue_r1.md)。负责人在实际Kit图审发现大量悬浮白色短杆，本轮还要求排查重叠、漂浮及其它同类问题。**现有调查只覆盖了部分支承；尚未完成全场或重叠问题的全量根因排查。** 不得把它当作已取得完整问题集合。

已知来源是`production_port.py`的固定落点短横杆，以及`production_support_port.py`建立的移动横杆/停放托片，相关几何计算在`production_supports.py`。真实检查点扫描711个可见且启用碰撞的USD对象，识别510个支承：246固定横杆、132托片、132移动横杆。2mm容差的AABB地面连通性筛查分别发现238/120/120个未连到起点，共478个；完整USD根层摘要前后不变。AABB相邻/重叠可能误判真实接触，这不是结构计算、动力学或工业安全证明，也不是全部悬浮或重叠物体的最终数量。

原执行审计与B1验证通过不证明可视支承真实成立；旧S19A静态外观认可不能覆盖所有生产动态状态。当前问题OPEN / NOT_FIXED，未隐藏、删除、移动这些对象或修改原几何/碰撞。

## 全量排查要求

先读AGENTS.md、README.md、PROGRESS_LOG.md、PROMPT_LEDGER.md、本交接、原问题文档、S19B步骤卡及相关S15/S18/S19A冻结/批准记录。沿当前已保留源码，必要的只读诊断和复现记录另存全新本地目录；不得为了排查直接修复正式场景。

1. 盘点完整实际USD：静态/动态支承、材料与在制品、未生产/未到货对象、设备/工装、人员、接收/存放区与其它可见对象；区分可见性、碰撞、刚体、逻辑占位与实际物体。
2. 检查初始、运行前缀、相关搬运/支承换装/作业/接收状态，以及适用的多产品情况。检查复制/实例化、父子变换、缩放、世界/局部坐标、偏移/叠层、可见性生命周期、旧对象残留、读回与状态映射，不预设根因都来自支承。
3. 对重叠进一步做可适用的几何精查，区分正常接触/装配/承载、AABB假阳性和非预期穿插/悬空；不能只依据包围盒交集判为碰撞缺陷。
4. 对每项保存稳定实体ID、USD路径、时间/状态、坐标/尺寸/变换、源代码入口、截图及重现步骤；明确确定根因、假设、未覆盖项与历史失败，保持诊断/显示不进入规划器。

## 方案交付与批准关口

方案须具体可审：问题清单/优先级、逐项根因与证据、拟改文件/实体/属性、坐标/尺寸/对象数量及碰撞/可见性变化、影响的既有契约与批准项、冻结项例外表、修复取舍、回退方式和验证/图审判据。若依赖新增几何或更改原尺寸、碰撞、路径、手位、生产时间/容量/人因，应明确列出，等待对应批准；不要把旧边界解释为已全面解冻，也不能用隐藏、关闭碰撞、删除未来落点或纯装饰遮掩问题。

应提出覆盖相关支承取放/换装、搬运扫掠、落点接触、多人/多设备、原独立执行/决策审计、完整双后端链与迁移/截图检查的验证方案；哪些实际受影响、哪些不受影响须有依据。不把仅诊断或有限前缀称为修复完成、完整订单/物理承载验证。

本次只授权排查与拟案。**将方案交负责人批准后才实施；实施后展示实际验证和逐项前后图供审阅；成果验收与确切发布仍另审。** 内部排查子阶段不重复等启动许可，也不得先做修复再补批准。

## 本地原始索引与源码入口

- `.local/s19b-b1-feedback-20261011/ui-r5/ui-verification.json`：最终14组索引与三次运行，两个Kit目录内有`scene-support-diagnostic.json`、真实PNG、配置/源码摘要、事件/决策/审计；ui-r1至ui-r4全部失败保持。
- 最新B1累计60文件封包：`.local/s19b-b1-feedback-20261011/S19B-20261012-B1-feedback-r1-review.zip`，SHA256 **228041e2c802922d102c19762234ed8a70a8df535c162aaec08160ade3773bfe**。清单、累计/r1差异、回执在同目录，均非发布授权。
- 原B1封包SHA256：242e1fb458c3502e8f3b6b18f614918b8f2fbf68fe441a4970450819c948c9c2；原型r1/r2为932340ae39376cd390239a4af27ee24f9e99c9d9148ae1d80b5838f393409333、44758d3033d9c465e849ddc812431b6f4d8e16b753641a01b2457f690ae6073c。不要重写它们。
- `scripts/inspect_s19b_scene_supports.py`：只读筛查，不是根因/碰撞精查完成器。
- `sim/isaac/scene/production_port.py`、`production_support_port.py`、`target_scene.py`、`usd_scene.py`、`target_layout.py`与`src/adaptive_hrc_scheduling/production_supports.py`、`production_geometry.py`：优先追溯，但全场排查不限这些文件。
- `scripts/run_s19b_prototype.py`、`desktop/s19b/src/s19b_desktop/app.py`、`embedded.py`及`sim/isaac/s19b_viewport.kit`：当前原生嵌入显示/状态入口，几何/生产修复前保持。

原负责人两张截图仍在本机临时附件；不要仅依赖临时路径。应优先用上述可复现源码、完整诊断、项目图片及原记录。若需要原附件对照，私下本地读取，公开文档不泄露个人路径、机器配置或原始会话。
