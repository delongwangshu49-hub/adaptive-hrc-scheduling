# S15 r2 换行兼容修复审阅

2026-10-05；候选 S15-20261005-r2。VERIFIED_WITH_LIMITS / ACCEPTANCE_PENDING / NOT_APPROVED / NOT_PUBLISHED。

负责人已批准 r1 限定成果与确切快照发布（PR120）。101 文件原快照已形成提交 `8d0b283deccba1631bc2c1d8f35e5abc8e9788a9`，远端 main 与新标签 `step-S15-r1` 已核验，409 个远端文件内容对象一致。但是 Ubuntu、Windows CI 均因 APPROVED_RECIPE_DRIFT 失败：518 项测试运行，S15 测试类在准备阶段报错，后续 wheel 检查未执行。状态为 PUSHED_CI_FAILED，不能记为 PUBLISHED。失败见 [CI 回执](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/runs/37322598556)。

## 原因与修复

原配方标识是批准文件 CRLF 字节的 SHA-256，仓库 .gitattributes 将文本规范为 LF。原本地源码及 wheel 验证使用保留 CRLF 的副本，未覆盖 Git 检出后的形式；这是验证缺口。远端配方数值未漂移。

唯一运行时代码变化是在读取配方时，将 LF/CRLF 换行统一还原为原批准摘要采用的 CRLF 表示，再核验原摘要。原配方文件、数值、RECIPE_DIGEST、配置身份及 RP/SC/SH/WV 边界均保持。新增两项测试覆盖两种换行读取，以及数值篡改和额外内容仍被拒绝。

## 实际检查与范围

全部跟踪文本统一为 LF 的捕获副本：源码 564 项、从该副本离线构建的隔离 wheel 564 项通过；两种导入来源审计和依赖检查通过。Ruff、121 文件格式和差异空白检查通过。原失败、原 r1 封包和 step-S15-r1 标签保留。机器摘要见 [修复验证](S15_ci_repair_r2.json)。

本次没有重跑 Kit，不把原 16 条分批源码轨迹转记为 r2；原 [限定成果](S15_final_review_r1.md) 和全部限制保持。原 720 h 截尾不变，质量及外接收仍为合成，工业资格 UNKNOWN、HR 禁用，负责人 GUI 体验未单独记录，历史偶发 Kit 关闭超时根因仍未闭合。

## 待批准的确切发布

基准为上述 r1 提交；审阅包提供确切文件、逐文件 SHA-256、完整差异及归档摘要。拟目标为既有仓库 https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling 的 main；拟精确暂存清单文件、创建一个修复提交、新建 step-S15-r2 标签、非强制原子推送 main 和新标签并核验双平台 CI。不移动 r1 标签，不创建 PR 或上传附件，不修改远端元数据。r1 批准不扩展到此新快照；S16—S28 未启动。
