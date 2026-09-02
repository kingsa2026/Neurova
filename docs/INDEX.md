# Neurova 文档单一事实源（Documentation Single Source of Truth）

> 本文件是 Neurova 文档体系的**唯一权威入口**。所有文档的阅读顺序、归属领域、权威版本都以此为准。
> 新增或移动任何文档前，必须先更新本索引。

## 0. 阅读顺序（新人必读）

1. **`/CONTEXT.md`** —— 项目总览、核心架构、ChatPipeline、记忆温度系统（最高权威，先于本目录）
2. **`/AGENTS.md`** —— 开发者快速上手与关键约定
3. 本索引 `docs/INDEX.md` —— 按领域定位详细文档
4. 进入具体领域后，只读该领域的 **[权威]** 文档，历史/对比类仅作参考

## 1. 文档归属领域与权威文档

每个领域只保留 **一个 [权威]** 文档作为事实源，其余为参考或历史归档。

| 领域 | 权威文档 | 说明 |
|------|----------|------|
| 整体架构 | `/CONTEXT.md`（根）+ `docs/architecture/OVERVIEW.md` | 系统级事实源 |
| 架构决策(ADR) | `docs/adr/` | 已编号的决策记录，不可覆盖 |
| API 规范 | `docs/api/` + `docs/API_REFERENCE.md` | 接口事实源 |
| 记忆系统 | `docs/memory/` | 记忆层事实源 |
| 认知架构 | `NEUROVA_CogArch_2.0.md` | 认知层演进总纲 |
| 开发进度 | `docs/dev_progress/` | 迭代记录（历史） |
| Bug 修复史 | 根目录 `bugfix-*.md` 集群 | 变更日志（历史，归档用） |
| 配置 | `docs/configuration/` | 部署/配置事实源 |
| 国际化 | `docs/i18n/` | 多语言事实源 |
| 产品/品牌 | `PRODUCT_GUIDE.md` / `NEUROVA_BRAND.md` | 对外信息事实源 |
| 鸿蒙端 | `HARMONYOS_*.md` | NeurovaHarmony 端事实源 |

## 2. 文档真实分布（实测，2026-08-23）

> 说明：扫描时混入的 `.venv/`(102)、`.trae/`(22)、`flow-kb-sdk/`(18) 等是**虚拟环境/第三方工具缓存**，
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

> 具体每篇文件的移动映射由 `scripts/reorg_docs.py --dry-run` 生成（见 `docs/REORG_PLAN.md`）。

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
| `NEUROVA_CogArch_2.0.md` | **[权威] 认知架构** | 认知层 |
| `docs/architecture/`（42 篇） | 参考 | 子系统设计集 |
| `认知_graph_storage_architecture.md` / `cognitive-graph-storage-architecture.md` | ⚠ 疑似重复，合并为 1 篇 | 知识图谱 |
| `cognitive-graph-one-step-design.md` | 参考 | 知识图谱 |
| `CONTEXT_CACHE_COMPRESSION.md` | 参考 | 上下文压缩 |
| `context_pool_settings_plan.md` | 参考 | 上下文池 |
| `living_context_pool_design.md` | 参考 | 上下文池 |
| `cross-channel-session-sync-design.md` | 参考 | 会话同步 |
| `session-sync-integration-complete.md` | 历史 | 会话同步 |
| `memory-system-upgrade-plan-final.md` | **[权威] 记忆升级** | 记忆 |
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

`bailongma_vs_neurova_comparison.md`、`comparison-openmythos-vs-neurova.md`、
`mflow_vs_neurova_memory_comparison.md`、`sirchmunk_vs_neurova_comparison.md`、
`supermemory-vs-neurova_comparison.md`、`tencentdb_vs_neurova_comparison.md`、
`QwenPaw_Neurova_Comparison_Analysis.md`、`QwenPaw_Integration_Summary.md`、
`sim-studio-analysis-for-neurova.md`、`sim-studio-frontend-analysis.md`、
`CODE_BASED_COMPARISON_ANALYSIS.md`、`CODE_BASED_COMPREHENSIVE_COMPARISON.md`、
`agent-memory-cutting-edge-research-2026.md`、`funasr-vs-moss-audio-comparison.md`、
`moss-audio-completeness-check.md`、`neurova_skill_vs_meta_skill_comparison.md`

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

## 3. 已识别的重复/待合并项（下一步清理）

| 重复簇 | 建议 | 动作 |
|--------|------|------|
| `cognitive_graph_storage_architecture.md`（一步到位方案）↔ `cognitive-graph-storage-architecture.md`（分层设计 v1.0） | ⚠ 文件名仅连字符差异，但**内容不同**：前者为单步替换方案，后者为分层深度设计（基于 unified-storage-format-discussion） | **两篇均保留**，不可合并/删除 |
| 记忆升级 6 篇（`memory-system-upgrade-*` / `neurova-memory-system-upgrade-*` / `memory-nerf-*` / `nerf-memory-*`） | 以 `memory-system-upgrade-plan-final.md` 为 [权威] | 其余标注"已被 final 取代" |
| `thought-memory-upgrade-dev-doc.md` 与 Evocate 集群 | 归入记忆领域参考 | 链接到 2.1 |
| `QwenPaw_Integration_Summary.md` 与 `QwenPaw_Neurova_Comparison_Analysis.md` | 一篇集成、一篇对比，保留两者 | 已分类 |

## 4. 文档管理规则（保持单一事实源）

1. **每个领域只允许一个 [权威] 文档**。新增事实必须更新权威文档，而非新建平行文件。
2. **历史/评审/对标类**保留原文件，但不得被当作事实源引用。
3. **禁止同名近似文件**（如连字符差异）。新建前先检索本索引。
4. **根目录不再堆砌**：新文档按领域落入 `docs/<领域>/` 子目录，并在本索引登记。
5. 本索引由人工/脚本在每次文档变更时同步更新；`docs/INDEX.md` 是文档体系的唯一导航事实源。

---
最后更新：2026-08-23 ｜ 文档总数：约 296 篇（含 `docs/` 子目录）
