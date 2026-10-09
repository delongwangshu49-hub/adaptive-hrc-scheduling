# S19A：整组静态外观前后对照

2026-10-10；PR165 / LOG219—LOG220。负责人将流程改为集中完成全部拟调整内容，再逐个提供图片对照，不再逐个暂停审批；人物保留现有建模，重点加强岗位和个体涂装区分。原几何尺寸硬约束继续有效。本页集中交付15个人物、11项设备和全场，共44张真实Kit图片。

当前 **STATIC_BATCH_VERIFIED_WITH_LIMITS / BATCH_VISUAL_REVIEW_PENDING / NOT_PUBLISHED**。所有外观已进入本地候选场景构建；未据此记录人工验收或发布。原W1图审与旧图片保持封存。这里的“整组”指本轮静态外观；人物朝向/动作仍沿用原实现，不能将本图册当作S19A整步完成。

打开[完整浏览图册](../sim/images/s19a/batch-r1/index.html)，可按ID跳转、展开每个个体，并点击图片查看原图。以下也完整逐项展示。**所有个体对照均为左侧修改后、右侧S19 r2原模型**，W1也采用同一发布基线，而非上一轮已接受外观。整体人像排布仅用于色彩审阅，未改变生产场景的位置。

![15人涂装总览](../sim/images/s19a/batch-r1/people-all-after.png)

## 核验及边界

独立USD对照从已发布S19 r2场景实现构建原模型，并对前后执行同一生产初始化。原1,148几何对象的属性、变换、可见性、schema和世界AABB完全相同；728原碰撞体及实际障碍集合保持。15人的身体AABB、根位置、手位保持，新增165个无碰撞视觉细节均未扩大各自原身体AABB。人物外形、四肢和遥控器保持；身体可视宽0.64m与原占用宽0.60m的既有差异如实保留。

设备只换材质；地面颜色和原两盏灯的强度调整，相机、布局、路径、工时、容量和人因参数保持。灯光原650/2500、现800/1900。个体图采用一致的审阅光照；全场图展示各自实际光照。保留原工业资格/状态标识，不将配色当作工业防护或资格认定。

57项现有场景回归通过（2.981s），Ruff通过。最终44图逐张记录PNG摘要、相机矩阵误差小于1e-4；真实Kit完整关闭及外部退出码0。首轮虽然也退出0，但日志含关闭异常，保留为非正常关闭证据；释放场景/视口引用后第二轮不再复现。总览编号裁切、设备长标题重叠在审图后修正，最终图来自第三轮。详细记录见[机器证据](S19A_static_batch_r1.json)。

## 人员逐项对照

### P1 · 备料

赭黄衣 / 明黄背心，另有胸牌编号。

![P1正面：左后右前](../sim/images/s19a/batch-r1/P1-front.png)

![P1斜侧：左后右前](../sim/images/s19a/batch-r1/P1-side.png)

### W1 · 焊接

深蓝衣 / 橙背心 / 黄帽，另有胸牌编号。

![W1正面：左后右前](../sim/images/s19a/batch-r1/W1-front.png)

![W1斜侧：左后右前](../sim/images/s19a/batch-r1/W1-side.png)

### W2 · 焊接

亮蓝衣 / 橙背心 / 白帽，另有胸牌编号。

![W2正面：左后右前](../sim/images/s19a/batch-r1/W2-front.png)

![W2斜侧：左后右前](../sim/images/s19a/batch-r1/W2-side.png)

### OP1 · 机器人操作

紫衣 / 浅紫背心，另有胸牌编号。

![OP1正面：左后右前](../sim/images/s19a/batch-r1/OP1-front.png)

![OP1斜侧：左后右前](../sim/images/s19a/batch-r1/OP1-side.png)

### AF1 · 装配

深绿衣 / 黄绿背心，另有胸牌编号。

![AF1正面：左后右前](../sim/images/s19a/batch-r1/AF1-front.png)

![AF1斜侧：左后右前](../sim/images/s19a/batch-r1/AF1-side.png)

### AF2 · 装配

青绿衣 / 薄荷背心，另有胸牌编号。

![AF2正面：左后右前](../sim/images/s19a/batch-r1/AF2-front.png)

![AF2斜侧：左后右前](../sim/images/s19a/batch-r1/AF2-side.png)

### E1 · 电气

深蓝衣 / 青色背心和帽，另有胸牌编号。

![E1正面：左后右前](../sim/images/s19a/batch-r1/E1-front.png)

![E1斜侧：左后右前](../sim/images/s19a/batch-r1/E1-side.png)

### PL1 · 管路

亮蓝衣 / 浅蓝背心和蓝帽，另有胸牌编号。

![PL1正面：左后右前](../sim/images/s19a/batch-r1/PL1-front.png)

![PL1斜侧：左后右前](../sim/images/s19a/batch-r1/PL1-side.png)

### T1 · 湿作业

砖红衣 / 杏色背心，另有胸牌编号。

![T1正面：左后右前](../sim/images/s19a/batch-r1/T1-front.png)

![T1斜侧：左后右前](../sim/images/s19a/batch-r1/T1-side.png)

### T2 · 湿作业

赭黄衣 / 米色背心和白帽，另有胸牌编号。

![T2正面：左后右前](../sim/images/s19a/batch-r1/T2-front.png)

![T2斜侧：左后右前](../sim/images/s19a/batch-r1/T2-side.png)

### C1 · 涂装

米白衣 / 薄荷背心和帽，另有胸牌编号。

![C1正面：左后右前](../sim/images/s19a/batch-r1/C1-front.png)

![C1斜侧：左后右前](../sim/images/s19a/batch-r1/C1-side.png)

### QA1 · 质检

白衣 / 蓝背心，另有胸牌编号。

![QA1正面：左后右前](../sim/images/s19a/batch-r1/QA1-front.png)

![QA1斜侧：左后右前](../sim/images/s19a/batch-r1/QA1-side.png)

### Lop · 吊机操作

靛蓝衣 / 明黄背心，另有胸牌编号。

![Lop正面：左后右前](../sim/images/s19a/batch-r1/Lop-front.png)

![Lop斜侧：左后右前](../sim/images/s19a/batch-r1/Lop-side.png)

### Lrig · 司索

红衣红帽 / 白背心，另有胸牌编号。

![Lrig正面：左后右前](../sim/images/s19a/batch-r1/Lrig-front.png)

![Lrig斜侧：左后右前](../sim/images/s19a/batch-r1/Lrig-side.png)

### Lsig · 指挥

洋红衣 / 黄绿背心和帽，另有胸牌编号。

![Lsig正面：左后右前](../sim/images/s19a/batch-r1/Lsig-front.png)

![Lsig斜侧：左后右前](../sim/images/s19a/batch-r1/Lsig-side.png)

## 设备逐项对照

原内部几何和位姿保持；为并排展示，仅在独立审阅副本中平移整体。图片中的悬空件及姿态也来自原模型，并非新增结构。

### CUT1

切割设备：蓝色机壳、金属色送料与滚轮、深色控制面。

![CUT1：左后右前](../sim/images/s19a/batch-r1/CUT1-comparison.png)

### R1

机器人：橙色机械臂、钢灰底座与控制柜；原可达边界保持。

![R1：左后右前](../sim/images/s19a/batch-r1/R1-comparison.png)

### SCN-WELD-J2

J2焊接设备：橙色电源、青色气瓶、深色线缆。

![SCN-WELD-J2：左后右前](../sim/images/s19a/batch-r1/SCN-WELD-J2-comparison.png)

### SCN-WELD-J3

J3焊接设备：蓝色电源，与J2明显区分。

![SCN-WELD-J3：左后右前](../sim/images/s19a/batch-r1/SCN-WELD-J3-comparison.png)

### SCN-FORK-01

搬运车：黄色主体、钢灰门架和货叉、深色车轮与控制件。

![SCN-FORK-01：左后右前](../sim/images/s19a/batch-r1/SCN-FORK-01-comparison.png)

### SCN-CART-01

手推车：青绿底盘、金属色托盘和把手、深色车轮。

![SCN-CART-01：左后右前](../sim/images/s19a/batch-r1/SCN-CART-01-comparison.png)

### TEST1

测试小车：白色底盘、蓝色仪表、金属色托盘。

![TEST1：左后右前](../sim/images/s19a/batch-r1/TEST1-comparison.png)

### FIX-J2

J2工装：青绿横梁、黄色夹持端。

![FIX-J2：左后右前](../sim/images/s19a/batch-r1/FIX-J2-comparison.png)

### FIX-J3

J3工装：蓝色横梁、黄色夹持端。

![FIX-J3：左后右前](../sim/images/s19a/batch-r1/FIX-J3-comparison.png)

### CR1

吊机：黄色主体、深色车轮与绳索，原支承和跨度保持。

![CR1：左后右前](../sim/images/s19a/batch-r1/CR1-comparison.png)

### CR1-HOOK

吊具：黄色承载梁与吊钩块、深色索具；此项颜色变化较小，主要统一材质。

![CR1-HOOK：左后右前](../sim/images/s19a/batch-r1/CR1-HOOK-comparison.png)

## 全场同镜头对照

修改前：

![原场景](../sim/images/s19a/batch-r1/factory-before.png)

修改后：

![修改后场景](../sim/images/s19a/batch-r1/factory-after.png)

## 静态帧耗时与未完成出口

固定1280×720、同一Overview相机，ABBA顺序，每组预热60帧后采样180帧。以下为app.update墙钟耗时，既不是GPU专用计时，也不是完整生产调度。事前未有负责人认可的性能门限，因此只报告实测值，不事后判定性能PASS。

| 次序 | 场景 | 中位数ms | P95 ms | 最大ms |
| --- | --- | ---: | ---: | ---: |
| 1 | before | 3.386 | 4.255 | 64.648 |
| 2 | after | 3.521 | 4.464 | 8.459 |
| 3 | after | 3.309 | 4.237 | 66.299 |
| 4 | before | 3.198 | 4.233 | 64.805 |

A2动态朝向/转弯/折返等保持未完成，A3仅完成本轮截图、局部回归和静态帧耗时采样，视频和整步实际视觉验收未完成。未跑新的完整生产链、849全量或隔离wheel，不作前置完整验证重新通过的结论。工业G2仍OPEN/NOT_ESTABLISHED，S19B及S20—S28未启动。沿用main/目录，无分支、worktree、子代理或Git写入。拟远端操作为空，无新标签；确切文件摘要在本地候选清单保存。
