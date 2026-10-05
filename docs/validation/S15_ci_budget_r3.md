# S15 r3 Windows CI 时间预算修订

2026-10-05；候选 S15-20261005-r3。VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。

## r2 实际发布执行结果

负责人已批准 r2 确切快照（PR121）。提交 `9d82b292a0a1c585b71bc7676b08f2bd417c9387` 与标签 `step-S15-r2` 已推送，远端 411 文件及历史标签核验通过。Ubuntu CI 两轮各 564 项通过，耗时 240.776 s / 235.763 s。

Windows 初次与同提交重试均被 GitHub 的 15 分钟作业上限取消。第一轮各 564 项通过，耗时 434.774 s / 430.842 s；第二轮接近结束时被取消，没有完整成功回执，不能记为通过。日志未见断言失败；这不代替未完成的测试结论。两次失败均保留，r2 状态为 PUSHED_CI_TIMEOUT。实际 [CI 运行](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/runs/37324618681) 和 [数值摘要](S15_ci_budget_r3.json) 可核对。

## 唯一执行配置变化

将 Windows 作业上限由 15 分钟改为 25 分钟，Ubuntu 保持 15 分钟。工作流使用 matrix.os 条件表达式；其余工作流字节、检查命令、测试数量、失败判定、依赖版本和权限均不变。该时限是 CI 执行预算，不修改仿真的 720/240/960 h 等窗口。

生产源码、配方、测试均与 r2 提交相同，原 LF 源码及隔离 wheel 各 564 项本地证据继续适用。已验证工作流仅一行差异、源码/测试无变化、差异空白及封包摘要。没有为了这个时间预算修改重复执行本地功能测试，也没有预写新远端 CI 成功。25 分钟为待实际运行检验的余量，并非已经证明所需最大时长。

## 审阅与发布范围

确切包提供文件清单、完整差异和逐文件摘要。拟在既有仓库 https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling 的 main 精确暂存清单、创建一个 CI 修复提交、新建 step-S15-r3、非强制原子推送 main 与新标签，并核验双平台 CI。保留 r1/r2 标签及失败证据，不建 PR、不上传附件、不改远端元数据。新快照需单独批准。

原 16 条 Kit 轨迹仍绑定各自源码，没有重跑或转记；720 h 截尾、合成质量/接收、工业 UNKNOWN、HR 禁用、GUI 体验未单独验收及历史 Kit 关闭根因未闭合等限制保持。S16—S28 未启动。
