#requires -Version 7.0
<#
.SYNOPSIS
HRC 工作台离线自检。只诊断，不安装、修复或启动生产/Kit。
.EXAMPLE
& ./Test-HRCWorkbench.ps1 -Root 'C:/HRC/Workbench' -Backend CPU
#>
[CmdletBinding()]
param(
    [string]$Root,
    [ValidateSet('CPU', 'Isaac')][string]$Backend = 'CPU',
    [string]$RunDirectory,
    [string]$RunsDirectory,
    [string]$SettingsFile,
    [string]$ErrorText,
    [string]$OutputDirectory,
    [ValidateRange(5, 120)][int]$ProbeTimeoutSeconds = 40,
    [switch]$StaticOnly,
    [switch]$SkipIntegrity
)
$ErrorActionPreference = 'Stop'
$checks = [Collections.Generic.List[object]]::new()
$logEvidence = [Collections.Generic.List[object]]::new()
$started = [DateTimeOffset]::Now
$mode = 'unknown'
$appRoot = $null
$packageRoot = $null

function Add-Check($Id, $Status, $Summary, $Target, $Evidence, $Fix) {
    $checks.Add([ordered]@{ id=$Id; status=$Status; summary=$Summary; target=$Target; evidence=$Evidence; fix=$Fix })
    Write-Host "[$Status] $Id - $Summary"
}
function Quote-PS([string]$Text) { return "'" + $Text.Replace("'", "''") + "'" }
function Need-File($Id, $Path, $Fix) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Add-Check $Id PASS '文件存在' $Path $null $null
        return $true
    }
    Add-Check $Id FAIL '必需文件不存在' $Path '已检查实际绝对路径。' $Fix
    return $false
}
function Invoke-PythonProbe($Python, $Role) {
    # Reject truncated/non-PE files without asking Windows to load them (can display a loader dialog).
    try {
        $binary = [IO.File]::OpenRead($Python)
        try {
            if ($binary.Length -lt 64 -or $binary.ReadByte() -ne 77 -or $binary.ReadByte() -ne 90) {
                return @{ ok=$false; reason='INVALID_EXECUTABLE'; error='解释器不是完整 Windows PE 可执行文件。' }
            }
            $reader = [IO.BinaryReader]::new($binary, [Text.Encoding]::ASCII, $true)
            $binary.Position = 60
            $offset = $reader.ReadInt32()
            if ($offset -lt 64 -or $offset -gt $binary.Length - 24) {
                return @{ ok=$false; reason='INVALID_EXECUTABLE'; error='解释器 PE 文件头被截断或无效。' }
            }
            $binary.Position = $offset
            if ($reader.ReadUInt32() -ne 17744 -or $reader.ReadUInt16() -ne 34404) {
                return @{ ok=$false; reason='INVALID_EXECUTABLE'; error='解释器不是本项目要求的 Windows x64 PE 文件。' }
            }
        } finally { $binary.Dispose() }
    } catch { return @{ ok=$false; reason='EXECUTABLE_UNREADABLE'; error=$_.Exception.Message } }
    # Import and construct inputs only. No solve(), QApplication, worker or Kit launch.
    $code = @'
import sys, json, struct, traceback
from pathlib import Path
root, role = Path(sys.argv[1]), sys.argv[2]
sys.path[:0] = [str(root), str(root/'src'), str(root/'scripts'),
               str(root/'desktop/s19b/src'), str(root/'desktop/p051/src')]
out = dict(executable=sys.executable, version=sys.version, bits=struct.calcsize('P')*8, checks=[])
def check(name, action):
    try:
        detail = action()
        out['checks'].append(dict(name=name, ok=True, detail=detail))
    except Exception as e:
        out['checks'].append(dict(name=name, ok=False, error_type=type(e).__name__,
                                 error=str(e), filename=getattr(e, 'filename', None),
                                 traceback=traceback.format_exc()))
def version():
    if sys.version_info[:2] != (3, 12) or out['bits'] != 64:
        raise RuntimeError('This project requires Python 3.12 x64')
    return sys.version
check('python_version', version)
if role == 'cpu':
    def solver():
        import ortools
        from ortools.sat.python import cp_model
        cp_model.CpModel()
        return dict(version=ortools.__version__, path=ortools.__file__)
    check('ortools', solver)
    def template(name):
        from build_simulation_production import configuration
        value = configuration(products=1, variant=name)
        return dict(variant=name, products=len(value.products))
    for name in ('SR-W1', 'SR-W2'):
        check('template_' + name, lambda name=name: template(name))
else:
    def qt():
        import PySide6
        from PySide6 import QtCore, QtWidgets, QtWebEngineWidgets, QtWebChannel
        package = Path(PySide6.__file__).parent
        for name in ('QtWebEngineProcess.exe', 'plugins/platforms/qwindows.dll',
                     'resources/icudtl.dat', 'resources/qtwebengine_resources.pak'):
            path = package / name
            if not path.is_file():
                raise FileNotFoundError(2, 'Required Qt runtime resource is missing', str(path))
        return dict(version=PySide6.__version__, path=PySide6.__file__)
    check('qt_webengine', qt)
    def desktop():
        import p051_desktop.app as app
        if app.ROOT.resolve() != root.resolve():
            raise RuntimeError('Imported application root differs from selected root: ' + str(app.ROOT))
        return dict(module=app.__file__, root=str(app.ROOT))
    check('desktop_import', desktop)
print('HRC_DIAGNOSTIC_JSON=' + json.dumps(out, ensure_ascii=True))
'@
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Python
    $info.WorkingDirectory = $appRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($arg in @('-B', '-X', 'utf8', '-c', $code, $appRoot, $Role)) { $info.ArgumentList.Add($arg) }
    foreach ($key in @('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONEXE')) { [void]$info.Environment.Remove($key) }
    $info.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $outTask = $process.StandardOutput.ReadToEndAsync()
        $errTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($ProbeTimeoutSeconds * 1000)) {
            # Only the diagnostic child created above is stopped; never a workbench process.
            $process.Kill($true)
            $process.WaitForExit()
            return @{ ok=$false; reason='TIMEOUT'; stderr=$errTask.GetAwaiter().GetResult(); stdout=$outTask.GetAwaiter().GetResult() }
        }
        $stdout = $outTask.GetAwaiter().GetResult()
        $stderr = $errTask.GetAwaiter().GetResult()
        $line = @($stdout -split "`n" | Where-Object { $_.StartsWith('HRC_DIAGNOSTIC_JSON=') })
        if ($process.ExitCode -ne 0 -or $line.Count -ne 1) {
            return @{ ok=$false; reason='PROCESS_FAILED'; exit_code=$process.ExitCode; stdout=$stdout; stderr=$stderr }
        }
        return @{ ok=$true; data=($line[0].Substring(20) | ConvertFrom-Json -AsHashtable); stderr=$stderr }
    } catch {
        return @{ ok=$false; reason='PROCESS_START_OR_READ_FAILED'; error=$_.Exception.GetBaseException().Message }
    } finally { $process.Dispose() }
}
function Test-Python($Id, $Python, $Role, $Fix) {
    if (-not (Need-File "$Id.file" $Python $Fix)) { return }
    if ($StaticOnly) {
        Add-Check "$Id.probe" WARN '已跳过解释器和依赖的实际加载，不能认定运行环境正常' $Python $null '去掉 -StaticOnly 后复查。'
        return
    }
    Write-Host "正在实际加载 $Role 环境（最多 $ProbeTimeoutSeconds 秒）…"
    $result = Invoke-PythonProbe $Python $Role
    if (-not $result.ok) {
        Add-Check "$Id.launch" FAIL '解释器无法正常完成自检；文件存在不等于可运行' $Python $result $Fix
        return
    }
    foreach ($item in $result.data.checks) {
        $status = if ($item.ok) { 'PASS' } else { 'FAIL' }
        $summary = if ($item.ok) { "$($item.name) 实际加载通过" } else { "$($item.name) 加载失败：$($item.error)" }
        Add-Check "$Id.$($item.name)" $status $summary $Python $item $(if ($item.ok) { $null } else { $Fix })
    }
    if ($result.stderr) { Add-Check "$Id.stderr" INFO '解释器标准错误输出（不自动认定故障）' $Python $result.stderr $null }
}
function Test-PackageIntegrity {
    $manifest = Join-Path $packageRoot 'PACKAGE-SHA256.txt'
    if (-not (Need-File 'package.manifest' $manifest '使用完整官方 Windows ZIP 重新解压到新目录；不要把源码 ZIP 当作便携包。')) { return }
    if ($SkipIntegrity) {
        Add-Check 'package.integrity' WARN '已跳过随包逐文件 SHA-256 校验' $manifest $null '去掉 -SkipIntegrity 后复查。'
        return
    }
    Write-Host '正在核对便携包全部清单文件的 SHA-256…'
    $bad = [Collections.Generic.List[object]]::new()
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $safeParents = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $count = 0
    foreach ($line in [IO.File]::ReadLines($manifest)) {
        $count++
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            $bad.Add(@{ line=$count; reason='INVALID_MANIFEST_LINE' }); continue
        }
        $digest, $relative = $Matches[1], $Matches[2]
        $path = [IO.Path]::GetFullPath((Join-Path $packageRoot $relative))
        $prefix = $packageRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or
            -not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or -not $seen.Add($path)) {
            $bad.Add(@{ path=$relative; reason='UNSAFE_OR_DUPLICATE_PATH' }); continue
        }
        try {
            $cursor = $path
            while ($cursor -ne $packageRoot -and -not $safeParents.Contains($cursor)) {
                if ((Test-Path -LiteralPath $cursor) -and
                    ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                    throw 'REPARSE_POINT_NOT_VERIFIED'
                }
                [void]$safeParents.Add($cursor)
                $cursor = Split-Path -Parent $cursor
            }
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                $bad.Add(@{ path=$relative; reason='MISSING' }); continue
            }
            $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            if ($actual -ne $digest) { $bad.Add(@{ path=$relative; reason='SHA256_MISMATCH'; expected=$digest; actual=$actual }) }
        } catch { $bad.Add(@{ path=$relative; reason='READ_FAILED'; error=$_.Exception.Message }) }
    }
    if ($count -eq 0) { $bad.Add(@{ reason='EMPTY_MANIFEST' }) }
    # A truncated or substituted manifest must not look like a complete package audit.
    foreach ($required in @('HRC-Workbench.exe', 'app/.venv/Scripts/python.exe', 'app/portable-launch.py',
        'app/scripts/run_s19b_prototype.py', 'app/desktop/p051/src/p051_desktop/app.py', 'app/desktop/p051/web/dist/index.html')) {
        if (-not $seen.Contains([IO.Path]::GetFullPath((Join-Path $packageRoot $required)))) {
            $bad.Add(@{ path=$required; reason='REQUIRED_ENTRY_NOT_LISTED' })
        }
    }
    $evidence = @{ checked_entries=$count; differences=@($bad.ToArray()); trust='仅与随包清单比对；不证明清单来源可信。' }
    if ($bad.Count) {
        Add-Check 'package.integrity' FAIL "清单校验发现 $($bad.Count) 项问题；完整路径见报告 evidence" $manifest $evidence '保留原运行记录；从可信发行页重新下载完整 Windows ZIP，解压到新目录。不要单独替换 DLL 或 python.exe。'
    } else { Add-Check 'package.integrity' PASS "随包清单 $count 项 SHA-256 一致" $manifest $evidence $null }
}
function Test-WritableDirectory($Directory) {
    $probe = $null
    try {
        $target = [IO.Path]::GetFullPath($Directory)
        if (Test-Path -LiteralPath $target -PathType Leaf) { throw '该路径是文件，不是目录。' }
        $parent = $target
        while (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            $next = Split-Path -Parent $parent
            if (-not $next -or $next -eq $parent) { throw '找不到可访问的父目录。' }
            $parent = $next
        }
        $probe = Join-Path $parent ('.hrc-diagnostic-' + [guid]::NewGuid().ToString('N') + '.tmp')
        $stream = [IO.File]::Open($probe, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
        Remove-Item -LiteralPath $probe
        $probe = $null
        Add-Check 'runs.writable' PASS '结果目录或其现有父目录可写（已创建并删除临时探针）' $target @{ tested_parent=$parent; target_exists=(Test-Path -LiteralPath $target) } $null
    } catch {
        Add-Check 'runs.writable' FAIL '结果路径不可用' $Directory $_.Exception.Message '在便携设置中选择当前用户可写的结果目录；源码版检查 .local/p051-ui-runs 的访问权限。不要用提权运行掩盖路径问题。'
    } finally { if ($probe -and (Test-Path -LiteralPath $probe)) { Remove-Item -LiteralPath $probe -ErrorAction SilentlyContinue } }
}
function Inspect-ErrorText($Text, $Origin) {
    $rules = @(
        @('winerror2', '(?i)WinError\s*2\b|FileNotFoundError|系统找不到指定的文件', '文件或进程路径找不到', '先处理报告中 FAIL 的确切路径。源码版重点检查根目录 .venv；便携版检查完整性。若路径检查通过，保留完整 traceback，不能只凭错误码确定缺失文件。'),
        @('module', 'ModuleNotFoundError|No module named', '依赖模块缺失线索', '按失败环境重建锁定依赖：源码 CPU 在根目录 uv sync --locked；界面 uv sync --locked --project desktop/p051；便携版重新完整解压。具体模块名见日志。'),
        @('dll', 'DLL load failed|WinError\s*(126|193)\b|0xc000007b', 'DLL 或架构不匹配线索', '核对 Python 3.12 x64 和包完整性；不要从第三方网站单独下载 DLL。完整重建对应环境后复查，保留模块名和错误码。'),
        @('permission', 'PermissionError|WinError\s*5\b|Access is denied|拒绝访问', '权限或文件占用线索', '换到当前用户可写目录并复查；查看 Windows 安全中心保护历史。仅凭此错误不能认定杀毒软件删除了文件。'),
        @('kit_path', 'ASCII|CAPTURE_INCOMPLETE', 'Kit 路径或截图失败线索', 'Isaac 模式使用纯 ASCII 可写结果路径，并检查本次原生日志；CAPTURE_INCOMPLETE 也可能有其他渲染原因。'),
        @('completion', 'WORKER_.*(UNCONFIRMED|MISSING)|Traceback \(most recent call last\)', '后台异常或保存/退出未确认', '读取同一次会话日志末尾的完整异常和退出回执；不要把它记为正常保存，也不要删除会话后反复重试。')
    )
    foreach ($rule in $rules) {
        if ($Text -match $rule[1]) {
            Add-Check "log.$($rule[0])" WARN "$($rule[2])；日志可能属于历史运行，尚非当前根因" $Origin $null $rule[3]
        }
    }
}

try {
    if (-not $IsWindows -or -not [Environment]::Is64BitOperatingSystem) {
        Add-Check 'host.platform' FAIL '本工具针对 Windows x64 工作台' $null $PSVersionTable.OS '请在实际报错的 Windows 电脑上使用 PowerShell 7 运行。'
    } else { Add-Check 'host.platform' PASS 'Windows 64 位系统，PowerShell 7' $PSHOME $PSVersionTable.PSVersion.ToString() $null }
    if (-not $Root) {
        $candidates = @((Get-Location).Path, (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)), $PSScriptRoot)
        $Root = $candidates | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_ 'HRC-Workbench.exe')) -or
            (Test-Path -LiteralPath (Join-Path $_ 'desktop/p051/src/p051_desktop/app.py'))
        } | Select-Object -First 1
        if (-not $Root) { throw '无法自动定位项目。请用 -Root 指定含 HRC-Workbench.exe 的目录或源码根目录。' }
    }
    $Root = [IO.Path]::GetFullPath($Root)
    if (Test-Path -LiteralPath $Root -PathType Leaf) {
        if ([IO.Path]::GetFileName($Root) -ieq 'HRC-Workbench.exe') { $Root = Split-Path -Parent $Root }
        else { throw '-Root 必须是项目目录或 HRC-Workbench.exe 的路径，不是 ZIP 或其他文件。' }
    }
    if ((Test-Path -LiteralPath (Join-Path $Root 'HRC-Workbench.exe')) -or
        (Test-Path -LiteralPath (Join-Path $Root 'app/portable-launch.py'))) {
        $mode = 'portable'; $packageRoot = $Root; $appRoot = Join-Path $Root 'app'
    } elseif (Test-Path -LiteralPath (Join-Path $Root 'portable-launch.py')) {
        $mode = 'portable'; $packageRoot = Split-Path -Parent $Root; $appRoot = $Root
    } elseif (Test-Path -LiteralPath (Join-Path $Root 'desktop/p051/src/p051_desktop/app.py')) {
        $mode = 'source'; $appRoot = $Root
    } else { throw '所选目录不是可识别的项目根目录；请检查是否选到了 ZIP 外层目录或只复制了部分源码。' }
    Add-Check 'layout' PASS "已识别 $mode 布局；后端 $Backend" $appRoot $null $null
    $sourceFix = "在源码根目录运行：Set-Location -LiteralPath $(Quote-PS $appRoot)；uv sync --locked（项目要求 uv 0.12.3、Python 3.12）。若虚拟环境被搬动，先备份并将该 .venv 改名，再用锁文件重新创建。"
    $uiFix = "在源码根目录运行：Set-Location -LiteralPath $(Quote-PS $appRoot)；uv sync --locked --project desktop/p051。若环境被搬动，先备份并改名 desktop/p051/.venv，再重新创建。"
    $restoreFix = '保留会话数据，将完整 Windows 便携 ZIP 解压到新目录，保持 EXE 与 app 同级；不要直接在 ZIP 内运行或只复制 EXE。'
    $fileFix = if ($mode -eq 'portable') { $restoreFix } else { '从同一版本的完整源码包恢复该文件；不要混用不同版本。' }
    if ($mode -eq 'source') {
        foreach ($name in @('scripts/run_p051_workbench.py', 'pyproject.toml', 'uv.lock', 'desktop/p051/pyproject.toml', 'desktop/p051/uv.lock')) {
            [void](Need-File "source.$name" (Join-Path $appRoot $name) $fileFix)
        }
    }
    foreach ($name in @('scripts/run_s19b_prototype.py', 'scripts/build_simulation_production.py',
        'scripts/build_production_contracts.py', 'scripts/build_logistics_contracts.py', 'scripts/build_building_contracts.py',
        'desktop/p051/src/p051_desktop/app.py', 'desktop/s19b/src/s19b_desktop/control.py',
        'src/adaptive_hrc_scheduling/__init__.py', 'docs/model/steel_process.tsv', 'docs/model/steel_edges.tsv',
        'examples/building_contracts/configuration.json')) {
        [void](Need-File "resource.$name" (Join-Path $appRoot $name) $fileFix)
    }
    $webFix = if ($mode -eq 'portable') { $restoreFix } else { '在源码根目录执行 npm.cmd --prefix desktop/p051/web ci，然后 npm.cmd --prefix desktop/p051/web run build。' }
    $webRoot = Join-Path $appRoot 'desktop/p051/web/dist'
    if (Need-File 'web.index' (Join-Path $webRoot 'index.html') $webFix) {
        $html = [IO.File]::ReadAllText((Join-Path $webRoot 'index.html'))
        foreach ($match in [regex]::Matches($html, '(?:src|href)=["'']([^"'']+\.(?:js|css))(?:\?[^"'']*)?["'']')) {
            $asset = $match.Groups[1].Value
            if ($asset -notmatch '^(https?:|data:|qrc:)') { [void](Need-File "web.asset.$asset" (Join-Path $webRoot $asset.TrimStart('/')) $webFix) }
        }
    }
    if ($mode -eq 'portable') {
        [void](Need-File 'package.launcher' (Join-Path $packageRoot 'HRC-Workbench.exe') $restoreFix)
        [void](Need-File 'package.bootstrap' (Join-Path $appRoot 'portable-launch.py') $restoreFix)
        Test-PackageIntegrity
    }
    $cpuPython = Join-Path $appRoot '.venv/Scripts/python.exe'
    $uiPython = if ($mode -eq 'portable') { $cpuPython } else { Join-Path $appRoot 'desktop/p051/.venv/Scripts/python.exe' }
    if ($Backend -eq 'CPU' -or $mode -eq 'portable') {
        Test-Python 'cpu.python' $cpuPython 'cpu' $(if ($mode -eq 'portable') { $restoreFix } else { $sourceFix })
    } else { Add-Check 'cpu.not_selected' INFO '源码版本次选择 Isaac，不把独立 CPU 环境缺失认定为 Kit 启动故障' $cpuPython $null $null }
    Test-Python 'ui.python' $uiPython 'ui' $(if ($mode -eq 'portable') { $restoreFix } else { $uiFix })
    $localData = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'HRCWorkbench' } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) 'AppData/Local/HRCWorkbench' }
    $settings = @{}
    if (-not $SettingsFile) { $SettingsFile = Join-Path $localData 'settings.json' }
    if ($mode -eq 'portable' -and (Test-Path -LiteralPath $SettingsFile)) {
        try {
            $settings = Get-Content -LiteralPath $SettingsFile -Raw | ConvertFrom-Json -AsHashtable
            if ($settings -isnot [Collections.IDictionary]) { throw '设置必须是 JSON 对象。' }
            foreach ($key in @('runs', 'isaac')) {
                if ($null -ne $settings[$key] -and $settings[$key] -isnot [string]) { throw "$key 必须是字符串。" }
            }
            Add-Check 'settings' PASS '设置 JSON 可读取' $SettingsFile $settings $null
        } catch {
            $settings = @{}
            Add-Check 'settings' FAIL '便携设置格式错误' $SettingsFile $_.Exception.Message '退出工作台，备份 settings.json 后改名；重新启动并在便携设置中配置路径。不要删除 runs 会话。'
        }
    }
    if (-not $RunsDirectory) {
        $RunsDirectory = if ($mode -eq 'source') { Join-Path $appRoot '.local/p051-ui-runs' }
        elseif ($settings.runs) { $settings.runs } else { Join-Path $localData 'runs' }
    }
    if (-not [IO.Path]::IsPathRooted($RunsDirectory)) { $RunsDirectory = Join-Path $appRoot $RunsDirectory }
    $RunsDirectory = [IO.Path]::GetFullPath($RunsDirectory)
    Test-WritableDirectory $RunsDirectory
    if ($Backend -eq 'Isaac') {
        $isaac = if ($mode -eq 'source') { 'D:/Dev/tools/isaac-sim-6.1' } else { $settings.isaac }
        $pwsh = if ($mode -eq 'source') { 'C:/Program Files/PowerShell/7/pwsh.exe' } else { Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe' }
        [void](Need-File 'isaac.powershell' $pwsh '工作台当前使用固定的 PowerShell 7 安装路径。请安装到此路径；仅在 PATH 中存在其他 pwsh 不满足当前启动代码。CPU 模式不依赖 Kit。')
        [void](Need-File 'isaac.launch_script' (Join-Path $appRoot 'scripts/launch_s19b_kit.ps1') $fileFix)
        if (-not $isaac) { Add-Check 'isaac.root' FAIL '尚未选择 Isaac 根目录' $null $null '在便携设置中选择包含 python.bat 与 VERSION 的 Isaac Sim 6.1 根目录。' }
        else {
            if (-not [IO.Path]::IsPathRooted($isaac)) { $isaac = Join-Path $appRoot $isaac }
            [void](Need-File 'isaac.python_bat' (Join-Path $isaac 'python.bat') '选择完整 Isaac Sim 6.1 安装根目录；源码版目前固定使用 D:/Dev/tools/isaac-sim-6.1。')
            if (Need-File 'isaac.version_file' (Join-Path $isaac 'VERSION') '修复或选择完整 Isaac 安装目录。') {
                $version = (Get-Content -LiteralPath (Join-Path $isaac 'VERSION') -Raw).Trim()
                Add-Check 'isaac.version' $(if ($version.StartsWith('6.1.')) { 'PASS' } else { 'FAIL' }) 'Isaac 版本需为本项目要求的 6.1 系列' $isaac $version '使用与本项目匹配的完整 Isaac Sim 6.1 安装。'
            }
        }
        if ($RunsDirectory -match '[^\x00-\x7f]') { Add-Check 'isaac.ascii_runs' FAIL 'Isaac 结果路径含非 ASCII 字符' $RunsDirectory $null '在便携设置中改为纯 ASCII 可写路径，例如 C:/HRC/runs。源码版需将项目放到纯 ASCII 路径。' }
        Add-Check 'isaac.scope' WARN '仅检查 Kit 启动前条件，未启动 Isaac、检测 GPU 或验证渲染' $isaac $null '这些检查通过后，仍需在目标电脑实际运行 Isaac 并核对原生日志。'
    } else { Add-Check 'isaac.not_required' INFO '本次为 CPU 模式，不将未安装 Isaac/Kit 判为故障' $null $null $null }
    if ($ErrorText) {
        $logEvidence.Add(@{ source='用户输入'; text=$ErrorText })
        Add-Check 'error.reported' WARN '已记录用户报告的错误；即使静态检查通过，也不等于该错误已解决' '用户输入' $ErrorText '结合确切失败路径及本次会话日志排查；没有命中的已知规则时保留 UNKNOWN，不自动推断根因。'
        Inspect-ErrorText $ErrorText '用户输入'
    }
    $logs = [Collections.Generic.List[string]]::new()
    if ($mode -eq 'portable' -and (Test-Path -LiteralPath (Join-Path $localData 'startup.log'))) { $logs.Add((Join-Path $localData 'startup.log')) }
    if (-not $RunDirectory -and (Test-Path -LiteralPath $RunsDirectory -PathType Container)) {
        $latest = Get-ChildItem -LiteralPath $RunsDirectory -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) { $RunDirectory = $latest.FullName }
    }
    if ($RunDirectory) {
        $RunDirectory = [IO.Path]::GetFullPath($RunDirectory)
        if (-not (Test-Path -LiteralPath $RunDirectory -PathType Container)) {
            Add-Check 'logs.run_directory' WARN '指定会话目录不存在，无法读取本次运行日志' $RunDirectory $null '用 -RunDirectory 指向实际失败会话目录。'
        } else {
            foreach ($name in @('p051-worker.log', 'worker-native-exit.json', 'worker-launch.json', 'report.json', 'session/final-commit.json', 'last-error.json')) {
                $path = Join-Path $RunDirectory $name
                if (Test-Path -LiteralPath $path -PathType Leaf) { $logs.Add($path) }
            }
        }
    }
    foreach ($path in $logs) {
        try {
            $tail = (Get-Content -LiteralPath $path -Tail 200) -join "`n"
            if ($tail.Length -gt 24000) { $tail = $tail.Substring($tail.Length - 24000) }
            $logEvidence.Add(@{ source=$path; modified=(Get-Item -LiteralPath $path).LastWriteTime.ToString('o'); text=$tail })
            Inspect-ErrorText $tail $path
            if ([IO.Path]::GetExtension($path) -eq '.json') {
                try {
                    $receipt = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -AsHashtable
                    if (($receipt.ContainsKey('returncode') -and $receipt.returncode -ne 0) -or
                        ($receipt.ContainsKey('status') -and $receipt.status -in @('FAIL', 'ERROR')) -or
                        ($receipt.ContainsKey('closed') -and $receipt.closed -eq $false)) {
                        Add-Check 'logs.receipt' WARN '会话回执包含非零退出、失败或未关闭状态；需与本次运行身份核对' $path $receipt '检查同目录工作进程日志及 run_id/request_id；活动会话未关闭不一定是故障。不要把旧回执当作本次成功。'
                    }
                } catch { Add-Check 'logs.json' WARN '回执 JSON 不能解析，可能不完整或仍在写入' $path $_.Exception.Message '在会话安全结束后复查，并保留原文件。' }
            }
        } catch { Add-Check 'logs.read' WARN '日志读取失败' $path $_.Exception.Message '检查日志路径、占用和读取权限。' }
    }
    if (-not $logs.Count) { Add-Check 'logs.none' INFO '没有找到可读取的运行日志；不因此判定启动正常' $RunDirectory $null '若仍报错，提供 -RunDirectory 和 -ErrorText，保留完整 traceback。' }
} catch {
    Add-Check 'diagnostic.incomplete' FAIL '自检未能完成；以下错误不自动等同于应用根因' $Root $_.Exception.Message '核对参数、路径和读取权限；将本报告交给维护者。'
}

$failures = @($checks | Where-Object status -eq 'FAIL')
$warnings = @($checks | Where-Object status -eq 'WARN')
$exitCode = if ($failures.Count) { 1 } elseif ($warnings.Count) { 2 } else { 0 }
$conclusion = if ($failures.Count) { '发现明确阻断项：先按 FAIL 中的具体路径和建议处理，再运行自检。' }
elseif ($warnings.Count) { '未发现已检查项中的明确阻断，但有待核查线索或未执行项目；不能据此宣布故障已解决。' }
else { '已执行的启动前检查通过。若实际仍报错，根因尚未定位，请提供失败会话完整日志；本结果不代表完整生产或 GUI 验收。' }
$report = [ordered]@{
    format='HRC-DIAGNOSTIC-1'; tool_version='1.0.0'; started_at=$started.ToString('o'); completed_at=[DateTimeOffset]::Now.ToString('o')
    root=$Root; app_root=$appRoot; mode=$mode; backend=$Backend; runs_directory=$RunsDirectory; run_directory=$RunDirectory
    powershell=$PSVersionTable.PSVersion.ToString(); static_only=[bool]$StaticOnly; skip_integrity=[bool]$SkipIntegrity
    exit_code=$exitCode; conclusion=$conclusion; failures=$failures.Count; warnings=$warnings.Count
    checks=@($checks.ToArray()); logs=@($logEvidence.ToArray())
    limits=@('不自动修复，不联网，不启动工作台、生产仿真或 Isaac；仅创建报告和短暂写权限探针。',
        '日志线索可能来自历史会话，不当作当前故障的确定根因。', '校验清单只验证一致性，不验证发行来源；未覆盖所有未知错误。')
}
try {
    if (-not $OutputDirectory) { $OutputDirectory = Join-Path ([IO.Path]::GetTempPath()) 'HRC-Diagnostics' }
    $OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
    $reportDir = Join-Path $OutputDirectory ($started.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [void][IO.Directory]::CreateDirectory($reportDir)
    $jsonPath = Join-Path $reportDir 'diagnosis.json'
    $txtPath = Join-Path $reportDir '诊断报告.txt'
    $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $jsonPath -Encoding utf8
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add("HRC 工作台自检报告`n时间：$($report.completed_at)`n目录：$Root`n布局：$mode；后端：$Backend`n退出码：$exitCode`n$conclusion`n")
    foreach ($check in @($failures) + @($warnings) + @($checks | Where-Object { $_.status -notin @('FAIL','WARN') })) {
        $lines.Add("[$($check.status)] $($check.id)：$($check.summary)`n位置：$($check.target)")
        if ($null -ne $check.evidence) { $lines.Add('证据：' + ($check.evidence | ConvertTo-Json -Depth 20)) }
        if ($check.fix) { $lines.Add('处理：' + $check.fix) }
        $lines.Add('')
    }
    $lines.Add("日志末尾（可能来自历史运行；分享前检查本机路径及业务内容）：`n" + ($report.logs | ConvertTo-Json -Depth 8))
    $lines.Add($report.limits -join "`n")
    $lines | Set-Content -LiteralPath $txtPath -Encoding utf8
    Write-Host "`n$conclusion"
    foreach ($issue in $failures) { Write-Host "`n位置：$($issue.target)`n处理：$($issue.fix)" }
    Write-Host "`n文本报告：$txtPath`nJSON 报告：$jsonPath"
} catch { Write-Host "无法写入报告：$($_.Exception.Message)`n请选择可写的 -OutputDirectory。"; exit 3 }
exit $exitCode
