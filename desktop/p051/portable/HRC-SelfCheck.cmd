@echo off
setlocal
call "%~dp0app\tools\diagnostics\Run-Diagnostics.cmd" -Root "%~dp0." -Backend CPU
exit /b %ERRORLEVEL%
