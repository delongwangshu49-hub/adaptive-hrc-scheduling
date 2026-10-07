# S17固定合法模式LNS：本地成果与确切审阅

2026-10-07；PR134 / LOG173，候选 **S17-20261007-r1**：**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。已完成本步固定模式骨架、严格匹配小域验证、生产当前窗口接口/合法续接、必要治理和确切待审包；人工验收与新快照发布尚未发生。沿用main/目录，未建分支/worktree或调用子代理，S18—S28及S19A/S19B未启动。

S16 r2实际限定验收与发布已补录PR133 / LOG171：提交`a3088770c2aec19143f0693d60be3a2013ce69cc`、step-S16-r2、CI run37587529250双平台各源码/隔离wheel612项成功；439树项和22文件摘要已核验。原公开批准前状态保持封存身份。此补录不等于本步获批发布，本轮没有新Kit或远端CI。

## 实现与对应核验

通用骨架包含初解、未承诺决定破坏、有限受约束修复、等分/严格改进接受、最佳可行缓存和迭代/停滞/空邻域/墙钟停止。候选分数来自独立核验，非法/较差/超时到达候选不能进入缓存，返回前再次核验。种子、每轮候选/摘要、移除决定、分数、接受/改进、拒绝/等待原因、试探数及耗时可查。完整定义见[算法说明](../algorithms/lns.md)。

静态时隙邻域改变未承诺任务的开始时间/相应次序，固定模式、角色/工时和其余Entry；每个完整组合按S16独立口径检查。生产NEXT_DISPATCH邻域只改变当前待派工父操作优先次序，复用现行合法生成器及WALK/EMPTY_RETURN/REST/SUPPORT_CHANGE；隔离副本仅试启动，原事实不变，扩展S10从事件前缀重建审计并核对过去决策/当前计划/回执因果。材料预留、带载/运行承诺、真实驻留、人员到位、位置/容量/日历和质量/供给门保留。历史缺失、伪库存/位置、错模式/版本和未知未来均有拒绝用例。

生产返回当前单命令或WAIT，目标仅为(生产/准备/等待类别, 预计结束小时)；没有输出完整未来工厂排程、注入未来质量/到货/提货事实或证明交付最优。核验中的终端WAIT只关闭审计副本，不写入实际决策账；实际环境与驱动继续独立产生事实。

## 实际证据

29专项覆盖空邻域/单解/不可修复/无初解、种子预算重放、迭代/试探/停滞/零预算/超时迟到停止、等分和非法缓存、固定模式/承诺及生产前缀/等待/反例。完整源码 **641项/194.743s**、隔离wheel **641项/192.534s** 通过；Ruff/140文件格式、锁/依赖检查、sdist→wheel及reference组摘要安装通过。140获测输入摘要保持，**213个原冻结文件未改**，现有生产/模型/场景/Schema/配方/依赖/CI及S16参照实现/原样例保持；未升级环境。最终治理落盘后再构建wheel，模块字节逐项匹配获测源码，元数据包含本版说明；无OR-Tools环境导入三个算法模块并运行静态搜索通过，基础wheel仍无运行依赖。

原七个静态开发例先显式固定模式，再给CP-SAT、规则和LNS传同一个摘要实例。六个合法目标为 **3/3/5/8/17/15**，LNS/EDD/CP-SAT同值且界一致，比值1.0、相对界间隙0；剩余例CP-SAT确证不可行，LNS仅报WAIT/NO_LEGAL_INITIAL、无伪造值/比值。固定FAST后的TINY_BINDINGS域与原S16自由模式域不同，本步集合6条/最优5，不能用原11条/最优3混作同域对比。其余四个完整固定域集合为6/3/6/9，独立枚举/合法返回/精确小时反映射核对通过；B=2三件背压保持，B=3只作独立静态开发对照。全部逐轮搜索决定重复运行一致，实际耗时另记。

六个常规例没有进一步收益；另有延迟合法初解控制由4改进到3，与同域CP-SAT3一致，仅证明改进机制，不是正式A/D效果或速度主张。[输入](../../examples/lns/cases.json)、[摘要](../../examples/lns/summary.json)和[逐轮候选](../../examples/lns/search_traces.json)可检查。

新轻量生产比较按相同原配置/固定模式/合成情景运行，每条前12个观测调用LNS、后续原EDD续接；没有预知Scenario，也没有改动执行准入、独立检查器或生产文件。复现脚本只缓存不可变类型注解查找，所有数据解码/契约/准入/状态重建/审计仍执行。完整结果如下：

| 产品 | 配置操作数 / LNS续接完成数 | EDD结束h | LNS续接结束h | LNS调用 | 执行/决策审计 |
| --- | --- | --- | --- | --- | --- |
| SR-W1 | 442 / 442 | 291.307861556 | 291.307861556 | 12 | PASS / PASS |
| SR-W2 | 456 / 456 | 292.624039722 | 292.624039722 | 12 | PASS / PASS |

两条基线与两条LNS有限干预全轨迹均完成全部活动、一次READY及一次外接收，并经扩展S10与独立决策因果审计PASS。不能称全程LNS或新Kit验证；原质量/外接收仍合成。生产公开[必要摘要](../../examples/lns/production_summary.json)包括实际等待依赖边/供给与空间拒绝原因及独立人因汇总；这不是完整死锁证明。完整原始事件/决策/墙钟记录和输入摘要仅本地留存。当前窗口分数变好不能自动解释为整链交付/人因收益，不预设LNS获胜。

另对原LOADED-FAILURE情景做1h有限承诺见证：六个保护窗口包含两个EXCEPTION及其后STARTED，实际中途运动记录1、所有者5保持；当前预留数量0原样保持，未声称该短窗见证了非零预留。搜索副本不改原前缀，故障等待/修复续接均独立执行及决策审计PASS；结局仍为WINDOW_CENSORED，不当作产品完成或本步新全链成功。该辅助见证最初使用通用旧域codec入口被拒，改用明确生产decode/validate后通过，原设置失败保留。

另从本次已完成SR-W1实际轨迹抽取5.436826667h、446事件的授权可见前缀，删除全部后续事件并重建截至该时的人因区间；当时28条真实材料预留保持，初解/修复候选/返回再次独立核验PASS，原前缀未变。这是对本次实际历史的有限重建核查，明确不计为另一条新全链或后端运行。

首轮26测试出现7个错误：非法非有限候选无法序列化，以及生产适配未正确关闭S15决策审计前缀；修复后26项再通过，新增超时/伪状态/等待后29项及全部回归通过。首轮日志保留。早期未完成生产运行为最终源码/复现入口切换而停止，不计成功；最终独立运行及完成回执另存。S15原720h截尾/疲劳INVALID、WV01首轮180分钟监督失败、S16原反例及全部历史失败不重标。

## 复现与限制

```powershell
uv run --locked python -m unittest discover -s tests -p test_lns_core.py -v
uv run --locked python scripts/run_lns_reference.py --output .local/s17-static-replay --check
uv run --locked python scripts/run_lns_production.py --output .local/s17-production-replay
uv run --locked python scripts/check.py
```

墙钟协作式停止，初解/前缀/最终独立检查和单次不可中断工作可能超预算；固定种子/迭代/试探预算重放以墙钟未先触发为条件，不宣称S19在线实时性能。固定模式与当前窗口合法性不等于S18联合模式完成、完整动态最优或正式研究效益。

HR禁用、工业资格/质量UNKNOWN、合成质量/接收、有限USD/AABB/运动学与GUI未单独体验验收保持。RP01—RP08、SC01—SC04、SH01仅LINING2.45m、WV01仅960h/840h及D01—D06其余冻结边界保持。负责人贡献为启动/范围授权，AI辅助实现、验证与治理；不虚构人工编码、实验或验收。

## 确切待审快照与拟操作

基线提交`a3088770c2aec19143f0693d60be3a2013ce69cc`；目标[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)、main、拟不可移动新标签 **step-S17-r1**。确切 **23文件**：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/lns.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/steps/S16.md`
- `docs/steps/S17.md`
- `docs/validation/S17_lns_r1.json`
- `docs/validation/S17_lns_r1.md`
- `examples/lns/cases.json`
- `examples/lns/production_summary.json`
- `examples/lns/search_traces.json`
- `examples/lns/summary.json`
- `scripts/run_lns_production.py`
- `scripts/run_lns_reference.py`
- `src/adaptive_hrc_scheduling/algorithms/__init__.py`
- `src/adaptive_hrc_scheduling/algorithms/lns.py`
- `src/adaptive_hrc_scheduling/algorithms/production_lns.py`
- `src/adaptive_hrc_scheduling/algorithms/static_lns.py`
- `tests/test_lns_core.py`

逐文件SHA-256、完整含新增文件差异和快照校验本地留存；公开集合不含内部资料、原始会话/日志、机器路径/配置或凭据。负责人针对该快照另行验收并批准发布后，拟只精确暂存这23路径、复核全部拟推送历史和现有署名、创建一个S17提交及annotated step-S17-r1，非强制推送main与新标签，核验远端完整树/文件摘要/分支/标签和Windows/Ubuntu必要CI才记PUBLISHED。无新PR、附件、Release或远端元数据改动。本次尚未执行这些Git/远端写入，也未启动后续步骤。
