# 开发环境与依赖复现（S01 / S02 / S03）

C03适用边界（2026-10-02）：钢体系已选，专属文档待冻结；当前命令仍运行旧域。后续按[修复栏目](repair_plan.md)先修契约/数据，再修人因/事件/执行；[S10—S28](roadmap.md)逐步新功能全部未实施。当前不更改依赖、CI或安装配置。

本页版本 C01-0.1（2026-10-02），保留既有安装复现流程。现行 S09 r2 已有管道领域契约、人因、事件和手工派工执行内核；C04/C05已有建筑合成契约/执行见证；调度、CP-SAT 和 Isaac 生产闭环未完成。包版本仍为 `0.1.0`；安装入口仅自检，不是生产演示。

## 版本与隔离

| 项目 | 本步选择 / 检查范围 |
| --- | --- |
| 轻量解释器 | CPython 3.12.13；`.python-version` 固定补丁版本 |
| 包兼容范围 | `>=3.12,<3.13`；本步只实测 3.12.13 |
| 环境工具 | uv 0.12.3；`tool.uv.required-version` 阻止静默切换版本 |
| 构建后端 | uv_build 0.12.3；`build-system.requires` 精确固定 |
| 运行依赖 | 当前为空；最小自检使用标准库 unittest |
| 开发依赖 | S02 新增 Ruff 0.16.9；默认 dev 组，运行依赖仍为空 |
| 轻量锁 | `uv.lock`；项目与 Ruff 两个条目，项目路径为相对的 `.` |
| Isaac 候选安装 | 现有独立安装的 VERSION 为 `6.1.0-rc.26+release.49347.2d230af4.gl`，自带 Python 3.12.13 |
| Isaac 核验边界 | S03 实测指定最小场景的启动、回调、重置与退出；不代表生产闭环或一般兼容性，见 [运行验证](validation/runtime.md) |

Isaac 候选是 RC 构建，不能写成 6.1 正式版已经通过验证。另一个现有环境仅含 `isaacsim`、`isaacsim-app`、`isaacsim-kernel` 6.0.0.1，属于兼容性检查用途，不能充当完整仿真安装。S01 没有下载或升级这些安装；S03 沿用候选 RC 安装，实测范围和运行时限制另行记录。

本步先固定已实测可用的轻量工具链，不预装后续 OR-Tools、数值分析库或 Isaac 依赖。未来需要时在对应步骤更新声明与锁文件，重新检查。`uv.lock` 管理项目依赖，不包含 Python 二进制或构建后端；前者由 `.python-version` 固定，后者由精确构建要求及固定 uv 版本控制。当前 uv 使用其匹配版本的内置构建后端。[uv 构建后端说明](https://docs.astral.sh/uv/configuration/build-backend/)

## 首次安装与最小运行

以下命令从仓库根目录执行，Windows 使用已核验的 PowerShell 7。机器上的 PowerShell 可执行文件路径保存在本地配置，不写入仓库。先确认 `$PSVersionTable.PSVersion.Major` 为 7；无需激活虚拟环境。

如尚无 uv 0.12.3，可按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 获取该指定版本。已有系统 Python 时，也可用独立工具环境安装，避免修改系统包：

```powershell
python -m venv .local/tools/uv
& ./.local/tools/uv/Scripts/python.exe -m pip install --index-url https://pypi.org/simple 'uv==0.12.3'
$env:PATH = (Resolve-Path .local/tools/uv/Scripts).Path + [IO.Path]::PathSeparator + $env:PATH
```

这段只用系统 Python 引导 uv，不决定项目解释器。之后运行：

```powershell
uv --version
uv python install 3.12.13
uv sync --locked --link-mode copy
uv run --locked python -m adaptive_hrc_scheduling
uv run --locked python -m unittest discover -s tests -v
```

最小入口应输出 JSON，包含 `version: 0.1.0`、`python: 3.12.13` 和 `scope: installation-only`。两项自检验证：从仓库外以隔离模式运行已安装包；项目分发元数据没有运行依赖。它们不证明仿真、调度或 CI 正确。

项目环境位于 `.venv`。不要依赖裸 `python` 或 `py -3.12` 自动选对解释器；本次实际发现 Windows Python 启动器不能用该短选择器找到 uv 管理的解释器，而 `uv python find 3.12.13` 可以。可用以下命令在本地核查，输出中的绝对路径不进入公开日志：

```powershell
uv python find 3.12.13
uv run --locked python -c "import sys; print(sys.executable); print(sys.version)"
```

S02 日常完整检查使用 `uv run --locked --no-editable python scripts/check.py`，内容和发布后核验要求见 [开发说明](development.md)。下方保留安装复建方法，其两项安装自检不能替代 S02 完整入口。

## 从全新轻量环境复验

新建环境不能继承全局 site-packages。下面使用随机临时名称，并恢复原环境变量；不删除或覆盖已有环境。`.local` 已被忽略。

```powershell
$s01PreviousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$s01Rebuild = Join-Path '.local' ('s01-rebuild-' + [guid]::NewGuid().ToString('N'))
try {
    $env:UV_PROJECT_ENVIRONMENT = $s01Rebuild
    uv sync --locked --no-cache --no-editable --link-mode copy
    if ($LASTEXITCODE -ne 0) { throw 'Environment rebuild failed' }
    $s01Python = Join-Path $s01Rebuild 'Scripts/python.exe'
    & $s01Python -I -m adaptive_hrc_scheduling
    if ($LASTEXITCODE -ne 0) { throw 'Installed entry failed' }
    & $s01Python -I -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Installation checks failed' }
    uv pip check --python $s01Python
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed' }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $s01PreviousEnvironment
}
uv lock --check --offline
```

`--locked` 要求锁文件与声明一致，`--no-editable` 安装构建产物，`--no-cache` 避免依赖已有包缓存。Python 二进制仍可复用指定版本的本地安装；这不是从零下载所有二进制的离线复现。首次获取 Python 或工具需要网络，仓库不再分发它们。[uv 锁定与同步说明](https://docs.astral.sh/uv/concepts/projects/sync/)

可用 `uv build --no-sources --no-cache` 构建 sdist 和 wheel，默认输出到已忽略的 `dist/`；构建不代表允许上传软件包。当前公开集合只有自有源文件、治理文档与锁文件，不包含二进制或第三方资产。更新依赖时修改声明，再运行 `uv lock`、上述重建检查并审阅差异；日常复现保留 `--locked`，不要用 `--frozen` 跳过一致性检查。

## Isaac Sim 独立入口

轻量 `.venv` 负责后续 CPU 模型、调度和批量实验；Isaac 自带解释器负责后续 Kit、USD、物理及执行反馈。即使 Python 版本号相同，两者也不是同一环境。不得对 Isaac 安装运行项目的 `uv sync`，也不向轻量环境安装 `isaacsim`。本步项目尚未装入 Isaac 环境；未来连接方式在对应实现步骤另行验证。

在单独 PowerShell 7 会话中，将 `ISAAC_SIM_ROOT` 设置为实际安装根目录，清除从其他 Python 会话继承的 `PYTHONEXE`、`PYTHONHOME`、`PYTHONPATH` 和 `VIRTUAL_ENV` 后检查：

```powershell
if (-not $env:ISAAC_SIM_ROOT) { throw 'Set ISAAC_SIM_ROOT to the installed Isaac Sim root' }
Get-Content (Join-Path $env:ISAAC_SIM_ROOT 'VERSION')
& (Join-Path $env:ISAAC_SIM_ROOT 'python.bat') -c "import sys; print(sys.version); print(sys.executable)"
```

S03 自有脚本位于 `scripts/isaac_smoke.py`，由安装包装器执行，命令见 [运行验证](validation/runtime.md)。包装器设置 Kit 路径，不能用裸的内置 python.exe 替代。Isaac 上层模块遵循 SimulationApp 初始化顺序；CPU 静态通过不代表场景通过。[NVIDIA Python 环境说明](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/python_scripting/manual_standalone_python.html)

安装与版本匹配参照 [NVIDIA 6.1 Python 安装文档](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_python.html)。[官方硬件要求](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html) 与最小场景实测是不同口径：成功仅覆盖测试负载，不构成完整兼容性认证。S02 已发布提交的 Linux / 托管 Windows CPU CI 已核验，见 [开发说明](development.md)；S03 r1 两平台 CPU CI 已核验；r2 修订尚无新提交的远端 CI。
