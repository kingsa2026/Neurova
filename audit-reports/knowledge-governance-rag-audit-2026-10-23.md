# 知识库治理与 RAG 闭环审计（2026-10-23）

> 性质：只读审计。未改任何生产代码、未改任何知识库数据，仅新增本报告。
> 触发：对照一份外部经验描述——「RAG 上线三个月准确率从 85% 跌到 60%，文档没变、模型没换、prompt 没改，继续加文档是否有用」——核查本仓知识库源码是否存在同类根因。
> 范围：`neurova/knowledge/**`、`neurova/agent/knowledge_retriever_adapter.py`、`neurova/agent/chat_pipeline.py` 的检索段、`neurova/api/endpoints/knowledge*.py`、`neurova/knowledge/foundation/**`，以及本机 `data/knowledge/` 权威库的只读计数。
> 关联文档：`docs/01-architecture/24-knowledge-isolation-rag.md`、`docs/specs/2026-09-20-knowledge-foundation-design.md`、`docs/05-reports/memory-knowledge-write-paths-isolation-audit-2026-09-21.md`、`audit-reports/simplification-audit-2026-10-05.md`。

---

## 一、结论

**本仓不是视频里那种裸向量 RAG。** 主链已经是四路混合检索（tfidf / bm25 / fts / vector）＋ 加权 RRF ＋ 末端重排 ＋ 父子分块；写入侧还有 admission、血缘、置信聚合和事实级冲突裁决。因此外部描述里的六条根因不是“全中”，而是**分层中**：

| 外部根因 | 本仓判定 | 一句话依据 |
|---|---|---|
| 没有生命周期管理 | **部分存在** | 有 revision／软删／恢复／擦除，但文档没有有效期／TTL，定期冗余与过期审计未接线；事实有效期字段生产 0 行 |
| 冲突检测与裁决 | **事实层强、文档层弱** | 事实冲突 60 条全部自动裁决；条目冲突 0 条，导入显式跳过检测，文档只按标题相似度人工裁决 |
| 检索退化 | **部分存在** | 四路混合＋重排是强项；缺查询分布监控、元数据预筛、文档时效衰减、模型版本指纹；另一条 RAG API 仍是 TF-IDF |
| 评估缺失 | **部分存在** | 有离线台架和冻结基线；用例是自动标注的 30 条标题直取，无冲突／过期／权限场景，无生产/CI 回归门，无线上指标 |
| 反馈闭环缺失 | **明确存在** | `recordAdoption` 生产调用点 0；401 条事实 `adoption_outcome` 全 NULL；`/learn`、`/gaps/analyze` 直接 501 |
| 分块与元数据不足 | **部分存在** | 分块很强（父子块／overlap／代码围栏／表头）；但 tags 被搜索端忽略，source／confidence／origin 不参与排序，chunk 无时间／来源／权限／信任标签 |

**对“加更多文档能不能救准确率”的回答：不能。** 在本仓，加文档会同时放大三件事：

1. BM25／FTS 对全部可见语料逐次扫描，没有 category／tag／time 预筛（`hybrid.py:146-180`）；
2. 文档层没有去重和生命周期，重复／过期内容会继续进入候选；
3. 知识库侧没有线上准确率／召回监控，跌了不会报警；唯一基线是 30 条标题直取用例，不能代表真实语义质量。

**一句话总结：核心检索不是短板，闭环治理是短板。** 如果本仓出现“文档越多越不准”，优先查文档生命周期、重复条目、元数据过滤、评估与反馈，而不是继续加文档或改 prompt。

---

## 二、方法、证据与边界

### 2.1 方法

- **源码只读**：用 `grep`／逐文件阅读定位调用点；对“没有调用点”的结论，必须同时给出定义点、导出点和测试点，避免把“我没搜到”当成“不存在”。
- **运行时只读**：用 SQLite `mode=ro` 打开 `data/knowledge/knowledge_facts.db` 与 `data/knowledge/knowledge_evaluation.db`，只做 `SELECT`／`PRAGMA`，不写库、不迁移、不重建。
- **不做的部分**：没有压测、没有造数、没有改生产配置、没有启动服务、没有调用外部模型。本文的结论是“源码与现有数据能证明什么”，不是“线上流量实测”。

### 2.2 证据分级

- **A 级**：源码调用点＋运行时计数同时成立（例：`recordAdoption` 零调用点＋401 行全 NULL）。
- **B 级**：源码结构明确，但运行时没有足够数据（例：文档有效期字段不存在）。
- **C 级**：只有文档或注释声称，未见实现／调用点（例：`FlowKBConfig.flow_ttl_days` 只在配置里出现）。

本文对每条判定标注证据级别；C 级不作为“已实现”引用。

### 2.3 边界

- 本机 `data/knowledge/` 是本地权威库，不等于线上生产流量；其中的条目数、冲突数、评测数只说明“这台机器上发生过什么”，不能外推为线上准确率。
- 评测库在 `/data/` 下，`.gitignore` 已整根忽略；换一台机器或 CI 环境不会自动拥有这份基线。代码虽有 `exportCases`／`loadCases`，但全仓未发现调用点。
- 本文的“生产调用点”指 `neurova/` 下的运行时代码；测试、脚本、`tests/manual/*` 不计入。
- 审计读取的是 2026-10-23 的工作树；当时工作树含并发会话的在途改动（`neurova/agent/chat_pipeline.py`、`neurova/context/orchestrator.py`、`neurova/llm/provider_compat.py` 等），本文行号以当时工作树为准；落到提交态前需重新复核行号与内容。

---

## 三、本仓实际知识链路

### 3.1 写入链路

```
POST /knowledge/create 或 /knowledge/import
        │
        ▼
KnowledgeRepository.create_knowledge()                 repository.py:620
        │  ├─ 条目字段：title/content/category/tags/source/confidence/
        │  │  visibility/owner_user_id/chunks/parents
        │  └─ detect_conflict 默认 True；批量导入显式 False
        ▼
_syncEntryGovernance()                                 repository.py:592
        │
        ▼
EntryLedger.syncFromEntries()                          foundation/entry_ledger.py:44
        │
        ▼
KnowledgeAdmissionGate.admit()                          foundation/admission.py:280
        │  ├─ 内容去重 / 身份消解
        │  ├─ KnowledgeConflictJudge（冲突检测与自动裁决）
        │  ├─ ConfidenceAggregator（置信聚合）
        │  ├─ KnowledgeLineageLedger（血缘）
        │  ├─ OntologyValidationReport（本体）
        │  └─ ForwardChainingEngine（前向推理）
        ▼
knowledge_facts / knowledge_assertions / knowledge_narratives
knowledge_entry_conflicts / knowledge_conflicts / knowledge_activities
```

关键点：

- 权威默认在 SQLite 叙述层，不是 `knowledge.json`；只有显式设置 `NEUROVA_KB_NARRATIVE_STORE=off/json` 才退回旧 JSON 后端（`repository.py:66-72`）。
- 条目写入会投影成 `record_kind='narrative'` 的事实行；图谱抽取另走 `record_kind='triple'`（`graph_bridge.py:191` 起）。
- 向量索引不是写入时同步，而是检索时 `ensure_indexed` 增量同步；删除条目会 `dropEntry` 当场清分片（`vector_index.py:198`）。
- `create_knowledge` 的 `detect_conflict` 只覆盖交互式单条创建；文件导入显式 `detect_conflict=False`（`knowledge_ingestion.py:225`），理由是避免批量导入同名课件时刷屏。这个取舍本身合理，但它意味着**导入路径没有文档级冲突检测**。

### 3.2 读取链路

```
用户问题
   │
   ▼
ChatPipeline._retrieve_memories()                      chat_pipeline.py:1745
   │
   ▼
MemoryRetrievalChain（多级责任链）                      memory_retrieval_chain.py
   │  优先级 25：KnowledgeRetrieverAdapter
   ▼
KnowledgeRetrieverAdapter.retrieve()                   agent/knowledge_retriever_adapter.py:85
   │
   ▼
hybrid_search_knowledge()                              knowledge/hybrid.py:104
   ├─ tfidf：repo.search_visible_items()（分片索引）
   ├─ bm25：hybrid.bm25_rank()（全可见语料）
   ├─ fts：search.full_text_search()（全可见语料）
   └─ vector：KnowledgeVectorIndex.search()（按用户分片）
        │
        ▼
加权 RRF（rrf_fusion，默认权重 tfidf .30 / bm25 .30 / vector .25 / fts .15）
        │
        ▼
末端重排 refineMainPathResults()                        rerank/main_path.py:71
        │  默认开；模型通道在事件循环内会退化为 weighted
        ▼
父子分块回映：命中的子块 → 最多 3 个父块                  repository.py:1029-1045
        │
        ▼
RetrievalResult → ChatPipeline 上下文
```

关键点：

- `KnowledgeRetrieverAdapter` 的优先级是 25：记忆与 MoE 之后、Cache 之前（`knowledge_retriever_adapter.py:20-38`）。
- `FactSurface` 富化默认关：`NEUROVA_KB_FACT_SURFACE` 未设置时 `enabled=False`（`foundation/read_surface.py:32`）。因此默认聊天路径不会附带事实层的置信／证据态／血缘字段。
- `attachGovernance` 只把治理字段挂到已排好序的命中上，**不重排**（`read_surface.py:149-178`）。
- `origin` 信任级在 `KnowledgeRetrieverAdapter._map_origin` 中计算并放进 memories 载荷（`knowledge_retriever_adapter.py:193-232`），但在 `memory_retrieval_chain.py` 与 `context/` 中没有找到消费点；今天是“挂上了但没人用”的元数据。

### 3.3 三条旁路

本仓同一“知识检索”能力存在多条入口，质量不完全一致：

| 入口 | 实际检索 | 是否走 RRF／重排 | 备注 |
|---|---|---|---|
| chat 主路（`KnowledgeRetrieverAdapter`） | `hybrid_search_knowledge` 四路 | 是 | 质量最高的一条 |
| `POST /knowledge/search` | `repo.search_visible_items`（TF-IDF 分片） | 否 | 仍按“标题+内容”语义工作，但没有 bm25/fts/vector 融合 |
| `POST /knowledge/rag/retrieve`、`/rag/batch` | `repo.search_visible_items`（TF-IDF 分片） | 否 | 注释写“记忆 + 知识真实两路”，知识这一路没有用 hybrid |
| 图谱／时效分支 | fact store / `TemporalFactReader` | 不适用 | 走三元组与有效期，不和叙述条目同池排序 |

这不是“功能不存在”，而是**同一能力的两条质量线**。外部调用方走 `/rag/retrieve` 时，拿不到 chat 主路的四路融合与末端重排。

---

## 四、运行时数据快照

> 采集时间：2026-10-23。库：`data/knowledge/knowledge_facts.db`、`data/knowledge/knowledge_evaluation.db`。只读 URI，未写库。

### 4.1 事实与冲突

| 指标 | 读数 | 口径 |
|---|---:|---|
| `knowledge_facts` 总行数 | 401 | 全部状态 |
| `active` | 340 | `status='active'` |
| `superseded` | 60 | `status='superseded'` |
| `retracted` | 1 | `status='retracted'` |
| `record_kind='narrative'` | 36 | 条目正文投影 |
| `record_kind='triple'` | 365 | 抽取／推导三元组 |
| `knowledge_conflicts` 总数 | 60 | 事实层冲突账本 |
| `knowledge_conflicts` 状态 | 60 条全部 `auto_resolved` | 无 pending |
| `knowledge_entry_conflicts` 总数 | 0 | 条目层冲突账本 |
| `valid_from` 非空 | 0 | 事实表 |
| `valid_until` 非空 | 0 | 事实表 |
| `adoption_outcome` 非空 | 0 / 401 | 全部 NULL |
| `knowledge_subjects` | 212 | 主体 |
| `knowledge_activities` | 1566 | 活动账 |
| `knowledge_tombstones` | 0 | 底座墓碑表 |

### 4.2 评测基线

| 指标 | 读数 |
|---|---:|
| 用例数 | 30 |
| 标注口径 | 29 `title_literal` + 1 `category`；无 `manual` |
| run 数 | 2（同一天，2026-10-09） |
| 冻结基线 | 1 条，`evr_34ccf1295e76` |
| 冻结时间 | 2026-10-09T04:53:53Z |
| top_k | 5 |
| recall@5 | 0.971296 |
| MRR | 0.916667 |
| unhit_rate | 0.0 |
| 基线上下文 | `agent_id=default, scope=all, user_id=1` |
| 2026-10-09 之后的新 run | 0 |

**读法警告**：0.971 的 recall 来自 29 条“标题原文”查询和 1 条“类别”查询，不是人工标注的常见问题、冲突场景、过期场景、权限场景。它证明“检索管路通”，不能证明“语义质量高”。把它当线上准确率会高估系统。

### 4.3 这两个读数说明什么

- **事实层治理确实在跑**：60 条冲突全部自动裁决，401 条事实有 60 条 superseded，说明 `KnowledgeConflictJudge` 不是摆设。
- **文档层治理基本没跑**：条目冲突 0 条，与“导入跳过检测 + 只按标题相似度 + 完全重复被忽略”三条叠加一致。
- **有效期链路没有输入**：事实表两个时间列全空，说明生产写入没有声明 `validFrom`／`validUntil`；文档 schema 根本没有这两个字段。
- **反馈链路没有输入**：401 条事实的 `adoption_outcome` 全 NULL，与 `recordAdoption` 零生产调用点互相印证。

---

## 五、六条根因逐项

### 5.1 生命周期管理：部分存在

**外部描述**：只写不删、不更新、不标有效期和版本，知识库变成垃圾场。

**本仓已有**：

- 条目更新时旧值快照进 `revisions`，块级有 `revision`＋乐观锁（`repository.py:1053-1101`、`1337-1397`）。
- 软删走 tombstone，读路径不可见；物理擦除走 `purge_knowledge`，逐面清正文副本（`repository.py:1103-1165`）。
- 有恢复通道 `restore_knowledge` 与墓碑清单 `list_deleted`（`repository.py:1287-1306`）。
- 飞书远程同步会删除远端已消失的文档，且清单残缺（`partial=True`）时不执行删除收敛（`datasource_sync.py:98-165`）。
- 启动时对事实做一次 `expireDueFacts()` 收敛（`app.py:906-914`），API 也提供管理员手动触发（`knowledge_core.py:267-300`）。

**缺口**：

- 文档条目 schema 没有 `valid_from`／`valid_until`／TTL；只有事实表有这两列。
- `FlowKBConfig.flow_ttl_days`、`auto_cleanup`、`max_versions_per_flow` 只在 `config.py:18-35` 定义，生产代码未发现消费点。
- `KnowledgeBaseConfig.embedding_model`、`backup_interval_hours`、`backup_retention_days` 等配置同样只在 `config.py` 内出现，没有对应的运行期执行体。
- 事实有效期字段虽然存在，但生产调用方没有传值：`AdmissionRequest` 有 `validFrom`／`validUntil`（`admission.py:97-98`），而 `graph_bridge.py:191`、`entry_ledger.py:62` 的调用都没有带这两个字段。现查 0 行非空。
- `RedundancyAudit`（`foundation/redundancy.py:15`）只读、只报告、不删除，全仓未发现生产调用点。
- `FoundationReconciler`（`foundation/reconcile.py:85`）只有定义、导出和测试，没有生产调用点。
- 没有“旧文档降权／归档／过期后不进入检索”的策略；tombstone 只处理手动删除，不处理“内容过时但没人删”。

**判定**：**部分存在**。视频里“只写不删、不更新、不标版本”在本仓不成立；但“没有有效期、没有定期审计、没有归档降权”成立。

**影响**：文档会持续累积；重复、过期、被替代、测试数据不会自动识别；检索候选集越来越大，而这部分噪声没有治理出口。

---

### 5.2 冲突检测与裁决：事实层强，文档层弱

**外部描述**：新旧版本、多来源说法不一致，模型不知道信谁。

**本仓已有（事实层）**：

- `KnowledgeConflictJudge` 支持 `most_recent`、`highest_confidence`、`credibility_weighted`、`keep_both`、`manual` 五种策略；没有依据时返回 `manual`，不自动裁决（`conflict_judge.py:102-138`）。
- `record()` 检测并成账，能自动裁决的顺手取代败方，双方互写 `contradicted_by`（`conflict_judge.py:140-181`）。
- 写入经 `productionAdmissionGate` 统一装配冲突、血缘、置信、本体、推理（`admission.py:506-531`）。
- 运行时 60 条事实冲突全部 `auto_resolved`，说明这条链路确实在跑。

**本仓已有（文档层）**：

- `_detect_conflicts` 按标题归一化相似度 ≥0.9 找“同一事实的新说法”候选；内容完全相同（相似度 ≥0.999）被当作“不算冲突”跳过（`repository.py:1403-1454`）。
- 冲突账本默认 pending；管理员通过 `/knowledge/conflicts` 查看，通过 `/conflicts/{id}/resolve` 裁决 `keep_both` 或 `supersede_old`（`knowledge_sharing.py:62-157`）。

**缺口**：

- 文档层只按**标题**找冲突，不比对正文主张；标题不同但内容矛盾的两篇文档不会进队列。
- 内容完全相同的重复被显式跳过，**不等于去重**：`create_knowledge` 不查重，重复条目仍然入库、仍然进索引。
- 文件导入显式 `detect_conflict=False`（`knowledge_ingestion.py:225`），批量导入路径完全没有文档级冲突检测。
- 条目冲突现查 0 条；无法从数据上证明这条队列在真实导入中被使用过。
- 事实层的自动裁决策略不适用于文档：`foundation/conflict_judge.py` 对 `record_kind='narrative'` 按条目范围分组，不同文档即使同标题也不会被当成同一说法的多个值；这是有意的边界，不是 bug。

**判定**：**事实层强、文档层弱**。视频里“缺乏冲突检测和裁决”在本仓的事实层不成立，在文档层成立。

**影响**：同名／近义文档的新旧说法基本不会被发现；重复文档会同时进入检索候选，造成“同一内容两票”与候选集噪声。

---

### 5.3 检索退化：部分存在

**外部描述**：查询分布变了、嵌入模型没更新、索引碎片化、元数据缺失、过滤没用上。

**本仓已有**：

- `hybrid_search_knowledge` 四路检索＋加权 RRF（`hybrid.py:104-238`）。
- 末端重排默认开，候选池按 `limit * poolFactor` 截断；关闸态与开闸前行为逐字一致（`rerank/main_path.py:36-60`）。
- 向量索引按用户分文件，增量同步；引擎变化时重建；删除条目时 `dropEntry` 当场清副本（`vector_index.py:119-225`）。
- 父子分块：子块进索引，父块给 LLM；命中回映最多 3 个父块（`splitter.py:284-337`、`repository.py:1029-1045`）。
- 可见性过滤先于检索；向量索引按用户分片，融合后回映可见集双保险（`hybrid.py:9-13`、`repository.py:704-753`）。

**缺口一：没有查询分布／漂移监控。**
知识库侧没有 query log 聚合、没有检索质量时间序列、没有线上 recall/准确率读数。唯一评测是离线台架，且用例是自动标注的标题直取（见 5.4）。

**缺口二：嵌入模型指纹只记类名。**
`_engine_id(engine)` 返回 `type(engine).__name__`（`vector_index.py:49-50`）。`ONNXEmbeddingEngine` 的 `model_name` 默认 `BAAI/bge-small-zh-v1.5`（`neurova/embedding/onnx_embedding.py:51-80`），但同一类换 `model_name`／换权重版本时，索引文件头 `engine` 字段不会变，`ensure_indexed` 不会触发重建。`KnowledgeBaseConfig.embedding_model` 也没有消费点。结果是“换了模型，向量索引还在用旧空间”，且没有任何报警。

**缺口三：元数据过滤没有真正接上。**
`KnowledgeSearchRequest` 声明了 `tags`（`knowledge_common.py:69-75`），但 `/knowledge/search` 只把 `query/category/scope/agent_id/limit` 传给 `search_visible_items`（`knowledge_core.py:103-121`）；`search_visible_items` 的签名里也没有 tags（`repository.py:922-930`）。发 tags 的调用方拿到的是未过滤结果。chat 主路的 `hybrid_search_knowledge` 同样没有 category/tags/time 参数，只按 scope/agent 过滤。

**缺口四：文档排序没有时效／来源／置信加权。**
RRF 只消费秩，不消费分数（`hybrid.py:38-51`）；`attachGovernance` 只富化不重排（`read_surface.py:149-178`）；`FactSurface.rankHits` 有 freshness/confidence 修正，但默认关且只用于事实（`read_surface.py:32-41`、`96-124`）。条目级 `confidence` 和 `source` 不参与文档排序。`origin` 信任级只挂在结果上，未发现下游消费点（`knowledge_retriever_adapter.py:193-206`）。

**缺口五：自适应检索默认关，意图识别不在知识层。**
`NEUROVA_ADAPTIVE_RETRIEVAL` 未设置时默认关闭；只有请求级 metadata 或环境变量显式开启，才会在首查低质时做子问题拆解／查询改写（`chat_pipeline.py:102-114`、`1778`、`1863-1968`）。`QueryIntentDetector` 在记忆召回层 `neurova/cognitive_layers/memory_layer/neurova_recall.py:121`，知识适配器没有调用它。

**缺口六：同一能力两条质量线。**
`/knowledge/search` 与 `/knowledge/rag/retrieve` 都走 `search_visible_items`（TF-IDF），没有走 hybrid／rerank（`knowledge_core.py:103-121`、`knowledge_integration.py:97-120`）。chat 主路质量最高，外部 RAG API 质量较低，且调用方不一定知道。

**缺口七：候选集扫描没有预筛。**
`hybrid_search_knowledge` 用 `repo.visible_items` 构建全量可见语料，再让 BM25／FTS 逐次扫描（`hybrid.py:146-180`）；没有按 category/tag/time/source 预筛。当前条目规模小，这不是故障；扩容后就是视频里的“候选集膨胀 + 重排压力”路径。重排池本身有上限（`limit * poolFactor`），所以重排成本是可控的，真正会膨胀的是候选生成。

**附带的文档漂移**：
`docs/01-architecture/24-knowledge-isolation-rag.md:28-33` 仍写“FTS5 全文检索（辅）：关键词精确匹配（知识库恒占位）”“向量检索（主）”。实际 `search.full_text_search` 是内存 IDF 覆盖式评分并参与 RRF（`search.py:129-174`），默认权重是 tfidf .30 / bm25 .30 / vector .25 / fts .15（`hybrid.py:30-32`），vector 不是主路。文档需要回修，否则下一位读者会按错的权重和“FTS 恒占位”做判断。

**判定**：**部分存在**。核心检索不是短板；缺的是查询分布监控、模型版本指纹、元数据预筛、文档时效与统一入口。

---

### 5.4 评估缺失：部分存在

**外部描述**：没有黄金测试集和线上监控，跌了才发现。

**本仓已有**：

- `RetrievalBenchmark` 能把标注案例跑真检索路，算 recall@k／MRR／unhit，读数落 SQLite（`evaluation/retrieval_benchmark.py:78-323`）。
- 支持冻结基线、逐案对比、`newlyUnhit`／`missingCases` 判定回归（`:361-427`）。
- API 提供只读 `/knowledge/evaluation/baseline`（`knowledge_core.py:206-238`）。
- 本机已有 30 条用例、1 条冻结基线，基线 recall@5 0.971296 / MRR 0.916667 / unhit 0.0（2026-10-09）。

**缺口**：

- **用例不是黄金集**：30 条全部来自 `seedFromRepository` 自动标注，29 条 `title_literal`、1 条 `category`，没有 `manual`；没有覆盖冲突、过期、权限、常见问题的用例。它测的是“管路通”，不是“语义准”。
- **没有回归门**：`compareAgainstBaseline` 全仓没有生产／CI 调用点；`addCase`／`run`／`freezeBaseline` 没有 API；`/evaluation/baseline` 只读。
- **没有新鲜度**：2 次 run 都在 2026-10-09，之后 14 天没有新 run；本仓在 2026-10-20 还落了批 119 等改动，检索链变更没有触发基线复跑。
- **不可移植**：评测库在 `/data/` 下，被 `.gitignore` 整根忽略；代码有 `exportCases`／`loadCases`，但没有调用点。换机或 CI 不会自动拥有这 30 条用例。
- **没有线上指标**：知识库模块内未发现 recall／准确率／冲突率／过期率／拒答率／人工接管率／检索延迟／token 成本的聚合指标。`retrieval_time` 在 `RetrievalResult` 里返回，但没有知识库侧的聚合与告警。
- **没有 bad case 归因**：台架能指出 `newlyUnhit` 的 query，但没有把失败归因到“召回／重排／知识库本身”的分类。

**判定**：**部分存在**。离线台架是真实资产，但它没有形成“改策略→跑回归→不过门就拦”的闭环，也没有线上监控。视频里“跌了才发现”的风险在本仓成立，而且更隐蔽——因为没有线上准确率读数，可能“跌了也不知道”。

---

### 5.5 反馈闭环缺失：明确存在

**外部描述**：用户纠正没回流到知识库和排序模型。

**本仓现状**：

- `KnowledgeFactStore.recordAdoption()` 有实现、有校验、有 `usageMetrics()`（`foundation/knowledge_facts.py:544-600`），但**全仓没有生产调用点**；代码注释自己写明这一点（`knowledge_facts.py:588-594`）。
- 现查 401 条事实 `adoption_outcome` 全 NULL，`outcome_written=0`。这不是“没人采纳”，是“没人回写”。
- `/knowledge/learn` 直接 501，`/knowledge/gaps/analyze` 直接 501；`/gaps`、`/learning-records` 返回空列表并注明产生端未实现（`knowledge_integration.py:198-243`）。
- `/chat/feedback` 的 `like/dislike/corrected_answer` 进入记忆温度、通道权重、结晶、反思和标注库（`console.py:1773-2024`），**没有写知识库**。
- 即使把 `recordAdoption` 接上，当前排序链也没有消费 `adoption_outcome` 的位置：`hybrid` 的 RRF 不用它，`attachGovernance` 只挂字段不重排，`FactSurface.rankHits` 只看 freshness/confidence。要形成“采纳→越用越准”，还需要定义排序／置信回流规则。

**判定**：**明确存在**。这是六条里本仓最确定的一条，也是与视频描述最直接对应的一条。

**影响**：用户纠正、点赞点踩、引用采纳都不会让知识库变好；`usageMetrics` 的 `outcome_never_written` 会长期等于总数，读的人如果只看 0 会误判成“没人采纳”。

---

### 5.6 分块与元数据不足：部分存在

**外部描述**：切块破坏语义；缺少时间、来源、权限、可信度标签，无法精细过滤。

**本仓已有**：

- `chunk_text` 按段落→句子→硬切降级，支持 overlap、代码围栏原子保护、GFM 表头再注入；块偏移满足 `text == 原文[start:end]`（`splitter.py:1-209`）。
- `build_entry_chunks` 做父子分块：子块（默认 384 字）进索引，父块（默认 800 字）给 LLM；子块带 `parent_index`（`splitter.py:284-337`）。
- 条目级有 `tags`、`source`、`confidence`、`visibility`、`owner_user_id`、`shared_with`。
- 权限隔离在检索前完成：`visible_items` 先过滤，再进索引；向量索引按用户分片（`repository.py:704-753`、`vector_index.py:4-13`）。
- 上下文注入有上限：检索 limit 默认 10，命中回映最多 3 个父块（`repository.py:1029-1045`）。

**缺口**：

- chunk 本身只有 `content/index/char_start/char_end/context_header/parent_index/revision`，没有时间、来源、权限、可信度标签；这些信息只在条目级。
- 条目级 tags 在搜索端被忽略（见 5.3 缺口三）；source/confidence 不参与排序。
- `origin`（owner/agent/untrusted）在适配器中计算，但未发现下游消费点。
- 文档没有时间衰减；`FactSurface` 的 freshness 只作用于事实，且默认关。
- 没有按部门／权限／类型／时间做“先过滤再检索”的通用元数据预筛；chat 主路只按 scope/agent 过滤。

**判定**：**部分存在**。视频里“分块破坏语义”在本仓基本不是问题，分块是强项；“元数据无法精细过滤”是真的，尤其在 chat 主路。

---

## 六、五层治理矩阵

| 层 | 已有能力 | 主要缺口 | 判定 |
|---|---|---|---|
| 1 知识治理 | admission 唯一写咽喉；内容去重／身份消解／事实冲突自动裁决／置信聚合／血缘／本体／前向推理；条目 revision、tombstone、purge、restore；权限隔离 | 文档无有效期／TTL；定期冗余审计未接线；无归档降权；文档冲突只按标题、只人工；批量导入跳过冲突检测 | 半闭环 |
| 2 检索优化 | 四路混合＋加权 RRF；末端重排默认开；父子分块；向量索引增量同步；可见性隔离；自适应检索可开 | 无查询分布／漂移监控；模型指纹只记类名；tags 被忽略；无文档时效／来源／置信加权；意图识别不在知识层；/rag/retrieve 与 /knowledge/search 仍是 TF-IDF | 强核心、缺外围 |
| 3 评估闭环 | 离线台架、冻结基线、逐案回归、recall/MRR/unhit | 黄金集缺失；无冲突／过期／权限场景；无生产/CI 回归门；用例不可移植；无线上指标；无 bad case 归因 | 未闭环 |
| 4 反馈学习 | 有 `recordAdoption` 实现、`usageMetrics`、聊天反馈通道 | adoption 零生产调用点；401 行全 NULL；/learn、/gaps 501；反馈不进 KB；排序不消费 adoption | 缺失 |
| 5 运维监控 | 启动事实到期、投影分叉巡检、摄取排水、飞书同步；`/foundation/usage`、`/foundation/integrity`、`/foundation/expiry` | 无索引健康／新鲜度／过期率／冲突率／延迟／token 指标；无定期重建；无换模型迁移；无文档级过期巡检 | 部分 |

---

## 七、风险分级与修复票候选

> 以下是候选票，不构成实施授权。按仓内纪律，每条落地前应先立红灯，再做最小实现，并用 A/B 自证不回归。

### P0：不补就会继续“越用越脏/越用越不准”

#### P0-1 反馈闭环：把“采纳/纠正”接回知识库，或明确不承诺

- **问题**：`recordAdoption` 零调用点，401 条事实全 NULL；`/learn`、`/gaps` 501；聊天反馈只进记忆。
- **范围**：在聊天反馈／引用／回答采纳处识别“这条回答用了哪些知识命中”，调用 `recordAdoption`；定义 `success/failure/unevidenced` 的判定口径；决定 `adoption_outcome` 是否、如何影响排序／置信。
- **验收**：
  - 真实反馈路径能写出非 NULL `adoption_outcome`；
  - `usageMetrics` 不再以“全 NULL”呈现；
  - 若 adoption 不影响排序，报告必须明说“它只是治理读数”，不能暗示“越用越准”；
  - 红灯先咬住“写回没有发生”这一行为，不用 `MagicMock` 冒充。
- **风险**：回答→知识命中的归因不唯一；不要把“引用过”直接当“采纳成功”，三态要可解释。

#### P0-2 文档生命周期：有效期／陈旧／重复的定期审计

- **问题**：文档没有有效期/TTL；`FlowKBConfig` 的 TTL 字段无消费点；`RedundancyAudit`／`FoundationReconciler` 无生产调用点；条目冲突 0 条。
- **范围**：
  - 给文档条目增加可查询的生命周期状态（`valid_until` 或 `status=stale/archived`），先做“可标记、可查询、可排除”，不急于自动删除；
  - 把 `RedundancyAudit` 接成管理员端点或定时任务，输出重复组、无内容身份行、可归档候选；
  - 把 `FoundationReconciler` 的静态对账接成可手动触发的巡检，报告预测/实跑差异；
  - 明确“旧文档降权/归档”的规则：按时间、来源、置信、被替代关系，而不是凭感觉删除。
- **验收**：
  - 能列出重复/过期/被替代文档及证据；
  - 检索能排除或降权已归档/过期条目；
  - 审计只报告、不静默删除；删除仍走 tombstone／purge 的显式通道；
  - 红灯先咬住“重复/过期条目仍然进入检索”这一行为。
- **风险**：自动归档可能误伤仍在使用的旧文档；先做“报告 + 人工确认”，再考虑自动。

### P1：让检索在扩容时不变差

#### P1-1 元数据过滤：修 tags 静默忽略，接 category/tags/source/time 预筛

- **问题**：`KnowledgeSearchRequest.tags` 被声明但未传；`search_visible_items` 没有 tags 参数；hybrid 只按 scope/agent 过滤。
- **范围**：
  - 让 `/knowledge/search` 真正按 tags 过滤；补一条“发 tags 与不发 tags 结果不同”的判据；
  - `hybrid_search_knowledge` 增加 category/tags/time/source 的可选预筛参数，先过滤再 BM25/FTS/vector；
  - chat 主路按上下文携带的过滤条件透传，不要只靠 scope/agent；
  - 预筛先做“可选、默认不改变现有行为”，并用基线 A/B 证明不回归。
- **验收**：tags 过滤有行为测试；预筛后的候选集与延迟可观测；旧调用方不传参数时行为逐字不变。

#### P1-2 评估：从“离线台架”升级为“黄金集 + 回归门 + 线上指标”

- **问题**：30 条用例是自动标注标题直取；无冲突/过期/权限场景；无生产/CI 门；用例不可移植；无线上指标。
- **范围**：
  - 建人工 golden set：常见问题、冲突、过期、权限、无答案/拒答各至少一组；
  - 把 `compareAgainstBaseline` 接 CI 或发布前检查；检索策略/模型/分块/索引变更必须跑；
  - 把 `exportCases` 的结果放到可入库位置（不是 `/data/`），让换机/CI 可复现；
  - 增加线上指标：检索延迟、命中率、空结果率、冲突率、过期率、拒答率、人工接管率、token 成本；
  - bad case 归因至少分三类：召回没进、重排掉出、知识库本身没有/过期。
- **验收**：一次策略变更能在 CI 或发布前给出“通过/退步/无依据”三态，退步时点名具体 case。

#### P1-3 统一检索入口：`/rag/retrieve`、`/knowledge/search` 与 chat 主路同源

- **问题**：chat 走 hybrid+rerank，`/rag/retrieve` 与 `/knowledge/search` 走 TF-IDF，同一能力两条质量线。
- **范围**：让 API 检索也走 `hybrid_search_knowledge`；如果保留轻量 TF-IDF 路径，必须在响应里明示 `retrieval_method`，不能静默降级。
- **验收**：同一 query、同一用户、同一 scope 下，三条入口的召回集合差异可解释；没有“API 看起来有结果，但质量线更低”而调用方不知道的情况。

### P2：规模化与可观测性

#### P2-1 嵌入模型指纹与索引健康

- **问题**：`_engine_id` 只记类名；同引擎换 `model_name` 不重建；索引无健康度端点。
- **范围**：指纹加入 `model_name`／版本／维度／量化方式；索引文件头记录；换模型触发重建；暴露 `entry_count/computed/engine/model/updated_at` 等只读统计。
- **验收**：改 `model_name` 后下一次检索触发重建；索引健康度可查询；重建失败有显式错误而不是静默空结果。

#### P2-2 候选集预筛与规模测试

- **问题**：BM25/FTS 对全部可见语料逐次扫描；当前条目少，扩容后候选集膨胀。
- **范围**：先用 category/tags/time/source 预筛，再进词法/向量路；补规模测试（例如 1k/10k/100k 条目）记录延迟与召回；重排池仍按 `limit * poolFactor` 封顶。
- **验收**：规模增长时延迟曲线可解释；预筛不改变基线召回；没有“为了省成本把可见性过滤做丢”的回归。

---

## 八、不建议的做法

1. **不要先加文档、加 prompt。** 本仓的瓶颈不是“知识不够”，是文档生命周期、元数据过滤、评估和反馈没有闭环；加文档会同时放大噪声和成本。
2. **不要新造第二套检索。** 已经有 `hybrid_search_knowledge`，缺的是把 `/rag/retrieve`、`/knowledge/search` 和 chat 主路收口到同一实现，而不是再造一个 RAG service。
3. **不要用自动删除解决重复。** 先出重复/过期报告，保留 tombstone/purge 的显式通道；没有证据的删除会把“旧但仍在用”的文档误杀。
4. **不要把标题直取基线的 0.971 当真实准确率。** 它只证明管路通；拿它做“我们比 85% 好”的结论会误导。
5. **不要把 `adoption_outcome=0` 读成“没人采纳”。** 当前是“没人回写”；`usageMetrics` 自己已经写了这个成因，报告不能把账面缺失当产品结论。
6. **不要在测试里写生产库。** `storage_fence` 只守 `data/knowledge` 且是 pytest-only；新增判据必须走隔离数据根，不能为了省事碰真库。
7. **不要只改文档不改代码。** 本报告已经指出 `docs/01-architecture/24-knowledge-isolation-rag.md` 的 FTS/权重描述与实现漂移；文档回修要与代码同批，否则下一位读者会按错的模型做判断。

---

## 九、附录 A：证据索引

| 主题 | 证据（文件:行号） | 观察 |
|---|---|---|
| 四路混合检索 | `neurova/knowledge/hybrid.py:104-238` | tfidf/bm25/fts/vector → RRF → rerank |
| 默认权重 | `neurova/knowledge/hybrid.py:30-32` | tfidf .30 / bm25 .30 / vector .25 / fts .15 |
| 全量语料扫描 | `neurova/knowledge/hybrid.py:146-180` | BM25/FTS 对 `visible_items` 全量扫描 |
| 末端重排 | `neurova/knowledge/rerank/main_path.py:36-123` | 默认开；模型通道在事件循环内退化 |
| 父子分块 | `neurova/knowledge/splitter.py:284-337` | 子块进索引，父块给 LLM |
| 分块语义保护 | `neurova/knowledge/splitter.py:1-209` | 段落/句子/硬切、overlap、代码围栏、表头 |
| 向量索引增量 | `neurova/knowledge/vector_index.py:119-196` | 新增/变更/删除增量；重启恢复 |
| 引擎指纹 | `neurova/knowledge/vector_index.py:49-50` | 只取类名，不取 model_name/版本 |
| 条目 revision | `neurova/knowledge/repository.py:1053-1101` | 覆盖前快照旧值 |
| 块 revision/乐观锁 | `neurova/knowledge/repository.py:1337-1397` | `expected_revision` 冲突显式报错 |
| 软删/恢复/擦除 | `neurova/knowledge/repository.py:1103-1165,1287-1306` | tombstone / restore / purge |
| 文档冲突检测 | `neurova/knowledge/repository.py:1403-1519` | 标题相似度 ≥0.9；人工 keep_both/supersede_old |
| 导入跳过冲突 | `neurova/api/endpoints/knowledge_ingestion.py:210-226` | `detect_conflict=False` |
| 冲突 API | `neurova/api/endpoints/knowledge_sharing.py:62-157` | entry/fact 两轴；管理员裁决 |
| 事实冲突裁决 | `neurova/knowledge/foundation/conflict_judge.py:24-181` | 五种策略；无依据不自动裁决 |
| 唯一写咽喉 | `neurova/knowledge/foundation/admission.py:280,506-531` | 冲突/血缘/置信/本体/推理统一装配 |
| 条目投影 | `neurova/knowledge/foundation/entry_ledger.py:44-86` | 条目 → narrative 事实 |
| 有效期字段 | `neurova/knowledge/foundation/admission.py:97-98` | `validFrom` / `validUntil` 入参存在 |
| 有效期未落值 | `neurova/knowledge/graph_bridge.py:191`、`foundation/entry_ledger.py:62` | 生产调用未带有效期；现查 0 行非空 |
| 事实到期 | `neurova/knowledge/foundation/knowledge_facts.py:1065-1085` | `expireDueFacts()` 推进 active→expired |
| 启动到期收敛 | `neurova/api/app.py:906-914` | 启动一次性收敛，不起循环 |
| 到期 API | `neurova/api/endpoints/knowledge_core.py:267-300` | 管理员手动触发，幂等 |
| 冗余审计 | `neurova/knowledge/foundation/redundancy.py:15-69` | 只读、只报告、不删除；无生产调用点 |
| 对账器 | `neurova/knowledge/foundation/reconcile.py:85-190` | 静态预测 + 回放对账；无生产调用点 |
| 评测台架 | `neurova/knowledge/evaluation/retrieval_benchmark.py:78-463` | recall/MRR/unhit；冻结基线；逐案回归 |
| 评测 API | `neurova/api/endpoints/knowledge_core.py:206-238` | 只读 baseline；无 run/add/freeze 端点 |
| 反馈写回 | `neurova/knowledge/foundation/knowledge_facts.py:544-600` | `recordAdoption` 定义；注释自证无生产调用点 |
| 学习/盲点 501 | `neurova/api/endpoints/knowledge_integration.py:198-243` | `/learn`、`/gaps/analyze` 未实现 |
| 聊天反馈 | `neurova/api/endpoints/console.py:1773-2024` | 进记忆/通道/结晶/反思/标注，不进 KB |
| tags 请求字段 | `neurova/api/endpoints/knowledge_common.py:69-75` | 声明了 tags |
| tags 未消费 | `neurova/api/endpoints/knowledge_core.py:103-121`、`repository.py:922-930` | 端点不传；`search_visible_items` 无 tags 参数 |
| 治理富化不重排 | `neurova/knowledge/foundation/read_surface.py:149-178` | 只挂字段，顺序不动 |
| 事实读面默认关 | `neurova/knowledge/foundation/read_surface.py:32-41` | `NEUROVA_KB_FACT_SURFACE` 未设置即关 |
| 信任级挂载 | `neurova/agent/knowledge_retriever_adapter.py:193-232` | `origin` 计算并放进载荷；未发现下游消费 |
| 自适应检索默认关 | `neurova/agent/chat_pipeline.py:102-114` | 请求级/环境变量显式开启 |
| 查询拆解/改写 | `neurova/agent/chat_pipeline.py:1863-1968` | 首查低质时拆 2-3 子问题，失败退化改写 |
| 记忆意图检测 | `neurova/cognitive_layers/memory_layer/neurova_recall.py:121` | 知识适配器未调用 |
| API 旁路 TF-IDF | `neurova/api/endpoints/knowledge_integration.py:97-120` | `/rag/retrieve` 知识路走 `search_visible_items` |
| 配置无消费点 | `neurova/knowledge/config.py:18-90` | `flow_ttl_days`/`auto_cleanup`/`embedding_model` 仅在配置层 |
| 启动循环 | `neurova/api/app.py:895-956` | 摄取排水、到期收敛、投影巡检、飞书同步 |
| 飞书删除收敛 | `neurova/knowledge/datasource_sync.py:98-165` | 远端消失且清单完整时删除；partial 时不删 |
| 权限过滤 | `neurova/knowledge/repository.py:704-753` | public/private/shared/admin 先过滤 |
| 文档漂移 | `docs/01-architecture/24-knowledge-isolation-rag.md:28-33` | 仍写 FTS5 恒占位、vector 主路；与实现不符 |

---

## 十、附录 B：只读复算命令

以下命令只读，不写库、不迁移。Windows 下可用项目解释器执行。

### B.1 事实与冲突

```python
import sqlite3

con = sqlite3.connect("file:data/knowledge/knowledge_facts.db?mode=ro", uri=True)
for sql in [
    "select status, count(*) from knowledge_facts group by status",
    "select count(*) from knowledge_facts",
    "select record_kind, count(*) from knowledge_facts group by record_kind",
    "select count(*) from knowledge_facts where valid_from is not null and valid_from <> ''",
    "select count(*) from knowledge_facts where valid_until is not null and valid_until <> ''",
    "select adoption_outcome, count(*) from knowledge_facts group by adoption_outcome",
    "select status, count(*) from knowledge_conflicts group by status",
    "select count(*) from knowledge_entry_conflicts",
    "select count(*) from knowledge_subjects",
    "select count(*) from knowledge_activities",
    "select count(*) from knowledge_tombstones",
]:
    print(sql, "=>", [tuple(r) for r in con.execute(sql)])
con.close()
```

本次读数：

```
status: active=340, retracted=1, superseded=60
total: 401
record_kind: narrative=36, triple=365
valid_from 非空: 0
valid_until 非空: 0
adoption_outcome: None=401
knowledge_conflicts: auto_resolved=60
knowledge_entry_conflicts: 0
knowledge_subjects: 212
knowledge_activities: 1566
knowledge_tombstones: 0
```

### B.2 评测基线

```python
import sqlite3

con = sqlite3.connect("file:data/knowledge/knowledge_evaluation.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
for r in con.execute(
    "select run_id, started_at, case_count, top_k, measure_state, recall_at_k, mrr,"
    " unhit_rate, is_baseline, frozen_at, note from evaluation_runs order by started_at"
):
    print(dict(r))
print([tuple(r) for r in con.execute(
    "select labeling_method, count(*) from evaluation_cases group by labeling_method"
)])
con.close()
```

本次读数：

```
30 cases: title_literal=29, category=1
2 runs, 1 baseline, both 2026-10-09
baseline: recall_at_k=0.971296, mrr=0.916667, unhit_rate=0.0, top_k=5
```

### B.3 口径

- 这些计数是“本机 `data/knowledge/` 当前状态”，不是线上流量。
- `data/` 在 `.gitignore` 中整根忽略；评测库换机不可复现。
- 任何写操作（迁移、清理、重建）都不在本次审计范围内。

---

## 十一、附录 C：术语

- **RRF**：Reciprocal Rank Fusion，按各路排名而不是原始分融合，避免不同分数域直接相加。
- **admission gate**：知识写入的唯一咽喉；负责内容去重、身份消解、冲突检测、血缘、置信、本体与推理。
- **narrative / triple**：条目正文投影（`record_kind='narrative'`）与抽取/推导三元组（`record_kind='triple'`）。
- **tombstone**：软删记录；读路径不可见，但保留可恢复数据；物理擦除走 `purge`。
- **lineage**：事实到断言、活动、来源的血缘链；`/foundation/integrity` 只读巡检。
- **golden set**：人工标注的查询—期望结果集合，覆盖常见/冲突/过期/权限/无答案场景；与“从库内自动生成查询”不同。
- **adoption outcome**：知识被采纳后的三态结果 `success/failure/unevidenced`；当前生产写回为 0。
- **candidate set**：进入融合/重排前的候选集合；本仓 BM25/FTS 目前对全可见语料扫描。
- **confidence / freshness**：事实读面的排序修正项；文档条目当前不参与排序。

---

## 十二、变更记录与下一步

- **2026-10-23**：初版。只读审计，未改生产代码、未改知识库数据；仅新增本报告。
- **下一步（等点单）**：
  1. 若要先做 P0：反馈闭环（P0-1）与文档生命周期（P0-2）可以并行，但都要先立红；
  2. 若要先稳住检索质量：P1-1 元数据过滤与 P1-3 入口统一优先于 P2；
  3. 若要先建立可复现的评估：P1-2 的黄金集要先于任何排序/模型改动；
  4. 任何“自动删除/自动归档”都先做报告与人工确认，不直接改数据。

> 本报告是审计产物，不是实施授权。按仓内纪律，落地时单任务单 commit，先红后绿，附 A/B 与 live-verify 证据。

---

## 十三、实施终态（2026-10-23）

> 全部批次已落工作树，**尚未提交**。产品语义采用保守口径：自动反馈只消费服务端血缘、TTL 只归档不删除、未接指标只点名不伪造。

### 13.1 已落

| 票 | 落点 | 语义/边界 | 验证 |
|---|---|---|---|
| P1-1 tags | `visible_items/search_visible_items` 增加 tags（AND）；`/knowledge/search` 传 `body.tags` | 先筛后检 | A/B 5 红→0；live PASS |
| P1-1b hybrid 预筛 | hybrid 接收 category/tags/source/updated_after；适配器从 metadata 透传 | 预筛在 BM25/FTS 前 | 60/1k 合成分区；A/B 5 红→0 |
| P1-3 RAG 入口 | `/rag/retrieve`、`/rag/batch` 改走 hybrid；身份用端点注入用户 | 与 chat 同源；修掉 `request.state` 空身份 | live PASS；A/B 2 红→0 |
| P0-2a 冗余审计 | `GET /knowledge/audit/redundancy` | 管理员只读 | 单测＋live PASS |
| P0-2b 生命周期 | `valid_until/lifecycle_status/lifecycle_reason`；检索排除；EntryLedger retract | 手动 PUT＋审计 | A/B 5 红→0 |
| P0-2b TTL | `expireDueEntries`；启动自动 apply；`POST /audit/expiry` 默认 dry-run | 只归档不删正文，可恢复 | A/B 1 红→0；live archived=1 |
| P0-1 显式采纳 | `POST /knowledge/facts/{fact_id}/adoption` | 显式 fact_id＋三态 | A/B 3 红→0 |
| P0-1 自动反馈 | 适配器映射 fact lineage；随 assistant metadata 落盘；`/chat/feedback` 按服务端 lineage 写 adoption | like→success、dislike/纠错→failure；不接受客户端自报 | A/B 12 红→0；live facts_recorded=1 |
| P1-2 黄金集/门 | 人工 fixtures 覆盖常见/冲突/过期/权限；pytest 跑真 hybrid | 非自动标注 | A/B 2 红→0 |
| P1-2 指标 | `GET /audit/retrieval-metrics`；requests/hits/empty/errors/latency/routes/lifecycle/pending_conflicts/token_usage | 未接项进 `uninstrumented` | 单测＋live PASS |
| P1-2 token 归因 | v14 `knowledge_fact_usage`；post-chat 按服务端 lineage 均分写入；`knowledge_token_usage` | 均分估计（attribution=even_split），不冒充逐条真实成本；**多轮 turn_id 缺陷待设计 §5.2 修复** | A/B 3 红→0；live token 表可读（仅首轮） |
| P1-2 拒答信号 | `TurnOutcome` 分类 + `conversation_quality_events`；content_filter→safety_refusal、检索 gate→insufficient_evidence、unknown 单列 | 安全/证据不足/未知拆开；文本不猜 | 分类/事件账/API 判据；A/B 新增 3 红→0；live 质量 API PASS |
| P2 接管事件 | `conversation_quality_events` + `/v1/quality/outcomes`；`channel_event`/`console_mark`/`api` 三来源 | 事件幂等；渠道/控制台先接 API，不推断 | 6 条质量判据；live console_mark 路径 PASS |
| P3 FTS5 倒排 | `knowledge/fts_index.py`；可见性/标签/分类过滤；reconcile；大语料 hybrid 走 FTS5 | 无新依赖；索引持久化在仓内 knowledge 目录；失败回退内存词法 | FTS A/B 4 红→0；100k 构建 5.7s/查询 55ms；live index-health docs≥1 |
| P2-1 模型指纹 | `_engine_id` 纳入 model_name/版本 | 同模型复用 | A/B 1 红→0 |
| P2-1 索引健康 | `GET /audit/index-health`；`KnowledgeVectorIndex.health()` | 只读文件/向量/引擎/坏分片 | 单测＋live PASS |
| P2-1 周期维护 | `maintenance.py`：启动周期循环（默认 3600s）；`POST /audit/reindex`；repo/vector maintainAll | 周期增量自愈；全量重算显式 force | A/B 5 红→0；live 循环已启动、reindex 200 |
| P2-2 规模 | 辅助路候选上限 10k；手工探针 | 大语料 BM25/FTS 只看主索引候选；小语料不变 | A/B 1 红→0；规模读数见下 |

### 13.2 验证读数

- **最终宽域回归：996 passed**（知识库全量 + 质量 + 知识 API + 渠道接管 + 索引任务生命周期 + 控制台回归，288s；
  首轮 3 处陈旧判据已修：迁移版本断言、渠道管理器单例构造、v2 图谱工作区路径）。
- **定向追加**：ANN 真后端/未归因 token/MQTT 接管/质量 API 等判据随宽域一并通过；
  前端质量契约 + 组合式 + i18n + 管理员分析页 34 passed，`vue-tsc --noEmit` 通过；
  全量前端 **2165 passed、0 failed**（2 skipped；此前 duplicate-function 台账 ×2 已随生成脚本重写，
  `skillEvo.adopt*` 11 语言键已补齐）。
- **A/B 全部 `AB_PASS`**：batch1 5→0；检索 5→0；生命周期 5→0；评估/采纳/指标 6→0；身份 2→0；TTL/自动反馈/指标/索引健康 12→0；主源+补充源 lineage merge 1→0；周期维护/全量重算/辅助路上限 5→0；token 归因/content_filter 拒答 3→0；turn_id/检索阶段/引用归因 4→0；FTS5 4→0。
- **渠道全量：695 passed**（含飞书服务台/微信客服接管、MQTT 事件、回调选实例与 EventDoor 形状守卫）。
- **采纳重排定向：49 passed**；红自证把权重临时改中性后 2 条行为红（success 未升权、failure 未降权导致最终 top-2 从 `k1,k4` 变 `k1,k2`），恢复后转绿。
- **entry 反馈/token 合并判据：62 passed**（repository 三态/注入持久化、文档重排、
  entry 检索/生成分表、文档 citation、entry 审计端点）。
- **知识全量：843 passed**（378s；v18 entry 表、entry 反馈与重排纳入全量；
  仅 1 条 teardown 守卫 error，来自并发会话遗留在仓根的 `.tmp_liveLegacyGuard.py`，非本改动）。
- **最终 live-verify**：TTL archiving、自动反馈、reindex、索引健康、指标、token 表均 PASS；
  飞书服务台 webhook 与微信客服 webhook 各真打一次，`takeover_events=1 source=channel_event`；
  仓内 `knowledge_facts.db` md5 前后一致；v14 迁移在真实 `create_app` 中可应用。
- **规模读数**：aux cap 合成探针 1k/10k/100k→526.6/463.8/1,021.5ms；FTS5 手工探针 1k/10k/100k/1M 构建 477.6/585.7/5,717.4/58,416.8ms、查询 0.8/4.8/58.3/577.6ms；
- **ANN 部署**：hnswlib 已进基础 `requirements.txt` 与 `requirements-full.lock`（Docker builder 带 build-essential）；代码仍保留 faiss 探测与未装回退。
  ANN（hnswlib 0.8.0，dim=32）手工探针 10k/100k/1M 构建 125.2/1,929.0/52,481.5ms、查询 0.14/0.24/0.41ms、与精确内积 top-10 召回 1.0。
- **清理**：`.tmp_kb*` 探针与隔离数据根已删；永久规模探针保留。

### 13.3 已按推荐方案落地的四项（含 D5–D10 拍板后收尾）

- **人工接管率（D5 甲）**：事件账/API 之外，控制台会话页已接接管开关
  （`console_mark`，刷新后从 `GET /v1/quality/sessions/{id}/takeover` 恢复状态）；
  渠道侧 `ChannelAdapter.humanTakeoverEvents` 能力位随渠道状态读数报出，
  有原生事件的适配器经 `ChannelManager` 统一写 `channel_event`，无能力的渠道标 False，
  不伪造事件。三条原生 producer 已接：MQTT 协议事件、飞书服务台
  `ticket.stage 1→2`（关闭态结束）、微信客服 `session_status_change`
  （change_type 1/4 开始、2 转接、3 结束；回调解密 + sync_msg）；
  钉钉/Telegram/Discord 等没有原生事件，保持 False。质量 metrics 与管理员分析页
  都读这份读数。率仍按会话去重，来源覆盖单列；未覆盖不等于 0。
- **一般拒答率（D6 丙）**：`TurnOutcome` 六态分类不变；`tool_failure` 只接受显式
  `turn_outcome` 声明（执行链崩溃的工具记录），普通 `success=False` 不整轮判失败；
  `POST /turn-outcomes` 以 `explicit_api` 来源写事件，指标按 turn 去重且显式优先。
  `handoff` 维持 D7 乙：接管事件单列，不改写轮次 outcome。
- **token 归因精度（D8 甲 / D9 乙）**：`lineage_id` 作为结构化 `fact_id`；回答 citation
  抽成 `knowledge_citation_ids` 随 assistant metadata 落盘，生成归因走
  “引用优先→加权→均分”。检索 token 用 tiktoken 模型编码器；非 OpenAI 模型回退
  `cl100k_base` 并标 estimated，tiktoken 缺席再回退 jieba。检索阶段的模型名随
  `knowledge_retrieval_tokens_model` 落账，不与生成阶段模型混用。文档条目无 fact lineage 时
  走 v18 `knowledge_entry_usage` 分表（检索/生成），轮总量加 `entry_attributed_tokens`；
  只有真正无法映射 entry id 的 token 才进 v17 `retrieval_unattributed_tokens`。
  逐条检索成本仍是估计，不冒充 provider 真值。
- **采纳反馈重排（P0-1 收口）**：`recordAdoption` 的三态现在回流到检索：
  `feedback_prior.py` 单一权重表（success 1.10、failure 0.60、unevidenced/无值 1.0），
  RRF 分 × 先验后在最终 top-k 前重排；候选窗 3 倍（上限 100）。
  `attachGovernance` 即使 FactSurface 关闸也带 `adoption_outcome`；适配器归一化
  保留 `adoption_outcome/base_score/adoption_prior`。注入计数与 lineage 只对最终
  注入条目记，候选窗不计。无 fact lineage 的文档条目走 repository entry 级反馈：
  `/chat/feedback` 按 `knowledge_entry_ids` 写三态，重排消费同一权重；
  v18 `knowledge_entry_usage` 分表记文档检索/生成 token，轮总量加
  `entry_attributed_tokens`，不再落未归因桶。
- **更大规模（D10 乙）**：FTS5 持久倒排之外，ANN 作为可选依赖落地
  （hnswlib 已进基础 `requirements.txt`，faiss 仍可探测；按用户内存索引、最低条数阈值、
  构建/查询失败回退 JSON 全量余弦）。开发环境已装 hnswlib 0.8.0 并实测：
  `tests/manual/knowledgeAnnScaleProbe.py` 10k/100k/1M 构建 125ms/1.93s/52.5s、
  查询 0.14/0.24/0.41ms、与精确内积 top-10 召回 1.0；live 索引健康报
  `enabled=true backend=hnswlib`。部署镜像经基础 `requirements.txt` 内置 hnswlib；
  外部搜索服务不采用。

### 13.4 闭环复核（写入 → 读取 → 反馈 → 再写入）

| 链路 | 写 | 读 | 反馈/再写 | 状态 |
|---|---|---|---|---|
| 人工接管 | 控制台 `console_mark` / MQTT 协议事件 / 飞书服务台工单 / 微信客服 `session_status_change` / API | 会话状态 GET、质量 metrics、渠道能力位、管理员分析页 | 按钮刷新恢复；metrics 按会话去重 | **闭**（三条原生渠道已接；无原生事件的平台标 unsupported） |
| tool_failure | 执行链崩溃的显式 `turn_outcome`；显式 API | quality metrics、assistant metadata | 显式 API 原地改判并优先于自动分类 | **闭**（普通 `success=False` 不猜） |
| 引用归因 | `<memory_citation>` 句柄 → `fact_id` | 生成 token 归因 | 归因写回 fact usage | **闭**（无 citation 的轮次走加权/均分） |
| 检索 token | 运行模型 tokenizer → fact/entry 分表 + 未归因桶 | `/v1/quality/metrics` 的 token_usage | 有 lineage 摊 fact，文档摊 entry；真无法映射才进 `retrieval_unattributed_tokens` | **闭** |
| 采纳反馈重排 | 点赞/纠错 → fact 或 entry `adoption_outcome` | `feedback_prior` 权重 → RRF 重排 → 最终 top-k | 下一次检索按 success/failure 升降权 | **闭（事实＋文档）** |
| 可选 ANN | 基础部署依赖内置 hnswlib + 按用户建索引 | `vector.search` / `/audit/index-health` | 构建失败回退 JSON 并报 `failed_users` | **闭**（1M 实测；未装环境自动回退） |
| 周期维护/事件账 | 启动周期任务 + 质量事件连接 | 索引 health / 质量 metrics | 关停取消任务、关闭事件账 | **闭**（本轮补：`kb_index_task` 句柄与 `reset_quality_store`） |

**剩余留口（不伪装成已闭）**：

- 钉钉/Telegram/Discord/QQ/SIP 等适配器没有可接的平台原生接管事件，
  `human_takeover_events` 为 False，并随渠道状态/质量 metrics 报
  `unsupported:no_native_event`；这些渠道仍靠控制台/API 标记，设计上按能力接。
- 文档条目已有 entry 级三态与 token 分表；缺 `knowledge_id` 的旧条目在装载时
  用内容指纹补 `legacy-*` 稳定 id，不再永久无法反馈/归因。
- ANN 已实测并进基础部署依赖；未安装 hnswlib 的环境仍走 JSON 全量余弦（功能不减，大语料变慢）。
- 前端此前的 3 条既有红已清零：`skillEvo.adopt*` 补齐 11 语言键，duplicate-function 台账按生成脚本重写；全量 2165 passed、0 failed。

### 13.5 提交账

- 生产：**17 改＋9 新**；测试：**7 改＋12 新**；fixtures **2 新**；手工规模探针 **2 新**；审计/设计文档 **2 新**（以上为 D5–D10 前口径）。
- D5–D10 追加：`neurova/quality/*`、`neurova/api/endpoints/quality.py`、`neurova/knowledge/vector_ann.py`、
  `neurova/knowledge/token_count.py`、基础 `requirements.txt` 的 hnswlib、前端 quality API/组合式/接管按钮与文案、
  管理员分析页质量读数、MQTT/飞书服务台/微信客服三条接管 producer、微信客服回调解密与
  `sync_msg`、v17/v18 token 账、`feedback_prior` 采纳重排、entry 级反馈与
  `/audit/entry-feedback`、常驻探针 `tests/manual/knowledgeAnnScaleProbe.py`；
  另补生命周期/能力位/MQTT/飞书/微信客服/ANN/未归因/采纳重排/entry 判据。
  提交前以 `git status` 与 hunk 归属重新点数。
- 建议 8–9 笔：检索三票、生命周期/TTL、采纳/自动反馈、评估/指标、token/拒答、周期维护/规模、质量事件、FTS5、审计/设计文档；共享文件（`chat_pipeline.py`、`post_chat_pipeline.py`、`app.py`、`console.py`、`api/endpoints/__init__.py`）提交前按 hunk 核对归属。
- 工作树仍含并发会话在途改动；本批只对上述知识域/血缘/质量链路负责。
- 渠道原生接管/ANN 基础依赖收尾：`92da4050`（已推 CNB）。
- **D5–D10 追加落点**：`neurova/quality/*`、`neurova/api/endpoints/quality.py`、
  `neurova/knowledge/vector_ann.py`、`neurova/knowledge/token_count.py`、
  基础 `requirements.txt` 的 hnswlib；前端 `NeurUI/src/api/modules/quality.ts`、
  `NeurUI/src/composables/useHumanTakeover.ts`、`ChatPage.vue` 接管按钮与 11 语言文案；
  渠道能力位 `ChannelAdapter.humanTakeoverEvents`。提交归属仍需按 hunk 与并发改动分开核对。
