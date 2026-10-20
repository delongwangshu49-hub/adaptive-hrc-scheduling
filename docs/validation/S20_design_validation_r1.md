# S20 设计包开发验证 r1

2026-10-19；PR189；**DESIGN_VALIDATED_WITH_OPEN_SCOPE_DECISIONS / PENDING_FREEZE**。机器结果见 [验证摘要](S20_design_validation_r1.json)；协议和实际冻结状态见 [审阅候选](../experiments/S20_freeze_candidate_r1.md)。

## 实际完成的检查

- 6 个原配方产品/数量描述符通过现有仿真准入，整体配置、人/设备/库位及操作/路线/材料摘要可重建；72 条设计行完整解析，dev/tune/test 分别4/4/64，18个四方法配对，继承来源233文件均匹配。
- 新增14项设计检查通过，覆盖正式执行锁、配置/来源漂移、来源缺项、重复行/缺方法、跨集合换名泄漏、共同预算、随机流隔离、手算成对均值、失败/缺失/截尾和NaN。另有4项既有生产策略检查通过，覆盖累计预算、无更新隔离、冻结数值/路线漂移拒绝及合法班组。
- 仿真生成件 `scripts/build_simulation_production.py --check` 通过；3个新增Python文件的Ruff检查/格式检查通过。生产/资产/依赖未改，不重复执行全量源码/wheel或S19B性能矩阵；原862项属于继承CI证据。
- 四方法各一次最终1h开发运行，实际执行/决策双审计通过、窗口截尾、0 READY/0接收。每方法2调用/2迭代/4试次，全部预算记录within_budget=true。各运行真实保存配置、状态、事件、决策、manifest和文件摘要。
- 四份保存轨迹在独立过程重新读取、重建，执行/决策审计均PASS；逐份删末事件后为INVALID，截断决策后为INCOMPLETE。验证使用副本内存，原日志未修改。

| 最终开发方法 | 事件/决策 | 实际运行墙钟s | 搜索累计s | 终止与审计 |
| --- | --- | --- | --- | --- |
| ADAPTIVE_JOINT | 102 / 11 | 0.954504 | 0.740693 | WINDOW_CENSORED；PASS/PASS |
| FIXED_H | 101 / 10 | 0.665287 | 0.495190 | WINDOW_CENSORED；PASS/PASS |
| FIXED_HR | 102 / 11 | 0.739032 | 0.550797 | WINDOW_CENSORED；PASS/PASS |
| NO_OBSERVATION_UPDATE | 96 / 8 | 0.486089 | 0.274951 | WINDOW_CENSORED；PASS/PASS |

这些墙钟为一次实际开发观测，不作为方法速度优势结论。1h小例用于解析、驱动、身份、保存记录与预算核验，没有覆盖完整生产或全部模式切换。全部4次使用最终开发工具与当前233继承文件；运行前后工具与继承来源摘要一致。

## 继承与未执行范围

既有S19/S19A/S19B接受及发布回执已核对，18历史M归一化内容等于HEAD，11项S19B继承证据摘要匹配，最近228项捕获来源与当前字节一致。S20没有生产/场景/界面语义改动，复用最终正常完整链及B+1 CPU/Kit严格比较，不新增Kit运行，也不把旧证据改标为新64行已验证。

最终测试0、调参0、正式A/D/B/C运行0、新Kit0。D权重/共同窗尾部及B观察投影尚无本步生产实现，明确留在候选决定中；对应正式指标分析/图表脚本属于后续获准步骤，当前只做最小汇总夹具。工业G2保持OPEN/NOT_ESTABLISHED，S19B已接受限制保持，支承通过且不再排查。

## 开发过程与证据位置

初稿前置盘点使用了不存在的equipment属性、初稿材料批次检索把STEEL误当ID片段，分别在解析阶段失败；改为devices与material字段后通过。它们没有产生正式运行。一次补丁上下文不匹配被工具拒绝，随后按实际文件重做。

首版13项检查与第一批4次开发运行保留；增强来源清单绑定和工具运行前后摘要守卫后，重新完成最终14项检查和4次开发运行。两批均为独立开发尝试，不计入测试样本。初版设计三份JSON保存于本地design-initial目录；首/最终运行分别为development-r1/r2，旧记录未覆盖。

本地根目录为 `.local/s20-20261019/`：`preflight.json`、`design-tests-r2.log`、`inherited-policy-tests.log`、`generated-input-check.log`、`development-r2/`、`saved-reconstruction-r2.json`、保护核对及审阅封包。公开机器摘要提供必要计数与文件SHA256；完整原始日志不进入候选公开文件集合。
