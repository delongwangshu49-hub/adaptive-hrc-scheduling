# C03 仓库名称、About与链接迁移候选

版本 C03-0.3；2026-10-02；CANDIDATE_FROZEN（PR069）：推荐名称及About候选已确认，未修改远端或本地remote。只读API核验当前[仓库](https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling)为public、默认main；origin fetch/push均指该仓库.git。r1只读核查时About为“Adaptive human–robot scheduling for modular construction with fatigue and disruptions.”。本轮未核验远端完整树或重跑CI，不将API元数据读取当发布核验。

| 项目 | 具体候选 | 判断 |
| --- | --- | --- |
| 推荐名称 | steel-module-adaptive-scheduling | 对应已选完整钢模块及自适应排程；代码仍未实现新域，需要About明确状态 |
| 备选名称 | building-module-production-scheduling | 突出完整建筑生产，但材料和A主问题不如推荐名直接 |
| About候选 | Research on multi-resource adaptive scheduling for complete steel building modules, with state-dependent human–robot modes and human-factor trade-offs. Building-domain specifications; current executable baseline is a pipeline demo. | 描述目标及当前能力，不声称已完成仿真/算法/工业标定 |

名称可用性和管理权限在实际改名前再次核验，不因候选链接尚不存在而新建仓库。包名adaptive_hrc_scheduling、导入路径、distribution名称此刻不变，改仓库名与改API不是同一操作。

## 明确链接处置

逐处出现清单见[链接迁移表](repository_links.tsv)，包括文件、行号、当前URL、分类、将来动作和候选目标。纯相对README/文档链接无需改。历史LOG/步骤卡/旧标签/提交/Actions回执保留原URL与原时点，不进行全仓库字符串替换；即使跳转可用也不重写旧批准证据。现行文档中有意指向step-S09-r2的“旧实现参考”同样保留旧定位。新增规范入口优先使用相对路径。

批准后的操作顺序（尚未获批）：负责人确定名称/About及确切文件快照和远端动作→核对仓库身份/权限/目标名/分支标签历史→管理页面或API改名/About→只读核验新地址和重定向→显式更新origin fetch/push→核验所列现行链接、README/徽章/克隆示例和Pages/Actions依赖→保存元数据回执。文档提交/标签/推送仍是另外的确切快照发布动作，不由改名许可自动包含。

GitHub通常重定向仓库网页与Git访问，但Pages地址和作为Action使用的仓库调用有例外；旧名称被重新使用可能破坏重定向。因此不能只依赖自动跳转，也不复用旧名。本仓库配置核查未发现Pages部署或对本仓库作为Action的自引用；外部使用者依赖未知。[GitHub官方改名说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)

当前目标仍是既有仓库/main；C03 r2已获文档验收，但step-C03-r2未创建、上传未批准。C05收尾时按PR070重新整理实际上传快照及具体远端动作。拟执行远端动作列表为空，不暂存/提交/标签/推送/PR/附件/About写入。若之后内容或目标变化，重新封装快照，不移动旧标签或强推。

C05收尾注：上表为PR069冻结的历史候选，不改写原决定；C04/C05已有合成建筑内核，因此旧About中的pipeline demo现已过时。本轮拟上传包不含远端改名/About，后续操作须另审阅与当前能力一致的文案及确切目标。
