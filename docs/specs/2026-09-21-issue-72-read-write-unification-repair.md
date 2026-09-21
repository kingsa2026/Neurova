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
  **（第三轮处置见 §5c）**：信号判据与账的读写闭环已收口；"不阻断"语义按裁决保留。
- **记忆内容门"保首条"语义保留**：同作用域同归一内容仍是"首条为准 + 刷 `updated_at`"。
  取代的入口是"声明取代"（本批接通）与底座侧冲突裁决（既有），不把内容门改成裁决器——
  那会让内容去重变成裁决顺序的函数（019b-3 已由真数据否证过同型方案）。
- **JSON 属性图仍是第二份图**：本批把它降为派生投影（抽取先落权威、再投影），
  但两套数据仍在。彻底收口需要"投影由底座派生重建"的一张票，未开。
- **生产存量数据未回填**：12 条 triple 是逻辑通路打通后的新产物；存量 92 条 narrative
  条目要补抽需重跑 `/knowledge-graph/backfill`（已有端点，现在会同时落权威），
  属运维动作，本批不执行。

## 5b. 上述三条的收口（Issue #72 第二轮）

第二轮只做"登记了但没动"的那几条，逐条按"在产生非法状态的上游修"处理。

**① 投影不再是只写不读的第二份真相（原 §5 第 3 条）**

`graph_bridge` 新增三个函数与两条端点，形成 写入→读取→反馈→再写入 的闭环：

- `projectionDrift(agentId, graph, store)`：算出权威（底座三元组里两端都是主体的那些）
  与投影（JSON 属性图的两端都在节点表里的边）的**双向差集**——`missing_relations`
  是"权威有、投影无"，`orphan_relations` 是"投影有、权威无"。**只报不修**：顺手修掉
  就等于把报出与处置混成一件事，读的人再也看不到曾经分叉过。
- `rebuildProjectionFromAuthority(agentId, graph, store)`：按权威派生重建本域投影，
  节点类型取自主体的 `type_term_id`（不自己猜），幂等（跑几次结论一样）、只动本域。
- `GET /{agent}/knowledge-graph/authority-drift`（读数）与
  `POST /{agent}/knowledge-graph/projection/rebuild`（处置）：两条端点是这两个函数的
  生产消费点——只加函数不接线就是新断点。

**② 存量补抽的待办判据问权威，不再问投影（原 §5 第 4 条）**

这条不是纯运维动作，上游有一处判据要修：`/knowledge-graph/backfill` 此前按
"条目 `graph_node_ids` 为空"筛待办，而抽取收口**之前**抽过的条目两个字段都有值
（旧实现只落投影也照样回写）。于是最需要补抽的那批存量——"投影有、权威无"——
恰好被待办判据全部跳过：端点报表写 `entries=0`（"没有待补的"），实际是
"待补的认不出来"。修法：新增 `graph_bridge.extractionPending(item, store, agentId)`，
判据落在权威侧有没有指向本条目的抽取事实（按 `source_turn_id` 前缀与断言
`medium_ref` 两处认，只认一处会把另一条真实写入链的产物当成"没抽过"）。

**③ 本体播种不再抹掉已登记的行（本轮唯一从本分支带过来的修法）**

`seedBuiltinTerms` 走 `registerMany`（`INSERT OR REPLACE`），于是**每造一次注册表**
就把写入方登记过的 `domain_terms` / `range_terms` / `range_kinds` / `cardinality`
覆盖回默认裸值——给谓词登记了定义域，重新构造一次注册表，域就没了，本体硬拒随之
永远无依据可判。修法：新增 `seedMissing`（只补缺、已存在一行不动），播种改走它；
显式种子优先于枚举收编值（同一个 `term_id` 不同时出现在两份清单里，否则"谁定这一行"
取决于拼接顺序，而只补缺的语义是"先登记的为准"）。

## 5c. 记忆侧冲突链的收口（Issue #72 第三轮）

第二轮登记里剩下的最后一条是"对话后处理那条冲突链仍是纯观测"。这条当初被判为
**有意设计**（工单 012 裁决：检测器只给矛盾分，判不出哪条为准，据此否决会随机
丢真实记忆），本轮不动它的"不阻断"语义，只收口它真正的病灶——**它不是判不出，
是没有可分辨的信号**。

**① 信号判据重建：冲突必须落在"同一命题的否证"上**

规则模式此前的判据是"子串含否定词 + 字符重叠 ≥ 0.3"。实测产出的正是噪声：

- 「今天天气不错」里的"不"被当成否定词 ⇒ 与「今天天气很好」构成
  `negation_conflict`（相似度 0.429）；
- 同一轮的复述（`"用户: 今天天气不错"` 与其加长版）相似度 0.643，也报冲突；
- 真矛盾（「系统运行正常」vs「系统出故障了」）相似度只有 0.2。

真信号与噪声混在同一批 `negation_conflict` 里，下游据此判不出哪条为准——**这条链
之所以只能纯观测，根因在这里，不在"缺少裁决工单"**。

新判据只有两条，都要求两句在说同一件事：

- **同一命题的否证**：折掉否定标记后两个命题同源（同串，或尾串同源且长度相当），
  且只有一方带否定标记（`我喜欢咖啡` / `我不喜欢咖啡`）。
- **同一对象的矛盾取值**：落在矛盾词对上，且两侧共享内容词
  （`性能提升了` / `性能下降了` 是；`成本增加了` / `效率减少了` 不是——两个不同
  对象各自变化）。

比较在**子句**层做：一轮对话是两个说话人的两段话，矛盾住在子句里，
`"用户: X\n助手: Y"` 必须能与其子句逐条对上。判据唯一定义在
`memory_layer.conflict.judgeClauseConflict`，报出的冲突在 `basis` 里逐字带出被
比较的两个子句。

**② 判据收口：一个根因两处实现，修一处等于没修**

`ConflictModule` 自持一套"否定词子串包含 + 词重叠 < 0.3 算不一致"的判法，是同一
根因的第二份实现。中文没有词界，`split()` 让每个子句各成一个词元 ⇒ 任意两句都算
"不一致"，于是「正常/故障」被报成 `inconsistency`，与「天气不错/天气很好」同级。
本模块改为消费唯一判据，两份误报根因一起消失。

**③ 闭环：检出带依据落账，账可读**

`post_chat_pipeline._step_conflict_detection` 此前检出后只写日志，不写账；而
`manager.get_conflict_summary()` 全仓**零调用方**——检出了什么在读取侧看不见，
这既是 no-op，也是一处写入→读取断点。本轮的落点：

- `ConflictModule.record(...)` 落账，**依据为空即拒绝**（宁可不记，也不记一条读不懂
  的账；与底座侧 `KnowledgeConflictJudge` 的 `policy_basis` 同一条纪律）；
- `MemoryManager.record_conflicts(conflicts, source=...)` 是检测链的写入收口，
  返回值如实反映"检出 vs 入账"的差额；
- 读面三处同源：`get_conflict_summary()`、`/memory/stats` 的 `conflicts` 栏、
  `get_traces_by_trigger(trigger=...)`（该参数此前无任何过滤效果，现接到 `source` 上）；
- 前端 `MemoryPage` 统计卡把该读数显示出来（只加字段不接线就是新断点）。

**纯观测语义不变**：`blocking=False`、message 明写"不阻断写入"、不回滚不新增行
（工单 012 裁决原样保留，`tests/unit/agent/test_conflict_detection_observation_only.py`
继续锁定）。

**仍然登记、本批不动**：升级为"可否决"仍缺"哪条为准 + 出处"的裁决证据。
本轮把**依据**这一半补齐（账上每条冲突都自带依据），但"由谁按什么策略判定胜者"
与底座侧冲突裁决的合并仍属独立一张票。

**与 main 已合入的 #89 的重叠部分**：抽取落底座（`_ExtractionSink` / `is_a` /
主体 `type_term_id`）与 `rangeKinds` 已由 #89 落在 main，本分支的同型实现
（`admitExtractedFacts`）在合并时**删除**，不保留第二份实现（教义第 6 条）。

### 5c 的判据与实测（第三轮）

红灯（实现前实测）：

- `test_conflict_signal_scope.py`：`assert {'type': 'negation_conflict', 'similarity': 0.428...} is None`
  （「今天天气不错」vs「今天天气很好」被判成否证冲突）；复述用例同为 0.643 误报；
  `basis` 缺失。
- `test_conflict_disposition_loop.py` 8 例：`get_conflict_summary()` 恒 0（检出 1 处而账上 0 条）、
  `Conflict._basis` 不存在、`ConflictModule` 把「正常/故障」报成 `inconsistency`。

绿灯（实现后）：

| 判据 | 结果 |
|---|---|
| 信号落在同一命题（误报 4 例不再报、真否证/真矛盾 6 例仍报） | 7 例绿 |
| 检出带依据落账 + 读数可见（summary / stats / 按来源）+ 依据缺失不入账 | 8 例绿 |
| 既有冲突相关套件 | `test_audit_regressions`、`test_conflict_detection_observation_only`、`test_memory_guards_wiring`、`test_p2_pipeline_fixes`、`test_manager_full_delegation`、`test_conflict_single_implementation`、`test_conflict_policy_basis` 等 251 例全绿 |
| 爆炸半径 | `tests/unit/{agent,cognitive_layers/memory_layer,cognitive,memory,memory_ingest,knowledge}` A/B 自证：修复前后失败集合逐行相同（24 项预存环境失败，无新增） |

live-verify（真检测器 + 真 MemoryManager + 真 post_chat 步骤）：

```
[判据] ('今天天气不错','今天天气很好') -> None
[判据] ('我喜欢咖啡','我不喜欢咖啡') -> ('negation_conflict', ..., 同一命题的否证：...)
[判据] ('系统运行正常','系统出故障了') -> ('semantic_contradiction', ..., 同一对象的取值互斥：...)
[判据] ('成本增加了','效率减少了') -> None
[链1] 步骤读数: conflicts_count=1 recorded=1 blocking=False
[链1] message: 检测到 1 处记忆冲突（纯观测，不阻断写入；入账 1 条）
[链2] get_conflict_summary: {'total_conflicts': 1, 'unresolved': 1, 'by_type': {'contradiction': 1}, ...}
[链2] /memory/stats 冲突栏: {'total': 1, 'resolved': 0, 'unresolved': 1, 'by_type': {'contradiction': 1}}
[链3] 按来源读账: ["同一对象的取值互斥：'系统出故障了' 与 '系统运行正常'"]
[链4] 无依据不入账: recorded=0 | 账 total=0
[链5] ConflictModule: 天气不错/很好 -> None | 正常/故障 -> 同一对象的取值互斥：...
```

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
