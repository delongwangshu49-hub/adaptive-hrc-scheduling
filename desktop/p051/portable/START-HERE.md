# HRC Workbench · Windows x64

1. 将 ZIP 完整解压到较短的本地路径，双击 `HRC-Workbench.exe`。保留旁边的 `app` 目录。Windows x64 需有系统组件 .NET Framework 4.x。CPU 模式随包提供 Python、Qt、甘特资源和调度依赖。
2. 打开 **启动配置**。默认可直接用 CPU 启动一个 SR-W1 示例。初次完整排程及独立甘特核验可能需要等待。会话自动写到 `%LOCALAPPDATA%\HRCWorkbench\runs`。要结束活动会话，使用 **安全停止** 并等待进程退出。
3. 在 **启动配置 → 便携设置与示例** 中更改结果目录，或打开随包的只读 CPU 示例存档。**打开会话** 可重新打开自己的运行目录。CPU 和存档只提供甘特及相关数据，没有 Isaac 原生画面。示例存档可能显示旧帧状态，这是历史记录。
4. 需要 3D 时，先自行安装 Isaac Sim 6.1 系列与 PowerShell 7。在 **便携设置与示例 → 选择 Isaac** 中选择带 `python.bat` 与 `VERSION` 的安装根目录。为 Kit 选择纯 ASCII 的可写结果路径，例如 `C:\HRC\runs`，再选择 **Isaac / Kit**。本机实测中文结果路径会导致 Kit 原生截图失败。原生视口取决于 Isaac 版本、驱动和机器环境。
5. 启动失败时查看 `%LOCALAPPDATA%\HRCWorkbench\startup.log`，运行失败时查看对应运行目录中的 `p051-worker.log`。工作台为未签名的本地构建，可用交付时提供的 SHA-256 核对 ZIP。

1. Extract the entire ZIP to a short local path and double-click `HRC-Workbench.exe`. Keep the adjacent `app` folder. Windows x64 needs its .NET Framework 4.x component. The CPU mode includes Python, Qt, Gantt assets and the scheduler.
2. Open **Run setup** and start the default one-product SR-W1 CPU example. The initial schedule and independent Gantt audit take time. Sessions are written to `%LOCALAPPDATA%\HRCWorkbench\runs`. Use **Safe stop** and wait for the worker to exit.
3. Use **Run setup → Portable setup & example** to change the results folder or open the bundled read-only CPU example. Use **Open saved session** to reopen your own results. CPU and archive modes provide Gantt data. Historical frames may be marked stale.
4. For native 3D, install Isaac Sim 6.1 and PowerShell 7 separately. Select the Isaac installation folder containing `python.bat` and `VERSION`. Choose a writable ASCII-only results path such as `C:\HRC\runs`, then choose **Isaac / Kit**. A results path containing Chinese characters caused native capture to fail in local testing. The native viewport depends on your version, driver and host.
5. Startup diagnostics are in `%LOCALAPPDATA%\HRCWorkbench\startup.log`. Worker diagnostics are in the run's `p051-worker.log`. This local build is unsigned. Compare the ZIP against the supplied SHA-256 before use.
