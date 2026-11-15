@echo off
setlocal
set "HRC_DIAG_PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%HRC_DIAG_PWSH%" (
  echo PowerShell 7 was not found at "%HRC_DIAG_PWSH%".
  echo Install PowerShell 7, or run Test-HRCWorkbench.ps1 from your existing PowerShell 7.
  echo Windows PowerShell 5.1 is not supported. See the supplied Chinese troubleshooting guide.
  pause
  exit /b 3
)
if "%~1"=="" (
  "%HRC_DIAG_PWSH%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Diagnostics.ps1"
) else (
  "%HRC_DIAG_PWSH%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Test-HRCWorkbench.ps1" %*
)
set "HRC_DIAG_EXIT=%ERRORLEVEL%"
echo.
echo Diagnostic exit code: %HRC_DIAG_EXIT% (0=checks passed, 1=blocking issue, 2=needs review, 3=tool could not run/write report)
pause
exit /b %HRC_DIAG_EXIT%
