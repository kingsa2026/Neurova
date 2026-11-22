# Neurova 文档总索引

> 版本: v1.0.0-beta15 · 中文名: 智星 · 更新时间: 2026-11-21（版本读自 `neurova/__init__.py` 的 `__version__`）
> 本索引是 `docs/` 目录的唯一入口。功能状态标注基于对 `neurova/` 代码库的逐项核对。

## 快速导航

| 入口 | 路径 | 说明 |
|------|------|------|
| **纪律与约定（最高优先级）** | [AGENTS.md](../../AGENTS.md) | **核心原则 8 条 + 修复教义 7 条 + 协作红线（中文交流 / 原创性 / 命名法 / 闭环）**；全仓引用的唯一事实源 |
| 项目 README | [README.md](../../README.md) | 项目概述、快速开始、核心特性 |
| 项目上下文 | [CONTEXT.md](../CONTEXT.md) | 架构概览、技术栈、设计规则 |
| 文档总索引 | [docs/INDEX.md](../INDEX.md) | 文档体系唯一导航事实源 |
| 功能模块矩阵 | [见下](#功能模块矩阵) | 全部功能的状态对照 |
| API 参考 | [API_REFERENCE.md](../02-api/API_REFERENCE.md) | 96 端点模块参考（`ENDPOINT_MODULES` 注册项实测，2026-11-19） |

---

## 功能模块矩阵

状态说明: ✅ 已实现 | 🟡 部分实现 | ⬜ 未实现/骨架

### 认知层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 记忆系统（多维度分类 + 温度引擎） | ✅ | `cognitive_layers/memory_layer/` | [02-memory-system](../01-architecture/02-memory-system.md) |
| NeRF 增强记忆检索（六通道体积渲染） | ✅ | `neurova_recall.py` `volume_renderer.py` `positional_encoding.py` `unified_retriever.py` | [16-vector-retrieval-system](../01-architecture/16-vector-retrieval-system.md) |
| 记忆温度机制（遗忘曲线 + 固化） | ✅ | `temperature.py` | [12-memory-temperature-mechanism](../01-architecture/12-memory-temperature-mechanism.md) |
| 睡眠整理（记忆巩固 + 梦境） | ✅ | `sleep.py` `sleep_writeback.py` | [13-memory-intelligence-enhancements](../01-architecture/13-memory-intelligence-enhancements.md) |
| 情感中枢引擎（四层 17 种情感） | ✅ | `cognitive_layers/emotion_context_layer/emotion_hub_engine.py` | [15-emotion-resonance-engine](../01-architecture/15-emotion-resonance-engine.md) |
| 自我进化引擎（人格/动机/宪法/反思） | ✅ | `evolution/` + `agent_core.py`/`chat_pipeline.py` 注入面——E1–E5 已闭环：宪法死端点修复+规则注入行为、动机行动生成按 E3 裁定退役改道（不直接驱动行为）、人格特质注入、反思 lessons 补池 | [21-recursive-self-improvement](../01-architecture/21-recursive-self-improvement.md) |
| RSI 递归自我进化（8 组件） | ✅ | `evolution/rsi/`（orchestrator/convergence/ratchet 等） | [21-recursive-self-improvement-v1.3](../01-architecture/21-recursive-self-improvement-v1.3-summary.md) |
| 意图理解（QueryIntent 检测） | ✅ | `cognitive_layers/memory_layer/neurova_recall.py`（`QueryIntent` :110 / `QueryIntentDetector` :121，经 `memory_layer/__init__.py` 导出；无独立 query_intent.py） | [20-retrieval-context-injection](../01-architecture/20-retrieval-context-injection.md) |
| 知识库适配 + RAG | ✅ | `knowledge/`（repository/storage/vector_index） | [24-knowledge-isolation-rag](../01-architecture/24-knowledge-isolation-rag.md) |
| 知识图谱 | ✅ | `knowledge/graph_bridge.py` `knowledge_graph_api` | [cognitive-graph-storage-architecture](../01-architecture/cognitive-graph-storage-architecture.md) |
| 元认知监控 | ✅ | `cognitive_layers/meta_cognition_layer/` | [20-retrieval-context-injection](../01-architecture/20-retrieval-context-injection.md) |
| EKI 完整反演（高斯过程代理 + 嵌入式采样） | ✅ | `cognitive_layers/memory_layer/bayesian_eki/`（`ekiUpdate` 单一事实源 + `EnsembleKalmanInversion` + `GaussianProcessSurrogate`；EKIModule 活链与认知优化器均已接线） | [27-eki-complete-inversion](../01-architecture/27-eki-complete-inversion.md) |

### 执行层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 多 Agent 协作（四种模式） | ✅ | `collaboration/` | [04-multi-agent-collaboration](../01-architecture/04-multi-agent-collaboration.md) |
| NeurFlow 工作流引擎 | ✅ | `collaboration/neurflow/`（20+ 文件：dag/execution_engine/subflow/storage） | [22-neurflow-workflow-engine](../01-architecture/22-neurflow-workflow-engine.md) |
| 消息路由（事件总线） | ✅ | `collaboration/neurflow/` `core/` | [03-message-routing](../01-architecture/03-message-routing.md) |
| 任务调度（AgentScheduler + PlanningTool） | ✅ | `agent/scheduler.py` `planning/planning_tool.py`；编排器另见 `agent/supervisor/orchestrator.py`（SupervisorOrchestrator）与 `evolution/closed_loop.py`（EvolutionOrchestrator） | [07-implementation-plan](../01-architecture/07-implementation-plan.md) |
| 多语言 i18n | ✅ | `language/` + `NeurUI/src/i18n/`（11 语言） | [i18n/README.en](../03-user-guide/i18n/README.en.md) |
| 检查点/回滚（Agent 会话/工作区） | ✅ | `checkpoints/service.py`（restore_snapshot / restore_with_rollback 恢复面，K1）+ `api/app.py` 启动收敛接线（reconcileSwarmRunsAtStartup，K2）+ `api/endpoints/memory/versions.py` 回滚端点（K3）；蜂群 run 续跑（K5）另立项未含 | [14a-version-control-evolution](../01-architecture/14a-version-control-evolution.md) |

### 工具层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| Skill 系统（注册表/版本/热插拔） | ✅ | `skills/` `skill_system/` | [05-skill-system](../01-architecture/05-skill-system.md) |
| Skill 协议兼容 | ✅ | `skills/market_adapters.py` | [05-skill-system](../01-architecture/05-skill-system.md) |
| Skill 归档与回滚（治理面 + 技能页入口） | ✅ | `api/endpoints/governance.py` `evolution/skill_experience.py` `NeurUI/src/pages/AgentSkillPage.vue` | [05-skill-system](../01-architecture/05-skill-system.md) |
| 肌肉记忆（ToolMemory 三层） | ✅ | `cognitive_layers/memory_layer/muscle_memory.py`（L1/L2/L3 三层存取+固化/遗忘）+ `cognitive_layers/memory_layer/tool_memory_integration.py`（裁定门面）——写（on_tool_executed 统一记账，2026-11-18 M1 收口单源）→存（JSON 原子落盘）→读（check_tool_memory 跨层检索→auto_execute/suggest）→反馈（失败降级/权重联动/RSI 调参）全链闭环，NeuHebb 空转支路已退役 | [tool-memory-muscle-analysis](../01-architecture/tool-memory-muscle-analysis.md) |
| MCP 集成 | ✅ | `tool_layers/mcp_client.py` `mcp_config.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| MCP 治理安全加固（P0 六项） | ✅ | `tool_layers/mcp_bootstrap.py` `security/url_guard.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| LLM Provider 管理（元数据/智能路由） | ✅ | `llm/provider_manager.py` `multi_model_client.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| LLM Router（多模态选择） | ✅ | `llm/llm_router.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| Computer Use（视觉理解） | ✅ | `computer_use/`（browser_manager.py、actions.py、desktop_uia.py、som.py 等 17 个 py 模块） | [01-core-architecture](../01-architecture/01-core-architecture.md) |
| 浏览器自动化（Camofox） | ✅ | `computer_use/browser_manager.py` | [CUA 能力台账](../CUA能力台账.md)（投递路径与拒绝码登记） |
| web_reach 网络工具 | ✅ | `web_reach/`（reach.py + 5 工具） | `agent-reach-integration.md` 已随第三方痕迹清除波（685e40a3）退役 |
| 插件系统 | ✅ | `plugins/` | [06-plugin-cli-system](../01-architecture/06-plugin-cli-system.md) |
| 工具编排（Tool Orchestrator） | ✅ | `tool_layers/tool_orchestrator.py` | [07-implementation-plan](../01-architecture/07-implementation-plan.md) |

### 接口层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 多渠道接入（14+ 渠道） | ✅ | `channels/`（62 py 文件，实测） | [03-message-routing](../01-architecture/03-message-routing.md) |
| REST API（96 端点模块，`ENDPOINT_MODULES` 实测） | ✅ | `api/endpoints/` | [API_REFERENCE](../02-api/API_REFERENCE.md) |
| NeurUI 前端（90 页面） | ✅ | `NeurUI/src/pages/` | [UI_FRAMEWORK_GUIDE（已归档）](../11-legacy/UI_FRAMEWORK_GUIDE.md) |
| 上下文管线（活水上下文池） | ✅ | `context/`（fold_trigger 软抑制 SC-1/2/8 + 时机判读 SC-3、budget_report 折叠后召回率读数 SC-6、compression_doctrine 严格变小）——S6 压缩纪律 + S15 失败冷却 + SC 批 + S6' 折叠基线跨重启已闭环 | [26-context-pipeline-p1](../01-architecture/26-context-pipeline-p1.md) |
| 上下文缓存与压缩 | ✅ | `context/orchestrator.py`（ContextOrchestrator，压缩与确定性淘汰收口于此；原 `context_cache.py` 已删除） | [CONTEXT_CACHE_COMPRESSION](../01-architecture/CONTEXT_CACHE_COMPRESSION.md) |
| 移动配对（QR + WebSocket） | ✅ | `api/endpoints/mobile_pairing.py` | [API_REFERENCE](../02-api/API_REFERENCE.md) |
| 睡眠系统管理（睡眠设置页） | ✅ | `cognitive_layers/memory_layer/sleep.py` | [02-memory-system](../01-architecture/02-memory-system.md) |

---

## 文档目录

### 01-architecture 架构设计

**核心架构（按阅读顺序）**：

1. [01-core-architecture.md](../01-architecture/01-core-architecture.md) — 整体架构、分层设计（核心）
2. [02-memory-system.md](../01-architecture/02-memory-system.md) — 记忆系统、多维度分类、LSM 存储
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
| `agent-reach-integration.md`（已退役） | Agent-Reach 整合——该文档随 685e40a3 退役，现行能力登记见 [CUA 能力台账](../CUA能力台账.md) |
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

- [adr/README.md](../01-architecture/adr/README.md) — 架构决策记录（memory/recall/skill/market/sandbox/接力判据 等）
- [audit/three-tier-isolation-audit.md](../01-architecture/audit/three-tier-isolation-audit.md) — 三层隔离审计报告
- [audit/three-tier-isolation-fixes.md](../01-architecture/audit/three-tier-isolation-fixes.md) — 隔离修复记录
- [memory/memo-technical-overview.md](../01-architecture/memory/memo-technical-overview.md) — MeMo 技术综述
- [memory/neurova-memory-system-complete-technical-guide.md](../01-architecture/memory/neurova-memory-system-complete-technical-guide.md) — 记忆系统技术文档
- [memory/neRF-meMo-integration-analysis.md](../01-architecture/memory/neRF-meMo-integration-analysis.md) — NeRF-MeMo 集成分析

### 02-api API

- [API_REFERENCE.md](../02-api/API_REFERENCE.md) — 96 端点模块参考（核心；按 `neurova/api/endpoints/__init__.py` 的 `ENDPOINT_MODULES` 注册表实测 96 项，核对基准 2026-11-19）
- [API_CALLING_SPECIFICATION.md](../02-api/API_CALLING_SPECIFICATION.md) — 前端 API 调用规范
- [api_architecture_analysis.md](../02-api/api_architecture_analysis.md) — API 架构分析
- [console_api.md](../02-api/console_api.md) — 控制台 API

### 03-user-guide 用户指南

- [PRODUCT_GUIDE.md](../03-user-guide/PRODUCT_GUIDE.md) — 产品指南
- [MOBILE_EXECUTOR_PRODUCT_COPY_2026-11-19.md](../03-user-guide/MOBILE_EXECUTOR_PRODUCT_COPY_2026-11-19.md) — 手机执行器产品文案草案（规划中能力：授权后代操作手机/人在环审批/凭据隔离/敏感应用隐身/任务熔断；随预研推进更新）
- [cli_usage.md](../03-user-guide/cli_usage.md) — CLI 使用指南
- [工作流调试指南.md](../03-user-guide/工作流调试指南.md) — NeurFlow 工作流调试
- [触发器配置指南.md](../03-user-guide/触发器配置指南.md) — 触发器配置
- [心流知识库功能使用指南.md](../03-user-guide/心流知识库功能使用指南.md) — 知识库使用
- [UI_FRAMEWORK_GUIDE.md](../11-legacy/UI_FRAMEWORK_GUIDE.md) — UI 框架指南（**已归档 2026-11-19**：所述原生 JS 组件体系已不存在，现行前端为 NeurUI/Vue 3）
- [MIND_EXPANDER_USAGE.md](../03-user-guide/MIND_EXPANDER_USAGE.md) — Mind Expander 使用
- [HARMONYOS_DESIGN.md](../03-user-guide/HARMONYOS_DESIGN.md) — HarmonyOS 设计
- [HARMONYOS_PRIVACY_POLICY.md](../03-user-guide/HARMONYOS_PRIVACY_POLICY.md) — HarmonyOS 隐私政策
- [HARMONYOS_SIGNING_GUIDE.md](../03-user-guide/HARMONYOS_SIGNING_GUIDE.md) — HarmonyOS 签名指南
- [HARMONYOS_RELEASE_CHECKLIST.md](../03-user-guide/HARMONYOS_RELEASE_CHECKLIST.md) — HarmonyOS 发布清单
- [i18n/README.en.md](../03-user-guide/i18n/README.en.md) — README 英文版（另有 ar/fr/ja/ko/ru 5 种）

### 04-plans 实施计划

- [2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md](../04-plans/2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md) — 参照系 ad **工具与执行安全升级实施计划**（源自 D4 两份专项拆解的可借鉴点全量收口 21 项）：三批十九卡 U1–U19——批一 P0 四卡（U1 SSH host key 校验收紧 TOFU→known_hosts+首接确认卡/U2 SSRF 防护收敛专用 safe-fetch 模块+出站静态检查强制/U3 远程失联"未执行、可安全重试"错误语义/U4 派发前最后一刻授权复验）+批二 P1 七卡（U5 沙箱第二档容器·WASM/U6 动态干预审计注册表/U7 工具 manifest 运行元数据单源/U8 长命令 park+迟交回灌/U9 通道认证加固三件套 token 后置·newest-wins·watchdog/U10 进程树 CIM BFS 清算/U11 失败分级重试守卫）+批三 P2 八卡（U12 结构化 UNSUPPORTED+端能力声明路由/U13 HPKE 信道评估/U14 MCP Apps UI 评估/U15 云沙箱双 provider 评估/U16 通道多型 token/U17 不可信会话凭据隔离/U18 浏览器会话键控核对/U19 alint 式安全 lint 试点）；待拍板六项（D-T1 沙箱路线/D-T2 park 回灌通道/D-T3 known_hosts 存储/D-T4 SSRF 迁移范围/D-T5 lint 是否接 CI/D-T6 两评估卡立项）；不照搬×4（闭源云网关/DO 状态机/Electron IPC 零鉴权/local-system 主进程直执行）；总验收=D4 专项 82.0→90.0+、主报告 D4 11.5→13.0+、总分 96.0→98.0+（竞品/外部对标，研究参考）
- [2026-11-22-reference-ad-security-catchup-implementation-plan.md](../04-plans/2026-11-22-reference-ad-security-catchup-implementation-plan.md) — 参照系 ad **安全域（D9）追平实施方案**（源自同日 D9 十轴专项细拆，LobeHub 72.5 vs Neurova 70.0/100）：三批八卡——批一 P0（S1 认证审计接线：log_auth_* 五函数零调用接上登录成败/登出/改角色/S2 出站点位 SSRF 复检扫荡：url_guard 单源对照点位清单补漏/S3 API key CSPRNG 核销：实测已用 secrets.token_urlsafe 达标零码改）+批二 P1（S4 审计防篡改哈希链 sha256(prev‖entry)+/integrity 校验面/S5 租户过滤集中化 core/tenant_scope.py 三形态助手+试点三处/S6 安全响应头移层：SecurityHeaders 已存在但被 GlobalAuth 短路，移最外层+补 Referrer-Policy/Permissions-Policy/HSTS 条件启用）+批三 P2 已拍板立项（S7 通用 OIDC SSO 假 IdP 红绿/S8 TOTP 2FA 二步挑战+恢复码，对方有表无功能本仓做即双反超）；五项拍板落档（D-S2 全量入链/D-S3 试点后扫余量/D-S4 FORCE_HTTPS 才发 HSTS/D-S5 OIDC 立项/D-S6 2FA 立项）；不照搬×4（不引 ORM 不建 RLS/不改 JWT 单通道/不引工作区头信任/不为 SSO 弱化密码链）；总验收达成（2026-11-22 实施完毕）=D9 专项 70.0→73.5（反超 LobeHub 72.5，未达 76 目标）、主报告 D9 8.0→8.5、总分 96.0→96.5（竞品/外部对标，研究参考）
- [2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md](../04-plans/2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md) — 参照系 ad 多模态追平实施方案（源自同日十轴专项细拆，**已拍板并实施完毕（2026-11-22，七笔提交）**：fal 音乐/深化 SIP/三家视频协议全做用户可选/生成物入池）：三批十卡——批一 P0（M1 音乐生成最小闭环/M2 视频 video_to_video 协议+首尾帧/M3 Gemini 原生视觉链路核实补齐/M4 opencode vision 路由排除）+批二 P1（M5 多模态预算口径单源化进 model_limits/M6 SIP DTMF+通话转写闭环/M7 视觉探测矩阵扩到 6 provider）+批三 P2（M8 多模态契约测试棘轮四类/M9 AIGC 生成物入活水池·对方无/M10 realtime 语音评估不做实现）；待拍板四项（D-M1 音乐 provider 选型/D-M2 realtime 建议不立项/D-M3 视频协议优先级/D-M4 生成物入池建议做）、不照搬×4（TTS 有服务端无产品面断裂形态/realtime 占位卡片/云侧听写端点依赖/单 provider 绑定）；复评目标=专项 69.0→75.0+、总报告 D8 维保持 ≥7.0
- [2026-11-22-reference-ad-llm-routing-catchup-implementation-plan.md](../04-plans/2026-11-22-reference-ad-llm-routing-catchup-implementation-plan.md) — 参照系 ad（LobeHub）**LLM 接入与自适应路由追平实施方案**（源自同日十轴专项细拆，LobeHub 86.0 vs Neurova 70.0/100）：三批走——批一 P0 攻路由核心（R1 错误分类路由语义表封闭集/R2 attempt 级 fallback 生命周期+流式首可见输出前 hold 换路/R3 能力驱动选型进主聊天链路）→ 批二 P1 补目录流式计量（R4 流事件内部归一最小集/R5 定价单元体系 tiered+cache 细分+providerReportedCost 透传/R6 usage 缺失诊断/R7 能力位显式化进目录与路由）→ 批三 P2 边界收口（R8 base_url 出站 allowlist/R9 ollama 运行面原生分支/R10 双抽象归一评估/R11 embedding API 通道）；五项待拍板（D-R1 channel 配置面/D-R2 加权分流/D-R3 embedding 通道/D-R4 provider 铺量优先级/D-R5 协议自动选择）；不照搬×4（云侧闭源策略依赖/91 家铺量/框架在 OSS 策略在云/有卡无实现）；总原则=策略自主+新逻辑落 neurova/llm/routing/ 新模块+主链路灰度（仅 auto 请求生效，显式钉死不变）+治理不绕行；总验收=十轴复评 70.0→80.0+、轴4≥8.0（竞品/外部对标，研究参考）

- [2026-11-21-multi-agent-collaboration-repair-plan.md](../04-plans/2026-11-21-multi-agent-collaboration-repair-plan.md) — 多 Agent 协作断点修复计划（备稿待拍板，源自同日实现路径分析报告 §11）：批一 P0 四卡（M1 房间自由文本批准补治理回灌/M2 MCP 身份缺省改 fail-closed/M3 API-key 租户策略收口/M4 L2 审批通道故障改 fail-closed）+ 批二 P1 四卡（M5 事件库读面消费与周期 prune 接线·不重做 reference-ac A2/M6 外部代理池水位接真/M7 多副本约束显性化/M8 只写不读项处置）+ 批三 P2 六卡（泵线程去阻塞/池 acquire 有界等待/成员声明侧过滤/TEAM 可见性补真/前端四小项/文档心智债）；含 6 项待拍板（D-M3/D-M5/D-M7/D-M8/D-M9/D-M13a）、明确不做×4（不建第二编排/不引新中间件/候选板不落新表/不动已实施卡语义）、每卡红绿判据+live-verify 验收
- [2026-11-21-recursive-self-evolution-plan.md](../04-plans/2026-11-21-recursive-self-evolution-plan.md) — Neurova 递归自进化第一期实施详案（**备稿已评审，2026-11-21 起实施**）：五臂现状盘点（参数 RSI/文本技能进化/工具技能闭环/提案生命周期/dreaming 规则臂）+ 运行数据实证（RSI 1018 迭代 0 应用、EvalCase 生产零立案、multi_agent 零报告、phase 4 顶格与证据脱节）→ **R 批机制咬合（R1 RSI 咬合/R2 EvalCase 立案/R3 跑批入口/R4 metacog 门全局开/R5 回滚持久化参数化/R6 相位回调+实做门槛/R7 RSI 面板参数化）+ P0 安全地基（TargetRegistry 禁改内核/SurvivalProbe 存活探针/GenerationLedger 世代账本）+ P1 L1 闭环（门禁链/影子验证/金丝雀/全自动闭环贯通/P1-7 租户段补齐）+ P2 L2 试点（PrPatchChannel/neuacp 执行体/白名单/提案收口）+ P3 元层**；三原则（内核先于演化/候选不直改基线/裁判在演化集合外）+ 总纲（进化全程自动进行、跑不通自动回滚，人工仅三处保留点）+ 多租户影响面（scope 分级/共性聚类 N=3 已拍板/金丝雀永不碰生产流量）+ 各类对象回滚机制表 + 安全红线 + DoD；11 项待拍板已于 2026-11-21 交互拍板落档
- [2026-11-21-harness-nth-power-design.md](../04-plans/2026-11-21-harness-nth-power-design.md) — **Harness^N** 第二期设计（备稿挂起；n=无限演化可能/一次演化几何式复合增益/Neurova 自指）：一期六件套底座上做"递归的递归"（演化工具链自身入注册表成为可演化对象）、多臂协同世代、neuacp 执行体并行、信号驱动持续演化、复合增益六指标观测；P4–P6 卡位草案，立项前置=一期验收门（P0–P3 完成+3 个完整世代含 1 次回滚演练+首个被采纳 L2 改进）
- [2026-11-21-reference-ac-catchup-implementation-plan.md](../04-plans/2026-11-21-reference-ac-catchup-implementation-plan.md) — 参照系 ac（T3 Code）追平与超越实施方案（源自同日对照评测报告，19 卡覆盖全部落后子项，卡号=评分卡子项编号便于对账）：三批走——批一攻三大代差（B2 上下文传递工件化：ContextTransfer/Handoff+预算 min(16k token,64KiB,窗口)+三态投递+omitted 可恢复；C5 provider 切换五结果决策 reuse/switch_model/restart_and_resume/create_with_handoff/reject 全由能力声明驱动；A3 命令回执幂等 insertIfAbsent+按回执重放）→批二体系补强（A5 自动结算护栏组/B3 隐藏 git ref 检查点+会话协同回滚+隔离检查/A2 事件溯源全局 seq+pruned-through+快照降级/E2 契约单源兼容守卫/D2 权限天花板 rank 序四层收窄/C1 三家真握手+registry 评估）→批三扫尾十项（C3 进程组回收+重试预算/E3 WS 压缩+订阅预算/D3 三端 cursor 自适应/B1 完成投递 cohort/A1 终态质量分级/C4 探测无副作用/E1 evals 先 case 后修/B4 队列治理/C2 能力维度扩展/D1 记忆式批准 L2 永不记忆）；含八项待拍板（D-A…D-H）、明确不做×6（不引 Effect-TS/不做巨石/不做云推送/不造第二套 ACP/不引 full-access 缺省/不为追分做表面工程）、每卡红绿判据+live-verify 验收、批复评机制（对照 T3 当期主干同卡复测）
- [2026-11-21-reference-ac-ide-integration-plan.md](../04-plans/2026-11-21-reference-ac-ide-integration-plan.md) — 参照系 ac **IDE 接入差距补齐实施计划**（源自同日 IDE 接入专项对照报告，5 卡覆盖 G1–G5 差距）：批一=G1 ACP registry 零代码接入（官方注册表发现/SHA-256 校验/stale 降级，预设降为种子数据，只登记不安装）+G2 真实 transcript 回放契约（录制脚本进 scripts/、三家真 CLI fixture、真 neuacp 管线回放+变异防恒真+协议陷阱清单）；批二=G3 适配器方法面收敛（handoff/rollback/snapshot/steer/fork/switch_model 映射既有机制，能力不满足抛 CapabilityNotDeclared，禁绕过）+G4 多端连接运行时单源（心跳/重放窗口/订阅范围按需过滤）；批三=G5 权限两小项（symlink 感知逐级 realpath fail-closed/只暴露原生支持模式成文）；含五项待拍板（D-1 registry 拉取默认关/D-2 只登记不安装/D-3 录制脚本常驻/D-4 收敛仅外部成员/D-5 服务端先行）、明确不做×4（不引 Effect/不做编辑器插件·云中继·PTY/不做 registry 自动下载安装/不写无机制支撑的方法）、验收含第三轮复评
- [2026-11-20-neuacp-fidelity-lineage-upgrade-plan.md](../04-plans/2026-11-20-neuacp-fidelity-lineage-upgrade-plan.md) — neuacp 接入层保真与归因升级方案（参照系 O 对比报告 §6.11 借鉴清单 v2 落地，**已实施 2026-11-20：e6a395992/367f62dd0/b29d06d28/a76dc8f8f/e40eaa4b2，live-verify 21/21**）：F1 能力声明+打开前拒绝（catalog 每家 `capabilities`、teams_api 配置期 422 + `_resolveExternalMember` 派活期结构化拒绝双闸）/F2 控制与事实同流全序（H-4 账本补每 run 单调 `seq`、chunk/permission_decided 入账、新增逐 run 帧 JSONL `frames.jsonl` 一手留痕+游标回放）/F3 事件保真（plugin 无 result 帧改诚实失败删推断兜底、双层脱敏复用记忆层 SENSITIVE_RULES）/F4 内核级同构桩（`NeuacpScriptedExecutor` 与真执行体同一协议同一契约测试）/F5 谱系归因（事件与帧统一携带 lineage：tenant/team/agentPath/depth/trace，SubAgentRun 增 tenant_id/parent_subagent_id）；执行记录与偏离说明见 §9
- [2026-11-20-reference-aa-borrowable-mechanisms-plan.md](../04-plans/2026-11-20-reference-aa-borrowable-mechanisms-plan.md) — 参照系 AA（Linger）§10 八项借鉴机制实施细则（**已全部实施 2026-11-20**：项 2/8/5/4/3/7 首批落地、项 6 换绑吊销增量与项 1 远程驾驶可靠性通道（含四端透出）接续清偿，逐项进度见计划 §10；每项含 Neurova 侧现状锚点/红绿测试设计/验收判据）：P0=工具调用先记账 unknown 不重放（tool_call_journal 挂 execute 单管道）+护栏三招（复核失败即拒/同站免审/车道互斥）；P1=契约快照 verify 门、推送韧性四件套、工具定义三投影、Dreaming clue→规则夜间自改进（走 S16 候选审阅）；P2=placement 凭据轮换、跨机 WS 账本重放；建议顺序 2→8→5→4→3→7→6→1
- [2026-11-21-reference-ab-borrowable-mechanisms-plan.md](../04-plans/2026-11-21-reference-ab-borrowable-mechanisms-plan.md) — 参照系 ab（平台托管型多智能体编排 Guidance）借鉴机制实施细则（**除 P2-1 成本透明表外六项**，源自同日对照评测报告 §6；D-A…D-E 已于 2026-11-21 逐项交互拍板：图取 v2 全边集（含审批/候选边，候选投影提前同批）、判定走独立 ACP 会话、候选板走 H-4 重放、text2SQL 两面都接、巡检 24h 可配仅 admin 读面）：P1-2 外部成员验收判定通道补线（verify_channel 经独立 ACP 判定会话接入 acceptance/review gate，消除 judge_unavailable 降级，判定会话权限恒 fail-closed）/P1-1 蜂群协作拓扑图（服务端投影端点 /console/chat/runs/{id}/graph + vue-flow 渲染，图库已在依赖零新增）/P2-4 服务端投影契约钉子（投影 schema 单源+词汇表对齐钉子，前端只渲染不解析）/P1-3 企业源摄取启动钩子+24h 巡检补跑双保险（auditEnterpriseSyncStaleness 走 lifespan+addSystemJob，trigger_kind 增 startup/audit）/P2-3 候选板 H-4 事件重放投影（重启后可查，integrationReport 兜底标注 source=replay，不落新表）/P2-2 企业源 text2SQL 只读分析档（enterprise_data_query 接成员工具面+反向 MCP data_query，NEUROVA_NL2SQL_ENABLED 总闸语义不变，只读断言在连接器层强制）；红线=不建第二套编排/事实源、判定不记 token、图与候选投影均只读；**已全部实施 2026-11-21：批1 `627458c32` / 批2 `f5f32dcef` / 批3 `cb1de7db1` / 批4 `a48802918`——四车道并行，红→绿 + A/B 零新增 + live-verify 逐车道通过，执行记录与偏离说明见计划 §9**
- [2026-11-19-agent-desktop-adoption-tickets.md](../04-plans/2026-11-19-agent-desktop-adoption-tickets.md) — agent-desktop（vercel-labs，纯无障碍树 CUA：snapshot→ref→act→verify）对照借鉴工单集 AD-1…AD-6（**AD-1…AD-3 已实施 d40f57a4c/a31d46ead/e5bad7a07，AD-4…AD-6 已实施 2c3d720b4/0f89e0145/本笔（skeleton/独立 CLI/三平台骨架，2026-11-19 用户拍板立项），真 UIA 活体已验**）：核实结论=retry 三值语义本仓 P1-2 已落地（action_result.py:71-104 + 守卫 test_action_result_retry_contract.py）勿重复立项，仅剩收尾——AD-1 `NEVER_RETRY_REFUSAL_CODES` 死码处置（全仓零消费，§2 断点）+ `docs/CUA能力台账.md` 补登 retry 词表；AD-2 UIA 快照 depth 剪枝诚实上报（desktop_uia.py walk 静默剪枝、truncated 只看节点数 → subtree_truncated 元素自标 + depth_truncated，对齐浏览器侧截断诚实纪律）；AD-3 computer_dom_snapshot 按 root_index/root_runtime_id 下钻子树（下钻结果 index 续接入 session 缓存，复用 _lookup_element 单一寻址，缓存外 root 拒绝 ref_not_found）；AD-4 skeleton 骨架概览（匿名容器折叠 omitted_count，真机教训：legacy_default 不算交互信号）；AD-5 独立 CLI `python -m neurova.computer_use`（README `neurova computer` 漂移修正；MCP stdio 挂 ACP 批次）；AD-6 三平台适配骨架（platform.py 单一探测源 + macOS AX/Linux AT-SPI 预留 backend 诚实 NotImplemented）；操作守则 skills 化未立项
- [2026-11-19-acp-coding-agent-team-integration-plan.md](../04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md) — ACP 编码代理团队接入设计方案（备稿待拍板）：经 Agent Client Protocol（Zed/JetBrains 生态，v1 稳定/v2 草案）把 Claude Code、Codex、OpenCode、Gemini CLI、Qoder、CodeBuddy、Trae 等外部编码代理编入 swarm/team 协作——Neurova 任 ACP Client，最小切口=名册成员带 `executor` 标记时 `_resolve_agent`（swarm.py:1931）返回 chat 兼容适配器，事件/审批/台账/围栏全走既有 spawn 主链路零旁路；含七工具支持矩阵（原生/官方适配器/插件形态预留三档）、`session/request_permission`→审批链 L0/L1/L2 映射、stdio/SSH 双传输、前端 TeamPage 名册+外部成员表单适配（i18n×11）、P0–P2 任务卡与六项待拍板（D1–D6）
- [2026-11-19-enterprise-datasource-mcp-plan.md](../04-plans/2026-11-19-enterprise-datasource-mcp-plan.md) — 企业数据源接入与 MCP 形态方案（备稿待拍板）：ERP/MES/进销存/CRM 作本体数据源的路线选型——直连连接器为主路径（协议/工厂/映射/准入既有设施盘点）、内置 MCP 只读工具组先行（source_list/schema/sync/mapping_check + 治理红线五条）、`mcp_tool` 源类型挂台账缓办（立项条件 + 入模前净检闸）；含六项待拍板（增量游标/实体对齐/值变换闭集/变更准入语义/sync 开放范围/MES 设备层）与 P0–P2 批次建议
- [2026-11-19-enterprise-sync-reliability-plan.md](../04-plans/2026-11-19-enterprise-sync-reliability-plan.md) — 企业源持续同步可靠性方案（已实施 2026-11-19，3c234791d/14850e854，§7 有执行记录与偏离说明）：补齐连接器主动取数三缺口——同步历史落账（v56 `enterprise_sync_history`，runOnceAsync 统一写点，trigger=manual/interval，读面 admin）、interval 调度全租户覆盖（listSyncTenants+jobId 租户段+运行时单源跟随）、per-source 非阻塞单飞（already_running 如实跳过）；含测试计划/拆卡 A–D/live-verify 验收（源自同日主动取数机制分析的三缺口）；§8 租户共享设计（2026-11-19 拍板复制发布语义，**P1+P2+远程召回已实施 625b994a8/85fe74baa/d10dad497**，执行记录见 §8.7/§8.8）：shared_with 租户段+跨租户发布副本双边审批+远程召回+源级 share_tenants 投影式复制（事实层随投影落目标租户分区）
- [2026-11-19-mobile-executor-research-plan.md](../04-plans/2026-11-19-mobile-executor-research-plan.md) — 手机执行器预研与实施方案（安卓先行）：把手机端从「用户客户端」升级为「agent 的手」——后端经既有移动 WS 通道指挥端上无障碍执行器代用户操作手机；安卓最小闭环 M1–M9 拆卡（按需开关/指令协议/凭据隔离/审批扣住/事件账本/熔断/体检/演示模式/端到端）+ 鸿蒙 R1–R4 能力边界预研 + 安全红线五条 + 与既有审批/账本/调度设施的单源关系；源自 reference_x 对照报告的 P2-1 启发（待拍板排期）
- [2026-11-18-dcpm-memory-inspiration-plan.md](../04-plans/2026-11-18-dcpm-memory-inspiration-plan.md) — DCPM 论文（arXiv:2606.09483 双过程认知记忆）启发落地清单（T1–T6，记忆与睡眠体系进化方案；含高阶认知模块接线审计与本仓对照结论）（待拍板排期，研究参考）
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
- [2026-09-22-api-inventory-refresh-plan.md](../04-plans/2026-09-22-api-inventory-refresh-plan.md) — 前端 API 清单重生成立项（Issue #68 归档层导航影响筛选）
- [2026-09-22-ci-ast-scan-budget.md](../04-plans/2026-09-22-ci-ast-scan-budget.md) — 跨文件 AST 判据的解析预算收口（Issue #148 受保护子集偶发超时）
- [2026-09-25-ci-pipeline-cost-convergence.md](../04-plans/2026-09-25-ci-pipeline-cost-convergence.md) — CI 流水线耗时收口（Issue #223：离线库缓存 / 静态门禁合并 / 依赖走锁 / 不自举 pip）
- [2026-10-08-前置3-技能呈现账收口实施方案.md](../04-plans/2026-10-08-前置3-技能呈现账收口实施方案.md) — 技能「呈现→派发」漏斗补最上游一级（对照报告 §8 前置 3：三份账并存 + `times_presented` 零写入零消费，呈现账收口到 manifest 漏斗单源）
- [2026-10-08-前置1-例级不退化门实施方案.md](../04-plans/2026-10-08-前置1-例级不退化门实施方案.md) — 留出侧例级读数 + 例级不退化门（对照报告 §8 前置 1：均值吞掉单例退化，判分未量出与真退化同形）
- [2026-10-09-运行终态回写台账-例级门可见性实施方案.md](../04-plans/2026-10-09-运行终态回写台账-例级门可见性实施方案.md) — §6-9 终局拒绝回写台账：`accepted` 改钉「已部署」义，提示词 / 换轴指令 / 产出剪枝不再被假阳性骗
- [2026-10-09-四条自动化前置落成晋升判据实施方案.md](../04-plans/2026-10-09-四条自动化前置落成晋升判据实施方案.md) — §8 四条前置从"文档里的一句提醒"收成晋升判据：自动执行档（1→2 起）未满足即硬否决并逐条点名，每条配运行期可证伪探针
- [2026-10-09-双臂试评接真轨迹-前置2落地实施方案.md](../04-plans/2026-10-09-双臂试评接真轨迹-前置2落地实施方案.md) — §8 前置 2 落地（用户裁"丙 + 修 C"）：执行器回落收成单源接缝、评测轮补 save_memory 闸门、探针改问生产装配点；轮级候选正文覆盖槽待 D2 拍板
- [2026-10-10-渠道身份绑定与群聊记忆分账实施方案.md](../04-plans/2026-10-10-渠道身份绑定与群聊记忆分账实施方案.md) — §6-127 落地（用户裁四条）：未绑定者落渠道专属命名空间可事后提升、绑定接续 `UserIdentity`＋`verification_code` 加 `BIND_CHANNEL`、作用域取 **agent 级**、群=共享作用域/私聊=个人；四批分期与"不建第二套码/表、历史不合并、渠道 `user_id` 只服务端解析"的红线
- [2026-10-16-任务级环节证据-attribution升级实施方案.md](../04-plans/2026-10-16-任务级环节证据-attribution升级实施方案.md) — M-E 后半第二刀（未开工）：把环节证据从轮次级收件箱接到每条评测任务上，让 attribution_hit_rate 回答「改对地方没有」；含五条实测前提（模拟臂不跑环故恒空、_evaluate 五元组 8 个解包点、候选今天没有环节声明）与「声明由谁给」的三态裁定（推荐乙＝从证据反推，不采甲＝LLM 自报未校准标签）
- [联想线索落地工单_2026-10-21.md](../04-plans/联想线索落地工单_2026-10-21.md) — TM-2/TM-3 实施细则（待执行）：给记忆挂「只参与检索、永不进提示」的联想线索，四批拆分（规则线索并词法面 → 别名与死 DDL 收口 → 空闲窗口批量生成前瞻线索＋旁路向量通道 → 段落承载）；含从外部实现逐行核出的四条可借与五条不可借、门限**实测标定**法（不抄外部数值）、三条成本闸、每批红灯断言，以及「写侧模型预算开多大」的甲/乙/丙三态票（推荐甲先行）
- [2026-10-24-移动端扫码经中继连接无固定IP服务端设计方案.md](../04-plans/2026-10-24-移动端扫码经中继连接无固定IP服务端设计方案.md) — 设计已确认、未开工：手机端扫码经自研中继连上无固定 IP 的服务端。头号原则是**凭据与地址分离**（二维码只带高熵一次性 `ref`，地址扫码后向发现服务换取）；含自研中继的组件与事实源落点、按需新开数据连接的数据面选型、四条互不合并的状态机（配对生命周期／通道隧道／设备连接会话／面板视图态）与非法迁移矩阵、Web 与 Harmony 两端 UI（含面板缺失的「中继未注册」态）、代理头缺失导致限流失明等实测现状、CGNAT 边界，以及 S0–S3 分期与每批红灯判据；子裁定两则已落（`scanned` 超时＝直接 expired 不设宽限；凭证＝设备身份长期＋接入凭证可续签、在册长期保留仅 30 天提醒），并连带揪出「解除配对后旧凭证仍连得上」这个今天就存在的洞（归 S1a 先行修复）
- [2026-11-15-Neurova手机客户端设计方案.md](../04-plans/2026-11-15-Neurova手机客户端设计方案.md) — 手机客户端总体设计（**四项已裁，未开工**）：基于现有 `/api/v1` 全功能面零新建服务端协议；登录与租户（JWT `tenant_id`=部门根，App 只读展示不本地过滤）；三形态网络接入（内网直连／公网固定 IP 反代＋TLS 样板／无固定 IP 自研中继，均复用已实施设施）与客户端服务器档案连接管理；扫码配对作为登录辅助通道；SSE 主＋移动 WS 备的双通道事件映射；安全（凭证分层、安全存储、经反代限流前置条件）；服务端尾巴 S-1..S-4；M1–M4 分期判据。已裁（2026-11-15）：D1 客户端形态=两端（鸿蒙沿用 Mobile/harmony＋安卓新建 Vue3+Capacitor），**客户端构建物统一放置于仓库根 `Mobile/`**（harmony/android/dist，Mobile/harmony 随迁 Mobile/harmony）；D2 离线推送=做（推送桥＋鸿蒙 Push Kit／安卓 FCM，国内无 GMS 厂商通道后续扩展）；D3 租户切换=退出登录后以新账户登录（服务端零改动）；D4 多服务器档案=做。后续演进（2026-11-16）：安卓承载形态按 ADR 0024 转原生 Compose（`Mobile/android-native/`，已实施），Capacitor 工程 `Mobile/android/` 已退役删除
- [2026-11-17-multi-agent-collaboration-upgrade-plan.md](../04-plans/2026-11-17-multi-agent-collaboration-upgrade-plan.md) — 多 Agent 协作升级实施方案（依据 AutoSwarm 对照评测，未开工）：P0 评测 harness（三类基准形态：确定性模拟/测试判定/量规判分，复用 goal_verifier 判据与台账成本面）→ P1 协作机制闭环四件套（G-2 结构化任务单元 TaskUnit、G-3 子代理终态验收门（不达标带 missing 自动回炉一次，复用 resumeFinishedRun 通道）、G-5 监督评审相位（SUBAGENT_STATUSES 增 in_review，review.py rubric 单源复用）、G-4 依赖门控（spawn 增 dependencies + blocked 态不占槽 + 依赖失败则下游 failed 且不归档池））→ P2 可靠性与卫生（run 状态持久化/外部 agent 落库/死码双实现清偿/集成协议/升级闭环）→ P3（跨 agent 审批链/span 级 trace）；含四个拍板点（验收门灰度策略/CAPABILITY_* 接线或删/CRDT 退役或保留/SubAgentManager 并入）与"不做清单"（不建中心调度、不做多轮讨论解题、不削治理）
- [2026-11-17-surpass-reference-implementation-plan.md](../04-plans/2026-11-17-surpass-reference-implementation-plan.md) — 超越 CoworkOS 实施方案（**v3 完整实施版**，同框评测 84→目标 ≥96，细化到他方 agent 可直接执行；v2 统一拓展项后，v3 应用户拍板再纳入项目管理整合与 agent 发起面）：**S1–S14 十四批**——S1 评测地基（usage/轨迹判据/记忆隔离/T1 重设计）→ S2 邮箱语义补全（幂等/优先级/死主回收）→ S3 run 生命周期迁移表+状态事件归档 → S4 结果候选制（candidate→CAS 合入→冲突保留）→ S5 会话存储追加式（JSONL+快照，最大风险项独立会话）→ S6 压缩纪律（自动触发/事件化/严格变小，依赖 S5）→ S7 记忆准入轻量先行 → S8 审批审计持久化（E 维反超点）→ S9 团队/房间能力接入蜂群（升级/审批投房间回灌+群主权限、候选房间呈现拦截、名册动态组队、memory_scope 共享黑板、AgentTeam 双轨边界复核）→ S10 固定团队开放（list_teams/dispatch_team 多路 spawn 编排/临时团队沉淀走审批 ASK；原生工具优先，MCP 仅外部第二阶段）→ S11 多 agent 双入口（主 agent 编排发起 + 用户经项目房间直发，均复用 SwarmManager 单源不建第二引擎）→ S12 项目协作档案（留底+可观测：run→project 归属标签+聚合读面+收尾封卷，读时 join 不建新账）→ S13 项目/团队/群聊的 agent 工具面（project_create/project_list/room_post；加人类成员 L1 ASK、对外分享 L2；团队管理不加新工具防膨胀）→ S14 同框重评分判定超越（≥96）；MCP 深度集成与长程目标 park 移出另立项；涨分预算表（保守 95/满额锚点封顶）、15 条共享避坑清单（A/B 串行/具名常量钉子/路由快照重生成/邮箱唯一写点/热区撞车复核/密钥零入库等）与每批交付定义（红灯先行+A/B 零新增+live-verify+--only 提交）；范围钉死：群仅指协作房间（room_id=协作 project_id），渠道群（chgrp:）不参与；红线=不做群聊解题、不建第二套编排/验收/存储体系
- [2026-11-18-assistant-harness-adoption-plan.md](../04-plans/2026-11-18-assistant-harness-adoption-plan.md) — QwenPaw 借鉴点适配落地方案（待拍板）：P0 渠道子进程隔离+握手期依赖审计/技能扫描双语签名库对齐/DoomLoop 相似度两阶段升级/审批泛化安全校验；P1 声明式停止门编译/人机共编 MEMORY.md+蒸馏/沙箱 Python recall/token 保证金/File Guard/五档执行级别/工具完成缓存查询/Shell 逃逸对抗补齐/渠道优先级队列/市场多源 priority/manifest 渠道过滤+渐进披露；P2 跨平台内核沙箱/本地模型打包等按需项；含**已对齐不立项清单**（工具三处置/per-model 限流/错误分类/MCP 熔断/记忆准入/检查点等十项，防重复建设）与**不学清单**（guardian fail-open/云端外发脚本/Markdown 念 CLI/双份目录/沙箱默认关等七条反模式）；**P2 二轮严格化推翻 C2/C3/C5 初判并落地；B2 MEMORY.md 已退役（c132f7d64，蒸馏回写改道温度体系）**
- [2026-11-18-memory-distillation-plan.md](../04-plans/2026-11-18-memory-distillation-plan.md) — 记忆蒸馏回写立项方案（**已实施 D1–D4**，a2fb8f6a6/2fc1240ad）：对话轮末异步 LLM 归纳"值得长期记住的事实"→ memory_admission 敏感筛查 → pending_memories 候选（指纹去重/租约/tombstone）→ 人工审阅（复用 pending 审阅面+S16 纪律转正）→ memories 表温度生命周期；`NEUROVA_MEMORY_DISTILL` 灰度默认 off、预算护栏/失败熔断/候选洪水防护；红线=不直写 memories、不恢复 markdown 旁路、fail-soft 不阻断主对话；A/B 三域零新增、live-verify 真治理链（候选→审阅→落库可检索）全通，依据 QwenPaw 批 B2 后续裁定（蒸馏接温度机制、MEMORY.md 退役）
- [2026-11-18-four-domain-repair-plan.md](../04-plans/2026-11-18-four-domain-repair-plan.md) — 四域可靠性修复方案（任务卡制，源自 2026-11-18 四路代码级审计）：**进化域** E1 宪法死端点修复（agent.py:944 依赖不存在的 agent 方法，GET 恒空/PUT 假成功）+ E2–E4 宪法规则/动机/人格"只存不用"接行为或诚实化（需拍板）+ E5 反思 lessons 补池分支；**检查点域** K1 P1-5 CheckpointService 恢复面接通（组件齐备但恢复侧零调用零 API）+ K2 启动接线（swarm 账本收敛 reconcileRunFromEvents 零调用 + ShutdownGuard 槽位未装配）+ K3 记忆版本回滚接线或退役（rollback_to_version 零调用只写不读）+ K4 就地回滚决策卡 + K5 蜂群 run 续跑另立项；**肌肉记忆域** M1–M4 收尾（自动执行双重记账稀释固化阈值/Skill 失败不入账/死读取面与空转支路退役/集成去 mock）+ M5 矩阵 🟡→✅（实态已闭环）；**活水池域** SC-3→SC-7→SC-5 时机智能第一波（判读读数/反思节律对齐/回执召回指引，信号源现成）+ SC-1/SC-2/SC-8 软抑制 + SC-6/SC-4 召回率读数与四臂基准 + 折叠基线跨重启；共性根因=机制先行、消费滞后（数据模型与写入链路建齐，读→行为/用户可达的最后一公里未闭环）；红线=不建第二套检查点、不自动跨重启续跑、动机不直接驱动行为、SC 激进臂无数据不转默认

**CI / NPC 口径**：

- [npc轮数配额口径收口_2026-09-25.md](../05-reports/npc轮数配额口径收口_2026-09-25.md) — NPC `maxTurns` 配额口径收口（Issue #236：删掉「2h ÷ 单轮耗时」上钳、配额单源化到 `.cnb.yml`）
- [npc接力载体env自引用_2026-09-26.md](../05-reports/npc接力载体env自引用_2026-09-26.md) — 接力载体 `env` 自引用收口（Issue #256：键集合对齐，报错落在无关处的「Invalid container name」）
- [npc续跑角色连续性_2026-09-26.md](../05-reports/npc续跑角色连续性_2026-09-26.md) — NPC 自动续跑的角色连续性（Issue #272：接力落点 `role` 曾在册改名后静默回落；身份改随轮传递；`@CodeBuddy` 系统 NPC 不读本仓配置）
- [npc系统事件通道_2026-09-28.md](../05-reports/npc系统事件通道_2026-09-28.md) — NPC 会话「空转」的通道收口（Issue #306：本仓 NPC Job 未自带 `docker.image`，被平台系统默认配置按 key 覆盖；判据按每个 `@npc` 事件的每个 Job 遍历）
- [npc空转单轮输出预算_2026-09-28.md](../05-reports/npc空转单轮输出预算_2026-09-28.md) — NPC 空转死因（Issue #306：推理吃满单轮输出预算 ⇒ 该轮零正文零工具调用；零产出收官是 `success` 故收尾判据不成立、无人接手；修法落在六个在册角色的 prompt）
- 同上报告附录 A — 「提交状态通道 = 门禁专用」：非门禁流水线（建库 / 周级巡检 / 手动触发口 / NPC 接力载体）一律 `allowFailure`，失败不冒充门禁结论（PR #255 复核）

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
- [memory-temperature-convergence-2026-09-21.md](../05-reports/memory-temperature-convergence-2026-09-21.md) — 温度衰减双实现比对与收敛（Issue #74 死码退役）
- [同名函数盘点台账_2026-09-25.md](../05-reports/同名函数盘点台账_2026-09-25.md) — 跨文件同名函数分档与处置结论（Issue #192 待办项收口）
- [2026-11-21-multi-agent-collaboration-implementation-analysis.md](../05-reports/2026-11-21-multi-agent-collaboration-implementation-analysis.md) — 多 Agent 协作实现路径分析（六路并行代码级核读）：SwarmManager 编排核心（生命周期/状态机/候选制 CAS/双门/依赖门/父代控制）+ 父子通信（邮箱三层可靠/Steer/房间作用域）+ 四入口簇 + neuacp 外部代理接入（能力双闸/进程池/审批桥接/帧账本/租户红线/SSH）+ 审批治理（L0-L2/裁决单源/D1 记忆式批准）+ 工具面四层防线与 MCP 双面 + 八类台账面与 H-4 事件族 + 辅助编排线（neurflow/进程内 ACP 总线/Supervisor）+ 前端协作面；附 14 项断点与风险清单（P0×4/P1×4/P2×6）与总体评价

### 06-bugfix 修复记录

- [bugfix-*.md](../06-bugfix/) — 修复记录（Agent/LLM/Memory/Skill/UI 等各领域，按文件名）

代表性修复文档：

| 文档 | 主题 |
|------|------|
| [bugfix-agent-neurflow-integration.md](../06-bugfix/bugfix-agent-neurflow-integration.md) | Agent 与 NeurFlow 集成修复 |
| [bugfix-agent-tool-calling.md](../06-bugfix/bugfix-agent-tool-calling.md) | Agent 工具调用修复 |
| [bugfix-llm-no-client-available.md](../06-bugfix/bugfix-llm-no-client-available.md) | LLM 无客户端修复 |
| [bugfix-provider-routing.md](../06-bugfix/bugfix-provider-routing.md) | Provider 路由修复 |
| [bugfix-memory-system-breakpoints.md](../06-bugfix/bugfix-memory-system-breakpoints.md) | 记忆系统断点修复 |
| [bugfix-channel-agent-select-and-config-landing.md](../06-bugfix/bugfix-channel-agent-select-and-config-landing.md) | 渠道页选不到智能体 + 已有渠道配置失效（Issue #290） |
| [bugfix-p1-p2-report.md](../06-bugfix/bugfix-p1-p2-report.md) | P1/P2 修复报告 |
| [bug-audit-report-2026-06-25.md](../06-bugfix/bug-audit-report-2026-06-25.md) | 6 月 Bug 审计 |
| [TDD修复总结.md](../06-bugfix/TDD修复总结.md) | TDD 修复总结 |
| [JWT修复指南.md](../06-bugfix/JWT修复指南.md) | JWT 修复指南 |
| [browser-console-errors-fix.md](../06-bugfix/browser-console-errors-fix.md) | 浏览器控制台错误修复 |

### 08-research 研究

- [reference_ad_context_engineering_teardown_2026-11-22.md](../08-research/reference_ad_context_engineering_teardown_2026-11-22.md) — 参照系 ad 总评测的**上下文工程十轴专项细拆**（组装管线/token 计量预算/截断/压缩摘要/无损回滚/召回回灌/大结果卸载/缓存经济学/结构完整性/测试纪律，各 10 分）：**LobeHub 79.0/100 vs Neurova 75.5/100**——对方最强=缓存经济学修剪（StaleToolResultTrim 按 provider 缓存 TTL/价格盈亏平衡+字节稳定保前缀缓存，本仓无对应物）+27 处理器组装管线+附件 readAttachment 句柄卸载+Topic Doctor 消息树体检；本仓最强=召回自动回灌（被动 pool.draw 向量注入+主动 recall_history/pool_search/recall_context_span+防自污染，对方被压内容不可自动召回）、按 token 预算的折叠七步判据（对方按条数截断）、工具结果 microcompact 句柄化、压缩严格变小+失败冷却+CompressionEvent 时间线；共同强=压缩全程非破坏原文不删可回滚；借鉴 P0×3（缓存经济学修剪判据/token 漂移系数分桶计量/结构完整性 Doctor）+P1×3（处理器管线插件化/附件预算单源/压缩迟滞双阈值）+P2×3，不照搬×2（按条数截断/召回纯人工化）；据实回写总报告 D2 上下文工程子项 4.0/4.5→4.5/4.0（D2=12.5/11.0，总分 98.0/96.0）（竞品/外部对标，研究参考）
- [reference_ad_remote_execution_teardown_2026-11-22.md](../08-research/reference_ad_remote_execution_teardown_2026-11-22.md) — 参照系 ad 总评测的**远程执行能力细拆**（工具安全拆解轴3/轴6 的二级专项，十轴各 10 分）：**LobeHub 84.5/100 vs Neurova 78.0/100**——对方=设备网关产品级主架构（token 后置 auth+DO 复验 claim、服务端目录白名单+设备端 realpath 防符号链接逃逸+派发前最后一刻复验三层授权、Redis BLPOP 等结果+离线 hold 45s"never ran, safe to retry"+长命令 park 迟交回灌、云沙箱档、进程树 CIM BFS 清算；短板=设备身份无 attestation/Electron IPC 零对端鉴权/清算链路长多版本兼容）；本仓=六形态广度（SSH 命令+按需凭据卡/neuacp SSH key_ref fail-closed+租户段进程池/中继代部署可撤销全审计/移动隧道/远程 MCP OAuth PKCE/来宾机 RDP+Windows Sandbox；短板=SSH host key AutoAddPolicy TOFU/无凭据轮换/同步 60s 模型长任务表达力弱）；不改 D4 评分（方向一致已计入）；§4 升格为 **D4 全域可借鉴点单一收口（21 项）**——P0×4（SSRF 专用包收敛/SSH host key 收紧/离线 hold 安全重试/最后一刻授权复验）+P1×8（沙箱第二档/动态干预审计注册表/manifest 运行元数据/park 迟交/token 后置认证/newest-wins+watchdog/进程树清算/失败分级重试）+P2×9（结构化 UNSUPPORTED/能力声明路由/HPKE 信道/MCP Apps UI/沙箱双 provider/多型 token/不可信会话凭据隔离/浏览器 topic 键控/alint 安全 lint），不照搬×4（Electron IPC 零鉴权/闭源云网关依赖/DO 状态机迁移/local-system 主进程直执行）（竞品/外部对标，研究参考）
- [reference_ad_data_tenant_auth_security_teardown_2026-11-22.md](../08-research/reference_ad_data_tenant_auth_security_teardown_2026-11-22.md) — 参照系 ad 总评测的**数据/租户/认证/安全十轴专项细拆**（数据层工程/登录矩阵/会话与凭据生命周期/身份通道/多租户隔离/授权 ACL/网络边界/秘密保护/审计/端点进程设备面，权 12/12/10/8/14/10/12/8/8/6）：**Neurova 70.0/100 vs 参照系 ad 72.5/100**，差距较粗评（归一 66.7 vs 75.0）收窄至 2.5 分——对方强=认证矩阵（17 SSO+Passkey+magic link+OTP+自建 OIDC IdP 10 表）与数据层工程（238 表/227 迁移/FTS outbox/回收站/autovacuum），但 **2FA 有表无功能**（schema+迁移 0054 在、better-auth 插件未挂）/**RBAC OSS 仅 4 真实执行点**（tRPC 面全 stub+tsconfig path 放行+X-Workspace-Id 头不验成员，代码自认）/主站 CSP 默认关/tRPC·hono 面无限流（仅 OpenAPI REST 有）/secret-channel HPKE 零消费/API key 生成非 CSPRNG/两处验签非 timingSafe；本仓强=身份单通道（15 写入点无第二通道）+GlobalAuthMiddleware 全路径三模式/租户真实执行（JWT 源 192 处 31 文件+neuacp 四收口+进程池租户段+HMAC 作用域凭据）/全局限流中间件+9 文件验签（含 QQ Ed25519）+SSRF url_guard 单源 13+ 消费/keyring 数据根派生+sealSecrets+三层脱敏；共同短板=登录失败审计双方缺位（本仓审计函数在而零调用）/均无 RLS/均无 2FA；据实回写总报告 D9 子项（认证 L 3.0→2.5、N 1.5→2.0；租户执行 N 2.5→2.0；运行安全 L 1.5→2.0），D9 合计 9.0/8.0 不变（竞品/外部对标，研究参考）
- [reference_ad_tool_security_teardown_2026-11-22.md](../08-research/reference_ad_tool_security_teardown_2026-11-22.md) — 参照系 ad 总评测的**工具与执行安全十轴专项细拆**（声明治理/生态规模/执行面/MCP/调用学习/沙箱/SSRF/凭据/审批/入站审计，各 10 分）：**Neurova 82.0/100 vs 参照系 ad 78.0/100** 本仓小胜——对方最强=执行安全基建（三档沙箱：云沙箱/SRT 本地白名单排模型提供商/Pyodide WASM、ssrf-safe-fetch 专用包逐跳过滤+alint lint 强制、凭据值 `******` 永不进模型上下文+HPKE 信道储备、三层审批：声明式 humanIntervention+动态审计+auto-run 不可绕安全黑名单；短板=local-system 主进程直执行/MCP 仅 client/无程序性工具记忆）；本仓最强=**139 工具单源注册表 `_BUILTIN_SCHEMAS`+并行能力声明（readOnly/concurrentSafe/writeScopes）**、MCP client+server 双端（server 面 /v1/mcp/agent-tools 双鉴权）、**肌肉记忆程序性闭环**（on_tool_executed 单源记账→指纹+语义+成功率匹配 L1/L2/L3→高置信自动执行不绕治理/中置信建议注入，对方为零）、命令分段治理（防白名单搭便车）+8 渠道验签+技能扫描；据实回写总报告 D4 工具框架子项 L 5.0→4.5 / N 3.5→4.0（D4 = L 12.0/11.5 险胜 0.5，总分 97.5/96.0）；可借鉴点全量清单（21 项）收口于远程执行专项 §4（竞品/外部对标，研究参考）
- [reference_ad_multimodal_teardown_2026-11-22.md](../08-research/reference_ad_multimodal_teardown_2026-11-22.md) — 参照系 ad 总评测的**多模态十轴专项细拆**（视觉理解输入/图像生成/视频生成/TTS/ASR 听写/实时语音/音乐生成/屏幕与设备视觉/文档解析/契约测试，各 10 分）：**Neurova 69.0/100 vs 参照系 ad 68.5/100** 接近持平、本仓反超，**v6 追平三批实施+遗留清偿后复评 75.5**——对方最强=生成广度与工程化（图像 41 家/视频 24 家 provider、工具链状态机+client/server 双执行器+创作页）与契约测试矩阵；本仓最强=语音双栈全线接线（TTS 3+ 引擎/ASR 4 引擎/流式/语音纪要/渠道出入站三形态契约/SIP+Twilio）、桌面屏幕视觉（截图+UIA+SOM+感知三闸，对方无对应物）、OCR 三引擎同契约、AIGC 端点实测纪律+aigc_studio 分镜管线；对方产品面断点=TTS 有 6 家实现聊天 UI 未接线/realtime 纯占位/听写会话端点在云侧；本仓短板=音乐生成缺失/Gemini 原生收图待核实/video_to_video 无实测协议（追平+遗留清偿后已补：fal 音乐闭环+前端页/三家 v2v/Gemini 原生装配/SIP DTMF+转写/Twilio Digits）；追平方案见同日 04-plans 多模态追平实施计划（竞品/外部对标，研究参考）
- [reference_ad_llm_access_and_adaptive_routing_teardown_2026-11-22.md](../08-research/reference_ad_llm_access_and_adaptive_routing_teardown_2026-11-22.md) — 参照系 ad 总评测的 **LLM 接入与自适应路由十轴专项细拆**（provider 接入面/协议能力/模型目录/路由决策/容错/流式/计量成本/本地模型/安全/扩展性，各 10 分）：**Neurova 70.0/100 vs 参照系 ad 86.0/100**——对方最强=路由决策（channel 级 fallback+attempt 生命周期+流式首可见输出前可换路 hold+错误分类路由语义；加权抽签与路由配置在云侧闭源、OSS routers=[]）与计量成本（fixed/tiered/lookup 定价单元+providerReportedCost 透传+消息/操作/话题三级落库）；本仓最强=容错体系（熔断/重试预算/在飞准入/每模型 QPM+并发+429 等待预算/流内静默看门狗，唯一反超轴 9.0 vs 8.5）与模型目录治理（四层事实源+探测回填+limits 四级优先生效）；自适应五级标定：本仓 L2+能力驱动仅旁路、对方 L3 主线+L4 框架在云，双方均无学习型路由；借鉴 P0×3（attempt 级 fallback+hold 换路/能力驱动选型进主链路/错误分类路由语义表）+P1×3+P2×2，不照搬×3（云侧策略依赖/91 家铺量/框架在 OSS 策略在云模式）（竞品/外部对标，研究参考）

- [reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md](../08-research/reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md) — 与 lobehub/lobehub（LobeHub，85.9k stars，124 子包/378 万行 TS，"Super-Agents on Your Team"：agent 运行时+44 内置工具+91 家模型 provider+设备控制+7 渠道 IM 接入+Electron/CLI 端）的全方位代码级对照评测（v6 共 11 维 120 分：v2 自进化维、v3 活水池专项、v4 工具肌肉记忆专项、v5 多模态十轴专项、v6 多模态追平实施）：**Neurova 95.0/120 vs 参照系 ad 98.0/120**——对方在模型接入（91 vs 7）/工具生态与执行安全（三档沙箱+44 真工具）/认证（17 SSO+Passkey+自建 OIDC IdP）/数据层（242 表 228 迁移）/工程纪律（7321 测试文件+alint 模型背书 lint+四通道 OTA）六维领先，本仓在多智能体治理（审批链 L0-L2/候选 CAS/依赖门 vs 对方投票未实现+delegate 禁用）/记忆生命周期（睡眠整理+遗忘+纪律准入 vs 对方无遗忘无衰减）/本体图谱（对方为零）/租户隔离真实执行（对方 OSS RBAC 系空壳 stub）/MCP server 面（对方仅 client）/自我进化（对方=默认关闭的受控自改进：无评测闭环、无影子灰度、回滚靠人 vs 本仓门禁链+影子验证+回滚+存活探针世代闭环）/多模态（v5 十轴细拆 69.0 vs 68.5、v6 追平实施+遗留清偿后复评 75.5：语音双栈+屏幕视觉+OCR 本仓胜、生成广度对方胜）七处反超；借鉴 P0×3（跨 provider 路由容错/检索质量三件套 rerank+阈值+ANN/auto-run 不可绕过黑名单强制层）+ P1×4（+教训→验证判据编译注入）+ P2×4（+弱信号累加器反思触发），不照搬×4（三轨 API 与超细粒度 monorepo/云服务强依赖/主进程直执行无隔离 shell/静态模型卡远端拉取）（竞品/外部对标，研究参考）
- [reference_ac_vs_neurova_coding_agent_control_plane_evaluation_2026-11-21.md](../08-research/reference_ac_vs_neurova_coding_agent_control_plane_evaluation_2026-11-21.md) — 与 pingdotgg/t3code（编码 agent 开源控制平面，67.8k stars，约 20 万行 TS：事件溯源编排 + 十一家编码 agent 接入 + 桌面/Web/手机三端远程控制）的代码级对照评测（20 子项）：**Neurova 72.0/100 vs 参照系 ac 92.0/100**——对方在上下文传递五类型工件化/命令回执幂等/checkpoint 隐藏 ref 协同回滚/provider 中途切换五结果决策四处形成代差，本仓在并发准入治理/审批房间多人回灌/租户隔离三项反超；借鉴 P0×4（命令回执幂等/上下文传递工件化含预算与可恢复省略/能力驱动切换决策/raw 诊断记摘要不记值）+ P1×6（隐藏 ref 检查点/审批请求持久化+live|message 双通道/记忆式批准/探测无副作用/evals 先 case 后修/子代理完成投递 cohort）+ P2×5，不照搬×4（Effect-TS 栈与万行巨石/默认 full-access/云中继推送依赖/双协议栈）（竞品/外部对标，研究参考）
- [reference_ac_ide_integration_gap_analysis_2026-11-21.md](../08-research/reference_ac_ide_integration_gap_analysis_2026-11-21.md) — 参照系 ac（T3 Code）**IDE 接入支持范围专项**：对方=控制面形态（无编辑器插件），11 内置 driver（Codex 私有 JSON-RPC/Claude 官方 SDK/Cursor worker SDK/OpenCode HTTP-SSE/Pi 私有 RPC/Muse MSP + Grok/fx/Kiro/Antigravity ACP flavor）+ **ACP registry 零代码接入**（官方注册表发现+SHA-256 校验安装+7 特例 flavor），统一 ProviderAdapterV2 约 25 方法+12 组能力 schema、真实 transcript 回放测试契约、四档权限只暴露原生模式；对照本仓 8 家族目录/自研 ACP v1/plugin 执行体得出五条差距（接入成本档/回放契约/适配器方法面/多端连接运行时/权限两小项）与 P0-P2 补齐方案（registry 零代码接入+回放契约先行；编辑器插件/云中继/PTY 终端面明确不做）（竞品/外部对标，研究参考）
- [reference_ab_vs_neurova_managed_agent_orchestration_evaluation_2026-11-20.md](../08-research/reference_ab_vs_neurova_managed_agent_orchestration_evaluation_2026-11-20.md) — 与外部「平台托管型多智能体编排」解决方案 Guidance（IaC 装配 + 托管 Agent 平台原生监督者协作 + 4 领域子代理 + 向量知识库/text2SQL + WebSocket 流式 + React Flow 协作图；约 2.8 万行、76 stars）的对照评测（10 维 30 子项）：**Neurova 81.6/100 vs 参照系 ab 44.6/100**——编排智能全托管使对方在任务分解/生命周期/结果聚合/审批治理四维近乎空白，本仓 D5/D6 大幅领先；唯一平手维=记忆与知识接入（7.3 vs 7.3，对方强在数据工程与摄取自动化三件套）；对方最强单项=React Flow 实时协作可视化（9/10 全场最高）；借鉴 P1×3（蜂群协作拓扑图可视化/外部成员验收判定通道补线/知识摄取部署钩子+巡检双保险）+ P2×4（成本透明表/text2SQL 只读档/候选板可查询投影/trace 服务端投影），不照搬×4；顺带钉实本仓在途落差 5 处（外部成员 verify_channel 未接线/cost_source 未落地/候选板进程内态/租户化三遗留/插件单向控制）（竞品/外部对标，研究参考）
- [reference_o_vs_neurova_acp_access_comparison_2026-11-20.md](../08-research/reference_o_vs_neurova_acp_access_comparison_2026-11-20.md) — 与 botiverse/oar（Open Agent Runtime，自研 record-stream 归一层驱动 14 个编码 agent runtime，5.4 万行核心+6.7 万行测试）的接入方式专项对比（v2 含源码级走读）：单流全序事件保真/能力显式声明+打开前拒绝/会话外管理面/内核级同构测试桩为 OAR 强项，治理与多租户/多 agent 编排/ACP 标准生态为本仓强项，评分卡 v2 OAR 76 vs neuacp 73；借鉴五条（能力声明+打开前拒绝/控制与事实同流全序/事件保真不推断/内核级同构桩/谱系归因进事件流）待拍板（竞品/外部对标，研究参考）
- [agent-memory-cutting-edge-research-2026.md](../08-research/agent-memory-cutting-edge-research-2026.md) — Agent 记忆前沿研究
- [agent_memory_consciousness_research_20260511.md](../08-research/agent_memory_consciousness_research_20260511.md) — 记忆与意识调研
- [neurova_memory_consciousness_enhancement_20260511.md](../08-research/neurova_memory_consciousness_enhancement_20260511.md) — 记忆意识增强方案
- [AIGC生成端点矩阵_2026-09-14.md](../08-research/AIGC生成端点矩阵_2026-09-14.md) — AIGC 图像/视频生成端点矩阵（官方文档核实 + 真实 HTTP 探测，模型管理预置与 AIGC 页能力过滤的参考盘点）
- [reference_w_vs_neurova_tool_loop_comparison_2026-09-26.md](../08-research/reference_w_vs_neurova_tool_loop_comparison_2026-09-26.md) — 与外部编码代理 ZCode 的工具调用与迭代循环对标，含 G1–G8 缺口复验与自我更正记录（竞品/外部对标，研究参考）
- [reference_q_vs_neurova_rsi_comparison_2026-10-06.md](../08-research/reference_q_vs_neurova_rsi_comparison_2026-10-06.md) — 与外部 RSIAgent 的 RSI 代码级对比（竞品/外部对标）
- [reference_t_vs_neurova_skill_consolidation_2026-10-07.md](../08-research/reference_t_vs_neurova_skill_consolidation_2026-10-07.md) — 与外部技能沉淀论文 SkillGLoW 的技能域对比：吸收账本迁移、召回预检、全自动整合提交闸的落地登记与规则修订记录（竞品/外部对标，研究参考）
- [designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md](../08-research/designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md) — 与 Designer-RSI 论文（arXiv:2609.22086）的程序性记忆对照（竞品/外部对标）
- [reference_g_vs_neurova_aigc_pipeline_comparison_2026-10-08.md](../08-research/reference_g_vs_neurova_aigc_pipeline_comparison_2026-10-08.md) — 与外部自托管短剧流水线 dramaclaw 的 AIGC 管线代码级对比，含整合否决裁决的取证（竞品/外部对标，研究参考）
- [reference_s_vs_neurova_knowledge_graph_comparison_2026-10-09.md](../08-research/reference_s_vs_neurova_knowledge_graph_comparison_2026-10-09.md) — 与外部图谱工具链 Semantica（MIT / 22.4 万行）的知识库与知识图谱代码级对比，含本仓自有断点 N1–N6 与候选 K1–K8（竞品/外部对标，研究参考）
- [reference_m_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md](../08-research/reference_m_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md) — 与 ModularRSI 论文（arXiv:2609.14857）的 harness 递归自我改进对照，只记 RSIAgent／Designer-RSI 两篇前作未覆盖的增量项 M-A..M-E（竞品/外部对标，研究参考）
- [reference_j_vs_neurova_recursive_harness_comparison_2026-10-21.md](../08-research/reference_j_vs_neurova_recursive_harness_comparison_2026-10-21.md) — 与 google-research/harness2 的递归 harness 优化代码级对比：十维加权（权重 100% 归一）当前评估 7.8 vs 8.1、生产就绪度单列读数、本仓断点 N1–N8 与候选 C1–C8（N1–N8 已落地/部分落地，闭环 A–D、N6/C6/N8、完整工具 trace、跨域 UI、产物二进制证据与独立采纳流已落，竞品/外部对标，研究参考）
- [reference_u_paper_vs_neurova_associative_memory_comparison_2026-10-21.md](../08-research/reference_u_paper_vs_neurova_associative_memory_comparison_2026-10-21.md) — 与 T-Mem 论文（arXiv:2606.15405，EMNLP 2026，MIT，commit `dd9e152`）的记忆系统代码级对比：无表面重合「联想召回」可达性议题、写入侧预演的 800–900 次调用/构建成本复算、消融读数指向前瞻族独大、用户所述八步流程的四处更正、本仓自有断点 D1–D7 与候选 TM-1..TM-6（含不照搬清单与未验证项，竞品/外部对标，研究参考）
- [reference_h_vs_neurova_attention_and_authorization_comparison_2026-10-31.md](../08-research/reference_h_vs_neurova_attention_and_authorization_comparison_2026-10-31.md) — 与外部编码代理研究原型（deepseek-ai/dsh-superagent-prototype，浅克隆 @ 6337fc82，README 自述非官方产品/非生产级）的「注意力预算 / 授权门 / 工单模型」代码级对比：**外部侧未实跑**（依赖整套私有包，绿灯不可复现），作者另抽验 6 条关键断言原文；本仓自有断点 N-1..N-5（出口无注意力预算、台账 status 可漂移、"需要人"只有台账筛选非队列、审批可堆叠无一次一问、授权面两处不同源）与候选 D-1..D-6，含 11 条不照搬清单（JSON 列塞聚合、YAML 执行 JS、danger-full-access 与无 token 面板、无界增长、await 后重读式并发约定、交集扩权与默认监听、正则改写历史、私有依赖无 CI 等）与未验证项（竞品/外部对标，研究参考）
- [reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md](../08-research/reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md) — **QwenPaw vs Neurova 权威版对照**：改用主流 harness 十维中立框架（规划/工具执行/上下文/记忆/自我演化/编排/HITL/安全/可靠性/生态，等权百分制），两侧均逐文件代码走读（QwenPaw 六路 + Neurova 三路补读）。**结论：QwenPaw 81.5 vs Neurova 80.5 基本打平**——QwenPaw 领先在产品化完成度（工具执行 9.0/安全沙箱 9.0/HITL 8.5/生态部署 9.5），Neurova 领先在 harness 纵深（规划 8.0/记忆 9.5/自我演化 RSI 9.0/编排 9.0/可靠性恢复 8.5）；含双方改进清单。取代 2026-11-17 形态标尺版的总评结论（竞品/外部对标，研究参考）
- [reference_x_vs_neurova_phone_gateway_comparison_2026-11-19.md](../08-research/reference_x_vs_neurova_phone_gateway_comparison_2026-11-19.md) — 与外部真机操控安全网关项目（Go 桌面应用：agent 经 MCP 操作真实手机、人全程在环）的机制对照：网关式强制审批（审批绑定参数摘要 + 单次使用 + 执行前快照复核）、入模前统一脱敏闸（验证码打码/敏感应用隐身/秘密键 redacted）、26 工具设备域契约（租约/只读档/应用白名单/托管任务六件套）、条件触发调度与任务报告导出；本仓治理链已同构，差距收敛为 P1×3 + P2×3 借鉴项与五条不照搬项（竞品/外部对标，研究参考）
- [reference_y_vs_neurova_ontology_evaluation_2026-11-19.md](../08-research/reference_y_vs_neurova_ontology_evaluation_2026-11-19.md) — 与外部「企业数据→本体→知识图谱」平台（Go+Next.js 约 19.9 万行；连接器→本体 agent 起草→人审→图加载→带引用问答）的**本体域专项对照评测**（8 维 20 子项评分卡，取代同日已撤回的整体架构评测）：**Neurova 90/100 vs 参照系Y 77/100，领先 13 分**——本仓大胜建模表达力（14vs8：层次/多语言/单位/SHACL 形状）与互操作工程（15vs9：九格式导出+Ossie vs 仅私有格式），对方强在 agent 端到端起草本体（5 分全场最强单项）、mappings 映射语言、claim 级证据哈希人审与 load 版本工程；借鉴清单 P1×3（Check 三臂对照门禁/Audit 数据驱动缺口审计/Assess 本体贡献度评估）+ P2×3（映射增强/版本 impact 预标注/Probe 模型体检）+ **P3-1 血缘专项展开**（差距三处：审批决策绑定证据内容哈希 StatementHash/事实证据位置锚定 ClaimSpan/答案逐论断强制引用 citation；远期两项：行级数据血缘/事实级快照对比；已同构面=推导账本/双时态/PROV-O 勿重复建设），引擎闭源黑盒为评分主要局限；**借鉴清单 P1–P3 已全部实施**（批1 `dab74d955` 映射 transform/missing+impact 预标注+模型体检；批2 `11c050a63` checkGate 三臂门禁+缺口审计+问数贡献度评估；批3 `21a7ff7de` 审批证据哈希绑定+断言位置锚定+答案逐论断引用；实施回执与 A/B、live-verify 证据见报告 §8）（竞品/外部对标，研究参考）
- [reference_z_vs_neurova_agent_team_orchestration_comparison_2026-11-19.md](../08-research/reference_z_vs_neurova_agent_team_orchestration_comparison_2026-11-19.md) — 与外部「多代理编码团队编排 harness」（TypeScript 约 5 千文件、8.9k stars、daemon+终端复用驾驶未改装编码 agent、YAML 团队拓扑、CLI/TUI/MCP 三入口）的机制对照：**与本仓 neuacp 计划正面撞题**——对方 ACP 双向（serve 当 agent/run 当 client）、权限请求→审批行报价-应答咬合、结局五态诚实契约（unknown=无证据即不认完成）、进程清算（环境标记继承+三态）、占用者代际防幽灵认领、终态 closure_reason 封闭集强制、stub 场景+缺陷种子成对验收 CI 均为本仓在途批的直接对照基准；借鉴 P0×2+P1×5+P2×4，不照搬×5（交互式驾驶路线/单机无租户/编排层不持权限政策等）（竞品/外部对标，研究参考）
- [reference_d_vs_neurova_personal_assistant_harness_evaluation_2026-11-17.md](../08-research/reference_d_vs_neurova_personal_assistant_harness_evaluation_2026-11-17.md) — 【形态标尺专项视角，总评以 2026-11-18 十维版为准】与阿里 AgentScope 团队个人 AI 助理 QwenPaw（71.5 万行 Python；18 渠道/16 技能/41 插件/37 provider/多平台内核沙箱）的代码级对照：按其个人助理形态定制八维加权评分 QwenPaw 86.5 vs Neurova 82.5（v5 修订：Neurova 侧渠道/技能/安全/记忆上下文知识/记忆架构五处经逐文件核实后上调——channels 59 文件 12+ 渠道域、context 折叠层级索引+增长门、memory_layer 类脑多层级记忆（肌肉记忆 L1/L2/L3+NeuHebb+睡眠整合+贝叶斯遗忘）、knowledge/ontology 40 模块 9k 行 SPARQL/规则引擎/血缘/nl2sql 为 QwenPaw 无对等物），Neurova 多 agent 编排治理与知识语义层领先（9.0 vs 6.5 / 9.5 vs 8.5），含 9 条可借鉴清单（声明式停止门编译/工具双截止/沙箱 Python recall/人机共编蒸馏/渠道子进程隔离+依赖审计/技能扫描双语规则库/per-model 限流/审批泛化校验/覆盖率棘轮）与 5 条不照搬项（竞品/外部对标，研究参考）
- [reference_a_vs_neurova_final_evaluation_2026-11-18.md](../08-research/reference_a_vs_neurova_final_evaluation_2026-11-18.md) — **CoworkOS vs Neurova 终评**：S1–S18 全批 + 前端缺口收口 + 1F 真模型复跑落地后的独立重评（七维廿二子项体系与锚点不变，22 项全表；19/22 子项现场复核含全部 5 分子项，引证 commit 经 git log 逐一核验）——**Neurova 101/110（91.8%）vs CoworkOS 95，超越成立且领先 6 分**，四轮座次 70→84→98→101，七维全部 ≥ 参照系（A 协作形成/B 执行协调/E 治理安全领先，C 通信/D 记忆/F 观测评测/G 互操作追平）；唯一遗留缺项 A1 角色贡献辩护（参照系亦无）（竞品/外部对标，研究参考）
- [reference_w_agent_loop_comparison_2026-11-15.md](../08-research/reference_w_agent_loop_comparison_2026-11-15.md) — 与外部编码代理 ZCode 的 Agent 主循环机制对照——Neurova 视角分析与可补充候选（竞品/外部对标，研究参考）
- [reference_e_vs_neurova_context_compression_comparison_2026-11-14.md](../08-research/reference_e_vs_neurova_context_compression_comparison_2026-11-14.md) — 与 ranxianglei/billion-context（v0.1.213，含内嵌 acp-kernel）的上下文压缩机制代码级对照测评（竞品/外部对标，研究参考）
- [reference_f_vs_neurova_context_compression_comparison_2026-11-17.md](../08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md) — 与 Apple ML Research 论文 Self-Compacting Language Model Agents（SELFCOMPACT）的上下文压缩时机对照测评（竞品/外部对标，研究参考）
- [reference_i_vs_neurova_temporal_kg_memory_comparison_2026-11-13.md](../08-research/reference_i_vs_neurova_temporal_kg_memory_comparison_2026-11-13.md) — 与 getzep/graphiti（Zep 开源时序知识图谱记忆框架）的时序 KG 记忆对照测评（竞品/外部对标，研究参考）
- [reference_v_vs_neurova_harness_evolution_comparison_2026-11-14.md](../08-research/reference_v_vs_neurova_harness_evolution_comparison_2026-11-14.md) — 与论文 VideoEvolve（arXiv 2610.01766）的 harness 自进化机制对照测评（竞品/外部对标，研究参考）
- [reference_w_computer_use_comparison_2026-11-17.md](../08-research/reference_w_computer_use_comparison_2026-11-17.md) — 与外部编码代理 ZCode 的电脑操控（Computer Use）对照测评（竞品/外部对标，研究参考）
- [reference_w_swarm_orchestration_comparison_2026-11-15.md](../08-research/reference_w_swarm_orchestration_comparison_2026-11-15.md) — 与外部编码代理 ZCode 的子代理（蜂群）与任务编排/拆解机制对照（竞品/外部对标，研究参考）
- [reference_w_tool_inventory_comparison_2026-11-15.md](../08-research/reference_w_tool_inventory_comparison_2026-11-15.md) — 与外部编码代理 ZCode 的工具调用与工具数量对照分析（竞品/外部对标，研究参考）
- [reference_w_vs_neurova_harness_code_comparison_2026-11-14.md](../08-research/reference_w_vs_neurova_harness_code_comparison_2026-11-14.md) — 与 zai-org/ZCode 的代码级 harness 对照测评（竞品/外部对标，研究参考）
- [multi_agent_bench_baseline_2026-11-17.md](../08-research/multi_agent_bench_baseline_2026-11-17.md) — 多 Agent 协作评测基线 v1：真模型 13 任务 solo/swarm 实测（真模型基准实测，研究参考）
- [multi_agent_bench_baseline_v2_2026-11-18.md](../08-research/multi_agent_bench_baseline_v2_2026-11-18.md) — 多 Agent 协作评测基线 v2：新判据口径、真模型 26 任务 solo+swarm 复跑（真模型基准实测，研究参考）

### 09-dev-progress 开发进展

- [README.md](../09-dev-progress/README.md) — 开发进展索引
- [frontend_development_plan.md](../09-dev-progress/frontend_development_plan.md) — 前端开发计划
- [api_inventory.md](../09-dev-progress/api_inventory.md) — 前端 API 面清单（生成物：`python scripts/generate_api_inventory.py --write`，含「调用未命中后端」「后端无前端消费」两组显式差异）
- [progress_tracker.md](../09-dev-progress/progress_tracker.md) — 进度追踪
- [module_designs/](../09-dev-progress/module_designs/) — 模块设计（含 chat_page/execution_engine/knowledge_base 等）
- [daily_reports/](../09-dev-progress/daily_reports/) — 日常报告（2026-05-12/13）
- [code_reviews/](../09-dev-progress/code_reviews/) — 代码评审
- [architecture/frontend_architecture_guide.md](../09-dev-progress/architecture/frontend_architecture_guide.md) — 前端架构指南

### 10-configuration 配置

- [CHANNELS_CONFIG_TEMPLATE.md](../10-configuration/CHANNELS_CONFIG_TEMPLATE.md) — 渠道配置模板
- [DEPLOYMENT_CONFIG.md](../10-configuration/DEPLOYMENT_CONFIG.md) — 部署配置契约（Dockerfile / docker-compose / Helm 跨文件不变量 + 门禁）
- [KNOWLEDGE_BASE.md](../10-configuration/KNOWLEDGE_BASE.md) — 知识库索引接线（索引面 / 参数口径 / Open API 检索 / 重建方式）
- [MOBILE_APP_SIGNING.md](../10-configuration/MOBILE_APP_SIGNING.md) — 移动端签名获取指南（鸿蒙 + 安卓：本地已生成 keystore/CSR 的位置与指纹、AGC 换发证书/Profile 流程、Gradle 与 build-profile.json5 接线样例、密码/私钥不入库纪律；机密件已 .gitignore，清单见 Mobile/signing/INFO.md）

### 11-legacy 归档

- [UI_FRAMEWORK_GUIDE.md](../11-legacy/UI_FRAMEWORK_GUIDE.md) — 旧 UI 框架指南（2026-11-19 自 `03-user-guide/` 归档；文中原生 JS 组件体系在当前代码中不存在，现行前端为 NeurUI/Vue 3，勿按其开发）
- 历史/过时文档（grilling-* 分析、旧升级方案、旧 UI 方案、旧测试结果等），保留可追溯，不再维护。

---

## 维护指南

0. **纪律变更**：[`/AGENTS.md`](../../AGENTS.md) 是全仓纪律唯一事实源（`.cnb/settings.yml`
   的 NPC 人设与 `CONTRIBUTING.md` 逐条对齐）。改纪律须同步该文件 + 人设 + 人类入口三处落点，由
   `tests/unit/test_repair_discipline_guard.py` 常驻校验，禁止另造平行准则文档。

1. **新增模块**：在本文档"功能模块矩阵"增加一行（对照代码标注状态）
2. **状态变更**：功能从🟡→✅ 或⬜→🟡，更新矩阵 + 对应架构文档头部状态
3. **新文档**：按领域放入对应目录，在此索引的文档列表添加一行
4. **文档规范化**：文件名需有语义，日期放文件名尾部

> 归档条件：被新文档取代 / 已不反映当前实现 / 纯过程性记录
