param(
    [Parameter(Mandatory)][string]$BuildDirectory,
    [string]$ArchiveDirectory,
    [string]$CacheDirectory = $BuildDirectory,
    [switch]$StageOnly
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 is required' }
if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'An x64 Windows build host is required'
}
if (-not $StageOnly -and -not $ArchiveDirectory) { throw 'Supply a verified example session directory' }

$project = (Resolve-Path -LiteralPath "$PSScriptRoot/../../..").Path
$build = [IO.Path]::GetFullPath($BuildDirectory)
$cache = [IO.Path]::GetFullPath($CacheDirectory)
$destination = Join-Path $build 'HRC-Workbench-Windows-x64'
if (Test-Path -LiteralPath $destination) { throw 'Use a fresh build directory to avoid mixing builds' }
$application = Join-Path $destination 'app'
$runtime = Join-Path $application '.venv/Scripts'
$web = Join-Path $build 'web-build'
$env:UV_CACHE_DIR = Join-Path $cache 'uv-cache'
$env:npm_config_cache = Join-Path $cache 'npm-cache'
New-Item -ItemType Directory -Force $runtime, $web | Out-Null

Push-Location -LiteralPath $project
try {
    uv python install 3.12.13 --install-dir "$cache/python-build" --no-bin
    $python = Join-Path $cache 'python-build/cpython-3.12.13-windows-x86_64-none'
    uv export --locked --project desktop/p051 --no-emit-project --output-file "$build/qt.txt" | Out-Null
    uv export --locked --only-group reference --output-file "$build/reference.txt" | Out-Null
    uv pip install --target "$runtime/Lib/site-packages" --require-hashes --no-deps --link-mode copy `
        --python "$python/python.exe" -r "$build/qt.txt" -r "$build/reference.txt"

    & "$python/python.exe" "$PSScriptRoot/stage.py" $project $destination $python $web
    & "$runtime/python.exe" -B -X utf8 -c 'import p051_desktop.app; from build_simulation_production import configuration; from ortools.sat.python import cp_model; cp_model.CpModel(); [configuration(products=1, variant=name) for name in ("SR-W1", "SR-W2")]'

    Push-Location -LiteralPath $web
    try {
        npm.cmd ci --no-audit --no-fund
        npm.cmd test
        npm.cmd run build
    } finally { Pop-Location }
    Copy-Item -LiteralPath "$web/dist" -Destination "$application/desktop/p051/web" -Recurse
    & "$python/python.exe" "$PSScriptRoot/stage.py" --web-notices $web $destination

    $compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    $launcher = Join-Path $PSScriptRoot 'WorkbenchLauncher.cs'
    $exe = Join-Path $destination 'HRC-Workbench.exe'
    & $compiler /nologo /target:winexe /platform:x64 /optimize+ `
        /reference:System.Windows.Forms.dll "/out:$exe" $launcher
    if ($StageOnly) { Write-Output $destination; return }

    & "$python/python.exe" "$PSScriptRoot/finalize.py" $destination $ArchiveDirectory
} finally { Pop-Location }
