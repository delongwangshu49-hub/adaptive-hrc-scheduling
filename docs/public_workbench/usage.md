# P05 Windows工作台使用与构建

仓库根目录先按[README](../../README.md#quickstart)准备固定CPU环境，再安装独立桌面依赖：

```powershell
uv sync --locked --project desktop/p051
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py --help
& ./desktop/p051/.venv/Scripts/python.exe ./scripts/run_p051_workbench.py
```

无目录时从新会话配置开始；保存目录用`--directory <目录>`只读打开，有意操作活动会话才用`--writable`。不能复用旧输出目录或拼接run。Kit启动适配默认D:/Dev/tools/isaac-sim-6.1及PowerShell7，继承既有独立包装器；其他安装布局需适配。帮助检查不打开窗口，不代表真实Qt/Kit已重验。

普通/急单和人员事件经预览、确认及共享契约提交，SUBMITTED/ACCEPTED/APPLIED不等于订单完成。实际、当前未来计划、旧版/阻塞与未知状态分开，陈旧时禁写，关闭活动会话须安全停止并等待原进程退出。手动REST禁用且标明未实现，自动排程休息保留。

受测Web资产随包提供；需重建时在独立Node/npm环境：

```powershell
cd desktop/p051/web
npm ci
npm test
npm run build
```

Web测试验证模型/甘特逻辑，build不替代原生视口、持续4Hz或负责人操作。Qt依赖见[pyproject](../../desktop/p051/pyproject.toml)，原生宿主见[历史工作台](../../desktop/s19b/README.md)。基础wheel不含桌面和Isaac运行时。

辅助修复可用`python tools/p053_auxiliary/test_failure_context.py`运行8项隔离CPU控制流检查。r5协议execution_enabled=false/空rows，没有新生产输入或启动器，不能把源修复写成新Kit运行通过。
