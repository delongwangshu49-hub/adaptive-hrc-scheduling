param(
    [Parameter(Mandatory = $true)][string]$IsaacRoot,
    [Parameter(Mandatory = $true)][string]$RequestFile
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 is required' }
$s19bRoot = Split-Path -Parent $PSScriptRoot
$s19bPython = Join-Path (Resolve-Path -LiteralPath $IsaacRoot).Path 'python.bat'
if (-not (Test-Path -LiteralPath $s19bPython -PathType Leaf)) { throw 'Isaac python.bat missing' }
$s19bRequest = (Resolve-Path -LiteralPath $RequestFile).Path
foreach ($s19bEnvName in @('PYTHONEXE', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')) {
    Remove-Item -LiteralPath "Env:$s19bEnvName" -ErrorAction SilentlyContinue
}
Set-Location -LiteralPath $s19bRoot
$s19bOutput = Split-Path -Parent $s19bRequest
$s19bLaunchRecord = Get-Content -LiteralPath $s19bRequest -Raw | ConvertFrom-Json
$s19bLaunchId = [guid]::NewGuid().ToString('N')
$s19bRequestSha = (Get-FileHash -LiteralPath $s19bRequest -Algorithm SHA256).Hash.ToLowerInvariant()
$s19bMarker = @{
    format = 'S19B-NATIVE-LAUNCH-1'
    run_id = $s19bLaunchRecord.run_id
    request_id = $s19bLaunchRecord.request_id
    launch_id = $s19bLaunchId
    request_sha256 = $s19bRequestSha
}
$s19bMarkerPath = Join-Path $s19bOutput 'worker-launch.json'
$s19bMarkerTemp = "$s19bMarkerPath.$s19bLaunchId.tmp"
try {
    [IO.File]::WriteAllText($s19bMarkerTemp, ($s19bMarker | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $s19bMarkerTemp -Destination $s19bMarkerPath -Force
} finally {
    Remove-Item -LiteralPath $s19bMarkerTemp -ErrorAction SilentlyContinue
}
& $s19bPython -u (Join-Path $PSScriptRoot 'supervise_s19b.py') --request $s19bRequest --launch-id $s19bLaunchId
$s19bLauncherCode = $LASTEXITCODE
if ($s19bLauncherCode -ne 0) { exit $s19bLauncherCode }
# The vendor batch wrapper can map a Windows native exception to exit 0.
# Bind the actual native child's result to this exact launch, including a fresh
# token so an earlier run's receipt cannot satisfy a zero-returning wrapper.
$s19bNative = Get-Content -LiteralPath (Join-Path $s19bOutput 'worker-native-exit.json') -Raw | ConvertFrom-Json
if ($s19bNative.format -cne 'S19B-NATIVE-EXIT-1' -or
    $s19bNative.launch_id -cne $s19bLaunchId -or
    $s19bNative.request_sha256 -cne $s19bRequestSha -or
    $s19bNative.run_id -cne $s19bLaunchRecord.run_id -or
    $s19bNative.request_id -cne $s19bLaunchRecord.request_id -or
    $s19bNative.state -cne 'EXITED' -or
    -not ($s19bNative.pid -is [int] -or $s19bNative.pid -is [long]) -or
    $s19bNative.pid -le 0 -or
    -not ($s19bNative.returncode -is [int] -or $s19bNative.returncode -is [long]) -or
    $s19bNative.returncode -ne 0) {
    throw 'WORKER_NATIVE_EXIT_UNCONFIRMED'
}
if (-not (Test-Path -LiteralPath (Join-Path $s19bOutput 'report.json') -PathType Leaf)) {
    Write-Error 'WORKER_COMPLETION_MISSING: launcher returned 0 without report.json'
    exit 1
}
$s19bReport = Get-Content -LiteralPath (Join-Path $s19bOutput 'report.json') -Raw | ConvertFrom-Json
if ($s19bReport.closed -isnot [bool] -or $s19bReport.closed -ne $true -or
    $s19bReport.status -cne 'PASS' -or
    $s19bReport.run_id -cne $s19bLaunchRecord.run_id -or
    $s19bReport.request_id -cne $s19bLaunchRecord.request_id) {
    throw 'WORKER_CLOSE_UNCONFIRMED'
}
if ($s19bLaunchRecord.session -and -not (Test-Path -LiteralPath (Join-Path $s19bOutput 'session/final-commit.json') -PathType Leaf)) {
    Write-Error 'WORKER_COMPLETION_MISSING: session has no final-commit.json'
    exit 1
}
exit $s19bLauncherCode
