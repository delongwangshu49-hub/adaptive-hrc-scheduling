#requires -Version 7.0
$ErrorActionPreference = 'Stop'
if ([Console]::IsInputRedirected) { [Console]::InputEncoding = [Text.UTF8Encoding]::new($false) }
Write-Host 'HRC 工作台自检：不会启动生产或自动修改安装。'
$selectedRoot = (Read-Host '请输入/粘贴项目目录（含 HRC-Workbench.exe 的文件夹，或源码根目录）').Trim().Trim('"')
if (-not $selectedRoot) { Write-Host '未指定目录。'; exit 3 }
$selectedBackend = Read-Host '报错时选择的后端：CPU 或 Isaac（直接回车为 CPU）'
if (-not $selectedBackend) { $selectedBackend = 'CPU' }
if ($selectedBackend -notin @('CPU', 'Isaac')) { Write-Host '后端只能为 CPU 或 Isaac。'; exit 3 }
$reportedError = Read-Host '可选：粘贴报错文字（没有则直接回车）'
$selectedRun = (Read-Host '可选：本次失败会话目录（没有则直接回车）').Trim().Trim('"')
& (Join-Path $PSScriptRoot 'Test-HRCWorkbench.ps1') -Root $selectedRoot -Backend $selectedBackend -ErrorText $reportedError -RunDirectory $selectedRun
exit $LASTEXITCODE
