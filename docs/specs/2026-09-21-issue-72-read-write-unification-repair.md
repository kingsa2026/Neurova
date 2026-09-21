# Issue #72 修复：写面与读面分裂、第三套事实库、声明取代无人读

- 日期：2026-09-21
- 规格源：Issue #72（正文四条断链）、`docs/05-reports/memory-knowledge-write-paths-isolation-audit-2026-09-21.md` §5.3、`docs/specs/2026-09-21-memory-knowledge-foundation-audit.md` §B-02/B-09/B-11
- 范围：`neurova/knowledge/graph_bridge.py`、`neurova/knowledge/ontology/term_registry.py`、
  `neurova/api/endpoints/{knowledge_ingestion,knowledge_graph_api}.py`、
  `neurova/api/endpoints/memory/tkg.py`、`neurova/cognitive_layers/memory_layer/{manager.py,modules/tkg_module.py}`、
  `neurova/memory_ingest/intake.py`、`scripts/ingest_memory.py`

## 0. 一页结论

Issue #72 点的四条断链，根因都不是"少写一行"，而是**同一件事有两份定义**：

| 断链 | 根因（真正的写入点） | 修法 |
|---|---|---|
| 抽取写 JSON 属性图、答题读底座三元组 | `graph_bridge` 只有一个落点，而它不是被读的那张图 | 抽取改走唯一咽喉落 `is_a` + 关系三元组；JSON 属性图降为派生投影 |
| `upsertFact` 生产调用全是 `narrative` | 抽取从不经过咽喉 | 抽取经 `admit()` 落 `recordKind='triple'`；来路自陈 `extract` |
| `modules/tkg_module.py` 是第三套内存事实库 | 模块自持 `_facts` 字典 + 端点字段名对不上 | 模块退役私有存储，改薄适配底座；缺字段当场报错 |
| 记忆侧新证据无法取代旧证据 | `MemoryRecord.supersedes` 只写进 metadata、无任何读方 | 导入时按内容身份定位旧活跃行并软遗忘，找不到如实申报 |

## 1. 抽取产物的落点（B-09 / G12）

**现状取证**：`extract_knowledge_to_graph` 只调 `KnowledgeGraphManager.add_node/add_edge`
（`agent_workspaces/<agent>/knowledge_graph/*.json`），而 `temporal_facts` 与 `graph_walk`
双双按 `record_kind='triple'` 过滤底座表——实测同一个条目抽取后：JSON 图 2 节点 1 边，
底座 `searchableFacts` 为空，两条读面命中为 0。

**修法（两个落点，权威在前）**：

1. 新增 `graph_bridge.admitExtractedFacts()`：实体类型落 `(label, is_a, type)` 三元组，
   关系落 `(source, relation, target)` 三元组，逐条经 `productionAdmissionGate.admit()`。
   正文用 SPO 自述（`"RAG depends_on BM25"`）——三条共用条目正文会被内容身份折成同一行，
   第二条根本不存在（004 口径的正确行为，是夹具错）。
2. **主体主类型列**：`knowledge_subjects.type_term_id` 是设计 §4.2 定的身份层主类型，
   也是定义域校验唯一的读处。抽取此前只写 `is_a`，于是 87 个主体的这一列全 NULL，
   `matchesDomain` 那条硬拒永远无依据可判。现在两者同落，判据由
   `test_ontologyHardRejectIsLiveAndPointed` 钉住（登记定义域后越界主体的说法被点名拒写）。
3. JSON 属性图照旧写（可视化投影不丢），但**不再是唯一落点**；`factStore` 缺失时
   不再静默退成"只有投影"，测试会话里由 `storage_fence` 当场拦下。

**类型判据收口**：`_allowedTypes`（注册表优先 / 退回枚举）与 `_registeredTypeIds`（并集）
是同一件事的两份定义，合并为后者一份；注册表可得时不再并枚举值。

## 2. 附带根因：本体播种会抹掉已登记的类型属性

修 §1 时发现硬拒仍不响，追下去是 `OntologyTermRegistry.__init__` → `seedBuiltinTerms`
→ `registerMany` → `register`（`INSERT OR REPLACE`）：**每造一次注册表就把
`domain_terms` / `range_terms` / `cardinality` 覆盖回默认裸值**。

修法：新增 `seedMissing`（只补缺、已存在一行不动），播种改走它；`register` 仍是"更新"动词。
判据 `tests/unit/knowledge/ontology/test_term_seed_does_not_clobber.py`（3 例）。

## 3. 时序事实的单一权威与端点契约（B-02）

**现状取证**：`POST /memory/tkg/facts` 传 `entity/attribute/value`，委托层用
`.get("subject", "")` 取 `subject` —— 三个字段全取不到，**每次调用静默写一条空三元组**，
HTTP 层 200；事实落进程内 `_facts` 字典；`POST /memory/tkg/query` 调的
`manager.tkg_query` 这个动词**根本不存在**（恒 500）。

**修法**：

- `TKGModule` 改为薄适配：零私有存储，写经咽喉 `admit()`，读走底座 `searchableFacts`；
  时间窗用底座两列，不另立时间索引。
- 委托层新增三个归一函数（`subject/entity`、`predicate/relation/attribute`、
  `obj/object/value`），缺必填项**抛 ValueError**；端点把它映射成显式 400
  （`APIError.validation`），不再 500 也不假成功。
- 补上缺失的 `tkg_query` 动词；`get_stats` 键名对齐前端 `TKGStats` 契约
  （`total_facts` / `entities` / `relations` / `time_range`）。
- `entities` 只数主体名（旧口径把宾语字面量也算成实体，读数虚高）。

## 4. 记忆侧：声明的取代必须真的生效（B-11）

**现状取证**：`MemoryRecord.supersedes`（源库 `supersedes_key`）被转换器搬进
`metadata["supersedes"]` 之后**没有任何读方**——旧行照旧 active，`recall` 新旧一起端出来。

**修法**：`import_memories` 写完新行后消费该声明：按内容身份（`normalized_key`，
与内容门同一把键）在本作用域内定位被取代的旧活跃行并**软遗忘**（既有语义，可恢复、
不删数据），找不到就进 `supersede_unresolved` 并计数告警。返回值由 `(added, skipped)`
元组扩为字典（`added`/`skipped`/`superseded`/`supersede_unresolved`），
`IngestReport` 新增两栏读数，CLI 打印落地读数——写了不报就不叫闭环。

## 5. 未处置、继续登记（不静默遗留）

- **对话后处理那条冲突链仍是纯观测**：`post_chat_pipeline._step_conflict_detection`
  跑在 `save_memory` 之后、只给矛盾分、判不出"哪条为准"，故 `blocking=False`
  是有意设计（工单 012 裁决）。要升级为可否决，前提是"两条里哪条为准 + 出处"的证据，
  与底座侧 `KnowledgeConflictJudge.decide()` 的 `policy_basis` 是同一条判据；
  收编它属独立工单，本批不动。
- **记忆内容门"保首条"语义保留**：同作用域同归一内容仍是"首条为准 + 刷 `updated_at`"。
  取代的入口是"声明取代"（本批接通）与底座侧冲突裁决（既有），不把内容门改成裁决器——
  那会让内容去重变成裁决顺序的函数（019b-3 已由真数据否证过同型方案）。
- **JSON 属性图仍是第二份图**：本批把它降为派生投影（抽取先落权威、再投影），
  但两套数据仍在。彻底收口需要"投影由底座派生重建"的一张票，未开。
- **生产存量数据未回填**：12 条 triple 是逻辑通路打通后的新产物；存量 92 条 narrative
  条目要补抽需重跑 `/knowledge-graph/backfill`（已有端点，现在会同时落权威），
  属运维动作，本批不执行。

## 6. 判据与实测

红灯（实现前，逐条实测）：

- `test_extraction_lands_in_read_graph.py` 5 例全红（`factStore` 参数不存在 → 落点缺失）。
- `test_tkg_endpoint_single_source.py` 5 例：4 例 `attachFactStore` 不存在 / 端点 500，
  1 例"私有事实字典还在"。
- `test_imported_supersede_replaces_old.py` 4 例全红（旧行仍 active、recall 仍返回旧行）。
- `test_term_seed_does_not_clobber.py`：`assert [] == ['vessel']`（登记的定义域被播种抹掉）。

绿灯（实现后）：

| 判据 | 结果 |
|---|---|
| 抽取落底座 + 两条读面真命中 | 5 例绿（含 2 跳走查带出终点事实） |
| 时序事实单一权威 + 端点契约 + 坏输入 4xx | 5 例绿 |
| 声明取代生效 + 找不到目标如实申报 | 4 例绿 |
| 播种只补缺 | 3 例绿 |
| 本体硬拒真会响（登记定义域后越界说法被拒写） | 绿 |
| 受影响既有套件改判据 | `test_knowledge_to_graph` 6、`test_graph_types_as_data` 15、`test_graph_llm_bridge` 11、`test_knowledge_graph_agent_isolation` 8、`test_manager_full_delegation` 149、`test_conflict_single_implementation` 6 全绿 |
| 爆炸半径 | `tests/unit/knowledge` + `tests/unit/memory_ingest` 843 passed / 0 failed；`tests/unit/api` + `tests/unit/agent` 与修复前失败集合逐行相同（A/B 自证，差集只有本批新增用例自身） |

live-verify（真链路，`/tmp/live_verify.py` 原文进 PR）：

```
[链1] 投影节点 3 | 底座三元组 5
[链1] 时效读面: [('depends_on', 'BM25'), ('is_a', 'concept')]
[链1] 多跳读面(2跳): [(2, 'part_of', '向量检索'), (2, 'is_a', 'concept')]
[链1] 主体类型: {'BM25': ['concept'], 'RAG': ['concept'], '向量检索': ['concept']}
[链2] tkg_query: [('神经瓦', 'version', '2.0')]
[链2] 空字段响亮拒绝: 时序事实缺必填字段 subject（接受 subject/entity、predicate/relation/attribute…
[链4] 导入结果: {'added': 1, 'skipped': 0, 'superseded': ['mem_000001'], 'supersede_unresolved': []}
[链4] 旧行状态: forgotten | recall 是否含旧行: False
```
