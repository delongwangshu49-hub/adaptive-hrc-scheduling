param()
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 is required' }
$s19bRoot = Split-Path -Parent $PSScriptRoot
$s19bPython = Join-Path $s19bRoot 'desktop/s19b/.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $s19bPython -PathType Leaf)) {
    throw 'Prepare the isolated desktop environment using desktop/s19b/README.md first.'
}
# Suppress the venv launcher's console without suppressing the interactive Qt window.
$s19bStart = [System.Diagnostics.ProcessStartInfo]::new()
$s19bStart.FileName = $s19bPython
$s19bStart.ArgumentList.Add('-m')
$s19bStart.ArgumentList.Add('s19b_desktop.app')
$s19bStart.WorkingDirectory = $s19bRoot
$s19bStart.UseShellExecute = $false
$s19bStart.CreateNoWindow = $true
$s19bStart.RedirectStandardOutput = $true
$s19bStart.RedirectStandardError = $true
$s19bProcess = [System.Diagnostics.Process]::Start($s19bStart)
$s19bProcess.BeginOutputReadLine()
$s19bProcess.BeginErrorReadLine()
$s19bProcess
