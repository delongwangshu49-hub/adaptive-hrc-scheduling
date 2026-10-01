# 基础检查与持续集成（S02 / S03）

统一 CPU 入口检查轻量安装骨架，并对 `scripts/isaac_smoke.py` 做静态和格式检查。它不导入 Isaac 或运行场景；S03 实际 Kit 证据见 [运行验证](validation/runtime.md)。当前没有生产模型、调度算法或研究仿真实验。

## 统一入口

先按 [环境说明](setup.md) 安装 uv 0.12.3 和 CPython 3.12.13，从仓库根目录运行：

```powershell
uv run --locked --no-editable python scripts/check.py
```

Windows 使用 PowerShell 7，先确认 `$PSVersionTable.PSVersion.Major` 为 7；具体安装路径仅保存在本地。Linux 可从 Bash 执行同一命令。无需激活虚拟环境；不要设置 `UV_NO_SYNC` 或使用 `--frozen` 绕过锁定检查，也不要把 `UV_PROJECT_ENVIRONMENT` 指向 Isaac 环境。

命令同步默认 dev 组并按顺序执行下列检查；任何非零退出码立即终止，整条命令失败。检查入口不自动修复源码。

| 检查 | 内容与边界 |
| --- | --- |
| 版本与锁 | 解释器必须匹配 `.python-version`；`uv lock --check` 核对声明与锁 |
| 静态与格式 | Ruff 0.16.9；对 `src`、`tests`、`scripts` 检查 E4/E7/E9/F/I 规则及格式 |
| 安装自检 | unittest 两项：隔离模式从仓库外运行包，且分发元数据无运行依赖 |
| 环境一致性 | `uv pip check` 检查项目环境 |
| 构建与 wheel | 禁用构建包缓存，生成 sdist 并由其构建 wheel；新建独立环境，只安装 wheel，重跑两项自检与依赖检查 |

每次构建使用独立临时目录，完成或异常退出时清理。失败命令会显示在控制台，必要日志应保存在新的本地运行目录。指定 Python 安装可以复用；这不等于重新下载所有工具或完全离线复现。标准错误中的工具进度输出本身不代表失败，以退出码为准。

Ruff 是 MIT 许可的开发工具，精确版本与下载摘要由 `uv.lock` 记录，不属于安装包的运行依赖；仓库不再分发其二进制。S02 曾统一两份已有 Python 文件的格式，未改变安装行为。规则含义见 [Ruff 配置文档](https://docs.astral.sh/ruff/configuration/)。

需要修改格式时主动运行并审阅差异：

```powershell
uv run --locked python -m ruff format src tests scripts
```

更新工具时修改 `pyproject.toml`，运行 `uv lock`，再跑统一入口；版本升级属于新的审阅差异。没有加入类型检查器、覆盖率门槛或领域约束测试；应在后续实现有相应契约和行为后扩充。

## GitHub Actions

[工作流](../.github/workflows/ci.yml) 名为 `CPU checks`，在 main 的 push、以 main 为目标的 pull_request 或人工 workflow_dispatch 时触发。只推送步骤标签不会再重复运行。两项作业为 `CPU checks (ubuntu-24.04)` 和 `CPU checks (windows-2025)`，使用同一检查命令及 PowerShell 7；这两个托管镜像名称固定，但镜像内容仍由 GitHub 更新。

权限仅 `contents: read`，checkout 不保留凭据；Action 固定完整提交 SHA，uv 固定 0.12.3，Python 由 `.python-version` 决定。未启用持久缓存，未使用密钥、部署、附件上传或 Isaac/GPU 安装。每项作业超时 15 分钟，矩阵不因另一平台失败而提前结束，同一引用的新运行会取消旧运行。依据见 [uv 官方 CI 指南](https://docs.astral.sh/uv/guides/integration/github/)。

S02 已在本地用 actionlint 1.7.12 检查工作流语法、Action 输入和表达式，官方发布校验值匹配；该工具仅用于当步本地审阅，不加入项目运行依赖。静态通过本身不证明 GitHub 托管环境执行成功，实际远端结果见下文。[actionlint 官方说明](https://github.com/rhysd/actionlint)

## 贡献与发布

本次按负责人决定沿用 main 与现有目录，没有额外分支或 worktree。后续贡献先明确步骤范围，在本地完成统一检查并维护步骤卡、进度记录；出现实质性新指令时才追加规范化记录。暂存时使用确切文件清单，审阅完整差异、提交身份和拟推送历史。分支策略以后续授权为准；工作流支持 PR 不等于已批准创建 PR。

本地 VERIFIED 与人工 ACCEPTED、上传 APPROVED、远端 PUBLISHED 分开。负责人审阅并批准确切快照后，才提交、创建新步骤标签并推送 main 和该标签。不得继承旧步骤批准、强推或移动既有标签；不改变仓库保护规则。

推送后核对工作流运行的 `head_sha`、push 事件、两项作业及总体结论均对应获批提交，同时核验分支、标签和完整文件树。取消、跳过、失败或未启动均不能算通过；PUBLISHED 必须等待所需检查成功。若 CI 失败，保留运行链接与失败证据，修复后的内容须重新审阅批准；不能为了变绿覆盖原标签。相同提交的瞬时网络失败可核实后重跑，不冒称代码修复。

S02 封存时已完成 Windows 本地检查与独立源文件副本检查，其后真实远端结果见下文。尚未开启分支保护或将检查设为 required；S03 的场景运行与 CPU 检查分别记录。

## 已发生的远端核验与 S03 边界

S02 已发布提交 `ba8c8532af937771fcecf8f2f89c38c2bcf05998` 的 [push 工作流](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/runs/36742427800) 在 windows-2025 与 ubuntu-24.04 均成功。S03 没有修改该工作流、检查入口或依赖锁；候选仍需获批推送后核验绑定新提交的两平台结果。

不要在轻量环境中执行 Isaac 运行验收，也不要让普通 CI 安装 GPU 环境。Isaac 脚本的 `--help` 可由普通 Python 读取；实际运行需要 Isaac 解释器、场景断言及外部进程正常退出共同通过。脚本不进入项目 wheel，复验需要仓库源文件及独立安装。
