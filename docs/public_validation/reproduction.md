# P06.3 安装、执行与重建

本入口用于安装候选包、执行完整 CPU 链与动态案例、审计保存件并重建显示数据。实际结果与限制见同目录的 [evidence_summary.json](evidence_summary.json)，本包实际验证见 [validation_summary.json](validation_summary.json)；Git发布和远端CI按独立回执记录。

## 输入及安装

使用仓库锁定的 uv 0.12.3、Python 3.12.13 和 `uv.lock`。核心 wheel 不包含桌面程序、复现脚本、案例输入或原始运行日志；以下操作需要候选源码中的这些配套文件。`examples/reproduction/p063-configuration.json` 是完整单产品 SR-W1 合成配置，包含原生产工序、人员、材料、空间和质量/接收门；`p063-profile.json` 保留最终 Workbench 的预算配置。没有缩短工时或删除工序。

在 PowerShell 7 中，从仓库根执行；目录名仅为示例，应选择尚不存在的运行目录：

```powershell
uv build --no-sources --no-cache --out-dir .local/p063-reproduce/dist
uv venv --python 3.12.13 .local/p063-reproduce/env
$casePython = (Resolve-Path .local/p063-reproduce/env/Scripts/python.exe).Path
uv export --locked --only-group reference --format requirements-txt --output-file .local/p063-reproduce/reference.txt
uv pip install --python $casePython --require-hashes --link-mode copy -r .local/p063-reproduce/reference.txt
$caseWheel = (Get-ChildItem .local/p063-reproduce/dist/*.whl).FullName
uv pip install --python $casePython --no-deps --link-mode copy $caseWheel
uv pip check --python $casePython
```

`-I` 隔离启动；复现入口不把仓库 `src` 加入导入路径。核验入口还要求实际包位于所用环境，并逐项记录已加载包模块的来源和摘要。桌面只读消费者及原独立检查器通过显式参数加载。

## 执行及重建

```powershell
& $casePython -I scripts/reproduce_p063.py --configuration examples/reproduction/p063-configuration.json --profile examples/reproduction/p063-profile.json --output .local/p063-reproduce/normal --case normal
& $casePython -I scripts/verify_p063_reconstruction.py .local/p063-reproduce/normal --output .local/p063-reproduce/normal-audit --checkers scripts --desktop desktop/p051/src desktop/s19b/src
& $casePython -I scripts/reproduce_p063.py --configuration examples/reproduction/p063-configuration.json --profile examples/reproduction/p063-profile.json --output .local/p063-reproduce/dynamic --case dynamic
& $casePython -I scripts/verify_p063_reconstruction.py .local/p063-reproduce/dynamic --output .local/p063-reproduce/dynamic-audit --checkers scripts --desktop desktop/p051/src desktop/s19b/src
```

桌面消费者还依赖 `desktop/s19b/src/s19b_desktop`。上面命令显式传入两个配套目录；也可把两个桌面包逐字节复制到一个独立配套目录，并将该目录传给 `--desktop`。本次实际核验采用后一布局，核心包始终来自干净环境的 wheel；不需要安装 Qt 来重建这些纯数据投影。实际 Qt/Web 绘制使用原有桌面依赖及独立记录。

正常案例在真实 Session 中关闭接单后排空，要求实际产品接收、义务清空、`COMPLETED` 和执行/因果审计通过；没有取消产品或提交 STOP。动态案例在生产进行中提交一次 `ORDER_UPDATE`，要求同 ID 的 ACCEPTED/APPLIED、目录 v1 和完整计划 v2，随后走原 STOP 保存。该动态案例的 STOPPED 只证明所列变化和保存路径，不能代替正常案例的完整终点。

可用 `--run-id` 为独立尝试指定不同身份。STOP 载荷按原契约为空对象；动态助手要求自身 STOP 的 ACCEPTED/APPLIED 双回执及零协议错误，拒绝或未知结果不能计作成功。

核验调用原生命周期及完整计划检查器，核对终态、目录、事件、决策、投影增量和真实派发绑定；原断言不变。完整计划已独立审计后，Client 仅复用同摘要计划，重放全部投影包。输出包含：

`p063_exact_audit_cache.py` 是入口的配套辅助文件。针对本步固定、只读检查器调用内不会被修改的私有 JSON 事件对象，它复用精确解码结果和规范前缀摘要；原生命周期函数的代码对象和全部断言仍执行，原模块全局变量不被替换。该缓存不用于可变业务对象。采用前已逐一对照真实事件的原解码/规范字节、原前缀摘要及分叉/截断/替换控制，并以动态案例核对整个原函数与缓存调用结果。最终显示重建逐包执行原消费者的完整校验，读完封存增量后生成一次最终 Client 投影，不重绘所有中间显示帧。

- `lifecycle-independent.json`、`plans-independent.json`：原检查结果。
- `desktop-view.json`、`deterministic-display-data.json`：实际 Client 重建的甘特、资源、人因和业务结果数据；确定性摘要排除本地读取耗时等临时字段。
- `scene-domain-projection.json`：与甘特同观察的三维域状态输入；不表示新增原生 Kit 渲染图。
- `reconstruction-result.json`：游标、包/事件/行数、双图身份、只读状态及包模块来源。
- `presentation-cache.json`：与观察摘要绑定的颜色和 W 编号缓存。空缓存重放可重建相同业务行；恢复原图的精确外观还需原保存的显示缓存，不能仅由事件推定原来的显示顺序。

档案保留陈旧/未知年龄语义，不把重读时刻当成生产者的新鲜状态。保存重建要求同一证据得到同一目录、事件和显示数据；重新执行时的墙钟、观测标识和搜索结果不要求逐字节相同。

## 分发及边界

候选 wheel、sdist 和公开配套输入分别核验。历史全量回归和历史 CI 按原身份列示，当前未执行远端 CI。本入口不执行 Git 写入、上传、README 发布更新或自动唤醒。

持续 4 Hz、2 秒源龄、10/s 与 50/s 负载资格、稳段充分性及历史驱动根因沿用原未达/不足/OPEN 状态；本步不改变性能阈值。原 E20 同会话全接收、WIP/J3 HOLD、手动 REST、P08 人工操作和 G2 边界保持。P06.3 本地技术结果不授权 G06 实际发布或 P07。

交付引用额外由 `p063_schedule_bindings.py` 逐包绑定到已核验计划的摘要、run、版本、计划ID及可见锚点，最终计划行必须完整覆盖。它是复现入口必需的配套文件，不取代原证明/生命周期审计。元数据错配、引用缺失或计划行缺失将非零退出，不能借已缓存计划返回PASS。

## P06.1软件事务入口

在候选源码根执行，输出目录须尚不存在：

```powershell
uv run --locked python scripts/verify_p061_dynamic.py --output-directory .local/new-p061-software
```

这是既有源码CLI，使用其正常脚本导入环境；P06.3安装wheel入口的`-I`要求单独见上文。该入口建立动态订单/人员事务、目录与守恒见证，不派发生产。实际采用核验另需配套完整候选、真实事件/决策及动态目录证明，受控历史档案与此软件样例分别列示。
