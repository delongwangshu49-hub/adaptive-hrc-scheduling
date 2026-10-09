# S19A静态成果：验收与确切发布 r1

2026-10-10；PR167 / LOG223。负责人已通过最终静态外观并批准发布，同时要求README图片更新。决定 **S19A-STATIC-PUBLISH-APPROVAL-003**，验收 **ACCEPTED_WITH_DOCUMENTED_LIMITS**，发布已获批准、具体远端与CI回执待执行后核验。本页不预写实际发布或CI成功。

## 确切范围

15人物已通过的岗位涂装、编号及几何内视觉细节；最新五设备对比度修订、其余设备静态涂装、深黑灰地面/浅工作区、纯材质通行条纹和原两灯强度；全部前后图审与机器摘要及必要治理。README主图替换为最新全场，并展示已通过人员总览。历史图片和审阅保持，不替换原失败或原完整生产链源码绑定。

原1,148几何及上一轮165视觉对象保持，本次修订几何/碰撞新增0；728碰撞、15人属性/手位/根位置及实际障碍集合保持。57场景回归、真实Kit最终截图/相机读回/完整关闭/退出0已通过，首轮关闭异常与核验诊断如实保持。证据见[整组原图](S19A_static_batch_r1.md)、[最终修订](S19A_contrast_r2.md)和[实际批准](S19A_static_acceptance_r1.json)。

这是静态范围发布。A2动作未改、A3视频/整步出口未完成，没有新完整生产链或正式A/D实验。静态帧耗时为观测，不作性能门限PASS。工业G2 OPEN/NOT_ESTABLISHED，S19B及S20—S28未启动。

## Git目标及操作

目标：https://github.com/delongwangshu49-hub/adaptive-hrc-scheduling；分支`main`，父提交`5a69646fc3d4ed16cca0e6151dffe71b2447dae6`；一个新提交，一个新注释标签`step-S19A-static-r1`，原子推送`main`与该标签到`origin`。不移动旧标签、不强推或创建额外分支/worktree/子代理。提交身份沿用仓库已配置身份。

只暂存下列文件，逐文件摘要、完整差异、确切包及执行回执留存本地。保留其余569基线文件内容。所有公开路径为仓库相对路径，截图与贴图保持原PNG字节。远端完整树和两平台CPU CI须实际核验；不在当前提交中填入自身最终哈希。

## 发布前完整检查

本次与CI相同检查实际通过：源码849项/221.023s、隔离wheel849项/226.008s；锁文件、Ruff检查/格式、分发构建和依赖一致性均通过，完整进程退出0。最终发布集合共94文件，含69份原PNG（68张历史/当前图审图片及1份地面颜色贴图）。所有原图片/审阅保持；本地保存检查日志摘要、逐文件原字节/Git内容摘要和封包。远端CI为推送后的独立检查，当前不预写成功。

## 精确文件集合

- `AGENTS.md`
- `PROGRESS_LOG.md`
- `PROMPT_LEDGER.md`
- `README.md`
- `docs/PROJECT_CHARTER.md`
- `docs/roadmap.md`
- `docs/sim/images/s19a/a1/W1-back-before-proposal.png`
- `docs/sim/images/s19a/a1/W1-face-before-proposal.png`
- `docs/sim/images/s19a/a1/W1-front-before-proposal.png`
- `docs/sim/images/s19a/a1/W1-route-proposal.png`
- `docs/sim/images/s19a/a1/W1-three-quarter-before-proposal.png`
- `docs/sim/images/s19a/batch-r1/AF1-front.png`
- `docs/sim/images/s19a/batch-r1/AF1-side.png`
- `docs/sim/images/s19a/batch-r1/AF2-front.png`
- `docs/sim/images/s19a/batch-r1/AF2-side.png`
- `docs/sim/images/s19a/batch-r1/C1-front.png`
- `docs/sim/images/s19a/batch-r1/C1-side.png`
- `docs/sim/images/s19a/batch-r1/CR1-HOOK-comparison.png`
- `docs/sim/images/s19a/batch-r1/CR1-comparison.png`
- `docs/sim/images/s19a/batch-r1/CUT1-comparison.png`
- `docs/sim/images/s19a/batch-r1/E1-front.png`
- `docs/sim/images/s19a/batch-r1/E1-side.png`
- `docs/sim/images/s19a/batch-r1/FIX-J2-comparison.png`
- `docs/sim/images/s19a/batch-r1/FIX-J3-comparison.png`
- `docs/sim/images/s19a/batch-r1/Lop-front.png`
- `docs/sim/images/s19a/batch-r1/Lop-side.png`
- `docs/sim/images/s19a/batch-r1/Lrig-front.png`
- `docs/sim/images/s19a/batch-r1/Lrig-side.png`
- `docs/sim/images/s19a/batch-r1/Lsig-front.png`
- `docs/sim/images/s19a/batch-r1/Lsig-side.png`
- `docs/sim/images/s19a/batch-r1/OP1-front.png`
- `docs/sim/images/s19a/batch-r1/OP1-side.png`
- `docs/sim/images/s19a/batch-r1/P1-front.png`
- `docs/sim/images/s19a/batch-r1/P1-side.png`
- `docs/sim/images/s19a/batch-r1/PL1-front.png`
- `docs/sim/images/s19a/batch-r1/PL1-side.png`
- `docs/sim/images/s19a/batch-r1/QA1-front.png`
- `docs/sim/images/s19a/batch-r1/QA1-side.png`
- `docs/sim/images/s19a/batch-r1/R1-comparison.png`
- `docs/sim/images/s19a/batch-r1/SCN-CART-01-comparison.png`
- `docs/sim/images/s19a/batch-r1/SCN-FORK-01-comparison.png`
- `docs/sim/images/s19a/batch-r1/SCN-WELD-J2-comparison.png`
- `docs/sim/images/s19a/batch-r1/SCN-WELD-J3-comparison.png`
- `docs/sim/images/s19a/batch-r1/T1-front.png`
- `docs/sim/images/s19a/batch-r1/T1-side.png`
- `docs/sim/images/s19a/batch-r1/T2-front.png`
- `docs/sim/images/s19a/batch-r1/T2-side.png`
- `docs/sim/images/s19a/batch-r1/TEST1-comparison.png`
- `docs/sim/images/s19a/batch-r1/W1-front.png`
- `docs/sim/images/s19a/batch-r1/W1-side.png`
- `docs/sim/images/s19a/batch-r1/W2-front.png`
- `docs/sim/images/s19a/batch-r1/W2-side.png`
- `docs/sim/images/s19a/batch-r1/factory-after.png`
- `docs/sim/images/s19a/batch-r1/factory-before.png`
- `docs/sim/images/s19a/batch-r1/index.html`
- `docs/sim/images/s19a/batch-r1/people-all-after.png`
- `docs/sim/images/s19a/contrast-r2/CUT1-comparison.png`
- `docs/sim/images/s19a/contrast-r2/R1-comparison.png`
- `docs/sim/images/s19a/contrast-r2/SCN-CART-01-comparison.png`
- `docs/sim/images/s19a/contrast-r2/SCN-FORK-01-comparison.png`
- `docs/sim/images/s19a/contrast-r2/TEST1-comparison.png`
- `docs/sim/images/s19a/contrast-r2/crossing-after.png`
- `docs/sim/images/s19a/contrast-r2/crossing-before.png`
- `docs/sim/images/s19a/contrast-r2/factory-after.png`
- `docs/sim/images/s19a/contrast-r2/factory-before.png`
- `docs/sim/images/s19a/contrast-r2/floor-top-after.png`
- `docs/sim/images/s19a/contrast-r2/floor-top-before.png`
- `docs/sim/images/s19a/contrast-r2/index.html`
- `docs/sim/images/s19a/people-r1/Lop-front.png`
- `docs/sim/images/s19a/people-r1/Lop-side.png`
- `docs/sim/images/s19a/people-r1/P1-front.png`
- `docs/sim/images/s19a/people-r1/P1-side.png`
- `docs/sim/images/s19a/people-r1/W1-front.png`
- `docs/sim/images/s19a/people-r1/W1-side.png`
- `docs/sim/images/s19a/people-r1/W2-front.png`
- `docs/sim/images/s19a/people-r1/W2-side.png`
- `docs/steps/S19A.md`
- `docs/validation/S19A_a1_visual_review_r1.json`
- `docs/validation/S19A_a1_visual_review_r1.md`
- `docs/validation/S19A_contrast_r2.json`
- `docs/validation/S19A_contrast_r2.md`
- `docs/validation/S19A_people_acceptance_r2.json`
- `docs/validation/S19A_people_review_r1.md`
- `docs/validation/S19A_static_acceptance_r1.json`
- `docs/validation/S19A_static_batch_r1.json`
- `docs/validation/S19A_static_batch_r1.md`
- `docs/validation/S19A_static_publication_r1.md`
- `docs/validation/S19A_w1_acceptance_and_application_r1.json`
- `sim/isaac/scene/appearance_styles.py`
- `sim/isaac/scene/assets/s19a_floor_paint_r2.png`
- `sim/isaac/scene/floor_finish.py`
- `sim/isaac/scene/person_appearance.py`
- `sim/isaac/scene/scene_appearance.py`
- `sim/isaac/scene/target_scene.py`
