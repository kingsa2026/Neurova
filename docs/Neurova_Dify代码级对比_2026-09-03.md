# Neurova × Dify 代码级深度对比与启发

> 对比日期：2026-09-03
> 对比基线：Dify `langgenius/dify` main（release 镜像标签 **1.17.0**，last push 2026-09-03，154,276 ★ / 24,394 fork）vs Neurova `main`（a939408e）
> 方法：Dify 以 **浅克隆 + 稀疏检出源码**（api/ 全量 + docker/）逐模块核对，测试/文档用 docs.dify.ai 交叉验证；Neurova 侧以代码存量核对 + 子系统扫描。所有 Dify 结论有文件路径佐证，所有 Neurova 结论均有当前代码文件锚点。

---

## 0. 结论先行（TL;DR）

Dify 对 Neurova 最有价值的启发不是"复制功能"，而是 **五个工程决策**：

1. **把图引擎抽成独立库 `graphon`**：Dify 1.17 的 api/core 只剩 8.9k 行，引擎（Graph / VariablePool / 节点类型 / 层协议 / 事件总线）全部外迁到 langgenius 自有 PyPI 包 `graphon==0.7.0`。Dify 侧只写"Dify 特化节点 + 横切层"。这就是"深度模块 + 面向 Agent 的代码可读性"的活标本。
2. **横切关注点全部做成分层的 `GraphEngineLayer`**：观测（每节点 OTel span）、执行持久化、暂停/恢复（HITL）、对话变量持久化、时间切片、触发器后置、Agent 工作区回收——7+ 个层，插拔式挂在引擎上。
3. **插件=声明式 manifest + 运行隔离 + 反向调用**：manifest 用 `resource.permission` 显式声明工具/模型（llm/embedding/rerank/tts/asr/moderation）/节点/endpoint/app/存储容量六类权限；模型提供方、工具、Agent 策略、触发器、endpoint 全部插件化，运行时在 plugin-daemon 里，插件可"反向"被主应用调用、也能"反向"把 endpoint 注册出来给外部开发者。
4. **模型 6 型统一契约**：LLM / TextEmbedding / Rerank / Speech2Text / Text2Speech / Moderation，全部走 `_invoke` + `_get_num_tokens` + `validate_*_credentials` + `_invoke_error_mapping`（连接错误/服务不可用/限频/鉴权/坏请求五类标准化），参数与能力上下文从 provider/model YAML schema 元数据化。
5. **RAG 的检索策略与"选库"是分开的两层**：`RetrievalMethod`（semantic/full_text/hybrid/keyword 4 态）是数据源内检索；`multi_dataset_function_call_router` / `multi_dataset_react_route` 是多库路由；rerank 工厂双模式（模型重排 / 加权分融合），全链路有结构化的 Node output（含 chunk 编号、score 明细），画布上可直接 inspect。

按"对 Neurova 现状的净增量 + 改动成本"排序的**可落地清单**（详见 §4，P0=1~4 周级、P1=1~2 月级、P2=长线）：

- **P0-1 工作流执行流式化**：run/stream 分离 + `/executions/{id}/events` SSE 节点级事件——当前 `execute` 端点**同步阻塞**，是与 Dify 画布体验差距最大的一项。
- **P0-2 RAG 分块管线**：Dify splitter 式分段分块；当前摄取是"整篇存 JSON 不分块"。
- **P0-3 混合检索复活 + rerank 双模**：`fts` 权重恒 0 占位 + 全库无 rerank；抄 `RetrievalMethod` 四态 + `RerankRunnerFactory`（模型重排/加权融合）。
- **P0-4 技能 manifest 声明式权限**：抄 `resource.permission`（tool/model/node/endpoint/app/storage）——Neurova 治理是"调用时三态"，缺"安装时声明"。
- **P0-5 OTel 兼容层**：自研 `TrajectoryRecorder` 已有 span 模型，加 OTel bridge（可选依赖）即可接 Langfuse/Opik，单节点 span（node_results 已含 duration/tokens/cost）无需改业务代码。

**P1（发现即有基础，主要是补面）**：单节点 step-run 画布 UX（后端 `DebugSession` 已支持断点/step_mode/mock/变量检查）、HITL surface 安全模型（抄 `HumanInputSurface` 按调用面裁剪接收方）、workflow_as_tool（子流程注册为 agent 工具）、多库路由（FC 选库）、MCP server 面（平台当 MCP server 暴露）、节点 token 计量接配额、**双轨工作流引擎收敛**（`collaboration/neurflow/` 为唯一引擎，见 §3.1）。

**P2（按需长线）**：标注闭环（annotation reply）、trigger 统一契约、snippet/命令面板、检索溯源 UI。

**明确不建议抄的**：多租户 SaaS + 计费 + RBAC 企业版全套、Celery/Redis/Postgres + 多向量库微服务全家桶、plugin-daemon 子进程沙箱与签名市场、Next.js 前端迁移、20 节点全谱（按需保留子集）。

---

## 1. 规模基线（数字对数字）

| 维度 | Dify 1.17.0 | Neurova |
|---|---|---|
| 仓库规模 | 527,463 KB（含历史） | ~? |
| 后端文件 | api/ 1,767 个 .py | neurova/ 740 个 .py |
| 后端行数 | api/ ~190k 行（controllers 65.8k / services 89.6k / models 13.4k / tasks 10.1k / core 8.9k） | neurova/ 46,319 行 |
| 测试 | api/tests 1,355 文件 / 98,566 行（api 内 0 个 test_*.py，全在独立 tests 目录） | tests/ 972 文件（含 ad-hoc） |
| 控制器/端点 | api/controllers 240 文件（console 29 个模块目录） | neurova/api/ 若干 |
| 前端 | web/ Next.js + React（ReactFlow 画布，18+ locale） | NeurUI/ Vue 3（320 vue/ts 文件，11 locale） |
| 基础设施 | Postgres/MySQL + Redis + Celery Worker + sandbox 容器 + plugin-daemon + agent-backend + agent-local-sandbox + squid + 多向量库（weaviate/qdrant/pgvector/seekdb/oceanbase/couchbase） | SQLite + 单进程（事件循环内并发） |
| 对外形态 | 多租户 SaaS（Cloud/社区版/企业版）+ API + CLI(difyctl) | 本地桌面 + Web + 官网（个人助手定位） |

---

## 2. Dify 架构全景（代码级，2026-09-03 main 实测）

### 2.1 图引擎外迁：`graphon` 是独立库

```python
# api/pyproject.toml:48
"graphon==0.7.0"
```
`graphon`（github.com/langgenius/graphon，PyPI 发布）承担了 Dify 的 DAG 引擎核心：
`Graph`、`GraphRuntimeState`、`VariablePool`、`BuiltinNodeTypes`/`NodeType`、`graph_engine.layers.GraphEngineLayer`、`GraphEngineEvent` 事件总线、`graphon.model_runtime.entities.llm_entities.LLMStructuredOutput`。

Dify 侧只剩薄封装与特化：
- `api/core/workflow/`（接入层：`graph_topology.py`（86 行拓扑）、`node_factory.py`、`node_runtime.py`、`template_rendering.py`、`variable_pool_initializer.py`、`workflow_entry.py`、`llm_node.py`——且 `llm_node.py` 注释写明 "Dify-specific node once graphon exposes a polling finalization hook"，即特化节点挂在引擎之上）。
- `api/core/app/apps/`：`workflow_app_runner.py`、`pipeline/pipeline_runner.py`（**Pipeline 是新 App 类型**——RAG 管线本身作为一等应用）、`execution_coordinator.py`、`advanced_chat/`、`agent_app/`。

### 2.2 横切层：GraphEngineLayer 化

`api/core/app/layers/` 与 `api/core/app/workflow/layers/`：

| 层 | 文件 | 职责 |
|---|---|---|
| ObservabilityLayer | `workflow/layers/observability.py` | 每节点创建 OTel span，建立上下文，HTTP/DB 自动插桩自动归属节点 span |
| WorkflowPersistenceLayer | `workflow/layers/persistence.py` | 执行/节点执行明细持久化（`repositories/factory.WorkflowExecutionRepository`） |
| SuspendLayer | `app/layers/suspend_layer.py` | 监听 `GraphRunPausedEvent`，把运行态落库等待 resume（HITL 挂起） |
| ConversationVariablePersistenceLayer | `app/layers/conversation_variable_persist_layer.py` | 会话变量跨轮次持久化 |
| TimeSliceLayer | `app/layers/timeslice_layer.py` | 时间切片（长任务分片/续跑） |
| TriggerPostLayer | `app/layers/trigger_post_layer.py` | 触发器启动后置处理 |
| PauseStatePersistenceLayer | `app/layers/pause_state_persist_layer.py` | 暂停状态持久化 |
| AgentWorkspaceRetirementLayer | `workflow/nodes/agent_v2/workspace_retirement_layer.py` | agent 工作区回收 |

观测层关键实践：`_NodeSpanContext` 用 `contextvars.Token` 进出 OTel 上下文，`extensions/otel/parser.py` 提供 `DefaultNodeOTelParser / LLMNodeOTelParser / RetrievalNodeOTelParser / ToolNodeOTelParser` 按节点类型结构化 span 属性（semconv `DifySpanAttributes`）。

### 2.3 节点类型与调试设施

graphon 内建节点（代码枚举实测）：START / END / LLM / AGENT / ANSWER / CODE / TEMPLATE_TRANSFORM / PARAMETER_EXTRACTOR / QUESTION_CLASSIFIER / IF_ELSE / ITERATION / LOOP / VARIABLE_AGGREGATOR / LEGACY_VARIABLE_AGGREGATOR / LIST_OPERATOR / TOOL / HTTP_REQUEST / KNOWLEDGE_RETRIEVAL / DOCUMENT_EXTRACTOR / DATASOURCE / HUMAN_INPUT，另加触发器节点（schedule / webhook / plugin，`trigger/debug/` 有 event_bus + event_selectors）。

HITL（`api/core/workflow/human_input_policy.py`）：`HumanInputSurface = SERVICE_API / CONSOLE / OPENAPI`，**按表面裁剪接收方**（SERVICE_API/OPENAPI 只能收 STANDALONE_WEB_APP 的 web 表单，CONSOLE 只收 CONSOLE/BACKSTAGE）——这是对 API 安全模型的显式声明，值得照抄。表单（`nodes/human_input/`）支持 `FormInputConfig / SelectInputConfig`，暂停原因为 `HumanInputRequired/DifyHITLEventType`。

调试/开发周期（docs：`use-dify/debug/step-run`、`variable-inspect`、`history-and-logs`、`error-type`、`predefined-error-handling-logic`）：单节点运行、变量检查、历史日志回放、错误类型诊断、预置错误处理逻辑；`UseDify/build/version-control.md`（草稿/发布/回滚）、`snippet.md`（片段复用）、`workflow-collaboration.md`（协同编辑）、`goto-anything.md`（Cmd+K 全局命令面板）。

### 2.4 插件体系（2026 主线）

**Manifest（YAML，契约实测于 docs + `plugin/entities/plugin.py`/`plugin_daemon.py`）**：
- `version` / `type: plugin` / `author` / `label（多语言）` / `created_at` / `icon`
- `plugins`: 声明 extension 文件路径数组 —— `tools` / `models` / `agent_strategies` / `endpoints`
- `meta`: manifest 版本、`arch`(amd64/arm64)、`runner`（language **python 3.12**、entrypoint `main`）
- `resource`（**声明式权限与配额**）：`memory` 上限；`permission.tool.enabled`（反向调工具）、`permission.model.enabled + {llm, text_embedding, rerank, tts, speech2text, moderation}`（反向调模型）、`permission.node.enabled`（反向调节点）、`permission.endpoint.enabled`（注册 endpoint）、`permission.app.enabled`（反向调应用）、`permission.storage.{enabled, size}`（持久化 KV 配额）
- `privacy`（上架市场必填）
- 组合限制：工具+模型不可共体、模型+endpoint 不可共体、扩展列表不可为空；每类型当前仅支持一个 provider 文件。

**运行时结构**（`api/core/plugin/`）：
- `impl/model_runtime.py`（750 行）：`client.get_model_schema()` 从 plugin-daemon 拉 schema，`get_model_schema`/模型校验/调用全部走 daemon 客户端契约——**主应用不直接执行插件代码**。
- `impl/`：agent / asset / datasource / debugging / dynamic_select / endpoint / exc / model / oauth / plugin / tool / trigger 全套客户端。
- `backwards_invocation/`（反向调用）：model.py、tool.py、node.py —— 插件运行时可以回调主应用的模型/工具/节点能力。
- `entities/`：bundle / endpoint / marketplace / oauth / parameters / request / plugin / plugin_daemon。
- 发布链：marketplace-listing（release-overview / release-to-dify-marketplace / plugin-auto-publish-pr / release-to-individual-github-repo / release-by-file）+ third-party-signature-verification（签名验证）。

**模型提供方已经插件化**：`api/core/entities/model_entities.py` / `provider_configuration.py` 是主容器侧的实体；但真正的 provider 实现（`created_by=provider` YAML + 接口）在插件里提供，主应用仅通过 `ModelRuntimeClient` 消费。这与 Neurova 的 provider_manager 形成对照（见 §3.3）。

### 2.5 模型统一契约（6 型）

docs `model-schema.md`：LLM / TextEmbedding / Rerank / Speech2Text / Text2Speech / Moderation 六类，每类基类位于 `__base`：
- 统一方法：`_invoke`、`_get_num_tokens`（LLM/Embedding）、`validate_provider_credentials`（provider 级，失败抛 `CredentialsValidateFailedError`）、`validate_credentials`
- `provider_credential_schema` YAML（如 api_key、organization_id；密钥可用户级覆盖）
- `_invoke_error_mapping`：五类标准错误（连接失败 / 服务不可用 / 限频 / 鉴权 / 坏请求）——所有 provider 异常归一
- 消息族：UserPromptMessage / AssistantPromptMessage（含 tool_calls）/ SystemPromptMessage / ToolPromptMessage / PromptMessageTool；多模态 `Text/ImagePromptMessageContent`（data 支持 URL/base64）
- 结果族：LLMResult / LLMResultChunk / LLMResultChunkDelta / LLMUsage / TextEmbeddingResult / EmbeddingUsage / RerankResult / RerankDocument
- 参数与能力上下文（temperature/top_p/max tokens/context window……）全部来自 provider/model YAML，能力过滤由 schema 驱动
- `graphon.model_runtime.entities.llm_entities.LLMStructuredOutput`：结构化输出是一等契约（对应 Neurova 的六类能力检测，需对齐能力口径）

### 2.6 RAG 管线（`api/core/rag/`，58 文件）

- `retrieval_methods.py`：`RetrievalMethod` 四态——SEMANTIC_SEARCH / FULL_TEXT_SEARCH / HYBRID_SEARCH / KEYWORD_SEARCH，带 `is_support_semantic_search` / `is_support_fulltext_search` 能力助手（向量库类型决定支持集）
- `retrieval/router/`：**多库路由两策**——`multi_dataset_function_call_router.py`（LLM FunctionCall 选库）、`multi_dataset_react_route.py`（ReAct 选库）
- `rerank/`：`RerankRunnerFactory` 双模式——`RerankModelRunner`（rerank 模型）/ `WeightRerankRunner`（加权分融合）
- 管线分层：`extractor/`（PDF/PPT 等）→ `cleaner/` → `splitter/` → `index_processor/` → `docstore/`；`data_post_processor/` 后处理；`summary_index/` 摘要索引；`embedding/` 统一 embedding 层
- `nodes/knowledge_index/`：**工作流内建索引节点的**（流程中现场灌数据）
- 外部知识库：API 契约 + datasource（website_crawl / online_document / online_drive / local_file）多接入面
- 结构化输出：检索节点 output 带 chunk 编号与 score 明细，画布可 inspect —— 这是 Neurova 最值得对标的"检索可解释性"

### 2.7 可观测性与 LLMOps

- `api/core/ops/unified_trace/`：registry / hierarchy / trace_builder / provider / parent_context / entities —— OTel 统一 trace 包装
- `api/configs/observability/` + `api/extensions/otel/`：OTel 开关（`is_instrument_flag_enabled`）、parse 器、semconv
- 可插拔外部集成（docs `monitor/integrations/`）：**Langfuse / LangSmith / Opik / Arize Phoenix / Weave / 阿里云**
- `monitor/analysis.md`、`monitor/logs.md`；App 级 analytics
- **Annotation Reply**（`api/core/app/features/annotation_reply/`）：人工标注 → 命中即精准回复（annotation-reply 批处理 job + API：create/update/delete/configure-annotation-reply/get-job-status）；`feedback` API 收赞踩。这是"黄铁定标"的工程化：把修过的问答固化为系统记忆，绕过模型重抽。
- api/core/llm_generator/：LLM 生成器（自动生成标注/元数据/规则等）

### 2.8 工具与 MCP

- 工具五型：`builtin_tool` / `custom_tool` / `mcp_tool` / `plugin_tool` / **`workflow_as_tool`**（`api/core/tools/workflow_as_tool/{provider,tool}.py`——子流程是一等工具）
- `api/core/tools/tool_engine.py`：工具引擎（鉴权/权限/成本回传，callback_handler 挂工具成本）
- MCP 双面：`api/core/mcp/{client,server,auth,session}` + `api/controllers/mcp/` —— **Dify 平台自身可当作 MCP server 对外暴露**；MCP 工具也是工具类型的纯接入面

### 2.9 应用 API 面（服务 API + 控制台 API 双面）

- `api/controllers/service_api/`：chat-messages（send/stop/**get-next-suggested-questions**）、completion-messages、workflow-runs（run/stop/detail/logs/**stream-events**）、conversations（list/rename/delete/**variables/update-conversation-variable**）、files（upload/download）、audio（**TTS/ASR 面向 end-user**）、applications、feedback、annotations、end-users、**human-input（form/submit）**、knowledge-bases（CRUD + **test-retrieval**）、documents、**trigger/**（外部触发工作流）
- `api/controllers/web/`（控制台）与 `api/controllers/console/`：应用编排/插件管理/账单/RBAC
- 特点：**所有 Run 都是流式事件契约**（`httpx-sse`、`events` 总线），run 与 stream 分离（先 run 拿 id 再 stream 或查 logs）——Neurova 的 SSE 去重/历史回放可对齐这个"先 ID 后流"契约

---

## 3. 逐域比对：Dify vs Neurova

### 3.1 工作流引擎：NeurFlow vs Dify graphon

| 维度 | Dify (graphon + layers) | Neurova (collaboration/neurflow/) | 判定 |
|---|---|---|---|
| 引擎形态 | 外迁独立库 `graphon==0.7.0`，Dify 仅 8.9k 行 core | 自研一体：`execution_engine.py`(1330) + `dag.py`(312) + `variable_resolver.py`(411) + `builtin.py`(2367) | 引擎能力相当，但 Neurova 存在**双轨旧引擎** `execution_engine/workflow_engine.py`（CogArch 1.0 任务型，与 neurflow 并存）——Dify 的教训是"引擎单轨化、演化外迁" |
| DAG 语义 | graphon Graph + `GraphRuntimeState` + VariablePool；20 节点类型 | 真 DAG：Kahn 拓扑分层 + 层内 `asyncio.gather` 并发；29 内置节点 + `tool:*`/`skill:*`/`mcp:*` 外源节点；`source_handle=true/false/loop_body/loop_done` 编码分支与循环 | 同等（甚至节点种类更多：memory/emotion 等 Neurova 特有节点） |
| 运行持久化 | `WorkflowPersistenceLayer` → `WorkflowExecutionRepository` | `executions` 表 JSON（inputs/outputs/`node_results`（status/output/error/duration/tokens/cost）/variables）+ `execution_checkpoints` | Neurova 已有等价物，**且 node_results 规模比 Dify 的 NodeEvent 更细** |
| 断点/调试 | step-run 单节点、variable-inspect、history/logs 回放、mock | **已存在**：`DebugSession`（断点/step_mode in-over-out/mock 短路）+ `_NODE_MOCKS` + 端点 `/executions/{id}/breakpoint`、`/debug/resume`、`/variables`、`PUT /nodes/{id}/mock` | 基本对齐，差距是 UX（前端无单节点右键面板）与 `execute_debug` 自述"最小占位" |
| 版本 | version-control（草稿/发布/回滚） | `workflow_versions` 内容指纹快照（保留 20 版）+ `rollback_workflow`（回滚入史 undo-friendly） | **Neurova 反超**，无文档短板 |
| HITL | `HumanInputSurface`(SERVICE_API/CONSOLE/OPENAPI) 按表面裁剪接收方；`SuspendLayer` 监听 `GraphRunPausedEvent` 落库 resume；表单 FormInput/SelectInput | `human_input` 节点 + `approval` 节点 + approvals 端点 + `execution_checkpoints` 暂停续跑 | 机制在，缺"按调用面裁剪接收方"的安全模型（Dify 的 surface 枚举值得抄） |
| 触发器 | schedule/webhook/plugin trigger + `trigger/debug` event bus | `triggers.py` + `webhook_ingress.py` + scheduler（cron 星期语义已修）+ `webhook_deliveries` 投递记录 | 齐平 |
| 执行流 | **run/stream 分离**：run 拿 id → stream-events（SSE）/logs 查询；`execution_coordinator` + AppQueueManager | `execute` 端点**同步阻塞**（无后台任务队列、无 SSE 流式执行事件）；`_instances` 内存态 | **最大落差**：Dify 的"先 ID 后流 + 流式事件契约"是画布体验与前端联动的关键 |
| 复用 | `workflow_as_tool`：子流程是一等工具类型 | `subflow` 节点可引用子流程，但无"工作流=工具"注册进 agent 工具面 | 差距小，可补注册面 |
| 节点缺口 | 20 类 | transform 为占位（直接返回 `"transform: {expression}"` 字符串）；无 code 节点执行环境 | `transform` 补安全执行（Neurova 已有 `sandbox/exec_sandbox.py` 可直接拿来） |

**结论：工作流不是"缺功能"而是"缺流式执行契约 + 引擎单轨化"。** 断点、mock、checkpoint、版本回滚、HITL 都在——这是本报告最重要的发现，决定了 P0 清单里没有"重写画布"。

### 3.2 RAG：三档落差（本报告最尖锐的对比点）

| 层 | Dify | Neurova | 落差 |
|---|---|---|---|
| 摄取 | extractor→cleaner→**splitter 分块**→index_processor→docstore；`knowledge_index` 节点现场灌数据 | `attachment_parser.extract_attachment_text` 抽文本后**整篇存 JSON 不分块**；导入可选 LLM 图谱抽取 | **无分块管线**（Dify 的 splitter 是基础件，RAG 质量的地基） |
| 索引 | 多向量库（weaviate/qdrant/pgvector/seekdb/oceanbase） | `KnowledgeVectorIndex`=每用户一个 JSON 文件 + ONNX bge-small-zh-v1.5 + **暴力余弦**；KB 主检索是 TF-IDF 分片惰性重建；`UnifiedVectorStore`（tfidf/faiss/fastembed/onnx）在记忆域 | 数据规模小（个人助手）时暴力余弦可接受，但 "60k+ 条目即失效"；**至少应把 faiss backend 从记忆域复用到知识域** |
| 检索策略 | `RetrievalMethod` 4 态（semantic/full_text/hybrid/keyword）+ 能力助手（按向量库类型启用）；**多库路由独立**（FC/ReAct 选库） | `/semantic_search_api/hybrid` = BM25+vector+RRF 融合，但 `fts` 权重**恒 0 占位**（代码注释自认）；无多库路由 | 混合检索有架子，**fts 0 占位 + 无路由**是补课点 |
| 重排 | `RerankRunnerFactory` 双模：RerankModelRunner / WeightRerankRunner | **无任何 rerank 实现**（requirements.txt 无 rerank 依赖；仅 MoE router 的 `_layer2_tfidf_rerank` 内部重排） | 新增一个 `rerank/` 模块（cohere/bge-reranker 模型或加权融合），给 hybrid 出口 |
| 可解释性 | 节点 output 带 chunk 编号/score 明细，画布 inspect | `NodeExecutionResult` 有 output/error/duration/tokens/cost，但 knowledge 节点输出无 chunk 级溯源 | 中低优先级，但"检索了哪些块"是用户体验必答题 |

**结论：Dify 的 RAG 是"管线"，Neurova 的 RAG 是"单点查询"。** 优先级上，**分块（chunking）+ 混合检索恢复 + 重排**三件套是净增量（个人体量不需要塞向量库微服务；把记忆域的 faiss backend 引入知识域即可）。

### 3.3 模型管理：方向一致，缺"统一模型类型契约"

| 维度 | Dify | Neurova | 判定 |
|---|---|---|---|
| provider 抽象 | provider 插件化，`validate_provider_credentials`（`CredentialsValidateFailedError`）+ `validate_credentials` + **`_invoke_error_mapping` 五类标准化**（连接/不可用/限频/鉴权/坏请求） | `providers/base.py BaseProvider(ABC)` + 8 个 provider 类 + `secret_store`(AES-GCM) + `_RETRYABLE` 重试 + `CircuitBreaker` 熔断；`capability_cache/multimodal_prober/rate_limiter` | 能力近，**缺错误分类的统一规范**（Dify 的错误映射可作"错误契约"参考，便于前端给用户可行动提示） |
| 模型 schema | 6 型：LLM/Embedding/Rerank/ASR/TTS/Moderation，参数与上下文窗口在 YAML schema；`LLMStructuredOutput` 结构化输出一等契约 | `capability_detector.py` 六类能力标记（text/reasoning/vision/video/image_gen/video_gen，兼容 audio/tts/stt/tool_use）+ `MODEL_PRESETS` 60+ 条（含上下文/输出上限兜底）+ `model_limits.py` 手工表；能力检测=持久化元数据→目录→名称启发式 | 内存式能力目录 vs 声明式 schema；**建议把能力/上限并进 provider 配置元数据的声明式字段**，启发式只做兜底 |
| 内置范围 | 数百 provider（市场+内置） | 后端种子仅 5（OpenRouter/OpenCode/Kilo Code/GitHub Models/商汤）；前端 ModelPage 30+ 卡片是展示层 | 差距是**生态供给**，不是架构；对个人项目，把"provider schema 元数据化+运行时探测"盘活即可 |
| 负载均衡/故障转移 | 弱（每 app 绑定单模型） | **强项**：5 种 LoadBalancingStrategy + auto_failover + merge_discovered_models | Neurova 反超 |
| token 计量 | LLMUsage 全链路（chunk delta 累计） | `usage: {} # TODO`（LLM 节点 token 计量未接入管线；前端 Token 恒 0 曾三层根因修复，已入账到调用层） | 计量已在下沉层修复，工作流节点级 usage 待接 |

### 3.4 插件/技能生态：骨架 vs 生态

| 维度 | Dify | Neurova | 判定 |
|---|---|---|---|
| 市场 | Marketplace 发布流水线 + 签名验证 + 隐私声明 + 自动 PR | 多源（GitHub/ClawHub/LobeHub/ModelScope）+ 联邦注册 + 投稿审核（提交-审核三连）+ admin CRUD | 生态供给差距：`market_registry._MARKET_EXECUTORS` **真实执行体仅 web-search 一个**，其余为 SKILL.md 指令壳或 `executable=False` 可见不可调 |
| manifest | **声明式权限**：`resource.permission` 六类（tool/model{llm,embedding,rerank,tts,asr,moderation}/node/endpoint/app/storage 容量）+ `resource.memory` + `privacy`；组合限制 | 技能 manifest（name/version/description/author/tags/dependencies/parameters/outputs/requirements）**无权限字段**；权限治理在 `tool_executor._governance_preflight`（DENY/SANDBOX/ASK + fail-closed + 审批单）+ `security/constitution.py` | **这是最有价值的借鉴点**：Neurova 治理管"调用时"，Dify 声明管"安装时"。把 installed skill 的允许能力（工具白名单/网络/文件/容量）声明进 manifest，安装门直接用 |
| 沙箱 | sandbox 容器（code 节点）+ plugin-daemon 子进程（模型/工具隔离） | `sandbox/exec_sandbox.py`：Process/Bubblewrap/Seatbelt/AppContainer/Docker 五种 | 沙箱种类比 Dify 还多；**缺安全壳的"技能"维度**（技能默认在 agent 进程内执行指令） |
| MCP | Dify 是 MCP **客户端+服务端**（`core/mcp/{client,server,auth,session}` + `controllers/mcp`） | `tool_layers/mcp_client.py`（stdio/sse/streamable_http + ServerResilience 重连）+ MCP 工具接入 | Neurova 只有客户端；**服务端面**（把工作流/工具暴露成 MCP）可直接借鉴 |
| 反向调用 | 插件→主应用（model/tool/node）+ 插件 endpoint 注册给外部 | `plugin_api_registry.py`（插件 API 注册） | 有雏形，缺"外部 token 调插件 endpoint"的服务面 |

### 3.5 可观测性：自研 JSON trace 是好事，缺"标准界面 + 评估"

| 维度 | Dify | Neurova | 判定 |
|---|---|---|---|
| trace | OTel 标准 + 每节点 span + 自动插桩上下文（`extensions/otel/parser.py` 四类 parser + semconv） | `core/trace_recorder.py` `TrajectoryRecorder`（start_trace/start_span/end_span、record_llm_call/tool_call、JSON save/load/**replay**、user_id 隔离）——自研轻量、**无 OTel** | 自研 span 模型已够用，缺两件事：① OTel bridge（改造成本低：span 已结构化）② **节点级 span 关联**（neurflow node_results 已有 duration/tokens/cost，事件发到 trace 即可） |
| 外部集成 | Langfuse/LangSmith/Opik/Arize/Weave/阿里云 6 家 | 无 | 挑选 **Langfuse** 一家接 expo（本地/自托管避数据外泄） |
| 监控 | `monitor/analysis` + `monitor/logs` | Prometheus 埋点 + `ExecutionMonitor`（metric/alert/trace + EventBus）+ `/monitor` 真值（psutil+滚动历史，require_admin，已修 stub） | 机制齐备 |
| 评估 | （marginal；LLMOps 主打标注+回放） | 无 evaluation 子系统；仅 `benchmark.py`（Agent 基准：suites/runs/results/compare_agents） | 用 benchmark 跑道孵化"工作流评估"（输入样例集 + 断言），**不要**上 Dify 式企业评测平台 |

### 3.6 多租户/账号/计费：定位不同，保持克制

Dify 是 SaaS（workspace/RBAC/billing/套餐/企业 SSO），Neurova 是"本地桌面 + 单机 Web"。**这一域不抄**：
- Neurova 已有正确的用户级隔离（neurflow executions.user_id、KB 分片 public/user:<uid>/shared、provider scope 目录、StoreConnection.user_id、`resource_quota_manager` 配额门——max_agents/max_llm_calls_per_day/max_storage）；
- 唯一可借鉴：**配额门的"超出限频+按用户组"语义**（已具备），以及把工作流节点 `usage: {}` 的 token 计量接上配额（现在是"计量未接、配额靠天"）。

---

## 4. 可落地清单（按净增量排序）

### P0（1~4 周级，独立可交付）

| # | 事项 | 抄 Dify 的什么 | 落点（Neurova 文件） | 验收标准 |
|---|---|---|---|---|
| **P0-1** | **工作流执行流式化**（run/stream 分离） | `execution_coordinator` + AppQueueManager：run 返回 id → `/executions/{id}/events` SSE 推送节点级事件（GraphRunEvent 骨架）→ 前端画布实时点亮节点 | `neurflow/execution_engine.py`（`_instances` 改持久化协程句柄）、`neurflow_api.py`（新增 event stream）、`NeurUI/src/workflow/`（SSE 接收） | 长工作流执行中刷新页面仍可查进度；新增测试：执行中订阅事件收到全部节点完成事件 |
| **P0-2** | **RAG 分块管线** | Dify splitter 按段落/递归/固定窗口嵌套分块 | 新增 `knowledge/splitter.py`；`knowledge.py` import 流程接入；`KnowledgeRepository` 条目=分块集合 | 导入 10 页 PDF 产出 >50 块且检索命中定位到块（含出处页） |
| **P0-3** | **混合检索复活 + rerank 模块** | `RetrievalMethod` 四态 + `RerankRunnerFactory` 双模（模型重排/加权融合，无模型时退化加权） | `knowledge/search.py`（替代 `semantic_search_api` 的 fts=0 占位）、新增 `knowledge/rerank/`；接入 hybrid 出口 | 加依赖测试：trec 式小样本上 hybrid+rerank 胜过单路；fts 权重不再恒 0 |
| **P0-4** | **技能 manifest 声明式权限** | `resource.permission` 六类模型 + `resource.memory/storage` 配额 + `privacy` | `skills/models.py` `SkillManifest` 增 `permissions` 字段；`skill_install_gate.py` 安装时校验；`tool_executor._governance_preflight` 以声明为准 | 安装声明"无网络"的技能后，调用搜索工具被拒（fail-closed 有依据而非默认放行） |
| **P0-5** | **OTel 兼容层** | `unified_trace` + 每节点 OTel span + `parser` 按节点类型 | `core/trace_recorder.py` 加 OTel bridge（span→context），`neurflow` 节点事件挂 span；`api/app.py` 暴露 `status` 即可 | `otel` 依赖可选装；装后一个工作流 run 在 Langfuse 可见 1 root + N 节点 span（无需改业务代码） |

### P1（1~2 月级）

| # | 事项 | 要点 |
|---|---|---|
| P1-1 | 单节点 step-run 前端 + variable inspect 面板 | 后端 `DebugSession` 已支持；补 `StepRunRequest(node_id)` 端点 + 画布右键面板；复用 `/executions/{id}/variables` |
| P1-2 | HITL surface 安全模型 | 抄 `HumanInputSurface`（SERVICE_API/CONSOLE/OPENAPI）+ 接收方裁剪；approvals 端点加 surface 参数 |
| P1-3 | workflow_as_tool | `subflow` 节点升格：把已发布工作流注册为 agent 工具（`builtin_tools.py` 加 `workflow_*` schema + tool_executor 接线）；**天然自带输入校验（DAG 定义）** |
| P1-4 | 多库路由 | 参考 `multi_dataset_function_call_router`：多知识库时用 LLM FunctionCall 先选库再检索；直连已有 `llm/multi_model_client` |
| P1-5 | MCP server 面 | `tool_layers/` 新增 server 端：把 `neurflow` 工作流/`skill:*` 暴露为 MCP tools（`mcp/server/` 参考 Dify `core/mcp/server`） |
| P1-6 | 工作流节点 token 计量接配额 | LLM 节点 `usage` 真值 → `resource_quota_manager` 记账；Dify 的 LLMUsage chunk delta 是现成参照 |
| P1-7 | 双轨引擎收敛 | 以 `collaboration/neurflow/` 为唯一引擎，`execution_engine/workflow_engine.py` 冻结+迁移适配器；（Dify 抽 graphon 的第一课是"单轨才敢外迁"） |

### P2（长线，按需）

- 标注闭环（annotation reply）：人工修正的问答固化为"精准回复"命中表，配 `feedback` 赞踩→重训练化集——**在记忆系统之上最省事**。
- trigger 统一契约：webhook/schedule/plugin 三触发统一 `trigger` 面 + 触发投递重试（`webhook_deliveries` 已有表）。
- snippet 片段复用 + goto-anything（Cmd+K 命令面板）——UX 增益，工程价值一般。
- 检索溯源 UI：chunk 编号 + score + 原文预览（Dify inspect 的交互）。

---

## 5. 反模式（从 Dify 学，但不要学）

| Dify 的实践 | 为什么不抄 |
|---|---|
| plugin-daemon 子进程 + 签名市场 + 多语言发布流水线 | Neurova 单机个人体量，进程级插件隔离成本 >> 收益；**抄 manifest/权限声明，不抄运行时隔离**（沙箱已在 `sandbox/exec_sandbox.py`） |
| Celery + Redis + Postgres + 多向量库（weaviate/qdrant/pgvector/seekdb/oceanbase 并存） | 基建复杂度只为 SaaS 多租户规模化服务；Neurova SQLite+WAL+事件循环并发在单机体量下是正确解。向量库用 faiss backend（已存在）而非新微服务 |
| 20 节点全谱 + trigger/debug 事件总线 | Neurova 29 节点已超卖；缺口是流式契约与质量层（RAG），不是节点数 |
| workspace/RBAC/billing/企业版 | 定位是个人助手+桌面版；用户级隔离 + 配额门已够，别为抄而抄 |
| Next.js 前端与 18 locale | Vue 3 + 11 locale 是现状优势，无迁移理由 |
| OTel 全家桶强依赖 | Dify 把 OTel 做成 opt-in 配置；Neurova 应做成可选依赖（bridge 设计已按此）——避免"LogDir 双层"式反模式 |

---

## 6. 结论（可执行的一句话总结）

> **Neurova 的差距不在"功能缺失"，而在三个系统级契约**：① 执行流式事件（run/stream 分离 + SSE 节点事件）② RAG 质量层（分块→混合→重排，当前 fts 恒 0 + 无 rerank）③ 观察/权限的声明化（节点级 trace span + 技能 manifest 权限）。Dify 值得学的不是它的规模与节点库，而是它 **把引擎外迁（graphon）、把横切做成 Layer、把权限放进 manifest、把模型做成 6 型统一契约** 这四个"架构姿势"。按 §4 的 P0 五件套落地后，Neurova 在"个人智能体流水线"定位上将补足以与 Dify 工程深度对话的最后一层。
