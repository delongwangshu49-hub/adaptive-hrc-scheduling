# S13 工序与实体覆盖

## r3目标配置差异与覆盖层次

依据PR102；下方37项表继续逐项对应冻结生产配置，表内T1—T4、六设备和夹具入口均指 `--legacy`。本轮没有改写这些活动的设备资格或执行语义。新目标场景的对应关系如下；几何矩阵通过不等于工序生产通过。

| 原活动组 | 目标场景见证 | 保留的未实现内容 |
| --- | --- | --- |
| KIT / CUT | 新T1钢材接收、入库、PRE输入/抽象加工/输出；T3配套接收、入库、齐套及配送 | 全规格原料、真实切削、库存数量与生产质量放行 |
| MV-IN-B/T、MV-B/T | C01—C03主吊矩阵及新T2单框连续见证；西侧由S01—S04叉运交接 | 原HST资格不迁移；不是顶底双框全部工序连贯生产 |
| JOIN-IN / W-3D | C04立柱交接矩阵；两工装和固定焊接站配置，新T3人员到位 | C04只作几何覆盖，未将完整结构组装为连续动作；原JOIN合并见证保留旧入口 |
| W-B / W-T | 独立SCN-WELD-J2固定，R1基座固定 | 焊接工艺和HR资格未启用，J3另一焊站不共享WELD1域ID |
| MV-3D、F1内装/MEP相关活动 | 新T2模块J3→F1，T3小件推车连续配送及接收 | 不以箱体交接代替每项内装安装和全部工作面执行 |
| TEST / WAIT-TEST | 新T3人推检测车、部署、保持、撤离和取回 | 真实试验数值、生产锁、质量释放与WAIT工时 |
| HOLD / REPAIR相关与隔离 | 新T2 F1→Q1→F1完整载荷路径 | 不是修复算法或质量解除 |
| READY / OUT1 / RECEIVED相关 | 新T2到OUT1；新T4三件在OUT1、FG1/2、DISPATCH间实际移位与背压 | 内部暂存不等于EXTERNAL；无域RECEIVED事件、无多订单闭环 |
| 其余装配/涂层/围护/湿区/等待活动 | 保留原37项逐项空间/实体和抽象说明；目标场景不新增成功事件 | S14/S15执行契约与后续工艺/评价独立承接 |

新T1—T4详见[目标指南](S13_trial_guide.md)，任务级范围见[53行矩阵](S13_transfer_coverage.tsv)，实际见证与未验证项见[验证报告](../validation/building_scene.md)。下表的原配置证据和旧37项不能被新目标设备体系暗中替换。

## 冻结生产配置的37项历史对应

现行37项活动逐项对照冻结 `examples/building_contracts/configuration.json`。本表覆盖位置、输入输出、当前启用模式责任、可见检查与抽象，不将外观覆盖称为37项真实生产执行。禁用HR候选仍可在R1空载夹具中检查运动学；没有改变资格门。WAIT的人员不能按名称自行推断，WAIT-COAT仍有QA1；WAIT-TEST虽无人工作单元，TEST1持续持有。

| 活动 | 位置/工作面 | 输入 → 输出 | 设备/工装；人员 | 检查入口 | 抽象及后续责任 |
| --- | --- | --- | --- | --- | --- |
| KIT | PRE / PRE | 原料组件批次 → 齐套检查状态 | —；P1 | initial / T1 | 可见批次、缺件/齐套交接位置；库存与齐套判定未接入；S14/S15承接 |
| CUT | PRE / PRE | 长料 → 切割输出组件批次 | CUT1；P1 | initial / T1 | CUT输入/输出连续位移；形态抽象，无切削物理；S14/S15承接 |
| MV-IN-B | PRE / MOVE | PRE → J2；BOTTOM | HST1；Lrig,Lsig,P1 | 10路线实测 / T1 | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| W-B | J2 / HOT | 底框件 → 底框焊接状态 | FIX-J2,WELD1；W1 | manual_weld / robot_demo | 人工设备静态；R1局部空载FK，HR禁用，无焊缝生成；S14/S15承接 |
| MV-B | J2 / MOVE | J2 → BUF；BOTTOM | HST1；Lrig,Lsig,P1 | 10路线实测 / joining | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| MV-IN-T | PRE / MOVE | PRE → J2；TOP | HST1；Lrig,Lsig,P1 | 10路线实测 / T1 | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| W-T | J2 / HOT | 顶框件 → 顶框焊接状态 | FIX-J2,WELD1；W1 | dual_frame / robot_demo | 顶底槽分立，同产品双框，不扩大FIX-J2占用；S14/S15承接 |
| MV-T | J2 / MOVE | J2 → BUF；TOP | HST1；Lrig,Lsig,P1 | 10路线实测 / joining | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| JOIN-IN | BUF / MOVE | BUF底/顶及PRE立柱集合 → J3（三次落位） | CR1；Lop,Lrig,Lsig | 10路线实测 / joining | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| W-3D | J3 / HOT | 底/顶/柱 → 三维钢结构 | FIX-J3,WELD1；W1,W2 | joining / structure | 合并为分立检查状态；不声称装配动作连续；S14/S15承接 |
| Q-STR | J3 / ALL | 钢结构 → 结构质量记录 | —；QA1,W2 | structure | 外观与操作面静态，质量UNKNOWN；S14/S15承接 |
| COAT | J3 / ALL | 钢结构/涂料 → 涂层状态 | —；C1 | structure | 仅表面外观，喷涂与覆盖率未模拟；S14/S15承接 |
| WAIT-COAT | J3 / ALL | 涂层 → 等待结束状态 | —；QA1 | structure | 保持位置，等待期QA1责任按配置，不生质量结论；S14/S15承接 |
| MOVE-F | J3 / MOVE | J3 → F1；PRODUCT-1 | CR1；Lop,Lrig,Lsig | 10路线实测 / T2/T4 | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| FLOOR | F1 / ALL | 结构/板材 → 楼板基底 | —；AF1,AF2 | mep_wait | 楼板、板缝静态分层，不模拟逐板安装；S14/S15承接 |
| MEP-E | F1 / D-E | 模块/电气料 → 电气接口 | —；E1 | mep_wait / sr_w2 | 桥架、配电及插座；SR-W2额外插座静态；S14/S15承接 |
| MEP-P | F1 / W-P | 模块/给排水料 → 管道接口 | —；PL1 | mep_wait / sr_w2 | 给排水支路及SR-W2额外支管静态；S14/S15承接 |
| Q-MEP | F1 / ALL | MEP → 检测状态 | TEST1；E1,PL1,QA1 | mep_wait | TEST1工具组、质量UNKNOWN，无测量物理；S14/S15承接 |
| LINING | F1 / DRY | 模块/围护料 → 内衬围护 | —；AF1,AF2 | mep_wait | 墙板/保温/外覆分层；隐藏不释放碰撞；S14/S15承接 |
| Q-LIN | F1 / DRY | 围护 → 检查状态 | —；QA1 | mep_wait | 操作面静态，质量UNKNOWN；S14/S15承接 |
| WPROOF | F1 / WET | 湿区/防水料 → 防水层 | —；T1 | mep_wait | 湿区盘/膜边静态，不模拟涂布；S14/S15承接 |
| WAIT-W | F1 / WET | 防水层 → 等待结束状态 | —；无工作单元人员 | mep_wait | 静态等待，不自动记REST；S14/S15承接 |
| TEST-SET | F1 / WET | 湿区/测试料 → 试验设置 | TEST1；T1 | mep_wait / T3 | TEST1运入设置；不模拟真实蓄水检测；S14/S15承接 |
| WAIT-TEST | F1 / WET | 试验设置 → 保持状态 | TEST1（跨阶段持有）；无工作单元人员 | mep_wait / T3 | TEST1继续持有，人员释放；质量UNKNOWN；S14/S15承接 |
| Q-POND | F1 / WET | 保持状态 → 试验检查 | TEST1；QA1,T1 | mep_wait / T3 | 共享工具组检查/取回，无PASS回执；S14/S15承接 |
| TILE | F1 / WET | 湿区/饰面料 → 瓷砖饰面 | —；T1,T2 | mep_wait | 瓷砖缝和湿区静态，无逐块铺贴；S14/S15承接 |
| WAIT-TILE | F1 / WET | 饰面 → 等待结束状态 | —；无工作单元人员 | mep_wait | 静态等待，无固化模型；S14/S15承接 |
| EXT | F1 / EXT | 模块/外覆料 → 外围护 | —；AF1,AF2 | mep_wait | 外覆层及开口静态，无施工动作；S14/S15承接 |
| Q-EXT | F1 / EXT | 外覆 → 检查状态 | TEST1；AF1,QA1 | mep_wait | TEST1静态映射，质量UNKNOWN；S14/S15承接 |
| PAINT | F1 / DRY | 内装/涂料 → 饰面涂装 | —；C1 | mep_wait | 材料颜色静态，无喷涂动力学；S14/S15承接 |
| WAIT-PAINT | F1 / DRY | 涂装 → 等待结束状态 | —；无工作单元人员 | mep_wait | 静态等待，无挥发/健康推论；S14/S15承接 |
| FIT | F1 / ALL | 模块/配套件 → 内装安装状态 | —；AF1,E1,PL1 | mep_wait / sr_w2 / T3 | 门、柜、洁具及MEP配套配送代理；不模拟安装全过程；S14/S15承接 |
| Q-FIN | F1 / ALL | 完整内装 → 最终检查状态 | TEST1；E1,PL1,QA1 | sr_w2 | 工具/工作面静态，仍质量UNKNOWN；S14/S15承接 |
| PACK | F1 / ALL | 模块/保护料 → 保护包装外观 | —；AF1,P1 | outbound | 角部保护、内部保护、顶盖静态；S14/S15承接 |
| Q-PACK | F1 / ALL | 包装 → 出厂准备检查 | —；QA1 | outbound | 仍在F1工序，OUT1外观不代替检查；S14/S15承接 |
| MOVE-OUT | F1 / MOVE | F1 → OUT1；PRODUCT-1 | CR1；Lop,Lrig,Lsig | 10路线实测 / T2/T4 | 足尺寸固定路线及实际读回；工艺时钟/派工反馈S14接入；S14/S15承接 |
| READY | OUT1 / - | 全部放行前置 → 出厂就绪门 | —；无工作单元人员 | outbound | 仅OUT1外观；本步不生成READY生产事实；S14/S15承接 |

## 上游预留与批次谱系

T1内沿用同一个PRODUCT-1.BOTTOM域组件根，并附场景批次标识；试运行位置由独立排演状态及USD实际读回给出，不将其在SCN料区的位置写入冻结生产状态。原初始夹具是独立的生产核心空间参照。切换T1—T4或夹具都会显式重置，不能将其剪接成收料至READY历史。

| 对象 | 当前用途/容量参数 | 映射与后续责任 |
| --- | --- | --- |
| SCN-RECEIVE | 收料、待检批次外观，2展示槽 | 场景预留；S14批次/放行/数量守恒 |
| SCN-STEEL | 长料与取料面，3展示槽 | 场景预留；T1组件同根追踪，S14库存与加工消耗 |
| SCN-PANELS / SCN-MEP | 分类配套件，各2展示槽 | 场景预留；S14配送与预留，S15全链 |
| SCN-RETURN | 退料与异常料隔离，1展示槽 | 场景预留；不借用Q1产品容量 |
| SCN-KIT / SCN-INPUT / SCN-CUT-OUTPUT | 齐套、CUT前后交接 | 场景预留；不增加PRE bay或HST1令牌 |
| SCN-J3-SUPPLY / SCN-F1-SUPPLY | 工位短时料位及接收面 | 场景预留；S14开工物料可用条件 |
| SCN-MEP-BATCH | 连续配送的配套件/载体代理 | 装备选型未知，不冒用HST1/CR1资格 |
| SCN-PRODUCT-2 | T4第二产品足尺寸空间见证 | 场景预留，未加入生产Configuration；S15两产品闭环 |
| SCN-X-MODULE / SCN-X-SUPPLY | 排演内部局部通行互斥 | 场景检查锁，不输出生产资源/事件 |
| WELD1 / CR1 / TEST1 | 唯一域设备实体，阶段属性所有者 | 同域映射；T3转场与保持、T2/T4吊运，S14正式状态机 |

显示槽数只是位置/外观参数，没有提升域库位或bay容量。PRE只表达已存在的CUT；除锈、钻孔、倒角和板材加工仍待工艺证据判定，未增设备。Q1保持异常产品隔离用途，正常结构检验在J3、最终检验/包装在F1。

全部15人的具名起点和独立可达路径见版本化布局与真实检查报告；人员行走、准备和等待尚未接入S14/S18/S22的计时及人因。场景动作不改变D01—D06，质量UNKNOWN，HR禁用。上游材料、人员、运输执行由[总纲补丁](../PROJECT_CHARTER.md#process-layout-patch)所列后续授权步骤承接。
