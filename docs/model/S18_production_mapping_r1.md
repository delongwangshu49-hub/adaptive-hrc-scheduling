# S18现行生产映射与限定冻结修订表

2026-10-07；S18-MAP-20261007-r1；PR140授权内形成具体材料，PR141委托AI依据前置步骤自主判断。**DESIGN_SELECTED / EXECUTION_BLOCKED_MISSING_QUALIFICATION / G2_OPEN**。采用本表作为门关闭后的迁移设计；现阶段决定不执行生产HR迁移，不改变现行冻结值。现行生产文件、Schema、配方和场景保持原值，程序边界继续拒绝联合HR执行。此为受委托的AI工程判断，不冒称负责人逐项验收或工业资格批准。

## PR141自主判断及前置证据

负责人表示不清楚资料入口，授权分析前置步骤并自行判断。核对PR067允许的是明确标注的合成**时间/负荷**；PR069 D02仍限定HR默认禁用、G2 OPEN；PR108 ML修订保留D02，PR115 RP05仍H-only、RP07明确正常研究生产HOLD。S17 r2仅固定合法模式，并未取得共同输出资格。由这些前置不能推导双模式工艺已合格，也不能推导合成时间许可豁免G2。

本次重新读取[模块自动化案例B02](https://www.roboticplus.com/en/news/details/cate_id/61/id/495.html)、[模块焊接案例B11](https://www.roboticplus.com/en/news/details/cate_id/61/id/477.html)及[设备技术报告B03](https://www.kobelco.co.jp/english/r-d/technology-review/pdf/41_023-029.pdf)。两供应商页面支持模块框架自动化工程存在；设备报告介绍钢结构机器人/定位器/程序等系统，主要焊接条件针对钢柱。**工程判断**：这些已读材料没有提供本研究SR-W1/W2底/顶框的Q01—Q06适用记录，不能据此把未知字段设PASS；不声称证明全球不存在这样的资料。

自主决定：①保持G2 OPEN、实际HR禁用及A BLOCKED；②不删A、不改产品或缩成纯人工研究、不修改时长/负荷；③采用M01/M02作为具体门后设计，继续并交付不依赖真实资格的无更新控制、生产拒绝/固定接口及验证；④当前不进行新版实际HR迁移及Kit HR运行，因为它们需要缺失的接头、程序/夹具、隔离及停点定义，不能由算法自行推定。当前不再索取相同资料问题或重复启动批准；以后出现可查适用资料时按逐项门复核。完整S18出口保留明确BLOCKED。

## 现值核对与适用对象

现行`S15-PROD-1.0`生成器为PRODUCT-1的W-B/W-T各绑定H的U1—U6，一单元一Operation，共12条；HR-seq仍DISABLED且无生产绑定。H各单元base_h=0.5，前五单元kappa=0.5、卸载kappa=0；总基础3h。HR原定义为OP1装夹0.5h/kappa0.5、无人隔离加工1h/kappa0、OP1卸载0.5h/kappa0；设备R1与FIX-J2，基础2h。数值来自现行冻结定义，本稿不调整，也不证明本产品工艺或节拍。

当前W-B/W-T均在J2；人工设备为独立WELD-J2与FIX-J2，R1为J2固定设备。J3的WELD-J3不复制或移动。底/顶框身份、同产品双框可驻留、FIX-J2独占、各搬运至BUF及完整后续链保持。机器导出见[现行绑定及续接摘要](../../examples/joint_modes/continuation.json)。

建议新契约版本标识`S18-PROD-2.0`，只在如下条款获具体决定且迁移全部消费者后使用；旧版保持独立拒绝/回归，不把版本字符串变化当实现完成。

## M01：模式、执行承诺和共同输出

| ID / 冻结项 | 具体旧值 → 拟新值 | 消费者与影响 | 前置/验证出口 |
| --- | --- | --- | --- |
| M01-01 / D02 | HR disabled且G2 OPEN → **默认值仍disabled/OPEN**；新版本加入按产品版本/接头集合/模式/输出版本/资格版本的准入索引，只有适用Q01—Q05及Q06停点审阅关闭才可启用 | 规格、Evidence/模式契约、生成器、规划器、独立检查；绝不把通用INDUSTRIAL/PASS或合成PASS当适用范围 | J01：缺八项任一门、错产品/接头/版本/失效资格均拒绝；材料提供与审阅另行记录 |
| M01-02 / D03 | `Operation.production_mode`及`DispatchCommand.mode_id`只含H/H-team/MOVE/WAIT/GATE → 新版允许HR-seq，但命令另绑定`mode_definition_id`、`mode_revision`、`output_revision`、`qualification_revision`；标量kind不足以唯一定位程序 | domain/codec/Schema、命令与事件、轻量/Isaac、检查器/决策账；旧版仍拒HR-seq | J02：陈旧模式、仅改kind、错输出/资格版本拒绝 |
| M01-03 / D03 | `validate_mapping`要求每活动恰一enabled且非HR，绑定键(activity,mode,unit)现只有H → 按已审阅合法模式分别覆盖完整单位集合；H原6条保留；W-B/W-T各新增HR U1/U2/U3专属Operation ID，不复用H ID | mapping/生成器及precedence消费者；后继依赖改为“同活动实际选择模式的全部单元完成”，不能同时要求两模式或少做任一阶段 | J03：人工和机器人两支各完整集合、缺段/混段/双完成/跳卸载拒绝；不声称当前已生成 |
| M01-04 / D03 | `State.completed`只有operation ID、无活动模式尝试 → 新增`ModeAttempt(activity_id,attempt,mode_definition_id,mode_revision,crew,completed_units,prepared_revision,state)`；首装夹原子承诺，之后模式不可切换，停点换班须既有交接语义和Q06许可 | 准入/事件/观察/规划/S10因果重建；模式选择不能删除准备和材料历史 | J04：执行中/已准备换模式、换人未交接、错attempt、重新setup或重复耗料拒绝 |
| M01-05 / D03 | `hold_device/release_device`为单ID；持续所有者`HELD:product`不能区分同产品两框/尝试 → 新版多资源持有`(activity_id,attempt,resource_ids,mode_revision)`；装夹原子持有R1/FIX-J2，机器人结束不释放，实际卸载完成才释放；人工方案对应夹具持有也须逐项核对 | backend/checker/observation/Isaac；不得沿用单个product所有者提前释放另一框的锁 | J05：同产品两框/双产品互斥、机器人完成但卸载不到岗、异常/取消持有、伪释放拒绝 |
| M01-06 / D03/D04 | Operation phase把非SETUP单位映成WORK → 新增独立模式阶段元数据SETUP/ROBOT/UNLOAD；人因日历分类仍按实际SETUP/WORK/SUPERVISE/WAIT/REST等既有率；ROBOT不是全员REST事件 | 执行/人因/S10/Isaac读回；无人阶段只有Q04证据允许时不占监督人员，既有其他职责照常积分 | J06：需监督变体必须具名SUPERVISE；无休息事件不得计REST；cap/恢复/工作率不变 |
| M01-07 / D02/D03 | 尚无HR共同输出生产记录 → 模式尾段只产相同组件版本/焊缝集合完成事实，检验/质量状态沿既有明确门；程序/夹具改变使准备与适用资格失效，不自动给Q-STR PASS | 工艺/质量传播、生产账、检查器/后继；保持完整结构/MEP/内装/READY定义 | J07：质量UNKNOWN/FAIL、失效版本、机器人加工完但未卸载/未检验不得下游或READY |

## M02：具名班组、到位和物流

| ID / 冻结项 | 具体旧值 → 拟新值 | 消费者与影响 | 验证出口 |
| --- | --- | --- | --- |
| M02-01 / D03/D04 | 生产`choose`默认RoleBinding(role.id,role.id)、role_locations也绑定固定person ID → 新版阶段角色ID独立于person ID；枚举具名合格人员并为被选人映射真实站位；人选/职责纳入ModeAttempt，后续保持或合法交班 | 规划/派工/位置检查/S10/Isaac人员对象；不能仅在命令换人而位置仍指原人 | J08：错角色、同人双岗、不到位、错误控制点、陈旧班组、交班遗漏负荷拒绝 |
| M02-02 / D03/D04 | WALK/EMPTY_RETURN/REST/service为现行真实到位与恢复通路 → 通路保持，HR装夹/卸载候选先生成选中人员的实际WALK和必要准备，不瞬移；走行/准备计既有日历与负荷 | production_navigation/geometry/planner/backend/checker/Isaac；固定R1/WELD-J2/WELD-J3不转场 | J09：路线阻断、人员未到位、实际落位缺证、占岗REST拒绝；同预算固定/联合共用物流 |
| M02-03 / D01/D03，现值保持 | S15现行材料预留、源/目标容量、底/顶框驻留/组件运输、成品B=2及实际接收 → 数值/规则不改；联合候选复制实际完整前缀，未来未知到货/质量/修复/提货仍UNKNOWN | 所有候选/缓存/S10/因果账；D01及RP/SC/SH/WV不解冻 | J10：重复预留、删占位、伪提货、取消丢料、带载故障/容量背压保持；全链要求不被尾段PASS替代 |
| M02-04 / D03表达，D04数值保持 | 当前fixed production LNS只返回一条派工/WAIT → 新版联合修复覆盖模式/人员/顺序/合法开始时隙/显式REST，保持已执行与运输/准备承诺；每个可返回候选按完整前缀+尾段独立S10/决策账核验，缓存最终重验 | algorithms/control及两个独立审计；不得把只准入的动作作为完整未来可行解 | J11：模式/班组/顺序/休息四类可比邻域、合法停点、全窗口人因、超界/预算失败不缓存；必要未来仅预测，不写外部事实 |
| M02-05 / 方法，无新增冻结数值 | 部分`state_ranking=False` → 新增完整“无观测更新提案”通道；留存锚点信息供搜索，实际安全只在选择后拒绝，不重搜、不以实际分数择优 | 当前已交付同一时刻C04尾段及S15固定当前窗口控制；完整版联合生产滚动口径须随新版接口验证 | J12：同锚点不同当前故障/材料/质量/接收/位置/人因提案一致；实际盾可WAIT；每一分数标 nominal/actual，未完成/反向保留 |

## 迁移与两后端出口

迁移顺序：资格/停点范围审阅 → 条款具体决定 → domain/Schema/mapping及生成器 → 轻量执行+独立S10/决策账 → 规划/观测及固定/去更新共同控制 → Isaac共用命令/真实位置与阶段读回 → 成对机制/全链/必要回归 → 新确切审阅。任一消费者仍旧版即拒绝新版，不进行半迁移试运行。

消费者明确包括`domain/production.py`、`contracts/production.py`及生产Schema、`production_mapping.py`、生成器、`production_backend.py`/人因、`production_checker.py`、`planning/production.py`、`control/production_loop.py`/ledger/decisions、`backends/production_isaac_adapter.py`、`sim/isaac/scene/production_port.py`及人员/支承读回。现有441/455操作以上的完整链必须按真实新版重新建立证据，原S15证据仅保留其旧版归属，不重标为HR新版。

必须在双后端验证J01—J12中相关实际阶段/位置/容量/异常链，含正常/不变/抵消/反向，至少完整模块链和同产品双框/双产品竞争。真实Kit HR相关实现与验证**尚未运行且受门阻断**；本轮已有生产WALK轻量事实与双审计只验证既有接口边界，不作为上述迁移出口。

D05顺序、D06元数据、产品/BOM、设备数量/位置、几何/路线、B=2、RP01—08/SC01—04/SH01/WV01及其余冻结条款保持。本稿不下载资产、不升级环境、不启动后续步骤或正式A/D实验。

## 仍缺的确切资料与恢复条件

仍缺Q01同产品/组件/接头/钢材板厚/姿态范围，Q02 H/HR适用WPS和资格版本，Q03机器人程序/夹具及变更失效，Q04人员职责/资格/隔离与监督释放，Q05相同焊缝/质量标准/检验结果和输出，Q06合法停点/交班/异常与返修方法。必须有可查来源、版本及适用性核查，不能只添加“G2 PASS”标签。该事实缺项是自主判断的阻断原因，不是等待负责人重复启动决定。

门关闭后，按本表实施具体限定D02/D03/D04迁移并共同验证消费者；此前不更新冻结文件。没有选择范围替代，没有把AI设计选择写为人工验收、工业资格或发布批准。
