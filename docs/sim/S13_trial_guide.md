# S13 r3 目标工厂亲自试运行

依据 PR102 的 r5 授权实现，版本 `S13-TARGET-R5-1`。默认打开目标场景并暂停，标题和状态标明 `SCENE_ONLY / TARGET_LAYOUT`。15 名具名人员、两个独立固定焊接站、站驾叉运、配送车、可推检测车及 CR1 对应明确动作。质量 UNKNOWN、HR 禁用；四组之间显式 RESET，各组内部连续，不能拼接成完整生产历史。

## 启动与检查

在已有 Isaac 环境的 PowerShell 7 中，从仓库根目录运行。`ISAAC_SIM_ROOT` 使用既有本地配置；每次输出目录必须是新的。

```powershell
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/view_building_scene.py --output .local/s13-r3-review-session
```

启动前关闭本项目以前启动的 Kit 窗口。当前入口不安装环境或下载资产。旧版可另用同一命令加 `--legacy`，保留原六设备和旧 T1—T4；不要同时打开两套视图并把它们当成一套生产配置。

| 操作 | 当前行为 |
| --- | --- |
| T1—T4 / RESET | 显式重新建立所选测试初始状态，暂停；组间 RESET 不属于连续生产 |
| Run / Pause、Step 1/60s | 从当前状态继续、暂停或单步；被阻挡时保持载荷、位置和身份 |
| 1x / 4x / 10x | 只加速检查时钟，不代表工艺工时或实机速度 |
| Obstacle / Person / Occupied、Clear fault | 对当前运动插入实际碰撞体，解除后从原位置继续；请在搬运阶段注入 |
| Duplicate equipment request | 正在持有设备时拒绝重复请求；不是生产调度入口 |
| T4 External receiver READY | 合成接收方准备信号；信号本身不清空成品槽，实际搬出落位后才释放 |
| routes / roles / envelopes | 检查图层；不改变碰撞、载荷或容量 |
| Camera | Overview、Top、Supply、Equipment、Crossing、Finished、Gantry、F1、Fork、Test |
| Save issue | 暂停并保存备注、状态 JSON、实际 USD 和未编辑 PNG；完成后显示编号 |

面板显示当前阶段及 OUT1/FG1/FG2/DISPATCH 占位；人员下拉框可逐一查看15名人员的任务、目标世界坐标、状态和等待原因。期望看到人员领任务、行走、到位操作、让行等待、撤离；叉运司机随车、推车人随车。程序化自检走同一回调队列，不能代替负责人亲自操作和验收。

## 四组审阅顺序

| 测试 | 重点与实际对象 |
| --- | --- |
| T1 接收至预处理配送 | QA1 到收料位完成场景检查；唯一 `SCN-STEEL-001` 从 RECEIVE 入 STEEL、PRE-IN、CUT 抽象、PRE-OUT，再由 CR1 交 J2。P1 到站驾平台、驾驶、交接及空返；货叉空返前收回。60 kg 承载盒只是母批 1/4 的单件代表，不代表所有长料 |
| T2 构件/模块吊运 | 唯一模块 J3→F1→Q1→F1→OUT1；随后一个框架 PRE-OUT→J2→BUF→J3。Lop 遥控、Lrig 司索后撤离、Lsig 指挥、接收人到位；空钩接近与返回保留 |
| T3 人员、固定焊接站与推车 | W1/W2 同时请求交叉通道，W2 原位让行后走合法路线；两固定焊接站独立。唯一 MEP 箱经接收/入库/齐套/配送到 F1-KIT，E1 推车、交接托盘收回、空返。QA1 推 TEST1 到使用位，保持、撤离、再到位取回 |
| T4 B+1 成品背压 | 初始 FG1/FG2 各一件、第三件在 OUT1。运行后等待接收准备信号；点 READY 后，FG1 的产品实际搬到 DISPATCH，FG1 才释放，第三件再入 FG1。三件始终存在，内部交接不写 EXTERNAL/RECEIVED |

先用 Top 看 60×44 m 边界和通道，再看 Fork/Equipment 的设备形式，最后用 Finished 对比三件产品搬出前后。正常排演使用最短合法通道图路线；交叉采用确定性整段预留，不能外推任意人群动态避碰。没有自动紧急制动、接触力/强度验证或真实转向动力学。

## 自动复核与证据

```powershell
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/verify_building_target.py --mode verify --output .local/s13-r3-target-verify
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/view_building_scene.py --self-test --output .local/s13-r3-ui-check
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/verify_building_target.py --mode load --level L2 --output .local/s13-r3-load-L2
uv run --locked python scripts/build_target_coverage.py --check
```

分级负载用 `--level L0/L1/L2` 各单独运行，30 秒暖机、至少120秒测量、10次完整重建；不要与其他 Kit 或完整 CPU 测试并跑。L0为目标静态场景，L1为T1，L2为三产品与交叉让行组合。应用更新耗时不能称为 FPS，真实帧时间戳仍未取得。

阅读[设备裁定](S13_equipment_decisions.md)、[53行任务矩阵](S13_transfer_coverage.tsv)、[验证报告及原图](../validation/building_scene.md)、[目标机器摘要](../../examples/building_scene/target_summary.json)。矩阵逐项验证几何；真实连续排演是其中代表链，不表示53项都形成生产工序。

下方保留 r2 操作历史；其中 T1—T4、WELD1/HST1 和夹具按钮仅适用于 `--legacy`。

---

# S13 r2 亲自试运行

这是场景动作排演，生产反馈尚未接入。四个测试各有独立初始状态，切换测试或夹具会重置；不能将画面串联解释为收料至READY生产。质量始终UNKNOWN、HR禁用。首次打开处于暂停，避免来不及观察。

## 启动

使用现有Isaac环境，在仓库根目录的PowerShell 7会话运行。`ISAAC_SIM_ROOT`由本地环境配置；入口不包含机器绝对路径，不下载资产或安装依赖。

```powershell
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/view_building_scene.py --legacy --output .local/s13-review-session
```

每次换一个输出目录，拒绝覆盖既有证据。运行前关闭此前由本项目启动的检查窗口，避免多个Kit进程竞争。若尚未配置Isaac环境，先按[环境说明](../setup.md)核对既有安装，不把启动失败当作场景通过。

## 操作

| 控件 | 实际含义 |
| --- | --- |
| T1—T4 | 加载该测试的完整初始状态，清空检查锁，暂停并提示RESET |
| Run / Pause | 继续/暂停当前排演；不影响生产时钟，因为尚无生产执行 |
| Step 1/60s | 暂停并前进一步；倍速仍作用于检查时钟 |
| 1x / 4x / 10x | 调整检查播放倍率，不是实测设备速度或工艺工时 |
| RESET | 同一测试原位恢复初始位置/设备所有者；分立夹具则重新加载，保持暂停 |
| Obstacle / Person / Occupied | 在当前运动路线插入实际碰撞体；非运动阶段会提示错误 |
| Clear fault | 移除注入问题；从保留位置及所有者状态恢复，不能跳至终点 |
| Duplicate equipment request | 在设备被持有时发出第二检查请求，显示RESOURCE_BUSY；未持有阶段提示先运行 |
| routes / roles / envelopes | 显示图层；切换不移除碰撞或改变容量、所有者 |
| Camera按钮 | 总览、俯视、供料、PRE、工位、人员交叉、WELD转场、机器人和吊机镜位；也可用视口鼠标旋转/缩放 |
| Load selected fixture | 原10类分立夹具，用于[37项覆盖巡检](S13_process_coverage.md)，显式RESET，非连续过程 |
| Save issue | 暂停并保存真实PNG、USD和状态JSON，包含填写的备注、相机、检查时钟、所有者与实际世界坐标 |

问题文件留在所选本地输出目录；包含运行状态，未纳入公开发布清单。保存完成会显示文件编号；PNG必须实际写入完成才报告成功。关闭Isaac窗口结束会话。

## 四组观察重点

| 测试 | 连续内容 | 可检查的问题 |
| --- | --- | --- |
| T1 | 同一底框组件批次从钢材料位经PRE输入、CUT抽象阶段、输出交接；P1/Lrig/Lsig到位；HST空载接近、搬至J2及空载返回 | 批次不能在失败后出现在终点；HST保持3t限制；CUT不模拟切削物理 |
| T2 | Lop/Lrig/Lsig接近、挂接阶段、人员退出、CR1搬至F1、落位摘钩、空载返回 | 人员留在吊运包络必须拒绝；吊钩、载荷分别读回，轨道支腿也检查 |
| T3 | WELD1唯一实体撤离J2、连续转至J3、工具准备；配套件代理送F1；TEST1运入、保持、取回 | WELD1不可双重持有；等待期TEST1不因无人工作单元而释放；配送载体为SCN预留 |
| T4 | PRODUCT-1在J3、SCN-PRODUCT-2在Q1，依次争用CR1/路线；第一产品落位后吊机空载转至第二产品 | 重复所有者、目标占位、超容量及跨产品组件误用分别有负例；第二产品未加入冻结生产配置 |

人员路线采用固定折线，吊机作业时通过控制顺序停止交叉通行。这是所测代理包络的几何检查，不是工业安全认证或自主导航。R1只有局部空载运动，地面最大伸展界及不可达提示不构成全框焊接资格。

## 自动复核入口

```powershell
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/build_building_scene.py --mode trials --output .local/s13-trials-check
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/view_building_scene.py --self-test --output .local/s13-ui-check
```

`--self-test`创建实际面板，调用按钮共用的回调队列并实际保存问题文件；这是程序化GUI回调检查，不能冒称人工鼠标点击或负责人体验验收。测试结果和未覆盖项以[验证报告](../validation/building_scene.md)为准。脚本结果PASSED、closed=true、进程退出正常须分别核对；关闭前结果不能单独证明正常退出。
