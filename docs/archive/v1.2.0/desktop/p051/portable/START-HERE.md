# HRC Workbench v1.2.0 · Windows x64

1. 完整解压 ZIP，保留同级 app 文件夹，双击 HRC-Workbench.exe。先从首页“查看只读示例”体验，无需安装 Isaac。
2. 新建 CPU 会话前检查配置，点击“检查并启动”。需要结束时使用“安全停止”，等待保存与进程退出。
3. 界面右上“自检”提供快速检查与完整校验。若界面无法打开，双击同级 HRC-SelfCheck.cmd。完整自检需要 PowerShell 7；快速启动检查不需要它。
4. 查看“新版使用指南.txt”；排错时阅读“工作台排错与AI修复指南.txt”。完整报告包含具体文件、环境和日志检查结果。
5. 原生三维另需 Isaac Sim 6.1 与 PowerShell 7，选择纯 ASCII 的可写结果路径。CPU 和存档可使用中文路径。默认结果保存在 %LOCALAPPDATA%\HRCWorkbench\runs。

Extract the entire ZIP, keep app beside HRC-Workbench.exe, and open the read-only example. Use Check & start for a CPU session; Safe stop saves before exit. Diagnostics checks prerequisites and package integrity. If the window cannot open, run HRC-SelfCheck.cmd (PowerShell 7 required). See USER-GUIDE.txt. Native 3D additionally needs Isaac Sim 6.1 and PowerShell 7. This is an unsigned local build; validate the ZIP using its supplied SHA-256.
