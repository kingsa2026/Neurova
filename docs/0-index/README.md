# Neurova 文档总索引

> 版本: v1.0.0-beta1 · 中文名: 智星 · 更新时间: 2026-08-31
> 本索引是 `docs/` 目录的唯一入口。功能状态标注基于对 `neurova/` 代码库的逐项核对。

## 快速导航

| 入口 | 路径 | 说明 |
|------|------|------|
| 项目 README | [README.md](../../README.md) | 项目概述、快速开始、核心特性 |
| 项目上下文 | [CONTEXT.md](../CONTEXT.md) | 架构概览、技术栈、设计规则 |
| 功能模块矩阵 | [见下](#功能模块矩阵) | 全部功能的状态对照 |
| API 参考 | [API_REFERENCE.md](../02-api/API_REFERENCE.md) | 82 端点模块参考 |

---

## 功能模块矩阵

状态说明: ✅ 已实现 | 🟡 部分实现 | ⬜ 未实现/骨架

### 认知层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 记忆系统（17 维分类 + 温度引擎） | ✅ | `cognitive_layers/memory_layer/` | [02-memory-system](../01-architecture/02-memory-system.md) |
| NeRF 增强记忆检索（六通道体积渲染） | ✅ | `neurova_recall.py` `volume_renderer.py` `positional_encoding.py` `unified_retriever.py` | [16-vector-retrieval-system](../01-architecture/16-vector-retrieval-system.md) |
| 记忆温度机制（遗忘曲线 + 固化） | ✅ | `temperature.py` | [12-memory-temperature-mechanism](../01-architecture/12-memory-temperature-mechanism.md) |
| 睡眠整理（记忆巩固 + 梦境） | ✅ | `sleep.py` `sleep_adapter.py` `sleep_writeback.py` | [13-memory-intelligence-enhancements](../01-architecture/13-memory-intelligence-enhancements.md) |
| 情感中枢引擎（四层 17 种情感） | ✅ | `cognitive_layers/emotion_context_layer/emotion_hub_engine.py` | [15-emotion-resonance-engine](../01-architecture/15-emotion-resonance-engine.md) |
| 自我进化引擎（人格/动机/宪法/反思） | 🟡 | `evolution/`（11 文件，遗传引擎部分） | [21-recursive-self-improvement](../01-architecture/21-recursive-self-improvement.md) |
| RSI 递归自我进化（8 组件） | ✅ | `evolution/rsi/`（orchestrator/convergence/ratchet 等） | [21-recursive-self-improvement-v1.3](../01-architecture/21-recursive-self-improvement-v1.3-summary.md) |
| 意图理解（QueryIntent 检测） | ✅ | `memory_layer/query_intent.py`（检测器） | [20-retrieval-context-injection](../01-architecture/20-retrieval-context-injection.md) |
| 知识库适配 + RAG | ✅ | `knowledge/`（repository/storage/vector_index） | [24-knowledge-isolation-rag](../01-architecture/24-knowledge-isolation-rag.md) |
| 知识图谱 | ✅ | `knowledge/graph_bridge.py` `knowledge_graph_api` | [cognitive-graph-storage-architecture](../01-architecture/cognitive-graph-storage-architecture.md) |
| 元认知监控 | ✅ | `cognitive_layers/metacognition_layer/` | [20-retrieval-context-injection](../01-architecture/20-retrieval-context-injection.md) |

### 执行层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 多 Agent 协作（四种模式） | ✅ | `collaboration/` | [04-multi-agent-collaboration](../01-architecture/04-multi-agent-collaboration.md) |
| NeurFlow 工作流引擎 | ✅ | `collaboration/neurflow/`（20+ 文件：dag/execution_engine/subflow/storage） | [22-neurflow-workflow-engine](../01-architecture/22-neurflow-workflow-engine.md) |
| 消息路由（事件总线） | ✅ | `collaboration/neurflow/` `core/` | [03-message-routing](../01-architecture/03-message-routing.md) |
| 任务调度（CognitionOrchestrator） | ✅ | `planning/` `scheduler/` | [07-implementation-plan](../01-architecture/07-implementation-plan.md) |
| 多语言 i18n | ✅ | `language/` + `NeurUI/src/i18n/`（11 语言） | [i18n/README.en](../03-user-guide/i18n/README.en.md) |
| 检查点/回滚（Agent 会话/工作区） | ⬜ | 无实现（仅工作流定义级版本快照） | [14a-version-control-evolution](../01-architecture/14a-version-control-evolution.md) 标注 |

### 工具层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| Skill 系统（注册表/版本/热插拔） | ✅ | `skills/` `skill_system/` | [05-skill-system](../01-architecture/05-skill-system.md) |
| Skill 协议兼容（OpenClaw/Qwenpaw） | ✅ | `skills/adapters/` | [05-skill-system](../01-architecture/05-skill-system.md) |
| 肌肉记忆（ToolMemory 三层） | 🟡 | `evolution/tool_weights.py` `tool_lifecycle.py`（L1/L2/L3 部分） | [tool-memory-muscle-analysis](../01-architecture/tool-memory-muscle-analysis.md) |
| MCP 集成 | ✅ | `tool_layers/mcp_client.py` `mcp_config.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| MCP 治理安全加固（P0 六项） | ✅ | `tool_layers/mcp_bootstrap.py` `security/url_guard.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| LLM Provider 管理（元数据/智能路由） | ✅ | `llm/provider_manager.py` `multi_model_client.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| LLM Router（多模态选择） | ✅ | `llm/llm_router.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| Computer Use（视觉理解） | ✅ | `computer_use/`（vision.py + vision_lite） | [01-core-architecture](../01-architecture/01-core-architecture.md) |
| 浏览器自动化（Camofox） | ✅ | `computer_use/browser_manager.py` | [agent-reach-integration](../01-architecture/agent-reach-integration.md) |
| web_reach 网络工具 | ✅ | `web_reach/`（reach.py + 5 工具） | [agent-reach-integration](../01-architecture/agent-reach-integration.md) |
| 插件系统 | ✅ | `plugins/` | [06-plugin-cli-system](../01-architecture/06-plugin-cli-system.md) |
| 工具编排（Tool Orchestrator） | ✅ | `tool_layers/tool_orchestrator.py` | [07-implementation-plan](../01-architecture/07-implementation-plan.md) |

### 接口层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 多渠道接入（14+ 渠道） | ✅ | `channels/`（42 py 文件） | [03-message-routing](../01-architecture/03-message-routing.md) |
| REST API（82 端点模块） | ✅ | `api/endpoints/` | [API_REFERENCE](../02-api/API_REFERENCE.md) |
| NeurUI 前端（60 页面） | ✅ | `NeurUI/src/pages/` | [UI_FRAMEWORK_GUIDE](../03-user-guide/UI_FRAMEWORK_GUIDE.md) |
| 上下文管线（活水上下文池） | 🟡 | `context/`（collector/compressor/converter），P1-1 已补齐溢出恢复/真摘要等 | [26-context-pipeline-p1](../01-architecture/26-context-pipeline-p1.md) |
| 上下文缓存与压缩 | ✅ | `context_cache.py` `context_compressor.py` | [CONTEXT_CACHE_COMPRESSION](../01-architecture/CONTEXT_CACHE_COMPRESSION.md) |
| 移动配对（QR + WebSocket） | ✅ | `api/endpoints/mobile_pairing.py` | [API_REFERENCE](../02-api/API_REFERENCE.md) |
| 睡眠系统管理（睡眠设置页） | ✅ | `cognitive_layers/memory_layer/sleep.py` | [02-memory-system](../01-architecture/02-memory-system.md) |

---

## 文档目录

### 01-architecture 架构设计

**核心架构（按阅读顺序）**：

1. [01-core-architecture.md](../01-architecture/01-core-architecture.md) — 整体架构、分层设计（核心）
2. [02-memory-system.md](../01-architecture/02-memory-system.md) — 记忆系统、17 维分类、LSM 存储
3. [03-message-routing.md](../01-architecture/03-message-routing.md) — 消息路由、14 渠道适配
4. [04-multi-agent-collaboration.md](../01-architecture/04-multi-agent-collaboration.md) — 多 Agent 协作、任务分配
5. [05-skill-system.md](../01-architecture/05-skill-system.md) — Skill 系统、协议兼容、沙箱
6. [06-plugin-cli-system.md](../01-architecture/06-plugin-cli-system.md) — 插件系统、CLI
7. [07-implementation-plan.md](../01-architecture/07-implementation-plan.md) — 实现计划、API 规范
8. [08-project-structure.md](../01-architecture/08-project-structure.md) — 项目结构、开发规范
9. [09-context-processing.md](../01-architecture/09-context-processing.md) — 上下文处理、窗口管理
10. [10-cache-mechanism.md](../01-architecture/10-cache-mechanism.md) — 读写缓存、批量写入
11. [11-database-architecture.md](../01-architecture/11-database-architecture.md) — 数据库主副表、关联索引
12. [12-memory-temperature-mechanism.md](../01-architecture/12-memory-temperature-mechanism.md) — 温度、遗忘曲线、固化
13. [13-memory-intelligence-enhancements.md](../01-architecture/13-memory-intelligence-enhancements.md) — 9 大认知机制
14. [14-proactive-recall-mechanism.md](../01-architecture/14-proactive-recall-mechanism.md) — 主动回忆
15. [14a-version-control-evolution.md](../01-architecture/14a-version-control-evolution.md) — 版本快照、演变追踪
16. [15-emotion-resonance-engine.md](../01-architecture/15-emotion-resonance-engine.md) — Agent 情感共鸣
17. [16-vector-retrieval-system.md](../01-architecture/16-vector-retrieval-system.md) — 语义嵌入、RRF 混合检索
18. [17-memory-compression-mechanism.md](../01-architecture/17-memory-compression-mechanism.md) — 层级/语义压缩
19. [18-memory-security-privacy.md](../01-architecture/18-memory-security-privacy.md) — 敏感检测、AES 加密
20. [19-time-awareness-mechanism.md](../01-architecture/19-time-awareness-mechanism.md) — 模式识别、事件预测
21. [20-retrieval-context-injection.md](../01-architecture/20-retrieval-context-injection.md) — 语义理解、上下文构建
22. [21-recursive-self-improvement.md](../01-architecture/21-recursive-self-improvement.md) — RSI 递归自我进化
23. [21-recursive-self-improvement-v1.3-summary.md](../01-architecture/21-recursive-self-improvement-v1.3-summary.md) — RSI v1.3 总结
24. [21-recursive-self-improvement-v1.2-summary.md](../01-architecture/21-recursive-self-improvement-v1.2-summary.md) — RSI v1.2 总结

**新功能架构文档（本轮新增）**：

- [22-neurflow-workflow-engine.md](../01-architecture/22-neurflow-workflow-engine.md) — NeurFlow 工作流引擎（IDE 化编排/触发器/版本回滚/subflow）
- [23-llm-provider-management.md](../01-architecture/23-llm-provider-management.md) — LLM 服务商管理（元数据化/智能路由/OpenCode）
- [24-knowledge-isolation-rag.md](../01-architecture/24-knowledge-isolation-rag.md) — 知识库隔离共享 + RAG 演进
- [25-mcp-governance.md](../01-architecture/25-mcp-governance.md) — MCP 治理安全加固（P0 六项）
- [26-context-pipeline-p1.md](../01-architecture/26-context-pipeline-p1.md) — 上下文管线 P1-1（六块短板补齐）

**专题设计（按主题）**：

| 文档 | 主题 |
|------|------|
| [living_context_pool_design.md](../01-architecture/living_context_pool_design.md) | 活水上下文池设计（五大活水特性） |
| [agent-reach-integration.md](../01-architecture/agent-reach-integration.md) | Agent-Reach 整合（web_reach 5 工具） |
| [agent-swarm-orchestration.md](../01-architecture/agent-swarm-orchestration.md) | Agent 集群编排 |
| [cross-channel-session-sync-design.md](../01-architecture/cross-channel-session-sync-design.md) | 跨渠道会话同步 |
| [channels.md](../01-architecture/channels.md) | 渠道适配说明 |
| [data-flow-analysis.md](../01-architecture/data-flow-analysis.md) | 数据流分析 |
| [plugin-architecture-design.md](../01-architecture/plugin-architecture-design.md) | 插件架构设计 |
| [nerf-memory-system-analysis.md](../01-architecture/nerf-memory-system-analysis.md) | NeRF 记忆系统分析 |
| [tts_architecture.md](../01-architecture/tts_architecture.md) | TTS 架构 |
| [voice_system_architecture_overview.md](../01-architecture/voice_system_architecture_overview.md) | 语音系统架构 |
| [tool-memory-muscle-analysis.md](../01-architecture/tool-memory-muscle-analysis.md) | 肌肉记忆分析 |
| [cognitive-graph-storage-architecture.md](../01-architecture/cognitive-graph-storage-architecture.md) | 认知图谱存储架构 |
| [unified-storage-format-discussion.md](../01-architecture/unified-storage-format-discussion.md) | 统一存储格式讨论 |

**ADR / 审计 / 记忆专题**：

- [adr/README.md](../01-architecture/adr/README.md) — 13 个架构决策记录（memory/recall/skill/market 等）
- [audit/three-tier-isolation-audit.md](../01-architecture/audit/three-tier-isolation-audit.md) — 三层隔离审计报告
- [audit/three-tier-isolation-fixes.md](../01-architecture/audit/three-tier-isolation-fixes.md) — 隔离修复记录
- [memory/memo-technical-overview.md](../01-architecture/memory/memo-technical-overview.md) — MeMo 技术综述
- [memory/neurova-memory-system-complete-technical-guide.md](../01-architecture/memory/neurova-memory-system-complete-technical-guide.md) — 记忆系统技术文档
- [memory/neRF-meMo-integration-analysis.md](../01-architecture/memory/neRF-meMo-integration-analysis.md) — NeRF-MeMo 集成分析

### 02-api API

- [API_REFERENCE.md](../02-api/API_REFERENCE.md) — 82 端点模块参考（核心）
- [API_CALLING_SPECIFICATION.md](../02-api/API_CALLING_SPECIFICATION.md) — 前端 API 调用规范
- [api_architecture_analysis.md](../02-api/api_architecture_analysis.md) — API 架构分析
- [console_api.md](../02-api/console_api.md) — 控制台 API

### 03-user-guide 用户指南

- [PRODUCT_GUIDE.md](../03-user-guide/PRODUCT_GUIDE.md) — 产品指南
- [cli_usage.md](../03-user-guide/cli_usage.md) — CLI 使用指南
- [工作流调试指南.md](../03-user-guide/工作流调试指南.md) — NeurFlow 工作流调试
- [触发器配置指南.md](../03-user-guide/触发器配置指南.md) — 触发器配置
- [心流知识库功能使用指南.md](../03-user-guide/心流知识库功能使用指南.md) — 知识库使用
- [UI_FRAMEWORK_GUIDE.md](../03-user-guide/UI_FRAMEWORK_GUIDE.md) — UI 框架指南
- [MIND_EXPANDER_USAGE.md](../03-user-guide/MIND_EXPANDER_USAGE.md) — Mind Expander 使用
- [HARMONYOS_DESIGN.md](../03-user-guide/HARMONYOS_DESIGN.md) — HarmonyOS 设计
- [HARMONYOS_PRIVACY_POLICY.md](../03-user-guide/HARMONYOS_PRIVACY_POLICY.md) — HarmonyOS 隐私政策
- [HARMONYOS_SIGNING_GUIDE.md](../03-user-guide/HARMONYOS_SIGNING_GUIDE.md) — HarmonyOS 签名指南
- [HARMONYOS_RELEASE_CHECKLIST.md](../03-user-guide/HARMONYOS_RELEASE_CHECKLIST.md) — HarmonyOS 发布清单
- [i18n/README.en.md](../03-user-guide/i18n/README.en.md) — README 英文版（另有 ar/fr/ja/ko/ru 5 种）

### 04-plans 实施计划

- [neurova-upgrade-p0-p1-implementation-steps.md](../04-plans/neurova-upgrade-p0-p1-implementation-steps.md) — 升级 P0-P1 实施步骤（TDD）
- [neurflow-ide-upgrade.md](../04-plans/neurflow-ide-upgrade.md) — NeurFlow IDE 升级计划
- [memory-nerf-upgrade-plan.md](../04-plans/memory-nerf-upgrade-plan.md) — NeRF 升级计划
- [memory-system-upgrade-plan-final.md](../04-plans/memory-system-upgrade-plan-final.md) — 记忆系统升级计划
- [2026-05-08-phase5-awakening-foundation.md](../04-plans/2026-05-08-phase5-awakening-foundation.md) — Phase 5 觉醒计划
- [p1-state-machine-design.md](../04-plans/p1-state-machine-design.md) — P1 状态机设计
- [iteration-plan-channel-plugin-moe.md](../04-plans/iteration-plan-channel-plugin-moe.md) — 渠道/插件/MoE 迭代
- [stub-cleanup-plan.md](../04-plans/stub-cleanup-plan.md) — 存根清理计划
- [DOCS_ALIGNMENT_PLAN.md](../04-plans/DOCS_ALIGNMENT_PLAN.md) — 文档对齐计划
- [neurova-memory-system-upgrade-technical.md](../04-plans/neurova-memory-system-upgrade-technical.md) — 记忆升级技术方案

### 05-reports 报告

**测试报告**：

- [NEUTESTING.md](../05-reports/NEUTESTING.md) — 测试框架说明
- [TEST_COVERAGE_REPORT.md](../05-reports/TEST_COVERAGE_REPORT.md) — 覆盖率报告
- [COMPLETE_TEST_REPORT.md](../05-reports/COMPLETE_TEST_REPORT.md) — 完整测试报告
- [COMPREHENSIVE_TEST_REPORT.md](../05-reports/COMPREHENSIVE_TEST_REPORT.md) — 全面测试报告
- [AUDIT_TEST_REPORT_20260603_134640.md](../05-reports/AUDIT_TEST_REPORT_20260603_134640.md) — 审计测试报告

**集成/功能报告**：

- [INTEGRATION_REPORT.md](../05-reports/INTEGRATION_REPORT.md) — 集成报告
- [FUNCTIONAL_MODULE_INTEGRITY_REPORT.md](../05-reports/FUNCTIONAL_MODULE_INTEGRITY_REPORT.md) — 功能模块完整性
- [CLOSED_LOOP_ANALYSIS.md](../05-reports/CLOSED_LOOP_ANALYSIS.md) — 闭环分析
- [REFACTORING_SUMMARY.md](../05-reports/REFACTORING_SUMMARY.md) — 重构总结
- [BUG_FIX_REPORT.md](../05-reports/BUG_FIX_REPORT.md) — Bug 修复报告
- [VERSION_HISTORY_REPORT.md](../05-reports/VERSION_HISTORY_REPORT.md) — 版本历史
- [code-audit-report-2026-08-28.md](../05-reports/code-audit-report-2026-08-28.md) — 8 月代码审计
- [2026-06-12-code-audit.md](../05-reports/2026-06-12-code-audit.md) — 6 月代码审计
- [执行摘要.md](../05-reports/执行摘要.md) — 执行摘要
- [最终集成总结.md](../05-reports/最终集成总结.md) — 最终集成总结

### 06-bugfix 修复记录

- [bugfix-*.md](../06-bugfix/) — 47 个修复记录（Agent/LLM/Memory/Skill/UI 等各领域，按文件名）

代表性修复文档：

| 文档 | 主题 |
|------|------|
| [bugfix-agent-neurflow-integration.md](../06-bugfix/bugfix-agent-neurflow-integration.md) | Agent 与 NeurFlow 集成修复 |
| [bugfix-agent-tool-calling.md](../06-bugfix/bugfix-agent-tool-calling.md) | Agent 工具调用修复 |
| [bugfix-llm-no-client-available.md](../06-bugfix/bugfix-llm-no-client-available.md) | LLM 无客户端修复 |
| [bugfix-provider-routing.md](../06-bugfix/bugfix-provider-routing.md) | Provider 路由修复 |
| [bugfix-memory-system-breakpoints.md](../06-bugfix/bugfix-memory-system-breakpoints.md) | 记忆系统断点修复 |
| [bugfix-p1-p2-report.md](../06-bugfix/bugfix-p1-p2-report.md) | P1/P2 修复报告 |
| [bug-audit-report-2026-06-25.md](../06-bugfix/bug-audit-report-2026-06-25.md) | 6 月 Bug 审计 |
| [TDD修复总结.md](../06-bugfix/TDD修复总结.md) | TDD 修复总结 |
| [JWT修复指南.md](../06-bugfix/JWT修复指南.md) | JWT 修复指南 |
| [browser-console-errors-fix.md](../06-bugfix/browser-console-errors-fix.md) | 浏览器控制台错误修复 |

### 08-research 研究

- [agent-memory-cutting-edge-research-2026.md](../08-research/agent-memory-cutting-edge-research-2026.md) — Agent 记忆前沿研究
- [agent_memory_consciousness_research_20260511.md](../08-research/agent_memory_consciousness_research_20260511.md) — 记忆与意识调研
- [neurova_memory_consciousness_enhancement_20260511.md](../08-research/neurova_memory_consciousness_enhancement_20260511.md) — 记忆意识增强方案

### 09-dev-progress 开发进展

- [README.md](../09-dev-progress/README.md) — 开发进展索引
- [frontend_development_plan.md](../09-dev-progress/frontend_development_plan.md) — 前端开发计划
- [api_inventory.md](../09-dev-progress/api_inventory.md) — API 清单
- [progress_tracker.md](../09-dev-progress/progress_tracker.md) — 进度追踪
- [module_designs/](../09-dev-progress/module_designs/) — 模块设计（19 篇，含 chat_page/execution_engine/knowledge_base 等）
- [daily_reports/](../09-dev-progress/daily_reports/) — 日常报告（2026-05-12/13）
- [code_reviews/](../09-dev-progress/code_reviews/) — 代码评审（3 篇）
- [architecture/frontend_architecture_guide.md](../09-dev-progress/architecture/frontend_architecture_guide.md) — 前端架构指南

### 10-configuration 配置

- [CHANNELS_CONFIG_TEMPLATE.md](../10-configuration/CHANNELS_CONFIG_TEMPLATE.md) — 渠道配置模板

### 11-legacy 归档

- 历史/过时文档 30 篇（grilling-* 分析、旧升级方案、旧 UI 方案、旧测试结果等），保留可追溯，不再维护。

---

## 维护指南

1. **新增模块**：在本文档"功能模块矩阵"增加一行（对照代码标注状态）
2. **状态变更**：功能从🟡→✅ 或⬜→🟡，更新矩阵 + 对应架构文档头部状态
3. **新文档**：按领域放入对应目录，在此索引的文档列表添加一行
4. **文档规范化**：文件名需有语义，日期放文件名尾部

> 归档条件：被新文档取代 / 已不反映当前实现 / 纯过程性记录
