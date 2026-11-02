# G07 P07 publication r1：实际发布与核验

**G07_PUBLISHED_AND_VERIFIED**。负责人本轮“批准”授权本阶段发布至现有 main，并建立阶段注释标签。最终提交 `4158ba0a43ce1acda349bd431d291b9b70a52a04`，树 `9d00abfbe8a52d9548b594619d2c84c781498496`，标签 `step-P07-r2`。远端全部1248文件的路径、模式、blob与锁定清单相同；相对批准前基线为175新增、3修改、0删除。原G06标签保持。

## 首次发布与字节保全修正

首次 `306d35ffa54f329402e0050d58254f82b87af5c5` / `step-P07-r1` 已推送，发布后核验发现Git换行归一化使108个活动SHA契约失配。这是准备阶段漏查的分发问题。首次提交、标签、失败核验与已取消的首次CI均保留，不移动旧标签。

后续仅增加字节保全属性和一项回归检查，另122个路径恢复批准包的原精确字节；换行归一化后内容完全相同。研究数值、运行逻辑、原测试断言和247原核心pin保持。新回归在首次真实Git导出中失败，在修正导出与真实检出中通过。修正导出包完整重算12单元并通过严格校验，审计钩子禁止读取私有原始档案。

初次再生核验将输出指定到导出仓库外，因ROOT相对来源绑定失败；原日志保留。随后按README使用导出仓库内的新目录完整通过。本次验证覆盖仓库内输出路径，不宣称支持任意外部输出位置。

## 本次实际CI

[Actions 41407810409](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling/actions/runs/41407810409) 对应最终精确提交、push、attempt1。两个作业及共享检查步骤均成功；逐项解析真实日志身份和结果，各轮保留候选1272身份并包含新增字节回归。平台跳过单列。

| 平台 | 环境 | 收集身份数 | 秒 | 平台跳过 |
| --- | --- | ---: | ---: | ---: |
| CPU checks (windows-2025) | source | 1273 | 1858.009 | 0 |
| CPU checks (windows-2025) | isolated_wheel | 1273 | 1795.288 | 0 |
| CPU checks (ubuntu-24.04) | source | 1273 | 1439.113 | 1 |
| CPU checks (ubuntu-24.04) | isolated_wheel | 1273 | 1439.326 | 1 |

原本地完整源码与隔离wheel各1272通过的证据，与最终远端四轮分别保存。命令行状态读取曾遇EOF、无效凭据及匿名API限流；随后使用已连接GitHub工具和实际运行页面读取结果，未修改认证或重跑CI。最终状态来源和最初不可变运行元数据在机读记录中分列。

## 交付包与README

GitHub生成的源码ZIP含1248文件，全部CRC与成员字节和修正后的真实Git导出相同。SHA256为 `d0c95fc9c77556a5d938cb5848cbe0b32f911f1b720999964b0de95695136bd9`，保存于 `.local\g07-publication-20261102-r1\github-source-r2.zip`。最终178项增量ZIP、wheel/sdist及SHA256清单见 `.local/g07-publication-20261102-r1/final-package-artifacts.json`。原wheel/sdist及110核心成员保持；本次没有建立PyPI发行或GitHub Release对象。

README按用途、快速开始、真实工作台、原生Mermaid、研究结果及文档组织。发布提交的真实图全部加载。独立浏览器中两个GitHub原生Mermaid均已渲染，放大和平移使SVG变为 `translate(-100px, 0px) scale(1.1)`，随后重置；直接鼠标拖动未测。Chrome初始富显示失败原因UNKNOWN，同源独立浏览器成功。原本地桌面/窄屏/浅深预览证据适用于相同README字节。

## 保全与阶段边界

583无关可见文件和247原核心保持事前摘要。六治理保留完整原后缀，最终回执仅在本地追加。索引仅作已批准路径写入，暂存为空；此前历史index变化原因UNKNOWN不回写。无新分支、worktree、子代理、正式生产、Kit或研究求解，P08/P09未启动。

P07 R1–R4维持限定范围关闭；原性能NOT_MET/INSUFFICIENT、K01、E20、WIP/J3、REST、P08、G2和Vite high边界保持。发布不扩展为原生产全部目标完成或方法普遍收益。

机读记录：`docs/delivery/g07_publication_r1.json`。实际回执、原失败及原日志：`.local/g07-publication-20261102-r1/`。
