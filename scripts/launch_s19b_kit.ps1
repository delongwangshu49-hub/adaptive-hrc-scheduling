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
& $s19bPython -u (Join-Path $PSScriptRoot 'run_s19b_prototype.py') --request $s19bRequest
exit $LASTEXITCODE
