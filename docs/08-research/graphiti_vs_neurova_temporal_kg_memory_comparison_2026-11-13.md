# Graphiti vs Neurova：时序知识图谱记忆对照测评（2026-11-13）

> 对照对象：[getzep/graphiti](https://github.com/getzep/graphiti)（Zep 开源时序知识图谱记忆框架，Apache-2.0，32.8k stars，v0.31.2）
> 被对照方：Neurova（本体世界模型 + 治理型事实库 + 记忆分层体系）
> 性质：只读研究测评，**不含任何代码改动**；改进候选见 §7，全部待点单。

---

## 0. 结论先行

**总分：Neurova 7.7 vs Graphiti 7.4（满分 10，九维加权）。**

| 视角 | Neurova | Graphiti | 谁强 |
|------|---------|----------|------|
| **记忆框架核心域**（数据模型/写入演化/检索/性能证据，权重 48%） | **7.1** | **8.5** | Graphiti |
| **平台治理与生态域**（推理/存储/集成/安全/工程，权重 52%） | **8.3** | **6.4** | Neurova |
| 加权总分 | **7.7** | **7.4** | Neurova（微弱） |

一句话：**Graphiti 赢在「从对话流自动生长时序知识图谱」这一条核心闭环——LLM 抽取、实体消歧、自动边失效、混合检索配方化，且有论文级实证（LongMemEval +18.5%、延迟 -90%）；Neurova 赢在治理、推理与产品化——双时态查询语义比 Graphiti 更完整、Datalog/溯因/模拟/决策台账是 Graphiti 完全没有的层、多租户隔离与写入审批咽喉远强于 Graphiti 的 group_id 命名空间。**

最大的差距点（也是最大的启发点）：Neurova 的本体/事实库是「有人喂才长」的治理型系统，缺一条 **episode → 实体关系图自动蒸馏管线**；Graphiti 的记忆图是「自己会长」但几乎裸奔（无认证、无审批、无租户隔离）。两者恰好互补。

---

## 1. 测评方法

### 1.1 维度与权重

对照领域为「Agent 记忆 / 时序知识图谱」，故核心记忆能力合计占 40%+，工程可用性与生态占其余：

| # | 维度 | 权重 | 界定 |
|---|------|------|------|
| A | 记忆与知识数据模型 | 12% | 结构完备性、时间语义、provenance、版本化 |
| B | 写入与演化管线 | 14% | 抽取、增量更新、去重消歧、失效、冲突、社区归纳 |
| C | 检索能力 | 14% | 混合检索、rerank、可定制性、默认可用性 |
| D | 推理与分析能力 | 10% | 规则推理、溯因、模拟、决策支持、图分析 |
| E | 存储与部署 | 10% | 后端支持、嵌入式性、服务化、导出兼容 |
| F | Agent 集成与生态 | 12% | SDK/MCP/工具面/前端/框架集成 |
| G | 安全·多租户·治理 | 10% | 隔离、鉴权、审计、写入治理、注入防护 |
| H | 工程成熟度 | 10% | 测试、CI、文档、发版、稳定性记录 |
| I | 性能与成本证据 | 8% | 公开基准、延迟/成本数据、性能门禁 |

### 1.2 评分锚点

- **9–10**：领域标杆，有论文/基准级实证或经多场景锤炼；
- **7–8**：完备可用，实现与测试可核实；
- **5–6**：能力存在但有明显缺口，或默认关闭/需显式开启；
- **3–4**：仅有部分对应物，或依赖外部补齐、明确不可生产直用；
- **0–2**：缺失。

### 1.3 证据规则

只采信可核实来源：论文原文、仓库源码/文档、Issue 编号、本仓代码路径。Graphiti 侧来源以「URL / 文件路径」标注；Neurova 侧以仓库路径标注。未能核实的项显式声明，不推分。

---

## 2. Graphiti 概览（证据摘要）

### 2.1 定位与实证

- 定位「Build Real-Time Knowledge Graphs for AI Agents」：为运行在持续演化数据上的 agent 构建时序上下文图，事实带有效期、provenance 可溯、支持 Pydantic 自定义本体、增量更新无需全图重算。（README）
- Zep 论文（arXiv:2501.13956）：DMR 94.8% vs MemGPT 93.4%（gpt-4-turbo）；LongMemEval_s 上 gpt-4o 达 71.2% vs 全上下文 60.2%（**+18.5%**），延迟 2.58s vs 28.9s（**约 -90%**），平均上下文仅 1.6k tokens。论文亦自认 DMR 区分度弱、LongMemEval 个别类型（single-session-assistant -17.7%）退步。

### 2.2 数据模型（`graphiti_core/nodes.py`、`edges.py`）

- 三层子图：**EpisodicNode**（non-lossy 原始数据/provenance，source=json/text/message/fact_triple）→ **EntityNode**（name_embedding/summary/attributes）→ **CommunityNode**（label propagation 社区+摘要）；v0.29.0 增 SagaNode（跨 episode 运行摘要）。
- **EntityEdge** 携带 `fact`/`fact_embedding`/`episodes`（回指来源）/`valid_at`/`invalid_at`/`expired_at`/`reference_time`/`created_at`。
- **双时间线**：事件时间（valid_at/invalid_at）与事务时间（created_at/expired_at）分轴；相对时间（"next Thursday"）按 episode 参考点折算 ISO 8601。
- 已知缺口：节点属性**无时序版本化**（issue #1166）；invalid_at/expired_at 语义仅边级。

### 2.3 写入管线（论文 + `add_episode` 实现）

episode 摄入 → LLM 结构化抽取实体（含反思步，speaker 自动成实体）→ 实体消歧（embedding 召回+全文补候选+LLM 判重合并）→ 预定义 Cypher 写入（**不用 LLM 生成查询**，防注入）→ 事实抽取与边嵌入 → 边去重（限同一实体对内）→ **时间抽取+自动边失效**（LLM 对比语义相关旧边，矛盾则置旧边 `invalid_at`=新边 `valid_at`，事务时间新信息优先）→ 社区归纳（label propagation，增量按多数邻居归属）。
弱点：每 episode 多次 LLM 调用成本高；社区需**手动周期性 `build_communities()` 全量重建（先删后建）**；并发可靠性有欠账——跨 group 串图（#1795）、静默丢 episode（#1707）、label propagation 非收敛图死循环（#402）、边失效全图扫描误伤（#1728，v0.30.2 部分修复）。

### 2.4 检索

- 混合检索三路：cosine 语义 + BM25 全文 + BFS 图遍历（最近 episode 为种子 n-hop 扩展）。
- 可插拔 reranker：RRF / MMR / episode_mentions / node_distance / cross_encoder（OpenAI logprobs、Gemini、BGE 三实现）。
- **16 个官方 search recipes**（`search_config_recipes.py`：EDGE/NODE/COMMUNITY/COMBINED × 五种 reranker）；SearchConfig 支持 limit、reranker_min_score、group_ids、edge_types、valid_at/invalid_at 日期范围过滤（MCP `search_memory_facts`）。

### 2.5 存储与交付

- 图数据库驱动：Neo4j 5.26（推荐）、FalkorDB 1.1.2（MCP 默认，含嵌入式 falkordblite）、Amazon Neptune（全文走 OpenSearch Serverless）、Kuzu 0.11.2（**已 deprecated**）。Memgraph **不支持**。向量/全文落在图库自身索引；embedding 需外部模型（默认 OpenAI，可换任意 OpenAI 兼容端点）。
- 交付形态：pip 库 `graphiti-core`（3.10+）、FastAPI 参考服务（`server/`）、MCP server（15+ 工具）。**两者均官方声明无认证/无授权/无 prompt-injection 防护，不可直接上生产。**

### 2.6 生态与治理

- `group_id` 命名空间实现多图隔离，文档明确**它不是权限控制**；LangGraph 官方教程；LLM 适配 OpenAI/Azure/Anthropic/Gemini/Groq/Ollama/vLLM；v0.31.0 新增 LLMRuntime 按 prompt 类型路由模型。CI 含 Lint/UT/MyPy/Socket Firewall；月级发版。
- 安全面：参考服务无鉴权、无注入防护、PostHog 匿名遥测（可关）。生产路径=自建护栏或购买 Zep 商业服务。

---

## 3. Neurova 对应面事实清单

### 3.1 记忆体系

- 门面 `neurova/mem_core.py`（`class MemCore` :442）：写入 `save_conversation_memory` :1100 / `save_to_session` :1437，检索 `retrieve_memories` :964 / `moe_retrieve` :1007，反馈闭环 `apply_feedback_to_memories` :1244。
- 统一模型 `neurova/cognitive_layers/memory_layer/models.py` :312：memory_type（语义/情景/程序/模式/情感/工作/工作流经验）、lifecycle_stage（active→consolidated→archived→forgotten/crystallized）、origin 信任级（untrusted 检索降权 0.6）、temperature（0-100 贝叶斯遗忘，`temperature.py`）、importance、embedding、**三层隔离 agent_id/neuser_id/user_id + share_group_ids**。
- 管理器 `memory_layer/manager.py`（5300 行）：SQLite 持久化、`searchMemoriesFulltext` :688、请求作用域隔离 `set_request_scope` :1333、关联线索（association cues）。
- 睡眠整合 `memory_layer/sleep.py`：近等价合并（cosine≥0.98）、温度衰减、压缩归档、REM insight 生成；写回 `sleep_writeback.py` 由空闲（`core/idle_tracker.py`）与关机（`agent_shutdown.py`）双路触发——**这是 Graphiti 没有的「自主巩固」机制**。
- 待确认写入 `memory/pending_memory.py`（拒绝指纹去重+confirm 注入）。
- 缺口：记忆条目以「文本+向量+温度/生命周期」为主，**没有从对话自动蒸馏实体-关系图的 LLM 抽取管线**；记忆库无 fact 级 validity 字段。

### 3.2 本体/知识图谱（`neurova/knowledge/ontology/` 30+ 文件）

- 术语注册、SHACL shapes、**Datalog 前向链+分层否定+递归 CTE**（`rule_engine.py` :505/:841-848）、SPARQL 只读投影（W9，rdflib 惰性）、溯因（abduction）、函数引擎/注册表/求值、状态机注册、动作注册与运行时（前置条件/影响）、**克隆世界模拟推演**（simulation）、**决策台账/因果链/判例**（decision_ledger）、CQ 追溯探针（cq_matrix，状态自动翻转）、内容寻址不可变工件存储（artifact_store，C2）、只追加 change_log、derivation_ledger、semver、领域包、RDF 导入、九格式导出（Turtle/JSON-LD/OWL/PROV/SHACL/GraphML/GEXF/Cypher/CSV）、**标签传播社区图+global/drift 检索**（community_graph，v48）、质量/校验、pipeline（dry-run/diff/rollback）、未知关系审批（relation_candidates）。
- API：`neurova/api/endpoints/knowledge_ontology.py`（2036 行，约 75 个 `/ontology*` 路由），聚合于 `knowledge.py` :67/:108。
- MCP：`neurova/mcp_ontology_server.py`（ontology_query/validate/fact_submit/sparql/abduce/community_search/decision_*/simulate/act/state），挂载 `/v1/mcp`，**Bearer JWT fail-closed 双鉴权**。
- 前端：`NeurUI/src/pages/ontology-studio/`（九节工作台）+ `graph-workbench/`（3D 图浏览/力导向/性能预算）。
- 写入治理：唯一写咽喉 `knowledge/foundation/admission.py`（KnowledgeAdmissionGate.admit；Simulation 只写隔离副本）；schema 迁移注册表 `foundation_schema.py`（v48/v50）。
- 缺口：无图数据库原生存储/查询；本体登记面仅 admin REST，Agent 不可自主改登记（设计裁定）。

### 3.3 时间语义（`neurova/knowledge/foundation/knowledge_facts.py`）

- 事实四时间字段 :58-91：**valid_from / valid_until / recorded_at / retracted_at**，另有 supersedes_fact_id、status（active/superseded/retracted）。
- **双时态查询** `factsBitemporal` :1049-1094：`asOf` 裁有效时间、`knownAt` 裁事务时间（「撤销后回看不出现」）；单点校验 `parseBitemporalStamp` :436，非法时间显式 4xx。**比 Graphiti 的边级 invalid_at 语义更完整**（Graphiti 节点无版本化、无效语义仅边级）。
- 三时间戳源钟：source_created_at/source_modified_at（源自文档元数据，缺失不猜、不回拨 mtime，`backfillSourceClock` :980-1011）+ 入库时间；消费面含同源重入库、冲突「新者胜」建议、检索时间范围过滤+recency 打分（可配默认关）。
- 失效语义等价物：`memory_layer/temporal_knowledge_graph.py`（头注自述基于 arXiv:2501.13956）——TemporalFact.valid_from/valid_until、FactStatus ACTIVE/EXPIRED/CONFLICTED/SUPERSEDED、`expire` :93、`supersede` :98；现经 `/tkg/*` API 与 TKGRetrieverAdapter(priority 26) 接线，但权威时序读面是 knowledge_facts（`temporal_facts.py` 头注工单 012）。
- 缺口：记忆库侧无 fact 级 validity；矛盾消解停在「建议」层，未自动闭环。

### 3.4 检索架构

- 责任链 `agent/memory_retrieval_chain.py`：Unified(10)→MoE(20)→Knowledge(25)→TKG(26)→Graph(27)→Cache(30)→Fallback(40)，带质量评分与降级。
- 知识主路 `agent/knowledge_retriever_adapter.py`：**四路 RRF（tfidf/bm25/fts/向量）+ 采纳先验重排（rerankByAdoption）+ 检索脱靶登记**；`hybrid.py` 加权 RRF（RRF_K=60）+ 图谱条件第五路（chat 主路默认 on，权重 0.10）。
- FTS5 持久倒排（`fts_index.py`，jieba 可选预分词，已入主库）；向量 `vector_index.py`+`vector_ann.py`（hnswlib/faiss 可选，失败回退全量余弦）。
- Rerank 模块 `knowledge/rerank/`（LLM/local/model/weight 工厂）——**默认关闸**，开启才精排。
- 缺口：无跨库统一「向量+图+全文」单引擎；检索配方未设置项化，图路权重固定。

### 3.5 图存储与查询

- 权威图读面 `knowledge/foundation/graph_walk.py`：knowledge_subjects+knowledge_facts 上的 **SQLite 递归 CTE 多跳走查**（默认 2 跳、上限 4、环靠路径去重），已接 hybrid 第五路。
- 内存属性图 `cognitive_layers/knowledge_graph/manager.py`（BFS/最短路/merge_nodes/undo_merge）——读兼容层，非权威。
- 缺口：无 Neo4j/Cypher 查询引擎（Cypher 仅是导出格式，D11 裁定「SQLite 权威+导出投影，不做运行时换底」）。

### 3.6 工程化与安全

- 测试：`tests/unit/knowledge/` 141 文件（ontology 子目录 65）、`tests/unit/memory/` 108、`tests/unit/cognitive_layers/memory_layer/` 57；前端 `ontology-studio/__tests__`、`graph-workbench/__tests__`（含 Playwright perfBudget）；API 清单守卫、尺寸棘轮等自建守卫体系。
- 多租户/权限：知识面 `tenant_id`+`agent_id` 过滤（`factsBitemporal` :1056）+ 部门分类白名单（commit 4df40158b，服务端单点）；记忆面三层隔离+share_group；MCP JWT fail-closed；写入审批咽喉+审计三账（change_log/derivation_ledger/decision_ledger）。
- 缺口：记忆库表无 tenant_id/部门维度，与知识库模型不对齐；三套身份口径（session_owner_id / neuser_id+user_id / agent_id+tenant_id）无统一映射事实源。

### 3.7 Agent 集成

- 内置工具 `builtin_tools.py`：`memory_search` :60、`recall_history` :35、`voice_memory_search` :708；chat_pipeline 组装检索链自动注入上下文；知识命中回写采纳账（G07 注入账）；post_chat_pipeline 写回+睡眠巩固。
- 本体 MCP 工具经 `tool_executor.py` ToolExecutor.execute 单管道（治理/审批/审计/mcp_grants）。
- 缺口：**无一等图查询工具**（图走查仅被动注入或经 MCP 间接用）；记忆/知识/本体三面无统一「记忆层」agent 工具抽象。

---

## 4. 逐维对照与打分

| 维度 | 权重 | Graphiti | Neurova | 裁定理由（关键证据） |
|------|------|----------|---------|----------------------|
| A 数据模型 | 12% | **8.5** | **9.0** | Graphiti：三层节点+边级双时间线+episode 回指 provenance，但节点属性无版本化（#1166）。Neurova：四时间字段+asOf/knownAt 双时态查询语义完整（`knowledge_facts.py` :1049），三时间戳源钟不猜不回拨；失分在记忆库无 fact 级 validity、图无节点级属性版本化 |
| B 写入演化管线 | 14% | **8.5** | **6.0** | Graphiti 核心优势：episode→抽取→消歧→去重→自动边失效→社区归纳全自动闭环；扣分在成本高、社区先删后建、并发欠账（#1795/#1707/#402）。Neurova：写入治理极强（admission 咽喉/审批/dry-run/rollback/审计），但**自动抽取管线缺位**，事实库靠人工/规则喂入；睡眠整合是条目级不是图级 |
| C 检索能力 | 14% | **9.0** | **7.5** | Graphiti：向量+BM25+BFS 三路+5 类可插拔 reranker+16 recipes+SearchConfig 全可配。Neurova：四路 RRF+图第五路+采纳先验重排+rerank 工厂，但 rerank 默认关、图路权重固定 0.10、无检索配方层 |
| D 推理与分析 | 10% | **4.0** | **9.0** | Graphiti 仅社区摘要（GraphRAG 工艺），无规则推理。Neurova：Datalog 前向链+递归 CTE、SPARQL、溯因、状态机、动作运行时、克隆世界模拟、决策台账/判例、CQ 追溯、影响分析——Graphiti 完全没有的层 |
| E 存储与部署 | 10% | **7.5** | **7.0** | Graphiti：4 图库驱动+参考 REST+MCP，但强依赖外部图数据库与外部 embedding 服务，Kuzu 已弃用、跨后端行为不一致。Neurova：SQLite 权威零外部依赖、嵌入式即起、九格式导出兼容；但无原生图查询引擎、无横向扩展路径 |
| F Agent 集成与生态 | 12% | **8.0** | **8.5** | Graphiti：pip 库+MCP 15+ 工具+LangGraph 教程，对第三方 agent 友好，但参考服务不可生产。Neurova：MCP（JWT）+75 端点+内置工具+检索链自动注入+前端双工作台+经验闭环，端到端更深；但对外作为「可复用框架」的生态（第三方教程/插件）不可比 |
| G 安全·多租户·治理 | 10% | **4.0** | **9.0** | Graphiti：group_id 明确非权限控制、参考服务无鉴权无注入防护。Neurova：三层隔离+tenant+部门白名单+JWT fail-closed+审批咽喉+审计三账，悬殊优势 |
| H 工程成熟度 | 10% | **8.0** | **8.0** | Graphiti：32.8k stars、1060 commits、CI 四件套、月级发版、文档 v4+llms.txt；扣分在已知可靠性 bug 群。Neurova：测试纵深大（300+ 相关测试文件）+守卫纪律；扣分在预存红在册、无社区/发版面 |
| I 性能与成本证据 | 8% | **7.5** | **5.5** | Graphiti：论文级实证（+18.5%/-90%/1.6k tokens），但写入 LLM 成本高、个别类型退步。Neurova：有内部性能门（perfBudget、C3 预算门、ANN），**无任何对外基准成绩** |

### 4.1 汇总

| | A(12%) | B(14%) | C(14%) | D(10%) | E(10%) | F(12%) | G(10%) | H(10%) | I(8%) | **总分** |
|---|---|---|---|---|---|---|---|---|---|---|
| Graphiti | 8.5 | 8.5 | 9.0 | 4.0 | 7.5 | 8.0 | 4.0 | 8.0 | 7.5 | **7.4** |
| Neurova | 9.0 | 6.0 | 7.5 | 9.0 | 7.0 | 8.5 | 9.0 | 8.0 | 5.5 | **7.7** |

分域（按 §0）：记忆框架核心域（A/B/C/I）**Graphiti 8.5 vs Neurova 7.1**；平台治理与生态域（D/E/F/G/H）**Neurova 8.3 vs Graphiti 6.4**。

**测评效度声明**：本测评为架构与能力面的对照分析，非同环境跑分；Graphiti 侧性能数字引自其论文（自报），Neurova 侧无同口径基准，维度 I 的对比因此偏保守。若需同台跑分，见 §7 C7。

---

## 5. 对 Neurova 的启发

1. **「会自己长的记忆图」是被验证的产品方向**。Graphiti 用一条 episode→抽取→失效管线 + 一篇论文拿下 32.8k stars；Neurova 的事实库治理面更强，却缺这条自动化前段。治理不该是「不自动」的理由，而应是「自动得更可信」的资本——把 LLM 抽取产物当作 **untrusted origin** 走审批咽喉入库，即可兼得。
2. **双时间线是记忆系统的正确语义**，Neurova 的 asOf/knownAt 双时态查询在语义上已超过 Graphiti（边级 invalid_at、节点无版本化），应保持并显式守卫（现有 `test_bitemporal*` 已覆盖，可补「节点级版本化」演进位）。
3. **检索要「配方化」而不是「参数化」**。Graphiti 的 16 个 recipes + SearchConfig 把复杂检索变成了可命名、可测试、可文档化的资产；Neurova 的 RRF 权重/rerank 开关目前散落在适配器与 env 里，宜收敛成命名配方（默认配方+精排配方+图扩展配方），并设为设置项。
4. **provenance 要做到「条目可回指原文」**。Graphiti 的 episodic 层 non-lossy 设计使每个事实可回溯到原始消息；Neurova 的知识事实有 source_id/source 钟但记忆条目与对话轮次的回指不如它系统。
5. **基准即话语权**。Graphiti 的 LongMemEval/DMR 成绩是其生态号召力的核心；Neurova 缺同口径对外数字，任何「我们更强」的叙述目前都只是架构推断。
6. **反向启发（Graphiti 的教训）**：无鉴权参考服务、group_id 假租户、先删后建的社区重建、LLM 抽取幻觉需专项治理（v0.29.1 属性丢弃阈值）——这些恰恰都是 Neurova 已有纪律覆盖的面，说明 Neurova 的治理路线在工程侧是超前而非累赘。

---

## 6. 差距定位（一句话版）

- Graphiti 有而 Neurova 无：**episode→实体关系自动抽取管线、可插拔 reranker 配方族、图数据库多后端、论文级基准证据**。
- Neurova 有而 Graphiti 无：**双时态查询语义（asOf/knownAt）、规则推理/溯因/模拟/决策台账、多租户与部门隔离、写入审批与审计、睡眠巩固、前端工作台**。

---

## 7. 改进候选清单（全部待点单，未实施）

> 按 AGENTS.md 核心原则 8 给出影响面。编号沿用本仓惯例；P0 最高。

### C1（P0）episode→事实图自动蒸馏管线
- **动机**：§4 维度 B 最大差距。让 knowledge_facts 从「人工喂」变「对话流自动长」，同时用既有治理面守住质量。
- **建议落点**：`post_chat_pipeline.py` 后挂 `knowledge/digestion/`（新模块）：LLM 抽取 (subject, predicate, object, valid_from, confidence) 候选三元组 → hybrid 召回既有同主谓事实 + 向量近似 → LLM 判重/矛盾 → 以 `origin=untrusted` 走 `KnowledgeAdmissionGate.admit` → 落 knowledge_facts（自动带 agent_id/tenant_id）。
- **影响面**：`post_chat_pipeline.py`、`knowledge/foundation/admission.py`、`knowledge/foundation/knowledge_facts.py`、新增 digestion 模块与测试；不改权威读面。
- **代价/不可逆点**：每轮对话新增 1-2 次 LLM 调用（成本）；抽取质量差会污染事实库——靠 untrusted 降权 + 审批兜底，可回滚（change_log）。

### C2（P1）事实矛盾自动消解（temporal invalidation 闭环）
- **动机**：Graphiti 的核心卖点之一；Neurova 已有 supersedes/status 与「冲突建议不改判」，差一步自动建议→审批闭环。
- **建议落点**：digestion 管线判矛盾时生成 `supersede` 建议 → 走 `relation_candidates` 同款审批面 → 批准后置旧事实 status=superseded + supersedes_fact_id，新事实 valid_from 继承。
- **影响面**：knowledge_facts 状态机、审批 API（`knowledge_ontology.py`）、前端审批面板；纯增量。
- **代价**：无破坏性；不改既有判例语义。

### C3（P1）检索配方化 + rerank 默认档
- **动机**：维度 C 差距。把「四路 RRF+图第五路+采纳先验+可选精排」收敛为命名配方并设置项化。
- **建议落点**：`knowledge/search_recipes.py`（新）定义 default/balanced/precise/graph_expanded 四配方；`knowledge_retriever_adapter.py` 改读配方；SettingPage 加检索配方选择；i18n×11。
- **影响面**：knowledge 检索装配点、设置 API/前端、守卫测试（新配方默认值需与现网行为等价，避免隐性回归）。
- **代价**：中；需 A/B 自证检索质量不回退。

### C4（P1）agent 一等图查询工具 `graph_search`
- **动机**：§3.7 缺口——图走查只能被动注入，agent 无法主动查图。
- **建议落点**：`builtin_tools.py` 新增 `graph_search`（包 `GraphFactWalker` 多跳 + 可选 `community_search`），出参=事实链+来源+validity 窗口；登记 MCP 侧同名工具。
- **影响面**：builtin_tools、tool_executor 白名单、MCP 工具表、前端工具说明。
- **代价**：小；注意注入上下文的 token 预算（限跳数与条数）。

### C5（P2）社区图增量自动维护
- **动机**：Graphiti 社区先删后建是已知弱点；Neurova community_graph 有标签传播+摘要，但触发方式未自动化。
- **建议落点**：把 community 重建接进 `ontology/pipeline.py`（dry-run/diff/rollback），digestion 批次后增量触发，diff 超阈值才全量。
- **影响面**：ontology pipeline、community_graph、v48 表；可审计回滚。
- **代价**：中；需控制重建频率防抖。

### C6（P2）记忆库 fact 级时间语义
- **动机**：维度 A 扣分点——记忆条目只有 created/updated/accessed，无 validity。
- **建议落点**：memory_layer models 增可选 `effective_from/invalid_at` 字段（schema 迁移注册表），检索链按 asOf 过滤（复用 `temporal_facts` 语义）；缺省 NULL 行为不变。
- **影响面**：memory_layer schema+manager+检索链；老数据零迁移成本（NULL=永远有效）。
- **代价**：中；注意与温度衰减语义叠加时的排序口径。

### C7（P2）对外记忆基准（LongMemEval 式最小集）
- **动机**：维度 I 差距；建立可复跑的对外证据。
- **建议落点**：`tests/performance/memory_benchmark/`（新）：多轮对话注入→间隔追问→测检索命中/答案正确率/延迟/token 成本；先做「金集自证」，再考虑公开口径。
- **影响面**：新增性能测试目录（唯一测试根 tests/ 下）；不接 CI 门禁（只出报告）。
- **代价**：中高（需标注集）；可与 RSI 证据机器的评测基建复用。

### C8（P3，谨慎）图存储接口抽象预留多后端
- **动机**：维度 E 演进位。把 `graph_walk.py` 的递归 CTE 走查抽象成 GraphStore 接口，预留 Neo4j/Kuzu 适配位。
- **风险与保留**：违反教义第 6 条风险高（易造平行体系）；SQLite 权威是 D11 裁定。**仅建议做接口切面（读面抽象），不做第二套权威存储**；除非出现真实的多后端需求，否则不实施。

### 实施顺序建议

C1 → C2 → C4（一条「自动生长+可治理」主线，先让事实库活起来）→ C3（检索兑现增量价值）→ C5/C6/C7（夯实）→ C8（仅在有真实需求时再议）。

---

## 8. 证据索引

**Graphiti 侧**：README（github.com/getzep/graphiti）；`graphiti_core/nodes.py`、`edges.py`、`search/search_config_recipes.py`、`graphiti_core/driver/`；官方文档 v4（help.getzep.com：communities/graph-namespacing/searching/lang-graph-agent）；论文 arXiv:2501.13956；issues #402/#912/#871/#1166/#1272/#1707/#1728/#1795/#2012；releases v0.29.0-v0.31.2；HN 讨论（news.ycombinator.com/item?id=46511540）。

**Neurova 侧**：`neurova/mem_core.py`；`neurova/cognitive_layers/memory_layer/{models,manager,temperature,sleep,sleep_writeback,temporal_knowledge_graph}.py`；`neurova/knowledge/ontology/`（rule_engine/sparql_query/simulation/decision_ledger/cq_matrix/artifact_store/community_graph/pipeline 等）；`neurova/knowledge/foundation/{knowledge_facts,admission,graph_walk,temporal_facts,foundation_schema}.py`；`neurova/knowledge/{hybrid,fts_index,vector_index,vector_ann}.py`、`knowledge/rerank/`；`neurova/agent/{memory_retrieval_chain,knowledge_retriever_adapter,tkg_retriever_adapter,graph_retriever_adapter,retriever_adapters}.py`；`neurova/api/endpoints/{knowledge_ontology,knowledge_access_facade,memory_timeline_api,enhanced_memory_search_api}.py`；`neurova/mcp_ontology_server.py`；`neurova/builtin_tools.py`；`NeurUI/src/pages/ontology-studio/`、`graph-workbench/`；`docs/specs/2026-11-12-Ontology可运行世界模型补全设计.md`、`docs/specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md`、`docs/specs/2026-11-07-用户分组部门化与知识库分类隔离设计.md`；测试 `tests/unit/knowledge/`、`tests/unit/memory/`、`tests/unit/cognitive_layers/memory_layer/`。
