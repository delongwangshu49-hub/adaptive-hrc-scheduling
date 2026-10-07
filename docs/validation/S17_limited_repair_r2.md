# S17 r2：有限修复成果与确切审阅

2026-10-07；PR137 / LOG177。候选 **S17-20261007-r2**：**VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED**。负责人授权的F1/F2及C1必要契约处理已完成限定本地实现/验证；新成果验收与确切发布另审。沿用main/目录，无分支/worktree或子代理，后续未启动。

原r1已实际限定验收、批准并发布，提交`c72912b653bda6801da5c4dd2fce01cffb3f3ba3`、annotated step-S17-r1，远端454树项/23变更文件和两平台各源码/隔离wheel641项成功。PR135/LOG174实际回执补录及PR136/LOG175审阅包含在本次待审治理集合，不单独追加发布。原[批准前成果](S17_lns_r1.md)、[发布后反例](S17_post_release_audit_r1.md)、源码/封包及全部失败保留历史身份。

## 修复行为与控制证据

| 项 | 最终行为 | 实际验证 |
| --- | --- | --- |
| F1 承诺自动初解 | 有完整initial时路径保持；无完整initial且有committed时，将原Entry/资源占用全部留在有限补全中，显式栈按规则顺序/时隙回溯，返回前按原实例完整核验 | 原反例A=[1,3)、B=[0,1)自动返回FEASIBLE、目标3；未来资源锁、缺前序承诺、B=2接收背压、错误承诺、无合法补全、试探/零预算和固定流重放通过 |
| F2 已观察拒绝 | 初解自行过滤fresh value.operations中的已观察rejected父操作；修复与原驱动口径保持，验证仍核对拒绝来源 | 单产品返回独立合法WAIT；双产品选择PRODUCT-2准备，实际轻量STARTED，执行/决策前缀双审计PASS；未观察拒绝仍无法进缓存，零搜索预算仍保留合法过滤基线 |
| C1 分数维度 | 由合法初解确定维度，异维候选记OBJECTIVE_DIMENSION_CHANGED并拒绝，保留合法缓存；最终缓存漂移仍拒绝输出 | 原自定义(2,)→(1,1)不再直接丢失返回缓存，合法初解2保持；同维改进接受、最终维度漂移失败关闭通过；两个实际适配器目标定义不变 |

F1新增StaticProblem.initial_trials正整数试探上限，默认100000，与原规则初解默认一致。部分赋值剪枝只处理尚未赋值前序及未闭合驻留后缀的保守发现，不给部分赋值标合法、不进缓存、不修改执行事实或删除承诺；所有完整返回计划仍经原完整约束/模式/角色/资源/驻留/目标核验。INITIAL_TRIAL_BUDGET、WALL_BUDGET、NO_PLAN_FOUND、INVALID_COMMITMENT可查，不把搜索失败当数学不可行。不改S16参照/检查器、生产接口或任何冻结项。

## 实际检查及有限生产证据

新增18回归在未修复r1上实际检出11失败子用例/6错误，日志和旧文件已保存；最终 **47专项**、**源码659项/196.011s**、**隔离wheel659项/197.857s** 通过。Ruff/142文件格式、锁/依赖检查、sdist→wheel和reference组摘要安装通过；142获测代码/测试/脚本输入摘要保持，**213冻结文件未改**，依赖和环境未升级。原七例静态数值、固定域、目标、CP-SAT/规则/LNS摘要及逐轮重放逐项相同；原r1四完整固定集合6/3/6/9、六合法目标3/3/5/8/17/15及无收益结论保持。

另64个完整可枚举固定域没有预先提供完整initial，仅在61个可行域提供一条取自独立合法集合的承诺：自动补全和返回方案全部属于完整集合且承诺不变；3个空集合域明确等待。该检查直接覆盖F1旧缺口，不将原已给完整初解的64例PASS冒充新的自动补全证明。不是正式算法效果/速度或完整域最优性结论。

生产拒绝前缀均由公开dispatch的命令级preflight产生，未替换_admit或检查器；原观察/场景/规则/设备/人员/材料/配方保持。新双产品1h续接在原S15驱动上进行30次当前窗口LNS调用，6个静态操作、0 READY/0外接收，执行与决策因果双审计PASS，结局 **WINDOW_CENSORED**；不当作全链、全程LNS或新Kit成功。脚本只在核验副本中试启动，实际驱动产生回执/事实，规划器不接收未来Scenario。

补充承诺回归：原LOADED-FAILURE 1h合成短窗六个保护窗口保留中途运动和5个所有者，异常/修复续接双审计PASS，仍为WINDOW_CENSORED；从原已完成SR-W1轨迹重建的5.436826667h/446事件前缀保留28条预留，初解/候选/返回独立核验与种子预算重放PASS，未来事件已删除。这是有限前缀复核，不计新的全链。原r1两种442/456操作完整轨迹和全部历史失败保持，未新跑完整生产或Kit。

短窗见证首轮因原驱动的初始WORLD处理清空本地拒绝过滤，与脚本断言预期不同而失败，原日志保留且不计成功。最终脚本直接携带实际收到的最近拒绝，仍通过因果核验，未修改原驱动/准入/检查器或伪造拒绝；注解缓存只缓存不可变类型注解查找，所有数据解码/规则核验执行。最终完整检查绑定修正后的脚本，前一轮659/659工程PASS记录独立保留，不覆盖设置失败。

[必要摘要](../../examples/lns/repair_summary.json)、[初解/拒绝/维度候选](../../examples/lns/repair_traces.json)、[机器成果](S17_limited_repair_r2.json)可检查；原始事件/日志只在本地保留。

## 复现与边界

```powershell
uv run --locked python -m unittest discover -s tests -p "test_lns*.py" -v
uv run --locked python scripts/run_lns_repair.py --output .local/s17-repair-replay
uv run --locked python scripts/run_lns_reference.py --output .local/s17-reference-replay --check
uv run --locked python scripts/check.py
```

固定合法模式、有限静态补全和生产当前动作/等待边界保持；不声称完整未来工厂排程、完整动态最优、全程生产LNS、正式A/D收益或S19硬实时。初解/前缀/最终安全检查及单次工作仍可超过协作式预算。HR禁用、工业资格/质量UNKNOWN、合成质量/外接收、有限USD/AABB/运动学与GUI未单独体验验收保持；RP/SC/SH/WV与D01—D06其余冻结项保持。S15原720h截尾/疲劳INVALID、WV01首轮180分钟监督失败、S16反例和S17原失败/停止记录不重标。

负责人贡献为有限修复授权，AI辅助实现、验证及治理，不虚构人工编码/实验/验收。F1/F2/C1关闭只针对本次受测边界，不是任意输入全局正确性证明。

## 确切待审快照及拟操作

基线提交`c72912b653bda6801da5c4dd2fce01cffb3f3ba3`，目标[既有仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)、main、新不可移动候选标签 **step-S17-r2**。共 **20文件**：

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/algorithms/lns.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/steps/S17.md`
- `docs/validation/S17_limited_repair_r2.json`
- `docs/validation/S17_limited_repair_r2.md`
- `docs/validation/S17_post_release_audit_r1.json`
- `docs/validation/S17_post_release_audit_r1.md`
- `examples/lns/repair_summary.json`
- `examples/lns/repair_traces.json`
- `scripts/run_lns_repair.py`
- `src/adaptive_hrc_scheduling/algorithms/lns.py`
- `src/adaptive_hrc_scheduling/algorithms/production_lns.py`
- `src/adaptive_hrc_scheduling/algorithms/static_lns.py`
- `tests/test_lns_repair.py`

逐文件原始/LF SHA-256、完整含新增文件差异及确切快照本地留存；公開集合不含内部资料、原始会话/日志、机器路径/配置或凭据。负责人对本版成果和该快照明确验收并批准后，拟仅精确暂存这20路径，复核完整拟推送历史及现有署名，创建单个S17有限修复提交和annotated step-S17-r2，非强制推送main与新标签，核验远端完整树/摘要/分支/标签及两平台必需CI才记PUBLISHED。无新PR、附件、Release或远端元数据操作。本次尚未执行这些Git/远端写入，修复不启动后续步骤。
