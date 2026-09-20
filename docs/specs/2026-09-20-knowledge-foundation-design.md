# Neurova 知识库统一事实底座 — 目标态设计与缺口台账

- 文档性质：目标态设计 + 全量缺口台账（不是工单，工单另出）
- 成文日期：2026-09-20
- 范围：`neurova/knowledge/`、`neurova/cognitive_layers/knowledge_graph/`、`neurova/cognitive_layers/memory_layer/temporal_knowledge_graph.py`、`neurova/skills/experience_knowledge_base.py`、`neurova/agent/chat_pipeline.py` 检索装配段、`neurova/api/endpoints/knowledge*.py`、`NeurUI` 知识治理面
- 状态：已与负责人逐节确认（文档范围、后端约束、能力范围、依赖策略、验收判据、架构形态与迁移姿态六项均已定）

## 0. 已锁定的六项决策

| 决策点 | 取向 | 直接后果 |
|---|---|---|
| 文档范围 | 全景缺口台账 + 目标态设计 | 本文档不锁定实施顺序细节，细节在 §9 与后续工单 |
| 后端约束 | 零新增外部服务 | 全部落在 SQLite + 本地 ONNX，不引入需起进程的图/三元组/向量服务。向量与 embedding 不是缺口：本地栈已在位——`models/embedding/bge-small-zh-v1.5/` + `vector_index.py:34` 的 ONNX 引擎 + `UnifiedVectorStore` 的后端自动探测（faiss→fastembed→onnx→tfidf，`unified_vector_store.py:224-247`，全部 try/except ImportError 可选）。本约束只说"不外接服务"，不需要新增任何向量基建 |
| 能力范围 | 治理四臂 + 形式化本体 + 确定性推理 | §6 的三表本体与规则引擎属一期范围，不是"以后再说" |
| 依赖策略 | 零新增第三方依赖，完全自研 | `requirements.txt` 不新增包；RDF/Turtle 文本自拼；不做 SPARQL 文本查询 |
| 验收判据 | 离线检索评测集为主 | §8；治理指标为辅证；线上反馈信号为旁证 |
| 架构形态 | 统一事实底座（单一权威源） | §4；迁移走扩展-收缩五阶段 E0–E4，不做一次性切换 |

命名约定沿用仓库现状：文件名 snake_case，类名 PascalCase，函数与变量 camelCase，模块目录以 `neurova/<域>/` 组织。

---

## 1. 现状基线（实测）

### 1.1 五套异构存储并存

| # | 存储 | 位置 | 形态 | 权威域 |
|---|---|---|---|---|
| S1 | 知识条目库 | `neurova/knowledge/repository.py:158` | JSON `data/knowledge/knowledge.json`（按 agent_id 分组） | 叙述层条目 |
| S2 | 技能经验库 | `neurova/skills/experience_knowledge_base.py:100` | SQLite `data/experience_knowledge.db` | 技能执行经验 |
| S3 | 属性图 | `neurova/cognitive_layers/knowledge_graph/manager.py:190` | 每 agent 独立 JSON 目录 | 概念/实体关系 |
| S4 | 时序事实图 | `neurova/cognitive_layers/memory_layer/temporal_knowledge_graph.py:172` | SQLite，**默认 `:memory:`**（`:220`） | 带时效窗口的 SPO 事实 |
| S5 | 引用句柄 | `neurova/memory/citation.py:41` | 进程内注册表 | 记忆条目引用 |

S1–S4 四套存储互不相认、无共同身份层（缺口 G12）；其中 S4 是唯一已经具备"目标底座形状"的表结构（§4.1）。S5 只覆盖记忆域，未扩到知识域（缺口 G01）。

### 1.2 生产库读数（2026-09-20 实测，命令见 §1.3）

| 读数 | 值 | 含义 |
|---|---|---|
| 知识条目总数 | 130 | `default` 104 / `kai` 24 / `ag` 2 |
| 不同标题数 | 88 | 42 行标题重复 |
| 标题相似度 ≥0.9 的成对数 | 100 | 现有检测器口径下应大量成账 |
| 不同内容哈希数 | 92 | 19 组内容完全一致，覆盖 57 行 |
| **纯冗余行数** | **38（29%）** | 同内容重复入库 |
| 冲突账本记录数 | **0** | `knowledge_conflicts.json` 为 `{}` |
| 墓碑文件 | 不存在 | `knowledge_tombstones.json` MISSING |
| `confidence` 分布 | 0.7 × 126、0.9 × 3、0.5 × 1 | 字段无区分力，实为常量 |
| `visibility` 分布 | private × 130 | public/shared 通路从未承载数据 |
| 图谱抽取覆盖 | 34 / 130（26%） | 携带 `graph_node_ids` 的条目占比 |
| 分块覆盖 | 130 / 130 | `chunks` 全有，父子分块可用 |

### 1.3 复核命令

```bash
python - <<'PY'
import json, difflib, hashlib, collections
d = json.load(open('data/knowledge/knowledge.json', encoding='utf-8'))
items = [i for a in d.values() for i in a]
ts = [str(i.get('title','')).strip().lower() for i in items if i.get('title')]
pairs = sum(1 for a in range(len(ts)) for b in range(a+1, len(ts))
            if difflib.SequenceMatcher(None, ts[a], ts[b]).ratio() >= 0.9)
h = collections.Counter(hashlib.sha256(str(i.get('content','')).encode()).hexdigest()[:10] for i in items)
dup = {k: v for k, v in h.items() if v > 1}
print('items', len(items), 'distinct_titles', len(set(ts)), 'near_dup_pairs', pairs)
print('distinct_content', len(h), 'redundant_rows', sum(dup.values()) - len(dup))
print('conflicts', json.load(open('data/knowledge/knowledge_conflicts.json', encoding='utf-8')))
print('confidence', collections.Counter(round(float(i.get('confidence') or 0), 2) for i in items))
print('graph_linked', sum(1 for i in items if i.get('graph_node_ids')))
PY
```

---

## 2. 空转型断点（接了但不工作，比缺功能优先级更高）

| ID | 断点 | 证据 | 后果 |
|---|---|---|---|
| B01 | 对话链上的 TKG 检索分支恒空 | `chat_pipeline.py:255` 无参构造 `TemporalKnowledgeGraph()` → `temporal_knowledge_graph.py:220` 落 `":memory:"` | priority 26 的检索器每轮扫一张空表，成本恒定、收益恒零 |
| B02 | 事实抽取与记忆→TKG 同步无生产调用方 | `extract_facts_from_memory`（`temporal_knowledge_graph.py:667`）、`sync_memory_to_tkg`（`:729`）全仓仅自引用 | 即使 B01 修好，也没有事实进表 |
| B03 | 条目层没有去重能力，重复既不过滤也不记账 | 条目字段集（`repository.py:484-504`）**无内容身份列**；唯一的去重是摄取事件表的 `dedupe_key UNIQUE`（`ingest_queue.py:38`，`INSERT OR IGNORE` 于 `:144`），其口径是"原始文件字节的 sha256 + agent_id + user_id"（`:119-120`）或"URL 字符串的 sha256 + agent_id + user_id"（`:132-133`）——不是抽取后的内容，且只覆盖异步入队两路；同步导入（`knowledge_ingestion.py:142`）、手工 `create_knowledge`、渠道同步、外部抓取四类入口完全不经它。同时 `repository.py:1132` 把内容完全一致判为"不算冲突" | §1.2 的 38 行纯冗余：同内容重复入库、检索时反复占槽，而两套机制都声称"这不是问题" |
| B04 | 属性图不进对话检索链 | 检索链注册序列见 `chat_pipeline.py:220-276`，无 graph retriever | 26% 覆盖率的图结构在答题时完全不被利用 |
| B05 | rerank 只在旁路 API 生效 | `knowledge/rerank/` 仅被 `api/endpoints/semantic_search_api.py:35` 消费；`hybrid.py`、`knowledge_retriever_adapter.py` 零引用 | 主链排序停留在 RRF 秩融合，精修能力闲置 |
| B06 | 知识条目层零使用度量 | `hit_count\|last_used_at\|usage_count\|recall_count` 在 `neurova/knowledge/` 零命中 | 知识被用到还是被无视，无从判断；淘汰与排序都失去输入 |

B06 与已完成的经验库修复同型：EKB 侧的对应列已在 `experience_knowledge_base.py:166-215` 落地（`injected_count/last_injected_at/adoption_outcome/evidence_state`），本设计直接复用该套词汇，不另造第二套。

---

## 3. 缺口台账 G01–G12

每条含：现状锚点 / 目标态 / 可证伪判据 / 影响面 / 规模估计 / 落点阶段。判据一律写成"不满足即判定该项未完成"的形式。

### G01 逐跳血缘缺失
- 现状：条目 `source` 是单个自由字符串（`repository.py:490`，形如 `import:note.txt`）；`provenance` 在 `neurova/knowledge/` 零命中；`citation.py` 只服务记忆条目（`register:50`、`render_citation:81`、`extract_citations:113`），知识读路径不引用它。
- 目标态：`knowledge_assertions` + `knowledge_activities` + `knowledge_derivation_edges` 三层（§4.2），任一事实可回答"谁在何时经哪条管线、依据哪些前提得出"，推导事实可回溯到原始断言。
- 判据：任取一条推导事实，沿 `derivation_edges` 反向遍历，能在不查日志的情况下还原到全部原始断言；断言为空的事实无法被写入（咽喉拒绝，见 §5）。
- 影响面：`repository.py` 写路径全部 5 个上游 + 前端详情面板。
- 规模：新增约 4 表 + 1 门面，中等偏大。阶段 E1。

### G02 溯源完整性无校验
- 现状：无任何防改写机制；`_REVISION_FIELDS`（`repository.py:40`）只存改前快照，不校验账本自身。
- 目标态：`ActivityDigestChain`（§4.2 表 `knowledge_lineage_heads`），**每活动一条链头，链头内逐断言递增 `seq + digest`**，链头另相约为 `head_digest`。
- 判据：篡改任一断言文本或其 `prev_seq_digest` 后，校验必定位到该活动及其后所有断言；不篡改时全链校验通过。
- 规模：小。阶段 E4。

### G03 冲突建模能力不足
- 现状：`_detect_conflicts`（`repository.py:1106-1157`）= 标题归一化 `difflib` ≥0.9 + 同 agent 范围（`:1119` 遍历 `self._items.get(agent_id)`）+ 只记账不阻断 + 每条新条目最多记一条 + 仅 `keep_both`/`supersede_old` 两种人工裁决（`:1176`）。TKG 侧另有独立实现 `temporal_knowledge_graph.py:439`，规则引擎里还有第三份 `temporal_reasoner.py:471`。
- 目标态：单一 `knowledge_conflicts` 表，五类（value / qualifier / type / temporal / cardinality）× 严重度 × 策略，作用域覆盖公私域与跨 agent；三套实现合一（§4.2、§5 第 4 段）。
- 判据：同一 `subject + predicate` 上存在两个不同值时必产生一条 value 冲突；带不同时间窗口的两条事实判为 temporal 而非 value；`unevidenced` 成员不得进入自动裁决路径。
- 影响面：`repository.py`、`temporal_knowledge_graph.py`、`temporal_reasoner.py`、`knowledge_sharing.py` 冲突端点、`KnowledgePage.vue:178-196` 冲突队列。
- 规模：大（含三份实现收敛）。阶段 E1 立表、E3 收删除。

### G04 冲突严重度与解决策略单一
- 现状：无严重度字段，无自动策略，全部落人工。
- 目标态：写入时算 `severity` 与 `recommended_policy`，并**必须带 `policy_basis`**（依据哪个可信度账本/时间戳/来源类型）；无依据即记 `unevidenced` 并强制留人工。
- 判据：任何 `status='auto_resolved'` 的冲突记录都能读出 `policy_basis`；读不出的记录不允许以自动方式关闭。
- 规模：小-中。阶段 E2。

### G05 消解不可重放、复杂度失控
- 现状：`resolution.py` 三段式——精确签名（`_side_signature:38`）、`difflib` 全对遍历（`find_candidates:105`，阈值 0.85，`:34`）、逐对 LLM 裁决（`run_adjudication:142`、`_ask_llm:192`）+ 人工队列（`list_human_reviews:247`、`resolve_human:256`）。成本 O(n²) 且每对可能一次 LLM 调用，同一批数据重跑结果可不同。
- 目标态：`EntityBlockingResolver`——候选分块（前缀 / token / 类型 / 值域）→ 多因子相似度加权融合（字面 Levenshtein 与 Jaro-Winkler、属性重叠、关系邻域重叠、向量余弦（**复用 §0 所述的既有本地 embedding 栈，不新增向量基建**），全部自研实现）→ 并查集聚类 + 层次聚类备选；**消解层零 LLM**，LLM 仅保留在人工队列之前的可选解释位。
- 判据：同一输入重放两次，合并集完全一致（哈希对账）；§8 的消解错合率与漏合率相对基线不升；LLM 调用计数在消解段为 0。
- 规模：中。阶段 E4。

### G06 知识生命周期缺失
- 现状：条目无 `status`、无失效语义，仅墓碑（`repository.py:992` restore）；`ttl|decay|retire|lifecycle` 在 `neurova/knowledge/` 零命中。
- 目标态：`knowledge_facts.status`（active / superseded / expired / retracted）+ `supersedes_fact_id` + `contradicted_by_json` + 三值 `evidence_state`；EKB 已有的词汇沿用（§2 B06 末）。
- 判据：被取代的事实在检索候选中出现即为缺陷；`retracted` 事实必须仍可被溯源查询读到（可撤销但不可遗忘）。
- 规模：中。阶段 E1。

### G07 证据回流缺失
- 现状：B06。
- 目标态：`adoption_outcome` 三值（success / failure / unevidenced），NULL 专用于"从未回写"；注入即增 `injected_count`、更新 `last_injected_at`；下游反馈（人工修正、`annotation` 通道、答案被采纳信号）回写 `adoption_outcome`；可信度账本按断言 actor 维度聚合，并**显式声明它不等于真值度量**——只回答"该来源历史上被采纳后的结果分布"。
- 判据：任一事实被注入上下文后 `injected_count` 必增；回写通路存在且有测试覆盖；账本页面上 `unevidenced` 计数可见。
- 规模：中。阶段 E1 立列、E2 接通路。

### G08 类型系统硬编码、入库无校验
- 现状：`NodeType`（`manager.py:23`）10 值、`RelationType`（`manager.py:38`）15 值，均为 `Enum`；`ontolog` 关键词全仓 `.py` 零命中；`graph_bridge.py:50` 仅按 `(label, type)` 精确复用节点，写入无字段与基数校验。
- 目标态：`ontology_terms` 声明式注册表（term、域与值域、基数、父子、不相交公理）+ `OntologyValidationReport` 五条校验（§6.2）。
- 判据：新增一个概念类型不需要修改任何 Python 文件；违反值域或基数的写入被拒绝并产出一条可定位的违规记录。
- 规模：中。阶段 E4。

### G09 蕴含推理缺失
- 现状：只有遍历——`manager.py` BFS 路径查询、`temporal_reasoner.py` 时效推断；无法从已有事实得出新事实。
- 目标态：`ontology_rules` + `ForwardChainingEngine` + `DerivationLedger`（§6.3），推导事实 `derivation_kind='inferred'` 并挂 `derived_from` 前提集。
- 判据：给定传递性规则（如 `part_of` 链）与 3 条原始事实，推理后新事实数量符合预期且每条都能读出前提与规则标识；规则被修订后可凭推导账本精确撤销受影响结论。
- 规模：大。阶段 E4。

### G10 时效排序缺失
- 现状：`hybrid.py:104` 四路 RRF（`DEFAULT_ROUTE_WEIGHTS` tfidf .30 / bm25 .30 / vector .25 / fts .15，`hybrid.py:31`，k=60）不读 `updated_at`；仅 TKG 路带时效窗口（`query_tkg_for_context:743`）。
- 目标态：排序式引入 `freshness_term` 与 `confidence_term`（§7），`confidence_term` 在 §5 第 5 段落地前恒为 1 并记 `unevidenced`。
- 判据：同等相关度下，`valid_until` 更近者排前；`expired` 项不进入候选；关闭新项后行为与现基线逐条一致（可回退开关）。
- 规模：小。阶段 E2。

### G11 置信度语义未定义
- 现状（**2026-09-20 实施期复核修正**，原写"create_knowledge 默认 0.7"是错的归因）：
  0.7 来自**文件/URL 导入路径的硬编码** `api/endpoints/knowledge_ingestion.py:208 confidence=0.7`；
  `create_knowledge` 与 API 请求模型的默认其实是 0.5（`repository.py:491` 区段、`knowledge_common.py:34,55`）。
  §1.2 实测 126/130 = 0.7 之所以是那个值，正因为这 130 条几乎全部来自 `source: import:*` 的导入路径
  ——一个常量决定了全库"置信度"。
- 目标态：`confidence` 只能由事实层按断言聚合得出（§6.1 定义式），条目与叙述层不得自带数值置信。
- 判据：全库 `confidence` 值种数显著多于 1，且每条非默认值都能回溯到至少一条断言；导入路径不再写死常量。
- 规模：小（删硬编码 + 换聚合口径）。阶段 E1 立聚合、019 换条目侧。

### G12 三套图谱/事实/经验存储无共同身份层
- 现状：`graph_bridge.py` 唯一写入方是知识导入链；`knowledge/` 与 `cognitive_layers/knowledge_graph/` 无交叉；EKB 与 KB 之间只有关联簿记（`knowledge_integration.py` 的 `memory_links.json`，`:43` 注释自陈原实现谎报 Synced），无条目通路。
- 目标态：`knowledge_subjects` 作为唯一身份层，S1–S4 全部经 `subject_key` 对齐；`merged_into` 承载合并链。
- 判据：同一现实实体在条目、属性图、事实层三处解析出同一 `subject_key`；合并后可从旧 key 走到新 key 且旧 key 不再被检索命中。
- 规模：大（迁移咽喉）。阶段 E1 立表、E2 切读、E3 收缩。

---

## 4. 目标态架构

### 4.1 分层

```
写入方（5 上游）
  人工录入 / 文件与 URL 导入 / 外部抓取 / 渠道同步 / 对话后处理结晶
                          │
                          ▼
        KnowledgeAdmissionGate.admit()        ← 唯一写咽喉（§5）
   normalize → resolve → adjudicate → conflict → record → digest → index
                          │
                          ▼
     KnowledgeFactStore（data/knowledge/knowledge_facts.db）  ← 唯一权威源
     ┌────────────────────────────────────────────────┐
     │ 身份层  knowledge_subjects                    │
     │ 事实层  knowledge_facts                       │
     │ 溯源层  knowledge_assertions / _activities /  │
     │         _derivation_edges / _lineage_heads    │
     │ 治理层  knowledge_conflicts                   │
     │ 叙述层  knowledge_narratives / _chunks        │
     │ 本体层  ontology_terms / _rules / _rule_fires │
     │ 评测层  evaluation_cases / _runs / _findings  │
     └────────────────────────────────────────────────┘
        │            │             │            │
        ▼            ▼             ▼            ▼
   条目投影      图投影        时效事实投影   经验投影
 （叙述/版本） （可视化+多跳）  （SPO+窗口）  （EKB，独立域）
        └────────────┴──────┬──────┴────────────┘
                            ▼
        读路径：四路 RRF + 时效/置信项 + rerank + 图检索器（§7）
```

投影层不持写权：所有既有门面（`KnowledgeRepository` / `KnowledgeGraphManager` / `ExperienceKnowledgeBase`）在 E3 前保留双写，E3 后降为只读视图或薄适配层。

### 4.2 表设计要点（13 表）

**身份层 `knowledge_subjects`**
`subject_key` PK、`canonical_label`、`type_term_id`→`ontology_terms`、`aliases_json`、`first_seen_at`、`merged_into`（自指链，收敛后禁止悬空）、`status`。吸收 `manager.py:66` 的 `aliases` 语义。

**事实层 `knowledge_facts`**
以 `temporal_knowledge_graph.py:181-196` 形状为骨架：`fact_id`、`subject_key`、`predicate_term_id`、`object_term`、`relation_kind`（literal / entity）、`qualifier_json`、`confidence`、`evidence_state`、`status`、`supersedes_fact_id`、`contradicted_by_json`、`valid_from`、`valid_until`、`recorded_at`、`retracted_at`；沿用 EKB 词汇：`assertions_json`、`source_turn_id`、`injected_count`、`last_injected_at`、`adoption_outcome`；新增 `assertion_count`、`latest_adoption_outcome`。（019b-1 又加 `record_kind`：`triple` / `narrative`，默认 `triple` 让既有行零改写。）（实施复核：`contradicted_at` 未建列——矛盾时刻由 `knowledge_conflicts.detected_at` 承载，不重复存一份。）

**两列三值的分工（工单 008 实施中定清，原工单文本把两件事混写了）**：
`evidence_state` 是 `NOT NULL DEFAULT 'unevidenced'` 的显式三值（evidenced / unevidenced / failed），
承载"**形成侧**有没有证据"；"从未回写"这个第四态由 `adoption_outcome` / `latest_adoption_outcome` 的
**NULL** 承载，承载"**采纳侧**有没有结果"。两个问题正交，不能用同一列表达。

**溯源层四表**
- `knowledge_assertions`：`assertion_id`、`fact_id`、`actor_type`（agent / user / pipeline / importer）、`actor_id`、`activity_id`、`medium_ref`（`ingest_queue` 的 `source` 列值 / URL / session id）、`statement_text`、`asserted_at`、`weight`、`verification_state`。
- `knowledge_activities`：`activity_id`、`activity_kind`（admit / normalize / extract / resolve / adjudicate / import / derive / retract）、`started_at`、`finished_at`、`inputs_json`、`outputs_json`、`basis`、`tool_version`。`admit` 为实施期补：咽喉若不建活动，"经哪条管线进来"这一维对直写路径恒空。
- `knowledge_derivation_edges`：`derived_fact_id`、`premise_fact_id`、`derivation_id`、`rule_id`、`derivation_kind`。
- `knowledge_lineage_heads`：`head_id`、`scope`（entry / activity / global）、`last_seq`、`last_digest`、`updated_at`。

**治理层 `knowledge_conflicts`**
`conflict_id`、`kind`、`subject_key`、`predicate_term_id`、`member_fact_ids_json`、`severity`、`recommended_policy`、`policy_basis`、`status`（pending / auto_resolved / resolved / dismissed）、`detected_at`、`resolved_at`、`resolution`、`resolved_by`。

**叙述层**：`knowledge_narratives`（承 `knowledge.json` 条目字段：`knowledge_id`、`title`、`category`、`tags`、`visibility`、`owner_user_id`、`shared_with`、`submission`、`revision` 快照；**新增 `content_key`**——条目层此前无内容身份列，这是 B03 的根因位）、`knowledge_chunks`（`chunk_id`、`knowledge_id`、`parent_id`、`seq`、`text`、`revision`、`embedding_ref`）。**不含 `confidence`、不含 `source`**（G11、G01）。

> **019a 实施复核（两处偏离，均为主动收窄而非遗漏）**
> 1. **分块不立表**。分块随条目整篇读写，`_item_index_docs` / `_chunk_hit` / `parent_context_text`
>    都只从 `item["chunks"]` 取；把它拆成独立表就是给同一段文字建第二个权威，
>    正是本底座要消灭的东西。列式分块表只在"按块独立检索/独立修订"成为需求时才成立，
>    届时应扩 `knowledge_facts` 而非另立叙述副本。
> 2. **`content_key` 推迟到 019b**。内容身份是在 `admit()` 的第一段算出来的，而条目的写路径
>    要到 019b 才转调咽喉；现在就加列只能得到一列恒空，反而掩盖"这条目没经咽喉"这个事实。
>    019a 的 `knowledge_narratives` 因此只有：`knowledge_id` PK、`agent_id`、`owner_user_id`、
>    `visibility`、`shared_with_json`、`category`、`title`、`payload_json`、`updated_at`——
>    成列的字段全是"要按它查询"的，正文与子结构走 `payload_json`。

**本体层**：见 §6。**评测层单独建库** `data/knowledge/knowledge_evaluation.db`（迁移域
`knowledge_evaluation`），不并入底座 13 表——评测器不该与被测对象共用存储：底座一旦写坏，
读数会跟着一起坏，就失去"用独立尺子发现底座问题"的能力。§4.2 的表清单据此理解。

### 4.3 新增模块落位

| 模块 | 类 |
|---|---|
| `neurova/knowledge/foundation/knowledge_facts.py` | `KnowledgeFactStore` |
| `neurova/knowledge/foundation/admission.py` | `KnowledgeAdmissionGate` |
| `neurova/knowledge/foundation/lineage.py` | `KnowledgeLineageLedger` |
| `neurova/knowledge/foundation/digest_chain.py` | `ActivityDigestChain` |
| `neurova/knowledge/foundation/conflict_judge.py` | `KnowledgeConflictJudge` |
| `neurova/knowledge/foundation/redundancy.py` | `RedundancyAudit`（只读冗余审计，004） |
| `neurova/knowledge/foundation/narratives.py` | `NarrativeStore`（叙述层入库，019a） |
| `neurova/knowledge/foundation/foundation_schema.py` | 本域迁移链单主（版本域=库文件=一条注册序） |
| `neurova/knowledge/foundation/entry_ledger.py` | `EntryLedger`（条目↔治理层投影账本，019b-2） |
| `neurova/knowledge/foundation/storage_fence.py` | 生产目录单主 + pytest 会话围栏（001 立，019b-4b 收全四个写入面） |
| `neurova/knowledge/identity/entity_blocking.py` | `EntityBlockingResolver` |
| `neurova/knowledge/identity/similarity_fusion.py` | `SimilarityFusion` |
| `neurova/knowledge/identity/identity_merger.py` | `IdentityMerger` |
| `neurova/knowledge/identity/subject_resolver.py` | `SubjectResolver`（auto/review 双阈值决策） |
| `neurova/knowledge/ontology/term_registry.py` | `OntologyTermRegistry` |
| `neurova/knowledge/ontology/rule_engine.py` | `ForwardChainingEngine` |
| `neurova/knowledge/ontology/derivation_ledger.py` | `DerivationLedger` |
| `neurova/knowledge/ontology/validation.py` | `OntologyValidationReport` |
| `neurova/knowledge/evaluation/retrieval_benchmark.py` | `RetrievalBenchmark` |

既有约束不变：深度模块经 `agent_ref` 访问 Agent；`get_*()` / `reset_*()` 成对工厂；`threading.RLock` 保护共享态；可选依赖惰性 import；LLM 调用必须走 `track_llm_call` 与 `LLMRouter`。

**开关台账**（开闸即搬家、关闸即回退；除标注外默认关＝旧行为）

| 环境变量 | 作用 | 默认 | 现状 |
|---|---|---|---|
| `NEUROVA_KB_FACT_SURFACE` | 011：检索时并入底座事实池（时效/置信排序项） | 关 | **判负保持关**（§8.0） |
| `NEUROVA_KB_NARRATIVE_STORE` | 019a/019b-2：条目权威换到底座库，且装载即把治理层对齐 | **开**（019b-4b 翻向） | 默认即底座库；只有显式 `off/0/false/no/json` 才回 JSON 旧路。回退前先按下方"搬家是单向可逆"的步骤走 |

**搬家是单向可逆的**：开闸首次装载会把 `knowledge.json` 导入 `knowledge_narratives` 并把旧主文件
改名归档（`.pre-narrative-store-<UTC>`），归档保证只搬一次——删空条目后重启不会拿旧快照把已删项复活。
因此关闸（`off`）在搬家之后**不会**静默回到 JSON 权威，而是 `RuntimeError` 指名两条路：
要么保持新后端，要么把归档文件改回 `knowledge.json` 并清空叙述面三张表。
归档动作挂在**构造**上（`KnowledgeRepository.__init__` → `_load`），不是挂在首次写上面——
这决定了测试围栏必须守构造而不是只守 `_save`，见 §11.5 的 019b-4b 事故登记。

两个开关共用同一底座库 `data/knowledge/knowledge_facts.db`（迁移域 `knowledge_foundation`，
当前链尾 v7）。评测层单独建库，不与被测对象共用存储。

---

## 5. 唯一写咽喉：`KnowledgeAdmissionGate.admit()`

七段固定顺序，任何上游都不得绕过：

1. **归一化** `normalize()`：复用 `neurova/core/content_identity.py` 的 `normalized_key:27` / `normalized_payload_key:50`（CJK 2-gram + NFKC），产出**抽取后内容**的身份键并写入 `content_key`。口径从"原始字节 / URL 串"换成内容，直接补掉 B03 的根因位：同一文档换格式重传、同一 URL 带不同 query 串、同一内容经不同入口进来，一律命中同一键。
2. **身份消解** `resolve()`：`EntityBlockingResolver`（G05，确定性、零 LLM）→ 得 `subject_key`；置信不足落人工队列（复用 `resolution.py:247` 的 `list_human_reviews` / `resolve_human` 通路）。
3. **类型与规则裁决** `adjudicate()`：先 `OntologyValidationReport` 校验，再 `ForwardChainingEngine` 求值；推导事实在本段落库，因此后续冲突检测能看到推导结果（不后置于冲突，否则冲突永不涉及推导事实）。
4. **冲突判定** `conflict()`：在同一 `subject_key + predicate_term_id` 上聚合新旧事实判三值——`duplicate` / `contradicts` / `novel`。第 1 段拦住可判定的重复，本段负责把漏网的重复与真分歧**显式成账**：`duplicate` 不再被"不算冲突"打发（`repository.py:1132`），而是产出可计量的账目并进 §8 的重复率读数。**叙述记录另按条目划范围**（019b-4b 由真数据取证补上）：分歧的前提是"两条说法在说同一件事"，条目正文的那件事是这一条条目，不是它的标题——`documented_as` 基数不限，三条同名条目是三份文档。按三元组口径裁决会把活着条目的治理行判成 superseded（实测 5 行 / 10 条目投影永不收敛）。同一条目改正文仍走本段，新说法取代旧说法。
5. **可信度与使用记账** `record()`：`confidence` 由断言聚合得出——`assertion_count` 同值互证计数、`source_turn_id` 时间戳、`contradicted_by_json` 矛盾标记；`policy_basis` 缺失即记 `unevidenced`，禁止写自动裁决。**本定义不等于真值度量**，它只回答"该来源历史采纳后的结果分布"。
6. **血缘与链式记账** `digest()`：写断言、活动、链头（G01、G02）。
7. **入索引**：narrative/chunks/facts 三路进各自索引，图谱投影只作派生视图，不作权威源。

三条硬约束：
- `assertions_json` 为空 ⇒ **拒绝入库**（不允许匿名知识进咽喉）。
- 不接受调用方传入的裸 `confidence`（G11）。
- 咽喉是唯一写入口，`repository.py:514` 处的旁路调用在 E2 收编，E3 删除。

**第四条（019a 期间由真数据取证补上）：咽喉还必须是唯一的"装配点"。**
造门若散在各调用点各写一遍 kwargs，就会各差一段——实测 backfill 少接 `resolver`
（身份消解退回精确名，130 行回填多出 1 个未合并主体），reconcile 少接 `lineage`
（回放绕过"无主知识拒写"，于是 005 的守卫在这条路径上空转）。两处都报自己自洽，
所以这不是"少一条对账判据"，是咽喉被拆成了两个。修法：`admission.productionAdmissionGate(store, toolVersion=…)`
成为唯一造门入口，未接通的段由 `pendingSegments()` 如实报出而不是靠少传参数制造假接通；
常驻判据见 `tests/unit/knowledge/test_gate_wiring_parity.py`。

**合一的方式定了：富化，不是交织**（工单 019b-3）。检索命中一条知识只有一个候选，
底座把 `lineage_id` / `evidence_state` / 派生 `confidence` / `adoption_outcome` 挂到它身上，
排序仍由 002 那把冻结的尺子说了算；`recordHitsAsInjection` 按 `lineage_id` 计数，
010 的触发点自此不再恒 0。叙述记录的 `source_turn_id` 由咽喉兜底成 `entry:<kid>`——
客体换成内容键之后，那是"这条治理行属于哪条条目"的唯一落点。

**试过又撤回的一步（留证据）**：把内容/三元组唯一索引改成"只管 active 行"以支持 A→B→A 代际。
实测 130 行旧库从"预测 92 = 实跑 92"变成"预测 92 ≠ 实跑 102"，因为被裁决取代的行不再吸收
同内容——**内容去重变成裁决顺序的函数**，比它解决的问题更糟。已撤回并重放生产底座库到 v5。

**登记的开洞（不修，需时另立工单）**：正文改回原样 A→B→A 无法在两行之间选出生效者——
`ux_fact_agent_content` 禁止同 agent 出现两条同内容键的行，而取代不改 `recorded_at`，
"谁新谁生效"在时间轴上不成立。当前行为是报投影分叉、不猜（用例钉住）。
真要修，方向是给内容身份加代际维度，或把取代关系挪到带生效时刻的独立表。

**记录种类（工单 019b-1 补）**：咽喉认两种记录——`triple`（主体-谓词-客体）与
`narrative`（一条知识文档）。条目走咽喉不是为了被伪造成三元组，是为了拿到它以前没有的
四件东西：内容身份、消解后的主体、断言与活动、由断言聚合的置信度。因此叙述记录的谓词由
咽喉固定（`documented_as`）、客体就是条目的 `knowledge_id`、**事实行有意不存正文**
（正文唯一副本在 `knowledge_narratives.payload_json`，事实行只带指纹与治理字段）。
代价是一个刻意的中间态：`searchableFacts()` 默认不收叙述行（收进来就是一池空文本），
两池真正合成一池要等 019b-3 把"按 `object_term` 回查正文"接上。

**叙述记录以内容键立身，条目 id 记在溯源里（019b-2 实测定的）**：
条目 id 编辑前后不变，若拿它当客体，三元组唯一索引会把每次正文改写吞回同一行，
旧说法永不退场。所以 `record_kind='narrative'` 的行客体就是内容键（无内容身份时才退回条目 id），
条目 id 落在 `source_turn_id`（实时写 `entry:<kid>`、回填 `legacy:<kid>`）。
取代由冲突裁决做（它有 `policy_basis`），投影账本只做"按全集认领 + 无人认领则 retract"。

**迁移链单主（实施期立的结构约束）**：一个 SQLite 文件只有一个 `user_version`，
⇒ 一个库 = 一个版本域 = 一条注册序。本域的表分散在多个模块，注册必须由
`foundation/foundation_schema.py` 单主集中完成（SQL 仍由各模块持有），否则后注册的
低版本会在导入期被判"版本必须严格递增"直接抛错。往本域加迁移只改那一个文件。

---

## 6. 本体与推理（自研，零新增依赖）

### 6.1 为何是 Datalog 形状
底座是属性图 + 时效事实，规则需要"从已有事实得新事实"并可撤销。Datalog 形状（head :- body）配分层求值即可保证否定一致，且能直接落到 SQLite 递归 CTE；不采用图遍历式规则，因为遍历无法表达跨谓词连接。

### 6.2 本体三表与五条校验
- `ontology_terms`：`term_id`、`kind`（class / individual / object_property / datatype_property / annotation）、`parent_term_id`、`domain_term_id`、`range_term_id`、`cardinality`、`disjoint_with_json`、`required_props_json`、`version`。取代 `manager.py:23,38` 两个 Enum（G08），既有 10 + 15 值作为初始条目导入。
- `ontology_rules`：`rule_id`、`head_pattern`、`body_pattern_json`、`negation_as_failure`、`stratification_level`、`trust_class`、`version`、`enabled`。
- `ontology_rule_fires`：触发账本（`rule_id`、`binding_json`、`fired_at`、`produced_fact_id`）。
- `OntologyValidationReport` 五条：域与值域、基数、父子一致性、不相交公理、必填属性。违规只报不吞，且必须可定位到 `fact_id`。
- 互操作导出：自拼 RDF/Turtle 文本（纯格式化，不新增依赖）；**不做 SPARQL 文本查询**，查询面为程序化 API + REST。

### 6.3 推理引擎
`ForwardChainingEngine`：分层前向链（`stratification_level` 升序）→ 每层物化用递归 CTE 求传递闭包 → 命中写 `knowledge_derivation_edges`（`derivation_kind='inferred'`）与 `ontology_rule_fires`。`DerivationLedger` 支持按规则版本或前提集合精确撤销推导事实。检索时事实与推导事实合并返回，推导事实带 `derived_from` 前提集（不静默混入）。

---

## 7. 读路径改造

- 四路 RRF 单源语义不动（ADR 0007；`hybrid.py:104`），候选池扩为"事实 + 叙述段"双类命中。
- 排序式新增两项：`freshness_term`（读 `valid_until` / `recorded_at`，`expired` 项过滤）、`confidence_term`（G11 落地前恒为 1 并标 `unevidenced`）。整体置于可关闸配置下，关闭后行为须与基线逐条一致。
- rerank 从旁路升为主路末端可关闸段（B05），复用 `knowledge/rerank/` 的 `WeightRerankRunner` / `ModelRerankRunner`。
- 图检索注册为一等 retriever（B04），多跳走递归 CTE；`chat_pipeline.py:220-276` 的注册序保持 ADR 0005 的 `MemoryRetrievalChain.add_retriever` 单点纪律。
- B01 处置：TKG 检索器不再指向 `:memory:`，改指 `KnowledgeFactStore`；`extract_facts_from_memory` / `sync_memory_to_tkg` 由"接线"改为"删除并由咽喉段 2–3 取代"（净 LOC 下降）。
- 检索结果携带 `lineage_id`，答案可回指第 X 条依据；`citation.py` 的句柄机制从记忆域扩到知识域。

---

## 8. 验收判据（主锚：离线检索评测集）

- 三表：`evaluation_cases`（`query`、`expected_fact_keys_json`、`domain`、`created_by`、`frozen_at`）、`evaluation_runs`、`evaluation_findings`。
- 抽样自生产真实数据（§1.2 的 130 条 + EKB 真实记录），**禁止以 MagicMock 冒充检索对象**；每案可溯源到一个原始来源。
- 读数：`recall@5`、`MRR`、零命中率、冲突误报率与漏报率（人工抽样标）、消解错合率与漏合率。
- 基线在 E1 动工之前冻结一次，此后只追加不覆盖；每条工单必须声明它改动哪个读数及期望方向，读数不升即回退该切片。
- 三态纪律（ADR 0016）：读数取不到即 `unevidenced`，绝不按 `passed` 处理。
- 治理指标（溯源覆盖率、重复率、零使用条目占比、TKG 命中率从 0 到有）为辅证，不单独作为"变好了"的结论。

### 8.0 011 否证结果（2026-09-20）
读面开闸在同语料同尺子下 recall@5 0.855489 → **0.760371**、未命中率 0.100 → 0.167：
两池秩交织让短事实凭 BM25 优势顶掉强叙述命中。**011 不启用**，E2 读路径改走 019 先行
（事实成权威源后不存在两池）。关闸态与基线逐位一致，旧行为未受影响。

### 8.1 E1 前冻结的真实基线（工单 002，2026-09-20 实测）

台架：`neurova/knowledge/evaluation/retrieval_benchmark.py`，库 `data/knowledge/knowledge_evaluation.db`，
30 例（title_literal 24 / tag 3 / category 3），top_k=5，走 `hybrid_search_knowledge` 真检索路
（本地 ONNX `bge-small-zh-v1.5` 512 维在位，四路齐活）。

| 视角 | recall@5 | MRR | 未命中率 |
|---|---|---|---|
| **admin 全语料**（基线，run `evr_3a1abc27c977`） | **0.8555** | **0.8300** | 0.1000 |
| owner=u1 私库视角（对照） | 0.7013 | 0.7111 | 0.2667 |

三条必须一起读的结论：

1. **读数绑身份**：同一份标注仅因可见性上下文不同就差 15 个点，故 `evaluation_runs.context_json`
   是读数的组成部分，不是备注。E2 对比必须在同一 context 下比。
2. **自动标注偏管路**：现库 category/tag 取值太少，去重后 30 例里只有 6 例非标题口径。
   这批数说明"检索管路基本通"，**不足以**证明语义质量好——语义判据需人工标注追加，
   已登记为后续票（002 后置：人工标注 ≥30 例语义 query）。
3. 3 例未命中全是泛化词（`architecture` / `general` / `big_verify`），属预期：期望集是"该类全部条目"，
   top-5 装不下一整类。它们的处置见 E2 的时效/置信排序项票。

**基线可复查性（011 启动前复核，2026-09-20）**：重放同语境跑出 `0.855489 / 0.83 / 0.1`
与冻结值**逐位一致**，未命中仍是同样 3 例，基线行未被覆盖（`is_baseline=1` 仍 1 条，runs 追加）。
case 集与基线摘要已导出入库：`tests/fixtures/knowledge_eval_cases.json`（30 例，含口径标注）、
`tests/fixtures/knowledge_eval_baseline.json`（读数 + 身份上下文 + 未命中清单）。

**边界必须说清，别把"可移植"说过头**：case 集入库只防住"query 被悄悄改掉"这一种漂移；
`expected_ids` 是本机 `data/knowledge/knowledge.json` 的 knowledge_id，而 `/data/` 在 .gitignore 内。
因此基线**仍与本机语料绑定**——换机器跑会得到 0 命中而不是 0.8555，那不代表检索变差。
011 的对比必须在同一份语料上做；要跨机器可比，需把期望集改用 content_key 表达（已登记为后置项，
不混进 011 的判据里）。

---

## 9. 阶段划分与出口判据

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **E0 前置** | ~~修测试隔离~~ 已由 001 改判：无活跃污染源，改为在 `repository.py` 立**测试会话写入围栏**（防未来污染）+ 登记 §11.5 预存失败；冻结 §8 基线 | 全仓测试跑完后生产目录读数不变（001 实测时该读数就是 `knowledge.json` 哈希；019b-4b 默认翻向后改为**底座库叙述面 + 归档件**两者不变，围栏必须守构造而非只守 `_save`）；围栏守卫测试可红可绿；评测基线落库 |
| **E1 立骨** | 底座表分票落地（身份/事实/溯源/治理 + 评测层独立库）；`admit()` 咽喉接通段 1/2/4/5/6；条目库暂未降级（双写面见下） | **已达成（015 实测）**：旧库 130 行 → 预测 92 事实 = 实跑 92，主体 87 = 87，差异为空；38 行纯冗余 / 19 组 / 3 个 agent 域 |
| **E2 切读** | 检索链逐 retriever 从旧库改指底座；§7 排序项与图检索器接入；G07 回写通路；G04 策略账 | §8 读数相对基线不降；关闸后与基线逐条一致；B01/B04/B05 转绿 |
| **E3 收缩** | 删除三套冲突实现中的两份、`repository.py` 旁挂账本与旁路写、`extract_facts_from_memory`/`sync_memory_to_tkg` 死码；`NodeType/RelationType` Enum 退役为初始条目 | 净 LOC 显著下降；无残留调用方（grep 证明） |
| **E4 开闸** | 本体注册表 + 五条校验、Datalog 规则与前向链、G05 消解重写、G02 链式校验 | G05/G08/G09 各自判据成立；推导事实可精确撤销 |

与 `agent_core` 拆分（Phase 2–7，`docs/04-plans/agent-core-decomposition-plan.md`）串行：E2 与 E4 触碰 `chat_pipeline.py` 检索装配段，不得与拆分同批开工。

---

## 10. 风险登记

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | E1–E2 双写期数据分叉，底座与旧库读出不同答案 | 每阶段出口判据含对账巡检；差异即阻断推进，不带病进入 E2 |
| R2 | 与 `agent_core` 拆分抢同一段装配代码 | §9 串行约束；E2 前确认 Phase 2–4 落地状态 |
| R3 | E1 backfill 把 38 行纯冗余显式化，冲突/重复待审队列骤增 | 属预期；队列增长写进 E1 验收读数，不当故障处理 |
| R4 | 自动抽取引 LLM 成本 | 抽取只在异步 worker（`ingest_worker.py:21`）跑，不阻塞对话轮；必须经 `track_llm_call` + `LLMRouter` |
| R5 | 测试夹具持续污染生产库，使评测基线漂移 | E0 为硬前置，不修不开工。019b-4b 后污染面变大（构造即搬家），围栏相应上移到构造函数；代价是"测试里只读生产目录"也不再可行，这是有意的 |
| R6 | 完全自研本体与推理造成大块新代码，违背"简单优先" | 明确不做清单：SPARQL 文本查询、OWL DL 完整语义、外部服务后端、双写多模存储；规则形状固定为 Datalog 单形态 |

---

## 11. 待复核项（不得当已证事实引用）

1. ~~生产库中 `import:note.txt` 这类夹具来源写入的通路~~ → **已于 2026-09-20 工单 001 证伪**：
   全仓 6 个含这些夹具文件名的测试文件逐个跑完，`data/knowledge/knowledge.json` 哈希均不变；
   宽口径跑 `tests/unit tests/api tests/integration tests/e2e` 亦不变。这些条目按 `created_at`
   聚成历史批次（2026-09-07 08:55 一分钟 32 条、2026-09-16 22:37–22:41 三批各 10 条），
   与 AGENTS.md 所记 tests/ 根目录退役件归位日（2026-09-16）重合 ⇒ 定性为**历史非隔离运行残留**，
   不是活的测试缺陷。防回归改为常驻写入围栏（`repository.py` 的
   `_assertNotWritingProductionUnderPytest`，测试 5 用例）。
2. `data/knowledge.db`（仓内存在）归属——代码未见引用。
3. 文档 `docs/01-architecture/24-knowledge-isolation-rag.md`、`docs/09-dev-progress/module_designs/knowledge_base.md`、`docs/数据库图谱.md` 与代码的一致性（本次未通读比对）。
4. `graph_node_ids` 覆盖 26% 是否有对应的运行时补写通路（未见，但不排除由远程 KB 侧写入）。

### 11.5 预存失败登记（2026-09-20 工单 001 期间实测，非本批引起）

`tests/unit/api/` 下 15 个失败：`test_transfers_wave_h4.py`(7)、`test_files_store_persistence.py`(4)、
`test_skill_pool_api_rlock_protection.py`(2)、`test_my_skills_wave_v.py`(1)、`test_public_library_wave_h3.py`(1)。
归因方法：把本批写入围栏用补丁摘掉后同样 15 失败 ⇒ 与本批无关；日志显示失败面在 `skill_service`
（"No manifest found, starting with empty skills"）与文件库，属技能/文件域，且这些测试文件本身 tracked 未改。
处置：登记不修（越界），E2 出口判据要求这 15 个不新增失败。

2026-09-20 011 实施期又登记 1 个，同样非本批引起：
`tests/unit/core/test_agent_skill_packer_init.py::test_has_correct_param_name` 断言
`agent_core.py` 源码含 `min_pattern_occurrences=`，而 `neurova/agent_core.py` 与
`neurova/skills/experience_knowledge_base.py` 此刻都在他人的未提交改动里。
本批未触碰这两个文件（提交面只有 `neurova/knowledge/`、`neurova/agent/knowledge_retriever_adapter.py`、
`neurova/api/endpoints/knowledge_core.py`、`tests/`、`docs/`）。全量口径：`tests/unit` +
`tests/api` + `tests/core` 2369 passed / 1 failed（即上述这个）。

2026-09-20 019a 实施期再登记 1 个**收集期阻断**：
`tests/unit/evolution/experience/test_objective_tickets.py:148` 是一条被截断的中文断言字符串，
`ast.parse` 直接 SyntaxError。该文件 untracked（他人正在写的在途件，本批从未触及 evolution/experience 面），
但收集错误会 `Interrupted` 整轮会话——全量口径必须再加一条 `--ignore=tests/unit/evolution/experience`。
不代修：改了会把别人的半成品断言按我的猜测定形。

2026-09-20 019a 期间按 `tests/unit tests/api tests/core -v` 全量口径再登记一批失败，
同样非本批引起（该轮跑到 89% 被 neurflow 那类 30s 超时杀掉会话，所以清单不保证穷尽）：
`tests/unit/cognitive/test_pattern_crystallizer.py`(7)、
`tests/unit/cognitive/test_cognitive_graph_integration.py`(4)、
`tests/unit/test_crystallized_simple.py`(1)、
`tests/unit/security/test_p1_6_skill_guard.py`(1)、`tests/unit/models/test_cost_tracking.py`(2)、
`tests/integration/test_knowledge_evolution_loop.py`(3)、
`tests/integration/test_crystallized_experience_integration.py`(2)。
判据：失败断言全在"结晶是否落库/是否通知进化"这一族（`assert engine.store.call_count == 1` 实得 0），
而被断言的 `neurova/cognitive_layers/memory_layer/pattern_crystallizer.py` 此刻正处在他人未提交改动里
（+181 行），且该文件对 `neurova.knowledge` 的 import 数为 0 —— 本批改动集
（`neurova/knowledge/**`、`tests/unit/knowledge/**`、`docs/`）与它无交集。
同日工作树里新出现的 `docs/specs/2026-09-19-experience-quality-gate*` 也指向同一族在途改造。
处置：登记不修，归因留给该批负责人。

**仅在全量排序下才失败、单独跑通过的 2 例**（交叉污染，不是本批引入）：
`tests/unit/knowledge/test_rerank_refine_weknora.py::TestAPIWiring` 的
`test_default_off_preserves_contract` 与 `test_top_k_applied`——
单独跑该文件 24 passed。要查得从别的模块对 `semantic_search_api` / rerank 配置的污染入手，
别改这两个用例本身。

**`tests/unit/api/` 的失败面正在被人实时改写，别拿它当基线**（2026-09-20 晚实测）：
同一目录、同一份本批代码，间隔十几分钟两次跑出 25 failed 与 15 failed；与 `tests/unit/core/`
并跑时 37 failed + 2 errors。波动的一族是 artifacts / console events / agent package /
workspace zip / load saved agents（`test_console_artifact_events.py` 11、
`test_load_saved_agents_missing_dir.py` 4、`test_artifacts_registry.py` 4、
`test_agent_package_api.py` 2、`test_workspace_zip_offloop.py` 2 error）。

归因先摆证据：这些文件与被测模块**此刻正在另一个代理手里改**——`neurova/core/agent_workspaces.py`
mtime 09:02、`test_console_artifact_events.py` 09:20、`test_agent_package_api.py` 与
`test_artifacts_registry.py` 09:21，而我的两次跑分别在 09:12 与 09:24。
本段先前写的"失败随顺序与会话并发变化（争同一份磁盘状态）"是**未经核实的假设**，在此改口：
数字变动来自别人在改那批文件，不是测试顺序。

与本批无关的判据仍然成立：**把 `tests/unit/knowledge/` 与两个守卫全部摘掉，只跑 `api + core`
仍是 37 failed**，而 `knowledge + core` 只有 1 例（已登记的 `test_agent_skill_packer_init`）。
本批口径因此固定为：以 `tests/unit/knowledge/` 与 `knowledge + core` 两个窄口径为准，
api 域只认"已登记的 15 例不新增"，那族在途文件不计入本批信号。

另有 `tests/benchmarks/test_multi_agent_coordination.py:413` 未导入 `Optional` 导致全仓收集中断——
该目录未入库（`??`），属他人在途件，本批不触碰，跑套件时需 `--ignore=tests/benchmarks`。

**跑全仓套件的第二个阻断点（2026-09-20 实施期实测）**：
`tests/unit/neurflow/test_approval_reply_mechanism.py:48` 的 `asyncio.run(exec_approval(...))`
挂满 30s 触发 pytest-timeout，而本仓 timeout 方法为 `thread`（Windows），超时即**杀掉整个会话进程**，
输出只剩一段栈回溯——表现为"跑不出结果"而不是"有一个失败"。
判据：`pytest tests/unit tests/api --ignore=tests/benchmarks` 无法产出 passed/failed 汇总；
加 `--ignore=tests/unit/neurflow` 后可跑完。归因未做（属 neurflow 在途面），
E2 出口判据要求：**要么该用例修好，要么给出可控的超时口径**，否则任何全仓验证都是假绿。

**019b-4b 期间再登记两个全仓阻断点（本批未触碰这两处代码，归因未做）**：
`tests/unit/embedding/test_onnx_onnx_path_thread_safety.py::test_concurrent_encode_batch_updates_stats_atomically_onnx_backend`
单独跑 2.67s 通过，全仓跑挂到超时并杀会话；
`tests/unit/test_start_script*.py` 一族里有一条真的走到 `start.py:restart_services →
_open_chat_browser → webbrowser.open`（该函数在别的用例里被 patch 掉，这条没有），
在 Windows 上卡在 `shutil.which` 的枚举里直到超时。两者都属"跑不出汇总"而不是"有一个失败"，
所以全仓口径必须逐条 `--deselect` 或 `--ignore`；本批因此以窄口径为准（见本节末与 §11.6）。

### 11.6 实施进度快照（E0/E1 完成、E2 判据改序、E3 提前落刀）

| 工单 | 状态 | 证据 |
|---|---|---|
| 001 写入围栏 | 完成 | 5 用例；生产库哈希跑测前后不变 |
| 002 评测台架 | 完成 | 18 用例；基线 recall@5 0.8555 / MRR 0.8300 已冻结 |
| 003 底座立骨 | 完成 | 16 用例 + 2 迁移版本用例；两表全列 + admit 骨架 + 缺段显式抛 |
| 004 内容归一段 | 完成 | 12 用例；审计复现 130/92/38/19 组 |
| 005 溯源段 | 完成 | 17 用例；匿名断言写入前即拒 |
| 006 确定性消解 | 完成 | 25+5 用例；零 LLM 静态守卫、候选对 < 600（全对 19900） |
| 007 冲突一等对象化 | 完成 | 9+7 用例；kind 全覆盖、`policy_basis` 缺失即拒、无证据不许自动裁决 |
| 008 事实生命周期 | 完成 | 41 用例；supersede/expire/retract，只加行为不改表 |
| 009 置信聚合 | 完成 | 断言数/异质度/可重放/矛盾惩罚四因子；无断言为 NULL 不是 0 |
| 010 使用与采纳回流 | 完成 | 17 用例；注入/采纳两本账，`success/failure/unevidenced` 三态 |
| 015 双写对账 | 完成（019a 期间补判据并重做） | 真数据 130 行 → 预测 92 = 实跑 92 = backfill 92；主体 87 三方同数（原先 backfill 88，根因是造门各自装配） |
| 011 读路径切底座 | **实施后判负，留在关闸态** | 开闸 recall@5 0.7604 / MRR 0.8111 / 未命中 0.167，劣于基线；见 §8.0 |
| 019a 叙述层入库 | 完成 | 19 用例 + 真数据对等（读数三位相同，见 §8.1 口径）；默认关闸 |
| 019b-2 条目写路径转调咽喉 | 完成（含 restore 投影） | 16 用例；叙述行按内容键立身；取代归裁决；装载即对齐 |
| 019b-4a 冲突旁账收编 + source 派生 | 完成 | 9 用例；v7 建 knowledge_entry_conflicts；source 改派生，真数据只动 3/130 |
| 019b-2c 墓碑收编进底座库 | 完成 | 9 用例；v6 建 knowledge_tombstones；两个边界换后端，12 个调用点零改动 |
| 019b-3 读面合一为富化 | 完成 | 6 用例；排序零改动接上治理字段与注入回流；代际方案试过并撤回 |
| 019b-1 记录种类进咽喉 | 完成 | 14 用例 + 真数据三方同数（92/87 一字未动）；底座库 6.26MB→4.24MB |
| 019b-4b JSON 条目路径退役 | 完成（生产已搬家） | 默认翻向底座库；围栏守构造并收全四个写入面（`storage_fence`）；叙述冲突按条目划范围；生产 130/92/87 分叉 0，基线两侧同 0.855489/0.83/0.1 |
| 012 / 013 / 014 / 016 / 017 / 018 / E4 | 未开工 | 011 否证后落点改变，见工单索引"进度" |

`tests/unit/knowledge/` 543 passed（起点基线 265）。019b-4b 的爆炸半径口径：
条目 / 向量 / 评测 / api 消费方一起跑 488 passed、46 skipped、0 failed。
副作用已量过：`tests/unit` 在放宽前后收集到同样 15678 条用例（差集为空），
所以 `python_functions` 加 `test[A-Z]*` 不改变任何现有用例的运行与否，只是防未来再踩。

新增常驻守卫 2 条：生产库写入围栏用例、pytest 收集卫生守卫
（`test_pytest_collection_hygiene.py`——实施期三次把用例写成 `def testXxx` 导致整份文件静默不跑）。
迁移链守卫 `test_everyTableExistsAfterMigrationChain` 随 v4 一并抬到 `user_version == 4`，
并把 `knowledge_narratives` 纳入必查表集。新增 §5 第四条硬约束（咽喉必须是唯一装配点）与
常驻判据 `test_gate_wiring_parity.py`（6 例）。生产回填产物已在统一装配下重跑并留档
`.pre-20260920-gateparity`；`data/knowledge/knowledge.json` 哈希 `e0ea2a4524e7` 全程未变。

### 11.7 本批自伤事故登记（019b-4b，2026-09-20 晚，本批引起）

**事实**：`tests/unit/knowledge/test_default_storage_write_fence.py::test_fenceIsWhatStopsTheWrite`
为证明"围栏是唯一拦阻者"，把 `PYTEST_CURRENT_TEST` / `PYTEST_VERSION` 清掉后指向**真生产目录**。
默认值一翻向底座库（同一切片内），这条用例就在测试会话里跑了真的一次性搬家。

**证据链**（不是推测）：
- 归档时刻与用例窗口重合：`knowledge.json.pre-narrative-store-2026-09-20T095630001368+0000`、
  `knowledge_conflicts.json.pre-narrative-store-2026-09-20T095630564987+0000`；
- 隔离库 `knowledge_facts.db.polluted-20260920T1005` 的 `knowledge_narratives` 是 **131 行** =
  130 行真数据（`default` 104 / `kai` 24 / `ag` 2）+ 1 行
  `agent_id='guard-probe', knowledge_id='k1', title='t'`，与那条用例 `_withItem()` 探针逐字同名；
- 治理面同步长成 93 事实 / 88 主体，比 015 基线 92 / 87 各多 1，多的正是探针那一行。

**处置**：污染库改名留证未删；`knowledge.json` 与 `knowledge_conflicts.json` 从归档改回，
哈希回到登记值 `e0ea2a4524e7`（130 条）；生产库删除后按设计重放一次搬家；
用例改成指向 `tmp_path` 下的假生产目录，证明力不减。

**根因不在"忘了加守卫"，在守卫的边界与权威的位置不再重合**：围栏是 pytest-only 的，
它挡不住"用例自己把标记摘掉"的用法；而 019b-4b 之后**读路径本身就是写路径**（构造即搬家），
所以"摘掉标记去证明拦阻者"这个动作在 JSON 时代无害、在底座库时代就是真写。
修法因此是两条：围栏上移到构造（§4 开关台账），以及把"清标记的用例只准指向假生产目录"
钉成该测试文件的抬头铁律 + 一条专名反向判据（`test_readPathCutoverIsRealAndUnfencedOutsidePytest`）。

同一次翻向顺带挖出两处根因，细节与判据都在 `tickets/019b4b-JSON路径退役默认翻向.md`：

- **围栏只守对象、路径却抄了四份**：`data/knowledge` 在条目仓库 / 事实底座 / 评测账本 /
  向量索引各抄一份，于是守住仓库之后 `get_knowledge_fact_store()` 的默认路径照样在
  生产目录里建出底座库。修法是新建 `foundation/storage_fence.py` 同时拥有"生产目录是谁"
  与"pytest 内不许碰它"，四个模块一律派生，判据扩成"目录本身或其中任何文件"，
  并留一条"路径只准有一份"的常驻判据防第五份被抄出来。
- **条目正文之间按三元组口径互相取代**：见 §5 段4 补的"叙述记录按条目划范围"。
  真数据读数：搬家后 5 行叙述被裁决成 superseded、10 条条目投影分叉且不收敛；
  修完 92 行全 active、分叉 0，plan/reconcile/backfill 仍三方同数 92 / 87。

---

## 12. 遵循的既有约束与下一步

- ADR 0003 分层与深度模块、0005 `NeurovaRecallEngine` 单点注入、0007 RRF 融合单源、0016 三态与量纲纪律（`docs/CONTEXT.md:139-146`）。
- `AGENTS.md`：`agent_ref` 注入、单例工厂成对、可选依赖惰性 import、`threading.RLock`、测试落位 `tests/unit|integration|e2e/<模块>/`、修复教义（根因修复、禁止表面抹除、live-verify、放大视角）。
- 本文档净 LOC 预期：E1–E2 显著为正（新增底座与本体推理），E3 转为净负。这是目标态架构升级的必然形态，超出"bug fix 净 LOC ≤ 0"默认口径，超出行数去向已在 §9 各阶段列明。

下一步：按 §9 阶段顺序用 `to-tickets` 切垂直切片工单（落 `docs/specs/2026-09-20-knowledge-foundation/tickets/NNN-*.md`，回链本文档），首批起于 E0。
