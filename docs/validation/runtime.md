# S03 Isaac Sim 最小运行验证

2026-10-01，S03 r1 本地指定运行通过；人工验收和本步上传仍待独立批准。该结果证明当前候选安装能完成下述最小流程，不证明生产闭环、调度方法或一般硬件兼容性。

## 安装与 API 依据

实际使用的安装版本为 `6.1.0-rc.26+release.49347.2d230af4.gl`，自带 CPython 3.12.13。这是 RC 构建，不能称为 6.1 正式版。未下载大环境、升级驱动或调整系统配置。启动会生成正常的 Kit/Warp 缓存和日志，这不等于安装原件完全无写入。

根据 [6.1 standalone 初始化说明](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/python_scripting/manual_standalone_python.html)，先创建 SimulationApp，再导入 Isaac 模块；同时核对安装内相应 API 源文件。6.1 的 [基础场景与回调说明](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/core_api_tutorials/tutorial_core_hello_world.html) 使用 experimental primitives 和 SimulationManager。本脚本采用这些接口，没有依赖旧版 World/DynamicCuboid 入口。

[自有脚本](../../scripts/isaac_smoke.py) 使用代码生成的 GroundPlane、Cube、GeomPrim、RigidPrim；不引用外部 USD 或机器人模型。地面默认模板在运行时使用安装自带的网格纹理，不需另行下载；该纹理、NVIDIA 示例文件及二进制均不进入公开包。API 调用依据官方文档，第三方运行环境与内置资源仍适用其自身许可。

## 场景、判定与复验

场景为一个地面和间距 1 m、边长 0.25 m、初始中心高度 1.5 m 的分离立方体。实际采用 Isaac Sim / PhysX，物理设备显式为 CPU；Kit 渲染器仍初始化 GPU。它不是轻量事件仿真替代后端，也不是 GPU dynamics 验证。

应用 headless，配置分辨率 640×480。每轮 stop/play 与应用更新建立物理视图，然后 pause，调用 reset_to_default_state 恢复默认位姿、线速度和角速度。预热步排除在测量区间之外；逐次 SimulationManager.step 手动推进 1/60 s。测量循环不逐帧渲染，没有相机/传感器输出或图像正确性验收。

每个进程执行三轮，每轮 240 步、4 s 仿真时间，要求：

- 每步恰好一次 POST_PHYSICS_STEP 回调，回调中的位姿/速度为有限数；每次 dt 和物理步数、累计时间均匹配。
- 重置位姿与线/角速度的最大分量误差不超过 1e-5；第 30 步所有物体高度低于 1 m，验证真实下落。
- 末态中心高度距 0.125 m 不超过 0.02 m，线速度分量绝对值小于 0.05 m/s；末次回调与直接读取一致。
- 第二、三轮完整状态轨迹与首轮逐步比较，最大分量误差不超过 1e-4。位姿、四元数、线/角速度分别以其原生单位比较，该阈值仅适用于这个固定姿态的小场景。
- 停止时间线，正常关闭 SimulationApp；场景结果 PASSED、closed 为 true，且外部进程退出 0、无超时，三者同时成立才算完整通过。

从仓库根目录，在单独的 PowerShell 7 会话中运行；先按 [环境说明](../setup.md) 配置 ISAAC_SIM_ROOT 并清除其他 Python 会话的环境变量：

```powershell
if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 required' }
if (-not $env:ISAAC_SIM_ROOT) { throw 'Set ISAAC_SIM_ROOT first' }
$s03Output = Join-Path '.local/s03/manual' ([guid]::NewGuid().ToString('N'))
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') scripts/isaac_smoke.py --output $s03Output --bodies 1
$s03Exit = $LASTEXITCODE
if ($s03Exit -ne 0) { throw "Isaac process failed: $s03Exit" }
$s03Result = Get-Content -Raw (Join-Path $s03Output 'result.json') | ConvertFrom-Json
if ($s03Result.status -ne 'PASSED' -or -not $s03Result.closed) {
    throw 'Isaac scene or cleanup failed'
}
```

分别将 bodies 改为 16、64 并使用新输出目录，可复验本步规模。默认 cycles=3、steps=240；脚本有意把 bodies 限制为 1—64，扩大范围应另行验证。已有输出目录一律拒绝；started.json 绑定脚本 SHA-256，states.jsonl 保留各轮完整状态，result.json 记录断言和关闭结果。原始输出均仅供本地证据，不能直接作为公开附件。

本次另外用本地监督进程设置 600 s 上限，并独立记录退出码与资源。遇到原生崩溃、超时、缺失或损坏结果文件均不得认定通过。普通 Python 可运行 `--help`；缺失 Isaac 模块的实测调用产生 FAILED、closed=false 和非零退出，不会替代真实验证。

## 实际结果与资源口径

三次独立进程均通过，每次三轮 240 次回调，总计 2,160 次回调。全部重置误差及重复轨迹最大分量误差为 0；末态高度范围约 0.1249978—0.1249996 m，位移与落地条件均通过。完整设备日志与状态数组留本地。

| 基础刚体数 | 本轮启动耗时 s | 进程总墙钟 s | 每轮 240 步墙钟 s | 进程峰值工作集 GiB | 采样私有内存峰值 GiB | 整卡显存采样峰值 MiB |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| 1（本次首轮） | 51.97 | 173.94 | 0.143—0.158 | 13.21 | 15.58 | 3142 |
| 16（后续运行） | 10.65 | 67.59 | 0.188—0.192 | 6.36 | 9.90 | 3333 |
| 64（后续运行） | 10.01 | 66.58 | 0.265—0.268 | 6.33 | 9.86 | 3333 |

启动时间从脚本准备启动开始到 SimulationApp 构造返回；进程总墙钟含包装器、初始化、场景准备、检查、日志与完整退出。测量循环包含状态读取与 Python 回调，不含渲染、重置、逐条 JSON 写盘或退出。上述短时墙钟不能用于宣称在线实时能力。

本地监督器约每 1 s 采样，实际最大间隔约 1.094 s。Windows GetProcessMemoryInfo 的 PeakWorkingSetSize 为该进程截至采样时的工作集高水位；私有内存是采样瞬时值的最大值。显存为 nvidia-smi 的整卡 memory.used，包含桌面和其他进程，三次运行前采样约 1588、1584、1594 MiB；不是 Isaac 独占显存，也不把简单差值冒称精确归因。显存和私有内存采样可能漏掉短暂峰值。

首轮系统可用物理内存最低约 4.53 GiB，后续两轮约 12.32、12.67 GiB。未清除既有缓存，也未进行重复冷启动控制试验，因此只能称“本次首轮”与“后续运行”，不能据此量化缓存收益或不同规模的纯增量成本。

## 可承载边界与限制

目前直接证据覆盖：单个 Isaac 进程、1/16/64 个分离基础刚体、同一地面、CPU PhysX、三轮重置、每轮 4 s、测量阶段无逐帧渲染。可将 **64 个此类刚体以内**作为后续最小场景试作的保守工作范围；这不是测得的最大容量，不保证未测负载或长时间稳定性。

没有测量接触密集堆叠、关节机器人、吊机、复杂网格、多相机、RTX 传感器、多进程或长时运行，也不能把 64 个刚体换算为 64 名工人或机器人。首轮内存开销较高，本步未授权并发多实例。正式硬件要求应另行对照 [NVIDIA 要求表](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html)；小场景成功不是满足全部官方配置的认证。

三轮真实运行无场景断言失败或超时。运行日志仍有 USD 导入构建警告、弃用提示、低分辨率 DLSS 提示及重置/关闭时 tensor view 失效警告；本步断言和正常退出已通过，但未证明这些警告在其他功能下无影响。没有修改安装或系统来隐藏警告。

本地监督工具首次错误解析工作目录，在启动 Isaac 前失败；修正后改用全新运行目录，保留原脚本和失败记录。初始旧 API 目录查找失败也保留，随后按真实安装核查。这些是工具准备问题，不冒称场景失败，也不删去实际失败。缺失 Isaac、非法规模与重复输出目录属于明确的负向检查。

独立读取原始状态的验证器和 CPU/命令行检查合计 103 项通过，覆盖轨迹、形状、有限数、步数、下落、落地、重置、源脚本摘要、退出码及输出防覆盖。统一 CPU 入口同时通过静态、格式、安装与独立 wheel 自检；两项安装测试仍是同一组测试，不按重复执行累计数量。远端 CI 属于获批推送后的单独检查，不能继承 S02 结果。

本步没有生产语义、派工反馈闭环或算法实验。S04 及之后的研究实施仍待独立启动授权。
