# G07 图表叙事修订候选 r1

本地候选，**暂不发布**。基线为 `4158ba0a43ce1acda349bd431d291b9b70a52a04` / `step-P07-r2`；建议后续标签 `step-P07-r3` 尚未创建。本次不创建提交、标签，不推送、上传或触发远端 CI。

新版 README 保留真实工作台与原生 Mermaid，以四幅研究图和有明确用途的表格组织叙事。九表与四图可从公开输入离线重建；旧 r3 数值、图、完成记录和原 README 快照保留。

源码/隔离 wheel 各 1276 项通过，耗时 890.860 / 1142.352 s，保留已发布基线全部 1273 身份。110 核心文件和依赖锁不改，最终 sdist 重建 wheel 字节相同，隔离 CLI 通过。四组桌面/窄屏浅深预览、九表与 12 个图片导出文件的全新环境重建一致。

交付目录：`.local/g07-presentation-preparation-20261102-r1/`。完整源码包 `g07-presentation-source-r1.zip`、确切增量 `g07-presentation-delta-r1.zip`、`dist/` 中 wheel/sdist，以及外部文件清单和 `SHA256SUMS.txt` 配套使用。核心 wheel 不包含离线分析材料；研究复现使用完整源码包。

实际 Git 树、导出/检出门禁、逐文件 SHA、ZIP CRC 和最终停止状态封存在外部 `result.json`。包内说明不嵌入包含自身的 ZIP 摘要，避免循环身份。公开[候选说明](g07_presentation_candidate_r1.json)、[展示契约](p07_presentation_r1.json)、[核查问题衔接](p07_presentation_resolution_r1.json)、[修订报告](../validation/P07_presentation_revision_r1.md)随包交付。

原性能、K01、E20、WIP/J3、REST、P08、工业 G2 与 Vite high 边界保持。P08/P09 未启动。
