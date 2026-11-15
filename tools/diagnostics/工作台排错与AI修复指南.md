# HRC 工作台排错、使用自检工具及 AI 本机修复指南

适用项目：Adaptive HRC Scheduling / 连续生产工作台，当前 v1.0.1 和 v1.1.0 的 Windows 目录布局。自检工具版本：1.0.0。

本文是 2026-11-13 r2 微信交付指南。你应收到两个文件：`工作台排错工具包_20261113_r2.zip` 和 `工作台排错与AI修复指南_20261113_r2.txt`。ZIP 内也有同内容的指南，任选一份阅读即可。工具包只有诊断程序和资料，不是 340 MB 左右的工作台安装包；它检查你电脑上已有的工作台，缺少原软件时按本文发行入口补齐。

## 一、最省事：两个文件一起交给能操作本机的 AI

使用有本机文件读写、终端执行能力的 AI 客户端；完整验证界面还需要桌面操作能力。把收到的 ZIP 和本指南一起交给它，或告诉它两个文件的绝对路径，再复制下面这段话作为**你的任务请求**。指南里的示例路径不能代替你电脑的真实位置，也不能因为上传到普通网页聊天就默认 AI 已能访问你的电脑。

```text
请在我的这台 Windows 电脑上，按随附《工作台排错与AI修复指南》完成 HRC 连续生产工作台的排错与修复，不要只给建议后结束。

我授权你在本机查找并读取相关安装和日志、解压诊断包、运行自检、备份后修复相关配置或 Python 环境、从指南列出的官方来源补齐必要依赖/同版本安装文件，并重新运行检查和工作台验证。请保留原软件、原会话和失败证据，不删除旧安装，不改排程逻辑或研究数据，不上传我的日志或进行 Git 发布。

先自行识别我是便携版还是源码版，以及实际安装路径；不要把发送者电脑的 D:\7023p 当成我的路径。默认先排查截图中的 CPU 模式。对于未知的安装位置，先从附件所在文件夹、现有快捷方式目标和常用下载/桌面位置查找；只有确实找不到或存在多个无法区分的安装时，才问我一次必要的问题。

请执行：读取指南和工具代码→备份和基线检查→找到具体失败路径/模块/启动命令→实施相应修复→完整复查→启动单产品 CPU 测试并观察甘特→安全停止并核对保存/退出→交付修复记录及可直接使用的启动路径。

遇到 UAC、受组织管理的安装权限、账户登录或缺少本机工具能力时，明确告诉我当前哪一步需要我操作；完成其余可执行步骤后等待我，不要虚构已经安装或修好。发现新错误要继续定位，不要把自检退出码 0 当作界面问题必然解决。最后用实际证据说明改了什么、根因是什么、哪些验证完成，以及还有没有剩余问题。
```

AI 应按本文后面的“AI 执行流程”工作。当前自检程序负责取证和生成修复建议；修复操作由收到上述任务请求的 AI 执行，程序本身不会静默安装软件或更改你的配置。

## 二、自己操作：从微信接收开始

1. **下载两个原文件。** 在微信文件消息中下载 ZIP 和 TXT，用“在文件夹中显示”找到它们；不要只转发文件截图或复制旧电脑的文件路径。
2. **准备工具文件夹。** 可在当前用户的“下载”目录创建 `HRC-Diagnostics`。右键 ZIP 选择“全部解压”，打开解压后的 `HRC-Diagnostics-r2` 文件夹。不要直接在压缩软件的预览窗口里双击脚本。
3. **确认解压结果。** 同一文件夹应包含 `Run-Diagnostics.cmd`、`Start-Diagnostics.ps1`、`Test-HRCWorkbench.ps1`、`Trace-HRCStartup.py`、中文指南、验证记录、测试源码和 `SHA256SUMS.txt`。不要把这些文件分散放置。
4. **找到原工作台。** 如果平时双击 EXE，右键其快捷方式→属性→目标或打开文件所在位置，找到原 `HRC-Workbench.exe`。如果平时用 Python 命令，找到包含 `pyproject.toml`、`src`、`desktop` 的源码根目录。复制该文件夹地址，不是工具包的地址。
5. **双击 `Run-Diagnostics.cmd`。** 不需要“以管理员身份运行”。若缺 PowerShell 7，按下方安装说明处理后重新双击。窗口提示的是诊断工具的依赖，不等于已查明工作台报错原因。
6. **按四个提示输入。** 第一行粘贴原工作台目录；第二行输入 `CPU`（截图所选模式，直接回车也可）；第三行粘贴 `[WinError 2] 系统找不到指定的文件。`；第四行有明确失败会话目录就填，没有就直接回车。粘贴目录时有双引号也可，交互入口会去除外层双引号。
7. **等待检测。** 完整便携包校验需要读取八千多个文件，磁盘较慢时可能需要几分钟。出现“正在核对…SHA-256”不代表卡死；Python 探针通常很快，默认每个探针最多等待 40 秒。出现 FAIL 后程序仍会继续收集其他检查结果。
8. **打开报告。** 窗口最后会给出 `诊断报告.txt` 和 `diagnosis.json` 的完整路径。复制到资源管理器地址栏即可打开，也可在 `%TEMP%\HRC-Diagnostics` 找到最新时间目录。窗口保留到按键退出。
9. **按报告修复，再完整运行一次。** 优先处理 FAIL 中的确切路径。保留第一次报告，不覆盖它。不会修复时把两个报告交给上述本机 AI，或发给维护者。
10. **验证原操作。** 重新打开修复后的原工作台，重复“启动配置→CPU→确认启动”。出现实际已验证甘特之后再按“安全停止”，等待保存及进程退出。只看到界面能打开或自检通过，还没有完成这一步验证。

例如，原工作台目录是 `C:\Users\你的用户名\Downloads\HRC-Workbench-Windows-x64`，工具目录是 `C:\Users\你的用户名\Downloads\HRC-Diagnostics\HRC-Diagnostics-r2`：第一行应输入前一个目录。两者可以放在不同磁盘。

## 三、AI 执行流程：从接收附件到修复验收

### A. 定位对象和建立工作记录

1. 先读本指南及 `Test-HRCWorkbench.ps1`，确认它是独立诊断脚本，不能当作原工作台。解压到新目录，不覆盖已有版本。
2. 查找本机真实安装：优先读取用户正在使用的快捷方式目标、附件附近目录和用户说明。对便携版记录 EXE 绝对路径；对源码版记录根目录和启动命令。存在多份安装时按错误截图时间、最近日志及用户实际启动入口定位，不能挑一份正常副本就宣布修复。
3. 明确后端：此问题首先按 CPU 排查，不为 CPU 故障安装数 GB 的 Isaac。只有用户确实要使用三维后端时才进入 Isaac 分支。
4. 在当前用户可写位置建立本次任务目录，建议 `%LOCALAPPDATA%\HRCWorkbench\diagnostic-work\日期-随机编号`。存放 `before`、`after`、备份、控制台日志和最终记录。记录原安装目录、应用标签/下载文件名、开始时间及是否有活跃会话。不要把 Python 库元数据 `0.1.0` 直接当成应用发行版本。
5. 若有活动会话，先通过工作台安全停止并等实际退出，再重建环境或更改配置。不要通过按进程名批量结束所有 Python/Kit 进程来腾位置。

### B. 准备 PowerShell 7 与必要工具

1. 所有 Windows 开发/诊断命令使用 **PowerShell 7**。优先检查 `C:\Program Files\PowerShell\7\pwsh.exe`，并读取 `$PSVersionTable.PSVersion.Major`；不要默默调用 Windows PowerShell 5.1。
2. 如已在其他位置安装 PowerShell 7，可以用其确切可执行路径运行 `.ps1`；`Run-Diagnostics.cmd` 的固定查找路径及 Isaac 启动代码的固定路径需单独核对。
3. 如未安装，使用[微软 PowerShell 安装页](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-windows)的 x64 MSI。可以通过本机终端的 WinGet 安装 MSI：`winget install --id Microsoft.PowerShell --source winget --installer-type wix`。如果本机 WinGet 不支持此参数，改为下载官网 MSI，而不是猜测安装成功。需确认安装进程成功且上述 `pwsh.exe` 存在。UAC 由用户本人处理，AI 不代输凭据。
4. 已有 PowerShell 7 时，在其中执行下方示例；先替换路径变量，其他参数照用。相对路径一律以记录的真实目录为准。

```powershell
$hrcPwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'
$hrcTool = 'C:\实际工具目录\HRC-Diagnostics-r2\Test-HRCWorkbench.ps1'
$hrcRoot = 'C:\实际原工作台目录'
$hrcWork = Join-Path $env:LOCALAPPDATA ('HRCWorkbench\diagnostic-work\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $hrcWork -Force | Out-Null

& $hrcPwsh -NoProfile -ExecutionPolicy Bypass -File $hrcTool `
  -Root $hrcRoot -Backend CPU -ErrorText '[WinError 2] 系统找不到指定的文件。' `
  -OutputDirectory (Join-Path $hrcWork 'before')
$hrcDiagnosticCode = $LASTEXITCODE
# 自检 1/2 是可解释的诊断结果，先读取报告，不能只因非零就停止整个修复任务。
$hrcReportFile = Get-ChildItem -LiteralPath (Join-Path $hrcWork 'before') -Filter diagnosis.json -Recurse |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $hrcReportFile) { throw '未生成报告，先检查终端错误和参数。' }
$hrcReport = Get-Content -LiteralPath $hrcReportFile.FullName -Raw | ConvertFrom-Json
$hrcReport.checks | Where-Object status -in @('FAIL', 'WARN') | Format-List
```

这里的 `-ExecutionPolicy Bypass` 只影响此进程，不修改永久策略；如果组织策略仍阻止执行，记录实际错误并请用户处理该阻断。

### C. 按证据选择修复分支

**C1. 源码版缺 CPU/桌面环境或环境已损坏**

- 不要用“全局 Python 已安装”替代项目中那两个确切解释器路径的检查。自检缺哪个就修哪个。
- 先记录根目录和桌面目录的 `pyproject.toml`、`uv.lock` 是否齐全，并备份准备更改的环境配置。缺源码/锁文件时恢复同一版本完整源码，不生成新锁文件来绕过问题。
- 若已有 uv，执行 `uv --version`。此项目锁定 uv 0.12.3；采用该版本，不擅自更新锁文件。没有 uv 时，按 [Astral 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)使用指定版本安装器 `https://astral.sh/uv/0.12.3/install.ps1`：下载到任务目录、检查来源与内容，再使用 PowerShell 7 执行。完成后定位真实 `uv.exe` 并验证版本；不能假设当前终端 PATH 会自动刷新。若版本资源不可用，记录下载失败并采用项目已发布便携包方案或向维护者确认，不能静默换版本。
- 在源码根目录执行 `uv python install 3.12.13`，确认退出码为 0，再执行 `uv sync --locked`；桌面环境使用 `uv sync --locked --project desktop/p051`。每个命令单独检查退出码，失败先解决本步网络/版本/权限问题，不继续假定安装成功。
- 若 `.venv` 已存在但探针加载失败，`uv sync` 不一定会修复所有被破坏的现有文件。关闭对应会话，先将**确切出错的环境目录**改名为带时间戳的备份，再按锁文件重建。改名前验证其绝对路径确实是该项目的根 `.venv` 或 `desktop/p051/.venv`；保留备份，不执行递归删除。
- 不把 CPU 启动路径直接替换为 `sys.executable` 来绕过错误：桌面解释器未必包含 CPU 求解依赖。先修复原设计要求的环境。

**C2. 便携版缺文件或 SHA-256 不一致**

- 不在损坏包上逐个拼接 Python/DLL。记录报告中的差异，保留原包与原会话，从下面官方发行入口取回**同版本 Windows 附件**，校验外部摘要后解压到一个新的本地目录。
- v1.0.1 正式版：[发行页](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/releases/tag/v1.0.1)，Windows 附件名 `HRC-Workbench-Windows-x64.zip`。
- v1.1.0 预发布：[发行页](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/releases/tag/v1.1.0)，Windows 附件名 `HRC-Workbench-Windows-x64-v1.1.0.zip`。
- 选择 `.zip` 运行附件，不选 GitHub 自动生成的 `Source code (zip)`。使用发行页该版本的 SHA-256 清单核对下载字节；取得不到可信清单时如实标记“下载来源/外部摘要未核验”，不能用自己计算的摘要冒充官方预期值。内部 `PACKAGE-SHA256.txt` 的检查另行执行。
- 恢复后仍复用原会话目录；不要搬走或删除 `%LOCALAPPDATA%\HRCWorkbench\runs`。如果新目录正常而旧目录失败，说明修复范围是安装副本；最后告诉用户正确的新 EXE 路径，避免再次打开旧快捷方式。更新用户实际使用的快捷方式前，备份原目标信息。

**C3. 前端、设置或结果路径问题**

- 缺前端文件：源码版先核对 Node/npm 可用，再执行本文前端重建命令并逐步检查退出码；便携版通过同版本完整解压恢复，不在便携目录现场 npm 构建。
- 设置 JSON 损坏：先备份 `settings.json`，退出工作台后改名，重新启动并通过“便携设置与示例”设置路径。保留全部运行目录。需要直接修正 JSON 时仅改确认有问题的 `runs`/`isaac` 字段，并保留修前内容。
- 结果目录不可写：选择当前用户可写的新路径，随后在工作台设置中实际保存。`-RunsDirectory` 参数只改变诊断目标，不能代替真正修改工作台设置。复查时去掉该覆盖参数，确认程序真实配置已生效。
- 缺 DLL/位数不匹配：使用 x64 环境和完整依赖。先根据报错的模块和文件判断损坏范围，再重建对应环境。不要下载来历不明的单个 DLL，不关闭系统防护。

**C4. 自检通过，原始错误仍存在**

- 首先确认自检目标和实际打开的 EXE/源码是同一份，错误是否来自本次新会话；读取该会话 `p051-worker.log` 以及便携 `startup.log`，不要只读“最近一份”就认定关联。
- 记录按钮操作、报错时间、完整异常、实际子进程命令和工作目录。自检报告里 `target`/`evidence.filename` 已有确切文件名时优先使用。
- 如果页面吞掉 traceback，可以在任务目录建立下方“临时启动取证脚本”，用对应的**界面解释器**启动原工作台。它只在本次进程中记录失败的 `subprocess.Popen`，不改原应用文件，不记录整份环境变量；运行结束恢复普通启动方式。
- 如果异常发生在文件读取、数据构造等其他阶段，而不是 Popen，脚本可能没有捕获记录。此时检查同版本 `app.py` 的 `prepare_launch` / `start_worker` 和实际异常调用链，进一步做最小复现；不要把“没捕获到 Popen 失败”解释成没有故障。
- 证明确为应用启动层缺陷而不是环境问题时，可以在用户授权范围内先备份、做最小本地修复，并验证差异及复现结果；不得通过删断言、改排程规则或伪造成功回执来消除报错。无法定位时提交已取得的证据及具体剩余阻断，不笼统写“全部搞定”。

工具包已附 `Trace-HRCStartup.py`，可以直接使用，无需手工重写。它与下方示例采用相同的取证方式；若需要独立副本，也可保存以下内容为任务目录中的 `trace_startup.py`：

```python
import datetime
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import traceback

# 参数：实际 app/源码根目录、portable 或 source、取证日志绝对路径。
root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
log = Path(sys.argv[3]).resolve()
if mode not in ("portable", "source"):
    raise ValueError("mode must be portable or source")
entry = root / ("portable-launch.py" if mode == "portable" else "scripts/run_p051_workbench.py")
if not entry.is_file():
    raise FileNotFoundError(str(entry))
log.parent.mkdir(parents=True, exist_ok=True)
original_popen = subprocess.Popen

class LoggedPopen(original_popen):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except OSError:
            record = {
                "time": datetime.datetime.now().astimezone().isoformat(),
                "command": args[0] if args else kwargs.get("args"),
                "cwd": str(kwargs.get("cwd") or os.getcwd()),
                "traceback": traceback.format_exc(),
            }
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            raise

subprocess.Popen = LoggedPopen
os.chdir(root)
sys.path.insert(0, str(entry.parent))
sys.argv = [str(entry)]
runpy.run_path(str(entry), run_name="__main__")
```

调用方式：便携版使用 `安装根目录\app\.venv\Scripts\python.exe`，第一个参数填 `安装根目录\app`；源码版使用 `源码根目录\desktop\p051\.venv\Scripts\python.exe`，第一个参数填源码根目录。第二个参数分别是 `portable` / `source`，第三个参数是任务目录中的 `failed-launch.jsonl`。例如：

```powershell
& 'C:\实际工作台\app\.venv\Scripts\python.exe' -B -X utf8 `
  'C:\实际任务目录\trace_startup.py' 'C:\实际工作台\app' portable `
  'C:\实际任务目录\failed-launch.jsonl'
```

打开界面后再次点击出错按钮；有失败记录时，AI 应读取 `command[0]`、`cwd` 和 traceback 中的具体路径，再修复对应原因。取证日志可能包含用户文件路径，仅用于本地排错。

### D. 修复后复查、实际运行与交付

1. 用**同一目标安装**重新执行完整自检，报告存入 `after`。不得使用 `-StaticOnly` 或 `-SkipIntegrity` 作为最终完整通过的依据。第一次报错文字留在 before；after 不再传入历史 `-ErrorText`，否则工具会刻意保留“用户错误尚待核查”的 WARN。
2. 自检自动读取到旧 startup.log 的历史错误时，WARN 可能继续存在；核对时间和运行身份后在结论中解释它，不能为了退出码 0 删除历史日志。
3. 启动原工作台：便携版运行新核验过的 `HRC-Workbench.exe`；源码版运行 `desktop/p051/.venv/Scripts/python.exe scripts/run_p051_workbench.py`。有桌面工具就实际操作；没有桌面工具时，明确请用户完成下面这一个连续验证步骤并提供结果，不冒称已经看到界面。
4. 本次只新建本地单产品测试：启动配置→SR-W1→1 件→CPU→确认启动。保持用户原调度选项，不连接外部设备。等待实际已验证计划和甘特出现，记录会话目录及成功/错误状态；等待中的空白甘特不算已经通过。
5. 使用“安全停止”，等待保存状态和工作进程真实退出，再通过“打开会话”重开这次保存件，确认甘特可读取。保留该新会话与其回执。存在长时间无进展或新报错时，按该次日志继续排查，不能强杀后记作安全结束。
6. 如果用户还要 Isaac，CPU 成功后再单独核查其安装、固定启动路径、ASCII 结果路径、硬件和驱动，并实际验证原生画面。CPU 成功不代表 Isaac 成功。没有 SDK/合适硬件时将该项明确列为未完成，不为完成文字而改用别的后端冒充。
7. 在任务目录写 `修复完成记录.txt`：根因及证据；原安装/新安装及启动路径；备份位置；执行的修复和命令结果；before/after 报告路径；实际 CPU 会话、甘特、停止、保存、退出和重开结果；剩余问题。只有相关验证真的通过，才写“该故障已修复”。

完整流程会处理能在当前权限和环境下修复的本地问题。管理员批准、登录、无法取得的安装资源或缺少实际硬件，需要如实转交必要的用户操作；它们不能靠两份附件本身消除。

## 四、自检程序用法与诊断解释

1. 将本工具包完整解压。它可以独立放在桌面，无需覆盖工作台文件。
2. 双击 `Run-Diagnostics.cmd`。
3. 粘贴**发生错误的安装目录**：便携版选包含 `HRC-Workbench.exe` 的文件夹；源码版选包含 `pyproject.toml`、`src`、`desktop` 的项目根目录。
4. 输入报错时选择的后端 `CPU` 或 `Isaac`，按提示填写报错文字和失败会话目录。不知道会话目录时可留空。
5. 等待检测完成。程序会打印报告位置，生成中文 `诊断报告.txt` 和机器可读 `diagnosis.json`。将这两个文件发给维护者。

默认报告存放在 `%TEMP%\HRC-Diagnostics\时间-随机编号\`，每次使用新目录，不覆盖之前的结果。程序不会自动发送文件。报告包含本机路径及日志末尾，转发前可检查是否含有不宜分享的业务内容。

**自检工具需要 PowerShell 7；不依赖系统 Python，也不要求先修好项目 Python。** 双击入口使用 `%ProgramFiles%\PowerShell\7\pwsh.exe`。如果提示缺少 PowerShell 7，请按[微软安装说明](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-windows)安装 x64 MSI 到默认目录；已有其他位置的 PowerShell 7 时，也可在其窗口中运行下方命令。工具不会切换到 Windows PowerShell 5.1。CPU 工作台本身和这份自检工具的依赖不同，缺少 PowerShell 7 不应被解释成 CPU 工作台报错的根因。

## 如何读报告

| 状态 | 含义 | 下一步 |
| --- | --- | --- |
| `FAIL` | 查实的缺失、加载失败、路径错误，或自检本身未完成 | 先看 `位置`，再执行该项 `处理` 建议 |
| `WARN` | 日志线索、跳过的检测或需要人工核对的情况 | 核对是否属于这一次失败；不能直接当成确定根因 |
| `PASS` | 该项实际检测通过 | 不代表整个工作台已完成 GUI、生产或长期运行验收 |
| `INFO` | 背景信息或未选用的组件 | 通常无需修复 |

退出码：`0`＝已执行的检查通过；`1`＝存在 FAIL；`2`＝没有 FAIL，但存在 WARN；`3`＝报告无法写入或启动入口无法执行。参数拼写错误、PowerShell 启动失败也可能在报告生成前返回非零，此时保留控制台文字。

报告将 FAIL 和 WARN 排在前面。JSON 中的 `checks[].target` 是检查的确切位置；`evidence` 保存解释器异常、模块名、缺失文件、摘要差异等证据；`fix` 给出下一步。若仍出现原错误，即使退出码为 0，也应继续提供完整异常，而不是宣布已经修复。

## WinError 2：这个项目中重点看什么

`[WinError 2] 系统找不到指定的文件` 表示访问文件或创建进程时找不到目标。仅凭这一行无法知道缺失文件名。这个项目的 CPU 启动代码会调用固定位置的 Python，因此首先查看以下检查项。

### 源码版：两个环境分别检查

| 用途 | 相对于源码根目录的路径 | 报告检查项 |
| --- | --- | --- |
| CPU 后台 | `.venv\Scripts\python.exe` | `cpu.python.file` / `cpu.python.launch` |
| 桌面界面 | `desktop\p051\.venv\Scripts\python.exe` | `ui.python.file` / `ui.python.launch` |

**界面能打开，不代表 CPU 后台环境已经存在。** 当前 README 的“从源码运行 Windows 工作台”小节只列出桌面环境同步；若跳过其他小节中的根环境安装，就可能出现界面正常而“确认启动”报 WinError 2。

在 PowerShell 7 中，将下列目录换成自己的源码位置。需要项目锁文件要求的 uv 0.12.3 和 Python 3.12；不要从其他电脑直接复制 `.venv` 代替安装。

```powershell
Set-Location -LiteralPath 'C:\HRC\adaptive-hrc-scheduling'

# CPU 后台：在项目根目录创建/同步环境
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'CPU 环境安装失败，请先处理 uv 输出。' }

# 桌面界面：单独创建/同步环境
uv sync --locked --project desktop/p051
if ($LASTEXITCODE -ne 0) { throw '桌面环境安装失败，请先处理 uv 输出。' }

& .\desktop\p051\.venv\Scripts\python.exe .\scripts\run_p051_workbench.py
```

如果 Python 文件存在但 `launch` 检查失败，报告会保留实际启动错误或标准错误输出。移动过的虚拟环境可能仍指向原电脑的基础 Python。先关闭工作台，备份并将**出错的那个环境目录**改名，再重新执行对应的 `uv sync`。不要把系统中另一个 `python.exe` 单独复制进去。

若 `uv` 命令本身找不到，需要先按项目要求安装 uv，或者改用发行页的完整 Windows 便携包。安装过程中若锁文件、网络或依赖下载报错，保留原始输出，不能跳过错误继续启动。

### 便携版：先核对完整解压

```text
HRC-Workbench-Windows-x64\
  HRC-Workbench.exe
  PACKAGE-SHA256.txt
  app\
    portable-launch.py
    .venv\Scripts\python.exe
    desktop\p051\web\dist\index.html
    scripts\run_s19b_prototype.py
```

便携版的界面和 CPU 后台都使用随包解释器；已打开界面时，不能仅凭 WinError 2 就断定 Python 缺失。

- `package.integrity` 会逐一核对 `PACKAGE-SHA256.txt` 的记录。`MISSING` 给出缺失路径；`SHA256_MISMATCH` 给出内容不一致的路径及摘要。清单自身不在其自列记录中。
- 清单损坏、必需记录缺失、重复路径、越出包目录的路径及不能可靠核验的链接都会报告异常。完整性只表示与随包清单一致，不证明下载来源可信。
- 如有缺失或损坏，保留原会话，重新下载可信发行页中的 **Windows 运行 ZIP**，解压到一个新目录再使用。不要下载 `Source code (zip)` 当作便携运行包，不要从压缩软件里直接运行，也不要只转发 EXE。
- 若完整解压后文件再次消失，可检查 Windows 安全中心的保护历史。没有相应记录前，不应认定是杀毒软件造成的；不要直接关闭防护或添加整盘排除。

源码包与便携包内的环境布局不同，自检会识别当前选中的布局。工具支持把 `-Root` 指向 EXE、本身的 `app` 目录或安装根目录。

## 其他常见诊断结果

| 检查/现象 | 可能位置 | 处理方式 |
| --- | --- | --- |
| `cpu.python.ortools` 失败 | CPU 环境的 OR-Tools 或其 DLL | 查看具体异常；源码根环境按锁文件重新同步，便携包重新完整解压 |
| `template_SR-W1` / `template_SR-W2` 失败 | 模板输入、模型 TSV 或相关源码 | 根据 traceback 中的文件名恢复同版本完整文件；不需要先运行一次生产 |
| `ui.python.qt_webengine` 失败 | PySide6、Qt DLL、QtWebEngineProcess 或资源文件 | 修复桌面环境；便携版优先检查完整性。工具不会要求从第三方网站单独下载 DLL |
| `web.index` / `web.asset.*` 失败 | 缺前端构建结果 | 源码版重建前端，便携版重新解压；`qrc:` 属于 Qt 内置资源，不按磁盘文件误报 |
| `runs.writable` 失败 | 结果路径为文件、不可访问或不可写 | 便携版更换结果目录；源码版检查 `.local\p051-ui-runs` 权限 |
| `settings` 失败 | `%LOCALAPPDATA%\HRCWorkbench\settings.json` | 退出工作台，备份并改名设置文件，再重新配置；不删除 runs 会话 |
| `log.winerror2` / `log.module` / `log.dll` | 输入报错或日志末尾命中相应模式 | 这是线索；结合实际环境检测和同一次会话 traceback 定位 |
| `logs.receipt` | 工作进程非零退出、失败或未关闭回执 | 核对 run_id/request_id 和日志；活动会话未关闭、历史失败都不能混作当前根因 |
| 所有检查通过但界面仍报错 | 尚未覆盖的 GUI、渲染、运行时业务或版本问题 | 保留具体操作、时间、完整异常和本次会话，交由维护者继续定位 |

源码前端重建命令，在项目根目录的 PowerShell 7 中执行：

```powershell
npm.cmd --prefix desktop/p051/web ci
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
npm.cmd --prefix desktop/p051/web run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
```

CPU 模式只提供甘特和相关数据，不提供 Isaac 原生三维画面。左侧没有三维画面本身不能作为 CPU 启动失败的依据。

## Isaac 模式额外检查

选 `Isaac` 后，工具检查 PowerShell 固定路径、Kit 启动脚本、Isaac 的 `python.bat` 和 `VERSION`、6.1 系列版本，以及结果路径是否含非 ASCII 字符。

便携版从设置文件读取所选 Isaac 目录；源码版当前启动代码固定使用 `D:\Dev\tools\isaac-sim-6.1`。自检会报告实际使用的位置，不会将仅存在于其他目录的安装误记为就绪。当前工作台使用固定的 `C:\Program Files\PowerShell\7\pwsh.exe`（便携版以 ProgramFiles 为前缀）；仅在 PATH 中能找到另一个 PowerShell 不代表该启动路径存在。

使用 `C:\HRC\runs` 这类纯 ASCII、可写的结果路径。源码版默认结果在项目内部，因此项目路径含中文也会影响该条件。**CPU 模式支持中文路径，自检不会把这一限制套到 CPU。**

本工具不启动 Kit、不检测 GPU 驱动兼容性、不创建原生窗口。因此 Isaac 检查会明确保留 `isaac.scope` 警告；它不能替代在目标电脑上的原生渲染验收。

## 命令行用法

在 PowerShell 7 中运行。工具和被检查项目可以在不同位置，以下路径均为示例，需替换为实际位置：

```powershell
& 'C:\HRC-Diagnostics\Test-HRCWorkbench.ps1' `
  -Root 'C:\HRC\HRC-Workbench-Windows-x64' `
  -Backend CPU `
  -ErrorText '[WinError 2] 系统找不到指定的文件。'
```

有失败会话时，优先明确指定，避免自动选中其他历史运行：

```powershell
& 'C:\HRC-Diagnostics\Test-HRCWorkbench.ps1' `
  -Root 'C:\HRC\HRC-Workbench-Windows-x64' `
  -RunDirectory 'C:\Users\你的用户名\AppData\Local\HRCWorkbench\runs\P051-实际编号' `
  -OutputDirectory 'C:\HRC\diagnostics'
```

| 参数 | 用途 |
| --- | --- |
| `-Root` | 报错电脑上的安装/源码目录。省略时尝试当前目录及工具所在项目目录；排错时建议明确填写 |
| `-Backend CPU/Isaac` | 按报错时的实际选择填写，默认 CPU |
| `-ErrorText` | 保存当前报错文字。即使未命中已知模式，也保留待查状态，不伪称已修复 |
| `-RunDirectory` | 明确指定失败会话。省略时取结果目录中最近修改的子目录；这不保证就是失败的那一次 |
| `-RunsDirectory` | 仅覆盖本次自检的结果路径，不修改工作台设置；不指定时读取实际默认/便携设置 |
| `-SettingsFile` | 仅供检查指定便携设置副本；默认读取当前用户实际设置 |
| `-OutputDirectory` | 报告父目录，每次新建唯一子目录；默认为 `%TEMP%\HRC-Diagnostics` |
| `-ProbeTimeoutSeconds` | 每个 Python 加载探针的等待上限，默认 40 秒，范围 5–120 秒 |
| `-StaticOnly` | 只查文件等静态条件，跳过 Python/依赖实际加载；会产生 WARN，不能当作完整通过 |
| `-SkipIntegrity` | 跳过便携包全量摘要比对；会产生 WARN，仅适合先快速检查后再完整复查 |

若直接运行 `.ps1` 被执行策略拦截，优先使用随包 `.cmd` 入口；它只为这次 PowerShell 进程指定策略，不修改系统持久设置。组织策略仍可能禁止运行，此时由维护者处理，不要求关闭系统安全控制。

## 检测会做什么、不会做什么

检测会读取当前安装、设置和指定/最近会话的有限日志末尾；运行最多两个短期 Python 加载探针；构造两个产品模板及一个空的求解器模型以验证依赖加载；在结果目录或其最近存在的父目录创建并删除一个随机临时文件，确认写入能力。便携完整性检查会读取清单列出的文件。结果目录尚不存在时，报告会注明只验证了父目录。

不会安装依赖、修改配置、覆盖程序、调整系统 PATH、执行求解、创建生产会话、启动 Isaac 或上传日志。超时只终止本次创建的诊断子进程，不终止正在运行的工作台。存在运行中的会话时，仍应通过工作台的“安全停止”流程结束。

本工具用于找出常见启动和环境问题。它不能保证自动定位所有未知软件缺陷。没有确证时会保留“未定位/待核查”，并给出进一步需要的证据。

## 给维护者的信息

请一并提供：诊断 TXT/JSON、软件版本及下载包名、EXE 或源码启动方式、出错时选择的后端、触发错误的操作和时间、明确的失败会话目录。若报告只有 WinError 2 而没有文件名，需要完整 traceback 或终端输出；一张只截出错误码的截图通常不足以确定缺失文件。

便携默认日志：`%LOCALAPPDATA%\HRCWorkbench\startup.log` 和对应会话的 `p051-worker.log`。源码默认会话目录：项目下 `.local\p051-ui-runs`。当前应用会把部分 UI 异常只显示在页面上，因此日志里没有异常并不能证明没有发生错误。

## 实现依据

检查路径和规则来自本项目 `desktop/p051/src/p051_desktop/app.py` 的 `start_worker`、`portable.py` 的设置逻辑、`desktop/p051/portable/WorkbenchLauncher.cs`、`stage.py` / `finalize.py` 以及 `scripts/launch_s19b_kit.ps1`。本工具作为独立附件添加，不改变上述应用实现或既有发行包。

本机验证记录另见同包 `VALIDATION.zh-CN.md`。开发者可在源码根目录使用项目 Python 执行 `tools/diagnostics/test_diagnostics.py`，故障夹具和报告默认写入 `.local/diagnostic-tests`，不会破坏真实安装。

r2 补充：`Test-HRCWorkbench.ps1` 是不启动工作台的自检入口；`Trace-HRCStartup.py` 是 C4 分支按需使用的**实际 UI 启动取证入口**，需要已有可运行的界面 Python，不会由常规自检自动执行。不要把两者的用途混淆。
