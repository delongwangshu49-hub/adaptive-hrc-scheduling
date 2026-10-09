# S19-2 四项修复与合并成果审阅

候选 **S19-20261009-online-r2**；PR156 / LOG207、LOG209。**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。沿用当前 main 和目录，仅开展 S18-SIM-A1 仿真研究；工业 G2 为 OPEN / NOT_ESTABLISHED。原 S19 成果、原封包及全部失败证据保持，尚未执行新 Git 写入或启动 S19A/S19B、S20—S28。

## 四项出口与实现

1. 原 5 s／50 ms 条件下，已取得完整核验候选及真实缓存派工，并测量完整生产链周期和反馈时延。不可变结构校验、精确配置/几何缓存和独立前缀审计检查点减少重复工作；可变数据、变更前缀、配置或版本必须重新核验。完整离线复审仍从原点执行。

   计时契约明确修订：已经交付的执行/因果前缀审计放在未来 50 ms 搜索计时前，仍在观察开始后的完整 5 s 周期内，另记 feedback_verification_seconds。未来候选的构造、整个原预测窗口回放及独立核验仍计入搜索。短预算初解提出一个当前动作，对其余未承诺动作保守 HOLD 至原窗口结束；所有完成、日历、负荷、约束和已有承诺仍检查。剩余时间修复可解除初解限制。未缩短时域、减少产品或放宽物理约束，亦未证明优于 EDD 的目标值。

2. 原 Bogie0 事件的相邻记录证明，地面搬运准入后发生了 CR1 空返，旧准入只看当时几何，缺少并行动作整个扫掠范围。两方向准入现共同保守占用既有吊机立柱的完整扫掠范围直到实际释放。设备尺寸、场景 USD、工艺时长及容量不变；历史实际碰撞不归咎于早期预算 WAIT。最终完整 B+1 的实际事件、严格比较和独立审计见下表。

3. 最终源码捕获 351 份文件，所有最终运行前后核验原字节。完整两订单和 B+1 各自一次初始化、连续运行至全部接收；不拼接短窗、不补写历史关闭回执。Kit 完整清理返回后才写 closed=true，并同时保存进程退出 0。原严格比较器保持，其完整离线审计继续支持流式事件。

4. 新增非零未来承诺窗口，承诺绑定候选来源、动作顺序、模式、班组和最早开始；扰动保留承诺，实际开始/完成或有证据的产品取消才相应释放。正在执行的 EXCEPTION 恢复优先，避免未开始承诺阻断实际恢复。实际开始与原提议开始分别记录，独立核对延迟。0.25 h 承诺的持续重排和带载故障使用单独 120 s／110 s 诊断预算，不替代原 50 ms 结果。

## 最终源码实际运行

| 运行 | 终点 h / 接收 | 终止 | 执行 / 因果 | closed / 退出码 | 进程 s |
| --- | --- | --- | --- | --- | --- |
| active-short | 26.477448889 / 0 | WINDOW_CENSORED | PASS / PASS | 不适用 / 0 | 12.620 |
| b_plus_one-isaac | 845.618333333 / 3 | OPERATIONS_COMPLETE | PASS / PASS | True / 0 | 2161.075 |
| b_plus_one-light | 845.618333333 / 3 | OPERATIONS_COMPLETE | PASS / PASS | True / 0 | 931.123 |
| loaded_path_obstruction-isaac | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 98.353 |
| loaded_path_obstruction-light | 8.066901969 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 5.234 |
| multiple_orders_delayed_supply-isaac | 553.929958333 / 2 | OPERATIONS_COMPLETE | PASS / PASS | True / 0 | 1052.316 |
| multiple_orders_delayed_supply-light | 553.929958333 / 2 | OPERATIONS_COMPLETE | PASS / PASS | True / 0 | 337.900 |
| overloaded_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 67.315 |
| overloaded_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 1.441 |
| short_parity_probe-isaac | 4.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 67.726 |
| short_parity_probe-light | 4.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 1.609 |
| stability | 26.477448889 / 0 | WINDOW_CENSORED | PASS / PASS | 不适用 / 0 | 17.038 |
| stability-failure | 26.477448889 / 0 | WINDOW_CENSORED | PASS / PASS | 不适用 / 0 | 16.499 |
| three_product_initial_probe_r3-isaac | 2.043355833 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 82.963 |
| three_product_initial_probe_r3-light | 2.043355833 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 4.929 |
| zero_budget-isaac | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 68.336 |
| zero_budget-light | 2.000000000 / 0 | DECLARED_CHECKPOINT | PASS / PASS | True / 0 | 1.410 |

准备前缀的三个续接窗口不等于完整生产链；其 closed 不适用。零预算/过载预算是明确有限窗口，保留不可消除的接口开销和超限。完整长链接收及有限窗口严格区分。

| 严格比较 | 状态 / 发现数 | 事件 / 决策 | 最大时间差 h / 几何差 m | 离线进程 s |
| --- | --- | --- | --- | --- |
| b_plus_one | PASS / 0 | 13131 / 6156 | 0.0 / 4.69e-11 | 3551.124 |
| loaded_path_obstruction | PASS / 0 | 555 / 235 | 0.0 / 1.33e-14 | 17.006 |
| multiple_orders_delayed_supply | PASS / 0 | 8707 / 4091 | 0.0 / 5.27e-11 | 1131.296 |
| overloaded_budget | PASS / 0 | 11 / 9 | 0.0 / 0 | 2.322 |
| short_parity_probe | PASS / 0 | 93 / 7 | 0.0 / 3.55e-15 | 4.283 |
| three_product_initial_probe_r3 | PASS / 0 | 225 / 71 | 0.0 / 3.55e-15 | 14.575 |
| zero_budget | PASS / 0 | 11 / 9 | 0.0 / 0 | 2.360 |

| 完整 B+1 | 第三件 READY / 背压结束 h | 满缓冲位置 | 全部接收 h | 原阻挡动作开始 / 完成 h | 该动作异常数 |
| --- | --- | --- | --- | --- | --- |
| light | 746.516472667 / 840.000000000 | PRODUCT-1：FG1；PRODUCT-2：FG2 | 845.618333333 | 147.538827192 / 147.607693858 | 0 |
| isaac | 746.516472667 / 840.000000000 | PRODUCT-1：FG1；PRODUCT-2：FG2 | 845.618333333 | 147.538827192 / 147.607693858 | 0 |

原阻挡动作指 PRODUCT-3.ST-C.04.DELIVER-1；逐事件身份、开始/完成/恢复与原因见配套 JSON。完整 B+1 未再次记录 Bogie0 实际阻挡；这一结果不改变历史失败，也不将历史阻挡未经验证地归因于预算 WAIT。

## 原预算与端到端时延

| 运行 | 周期数 | P50 / P95 / 最大 s | 周期超限数 | 反馈最大 s | 完整候选 / 缓存实际启动 |
| --- | --- | --- | --- | --- | --- |
| active-short | 54 | 0.062234 / 0.107622 / 1.057662 | 0 | 0.122275 | 3 / 3 |
| b_plus_one-isaac | 6156 | 0.110934 / 0.242667 / 0.882314 | 0 | 5.971843 | 2 / 0 |
| b_plus_one-light | 6156 | 0.049054 / 0.105734 / 0.494316 | 0 | 0.535554 | 3 / 1 |
| loaded_path_obstruction-isaac | 235 | 0.039856 / 0.128096 / 0.342249 | 0 | 1.676018 | 2 / 0 |
| loaded_path_obstruction-light | 235 | 0.009363 / 0.017708 / 0.094881 | 0 | 0.112517 | 4 / 2 |
| multiple_orders_delayed_supply-isaac | 4092 | 0.076324 / 0.193296 / 0.668207 | 0 | 3.641532 | 3 / 0 |
| multiple_orders_delayed_supply-light | 4092 | 0.029447 / 0.065474 / 0.319740 | 0 | 0.336153 | 3 / 0 |
| overloaded_budget-isaac | 8 | 0.006366 / 0.014567 / 0.014567 | 8 | 0.122053 | 0 / 0 |
| overloaded_budget-light | 8 | 0.002721 / 0.010485 / 0.010485 | 8 | 0.015134 | 0 / 0 |
| short_parity_probe-isaac | 7 | 0.066011 / 0.240917 / 0.240917 | 0 | 1.858312 | 3 / 0 |
| short_parity_probe-light | 7 | 0.027671 / 0.115063 / 0.115063 | 0 | 0.142341 | 3 / 0 |
| stability | 56 | 0.057485 / 0.491755 / 1.575072 | 0 | 0.587517 | 8 / 25 |
| stability-failure | 56 | 0.060999 / 0.393181 / 1.591953 | 0 | 0.613253 | 6 / 25 |
| three_product_initial_probe_r3-isaac | 70 | 0.048501 / 0.169335 / 0.465202 | 0 | 2.754006 | 2 / 0 |
| three_product_initial_probe_r3-light | 70 | 0.019405 / 0.064747 / 0.209517 | 0 | 0.250153 | 2 / 0 |
| zero_budget-isaac | 8 | 0.006489 / 0.009648 / 0.009648 | 8 | 0.118498 | 0 / 0 |
| zero_budget-light | 8 | 0.002465 / 0.009512 / 0.009512 | 8 | 0.014485 | 0 / 0 |

原预算准备前缀续接的候选接纳毫秒：[29.5924, 32.6238, 26.3069]；全部从保存前缀独立完整重放通过。主生产仍只允许原四次搜索，后续采用当前合法规则/缓存；这不是全生产周期持续联合搜索效果证据。完整搜索用时、退出原因、修复及核验阶段数据见配套 JSON。协作退出存在超出 50 ms 的调用，不能声称每次搜索硬截止；迟到新候选不入缓存，先前及时通过的候选仍可保留。

完整 B+1 Kit 的反馈到决策结束最大为 **5.971843 s**，超过 5 s；该统计包含事件等待下一次观察的时间，与从本次观察开始计量的决策周期不同。其决策周期无 5 s 超限，不能据此宣称所有反馈均在 5 s 内处理。

反馈时延从实际事件生成到首次观察及该周期结束；周期涵盖观察、输入、前缀核验、候选、回退、派工再验证和回执。离线审计、压缩导出、Kit 启动与退出另计在进程总墙钟，不能与周期相加或当成硬实时能力。一次运行中的多个周期不是独立实验重复。

| 运行 | 声明搜索预算 s | 实际调用数 | 最大搜索 s | 搜索超限数 |
| --- | --- | --- | --- | --- |
| active-short | 0.05 | 4 | 0.050986 | 1 |
| b_plus_one-isaac | 0.05 | 4 | 0.088215 | 2 |
| b_plus_one-light | 0.05 | 4 | 0.057182 | 3 |
| loaded_path_obstruction-isaac | 0.05 | 4 | 0.067146 | 4 |
| loaded_path_obstruction-light | 0.05 | 4 | 0.050446 | 1 |
| multiple_orders_delayed_supply-isaac | 0.05 | 4 | 0.067723 | 1 |
| multiple_orders_delayed_supply-light | 0.05 | 4 | 0.051530 | 1 |
| overloaded_budget-isaac | 0.0005 | 4 | 0.000007 | 0 |
| overloaded_budget-light | 0.0005 | 4 | 0.000003 | 0 |
| short_parity_probe-isaac | 0.05 | 4 | 0.067125 | 1 |
| short_parity_probe-light | 0.05 | 4 | 0.052107 | 1 |
| stability | 110.0 | 8 | 0.575290 | 0 |
| stability-failure | 110.0 | 8 | 0.568547 | 0 |
| three_product_initial_probe_r3-isaac | 0.05 | 4 | 0.084581 | 2 |
| three_product_initial_probe_r3-light | 0.05 | 4 | 0.062013 | 4 |
| zero_budget-isaac | 0.0 | 0 | 0.000000 | 0 |
| zero_budget-light | 0.0 | 0 | 0.000000 | 0 |

零调用表示未进入搜索，最大值记 0 不表示执行了零耗时优化。整次搜索因后续尝试越限与先前候选按时接纳可以同时成立；逐次接纳时刻及退出原因见配套 JSON。

## 非空未来计划、承诺及实际偏差

| 诊断 | 可比较项 | 未来承诺 / 保护核对 | 顺序 / 模式 / 班组 / 提议开始变化 | 提议时移 h | 实际开始 / 延迟数 | 总 / 最大延迟 h |
| --- | --- | --- | --- | --- | --- | --- |
| stability | 201 | 18 / 88 | 0 / 0 / 0 / 0 | 0.000000000 | 29 / 0 | 0.0 / 0.0 |
| stability-failure | 182 | 19 / 110 | 0 / 0 / 0 / 1 | 0.142801822 | 28 / 3 | 0.75 / 0.25 |

故障诊断实际记录 EV-645：24.560716667 h 的 WORLD/FAILURE 令 FORK-01 上的 PRODUCT-1.ST-T.11.NET.DELIVER-0 进入 EXCEPTION；运动读回为 attached=true、landed=false、进度约 50%。EV-650 在 24.810716667 h 交付 REPAIR，EV-651/652 的恢复命令明确 resume_of 原命令，EV-654 在 24.845171111 h 完成。这里的异常由 WORLD 事件改变运行状态，不能仅按事件 kind=EXCEPTION 的数量判定是否发生故障。具体 WORLD、带载状态和恢复身份另存于配套 JSON，并绑定原事件流摘要。

所有保存候选逐一从原点重放并绑定摘要；模式、候选身份、实际延迟、班组、遗漏释放和候选内容六种独立副本篡改均拒绝。原 S19 的 13 项负例和历史证据继续保留。正常诊断的零变化有非零分母；故障诊断真实晚开始不会被名义时刻不变掩盖。结论限于所列续接窗口，不推断任意长期扰动下的稳定性。

## 工程验证与保留记录

源码与隔离 wheel 各 **824 项**通过，分别 215.282 s / 218.259 s；较已发布 S18 的 774 项增加 50 项，其中原 S19 的 32 项保留。锁文件、静态检查、格式、构建安装及依赖检查通过。两类生成检查通过且其输入保持。没有新远端 CI。

第一轮封存源码发现一个已核验但未使用候选缺来源摘要，原 FAILED 重放保留；修复候选身份记录并加入回归后重跑。第二轮短窗严格比较因新增增量审计对流式事件切片而 INCOMPLETE，原失败保留；改为流式迭代并加入材料化/流式一致及篡改拒绝回归，第三轮完整两订单取得接收及关闭回执，但一个动作因缓存/规则路径产生不同实际命令 ID，严格比较仍失败（23 处身份引用差异）。修复为来源无关的实际派工 ID，来源与候选摘要另存，增加实际命令一致及真实启动回归；第三轮已启动的 B+1 轻量运行明确停止。第四轮重新封存并运行全部最终负载，原三轮均按原结论保留。

第四轮新增三产品初始探针曾将 NORMAL 与专用 WV01 的 960 h 参数混用，被 WV01_EXACT_SCENARIO_REQUIRED 在执行前拒绝；修正探针命令为 NORMAL 的 2 h 检查点，完整 B+1 仍使用原获批 960 h／840 h 参数。随后父驱动中断，虽已有 Kit closed=true 报告，退出码未被观察，故该对探针另存并重跑。第四轮程序源码没有因此变化，最终表只列取得完整回执的探针；被拒绝和缺回执记录及其摘要另列于配套 JSON。

原 B+1 超限 WAIT、实际 Bogie0 阻挡、五个快速关闭缺回执及其他早期有限窗口全部保留在[原 S19 审阅](S19_online_r1.md)。本次成果不改变原事实，也不声称原封包逐文件等于当前工作区。原工艺/时长/负荷/容量及获批仿真假设数值保持，工业 G2 仍 OPEN / NOT_ESTABLISHED，符号焊接、合成质量/外接收和共用落点等限制继续适用。

## 合并审阅与拟发布

最终测量结束后仅更新治理入口和审阅文件；捕获目录中的 README 保留测量时原字节，工作区 README 新增本次结果说明。所有已测程序、配方和其他捕获输入保持原字节，封包核对对此分别检查，不将治理更新冒充已执行的新源码。

详细数值、各运行文件摘要、源码摘要、独立重放与严格比较见[配套 JSON](S19_online_r2.json)。合并封包包含原 S19 的全部 22 文件对应当前成果、交接和本轮实现/验证/治理，附逐文件 SHA256 与相对已发布基线的完整差异；保留原包，不另发旧 r1。具体文件集合和封包摘要以本地 review-manifest.json、seal-receipt.json 为准。

拟在现有 main 提交，提交标题 `feat: complete measured online scheduling and simulation continuation`，新建首个 S19 注释标签 `step-S19-r1`，再按 `git push --atomic origin main step-S19-r1` 原子推送。该方案仅供确切批准，目前未暂存、提交、建标签或推送。新成果验收与确切发布仍须负责人决定。
