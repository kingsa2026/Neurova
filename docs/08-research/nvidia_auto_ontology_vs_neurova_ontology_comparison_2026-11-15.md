# NVIDIA/auto-ontology 与 Neurova 本体代码级对照研究（2026-11-15）

> 研究参考类文档（背景参照，不作本仓事实源）。对象：[NVIDIA/auto-ontology](https://github.com/NVIDIA/auto-ontology)
> 快照 `9fba324`（2026-11-14，Apache-2.0），克隆件在 `E:/项目/_external_repos/NVIDIA-auto-ontology`（只读）。
> 本仓侧事实以当日代码为准；引用均给路径:行号，便于复核。

---

## 0. 结论摘要

**两者不是同位竞品，是互补象限。**

- **auto-ontology**：自下而上——从企业数据库元数据（表/列/键/查询历史）**自动构建语义目录**，让代理「查数可靠」：术语、SQL 属性、语义外键、确定性 join 路径、answerability 预检、text-to-SQL 修复环。本体在这里是**数据之上的语境层**；几乎没有推理（无规则引擎/溯因/推演），治理靠「认证标志 + 审批式修订」。
- **Neurova**：自上而下——治理型可运行世界模型：术语/规则/形状/事实四层存储、admission 唯一写咽喉、前向链推理＋推导账本精确撤销、基线 diff/回滚、九格式标准导出、CQ 追溯探针、GB/T 48000.3 对齐、租户隔离。**缺的恰是对方最强的两面**：从数据 schema 自动长出词汇与映射的管线（`describeSchema()` 五驱动已实现但零生产调用），以及面向业务库的问数 grounding（无 NL2SQL）。

**最值得吸收的三件事（P1）**：

1. **接线 `describeSchema()`，建「schema 目录自动摄取」管线**——把已实现却零调用的 schema 自省能力变成 catalog 记录，作为本体候选与后续一切的数据入口。
2. **「LLM 建议 + 数据证实」的术语/关系候选器**——LLM 猜、数据验（值包含 + join 探针），不确定不落库；与本仓既有 `ontology_relation_candidates` 审批流、`/ontology/pipeline` dry-run 闸天然契合。
3. **answerability 预检 + NL2SQL grounding 蓝图**——便宜的「覆盖度预检」可独立先行；完整问数链路（确定性 join 路径 + judge + 修复 + 空结果探针 + 诚实拒答）作为大项拍板。

**工程面借鉴（P2/P3）**：MCP 工具面 curated 治理（87→7 + 描述当 prompt 写 + spec 漂移 CI）、`check_readiness` 复合就绪探针、查询历史回灌成可复用表达式、Ossie 标准互操作、编译并发工程件（有序提交队列/在飞限流/取消语义）、面向外部 harness 的 skills 打包。

**不建议照搬**：Postgres+pgvector 单体栈、前端网关信任头身份（`x-auto-ontology-user-id`）、无自身鉴权的 ingestion 服务、Better Auth 体系——与本仓身份单通道教义（`AGENTS.md` §3）和既有治理体系冲突，且对方自己也把 3001/3002 限定在私网。

---

## 1. 对象概况

| 项 | auto-ontology | 本仓（对照基线） |
|---|---|---|
| 定位 | 企业数据语义目录/本体自动构建 + 代理分析 grounding 库 | 治理型可运行本体世界模型（Agent 平台内） |
| 规模 | `auto_ontology/` 包 449 个 py、约 12.7 万行；另有 Next.js 前端、MCP server、Helm/Compose | `neurova/knowledge/ontology/` 34 个 py 约 7,900 行；周边 foundation/enterprise/api/mcp |
| 存储 | Postgres 17 + pgvector（catalog、ontology、embeddings 同库） | SQLite（`knowledge_facts.db`），全库 `tenant_id` 分区 |
| 服务形态 | 前端网关 3000 / 后端 3001 / 摄取服务 3002 / MCP 3003 四进程 | 单体 FastAPI（9527）＋ `/v1/mcp` 挂载（`neurova/api/app.py:1699`） |
| 数据源 | 10 连接器（Snowflake/Databricks/ClickHouse/Postgres/MySQL/SQLite/DuckDB/HeavyDB/Kyuubi…） | 企业源六类适配器（sql/erp_api/chat/http_pull/unity_catalog/snowflake/sap_odata，`neurova/knowledge/enterprise/registry.py:44`） |
| 活跃度 | 2026-11-14 仍在提交（研究当日） | — |
| 许可 | Apache-2.0，暂不接受外部贡献 | — |

架构总图见其 `docs/architecture.md`（每步标注「是否调模型/是否默认开/哪个设置控制」的表格化做法本身值得学）。

---

## 2. 数据模型对照

### 2.1 auto-ontology：物理目录层 + 语义层（同库两个世界）

基线迁移 `alembic/versions/c778a7d94c20_create_the_auto_ontology_schema.py`（单文件 squash，注释详尽）：

- **物理目录层**：`catalog_database → catalog_schema → catalog_table`（pk、`is_junction_table`）`→ catalog_column`（`data_type/sample_values/format/is_unique/is_nullable/ordinal_position/pii_processed`）。列上带**数据画像**（采样值、唯一率、格式）。
- **语义层**：
  - `term`（业务概念：name/description/synonyms/`name_certified`/`description_certified`）；
  - `column_attribute`（term 下的物理列映射，certified、`description_suggestion`）；
  - `sql_attribute`（**可复用 SQL 表达式**：expression、source=manual/sql/table/bridgeTable、certified）；
  - 关系四件套：`column__foreign_key`（物理外键）、`column__semantic_fk`（列→列属性，**语义外键**）、`column__join`、`column__union`、`table__join`；
  - `join_path_edge` **视图**（迁移文件 :69-86 内联，注释明言「Alembic 不管视图，丢了它 `find_join_path` 会静默失效」）——join 路径 BFS 的边表。
- **查询历史作为一等输入**：`sql_query`（md5 去重、join/union 计数、使用计数）↔ `sql_query__table/__column`；`custom_analysis`（人工保存的 SQL）。
- **治理**：`tag/rule/tag_target`（规则打标，编译后自动回放）、`zone/zone_target`（数据分区）、`semantic_compilation_history`（每次编译留痕）、`imported_id`（Ossie 互操作锚点）。

### 2.2 Neurova：术语/规则/形状/事实四层 + 账本族

- `ontology_terms`（`neurova/knowledge/ontology/term_registry.py:53`）：kind/label/parent/domain/range/cardinality/disjoint/inverse/symmetric/transitive/aliases/外部 IRI 结构化映射/多语言标签/module/namespace/version——**建模表达力远强于对方**（对方 term 无层次、无属性约束、无推理标记）。
- `ontology_rules`（Datalog，rule_engine.py:31）、`ontology_shapes`（SHACL 风格，shapes.py:32）、`knowledge_subjects/knowledge_facts`（confidence/双时态 valid_from/until/超替链，knowledge_facts.py:45-91）。
- 账本族：derivation_edges/rule_fires/decisions/change_log/baselines/artifacts（sha256 内容寻址）。
- **没有** catalog_table/catalog_column 这样的物理目录层；最接近的是人工 R2RML 风格 `enterprise_source_configs`（`connectors/../schema_mapping.py:66`）。

**对照结论**：对方「物理目录 + 语义层」的双层结构是 text-to-SQL grounding 的地基；本仓「词汇层 + 事实层」结构是推理与治理的地基。两者可叠：在本仓补一层轻量 catalog（物理表/列/键画像），词汇层不变。

---

## 3. 构建链路对照

### 3.1 auto-ontology：两阶段「机器起草 + 人工认证」

入口 `semantic/compile.py:36`（`run_semantic_compilation`），全流程表见其 architecture.md「Generate an ontology」节：

1. **Catalog ingest**（`ingestion_service/ingest.py:82`）：连接器抽表/列/键/视图/查询历史 → PII 检测（规则优先 LLM 兜底，默认关）→ embedding 入 pgvector。
2. **Per-table pass**（`semantic/visit_enter.py:832`，3 表并行、LLM 在飞上限 6）：
   - SQL 采样 1000 行；`distinct_ratio ≥ 0.95` 判唯一（`_UNIQUE_RATIO`，visit_enter.py:66）；低基数列 DISTINCT 探针（设置可关）；
   - 规则推断日期格式（`date_format.py`）；
   - LLM 找 FK 候选 + 判 junction 表（`fk_suggester.py`，与声明键合并）；
   - LLM 写列描述、命名 term（含同义词/显示名，`term_extractor.py`）。
3. **Cross-table pass**（`compile.py:94-132` 逐段日志）：
   - **term families**（`term_families.py`）：同构表副本（`OLD_ROOMS/NEW_ROOMS` 前缀族）用「镜像边 + 孪生 Jaccard≥0.8 + 证据≥3 + 同前缀传递扩张」聚族，历史表 `*_HIST` 特判；
   - **semantic FK 解析**（`semantic_fk.py:130`）：声明键优先 → 向量检索 + LLM 选（`_resolve_via_vdb`）→ **值包含确认**（distinct 值比对，`containment`）→ **join 探针确认**（`SELECT 1 ... LIMIT 1`，双側 cast text 重试，`_join_probe_sql:771`）——LLM 的猜测必须被数据证实才落库，且永不跨 family 指向副本；
   - 每组备选链接选默认 join（LLM + 确定性兜底，每次编译重选）；
   - 未匹配 FK 列挂表 term 或新建 junction term（`unmatched_fks.py`）；
   - **查询历史 → sql_attribute 建议**（`sql_attribute_suggester.py`，每 term 取使用计数 top10 交 LLM 判定）；
   - bridge table 的 sql_attribute（reranker 定归属）；列属性一句话描述。
4. **认证闭环**：人工在 UI/API 修订 → 保存即重嵌入 → **下次编译只处理「尚无 term 的表」**（`fetch_all_tables_without_term`，pipeline.py:147）——人工成果永不被机器覆盖；唯一例外是 join 默认选择每轮重算。

**工程件**（本仓做自动管线时同款需要）：`_OrderedCommitQueue`（pipeline.py:33，LLM 并行抽取 + 按规范表序提交，碰撞名归属确定）、`limit_inflight`（compile.py:33）、取消语义（取消即跳队、等在飞完成、日志明说）、采样熔断器（连续 3 次失败弃采样）、trigram GIN 索引（无锚 `ILIKE` 全局搜索）。

### 3.2 Neurova：三条写入链，独缺「schema → 本体」

（本仓盘点证据，路径均为相对 `neurova/`）

1. **文档 → LLM 抽取 → 三元组**（全自动，输入是知识文本）：知识导入 → `_try_extract_to_graph`（`api/endpoints/knowledge_common.py:454`）→ `graph_bridge.extract_knowledge_to_graph`（`knowledge/graph_bridge.py:31`，候选类型取自 `ontology_terms` 注册表）→ admission 咽喉落事实；未登记关系落候选审批（`ontology/relation_candidates.py`）。
2. **企业源 → 行 → 事实**（映射人工配）：`registry.buildAdapter`（registry.py:44）→ 水位增量 `fetchBatch` → `schema_mapping.applyMapping`（schema_mapping.py:162）→ admission。**编译期强制 predicate/object 必须是已登记术语**（schema_mapping.py:109）——词汇不随源自动生长。
3. **管理面人工构建**：`/ontology/terms|rules|shapes|...`＋`/ontology/pipeline/run`（整批原子 + 基线快照 + diff/回滚，`ontology/pipeline.py`）。

**关键断点（本仓唯一 deadliest 的「有而无用」）**：SQL 连接器已实现 `describeSchema()`（`knowledge/enterprise/connectors_sql.py:203`，五驱动 information_schema/sqlite_master 目录查询，统一返回 `(table_name, column_name, data_type)`；lakehouse/file/chat/fake 适配器同签名为协议契约 `protocols.py:62`），但**全仓无任何生产调用方**（grep 仅命中测试与适配器自身；`registry.py`/`knowledge_enterprise.py` 零引用）。数据库 schema → 实体/关系/语义目录的自动抽取管线**不存在**。

### 3.3 对照结论

对方把「从数据长出语义」做成了全自动化流水线 + 人工认证闭环；本仓把「人/知识进来的语义」做成了强治理闭环。**把对方第 1-3 步的自动化嫁接到本仓第 2 条链与候选审批面上，是最高杠杆的改进方向**：`describeSchema()` 是现成的第一块积木。

---

## 4. 消费链路对照

### 4.1 auto-ontology：为「答对数」服务的一条固定管线

LangGraph 固定路由（`retrieval/text_to_sql/text_to_sql_graph.py`，流程表见 architecture.md）：

```
follow-up 改写 → 意图分类(calculation/information/prediction) → 实体抽取
→ 向量检索候选(列属性/SQL属性/自定义分析/主题 term)+LLM 相关性过滤
→ [元数据问题 → information agent(只读目录工具)]
→ 确定性 join 路径(semantic FK 最短路, dal/attributes.py:1225 find_join_path，无 LLM)
→ 推理模型写 SQL+解释 → 静态检查+LLM judge → 修复(≤7) → 执行
→ 空结果探针(LIKE 放宽/近失值修复) → 答案+SQL+行数(+图表)
```

要点：

- **join 不靠 LLM**：`join_path_edge` 视图 + BFS 最短路，答案时零模型调用——可靠性来自「关系已认证 + 路径确定性」。
- **答案必须可核**：返回 SQL 与步骤；拒答时附「过了静态检查未过意图 judge」的最后 SQL（不执行）——诚实形态。
- **answerability 预检**（`retrieval/entity_coverage/`）：抽问题实体 → 向量检索 → 距离阈值内命中占比 = coverage，不写 SQL 的廉价预检，暴露为 MCP `check_answerable`；代理据此决定「先问用户澄清还是直接答」。README 示例：问广告 ROI，coverage 0.5、无 term 覆盖「ad spend」→ 代理反问澄清而非编造。
- **MCP 面治理**（`mcp/auto_ontology_mcp/tools.py`）：87 个 OpenAPI 操作只暴露 7 个 curated 工具；catch-all exclude 保证新端点默认不可见；**工具描述按 prompt 语言手写**（"Use this first to learn what a business word actually means"）；`missing_from_spec()`（tools.py:169）让 CI 在 spec 漂移时启动失败；其 AGENTS.md 明确「handshake 工具列表是唯一事实源，skill 文档不复制工具表」。
- **check_readiness**（`mcp/auto_ontology_mcp/readiness.py`）：「已摄取 + 有活连接 + 已编译」三事实合一——注释点名失败是静默的：空目录也能完美回答 search_terms，直到 ask_question 烧几分钟才死。一个廉价调用把死胡同变成事实。
- **skills 打包**：`skills/` 三个可分发 agent skill（setup/query/management），SKILL.md + references + evals + BENCHMARK.md + 签名，同步到 nvidia/skills 公共目录；query skill 教代理「readiness → search_terms → check_answerable → ask_question → 校验」的顺序。

### 4.2 Neurova：检索注入 + MCP + Studio 三路消费（已接线）

- **Agent 对话**：`agent/chat_pipeline.py:323-370` 挂 TemporalFactReader（priority 26，只取当前有效事实）与 GraphFactWalker（priority 27，多跳走查，env 闸可关）；知识四路 RRF（priority 25）。
- **MCP**：`mcp_ontology_server.py` 16 工具（query/validate/fact_submit/derive/sparql/abduce/community_search/decision_*/simulate/act/state/compute），双鉴权 fail-closed。
- **REST**：`api/endpoints/knowledge_ontology.py` 76 条 `@router` 路由 + 四动词门面 `/v1/knowledge/access/*` + `/ontology/cq-matrix` 读数面。
- **前端**：Ontology Studio 八分区（`NeurUI/src/pages/ontology-studio/OntologyStudioPage.vue:75`）＋ GraphWorkbench/EnterpriseSources/FactExplorer/KnowledgeEval 等。
- **缺口**：内置工具 91 个中知识本体相关 0（五步评估自证）；无面向业务库的问数入口（`connectors_sql.py` 的只读 query 模板路由未接任何自然语言面）。

### 4.3 对照结论

本仓消费面「面广而深」（检索/推理/治理/可视化齐全），对方消费面「窄而锐」（一个问数场景打穿）。**answerability 预检与「工具描述即 prompt」的 MCP 治理是本仓当天就能借鉴的两件小事；NL2SQL 是需要拍板的大事。**

---

## 5. 治理对照

| 维度 | auto-ontology | Neurova | 判 |
|---|---|---|---|
| 写入治理 | 修订走 UI/API；编译只补空白表，不覆人工 | admission 唯一写咽喉 + 逐字可核闸 + 冲突三态 | 本仓强 |
| 人工认证 | `certified` 布尔标志（term/属性/描述分列），认证不改检索只改呈现 | 候选审批流 + pipeline dry-run + 基线 diff/回滚 | 各有取舍；本仓更硬 |
| 溯源 | 答案带 SQL+步骤；编译历史表 | 推导账本 + 决策台账 + 变更审计 + PROV-O 导出 | 本仓强 |
| 身份 | 前端网关信任 `x-auto-ontology-user-id` 头；ingestion 无鉴权（私网假设） | 身份单通道 + 租户分区 | 本仓强（对方形态不可学） |
| 测试 | 每模块 tests/ 目录；BIRD 基准外置仓 | 65 个本体单测 + CQ 探针 + golden 对拍 | 本仓强 |
| 互操作 | Ossie YAML 进出（Apache 开放标准） | 九格式导出（Turtle/JSON-LD/OWL2RL/SHACL/PROV-O/GraphML/GEXF/Cypher/CSV）+ RDF 导入 | 本仓广，对方有「标准语义模型」生态位 |

---

## 6. 启发与可改进项（按价值分级；均为候选，待点单）

> 每项给：做什么 / 对方证据 / 本仓落点 / 影响面 / 默认态。默认态统一从灰度/关开始，符合本仓门控习惯。

### P1-1 接线 `describeSchema()`：schema 目录自动摄取管线

- **做什么**：新建轻量 catalog 层（如 `ontology_catalog_tables/catalog_columns`，或扩展 `enterprise_source_configs`），企业源注册/健康检查时自动拉 schema 落目录；暴露「源 → 表 → 列 → 类型/键」读面给 Studio 与后续管线。
- **对方证据**：catalog ingest 是其一切的地基（§3.1 步骤 1）。
- **本仓落点**：`knowledge/enterprise/registry.py`（消费 describeSchema 的天然位置）、`schema_mapping.py`（目录可反向辅助人工配映射）、`api/endpoints/knowledge_enterprise.py`。
- **影响面**：企业源面＋前端 EnterpriseSourcesPage；不碰词汇层与事实层，风险低。这是清偿「有而无用」断点的正路（教义第 5 条同根因扫荡）。
- **默认态**：随企业源注册自动开（读 schema 元数据无副作用），可按源类型关。

### P1-2 术语/关系自动建议器：LLM 猜 + 数据证实

- **做什么**：在 P1-1 的 catalog 之上，自动产出**候选**（不直接落本体）：列 → 术语属性映射建议、表 → 概念命名 + 同义词、列值画像（唯一率/低基数 distinct/日期格式规则推断）、外键候选（声明键优先，其余 LLM 猜 + **值包含/join 探针数据证实**）。
- **对方证据**：`semantic_fk.py` 的「向量检索选 + 值包含确认 + join 探针确认，不确定不落库」（§3.1 步骤 3）；`visit_enter.py` 的采样/唯一率/日期格式规则件。
- **本仓落点**：候选全部进既有 `ontology_relation_candidates` 审批流（已带 confidence 字段）或新设 catalog 候选面；确定性规则件可落 `ontology/` 下新模块；LLM 调用走本仓既有 provider 面。
- **影响面**：`neurova/knowledge/ontology/`＋企业源面＋审批前端（Relations 分区已有审批 UI 雏形）；本体词汇仍由审批闸把关，不破「先登记术语再配映射」纪律，而是让登记有据可依。
- **默认态**：env/设置门控，默认关；候选只入审批队列，不自动晋升。

### P1-3 answerability 预检（可独立先行）

- **做什么**：给定问题 → 抽实体 → 在本体术语/事实/目录上做覆盖度评分；低于阈值即诚实回报「本数据面答不了，缺哪些概念」，供对话层反问澄清。
- **对方证据**：`entity_coverage/` 全链 + MCP `check_answerable`「先预检再花钱问」的定位（tools.py:127 描述原文）。
- **本仓落点**：可先做知识库/图谱版（对 `ontology_terms` + `knowledge_facts` 覆盖），复用检索适配器；MCP 加一个只读工具。
- **影响面**：对话链路新增一个前置探针（可跳过）；MCP 工具面 +1；对「问数」与「问知识」两类问题都提升诚实度。
- **默认态**：默认开（只读、便宜），阈值可配。

### P1-4 NL2SQL 问数 grounding（大项，需拍板）

- **做什么**：面向已连接业务库的「自然语言 → SQL → 执行 → 带 SQL 与步骤的答案」链路。对方蓝图：候选检索 → **确定性 join 路径**（semantic FK BFS）→ SQL 生成 → 静态检查 + LLM judge → 修复环（≤7）→ 值校验/空结果探针（LIKE 放宽、近失值修复）→ 诚实拒答。
- **对方证据**：§4.1 全节；拒答附最后确定性 SQL 的 fallback（architecture.md「Answer a question」节末）。
- **本仓落点**：依赖 P1-1/P1-2 的目录与语义外键；执行面可复用 `connectors_sql.py` 只读 query 路由（写意图拒逻辑已在，:112）；产出走本仓产出物面（工件）。
- **影响面**：新子系统（检索/生成/校验/执行四段）＋新 MCP 工具＋前端入口；是本研究中最大工程量，建议拆批：先「目录 + join 路径 + 单表查询」灰度，再「多跳 + 修复环」。
- **默认态**：整体默认关，按 agent/租户灰度开；只读 SQL 硬闸不可绕。
- **替代项**：若暂不做 NL2SQL，P1-3 + P1-1/P1-2 已能支撑「目录问答 + 覆盖度预检」，价值独立成立。

### P2-1 MCP/内置工具面 curated 治理

- **做什么**：给 MCP 工具面加「显式 allow-list + catch-all exclude + 描述按 prompt 语言手写 + 与路由注册表对拍的漂移守卫」；给工具描述补「何时用」的行为指引。
- **对方证据**：tools.py 全文（87→7、`missing_from_spec` 启动失败、描述手写）。
- **本仓落点**：`neurova/mcp_ontology_server.py`（16 工具）与 `tool_executor.py` 内置工具注册表；守卫可仿 `tests/unit/` 既有守卫风格。
- **影响面**：工具描述变更会影响模型选择行为（需回归 agent 工具选择冒烟）；不改工具语义。
- **默认态**：清单收紧默认生效（纯减法），描述改写逐条过。

### P2-2 `check_readiness` 复合就绪探针

- **做什么**：一个只读端点/MCP 工具回答「这个部署现在能不能答知识/数据问题」：术语已登记 + 事实非空 + 推理引擎可用 + 相关企业源连接健康，四事实合一。
- **对方证据**：readiness.py 头注「失败是静默的……一个廉价调用把死胡同变成事实」。
- **本仓落点**：`knowledge_observability.py`（cq-matrix 探针先例就在此）；四项各自已有现成读数。
- **影响面**：极小（只读聚合）；前端 Studio Overview 与运维面板可挂读数。
- **默认态**：默认开。

### P2-3 查询历史/使用回灌

- **做什么**：把高频问题/高频取数模式沉淀为**可复用表达式候选**（对方的 sql_attribute 形态；本仓对应物是 `ontology_functions` 或规则候选），按使用计数排序交 LLM 判定，入审批流。
- **对方证据**：`sql_attribute_suggester.py` 头注五步（3 个月使用计数 top10 → LLM 判 → 只嵌入新节点）。
- **本仓落点**：问数链路（若做 P1-4）的副产品；知识侧可先用「检索命中/未命中日志」做同类回灌（`knowledge_alias_candidates` 已有先例形态）。
- **影响面**：中；需要先有使用计数来源（P1-4 或检索日志）。
- **默认态**：默认关。

### P2-4 Ossie YAML 导入导出

- **做什么**：在九格式导出之外补 Ossie（Apache 语义模型开放标准）进出，降低企业侧已有语义模型（dbt语义层/Looker LookML 等经 Ossie 转换器）的接入成本。
- **对方证据**：README「 compatible with Apache Ossie 」＋ `dal/model_interchange.py`。
- **本仓落点**：`ontology/export/` 旁新增 ossie.py；导入走 pipeline dry-run 闸。
- **影响面**：小（纯增导出格式 + 一个导入入口走既有闸）。
- **默认态**：导出默认可用；导入默认关（走审批）。

### P3-1 面向外部 harness 的 skills 打包

- **做什么**：把「本仓本体 MCP 用法（readiness → 查术语 → 预检 → 问）+ 治理红线」打包成可分发 skill（SKILL.md + references + evals），供 Cursor/Claude 等外部代理使用。
- **对方证据**：`skills/` 三件套 + nvidia/skills 目录镜像 + NVSkills CI 签名纪律；其 AGENTS.md「skills 只编码流程与坑，不复制 API 目录」。
- **影响面**：纯文档/打包，无代码风险；本仓 MCP 面稳定后做才有意义。

### P3-2 term families（同构表副本聚族）

- **做什么**：企业迁移常见 `OLD_/NEW_` 前缀副本，自动聚族防止语义外键跨副本误连。仅在 P1-1/P1-2 落地且真实出现副本场景时再做。
- **对方证据**：`term_families.py` 头注四步算法（镜像边/孪生 Jaccard/证据阈值/同前缀传递）。

### P3-3 编译并发工程件

- **做什么**：若上自动构建管线，需要同款三件：有序提交队列（并行抽取 + 确定名归属）、LLM 在飞限流、可取消语义（跳队 + 等在飞 + 日志明说）。
- **对方证据**：`pipeline.py:33` `_OrderedCommitQueue`、`compile.py:33` `limit_inflight`、`cancellation.py`。

### P3-4 检索工程对齐

- **做什么**：目录/术语全局搜索需要无锚子串匹配；对方用 trigram GIN，本仓 SQLite 可用 FTS5（K-09 已把 FTS 搬主库，有现成基建）或 `LIKE` + 覆盖索引；向量检索复用本仓既有 embedding 面，不引入 pgvector。

---

## 7. 不建议照搬清单

1. **Postgres+pgvector 单体同库栈**：本仓 SQLite 主库 + 既有 embedding 面可覆盖同等能力；换库是伤筋动骨不是收益项。
2. **前端网关信任头身份 + 无鉴权 ingestion 服务**：对方靠「私网隔离」兜底并明文警告；与本仓身份单通道（§6-163 裁定甲）与鉴权收口方向相悖。
3. **四进程拆分（3000/3001/3002/3003）**：对方是部署形态选择；本仓单体 + ASGI 挂载已验证够用。
4. **Better Auth / Prisma / Next.js 16 栈**：前端已有一等体系，不引第二套。
5. **LangGraph 固定管线**：本仓自有 chat pipeline/工具环；借鉴其「固定步骤顺序 + 每步标注模型/规则」的文档化方式即可，不引框架。
6. **certified 布尔认证**：比本仓「审批 + dry-run + 基线回滚」弱；吸收其「人工修订不被机器覆盖」（编译只补空白表）的思想即可。

---

## 8. 证据文件清单

**对方（`E:/项目/_external_repos/NVIDIA-auto-ontology`）**：
`README.md`（557 行）、`docs/architecture.md`（361 行，全流程步骤表）、
`alembic/versions/c778a7d94c20_create_the_auto_ontology_schema.py`（数据模型全貌 + join_path_edge 视图 + trigram 索引）、
`auto_ontology/semantic/{compile,pipeline,visit_enter,semantic_fk,term_families,sql_attribute_suggester,models}.py`、
`auto_ontology/dal/attributes.py:1225`（find_join_path）、
`auto_ontology/retrieval/{text_to_sql/,entity_coverage/}`、
`auto_ontology/retrieval/data_access/semantic_search.py`、
`mcp/auto_ontology_mcp/{tools,readiness}.py`、
`skills/nvidia-ontology-query/SKILL.md`、`AGENTS.md`。

**本仓**：
`neurova/knowledge/ontology/`（34 文件：term_registry/rule_engine/pipeline/cq_matrix/validation/shapes/simulation/decision_ledger/derivation_ledger/export…）、
`neurova/knowledge/foundation/{knowledge_facts,admission,graph_walk,temporal_facts}.py`、
`neurova/knowledge/graph_bridge.py`、
`neurova/knowledge/enterprise/{registry,connectors_sql,schema_mapping,webhook_receiver}.py`、
`neurova/api/endpoints/{knowledge_ontology,knowledge_enterprise,knowledge_access_facade,knowledge_observability}.py`、
`neurova/mcp_ontology_server.py`（`/v1/mcp` 挂载见 `neurova/api/app.py:1699`）、
`neurova/agent/chat_pipeline.py:323-370`、
`NeurUI/src/pages/ontology-studio/OntologyStudioPage.vue`、
`docs/specs/2026-11-10-GB48000-3-本体建模符合性评估与补齐设计.md`、`docs/specs/2026-11-10-Ontology接入Agent五步对照评估与补全设计.md`。

> 复核提示：本仓侧「describeSchema 零生产调用」「76 条 ontology 路由」「MCP 16 工具」三条承重结论已当日 grep 复验；其余行号为盘点时代码态，后续漂移以现场为准。
