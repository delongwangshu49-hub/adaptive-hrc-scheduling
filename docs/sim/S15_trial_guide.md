# S15 本地合成闭环复核入口

本页对应正在实施的S15，不能作为成果验收或发布回执。已通过用例见[有限成对结果](../validation/S15_verified_cases_r1.md)，当前缺口和历史失败见[S15步骤卡](../steps/S15.md)。工业资格UNKNOWN、HR禁用；质量与外部接收均为SYNTHETIC_TEST_ONLY。

## 配置与轻量运行

在现有环境和仓库根目录使用PowerShell 7；不要为本步另行下载模型资产或升级环境。输出目录必须是尚不存在的本地目录，避免覆盖既有证据。

```powershell
python scripts/build_production_contracts.py --check
python scripts/build_production_motion_table.py --check
python scripts/verify_production_chain.py --backend light --rework --output .local/s15-trial-normal
```

`--rework`声明一次返修能力；正常质量PASS时33项attempt=1操作不激活。正常SR-W1有效操作为442；第一次Q-POND失败时返修激活，有效操作为475。SR-W2对应456/489，不能混用操作总数。

可分别增加以下参数，且为每次运行选择新的输出目录：

| 情景 | 参数 | 应检查的事实 |
| --- | --- | --- |
| 第一次Q-POND失败后返修 | `--quality-fail Q-POND` | 拆装0.020 t、水账、8 h工艺等待、第二次质量证据；不得重置场景 |
| 返修后再次失败 | `--quality-fail Q-POND --rework-fail --expect-quality-hold` | 返修清理完成后HOLD、无READY/正常接收 |
| 取消 | `--cancel-stage UNSTARTED`、`STOCK`、`WIP`或`READY` | 未用原包沿声明反向路线外退；在制或历史READY保留，不能自动销毁 |
| 实际路径占位 | `--actual-path-obstruction` | Kit前方路线放置实际USD障碍；碰撞读回异常先于通道FAILURE通知，移除后REPAIR并从原样本续接；与无障碍对照配对 |
| 实际设备异常 | `--actual-device-failure` | Kit先实际读回异常，再通知世界；修复后resume_of续接 |
| 原料延迟及截尾 | `--delayed-lot PRODUCT-1.ST-B.01 --arrival-after-h 24 --until-h 240 --expect-window` | 到货前不提前放行，240 h保留真实未完状态 |
| 窗口内缺料 | `--delayed-lot PRODUCT-1.ST-B.01 --arrival-after-h 720 --until-h 240 --expect-window` | 关键原料未到、核心生产不放行 |
| 多产品 | `--products 2`或`--products 3` | 一次初始化、共享真实人员设备和有限槽位 |
| 分时订单及减单 | `--products 2 --release-times 0 72 --cancel-product PRODUCT-2 --cancel-stage STOCK` | 未释放订单不得投料；取消不清除其他订单状态 |
| 延迟接收 | `--receive-after-h 700` | 不提前发运；B=2占用和第三件的实际状态分别报告 |
| WV01限定补充见证 | `--products 3 --rework --scenario B2_SUPPLEMENTAL_960 --until-h 960 --receive-after-h 840` | 三件SR-W1同时释放；必须实际见证满FG1/FG2、第三件在OUT1已READY受容量阻断的正时长区间，再全部接收 |

实际路径占位、实际设备故障和通知式带载故障每次只选择一种。轻量端只提供配对的参考症状，不能解释为物理观测。

返修参数应与`--rework`一起使用。常规窗口保持既定240/720 h；PR119批准的WV01只允许上表确切960/840 h组合，不能混入故障、取消、延迟到货、其他变体或分时释放。`--expect-window`是事前声明截尾用例，不得在失败结果产生后修改报告以冒充全链通过。补充用例即使三件接收，缺少正时长背压见证仍失败。三产品、多订单和其他矩阵是否已通过，以各自源绑定报告为准，不能从参数存在推定验证完成。

## 真实Kit和同源比较

先保留完整源码快照，再分别运行同一快照的轻量端和已配置的Isaac Python环境。两端参数、配置、规则及干预设置必须相同；Kit增加`--backend isaac`，输出到独立新目录。使用现有本地监督器记录进程正常退出、未强制清理；仅看到报告`closed`、启动器退出码或窗口消失不足以证明正常结束。

验证器输出配置、源码摘要、最终状态、压缩事件和决策、独立审计及报告；Kit另有独立合成接收器的有限运动样本。心跳仅供运行诊断，不能代替最终报告。原始日志、机器路径和完整事件留在本地，不进入公开材料。

```powershell
python scripts/compare_production_chain.py --light .local/example-light --isaac .local/example-kit --audit-source-root .local/example-source --output .local/example-comparison.json
```

以上比较路径只是示意，必须指向对应实际运行。审计器使用该次捕获源码，拒绝混用当前目录中已变化的执行或审计实现。比较要求两端均满足其事前声明的退出条件；比较PASS仅覆盖该情景，不能自动升级为S15完成。

完整工时包含逐包配送、实际空返、人员走行、支承重配及加工等待；[MOVE替换表](../model/S15_move_mapping_r1.md)只核对核心MOVE包时长的替换算术。USD有限几何扫掠和读回不等于刚体接触动力学、工业生产资格、可靠渲染帧率或负责人GUI体验验收。
