# 项目状态与使用范围

本轮版本入口为 [step-P07-r3](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/tree/step-P07-r3)，实际 CI 以[CPU工作流](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/workflows/ci.yml)中绑定该发布提交的结果为准。README 徽章跟随 main。

历史基线 G07 `step-P07-r2` / `4158ba0a43ce1acda349bd431d291b9b70a52a04` 的 Actions 41407810409 已通过 Ubuntu/Windows 源码与隔离 wheel 四轮检查，每轮1273项；首次r1的换行失败、原标签及记录保留。

[双语候选记录](../delivery/g07_presentation_candidate_r2.json)和[本轮发布范围](../delivery/g07_presentation_publication_scope_r1.json)区分发布前本地检查、历史完整检查与新提交的实际CI。候选记录是当时快照，不代表当前远端状态；不将历史CI移作本次结果。

| 范围 | 当前可用内容 |
| --- | --- |
| 模型与会话 | 多资源约束、疲劳/恢复、动态目录、订单与人员请求、实际执行及独立核验 |
| CPU 案例 | 正常完整单产品案例 436 项静态工序、1/1 接收与独立审计；源码入口可复现 |
| Windows 工作台 | Qt/WebEngine、原生 Kit 与计划/实际甘特、回执、保存及只读重建；依赖受测环境 |
| 研究分析 | 冻结 r3 的 12 原执行单元；按问题整理为九表、四图；原结果与失败保持 |
| 软件分发 | 核心 wheel 与完整源码分析材料分开；新版 README 随发行元数据重建 |

仍未完成的目标和使用边界：

- 2 秒源龄目标未达到，持续 4 Hz 未建立，稳段和 10/s、50/s 负载资格不足。
- E20 原连续 Kit 停止时 1 件接收、3 件未接收；其他运行不补齐尾段。WIP/J3 HOLD 剩余完成未成立。
- 手动 REST、负责人实际操作和最终联合验收保留待办状态，离线修订不代替实际操作。
- 历史 621.01 驱动下 K01 根因 OPEN，工业 G2 OPEN。S18-SIM-A1 为仿真研究域，USD 运动学读回不构成工业动力学或安全认证。
- Vite 工具链既定 high 告警 OPEN，见[工具链审计](../public_validation/toolchain_advisories.md)，未自动升级依赖。
- 固定研究未建立 ADAPTIVE 的普遍优势；未测 CPU 时间、峰内存和未知货币成本不填零。
- 本次不新增生产、Kit 或研究求解，P08/P09 未启动。
