# Neurova 文档单一事实源（Documentation Single Source of Truth）

> 本文件是 Neurova 文档体系的**唯一权威入口**。所有文档的阅读顺序、归属领域、权威版本都以此为准。
> 新增或移动任何文档前，必须先更新本索引。

## 0. 阅读顺序（新人必读）

1. **[`docs/CONTEXT.md`](CONTEXT.md)** —— 项目总览、核心架构、ChatPipeline、记忆温度系统（最高权威，先于本目录）
2. **[`/AGENTS.md`](../AGENTS.md)** —— 开发者快速上手与关键约定（纪律唯一事实源）
3. **[本索引](INDEX.md)** —— 按领域定位详细文档
4. 进入具体领域后，只读该领域的 **[权威]** 文档，历史/对比类仅作参考

## 1. 文档归属领域与权威文档

每个领域只保留 **一个 [权威]** 文档作为事实源，其余为参考或历史归档。

| 领域 | 权威文档 | 说明 |
|------|----------|------|
| 整体架构 | [`docs/CONTEXT.md`](CONTEXT.md) + [`docs/INDEX.md`](INDEX.md) | 系统级事实源 |
| **架构模型（可视化）** | `docs/architecture-model/` | **证据接地的 C4/DOT 文本源与风险图，`CONTEXT.md` 的图文配套层**；图中每条结论带 `文件:行号`，与 CONTEXT.md 冲突时以本目录的实测证据提 issue 回修 CONTEXT.md |
| 架构决策(ADR) | `docs/01-architecture/adr/` | 已编号的决策记录，不可覆盖 |
| API 规范 | [`docs/02-api/`](02-api/) + [`API_REFERENCE.md`](02-api/API_REFERENCE.md) | 接口事实源 |
| 记忆系统 | [`docs/01-architecture/02-memory-system.md`](01-architecture/02-memory-system.md)（架构）＋ [`docs/01-architecture/memory/retrieval-spine.md`](01-architecture/memory/retrieval-spine.md)（检索脊柱）＋ `docs/01-architecture/memory/`（专题与计划） | 记忆层事实源；两份 [权威] 各管一层，计划文档不是架构事实源 |
| 认知架构 | `NEUROVA_CogArch_2.0.md` | **2026-05-12 设计快照（沿革）**；§8.2 状态列不可作事实源（D9，台账 §6-362）；**现行组件状态见 [`cognitive-component-table.md`](01-architecture/cognitive-component-table.md)（机器生成）** |
| 开发进度 | `docs/09-dev-progress/` | 迭代记录（历史） |
| Bug 修复史 | 根目录 `bugfix-*.md` 集群 | 变更日志（历史，归档用） |
| 配置 | `docs/10-configuration/` | 部署/配置事实源 |
| 国际化 | `docs/03-user-guide/i18n/` | 多语言事实源 |
| 产品/品牌 | `PRODUCT_GUIDE.md` / `NEUROVA_BRAND.md` | 对外信息事实源 |
| 鸿蒙端 | `HARMONYOS_*.md` | NeurovaHarmony 端事实源 |

## 2. 文档真实分布（实测，2026-08-23）

> **口径说明（2026-09-21）**：本节及 2.1/2.2 是**搬迁前**的实测快照，正文按当时实况逐字保留；
> 其中的旧目录路径（`docs/dev_progress/`、`docs/memory/`、`docs/reports/` 等）今天已按编号分层归位，
> 当前归属一律以第 1 节表为准。保留原文是为了让重排前后可对照，不是当下导航。

> 说明：扫描时混入的 `.venv/`(102)、(22)、`flow-kb-sdk/`(18) 等是**虚拟环境/第三方工具缓存**，
> 不属于项目文档，已排除。真实项目 markdown 约 **377 篇**，其中 `docs/` 占 **297 篇**。

| 位置 | 数量 | 性质 | 处置 |
|------|------|------|------|
| `docs/`（13 子目录 + 139 扁平文件） | 297 | **主文档库** | 单一事实源承载地，扁平文件需归类 |
| 根目录 `.md`（`CONTEXT.md`/`AGENTS.md`/`README.md`/`CHANGELOG.md` 等） | 52 | 项目入口 + 报告 | 入口保留，报告类下沉到 `docs/reports` |
| `tests/` `i18n/` `other/` 等其他项目目录 | ≤20 | 专题/测试文档 | 按领域归集到 `docs/` |

**核心问题不是"合并 296 篇"，而是：`docs/` 有 139 个文件直接平铺在根（零层级），
且存在记忆升级 6 篇、竞品对标 16 篇、grilling 评审 10 篇等明显冗余簇。**
正确做法是**按主题移入已有子目录**（而非物理拼接成一个大文件，那会摧毁可检索性）。

`docs/` 现有子目录：`adr/ api/ architecture/ bug/ compose/ configuration/ dev_progress/ i18n/ memory/ plans/ reports/ research/ 用户指南/`

### 2.1 扁平 139 文件的主题分布（自动化归类依据）

| 目标子目录 | 命中数 | 来源关键词 |
|------------|--------|-----------|
| `docs/bug/` | 43 | bug / fix / 修复 |
| `docs/misc`（待细分） | 31 | 未匹配 |
| `docs/research/` | 16 | comparison / vs_ / 对标 / analysis |
| `docs/reports/` | 12 | report / 报告 / summary / 总结 |
| `docs/memory/` | 9 | memory / 记忆 |
| `docs/`（前端→`web/` 或新建 `frontend/`） | 7 | ui / frontend / 前端 |
| `docs/architecture/`（图谱） | 6 | graph / 图谱 / knowledge |
| `docs/architecture/` | 6 | architecture / 架构 / design |
| `docs/voice/`（新建） | 4 | voice / tts / audio / 语音 |
| `docs/plugins-skills/`（新建） | 3 | plugin / skill / 技能 |
| `docs/harmony/`（新建） | 2 | harmony / 鸿蒙 |

> 具体每篇文件的移动映射由 `scripts/reorg_docs.py --dry-run` 生成。

### 2.2 已识别的冗余簇（应删除/降级，非合并）

| 冗余簇 | 建议 | 动作 |
|--------|------|------|
| 记忆升级 6 篇：`memory-system-upgrade-plan-final.md`(权威) / `memory-system-upgrade-summary.md` / `neurova-memory-system-upgrade-technical.md` / `memory-nerf-upgrade-plan.md` / `nerf-memory-system-analysis.md` / `nerf-frontend-adaptation-summary.md` | 以 `-plan-final` 为 [权威]，其余标注"已被 final 取代"或删除 | 删除 4 篇重复，保留 final + 1 参考 |
| 竞品对标 16 篇（`*_vs_neurova_comparison.md` 等） | 全部为**研究参考**，不可作事实源 | 移入 `docs/research/`，不删 |
| grilling 评审 10 篇 | 架构评审轨迹 | 移入 `docs/architecture/grilling/`，结论回流权威文档 |
| `cognitive_graph_storage_architecture.md` ↔ `cognitive-graph-storage-architecture.md` | ⚠ 文件名仅连字符差异，但**内容不同**（一步到位 vs 分层设计），**不可合并** | 两篇均保留 |

### 2.1 主文档库 `docs/` 专题深潜（权威方向见第 1 节表）

| 文档 | 状态 | 归类 |
|------|------|------|
| `NEUROVA_CogArch_2.0.md` | **历史（2026-05-12 设计快照；§8.2 状态列不可作事实源，D9／§6-362）** | 认知层 |
| `docs/01-architecture/cognitive-component-table.md` | **[权威] 认知层现役组件表**（机器生成，逐格与生成器比对） | 认知层 |
| `docs/architecture/`（42 篇） | 参考 | 子系统设计集 |
| `认知_graph_storage_architecture.md` / `cognitive-graph-storage-architecture.md` | ⚠ 疑似重复，合并为 1 篇 | 知识图谱 |
| `cognitive-graph-one-step-design.md` | 参考 | 知识图谱 |
| `CONTEXT_CACHE_COMPRESSION.md` | 参考 | 上下文压缩 |
| `context_pool_settings_plan.md` | 参考 | 上下文池 |
| `living_context_pool_design.md` | 参考 | 上下文池 |
| `cross-channel-session-sync-design.md` | 参考 | 会话同步 |
| `session-sync-integration-complete.md` | 历史 | 会话同步 |
| `docs/01-architecture/02-memory-system.md` | **[权威] 记忆架构** | 记忆 |
| `docs/01-architecture/memory/retrieval-spine.md` | **[权威] 检索脊柱**（在服链路，逐环节 `file:line`） | 记忆 |
| `memory-system-upgrade-plan-final.md` | **[权威] 记忆升级计划**（计划口径，非架构事实源） | 记忆 |
| `memory-system-upgrade-summary.md` | 历史 | 记忆 |
| `neurova-memory-system-upgrade-technical.md` | 参考 | 记忆 |
| `memory-nerf-upgrade-plan.md` | 参考 | 记忆 |
| `nerf-memory-system-analysis.md` | 参考 | 记忆 |
| `nerf-frontend-adaptation-summary.md` | 参考 | 前端记忆 |
| `thought-memory-upgrade-dev-doc.md` | 参考 | Thought 记忆 |
| `neurova-evocate-implementation-summary.md` | 参考 | Evocate |
| `neurova-evocate-loop-diagnosis.md` | 历史 | Evocate |
| `plugin-architecture-design.md` | 参考 | 插件 |
| `unified-storage-format-discussion.md` | 参考 | 存储 |
| `meta-skill-integration-design.md` | 参考 | 技能 |
| `voice_system_architecture_overview.md` | **[权威] 语音** | 语音 |
| `initialization_manager_implementation.md` | 参考 | 初始化 |
| `iteration-plan-channel-plugin-moe.md` | 历史 | 渠道 |
| `moe-based-dependency-extraction.md` | 参考 | MoE |
| `workflow-editor-deep-integration.md` | 参考 | 工作流 |
| `evolution_init_order_fix.md` | 历史 | 进化 |
| `neurloop-integration-fixes.md` | 历史 | 闭环 |
| `api_architecture_analysis.md` / `api_architecture_fix_summary.md` | 参考 | API 架构 |
| `数据库图谱.md` / `源码图谱.md` | 参考 | 图谱 |

### 2.2 子系统深潜系列（grilling-*，架构评审留痕，全部为参考）

`grilling-context-deep.md`、`grilling-context-facade.md`、`grilling-evolution-deep.md`、
`grilling-evolution-facade.md`、`grilling-knowledge-bridge-deep.md`、`grilling-memory-knowledge-bridge.md`、
`grilling-memory-retrieval-facade-deep.md`、`grilling-memory-retrieval-facade.md`、
`grilling-tool-lifecycle-deep.md`、`grilling-tool-lifecycle-manager.md`

> 这些是对 context / evolution / knowledge-bridge / memory-retrieval / tool-lifecycle 的"深度 vs 门面"双视角评审。
> 结论应回流到对应子系统 [权威] 文档，本系列仅保留作评审轨迹。

### 2.3 Bug 修复史（变更日志，按时间归档，不合并）

- `bugfix-*.md`（约 30 篇）：逐次修复记录，命名 `bugfix-<模块>-<问题>.md`
- `bug-audit-report-2026-06-25.md`、`bugfix-report-2026-06-25.md`、`bugfix-p1-p2-report.md`
- `p1-fixes-summary.md`、`frontend-ui-bug-audit-2026-06-25.md`

> 规则：新修复追加新 `bugfix-*.md`，不得改写历史文件。

### 2.4 竞品 / 外部对标（研究参考，不可作为事实源）

`bailongma_vs_neurova_comparison.md`、、
`mflow_vs_neurova_memory_comparison.md`、`sirchmunk_vs_neurova_comparison.md`、
`CODE_BASED_COMPARISON_ANALYSIS.md`、`CODE_BASED_COMPREHENSIVE_COMPARISON.md`、
`agent-memory-cutting-edge-research-2026.md`、`funasr-vs-moss-audio-comparison.md`、
`moss-audio-completeness-check.md`、`neurova_skill_vs_meta_skill_comparison.md`、
[`08-research/zcode_vs_neurova_tool_loop_comparison_2026-09-26.md`](08-research/zcode_vs_neurova_tool_loop_comparison_2026-09-26.md)（外部编码代理工具调用与迭代循环对标，含 G1–G8 缺口复验与本文自我更正记录）
[`08-research/rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`](08-research/rsiagent_vs_neurova_rsi_comparison_2026-10-06.md)（外部 RSI 框架与 Neurova 演进系统代码级对比：十维加权评分 7.9 vs 6.7、习得点清单与本仓待修点登记，研究参考）
[`08-research/skillglow_vs_neurova_skill_consolidation_2026-10-07.md`](08-research/skillglow_vs_neurova_skill_consolidation_2026-10-07.md)（外部技能沉淀论文与 Neurova 技能域对比：吸收账本迁移、召回预检、全自动整合 commit gate 的落地登记与规则修订记录，研究参考）
[`08-research/designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md`](08-research/designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md)（Designer-RSI 论文与 Neurova 程序性记忆对照：例级成对回放闸 P1-A、成败对照 P1-B、真轨迹核验面 P1-C 与「能不能撤掉人在环」的四条前置条件，研究参考）
[`08-research/dramaclaw_vs_neurova_aigc_pipeline_comparison_2026-10-08.md`](08-research/dramaclaw_vs_neurova_aigc_pipeline_comparison_2026-10-08.md)（外部自托管短剧流水线 dramaclaw 与 Neurova AIGC 管线代码级对比：含整合否决裁决的三道闸取证，研究参考）
[`08-research/semantica_vs_neurova_knowledge_graph_comparison_2026-10-09.md`](08-research/semantica_vs_neurova_knowledge_graph_comparison_2026-10-09.md)（外部图谱工具链 Semantica 与 Neurova 知识库/知识图谱代码级对比：22.4 万行的「账面功能 vs 已接线」逐层清点、本仓五条自有断点 N1–N6 与候选 K1–K8，研究参考）
[`08-research/modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md`](08-research/modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md)（ModularRSI 论文与 Neurova harness 层自改进对照：可演化面覆盖面 M-A、联合轮归因 M-B、跨基座迁移 M-C、难度维只写不读 M-D、环节归因 M-E，只记两篇 RSI 前作未覆盖的增量，研究参考）
[`08-research/harness2_vs_neurova_recursive_harness_comparison_2026-10-21.md`](08-research/harness2_vs_neurova_recursive_harness_comparison_2026-10-21.md)（google-research/harness2 与 Neurova 递归 harness 优化代码级对比：十维加权（权重 100% 归一）当前评估 7.8 vs 8.1、生产就绪度单列、本仓断点 N1–N8 与候选 C1–C8，N1–N8 已落地/部分落地、闭环 A–D 与 N6/C6/N8、完整工具 trace、跨域 UI、产物二进制证据与独立采纳流已落，研究参考）
[`08-research/tmem_paper_vs_neurova_associative_memory_comparison_2026-10-21.md`](08-research/tmem_paper_vs_neurova_associative_memory_comparison_2026-10-21.md)（T-Mem 论文与 Neurova 记忆系统代码级对比：无表面重合联想召回的可达性上界、写入侧预演成本复算、本仓断点 D1–D7 与候选 TM-1..TM-6、不照搬清单，研究参考）
[`08-research/kweaver_vs_neurova_ontology_knowledge_base_comparison_2026-11-05.md`](08-research/kweaver_vs_neurova_ontology_knowledge_base_comparison_2026-11-05.md)（爱数 KWeaver DIP 公开生态与 Neurova ontology 知识库代码级对比：主仓 kweaver/kweaver-core 均 404、公开五仓快照（decision-agent 已弃用/dolphin/dsg/studio/旧文档归档）；十维加权 7.5 vs 4.4（公开可得性折扣声明）；本仓新断点 N1–N2（cognitive_security/data_masking 零生产消费，主代理亲验）与候选 C1–C6（净接线二＋新能力四）＋不采纳两条，研究参考）
[`08-research/sag_vs_neurova_event_graph_retrieval_comparison_2026-11-05.md`](08-research/sag_vs_neurova_event_graph_retrieval_comparison_2026-11-05.md)（Zleap-AI SAG（SQL-Retrieval Augmented Generation，事件-实体索引＋查询时 SQL JOIN 动态超边）与 Neurova 知识检索代码级对比：应用壳 MIT 开源（v1.9.2/1030 后端测试）但论文核心引擎闭源（zleap-sag==0.15.0 PyPI wheel）；宣传数字对账——Recall@2 79.30/68.14 出自 v1 表 2 的相对提升换算、「数亿级生产验证」双零命中；检索子域八维加权 8.3 vs 6.6（黑盒折扣声明）；断点 N3 已接线（多跳事实种子锚点 1ff64cfe0）、候选 C1–C5 已全部落地（C1 实测转正 shadow→on 0416a9031；C2/C3 净接线 6632c6560；C4/C5 新能力 env 门控默认关 21732f012/9e4b0ad57）＋不采纳三条，研究参考）
[`08-research/ontology_landing_video_vs_neurova_knowledge_semantic_stack_comparison_2026-11-05.md`](08-research/ontology_landing_video_vs_neurova_knowledge_semantic_stack_comparison_2026-11-05.md)（视频号知识视频《Ontology 本体落地》参考架构与 Neurova 知识语义栈框架适配评测：对象为教学参考架构非产品，只评本方十维加权实现度 6.8/10（适用域折扣声明）——本体语义层与入库纪律超出参考架构（9 档），短板集中于 OWL 式条件类自动归入、标准栈互通、访问层统一四动词；候选 V1–V4＋缓办 V5＋不采纳三条，无新增断点，研究参考）

### 2.5 审计报告 / 验证（历史留痕）

`code-review-report.md`、`navigation-audit-report.md`、`navigation-fix-summary.md`、
`audit-skeleton-and-spec-compliance.md`、`external_cli_integration_report.md`、
`voice_system_cross_validation_report.md`、`voice_system_validation_summary.md`、
`voice-engine-integration-summary.md`、`test-results-2026-06-11.md`、
`协作模块完整性检查报告.md`、`cache-cleanup-report.md`、`skeleton_files_implementation_progress.md`

### 2.6 产品 / 品牌 / 鸿蒙端

`BRAND_GUIDELINES.md`、`BRAND_UPDATE.md`、`NEUROVA_BRAND.md`、`NEUROVA_LAUNCH.md`、
`PRODUCT_GUIDE.md`、`UI_FRAMEWORK_GUIDE.md`、
`HARMONYOS_DESIGN.md`、`HARMONYOS_PRIVACY_POLICY.md`、`HARMONYOS_RELEASE_CHECKLIST.md`、`HARMONYOS_SIGNING_GUIDE.md`

### 2.7 技能 / 插件实现

`plugins_modules_implementation_summary.md`、`skills_modules_implementation_summary.md`、
`SKILL_VERSION_MANAGEMENT.md`、`github_push_skill_summary.md`、`github_push_skill_usage.md`

### 2.8 前端 / UI

`FRONTEND_DEVELOPMENT_REPORT_2026-05-14.md`、`login-register-logo-replacement.md`、
`bugfix-card-text-clipping.md`、`bugfix-popup-container.md`、`nerf-frontend-adaptation-summary.md`

### 2.9 Neurflow 工作流

`neurflow-dev-spec.md`、`neurflow-medium-fixes-summary.md`、`neurflow-progress.md`

### 2.10 杂项 / 规划

`DOCS_ALIGNMENT_PLAN.md`、`docs-alignment-summary-2026-06-07.md`、`cli_usage.md`、
`jianying_comfyui_cli_integration.md`、`stub-cleanup-plan.md`、
`token-estimation-inconsistency-analysis.md`、`_git_automation.py`（脚本，非文档）

`specs/2026-11-05-ontology-cq.md`（本体能力问题目录（CQ）与需求追溯：P1×9 全部带查询与测试（追溯守卫 `test_cqTraceability.py` 零孤儿/状态闭集/P1 完整性）、P2×2 随 B10/B11 落；领域边界＋术语表随附；CQ 驱动是 L0 的立身判据）

`specs/2026-10-23-knowledge-governance-remaining-design.md`（知识治理四项缺口：人工接管／一般拒答／token 归因／大语料索引；设计、拍板与实施终态，含飞书服务台/微信客服/MQTT producer 与 ANN 1M 实测）

`specs/2026-10-23-knowledge-system-upgrade-design.md`（知识库系统升级：对照目标架构的差距矩阵、文档标准化/OCR、企微入站、冲突矩阵/精排/版本、存储与多 Agent 分期、验收与待拍板项）

`specs/2026-10-24-multiformat-kb-upgrade-plan.md`（多格式文档知识库升级计划：差距矩阵、去重/OCR provider/元数据过滤、图谱并入混合检索两阶段融合，以及 2D/3D 图谱建模工作台取代只读图谱页的分阶段设计）

`specs/2026-10-30-knowledge-retrieval-accuracy-upgrade-plan.md`（知识库检索准确性与事实守卫升级计划：查询侧别名归一、检索脱靶登记与审批闭环、图谱影子读数与转正判据、同名多口径主动澄清、生成后事实回查守卫；五批分期、每批红灯判据与拍板项；**已实施**，批次提交/偏差归一/live-verify 补证见文内 §11 实施台账）

`04-plans/2026-10-24-移动端扫码经中继连接无固定IP服务端设计方案.md`（移动端扫码经自研中继连无固定 IP 服务端：凭据与地址分离、中继控制面/数据面选型、四条互不合并的状态机与非法迁移矩阵、Web＋Harmony 两端 UI、代理头缺失致限流失明的实测现状、S0–S3 分期与每批红灯判据；设计已确认未开工）

`specs/2026-11-03-提示面资产化与出口审批收口升级设计.md`（提示面整面预算棘轮＋段单源扩展、审批等待双链收口（一次一问/线程不泄漏/未送达不计时/持久化复活）、出口禁拆与系统文案预算、入站队列不可用方向修正、deriveRunStage 钉格补齐、出口失败片归宿、渠道错误文案单源、统一指挥判据（单一判定落点＋判定台账＋渠道身份贯通）；八批分期、每批红灯判据与明确不做清单；六项拍板已裁（2026-11-03）；八批全部实施（E/A/F/G/B1/B2/C+D/B3/H），H3 身份贯通与 D 前端接线为在册尾巴格）

`specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md`（知识库条目三时间戳细分（源创建/源修改/入库）与时间感知消费面：契约只增（`source_created_at/source_modified_at`，`created_at` 语义钉死＝入库时间）、同源更新重入库（覆盖＋revisions＋保留 knowledge_id）、冲突「新者胜」建议读数（不改判）、搜索时间范围过滤（repository 内存层，无源时间条目如实排除）；三拍板已裁（T-C/T-D/T-E）；TA/TB/TC/TD① 已实施，实施终态与设计偏差见文内 §5；TD② recency 打分可配默认关、FTS 源时间列、facts 层源钟为在册尾巴）

`specs/2026-11-05-ontology-capability-upgrade-plan.md`（本体语义栈能力升级计划：依据 08-research《Ontology 本体落地》评测（6.8/10）的七批改进方案——B1 条件类推导模板（新规则形状不破 Datalog 片段边界、观察态灰度、走 admission 咽喉与推导账本）/B2 validate dry-run 出口/B3 四动词统一门面 `/v1/knowledge/access/*` 纯转发/B4 推理结论溯源进对话/B5 Turtle 全库导出＋rdflib 可选对拍/B6 本体构建流水线（挂 knowledge_baselines）/B7 效率可用性实测先行＋图谱影子转正执行；分数投影 6.8→≈7.8（逐维明细）；四项拍板已裁（2026-11-05 全按推荐：条件类走 ontology_rules 形状枚举扩展、推导默认观察态灰度、四动词门面立项、溯源后端契约先行＋行内徽标）；不纳入 Planner 抽象、企业数据源、OWL DL/SPARQL/SHACL；每批红灯判据、live-verify 9527 验收门与台账落格约定）

`specs/2026-11-05-知识库未接线与默认关闭修复计划.md`（知识库未接线与默认关闭能力修复计划：AST 静态导入图＋环境变量默认值复算，4 处死代码（`knowledge/config.py`、联邦 KB／多库路由、`FoundationReconciler`；`LegacyFactBackfill` 判“保持不启用”）、4 处半接线（`memory_links` 只写不读、gaps/learn 恒 501、非飞书同步被拒、access/integration 仓内零消费者）、21 项默认关闭能力；逐项给出原功能／关键入口／来历／现役替代／判定三态、P0–P3 批次、红→绿与 live-verify 判据、七项拍板项及影响面（D-1 已裁 A：远程库进对话，D-3/D-5 为建议待确认）；明确不重开 011 已否证的“事实池＋叙述池秩交织”，`FactSurface` 只保留零锚点种子与治理富化）

`specs/2026-11-04-agent-node-authoring-design.md`（Agent 自主节点编排与工作流修改能力设计：区分节点类型/节点实例/画布/工作流定义四层写入面；现状 10 个 canvas 工具、注册表 `sync_all` 缺口、`list_nodes` 缺参数契约、自定义节点仅 HTTP、已发布定义无 Agent 写口；拟新增 `canvas_list_nodes` 扩展/`node_schema`、`sync_nodes`、`custom_node_*`（L1/L2）、`workflow_definition_*`、环境预检与自愈闭环；含 RSI 复用边界（复用提案/回滚/评测与 EKB，不把 RSIOrchestrator 当节点修复调度器）、安全闸门、N0–N5 分期与每批红灯判据；**六项已拍板**：custom 默认 draft／已发布可直接改但先有安全版本可回滚／`env_requirements` 随 NodeDefinition／Agent 轮次编排／按任务批次一次审批／复用 RSI 基础设施与 EKB；**N0 交互门**：一句话需求先经 BuildSession 就绪门，缺信息/凭据走面板（secret 只写 SecretStore），构建中疑问/选择同样面板，未 ready 服务端拒绝写入；**N0/N1/N2/N3/N4/N5 已实施（2026-11-04：BuildSession/ask_user/构建门/面板/secret；节点参数与环境自描述；sync_nodes；node_schema；custom draft/批次激活；`workflows.safe_version` 基线/回填、`workflow_definition_get/update/duplicate`、`workflow_rollback/publish/execute`、定义校验与审计、DRAFT 草稿试跑；`node_env_preflight`、`workflow_repair` 自愈循环（DRAFT 隔离/RSI 快照与提案/EKB/5 轮/画布配置提交）、引擎内层 failed 不再假成功；B5 画布批量一次事务提交 `canvas_apply_batch`（失败整批不落盘/版本不变）；§12.4 交互回答后服务端自动拉起 Agent 回合（无聊天会话时降级前端提示）；批次补偿日志 + `build_batch_compensate`（跨 surface 半批可显式回滚）；换节点候选默认审批（`allow_replacements`））**；§9.1 实现细节已定（`safe_version` 走 workflows 加列／批次由 Agent 轮次创建／草稿用工作流 DRAFT 副本／自愈最多 5 轮／EKB 统一 `workflow_node_repair`）；§9.2 列 B1–B11 实施前阻塞点（BuildSession 触发、长等待 pending/resume、画布 staging、DRAFT 执行工具、批次原子性、迁移、前端 secret、权限、RSI 接线、真账号、分段提交））

`specs/2026-11-07-enterprise-source-connectors-plan.md`（企业源真连接器立项方案：兑现台账 §6-561/§6-564「另立项」——现状走查（REST 提交面→编译期校验→v34 配置表→映射→admission 唯一咽喉链路全景；`ingestBatch` 生产调用面为零、适配器注册表生产恒空，今天唯一喂行方式是 `FakeEnterpriseAdapter` 测试桩）；零第三方依赖约束下的候选取舍（以 `requirements.txt` 现值为准：CSV/TSV/JSON/JSONL 文件行源、目录轮询、SQLite 旁库只读挂接、HTTP 拉取（httpx 已在依赖清单且生产在用）进三批计划，Oracle/MSSQL/PG 直连、ERP SDK、Kafka/CDC 因驱动/外部服务违反六决策缓办并给未来放开约束的接法）；三批实施每批验收判据＋红绿落点 `tests/unit/knowledge/enterprise/`＋真后端 9527 活体验证路径；风险与回退（fail-soft 让路/大文件限流/编码方言不猜/增量重入幂等/与三时间戳 facts 源钟尾巴的对齐裁量）；三项待拍板各带影响面）

`specs/2026-11-07-wecom-chat-archive-history-source-plan.md`（企微聊天**历史消息**摄取方案，批 C7，**四项已裁：甲案＋A/B/C/D 各按推荐（2026-11-08），**C7a/C7b/C7c 已落格（台账 §6-584..588：凭据面/读取面与投影表/白名单与 worker 与水位读数/正文分档/媒体触发面）；页面读数缓办（i18n 撞车解除后小批）、真 SDK 部署 live-verify 双态登记**：兑现 §2.4-3/C6 留下的「历史拉取缺口」一格——两条通道实状对照（现役捕获面只覆盖「机器人进群后回调可达」的消息 vs 会话内容存档按 `seq` 拉已购席位且已同意成员的会话）；唯一合规历史通道选型与明确不成立项（`get_groupmsg` 是应用群发记录不是成员历史、微信侧无官方通道；**HTTP/专区面已核**：ISV `chatdata/sync_msg` 对自建应用/代开发/第三方一律「暂不支持」，专区 `sync_msg` 官方写明「通过 SDK 调用」且只回元数据＋`service_encrypt_info` **不带正文** ⇒ 只有经典 C SDK 那一面能把正文带回本仓）；客户侧前置逐条给 health 可读形态（席位/**存档专用 Secret**（管理工具→聊天内容存档，非应用 Secret）/RSA **2048 位**密钥对与 `publickey_ver` 轮换/出口 IP 白名单/成员同意/**≤5 天窗口须定期拉**/专区 2026-06-15 起 90 天定期授权过期 errcode 48002——并写明「按席位与同意过滤的子集」不得报成全量）；架构**已裁甲案**：读取面与存档凭据归**通道层**、落 append-only 投影表、企业源侧仍零凭据只读（乙案适配器直持私钥被否，理由是复现第二套凭据生命周期线）；**解密链更正**：`GetChatData` 从 `seq+1` 起、`limit≤1000`、`≤4000 次/分钟`，`encrypt_random_key` base64→**RSA PKCS1**→交官方 `DecryptData` 出明文，**AES 半边在 SDK 内、本仓不实现**（初稿「扩展单源抄 AES」作废，只新增 RSA 半边落 `wechat_kf_crypto` 同模块）；`sdkfileid` 与捕获面 `media_id` 引用形态不同须点名、媒体走 `GetMediaData` 分片续传；**5 天硬窗口推翻「可回溯」前提** ⇒「历史」＝≤5 天＋本地累积、投影表从可选优化升为必需设施、`archive.backfill` 由「默认关」改**默认开**（不拉即永久丢）、隐私缓解只能靠落库前过滤、常驻周期须远小于 5 天且 health 报水位落后；量与节流（单轮 20×200＝4000 行是自我节流，与官方 4000 次/分钟不是一回事）；正文落点**已裁分档最小版**（facts 承结构化、条目链承正文——十万级行灌 facts 不可逆）；附件触发**已裁先只落引用**、媒体面另批；隐私/明文驻留/撤回不回改/删连接器不级联清除四风险与两挡回退；**§6.1 凭据面定形：配置只放指针**（`archiveSdkPath`/`archiveSecretEnv`/`archivePrivateKeys`＝版本→路径），理由是 `GET /v1/channel-config/{type}` 把 `extra` 原样回读、且新增封存键名要同步 `CREDENTIAL_KEY_NAMES`＋前端密码字段表＋11 语言（并发会话正在改 i18n）；私钥判据＝存在可读→RSA 2048→POSIX owner-only，**Windows 无权限位则如实点名 NTFS ACL 不假通过**；**退役恒假探测**：官方只分发 C 动态库（linux x86/arm、windows，v3.0 依赖 openssl 3.0）、**无官方 Python 包** ⇒ 仓内 `WeWorkFinanceSdk` 模块名不对应任何可安装件、那次 `importlib` 恒 ImportError，C7a 换原生库可达性探测并自写 `ctypes` 薄包装（仓内零先例、零新增 pip 件、不引第三方包装）；判据与假 SDK 夹具红绿落点按批分列＋无席位时双态登记；另顺手闭合 §6-576 留裁定项③（ingress env 名已在 `channel_ingress_queue.py:41` 常量化）、**撞车前置已解除**（`channels/wecom.py` 协议合规批落在 `612caf931`／台账 `eb97f4db0` §6-583）；**新增 §16 官方文档实证**（路径 91774/99968/97240/99670/101545，浏览器渲染取全文）＋**四条**被推翻前提的更正对照表）

`specs/2026-11-07-用户分组部门化与知识库分类隔离设计.md`（用户分组（`/v1/groups` 正主）部门化＋知识库自定义分类隔离：分类注册表 `knowledge_categories`、分组模型加 `allowed_categories/default_category/parent_group_id`（单亲树禁环）、分区停在部门根而子部门用分类路径并集收窄、登录签发 tenant claim 打通休眠的 tenant 分区键、执行点收在 `visible_items`/`can_view` 服务端单点（聊天召回与用户 API 双通道自动覆盖）、agent 绑组＋chat 部门根对账 403＋kb_builder 补 tenant 修断点、死端点 `/v1/user-groups` 退役、本体零 schema 改动＋三处既有 tenant 缺口顺手修、前端四页逐一对齐（GroupPage 树形＋分类绑定/EnhancedUserPage 所属分组/AgentFormPage 分组选择/KnowledgePage 分类源与导入分类）；六项拍板已裁（T-A..T-F，2026-11-07 全按推荐）；**A/B/C/D/E/F1/F2 七批已全部实施（2026-11-07），live-verify 发现并修复路由遮蔽与分类清单过滤两缺口，实施终态见文内 §7**）



> 说明：`04-plans/` 的逐条登记在 [`docs/0-index/README.md`](0-index/README.md) 的「04-plans 实施计划」节，本节只收录跨领域入口与本目录内已归集条目。

## 3. 已识别的重复/待合并项（下一步清理）

| 重复簇 | 建议 | 动作 |
|--------|------|------|
| `cognitive_graph_storage_architecture.md`（一步到位方案）↔ `cognitive-graph-storage-architecture.md`（分层设计 v1.0） | ⚠ 文件名仅连字符差异，但**内容不同**：前者为单步替换方案，后者为分层深度设计（基于 unified-storage-format-discussion） | **两篇均保留**，不可合并/删除 |
| 记忆升级 6 篇（`memory-system-upgrade-*` / `neurova-memory-system-upgrade-*` / `memory-nerf-*` / `nerf-memory-*`） | 以 `memory-system-upgrade-plan-final.md` 为 [权威] | 其余标注"已被 final 取代" |
| `thought-memory-upgrade-dev-doc.md` 与 Evocate 集群 | 归入记忆领域参考 | 链接到 2.1 |
| 与 | 一篇集成、一篇对比，保留两者 | 已分类 |

## 4. 文档管理规则（保持单一事实源）

1. **每个领域只允许一个 [权威] 文档**。新增事实必须更新权威文档，而非新建平行文件。
2. **历史/评审/对标类**保留原文件，但不得被当作事实源引用。
3. **禁止同名近似文件**（如连字符差异）。新建前先检索本索引。
4. **根目录不再堆砌**：新文档按领域落入 `docs/<领域>/` 子目录，并在本索引登记。
5. 本索引由人工/脚本在每次文档变更时同步更新；[`docs/INDEX.md`](INDEX.md) 是文档体系的唯一导航事实源。

---
最后更新：2026-08-23 ｜ 文档总数：约 296 篇（含 `docs/` 子目录）
