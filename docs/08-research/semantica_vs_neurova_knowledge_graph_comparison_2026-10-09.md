# Neurova × Semantica 代码级对比（2026-10-09）

> **对象**：https://github.com/semantica-agi/semantica （README/搜索面标称 10k+★；MIT License；
> 版本 `0.7.0`；Python 3.10–3.13；`pyproject.toml:61` 把 `rdflib` 列为**核心**依赖）。
> 克隆快照 commit **`746dc63544397e61d26b5e636340683a37db9fc1`**（2026-10-08 19:07 +0500，
> 提交标题 `fix(context): index Decision objects passed to add_decision (#1954) (#1955)`），
> 浅克隆于 `$TEMP`（**未进本仓工作树**），全量检出。下文对方锚点相对该 commit，`semantica/` 为其内层包。
> **本方基线**：`neurova/knowledge/`（含 `foundation/` `ontology/` `identity/` `rerank/` `evaluation/`）、
> `neurova/cognitive_layers/knowledge_graph/`、`neurova/cognitive_layers/memory_layer/`（TKG 与图遍历）、
> `neurova/agent/*retriever_adapter*.py`、`neurova/api/endpoints/knowledge*`、
> `NeurUI/src/modules/knowledge/`。
>
> **文档定位**：研究参考类，仅作背景，**不可作事实源**（`AGENTS.md` §2 原创性与自主性条款）。
> 本文**不授权任何代码搬运**——即便对方是 MIT，§2 也禁止引用、模仿或对齐第三方实现。
> 文中「对方有 X」只用于**提问**，不用于**规定本仓怎么做**；所有候选项（§6）的立项理由
> 一律写成本仓自身可核实的断点或缺口（§5），并区分「净接/净删」与「新能力」两类，不混批。
>
> **证据分级**：本仓侧 §5 每条锚点由主代理 `grep`/`Read` **亲验**（清单见 §8）；
> 对方侧锚点由六路只读子代理在同一克隆内实读，主代理只抽验了影响结论方向的四条
> （见 §8 三态表），**未逐行复算**。行号会随对方推进而漂移，复核请锁 commit。

---

## 0. 一页结论

1. **形态判断先于功能判断**：对方是**图谱构建工具链**（library + CLI + Explorer SPA + MCP），
   本仓知识库是**产品内的单一事实源**。对方把「接什么后端」当第一性问题（Neo4j/FalkorDB/AGE/Neptune
   四选一），本仓把「谁写谁读、写完谁反馈」当第一性问题。这两个取向各自内部自洽，
   **不能按"对方功能多"直接换算成本仓缺口**。
2. **对方 22.4 万行里约三分之一是"账面功能"**：六路子代理独立报出的同一形态是——
   检测/推理/校验/融合的代码写得完整，**但调用点缺失或结果被丢弃**。
   最典型的三处：`kg/graph_builder.py:1047-1069` 跑完冲突检测与裁决后**只记计数、结果整份丢掉**；
   `ontology/ontology_validator.py:340,381-382` 的一致性/可满足性是 `pass`、
   `check_constraint()` **无条件 `return True`**（主代理亲读原文）；
   `evals/` 与 `benchmarks/` 有 `objective/threshold/expect` 判分与 flaky 检测，
   但 `.github/workflows/benchmark.yml:76` 指向一个**不存在的文件**，注释自认"real invocation 就挂"。
   这条与 dramaclaw 那次是同一条教训的复现：**「有校验代码」≠「有质量闸」**（§7）。
3. **对方 HEAD 就是一个"文档路径静默空转"的活证**：`746dc63` 修的正是
   `add_decision(Decision对象)` 只落了节点、没注册四个派生索引，于是判例检索/影响分析/因果链/洞察
   四条 documented 主入口全部看不见这条记录，此前只有 `to_dict/from_dict` 回环路径被测到过。
4. **对方的"混合检索"其实只有一条路**：`vector_store/hybrid_search.py:400-435` 是
   向量召回 + 元数据后过滤（over-fetch `k*2`/`k*4`），RRF 融合函数存在（`:181-219`，主代理亲读）
   却**没有词法路可融合**——`grep bm25|tfidf|fts5|lexical` 在 `semantica/vector_store/*.py` 零命中。
   且 RRF 用 `result["score"] = score` 把原始分覆盖掉、跨路同 id 靠 `result_map` 后写覆盖前写。
   **本仓四路（tfidf/bm25/fts/vector）在此维实质领先。**
5. **本次对比抓出本仓五条自有断点**（每条与本仓代码独立成立，与对方有无实现无关）：
   推导事实不带时效窗口且到期巡检无触发点、`purge=true` 端点承诺"物理删除整条"但权威库里删不掉、
   检索评估台架建表建端点却**从未在生产数据根上跑过一次**（`data/knowledge/` 无评估库文件）、
   投影漂移只能人工按需探、抽取断言的 `actorType` 恒为 `"pipeline"` 使置信度来源不可分。见 §5。
6. **反向也要记账**：本仓在单一事实源、咽喉写入口、逐跳溯源+哈希链、有符号推导撤销、
   四路词法+向量融合、评估历史落盘、测:源比 1.0:1 这七处**不低于或高于**对方（§4）。
7. 本文只出报告与候选清单，**未改任何代码**。候选 K1–K7 待拍板（§6）。
   与 [[feedback-audit-report-only-first]] 咬合：未点单前不动码。
   **2026-10-09 当日追记**：用户点单 **K2（断点 N2）**并拍定不可逆点为「擦正文、留链与哈希」，
   已落地为 `a0316ec0`（判据入受保护子集 `9c710d31`，台账 **§6-101**）。落地时的复算把本文
   N2 那格的三处旧述就地改判：条目权威早已在 SQLite `knowledge_narratives`（不是"只删 JSON 层"，
   而是"只删了条目这一面"）、知识域**没有** fts5 影子表（那条清理纪律只适用于 `memories_fts`
   与 `evicted_fts` 两个记忆面）、端点此前连 `purge_knowledge` 的返回值都没读（比"折成一个 bool"
   更弱）。**同日第二笔追记**：用户又点单 **K1（断点 N1）**，在"推导继承窗口"与
   "给到期一个真触发点"之间选了后者，已落地为 `537f805b`（判据入子集与本批同笔登记，
   台账 **§6-103**；提交正文原写 §6-102，与并发会话撞号后按"先入库者保号"顺移，勘误记在台账）。
   剩余未点单：无（K4 已按用户裁定处理，见下）。
   **同日第四笔追记**：**K4** 走"先跑一次 rebuild 清账、不接运行期"——实测缺账 0、
   有账无据 52 条，重建后归零并逐格核对磁盘终态；复算另抓出三格（探针看不见 33 个无据
   孤立节点、`_save` 吞下落盘失败仍报 success、N6 原判被推翻），全文见台账 §6-106。**同日第三笔追记**：**K3（断点 N3）** 已按「真库跑一次取读数 +
   合成夹具做闸」落地为 `c6b175a8`（台账 §6-105）。

**逐维对照结论（10 分制，仅覆盖本文比到的六维；分值为本文判断，非工具产出）**

| 维度 | Neurova | Semantica | 差在哪（一句话） |
|---|---|---|---|
| 写入口唯一性与咽喉纪律 | 9 | 4 | 对方多写入口且结果丢弃；本仓 `admission.admit()` 单喉 |
| 溯源与可审计性 | 8 | 6 | 对方粒度到 chunk/属性级且有 W3C PROV-O 序列化，本仓到 entry/轮次但有哈希链与逐跳缺口声明 |
| 检索融合质量 | 8 | 5 | 本仓四路真融合，对方单路 + 后过滤 |
| 时效模型（bi-temporal） | 5 | 8 | 对方有 valid/transaction 双轴 + as-of 重建且**不依赖后台清扫**；本仓双列已落库但到期推进无人调 |
| 遗忘/擦除的诚实性 | 4（对比时点；`a0316ec0` 起逐面回执，本文不再自评新值） | 8 | 对方 `ErasureReceipt` 五态 + 顺序化级联；本仓 `purge` 当时只覆盖一处存储却对外宣称整条删除 |
| 外部服务足迹（越少越好） | 9 | 3 | 对方四个图后端全部要求外部服务、默认后端是服务器；本仓零外部服务、单文件 SQLite |

---

## 1. 体量与形态

**对方**：`semantica/` 内层包 **421 个 .py / 224,381 行**（主代理亲算，`git ls-files`+`wc -l` 口径）；
`tests/` **471 个 .py / 171,331 行**，测:源比 **0.76 : 1**。28 个子包。
另有 `explorer/` 前端（React 19 + Vite + sigma/graphology + Monaco + vis-timeline）、
`cookbook/`、`docs/`（95 个 .md）、`integrations/`（agno/crewai/google_adk）、两个 MCP 面。

**本仓同域切片**（子代理口径，主代理未整域复算）：`neurova/knowledge/` 12,376 行、
`cognitive_layers/knowledge_graph/` 1,249、memory_layer 图族 2,082、KB API 面 2,414、
agent 适配器 859、经验库 884、嵌入+向量 1,679 ⇒ **域内约 19,400 行**；
测试侧 109 个文件引用该域 / 18,481 行 ⇒ **测:源比约 1.0 : 1**，`neurova/knowledge/` 内部 0.91 : 1。

**结论口径**：对方在这条功能族上的**源码规模约为本仓同域的 11.6 倍**，但**测:源比低于本仓**。
且那 22.4 万行里有相当比例是"每个后端一份驱动"——`graph_store/` 的 Neo4j 1,114 / Neptune 1,802 /
AGE 1,343 三行即约 4,259 行是同职能的平行实现，按 §7 单看即本仓纪律会判未闭环。
**所以"对方 11 倍"不等于"本仓缺 11 倍的工作量"**，本仓的倍率优势恰在"一处实现被消费"。

**存储足迹**（主代理亲验）：`grep -rn "sqlite\|parquet\|duckdb\|rocksdb" semantica/graph_store/*.py`
→ **零命中**；无 `ABC`/`abstractmethod`，后端靠方法名约定鸭子类型，能力探测退化为类名字符串嗅探。
默认后端是服务器（`graph_store.py:560` neo4j / `triplet_store.py:52` blazegraph）；
唯一免外部服务的路径是 `oxigraph`（需额外可选 wheel）与 `jena` 端点为空时的 rdflib 内存 Dataset。
本仓 `docs/specs/2026-09-20-knowledge-foundation-design.md:11` 明确**禁止外部服务**——这是取向差异，
不是本仓短板。

---

## 2. 功能全貌（代码级，按层，附接线状态）

下表"接线"三态含义：**活** = 有非测试消费方且在本仓抽验范围内可达；
**CLI** = 仅命令行可达，无 HTTP/流水线消费方；**测试/孤** = 只被 `tests/` 或文档引用。

### 2.1 摄入与切块（`ingest/` 29,066 · `parse/` 7,948 · `split/` 4,703）
- 源面极宽：文件（PDF/DOCX/PPTX/HTML/CSV/JSON/Excel/XML）、网页与 RSS、六种数据库、云、
  四条流（Kafka/RabbitMQ/Kinesis/Pulsar）、Git/邮件/MCP/Parquet。
- 切块是本层最有含金量的部分：**默认 `recursive`，chunk_size 1000 / overlap 200**（`split/splitter.py:65,95`）。
  `split_entity_aware`（`methods.py:861`）先跑 spaCy NER 取实体字符边界，再按正则句子贪心装箱、
  **含实体边界的句子拒绝切断**（允许超 chunk_size）；`split_relation_aware`（`:999`）同理但保护
  subject–object 整跨度；`split_graph_based`（`:1159`）建 networkx 图按 **Louvain 社区**或中心度分区，
  再取实体 ±100 字符拼接（`text.find(chunk_text[:50])` 重定位是有损的）。
  `split_ontology_aware`（`:1354`）是**桩**：记一行日志后转调 `split_entity_aware`。
  所有 KG 系切块**异常时静默降级为 `split_recursive`**（`:881,:992,:1347`）。
- 每个 chunk 带 `start_index/end_index` 与 `parent_chunk_id`（`split/provenance_tracker.py:57-68`）。

### 2.2 归一（`normalize/` 6,303）
全确定性规则+词典，无学习成分。`DateNormalizer` → dateutil → UTC → **ISO 8601**；
`NumberNormalizer` 处理千分位/货币/百分号/K-M-B-T/科学计数；
`EntityNormalizer` 仅 `strip/压缩空白/Person 才 .title()` + 小写别名表；
`AliasResolver.map_variants` 与 `handle_cultural_variations` **原样返回入参**（`entity_normalizer.py:291-327`）。
`DataCleaner` 内建 Jaccard 分组去重（`data_cleaner.py:282-545`）——即"廉价预去重层"。

### 2.3 抽取（`semantic_extract/` 14,796）
- 同一职能**多后端可选**：实体 `pattern|regex|rules|ml(spaCy，默认)|huggingface|llm`；
  关系 `pattern|regex|cooccurrence|similarity|dependency|hf|llm`；三元组默认 `method="pattern"`。
- LLM 路径是 **Pydantic 结构化 + 报错回喂重试**：`llm.generate_typed` → `model_validate`，
  `ValidationError` 文本追加进提示重试（`providers.py:685-702`），非平铺的"分类字典"输出**整形回收**
  而非丢弃（`:604-683`），超长则**折半重试**（`methods.py:1400-1418`）。
- **多后端共识投票**：`merge_strategy=fallback|union|consensus` + `min_votes`/`min_agreement`/
  方法权重/跨度 IoU≥0.5 聚类（`ner_extractor.py:96-107,283-368,1053-1130`）。
- **置信度带来源类型**：`types.py:14-18` `confidence_source ∈ model|heuristic|type_similarity|unavailable`，
  未知不被静默当 0（`named_entity_recognizer.py:311-315`），模型自报默认 0.9 也照样带标记（`schemas.py:12`）。
- 反向警示：`EventDetector` 默认 `method="llm"` 但实现是 **5 组硬编码正则**（`event_detector.py:110-117`），
  "llm" 只透传 ner 参数；`ExtractionSchema`/`SchemaValidator`（ ontology domain/range 门）**零生产消费方**。

### 2.4 冲突、去重、变更（`conflicts/` 4,997 · `deduplication/` 4,634 · `change_management/` 2,115）
- 冲突类型五种（VALUE/TYPE/RELATIONSHIP/TEMPORAL/LOGICAL，`conflict_detector.py:68-76`），
  **全确定性**，域内 grep 无 LLM/embedding 命中。时序判据靠硬编码属性名清单 + 年份正则（`:841-850,:954`）。
- 裁决有五种策略，默认 `voting`：`Counter` 多数表决取"票数/总数"当置信度（`conflict_resolver.py:405-411`），
  或 `source_confidence × tracker.get_source_credibility(doc)` 取 argmax（`:440-467`），或纯 recency。
  每 `(实体, 属性)` 可登记裁决规则，但**只在调用方未显式传策略时才生效**（`:246-251`）；
  无领域级策略；**裁决结果不回写、败方不留墓碑**，未决只返 `resolved=False` 加一个 flag，
  冲突仅存 RAM 且在 `:1420` 被清空。`SourceTracker` 到 document/page/section 粒度（无字符偏移），
  可信度**只能人工设**、未知文档默认 0.5——尽管 `__init__.py:42` 写着"基于历史准确率"。
- 去重：**无 MinHash/LSH**，用 token 前 4 字符分桶 + 可选 Soundex + 类型键（`similarity_calculator.py:651-692`）；
  加权四因子（串 0.6/属性 0.2/关系 0.2/**embedding 默认权重 0.0**）；阈值 `0.7/0.6`，关系 `0.9`；
  **类型不符直接把置信度钉成 0.0**（结构否决，`:774-787`）；DSU 传递闭包分组，簇大小 2–100。
  合并默认 `keep_most_complete`，边按 (subj,pred,obj) 求并集，留 `merged_from`，**不可逆**
  （grep `undo|unmerge|rollback` 零命中）。
- 变更管理：**不是 bi-temporal**（该域 grep `valid_from|bitemporal|as_of` 零命中）；
  整图 JSON 快照 + SHA-256 校验 + 追加式 `mutation_log`；删除只留一行日志、无软删列；
  `restore_snapshot` 是破坏性全覆盖（需 `require_confirmation`）；`prune_versions(keep_last_n=5)` 删历史；
  **无真值维持**：仅一句"检查依赖链"的提示字符串（`change_log.py:263`）。

### 2.5 图谱构建核心（`kg/` 18,504）
- `GraphBuilder` 输入宽（裸串/对象/dict），输出**普通 dict** `{entities, relationships, metadata}`；
  id 不自造（信任传入 id，否则 `str(hash(...))` 兜底），`merge_entities` 默认 **False**；
  单线程无锁，实例态在 `build()` 里重置。
  **持久化整段靠注入的 `graph_store`，而生产调用点从不注入**（`core/orchestrator.py:164` 只传 `config=`）
  ⇒ 实跑路径**纯内存**；`load_from_neo4j` 只读，**没有 `save_to_neo4j`**。
- `BiTemporalFact`（`temporal_model.py:27-66`）双轴：valid(`valid_from/until`) + transaction
  (`recorded_at/superseded_at`)。`apply_revision`（`temporal_query.py:1397-1495`）**不删**：
  旧事实置 `superseded_at`、盖 `role: superseded` 溯源、克隆 `__rev__` 兄弟行；
  `reconstruct_at_time/query_at_time` 可按任一轴 as-of 重建（`:107-209`，O(V+E) deepcopy），
  **正确性不依赖任何后台清扫**。`find_temporal_paths` BFS + 因果序（最坏指数，visited 集使其取最优单路）。
- 置信度是普通字段：合成端点**硬编码 0.8**（`graph_builder.py:264`）；`kg/` 全域 grep `decay` 零命中
  ⇒ **无衰减、无因矛盾而降权**；冲突只记日志。
- 更新是**每次全量重建**：grep `reindex|upsert` 零命中，"incremental" 只存在于 docstring。
- `schemas/` 目录**只有一份 JSON Schema 且零加载器**——快照校验另写了一套手搓字段→类型 dict（`:1518-1559`）；
  `build()` 从不调 `GraphValidator` ⇒ **抽取三元组进图前无任何校验**。

### 2.6 本体与推理（`ontology/` 9,474 · `reasoning/` 6,542）
- 本体是**内存 dict，无落盘**；OWL/RDFS 靠 f-string 模板生成，SHACL 亦手写 Turtle/JSON-LD/N-Triples 三套序列化，
  再交给外部 pySHACL 执行（`ontology_validator.py:194-199`）。SKOS **只读不产**。
  本体来自**统计归纳**（类型频次 ≥2、属性 50% 出现率、名称前缀猜父类，`class_inferrer.py`），
  LLM 生成是另挂的 `LLMOntologyGenerator`（提示词 3 行，`llm_generator.py:70-75`）且**零生产消费方**；
  人审只以 `{"draft": True}` 约定存在，真正的 approve/reject/publish 在 explorer 路由里。
  `OntologyValidator` 是占位（见 §0.2），真校验在 `OntologyQualityGate`（阈值化打分，**不阻断写入**）
  ——而后者本身也是**测试/孤**状态。`vocabulary/` 仅一份 25 词的 TTL，加载方**只有测试**。
- 六个推理器并存（本仓 §7 视角即"同一功能第二份实现"）：
  `Reasoner`（字符串规则 `IF P(?x) THEN Q(?x)`，正则解析，**迭代上限 50 而非不动点证明，无否定**）——
  唯一走 HTTP 的那个（`explorer/routes/enrich.py:343`）；
  `DatalogReasoner` 是**真 semi-naive 不动点**（`datalog_reasoner.py:262`），仅 CLI 可达；
  `ReteEngine` alpha/beta/terminal 网络齐全但**只匹配不回写**，且把结论模板原样返回（未实例化，`:629`）；
  `AbductiveReasoner` **不搜索**，打分是常量 `return 0.5` / `return 0.8`（`:267,:380`）；
  `SPARQLReasoner` 的 `RDF.type` IRI 拼错（`:937` 写成 `1999-02-22`），**测试里复制了同一个错**所以恒绿；
  `GraphReasoner` 是一次 LLM 调用，无逻辑。
  对比本仓：本仓是**分层的、带否定的前向链 + 不动点 ≤10 轮 + 推导账本记 `rule_version` 与 stratum**
  （`ontology/rule_engine.py:199-251,285,309,425`、`derivation_ledger.py:26-38`）——
  对方的 `TruthMaintenanceSession` 反而**明确拒绝递归与环**（`_truth_maintenance_validation.py:194,258`），
  靠"替代论证集 + 拓扑序重推导"维持真值，检查点**从不持久化推导事实**（`truth_maintenance.py:216`）。
- 解释：`ExplanationGenerator` 只出**一跳扁平路径**（`:187`），NL 靠 f-string 模板，**无落点存储**。

### 2.7 溯源与完整性（`provenance/` 3,808）
- 单层扁平 `ProvenanceEntry` 映射 PROV-*（`schemas.py:36`），导出时才具化为 Agent/Activity/Invalidation。
  存储有内存与 **SQLite（WAL）** 两种，**一张 `provenance` 表**。
  粒度做到 doc → chunk → entity/relationship/property，**带 `start_index/end_index` + `source_quote`**
  （比本仓 `entry:<kid>` / 轮次锚点更细一层）。
  **非自动**：全靠调用方套 `XWithProvenance(provenance=True)` 包装器；
  五个 `*_provenance.py` 包装器（extract/normalize/export/visualization/pipeline）**均无生产消费方**。
- 完整性（`integrity.py:27`）：字段拼接 SHA-256 + `sequence_id`/`previous_checksum` **单链**，
  `verify_chain` 可查就地改与删行；**无签名、无 Merkle、无外部锚定**；且**故意排除 `entity_id`**（`:45-55`）。
  本仓的 `digest_chain.py:29` + `ActivityDigestChain.verify` 是同构物，且本仓把它接到了写收尾（见 §4.3）。
- `bridge_axiom.py` 桥的是**跨学科数值换算**（`output = input × coefficient` 带 DOI/页/引文，
  L1→Ln 传递链），与图谱分层无关——命名容易误读。

### 2.8 上下文与决策层（`context/` 26,362，对方的招牌）
- `ContextGraph` 是**纯内存 dict + JSON/Markdown 双落盘**（原子 tempfile+`os.replace`+`fsync`），
  **本层零 SQLite**。节点/边**一律带 `valid_from/valid_until`**，边用内容哈希定 id 使"改时效窗口不 mint 新 id"
  （`context_graph.py:475-499`），有 `state_at(ts)` 全图回放、**retract 与 purge 是两个不同操作**、
  墓碑按 `(kind,id)` 键。
- 决策被**具体化为图中枢纽**：一条 `record_decision` 扇出 decision 节点 + 每个实体一个 `involves` 节点 +
  类别节点 + 作出者节点，异常时对已写节点/边做**补偿回滚**（`:5118-5127`）。
  因果只有三值 `CAUSED|INFLUENCED|PRECEDENT_FOR`；调用方断言的边是"真"，
  共享实体+早于时间戳推出来的 `influences` 边**显式标注为附加启发**并去重（`:4855-4896`）；
  全路径枚举 + 每路径独立判环 + 截断时返回**自描述 `{"truncated": True}` 哨兵**（`:4918-4934`）。
- 相似判例检索是**词面 Jaccard**（`:5453-5505`，CJK 走字符二元回退），
  `use_semantic_search=True` 参数**从未被读**；`find_similar_nodes` 文档承诺三种 similarity_type、
  只实现两种，`"embedding"` 静默落进 content 分支。
- 装配与融合：`context_retriever.py:996-1180` 先**按来源分组各自 min-max 归一**再按 `hybrid_alpha`（默认 0.5）
  混合、记忆路固定乘 0.3、跨源印证 +20%、可选第二趟向量重排（0.7·score + 0.3·cosine）；
  token 预算在 `drift_search.py`/`global_retriever.py`；锚点跳数衰减 `proximity_score = 1/hop`
  **默认权重 0.0 即关闭**（`agent_context.py:885`）。
- **本层的溯源是断的**：`_track_decision_provenance` 只把 `source_documents` 传给 ProvenanceManager
  且**两处调用点都传空列表**，注释写"could be enhanced"（`agent_context.py:1742`、
  `decision_methods.py:71`）；`graph_schema.py:370-372` 声明了 `DERIVED_FROM/INFLUENCED_BY/BASED_ON`
  却无一处写；`context_provenance.py` 里 import 了一个**不存在的 `context_manager` 模块**，导入即抛。
- `ErasureReceipt` **五态**（`erased/not_found/not_configured/unsupported/failed`，`erasure.py:66-79`），
  按向量→记忆→图顺序级联、**持久墓碑最后写**，对无删除能力的 FAISS/Milvus/Weaviate 如实给 `complete=False`；
  `check_compliance` 把"判为不合规"（返 False）与"**无法评估**"（抛 `ProcessingError`）分开——
  缺证据即按策略判不合规（`policy_engine.py:391-404`）。
- 接线：`ContextGraph` 与全局/drift 检索器经 CLI、MCP、explorer、四个 agent 框架集成可达；
  `TruthMaintenanceContextFilter`、`TrustTier`/`TierCalculator`、`graph_schema.setup_decision_schema`、
  `DecisionContext`、`capture_decision_trace`、`create_policy_with_versioning`
  **非测试消费方为零**（注：`setup_decision_schema` 的 Cypher 还只认 Neo4j）。

### 2.9 存储、评测、对外面（`triplet_store/` 6,313 · `graph_store/` 7,885 · `vector_store/` 12,615 ·
`pipeline/` 3,970 · `evals/` 967 · `benchmarks/` 1,889 · `export/` 11,956 · `explorer/` 9,952 ·
`visualization/` 6,524 · `mcp_server/` 1,061 · `seed/` 1,151）
- 三元组后端五种（blazegraph 默认/jena/rdf4j/anzo/oxigraph），图后端四种（neo4j 默认/falkordb/age/neptune）。
  n-hop 遍历在**各后端各自实现**里（Neo4j 变长 Cypher `-[r:TYPE*1..depth]-`，AGE 裸 SQL），门面不拥有遍历。
- 评测：14 个判分器（含 `rouge`、`token_f1`、`llm_as_judge`），`objective{direction,threshold,expect}` 把分数变裁决，
  `evaluate_repeated(runs=10)` 出 `stable_pass|flaky|stable_fail`。数据集只有 6 条**自认"不是真基准"**的样本，
  hotpotqa/musique/locomo 是**适配器**（不下载，要用户给本地文件）。`mem0/graphiti/cognee` 对比系统
  注释自认 **"not exercised in CI"**。**结果是内存 dataclass，由 CLI 写成 JSON/Markdown 文件——没有任何历史表**。
- 管道是 Builder DSL + 拓扑分层执行，有重试与并行契约（确定性错误不重试）、合并冲突检测；
  **无持久化、无幂等、无 checkpoint、无死信/熔断**（grep `idempot|checkpoint|quarantin|dead_letter|circuit_breaker` 零命中），
  `pause/resume/stop` 只翻标志位；顶层 `execute_pipeline` 捕获后**返回 `success=False`** 而非抛。
- 导出面确实是对方最强的一块之一：Turtle/RDF-XML/JSON-LD/N-Triples/N3、OWL/XML 与 OWL 2 限制、
  OWL-Time 双时间轴、GraphML/GEXF/DOT、Parquet/Arrow、Cypher CREATE、Arango AQL、Neo4j 导入 CSV、
  HTML/Markdown 报告、给 GNN 的 JSONL 距离集；置信度作为规范 `xsd:decimal` 落 RDF。
  **PROV-O 的 RDF 不在 `export/` 而在 `provenance/manager.py:1240-1256`**（README:94 的表述与此有偏差）；
  `export_shacl` 未通过 `methods.py`/`__init__.py` 暴露；决策对象不可导出。
- Explorer：FastAPI 13 个路由（graph/analytics/decisions/temporal/enrich+reason/import+export/markdown/
  memories/annotations/sparql/provenance/vocabulary/ontology≈37 子路由）+ React 19 SPA，
  含 Lineage/Decision/DiffMerge/Sparql/Ontology/Enrich 工作区；
  `/api/provenance` **逐条先验校验和、失败即退化到 2-hop 自我图遍历**（`routes/provenance.py:189-204,227`），
  再把 PROV 类映射成前端泳道。这是**真接线的、人可审的溯源面**。
- MCP：自搓 JSON-RPC stdio，**16 个工具** + 3 个资源；另有 `semantica_mcp/` 第二套 MCP 面（工具名重叠）。

---

## 3. 与本仓同域机制的逐点映射

| 机制族 | Semantica 落点 | Neurova 落点 | 实质差异 |
|---|---|---|---|
| 写入口 | 无统一喉（`kg/graph_builder` + `context` 图 + 各 `add_*`） | `foundation/admission.py:280 admit()` 单喉（7 个生产者全指它） | 本仓强，且本仓咽喉分段可判（`admission.py:40-57`） |
| 事实/断言分层 | `provenance` 单表 + `SourceTracker`（内存） | `knowledge_facts` + `knowledge_assertions`（actor/medium/hash/weight/verification_state） | 本仓更规范；对方粒度多一层字符偏移 |
| 冲突 | 五类检测 + 五策略裁决，**结果丢弃、内存态、重启即失** | `knowledge_conflicts`（severity/policy/winner 落库）+ `conflict_judge.py:210` + REST 列表与裁决 | 本仓闭环；对方在"裁决回写"这步断 |
| 时效 | 双轴 + `apply_revision` 不删 + `reconstruct_at_time` as-of | 双列已落库（`fillValidityWindow`，`admission.py:317`）但**过期靠显式调用、无人调** | 对方在架构上免掉了清扫依赖；本仓有列无推进（§5-N1） |
| 推理 | 六推理器并存，正则串规则为主，**无否定无分层** | 分层前向链 + 否定 + stratum + `retractAllDerivedFrom` 深→浅撤销 | 本仓更严；对方 TMS 拒环拒递归 |
| 溯源完整性 | 单链 SHA-256（排除 entity_id） | `digest_chain.py` 活动哈希链 + 写收尾回写 `verification_state` + `/integrity` | 同构；本仓形成写→裁→读闭环 |
| 检索 | 向量单路 + 元数据后过滤，RRF 无词法路可融 | `hybrid.py` 四路（tfidf/bm25/fts/vector）+ rerank 面 + 优先级适配器 | 本仓领先 |
| 图遍历 | 后端原生 Cypher/SQL；`kg/` BFS 最坏指数 | SQLite `WITH RECURSIVE` 标签接力 + visited 判环 + hop 上限 4（`graph_walk.py:105-136`） | 本仓零外部依赖且默认开 |
| 遗忘/擦除 | 五态 `ErasureReceipt` + 顺序级联 + 如实 `complete=False` | `retract`（可撤销不可遗忘）+ `purge_knowledge`（**当时**只覆盖条目一面） | 对方语义诚实；本仓在 `a0316ec0` 补上逐面回执与跨存储动作（§5-N2 追记） |
| 质量闸 | `evals`/`benchmarks` 判分器丰富但**无历史无 CI 门** | `evaluation/retrieval_benchmark.py` 三表 + baseline + REST 读面，但**从未跑出**（§5-N3） | 两边都缺最后一步；本仓的表结构更完备 |
| 投影一致性 | 一份 dict，投影是可选 sink ⇒ **无漂移可言** | SQLite 权威 + JSON 投影双份，`/authority-drift` 按需探 | 对方的形态说明"双份才会漂移"；本仓要的是让探变成跑（§5-N4） |
| 置信度来源 | `confidence_source` 四态枚举，未知不折 0 | 只有一列 `confidence`/`weight`；抽取侧 `actorType` 恒 `"pipeline"` | 对方把"数从哪来"显式化（§5-N5，薄差集） |
| 人可审面 | Explorer 13 路由 + React 六工作区 + 校验和退化 | `/facts/{id}/lineage` + `KnowledgeLineageDrawer.vue` + turtle 视图 + 冲突列表 | 本仓已接线；对方广度更大、深度依赖校验和自检 |

---

## 4. 本仓不低于或高于对方的七处（避免单向比较）

1. **单一事实源与咽喉**：本仓 7 个写生产者全部经 `admit()`，分段状态是**可读出的台账**
   （`admission.py:40-57`）；对方无统一写入口、`kg/` 生产路径甚至不落盘。
2. **推导账本与精确撤销**：`derivation_ledger.py:138-175` 按推导边、深 stratum 先撤，
   且 `supersede`/`retract`/`markContradicted` 三处都跟着 `_retireDerived`；
   对方 `change_management` **无任何真值维持**，只有一句提示字符串。
3. **写→裁→读的闭环**：`digest_chain.py:201,226` 在写收尾时**回写** `verification_state`
   并配受保护测试（`test_assertion_verification_loop.py`、`test_write_boundary_closes_verification.py`）；
   对方溯源靠 opt-in 包装器、五个包装器零消费者。
4. **检索融合是真的多路**：四路 + 优先级装配 + `rerank/` 面 vs 对方单路。
5. **零外部服务足迹**：一个 SQLite 文件 vs 对方 8 个后端里 6 个要服务器 + 约 16k 行平行驱动 + 注入净化面。
6. **测:源比 1.0:1 vs 0.76:1**，且本仓有 `.cnb` 流水线与受保护测试子集；对方 CI 里的 benchmark 作业自认已挂。
7. **断言级来源可查**：`medium_ref`（`knowledge_facts.py:133`，并有 `(fact_id, actor_type, actor_id,
   medium_ref, statement_hash)` 索引 `:141`）把断言钉回具体条目/轮次——
   这正是对方 `context/` 层想做却传了空列表的那件事。

---

## 5. 本次对比抓出的本仓自有断点（每条与本仓代码独立成立）

> 写法纪律：先给本仓证据，再给"对方的存在"作为提问的引子。**「对方有」不出现在理由列。**

### N1 · 推导事实不带时效窗口，且到期推进在整个仓里没有触发点（✅ 已按 ② 闭环 `537f805b`，台账 §6-103）
- 本仓事实：`rule_engine._admitDerivedFact`（`neurova/knowledge/ontology/rule_engine.py:378-400`）
  构造 `AdmissionRequest` 时**不传 `validFrom`/`validUntil`**——`grep validFrom\|validUntil
  neurova/knowledge/ontology/rule_engine.py` **零命中**。而 `AdmissionRequest` 契约是有这两个字段的
  （`admission.py:98`），折回路径也确实会填窗口（`admission.py:317`）。
- 后果链：推导出的结论行 `valid_until IS NULL` ⇒ 永远不进 `expireDueFacts` 的候选集
  （该查询要求 `valid_until IS NOT NULL`，`knowledge_facts.py:1034`）。
  而 `expireDueFacts` 本身（`:1029`）**在全仓 `neurova/` + `scripts/` 内零调用点**——
  只剩它自己的定义与两处中文注释提到它。于是 `:1041-1042` 那段"前提到期 ⇒ 撤销其推导结论"
  的级联**从未在运行期可达**。
- 设计意图是清楚的：`knowledge_facts.py:952-954` 写明"状态是生命周期的唯一权威……到期靠显式调用推进，
  不起后台线程"，`searchableFacts:583-584` 又额外挡掉"已到期但尚未被推进的行"以免读面跑在巡检前头。
  **所以直接检索面是正确的**；漏的是派生面：由带窗口前提推出的、自身无窗口的结论，
  会带着 `active` 状态被 `graph_walk.py:90-100` 与四路检索长期命中。
  `supersede` 与 `retract` 都有级联，唯独"到期"这一条生命周期迁移的级联不可达。
- **不要拿 `test_validity_window_segment.py`（受保护子集 `protected_tests.txt:195`）当反证**：
  该用例的判据是"声明过窗口的 admit 必须读得到同一瞬时"+"过了 `validUntil` 该事实退出检索候选"——
  后者由上面那句读侧兜底满足，**并不经过 `expireDueFacts`**；
  `expireDueFacts` 在整个文件里只出现在 docstring 第 7 行的问题描述中，无任何断言触及它，
  更没有"带窗口前提推出结论 → 推进时钟 → 结论必须退出"这一条。
  该用例自己的注释还记录了一次时间炸弹（写死 `2026-09-21T12:00Z` 当"此刻"，绿灯窗口实际只剩 45 分钟），
  现在取时口径已收口到系统时钟——**这条纪律是好的，但它钉的是落库跳，不是迁移跳**。
- 当时留给拍板的两种收口：① 给推导事实**继承前提的 `valid_until`**（取最小值），让窗口随推导传递；
  ② 给 `expireDueFacts` **一个真实触发点**，并让判据可证伪。
  **✅ 已按 ② 落地 `537f805b`**（判据入子集与本笔同批，台账 **§6-103**）：触发点有两处消费者——
  `_on_startup` 里的一次性收敛（紧挨"AgentRun 台账启动收敛"与"知识摄取队列排水"那两段同族 fail-open
  先例，且走 `asyncio.to_thread`，不给自己添 §6-93/§6-99 那族"协程内裸调阻塞"新格），
  以及管理员运维端点 `POST /api/v1/knowledge/foundation/expiry`（照 `/foundation/integrity`
  那格"巡检即运维入口"的先例；第二次跑回 0 才成立"敢被启动调一次"的前提）。
  不取 ① 的理由记录在案：① 让 `status` 永不记"已到期"，并把全仓唯一的状态推进实装
  逼成同期退役项；② 与 `:953` 那句"状态是唯一权威"逐字一致，到期/取代/撤回三条迁移同构。
- 对方侧的引子只是提问：对方的 as-of 重建让"清扫进程"从正确性依赖里消失，
  这是否说明本仓②路径（依赖被调用）在架构上比①脆弱？

### N2 · `purge=true` 端点对外承诺"物理删除整条"，其余存储面删不掉（✅ 已闭环 `a0316ec0`，判据入子集 `9c710d31`，台账 §6-101）
- 本仓事实：`knowledge_core.py:409,418,448-449` 提供 `?purge=true`，
  文案是"**物理删除整条（清除违规内容的显式通道）**"，实现落到 `repo.purge_knowledge`，
  后者只动**条目这一面**：删 item、删 `_tombstones`、同步治理行、存盘、记一次索引操作。
- **本文首稿把这一面说成"JSON 条目层"，落地时复算作废**：条目权威自工单 019a–019b-4b 起已在
  SQLite `knowledge_narratives`（`repository.py:570` 的 `replaceAll`），所以条目行**确实删得掉**；
  缺口不在"删错地方"，在"只删了一个地方"。
- 而权威侧：**`grep "DELETE FROM knowledge_facts|knowledge_subjects|knowledge_assertions" neurova/` 零命中**
  ⇒ SQLite 事实行（`content`/`object_term`）、断言行（`statement_text` 列就在里面）、
  活动信封（实测 `knowledge_activities.inputs_json` 里 import 那批带归一化正文）、
  `data/knowledge/knowledge_vectors_1.json`（实测现存 525,690 字节）里的 `content[:2000]` 副本，
  以及投影节点的 `properties.description`（`graph_bridge.py:397` 写 `content[:200]`），
  **五条副本都不在这条 purge 的覆盖范围内**。另：端点从不读 `purge_knowledge` 的返回值，
  半删照报 200——这一点本文首稿也写窄了（原话"折成一个 `bool`"，实况是连那个 `bool` 都没读）。
- 这不是"要不要遗忘"的设计分歧——`knowledge_facts.py:1046` 的 `retract` 明确写了
  "可撤销不可遗忘：行不删，只出候选"，那是**有意**的账本立场。问题在**两个语义被混用**：
  对外叫"物理删除整条、清理违规内容"的通道，只清了一面。影响面：合规删除承诺、
  公共条目治理、以及"违规内容"这一类必须真删的场景。
- 可实施性当时已具备（也确实如此落地）：`medium_ref` 现就存着 `entry:<knowledge_id>` 形态
  （`graph_bridge.py:164`，并有 `(fact_id, actor_type, actor_id, medium_ref, statement_hash)` 索引
  `knowledge_facts.py:141`），按它反查受影响 fact_id 是**已有链接的用法**，不是新研究。
- **落地裁定（用户 2026-10-09 点单方案 ①，并拍定不可逆点为「擦正文、留链与哈希」）**：
  断言行是审计链上的一跳，硬删会让 `seq` 出空洞、`ActivityDigestChain.verify` 判"链被削过"、
  `/foundation/integrity` 从此常红，故落点是 v13 新增列 `erased_at` + 正文置空，行与
  `seq`/`digest`/`statement_hash` 不动；`_breakReason` 同步认领这个本仓自己造出的合法态，
  并反咬"带标记却塞回正文"。逐面动作与五态回执（`erased/redacted/absent/unavailable/failed`
  外加前序失败时 `not_attempted`）由 `foundation/erasure.py` 单点实现，`purge_knowledge`
  改为编排喉，端点读回执、任一面失败即 500 点名。全文见台账 §6-101。
- 顺带作废本文另一条预设：知识域**没有 fts5 影子表**（`hybrid.py` 的 fts 路是查询期对可见语料
  打分），所以不存在"删主表漏删影子行"那一格——那条清理纪律在本仓只适用于 `memories_fts`
  与 `evicted_fts` 两个记忆面。

### N3 · 检索评估台架建了表、建了端点，**从未在生产数据上跑过一次**（✅ 已闭环 `c6b175a8`，台账 §6-105）
- 本仓事实：`evaluation/retrieval_benchmark.py` 有 `evaluation_cases/runs/findings` 三表
  （`:31,40,56`）、独立迁移域 `knowledge_evaluation`（`:67`）、`seedFromRepository(:206)`、
  `freezeBaseline(:361)`、`baselineReport` 与 `findings` 读面；REST 读面 `knowledge_core.py:214-221`
  在没有基线时**如实**给 `missing_reason`，并直接指名要做的那三步。
- 但：**`freezeBaseline` 与 `seedFromRepository` 在 `neurova/` + `scripts/` 内零生产调用点**
  （仅测试与那句提示文本）；且 `data/knowledge/` 目录实测**只有 `knowledge_facts.db` 与
  `knowledge_vectors_1.json`**，**评估库文件根本不存在** ⇒ 该台架从未对真数据跑过。
  `scripts/ci/protected_tests.txt` 里有 13 条路径含 `knowledge` 的受保护测试文件
  （主代理逐行核过，已剔掉两处注释行），**其中 `grep -c "evaluation\|benchmark"` 为 0**
  ——没有一条是基线冻结或回归比对。
- 本仓自己已把这一步写进注释：`tests/unit/knowledge/test_retrieval_benchmark.py:137`
  "真实基线由 `freezeBaseline` 一次性跑出，不落进单测"。**这句话是一个欠执行的承诺**：
  台架的数学被单测保护了，检索质量本身却**没有任何回归地板**——
  改一路检索权重、改 hop 上限、开 `NEUROVA_KB_FACT_SURFACE` 都不会有任何东西变红。
- 与 §5-N1 的区别要说清：这不是"缺功能"，是**已有功能没有执行入口**。
  收口形态是把"跑一次并落盘基线"变成可判定的动作（脚本 + 基线产物入受保护子集的比对判据），
  而不必新增任何判分逻辑。
- 对方侧引子只作提问：对方有 `objective/direction/threshold/expect` 把分数变裁决、
  有 `runs=10` 的 flaky 分类，但**结果是 CLI 写出的一个 JSON 文件、无历史表、CI 作业自认已挂**。
  即本仓的表结构其实更完备——**两边都卡在同一个最后一步：没有闸**。

### N4 · 权威库与投影的漂移只有"人去按"才探得到（✅ 一次性清账完成，用户裁定不接运行期；台账 §6-106）
- 本仓事实：`graph_bridge.py:6-12` 把"权威三元组 + JSON 投影"的双份存储写成了长期形态，
  漂移靠 `/authority-drift`（`knowledge_graph_api.py:327`）与 `/projection/rebuild`（`:348`）；
  投影 JSON 现存量级实测 139,519 字节 nodes / 58,835 字节 edges。
  受保护测试里 `test_projection_derived_from_authority.py`（`protected_tests.txt:341`）钉的是
  "投影必须由权威派生"这条**构造纪律**，不是"当前两份是否一致"的**运行期事实**。
- 于是这是一个典型"写入→读取→反馈"半环：探得了，但没人探；反馈不回喂到写路径。
  **今日实际偏差是多少，本文未测**（§8 剩余风险），必须先量再判。
- 对方侧引子只作提问：对方把投影做成写路径的**可选 sink**（同一份 dict 直接吐
  `add_nodes/add_edges`），因此**漂移这条故障类别不存在**。
  本仓是否值得把"投影"从第二份存储降为派生视图（或反过来，把 JSON 图退役、
  统一到 `knowledge_subjects/facts` 的递归遍历）——这是 §7 同功能双实现的裁决问题，
  须走"对比优劣→取长补短→接通→退役"的固定顺序，**本文不做裁决**。

### N5 · 抽取断言的 `actorType` 恒为 `"pipeline"`，置信度来源不可分
- 本仓事实：LLM 抽取写入的每条断言，`actorType` 是**硬编码字符串**（`graph_bridge.py:162`），
  且该处不设 `weight`；`grep confidence_source` 在 `neurova/knowledge/` 零命中。
  `confidence` 与 `credibility.py:37,66` 的聚合只看 assertion 权值，
  于是"模型自报的 0.9"与"由多源印证得到的 0.9"在账上是同一个数，
  而 `conflict_judge` 与可信度聚合又会吃这个数。
- 本仓已有的对冲是 `verification_state`（`:138`，默认 `unverified`，由 `digest_chain` 回写），
  它管的是"**这条断言被核验过没有**"，与"**这个分数是怎么来的**"是两个轴。
  所以这是一条**薄差集**，不是结构性缺陷；是否值得做，取决于 §5-N3 之后是否有判据能吃它
  （没有回归地板时，加一列来源类型的收益无法度量——两条候选因此有先后关系）。
- 对方侧引子只作提问：对方用四态枚举 + "未知绝不折成 0"把来源类型显式化，
  本仓是否只需要在 `knowledge_assertions` 的 `actor_id` 语义上把模型/提示版本区分开（`ACTIVITY_KINDS`
  里已有 `derive` 且 `rule_engine.py:398` 已在用，抽取侧却仍是一个常数）——
  这是**把已有字段用起来**，不是新增体系。

### N6 · ~~抽取侧的 ontology domain/range 门在本仓也是"写了没人接"的同类形态~~（✅ 原判作废：段状态是 wired 且违例即 raise）
- 本仓事实：`graph_bridge.py:37-42,80-93` 的提示是从 term registry 取候选类型给模型选，
  即**类型约束只存在于提示词里**；落库前有 predicate 合法性由咽喉把关，
  但 `ontology/validation.py` 一系校验是否对**每条抽取三元组做 domain/range 复核**，
  本文未逐条复算（§8）。对方在这一点上和本仓同形：`ExtractionSchema.from_ontology/from_owl`
  带 domain/range 约束却**零生产消费方**，三元组进图前无任何校验（`kg/` 全域）。
  **所以这不是"对方的启发"，是两边共同的一处待确认格**——列在此处只为防止把它当成已完成项。

---

## 6. 候选清单（**未点单、未落地、未提交**）

甲类＝净接/净删/改文案，不新增依赖，可各自独立成批；乙类＝新能力，须各自独立设计论证，**不与甲类混批**。

| 编号 | 内容 | 类 | 挂靠断点 | 判据形态（红须落在行为断言） | 前置 |
|---|---|---|---|---|---|
| K1 | 推导事实继承前提窗口，**或**给 `expireDueFacts` 一个真实触发点（二选一，不并存） | 甲 | N1 | 带窗口前提推出结论 → 推进时钟 → 结论从 `searchableFacts` 与 `graph_walk` 同时消失 | ✅ **已按 ② 落地 `537f805b`**（启动一次性收敛 + 管理员运维端点；台账 §6-103） |
| K2 | `purge=true` 语义诚实化：补跨存储擦除 + 逐面如实回执 | 甲 | N2 | ✅ **已落地 `a0316ec0`**（判据入子集 `9c710d31`，台账 §6-101）——用户点单方案①并拍定「擦正文、留链与哈希」；13 格判据含"副本取不回"与"链与哈希不许被顺手删"两类 | — |
| K3 | 检索基线跑出并落成会红的地板 | 甲 | N3 | ✅ **已落地 `c6b175a8`**（真库读数 + 合成夹具门；台账 §6-105） | — |
| K4 | 漂移探针接进运行期（写收尾或启动时自比），或走 §7 双实现退役裁决 | 甲 | N4 | 人为制造投影/权威不一致，探针必须指名并给出重建路径 | **先实测今日偏差** |
| K5 | 把 `actor_id`/`medium_ref` 用满，使抽取来源可分（不新增列亦可选） | 甲 | N5 | 同一 fact 两条不同来源断言，聚合读数必须能区分来源 | 依赖 K3 才有度量 |
| K6 | 图派生切块（实体边界/triplet 跨度不切断）对本仓导入分块的价值评估 | 乙 | — | 须先用本仓真实语料证明现分块导致的可测召回损失 | 需 K3 作地板 |
| K7 | 属性/文档级字符偏移溯源（对方有 `start_index/end_index`+`source_quote`） | 乙 | — | 须先证明"本仓逐跳溯源不足以定位错答" | 需 K3、K5 |
| K8 | 双时间轴 as-of 查询（`reconstruct_at_time` 形态）是否要进权威读面 | 乙 | — | 须先有本仓消费方（谁要在历史时点重放知识？）；**当前零需求证据** | 无需求即不立项 |

推荐起手序：**K1 → K3 → K2 → K4**（K1 无前置且影响正确性；K3 是 K5/K6/K7 的度量地板；
K2 涉及合规语义须先裁；K4 先量偏差）。K8 按当前证据**不应立项**。

---

## 7. 对方仓的"有代码 ≠ 有闸"实证清单（防照形态施工）

同一批 22.4 万行里，主代理与子代理可复算出的断链形态共 14 项，择要：
冲突检测跑完**结果丢弃**（`kg/graph_builder.py:1047-1069`）；
`OntologyValidator.check_constraint` **恒 True**（`ontology_validator.py:381-382`）；
CI 里的 benchmark 作业**指向不存在的文件**且注释自认必挂（`.github/workflows/benchmark.yml:44-56,76`）；
6 个推理器只有 1 个走 HTTP、`AbductiveReasoner` 打分是常量、`SPARQLReasoner` 的 RDF 类型 IRI 拼错
且**测试复制了同一个错**所以恒绿；
`split_ontology_aware` 是转调桩；`EventDetector` 宣称 llm 实为 5 组正则；
`kg/schemas/` 唯一一份 JSON Schema **零加载器**；
`ontology_provenance.py:26` 与 `context_provenance.py:30` 各 import 一个**不存在的模块**，导入即抛；
`cli.py:4138` 用 `strategy=/config=` 调用签名是 `(entities, method=)` 的函数；
四个 agent 框架集成 + 16 工具 MCP + 第二套 `semantica_mcp/` 三处对外面并存；
`graph_store` 四个后端 4,259+ 行同职能平行实现；
`find_similar_nodes` 文档承诺三种相似度只实现两种；
`proximity_weight` 默认 0.0（功能上线即关）；
五个 `*WithProvenance` 包装器零生产消费方。

**这一节的用处**：它是本仓 §1 第 1 条与第 6/7 条纪律的**反向教材**——一个 MIT 许可、
万星、文档齐备的仓，仍然可以大面积把"实现存在"当成"能力存在"。
因此本仓若采纳 §6 任一项，**判据必须写成运行期可证伪的探针**，
不能以"某类/某端点已存在"作为闭环证据。

---

## 8. 证据三态

**已核实（主代理亲验，本仓侧）**：`knowledge_facts.py:952-954/1029-1043/583-603/133-141`、
`rule_engine.py:378-400` + 该文件 `validFrom|validUntil` 零命中、
`DELETE FROM knowledge_facts|subjects|assertions` 全仓零命中、`repository.py:1129-1146`、
`knowledge_core.py:214-221/409-449`、`freezeBaseline|seedFromRepository` 生产零调用、
`data/knowledge/` 目录实测（无评估库文件）、`graph_bridge.py:162/164`、
`protected_tests.txt` 13 条含 knowledge 的受保护测试文件（剔注释后逐行数过）与其中 0 条评估/基准、`query_at_time` 仅 legacy TKG 一处（`:395`）及其消费面仅测试。
**已核实（对方侧抽验）**：`hybrid_search.py:181-219` 与 `vector_store` 词法零命中、
`ontology_validator.py:336-382` 原文、`graph_store` 无本地后端、克隆 commit 与 LICENSE/MIT 原文、
各包 `wc -l` 与总 LOC。

**子代理实读、主代理未逐行复算**：`context/` `kg/` `provenance/` `reasoning/` `ontology/`
`explorer/` 的内部机制细节与表内 file:line（六路 Explore 在同批 22 万行上分工覆盖约 14 万行）；
本仓 `neurova/knowledge/` 的 LOC 与 13 张表清单。

**剩余风险 / 未做的检查**：
① **N4 要求的"今日权威 vs 投影实际偏差"未测**——K4 开工前必须先量；
② 未跑对方的任何代码（纯静态读），"某功能不可用"的判定只到"无消费方/为桩"这一层，
   未做运行期复现，因此不可把这些条目当质量结论传播；
③ `ontology/validation.py` 对本仓每条抽取三元组的实际约束强度未逐条复算（N6）；
④ 未查对方贡献流程与治理（issue/PR 门禁、CODEOWNERS），因此"社区规模"类叙述不可作本仓依据；
⑤ 对方 `ingest/`（29,066 行）与 `parse/` 只做**结构级扫读**（枚举源类型与是否有字符偏移），
   未深读；若未来要评"连接器面"，需另切窄批；
⑥ 本文未与本仓 `docs/Neurova_WeKnora代码级对比_2026-09-15.md` 做三方对齐——
   同一"知识底座对标"主题在本仓已有第二份事实源，**刷新时应考虑合并到一处**，
   避免 §6/§7 双源（见 `docs/INDEX.md` 阅读顺序）。

---

## 9. 一句话给拍板用

对方值得本仓带走的不是它的 28 个子包，而是**三处能把本仓已有能力闭环起来的提示**：
到期迁移要有触发点（N1）、对外承诺的删除必须覆盖它声称覆盖的副本（N2）、
建好的评估台架要真的跑一次并落成判据（N3）。
其余各项——多后端共识、图感知切块、字符偏移溯源、as-of 重放——在本文可比范围内
**没有任何一条能由"对方有"变成本仓的立项理由**，须各自在本仓找到可核实的损失证据才成立。
