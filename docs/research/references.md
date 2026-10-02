# 参考文献与核查记录

版本 C03-0.1；2026-10-02。建筑生产来源B01—B11和访问限制见[生产证据台账](production_evidence.md)，本次不将供应商说明当独立标定。下文方法来源原核查日期：2026-10-01（UTC+08:00）。本清单服务于 [相关工作](related_work.md) 和 [研究假设与参数依据](hypotheses.md)，是针对已确认研究问题的定向核查，不是系统综述或穷尽性检索。论文结论与本项目结果严格分开。

## 检索和证据口径

本轮使用公开网页检索、出版商页面、作者机构存档及 DOI 注册元数据。检索组合覆盖 `human robot collaborative assembly scheduling fatigue`、`sequential collaboration simultaneous cooperation scheduling`、`dual task scheduling personalized fatigue`、`dynamic task allocation construction`、`dynamic muscle fatigue model`、`rescheduling manufacturing systems` 和 `large neighborhood search`；再按准确题名、DOI、作者和机构补查。未访问付费数据库检索接口，不报告无法复现的总命中数或筛选比例。

纳入依据是能够对应协作阶段、状态依赖分配、人因目标、动态调度或参照求解语义；参数迁移还需核查测量对象、单位和场景。只把原始研究、作者稿和官方工具文档用于技术主张。聚合站和综述仅提供查找线索，不代替原论文。检索未覆盖所有语种、会议和近期在线版本，因此“本轮未核实”不能改写为“已有研究没有”。

| 级别 | 本次实际获取范围 | 可支持的陈述 |
| --- | --- | --- |
| F | 全文可访问，并核查了下列相关章节；不表示复现论文全部实验 | 限于已查章节中的模型、方法及限制 |
| P | 原始出版商的索引正文片段或摘要；直接打开失败 | 片段明确说出的内容；不推断未见方程、附录或参数 |
| O | 官方工具说明 | API 与建模语义，不证明项目实现或最优性 |
| U | 日期或正文证据未解决 | 仅列待复核线索，不纳入已确证比较 |

检索输出、访问失败、书目核对和章节定位的详细证据仅本地留存。公开仅给原创概述和链接，不附论文、图表、课件、原始检索日志或参考资料全文。仓库 MIT 许可不重新许可被链接的第三方材料。

## 已用于比较的来源

### R01

Park, Kyu-Tae; Lim, Chiho; Lee, Ju-Yong. (2025). *Production scheduling for human–robot collaborative assembly workstations under constraints of ergonomic fatigue and simultaneous cooperation*. Journal of Manufacturing Systems, 83, 337–356. [DOI](https://doi.org/10.1016/j.jmsy.2025.09.012) · [出版商](https://www.sciencedirect.com/science/article/pii/S0278612525002390)。

- 证据：P；出版商索引中的 Abstract、Highlights、Introduction；DOI 注册元数据核对作者、题名、卷页。直接打开返回 403。
- 核查要点：明确同时讨论疲劳、顺序协作、同步协作和 AVNS。完整数学约束、参数表和复现实验未核实。文中的 single-mode workstation 不等于本项目 H/R/HR 模式固定，不能用词面差别建立创新性。

### R02

Chand, Saahil; Lu, Yuqian. (2023). *Dual task scheduling strategy for personalized multi-objective optimization of cycle time and fatigue in human-robot collaboration*. Manufacturing Letters, 35 (Supplement), 88–95. [DOI](https://doi.org/10.1016/j.mfglet.2023.08.064) · [出版商](https://www.sciencedirect.com/science/article/pii/S2213846323001219)。

- 证据：P；出版商索引 Abstract，DOI 注册元数据核对作者与卷页；出版商直接打开 403，正文 API 未取得可读内容。
- 核查要点：团队与个体疲劳目标及恢复已被研究。没有核实其目标是否等于本项目的积分总和与最大个人积分，也没有核实共同硬上限设置，不能声称完全相同或完全不同。

### R03

Petzoldt, Christoph; Niermann, Dario; Maack, Emily; Sontopski, Marius; Vur, Burak; Freitag, Michael. (2022). *Implementation and Evaluation of Dynamic Task Allocation for Human–Robot Collaboration in Assembly*. Applied Sciences, 12(24), 12645. [DOI](https://doi.org/10.3390/app122412645) · [出版商正文](https://www.mdpi.com/2076-3417/12/24/12645)。

- 证据：P；出版商索引可读 §2.2.1–2.2.2、§5 和摘要；直接打开返回 429，另一正文入口失败。
- 核查要点：依据任务可用性和资源状态动态分配，完成反馈触发后续安排；报告收益受装配并行性影响。未独立复核其全部用户研究数据。

### R04

You, Yingchao; Cai, Boliang; Pham, Duc Truong; Liu, Ying; Ji, Ze. (2025). *A human digital twin approach for fatigue-aware task planning in human-robot collaborative assembly*. Computers & Industrial Engineering, 200, 110774. [DOI](https://doi.org/10.1016/j.cie.2024.110774) · [作者机构记录](https://orca.cardiff.ac.uk/id/eprint/174446/) · [机构存档正文](https://orca.cardiff.ac.uk/id/eprint/174446/1/1-s2.0-S0360835224008969-main.pdf)。

- 证据：F；12 页出版版本，重点核查 §3.3（式 11–13）、§3.4、§5；PDF 第 6、10–11 页（从 1 计数）。DOI 年份 2024 与卷期年份 2025 分开保留。
- 核查要点：肌肉力估计、疲劳感知分配已有研究；实验采用一人一机器人。其肌肉级参数不直接成为本项目工人级合成状态参数。

### R05

Ma, Liang; Chablat, Damien; Bennis, Fouad; Zhang, Wei. (2009). *A new simple dynamic muscle fatigue model and its validation*. International Journal of Industrial Ergonomics, 39(1), 211–220. [DOI](https://doi.org/10.1016/j.ergon.2008.04.004) · [作者上传记录](https://arxiv.org/abs/2201.01069) · [作者稿](https://arxiv.org/pdf/2201.01069)。

- 证据：F；28 页作者稿，§2、§4、§5，特别是正文式 2 和动态验证限制。2022 是存档上传年，不是期刊出版年。
- 核查要点：模型涉及负荷历史及个体差异；作者明确更多动态情境的实验验证不足。不能把此文作为任意工序恢复、速度映射或安全阈值的验证依据。

### R06

Vieira, Guilherme E.; Herrmann, Jeffrey W.; Lin, Edward. (2003). *Rescheduling Manufacturing Systems: A Framework of Strategies, Policies, and Methods*. Journal of Scheduling, 6, 39–62. [DOI](https://doi.org/10.1023/A:1022235519958) · [作者机构记录](https://isr.umd.edu/Labs/CIM/projects/jos-cover.html) · [机构作者稿](https://isr.umd.edu/Labs/CIM/projects/jos-rescheduling.pdf)。

- 证据：F；39 页机构稿，§5.2 及 §6 的重排分类。机构稿分页不同于期刊版，引用按节定位；另一机构镜像直接打开失败。
- 核查要点：预测—反应式安排、事件触发和计划修复已有成熟分类。不能把滚动更新本身称为项目首创。

### R07

Pisinger, David; Ropke, Stefan. (2010). *Large Neighborhood Search*. In *Handbook of Metaheuristics*, 399–419. [DOI](https://doi.org/10.1007/978-1-4419-1665-5_13) · [作者机构稿](https://backend.orbit.dtu.dk/ws/files/5293785/Pisinger.pdf)。

- 证据：F；23 页机构稿，§2、§2.1–2.2；正文第 8–14 页描述破坏、修复与邻域选择。机构稿页码不等同书籍页码。
- 核查要点：LNS 和自适应邻域权重是已有通用方法。状态感知调度不自动等于采用自适应权重的 ALNS；本项目尚未冻结该实现选择。

### R08

Google OR-Tools. *The Job Shop Problem*. [官方文档](https://developers.google.com/optimization/scheduling/job_shop)。访问日 2026-10-01。

- 证据：O；任务前序、资源互斥、区间变量示例。
- 边界：示例不包含本项目全部模式、人员疲劳、缓冲与扰动规则，不能直接充当完整模型参照。

### R09

Google OR-Tools. *CP-SAT Solver*. [官方文档](https://developers.google.com/optimization/cp/cp_solver)。访问日 2026-10-01。

- 证据：O；整数建模要求与 CP-SAT return values。
- 边界：FEASIBLE 不是已证明最优，UNKNOWN 不是已证明不可行；结论还受所求模型和配置约束。实现时应再次核对固定版本及终止设置。

### R10

Sawicki, Bartłomiej; Düking, Peter; Placzek, Gerrit; Masur, Lukas; Dörrie, Robin; Schwerdtner, Patrick; Kloft, Harald. (2026). *Human–robot collaboration in digital fabrication with concrete: quantifying productivity and psychophysiological strain of human workers*. Construction Robotics, 10, 4. [DOI及正文](https://doi.org/10.1007/s41693-025-00173-x)。

- 证据：F；出版商 HTML，§1、§5–6 和出版记录；正式发布日期 2026-01-17，不按 DOI 中的 2025 推定出版年。
- 核查要点：真实构件生产的探索性研究涉及生产率与人员负荷；作者明确未完成全流程分析。其混凝土工艺与测量值不能直接校准传统整体浇筑建筑模块仿真。

## 日期或访问范围待复核的相近线索

以下两项作为 U 类保留，避免遗漏高度相近题名。已看见的摘要或正文片段提示可能有重叠，但尚不能确定其截至核查日的正式在线状态；不利用它们作已确证方法或参数证据，也不据此给出首创判断。

| ID | 可追溯书目信息 | 本次问题与处理 |
| --- | --- | --- |
| U01 | Wang, Hongxu; Wang, Mingzhu. *Adaptive task allocation and scheduling for human–robot collaborative construction under dynamic uncertainty*. [DOI](https://doi.org/10.1016/j.autcon.2026.107278)；Automation in Construction, 192, 107278 | 出版商索引有摘要，直接打开 403；DOI 元数据卷期为 2026-12，未给可核实的先行上线日。保留相近线索，后续核实日期和完整模型 |
| U02 | Tian, Fei; Yu, Yantao. *Optimizing Task Scheduling for Efficient and Ergonomic Human–Robot Collaboration in Construction Tasks*. [DOI](https://doi.org/10.1061/AOMJAH.AOENG-0094)；ASCE OPEN, 4(1) | 出版商索引有工作—休息与任务排序片段，直接打开失败；DOI 元数据为 2026-12-31，先行上线日未核实。不得把卷期日期当作首次公开日期，也不把索引抓取年龄当作上线证据 |

## 完成程度与后续缺口

核心清单共 10 项：5 项 F、3 项 P、2 项 O；另有 2 项 U。这个分级描述访问和核查范围，不是论文质量排名。R01、R02 的完整方程与参数仍是最重要的补证缺口；在提出任何具体差异或新颖性结论前必须重查。S04 可完成的是有界比较、假设和来源台账，不能因此宣布文献已穷尽或贡献已成立。
