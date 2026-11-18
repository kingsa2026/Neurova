# Neurova 文档总索引

> 版本: v1.0.0-beta1 · 中文名: 智星 · 更新时间: 2026-08-31
> 本索引是 `docs/` 目录的唯一入口。功能状态标注基于对 `neurova/` 代码库的逐项核对。

## 快速导航

| 入口 | 路径 | 说明 |
|------|------|------|
| **纪律与约定（最高优先级）** | [AGENTS.md](../../AGENTS.md) | **核心原则 8 条 + 修复教义 7 条 + 协作红线（中文交流 / 原创性 / 命名法 / 闭环）**；全仓引用的唯一事实源 |
| 项目 README | [README.md](../../README.md) | 项目概述、快速开始、核心特性 |
| 项目上下文 | [CONTEXT.md](../CONTEXT.md) | 架构概览、技术栈、设计规则 |
| 文档总索引 | [docs/INDEX.md](../INDEX.md) | 文档体系唯一导航事实源 |
| 功能模块矩阵 | [见下](#功能模块矩阵) | 全部功能的状态对照 |
| API 参考 | [API_REFERENCE.md](../02-api/API_REFERENCE.md) | 82 端点模块参考 |

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
| Skill 协议兼容 | ✅ | `skills/adapters/` | [05-skill-system](../01-architecture/05-skill-system.md) |
| Skill 归档与回滚（治理面 + 技能页入口） | ✅ | `api/endpoints/governance.py` `evolution/skill_experience.py` `NeurUI/src/pages/AgentSkillPage.vue` | [05-skill-system](../01-architecture/05-skill-system.md) |
| 肌肉记忆（ToolMemory 三层） | ✅ | `cognitive_layers/memory_layer/muscle_memory.py`（L1/L2/L3 三层存取+固化/遗忘）+ `tool_memory_integration.py`（裁定门面）——写（on_tool_executed 统一记账，2026-11-18 M1 收口单源）→存（JSON 原子落盘）→读（check_tool_memory 跨层检索→auto_execute/suggest）→反馈（失败降级/权重联动/RSI 调参）全链闭环，NeuHebb 空转支路已退役 | [tool-memory-muscle-analysis](../01-architecture/tool-memory-muscle-analysis.md) |
| MCP 集成 | ✅ | `tool_layers/mcp_client.py` `mcp_config.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| MCP 治理安全加固（P0 六项） | ✅ | `tool_layers/mcp_bootstrap.py` `security/url_guard.py` | [25-mcp-governance](../01-architecture/25-mcp-governance.md) |
| LLM Provider 管理（元数据/智能路由） | ✅ | `llm/provider_manager.py` `multi_model_client.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| LLM Router（多模态选择） | ✅ | `llm/llm_router.py` | [23-llm-provider-management](../01-architecture/23-llm-provider-management.md) |
| Computer Use（视觉理解） | ✅ | `computer_use/`（vision.py + vision_lite） | [01-core-architecture](../01-architecture/01-core-architecture.md) |
| 浏览器自动化（Camofox） | ✅ | `computer_use/browser_manager.py` | [CUA 能力台账](../CUA能力台账.md)（投递路径与拒绝码登记） |
| web_reach 网络工具 | ✅ | `web_reach/`（reach.py + 5 工具） | `agent-reach-integration.md` 已随第三方痕迹清除波（685e40a3）退役 |
| 插件系统 | ✅ | `plugins/` | [06-plugin-cli-system](../01-architecture/06-plugin-cli-system.md) |
| 工具编排（Tool Orchestrator） | ✅ | `tool_layers/tool_orchestrator.py` | [07-implementation-plan](../01-architecture/07-implementation-plan.md) |

### 接口层

| 功能模块 | 状态 | 关键代码 | 关联文档 |
|----------|------|----------|----------|
| 多渠道接入（14+ 渠道） | ✅ | `channels/`（42 py 文件） | [03-message-routing](../01-architecture/03-message-routing.md) |
| REST API（82 端点模块） | ✅ | `api/endpoints/` | [API_REFERENCE](../02-api/API_REFERENCE.md) |
| NeurUI 前端（60 页面） | ✅ | `NeurUI/src/pages/` | [UI_FRAMEWORK_GUIDE](../03-user-guide/UI_FRAMEWORK_GUIDE.md) |
| 上下文管线（活水上下文池） | 🟡 | `context/`（collector/compressor/converter），P1-1 已补齐溢出恢复/真摘要等 | [26-context-pipeline-p1](../01-architecture/26-context-pipeline-p1.md) |
| 上下文缓存与压缩 | ✅ | `context_cache.py`（压缩已收口到 `context/orchestrator.py` 的确定性淘汰） | [CONTEXT_CACHE_COMPRESSION](../01-architecture/CONTEXT_CACHE_COMPRESSION.md) |
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
- [2026-11-18-assistant-harness-adoption-plan.md](../04-plans/2026-11-18-assistant-harness-adoption-plan.md) — QwenPaw 借鉴点适配落地方案（待拍板）：P0 渠道子进程隔离+握手期依赖审计/技能扫描双语签名库对齐/DoomLoop 相似度两阶段升级/审批泛化安全校验；P1 声明式停止门编译/人机共编 MEMORY.md+蒸馏/沙箱 Python recall/token 保证金/File Guard/五档执行级别/工具完成缓存查询/Shell 逃逸对抗补齐/渠道优先级队列/市场多源 priority/manifest 渠道过滤+渐进披露；P2 跨平台内核沙箱/本地模型打包等按需项；含**已对齐不立项清单**（工具三处置/per-model 限流/错误分类/MCP 熔断/记忆准入/检查点等十项，防重复建设）与**不学清单**（guardian fail-open/云端外发脚本/Markdown 念 CLI/双份目录/沙箱默认关等七条反模式）；**P2 二轮严格化推翻 C2/C3/C5 初判并落地；B2 MEMORY.md 已退役（ca23e3940，蒸馏回写改道温度体系）**
- [2026-11-18-memory-distillation-plan.md](../04-plans/2026-11-18-memory-distillation-plan.md) — 记忆蒸馏回写立项方案（**已实施 D1–D4**，cb5252226/b7b927cf6）：对话轮末异步 LLM 归纳"值得长期记住的事实"→ memory_admission 敏感筛查 → pending_memories 候选（指纹去重/租约/tombstone）→ 人工审阅（复用 pending 审阅面+S16 纪律转正）→ memories 表温度生命周期；`NEUROVA_MEMORY_DISTILL` 灰度默认 off、预算护栏/失败熔断/候选洪水防护；红线=不直写 memories、不恢复 markdown 旁路、fail-soft 不阻断主对话；A/B 三域零新增、live-verify 真治理链（候选→审阅→落库可检索）全通，依据 QwenPaw 批 B2 后续裁定（蒸馏接温度机制、MEMORY.md 退役）
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
