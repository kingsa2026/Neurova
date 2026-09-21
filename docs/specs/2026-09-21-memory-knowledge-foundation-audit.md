# 记忆与知识底座现状审计（2026-09-21）

> 范围：`neurova/mem_core.py`、`neurova/memory_agent.py`、`neurova/memory_layer/`、
> `neurova/cognitive_layers/**`、`neurova/knowledge/**`、`neurova/agent/chat_pipeline.py`、
> `neurova/context/**`，以及生产库实际数据。
> 方法：**以代码与库内数据为准**，文档与注释仅作对照。全程只读（`sqlite3` 以
> `file:...?mode=ro` 打开），未运行 pytest，未修改任何文件。
> 基线提交：`ce840604`。所有 grep 排除 `NeurUI/src-tauri/**`（后端源码的构建期副本，
> 在其中命中的"消费方"一律是假命中）。
>
> 本条目的每一条断言都经过二次复验（子代理取证 → 独立复核 → 主控亲验矛盾类断言）。
> 复验推翻或收紧的内容集中记在 §10，正文只写复验后的口径。

---

## 0. 一页结论

1. **主干是真的，旁支是多的。** 记忆的写（`remember`）、检（责任链）、忘（贝叶斯衰减）、
   固（睡眠期聚类合并）四条臂都在生产路径上且被真实触发；但主干周围漂着 **15 个零生产
   消费者的实现件**（§8-B01），其中两处一旦被调用即静默返回错误字典或 AttributeError。
2. **"17 维记忆分类体系"不成立。** 代码里没有任何 17 维结构；生产实际生效的分类是
   6 个硬编码关键词桶，且与 `MemoryCategory` 的 7 个枚举只重合 2 个名字。
3. **知识底座是"有 schema、无人口"。** 本体表结构齐备（继承/定义域/值域/基数/不相交/
   必填属性），推理管线也接通了，但 92 条事实 **100% 是 `narrative`、0 条 `triple`**，
   0 条规则、0 个冲突、87 个主体无类型。直接后果：**底座默认读面恒定返回 0 行**。
4. **图谱的写面与读面是两张图。** 抽取产物落在 JSON 属性图（实测 175+ 节点、159+ 边），
   答题读的是底座事实表；**没有任何代码路径能把前者搬进后者**（反例已逐一排查）。
5. **真值维护机制齐备但零使用**：bi-temporal 四列、supersede、冲突账本、采纳回写
   全部存在，全部 0 行数据。**"接了没通电"，不是"没接线"** —— 这条区分决定修复成本。
6. **写围栏只覆盖知识侧，且只在 pytest 下生效。** 记忆库没有任何同类保护，实测被
   **71,378 行（99.37%）** 测试数据污染，主污源是 `test_agent_*`（82%）而非 `engine_it_*`。

---

## 1. 记忆主干：写 / 检 / 忘 / 固

**写**：`memory_layer/manager.py:827 remember`（默认温度 65、importance 50）。内容门命中
即返回旧 id、只刷 `updated_at`（`manager.py:968-986`）——即同作用域同内容的**新证据无法
取代旧行**。生产写入方为 `post_chat_pipeline.py:1071/1078`（每轮两条 episodic）与
`mem_core.py:1138/1145`。

**检**：见 §4。

**忘**：`memory_layer/temperature.py` —— `on_access:137`（升温）、`on_decay:203`（衰减）。
不衰减的三条硬规则：温度 ≥80（`:293`）、空闲 <1 天（`:302`）、已固化（`:284`）。
执行者 `manager.py:2063 run_decay_cycle` ← `agent_core.py:1948`、
`api/endpoints/memory/crud.py:211`，并由每轮 post-chat 触发（`post_chat_pipeline.py:666`）。
**注意：默认 `use_semantic=True` 时温度不参与语义排序**（`manager.py:1364-1433`），
仅作过滤与更新对象。

**固**：`memory_layer/sleep.py:581 run_sleep_cycle`，内部按 phase 分派 light_sleep（`:699`）
与 rem（`:704`），做 `cluster_by_similarity:260 → merge_cluster:303 → apply_sleep_decay:397`。
装配 `agent_core.py:1403-1452`；触发有**三条**生产路径：
`agent_shutdown.py:16-35`（启动监控，历史上"从未 start"的断点已修，见 `:19-21` 与
`idle_tracker.py:136-137` 自述）、`agent_shutdown.py:62-84`（关机整理）、
以及**主触发方 `core/idle_tracker.py:154 → :176 → :273`（按空闲分阶段）**。
`manager.py:3299/3313/3338` 的 `run_light_sleep_cycle`/`run_rem_sleep_cycle`/
`run_deep_sleep_cycle` 是**重复实现的第二套**，只被测试引用。

**结晶**：`pattern_crystallizer.py:107 min_observations=3`、`:108 min_success_rate=0.6`，
判定在 `:239` 与 `:267`（成功率分母是"有回执的观察" `:261`），另有第三处门 `:158`。

**版本**：`memory_layer/version_control.py` 有完整 SQL（建表 `:145-183`、读 `:185-203`、
写 `:236-267`），但三条路径的第一道闸都是 `if self._storage is None: return`
（`:147-148`/`:187-188`/`:242-243`），而 `agent_core.py:412-418` 装配时不传 storage。
结果：版本只活在 `:126-127` 的内存 dict 里，进程灭即没。`agent_core.py:399-400` 已自陈。
消费方 `post_chat_pipeline.py:730`（步骤 `version_snapshot`，实现 `:2323-2380`）。

---

## 2. 分类体系：所谓"17 维"

| 断言 | 复验结果 |
|---|---|
| "17 维记忆分类体系"（`AGENTS.md:109`、`docs/CONTEXT.md:62`） | **不成立**。17 只能凑自 `auto_classifier.py:27/39/50` 的 7+6+4 个枚举值，而该文件 549 行、生产消费者 **0**（唯一外部引用是 `manager.py:191` 一个 `= None` 死字段），也未被包 `__init__` 导出 |
| 真正生效的分类器 | `modules/classifier_module.py:32-39`，6 个硬编码关键词桶：`personal/work/knowledge/conversation/emotion/technical` |
| 与 `MemoryCategory`（`models.py:30-39`，7 值：`general/conversation/knowledge/experience/tool_usage/reflection/user_preference`）的关系 | **只重合 2 个名字**（`conversation`、`knowledge`）。写 `personal/work/emotion/technical` 会静默落 `GENERAL` |
| `remember` 是否自动分类 | **否**。函数体内只解析与回落（`:900-925`），无任何推断。`:843` 注释提到的 `auto_classify` 开关全仓无实现分支；`api/endpoints/memory/base.py:74` 仍写"为空则自动推断"——空头承诺 |
| 是否有 LLM 分类器 | **无**。记忆侧 5 处 LLM 用法（压缩/规则抽取/裁决/问句拆解）无一产出 `category` |
| 分类结果去向 | 只并入 `tags`，不写 `category`（`manager.py:2030-2044`） |

**实测数据**：仓库根记忆库 71,831 行中 `general` 71,670 / `conversation` 161；
真实工作区 `kai` 988 行（general 918、experience 47、knowledge 17、reflection 4、
conversation 1、user_preference 1），`default` 324 行（仅 general/reflection），
另两个工作区 0 行。**"99% general" 是根库（污染库）的特征，不能外推到真库。**

**新发现（原调研未收）**：多处生产调用传入**非法枚举值**并静默回落 ——
`meta_cognition_layer/question_queue.py:509` 传 `"system"`、
`memory/scripts/init_memories.py:36/50/63/77` 传 `"creative"/"profile"/"emotional"`、
（死码）`result_processor.py:323` 传 `"resolved_conflict"`。这些值在库里以
`_original_category` 元数据留存，但检索面按 `GENERAL` 参与过滤。

---

## 3. 本体与知识底座

**本体 schema 是真的**：`knowledge/ontology/term_registry.py:25-42` 定义 `ontology_terms`
（`kind ∈ concept|relation|property`、`parent_term_id`、`domain_terms`、`range_terms`、
`cardinality`、`disjoint_with`、`required_props`、`version`），支持继承
（`isSubtypeOf:164`）与定义域命中（`matchesDomain:177`）；`ontology/validation.py:15` 有
6 条规则（domain/range/parentConsistency/disjoint/cardinality/requiredProps），采用
**保守语义："未登记 ≠ 违规"**（`:43-58`）；`rule_engine.py:27-40` 是 Datalog 片段
（模块 `:1-18` 明确不做 OWL DL、SPARQL、外部推理服务）。图谱类型收编（`legacyGraphTerms:245-259`）
与"断言按活动上链"（`digest_chain.py:23-44`、`verify:198`）**均已落地**，92/92 断言带 digest。

**但库里没有人住**（`data/knowledge/knowledge_facts.db`，13 表，只读实测）：

| 表 | 行数 | 关键读数 |
|---|---|---|
| `knowledge_facts` | 92 | `record_kind` **narrative 92 / triple 0**；`predicate_term_id` 100% `documented_as`；`status` 全 `active`；`supersedes/valid_from/valid_until/retracted_at` **全 0** |
| `knowledge_subjects` | 87 | `type_term_id` **0 个非空**（无主体被类型化） |
| `ontology_terms` | 23 | concept 9 + relation 14；`parent/domain/range/cardinality/required_props` **全空** |
| `ontology_rules` | **0** | 前向链管线接通（`admission.py:245` 调 `fireFor`，`:331-334` 装配）但**无规则可推** ⇒ 每轮空转 |
| `knowledge_conflicts` / `knowledge_entry_conflicts` / `knowledge_derivation_edges` | **0 / 0 / 0** | 冲突消解从未发生 |
| `knowledge_assertions` | 92 | `verification_state` **92/92 `unverified`**；`actor_type` importer 89 / user 3 |
| `knowledge_activities` | 92 | `activity_kind` **92/92 `admit`**，`basis` 全等于 `"KnowledgeAdmissionGate.admit"` |

`basis` 这一列是自证铁证：**活动不是管线埋的，是写咽喉自己签的**（`admission.py:269-287`
的注释承认了这点，记为 2026-09-20 端到端冒烟实测）。

**三层口径必须分清（此前两份材料在此处互相打脸）**：

- 条目层 `knowledge_narratives.payload_json`（130 行）：`confidence` = 0.7 ×126、0.9 ×3、0.5 ×1；
- 事实层 `knowledge_facts.confidence`（92 行）：**恒 0.5，distinct = 1**；
- 归因：条目入咽喉时被 `_normalizedRecord`（`admission.py:96-99`）强制改写为
  `documented_as` 叙述记录，聚合置信未跨层存活（写侧硬编 0.7 在 `knowledge_ingestion.py:208`）。
  ⇒ **"条目 0.7 / 事实 0.5" 不是矛盾，是跨层丢失**。任何"给事实排序打分"的想法现在
  都没有输入差异可分辨。

**默认读面恒空**：`knowledge_facts.py:557-575` 的 `searchableFacts(includeNarratives=False)`
追加 `AND f.record_kind != 'narrative'`，而 92/92 全是 narrative ⇒ **底座默认检索面
返回 0 行**。这比"零使用"更彻底：不是数据没用起来，是默认读法把这批数据整体排除在外。

---

## 4. 对话式检索路径

**步数**：`chat_pipeline.py:447/450/454/457/462/465/468/471` 共 **8 个步骤**
（其中 `_step_evocate_injection` 是同步调用，`await` 计数为 7）。
`AGENTS.md:40` 与 `docs/CONTEXT.md` 称"6 步"——**文档滞后两步**。

**装配**（`chat_pipeline.py:203-305`，priority 数值写在各适配器类里而非此处）：

| 检索器 | priority | 定义处 | 生产状态 |
|---|---|---|---|
| AnnotationRetriever | 5 | `agent/annotation_retriever.py:34` | 已接线 |
| UnifiedRetriever | 10 | `agent/retriever_adapters.py:29` | 已接线；内部拼接后按"内容前 100 字"去重（`memory_layer/unified_retriever.py:133`），**各源 score 量纲不同直接混排** |
| MoE | 20 | `retriever_adapters.py:132` | 已接线（4 专家，`mem_core.py:798-820`） |
| Knowledge | 25 | `agent/knowledge_retriever_adapter.py:38` | 已接线（四路定权 RRF，`knowledge/hybrid.py:31`） |
| 时效事实 TKG | 26 | `agent/tkg_retriever_adapter.py:31` | **结构性空转**：`temporal_facts.py:98` 过滤 `record_kind='triple'`，而 triple 为 0 |
| 多跳图 | 27 | `agent/graph_retriever_adapter.py:23` | **结构性空转**：`graph_walk.py:89,98` 同上过滤；env 闸 `NEUROVA_KB_GRAPH_RETRIEVER` 默认开 |
| Cache / Fallback | 30 / 40 | `retriever_adapters.py:235 / :323` | 已接线；Fallback 质量分硬编 0.3（`:375`） |

**责任链语义不是"短路"**（原结论需纠正）：`memory_retrieval_chain.py:388` 是接受判据，
`:390-398` 把命中者分为 `primary` 与 `supplement`（Knowledge 恒作 supplement），
**提前返回只在链里没有 KnowledgeRetriever 时才可能** —— 而生产恒装它，所以
**每轮把所有检索器跑完**，再在 `:409-433` 合并，`quality` 取主源（`:425`）。
写成"首个达标者定主源的短路链"会误导后续改造误删合并逻辑。

**融合面**：RRF 只发生在**源内**（记忆 `manager.py:1418-1430`；知识 `hybrid.py:31`
四路 `tfidf .30 / bm25 .30 / vector .25 / fts .15`，`RRF_K=60`）。**源之间没有统一打分**。
`RetrievalStrategy.PARALLEL/BEST/FALLBACK`（枚举 `:41-47`，分派 `:252-258`）
**只有测试消费** —— 生产三处构造全为 `CHAIN`（`chat_pipeline.py:1569-1574/1637-1642/1709-1714`）。

**精排**：`hybrid.py:208-209` 末端 rerank 已接线、chat 路可达；底座对排序**不投票**，
只作富化（`knowledge_retriever_adapter.py:62-83`，注释记录"两池按秩交织"被真数据否证）。

**自适应二次检索**：`chat_pipeline.py:1584-1594/1608-1660/1680+` 已实现但
`NEUROVA_ADAPTIVE_RETRIEVAL` 默认关。

**前缀缓存自相矛盾（逻辑类，主控亲验）**：`context/orchestrator.py:583-589` 声明顺序设计
"[固定 system 前缀] → [对话历史 append-only] → [记忆调取块] → [瞬态] → [当前输入]"，
并断言"调取块变化只影响尾部，不破坏前缀缓存"；但 `agent/chat_pipeline.py:1935-1938` 的
`_step_evocate_injection` 在召回到 Hebb 时把文本**追加进第一条 system 消息并 break**。
system 消息是提示前缀之首 ⇒ 一旦该分支触发，整个会话前缀缓存失效。
**矛盾成立，且是条件性的**（`neuHebb_manager` 存在且召回非空时才发生）。

**多轮/跨会话**：caller history 优先（`chat_pipeline.py:1496-1500`）、窗口预算折叠 +
跨轮增量摘要（`orchestrator.py:606/1128+`）、工具结果 microcompact（`:612`）、
无损归档与语义调取（`:556-580`）、会话作用域隔离（`chat_pipeline.py:1596-1601`）。
本轮句柄表（`chat_pipeline.py:1509-1520`）会剥掉历史回放/伪造引用——这条是有效的防注入面。

---

## 5. 真值维护、溯源与隔离

**bi-temporal 形状具备、零使用**（§3 表）。读侧权威口径自陈两处且经核实：
`knowledge_facts.py:906-908`"状态是生命周期的唯一权威，读侧只看 status，到期靠显式
`expireDueFacts()` 推进，不起后台线程"；`:560-563`"只额外挡已到期"（实现 `:569-572`）。

**冲突裁决**：`conflict_judge.py:103-137` 政策优先级 `most_recent → credibility_weighted
→ highest_confidence → manual`，**`policy_basis` 为空即不得自动裁决**（`:103-113`）；
人工入口 `api/endpoints/knowledge_sharing.py:142`；三值处置 `keep_both/supersede_old/dismiss`
（`knowledge_facts.py:154`）。账本 0 行 ⇒ 这套逻辑在生产从未做出过一次裁决。

**溯源**：断言/活动两级 + `seq/digest/prev_digest` 链 + 巡检 `verify()`
（`api/endpoints/knowledge_core.py:262`）。**边界自陈不是防篡改**（`digest_chain.py:14-16`：
拿到写库权限者可重算整链）——这条诚实要保留在文档里。
`admission.py:163-167` 强制非匿名。**但 `verification_state` 92/92 `unverified`**：
记账齐全、校验从不闭环。

**记忆侧溯源较弱**：只有 `MemoryOrigin` 四值闭集（`models.py:52-63`）+ 只认显式形参
（`manager.py:931-943`，非法降级 untrusted），**没有 turn/工具结果级溯源表**；
对话轮次只落到 `metadata.session_id`（`post_chat_pipeline.py:1070-1079`）。

**记忆侧冲突消解是设计性 no-op**：`post_chat_pipeline.py:2222-2300` 自陈"检测器只给矛盾分、
判不出哪条为准，故不阻断不回滚"（`blocking=False`）；重复事实由内容门"保首条"吞掉
（`manager.py:968-986`）。另有三套检测器实现并存（`LegacyConflictDetector`
（`agent_core.py:411-424`，`use_semantic=False`）、`conflict_detector_v2.py:30`、
`channels/conflict.py:25`）。

**围栏覆盖面**（`knowledge/foundation/storage_fence.py`）：
`PRODUCTION_STORAGE_DIR = "./data/knowledge"`（`:25`，且是**唯一**该字面量，五个写入面
均从它派生）；判据是"目录本身 **或** 其中任何文件"（`:33-36`，双侧 resolve）。
**pytest-only**：`:41-42` 无 `PYTEST_*` 即 return ⇒ 普通运行与脚本**不受任何保护**
（docstring `:14-16` 自己承认）。断言点**恰好 5 处，全在知识侧**：
`repository.py:563`、`knowledge_facts.py:189`、`narratives.py:66`、`vector_index.py:76`、
`retrieval_benchmark.py:82`。决定性证据：**全 `neurova/` 只有 1 处 `PYTEST_*` 引用**
（就是 `storage_fence.py:41`）⇒ 记忆库、会话、EKB、`sleep_logs.json`、元认知账本
**均无同类围栏**。

**底座读面的 agent 约束缺口（潜在）**：`chat_pipeline.py:252` 与 `:279` 构造
`TemporalFactReader` / `GraphFactWalker` 时**只传 store**，`agentId` 走默认 `None`
（`temporal_facts.py:64`、`graph_walk.py:52-53`）。锚点跳的过滤是守卫式的
（`temporal_facts.py:39-43`、`graph_walk.py:89-95`）⇒ `None` 时**跨全部 agent 取锚点**。
比原结论更宽：时效读面在**事实段也不设域**（`temporal_facts.py:103-105`）。
递归段确有锁（`graph_walk.py:123/126`）。**当前 0 triple ⇒ 无实际越权读**，
但一旦灌入 triple 即成真缺口。

---

## 6. 抽取链路：对话到结构化记忆没有本体引导

**对话 → 记忆**：`post_chat_pipeline.py:1068-1079` 与 `mem_core.py:1145-1157` 把整轮压成
`"用户: %s"` / `"助手: %s"` 两条 episodic —— 自由文本模板入库，**无槽位、无校验、无 LLM**。

**对话 → 知识底座**：**无直连路径**。底座条目只来自文件/URL 导入：
`api/endpoints/knowledge_ingestion.py:143/303` → 条目仓库 →
`repository.py:603` → `EntryLedger.syncFromEntries`（`entry_ledger.py:62-69`，
`recordKind="narrative"`）→ 咽喉。生产侧构造 `AdmissionRequest` 只有三处，
其中两处显式 narrative，第三处（`rule_engine.py:349-356`，默认 triple）
因 0 条规则而**永不可达**。（`admission.py:34` 的默认值是 `"triple"`，
不能反过来当作"生产全产 narrative"的证据——方向是调用方显式传的。）

**唯一受本体约束的抽取**：`knowledge/graph_bridge.py:159-160` 从 `ontology_terms` 取合法
类型集（`:63-80`），越界落 `custom`（`:178/204`）。
**但喂给 LLM 的候选类型清单硬编码在 prompt 字符串里**（`:26-31`，唯一使用处 `:140`）。
实测当前注册表 9 个 concept 与 prompt 的 9 项**恰好同名重合**，属巧合而非机制 ——
**新增术语不会出现在抽取候选中**："加类型不改 .py"只对校验侧成立。

**写面与读面是两张图（本审计最硬的一条，反例已排查）**：

- 写面：`graph_bridge.py:184-192`（`add_node`）、`:205-208`（`add_edge`）、
  `:212-225`（只回写条目的 `graph_node_ids`）→
  `cognitive_layers/knowledge_graph/manager.py` 的 `nodes.json/edges.json/merges.json`
  （`_load:273-314`、`_save:316-339`、`_save_merges:341-352`），路径
  `agent_workspaces/<agent>/knowledge_graph/`（`:1199`）。该文件 grep 底座符号
  （`foundation|knowledge_facts|upsertFact|admit(`）**0 命中**，与底座零耦合。
- 读面：`foundation/graph_walk.py:4-6` 明文拒绝把上述 JSON 图当读面（"两套真相"），
  权威面声明为 `knowledge_subjects + knowledge_facts` 的递归 CTE（`:8`）。
- 实测两侧规模：JSON 图 `kai` 129 节点/118 边（mtime 09-15）、`default` 46/41（09-05 起未再更新）、
  `ag` 1/0、探针工作区 2/4，`merges.json` **全部缺失**（消解从未跑）；
  底座 triple **0 条**。
- **反例排查**：唯一看似桥的是 `repository.py:603 → syncFromEntries → recordKind="narrative"`，
  它投的是**条目本文**，客体是 `knowledge_id/content_key`（`entry_ledger.py:65`），
  被 `graph_walk.py:89` 的 triple 过滤直接排除 ⇒ **不构成反例**。
  `backfill.py:34-41` 复用同一映射，同为 narrative。
  ⇒ **抽取出的实体与边永远进不到被检索的那张图。**

**第三套关系词表**：`memory_layer/conversation_rule_extractor.py:80-115` 的 LLM 抽取
注入 `DependencyGraph`，关系类型是私有枚举 `dependency_graph.py:26-34`
（`causal/temporal/conditional/hierarchical/conflict/support/prerequisite`），**不读本体注册表**。
门控 `conversation_rules_enabled` 默认 False（`security/governance_settings.py:37`；
消费点 `post_chat_pipeline.py:3051-3070`，env 读 `:3055`、跳过分支 `:3075-3082`、
构造 `:3092-3120`）。注意 `DependencyGraph` 本身**不是死码**，有 4 个生产消费点
（`api/endpoints/neuron.py:30`、`moe_dependency_extractor.py:264`、
`neurova_recall.py:1183`、`post_chat_pipeline.py:3120`）—— 问题是"词表未与本体对齐"，
不是"这套图没人用"。

**真实存在的质量门控**（共 5 处，与"17 维"无关）：形成侧三态证据
（`post_chat_pipeline.py:1610-1667`，服务端票据 `evolution/objective_evidence.py`）；
结晶门（§1）；去重/取代内容门（`manager.py:968-986`、`knowledge_facts.py:142-143` 唯一索引）；
本体硬拒（`admission.py:204-208`，**当前恒免检**，见 §3 术语无 domain/range）；
冲突政策需依据（`conflict_judge.py:103-113`）。

---

## 7. 写盘面与污染

**路径可注入性成立**（行号经逐一命中）：`MemoryManager.__init__(db_path=...)`
`manager.py:157`（`:164-165` 空值即抛）、`get_memory_manager(db_path="")` `:3639`
（`:3657-3658` 空则按工作区推导，`:3660` 缓存键含路径，故非全局单例）、
`MemoryStorage(storage_dir)` `storage.py:274`、
`KnowledgeFactStore` 无 `db_path` 直接 ValueError（`knowledge_facts.py:182-189`）。

**可注入 ≠ 已收敛**：`manager.py:308-309` 用 `os.path.dirname(self._db_path) or "."`
派生 persist 库目录 ⇒ 裸文件名（默认值 `neurova_memory.db`）会**随 CWD 散落**。
实测散落 5 份：仓库根 71,831 / `neurova/memory/data/` 148 / `data/default/` 1 /
`data/` 0 / `test_workspace/memory/` 0。

**污染归因（原结论指错对象）**：根库 71,831 行、7,028 个不同 `agent_id` 中
`test_agent_*` **58,916 行（82.02%）**、其它 `test_*` 5,766（8.03%）、
`engine_it_*` 仅 **3,689（5.14%，1,085 个 id）**；`agent_id` 含 `test` 或为
`engine_it_*` 合计 **71,378 = 99.369%**，非污染余量仅 453 行
（`default` 161、`verify-agent` 4、`m060709_*` 等零散单次）。
根库还有三个独有病理特征：`origin` 100% `agent`、`metadata` 100% `{}`、
`memory_type` 100% `semantic` —— 真工作区里 `origin` 有 `owner`（kai 946/agent 42）、
`metadata` 几乎全非空 ⇒ **根库与真库不是同一条写入路径产出的**，这条比"污染"本身更有信息量。

**第二套 DDL 是真分叉不是超集**：`memory_layer/schema.py`（285 行、**29 列** `memories` +
FTS5 + 三触发器 + `dream_reports` + `memory_relations` + `trigger_chains`/`trigger_chain_nodes`）
**生产零导入者**（唯一真 import 在一个测试里）。运行库实测 **19 列**；扫全部 27 个 `.db`：
含 FTS5/关系表/触发链表/梦报告的 **0 个**。schema.py 的 10+ 列在运行库不存在，
运行库独有的 `shared` 列不在 schema.py 里。

**空壳写面**（原报告列为"落盘位置"，实测是 `mkdir` 出来的空目录）：
`agent_workspaces/*/memory/memory_storage/`、`data/memory_layer/` —— **0 文件**；
全仓 `memories.json` 只有 3 份且都在 `tests/`。
会话**不是数据库**，是 `sessions/<agent>/session_*.json`（实测 **3,113 个文件**）
+ `_timeline/*.jsonl`，根目录 `"sessions"` 为相对路径（`session_manager.py:185`）。
`memory_attachments`/`attachments` 表在 4 份 `memory.db` 里**全 0 行**（表建了没人写；
`memory_emotions` 在 default 有 5,903 行）。
EKB `data/experience_knowledge.db` 103 行（路径权威定义在 `experience_knowledge_base.py:40`，
可被 `NEUROVA_EKB_DB` 覆盖 `:43-48`）；元认知 `data/metacognition.db`（`:27`）09-13 起停更。

---

## 8. 缺陷台账

严重性判据：S=正确性/数据损失正在发生；A=对外可见的坏行为或静默失效；B=结构性隐患；
C=账面与实现不符。**每条都可由本文证据复现。**

| 编号 | 严重性 | 缺陷 | 证据 | 影响 |
|---|---|---|---|---|
| B-01 | **S** | `POST /api/v1/skills/learn` 的记忆写入**静默丢失** | `api/endpoints/skill.py:301` 前置分支要求 `agent` 有 `learn_from_conversation`（`:288` 是端点函数自身同名，Agent 上无此方法）⇒ 必落 `:338`；接收者是 `MemoryManager`（`:318`），其类无 `save_conversation_memory`（该方法只在 `MemCore`，`mem_core.py:1121`）；`:349` `except` 捕获后 `:351-353` 返回 `success:false` | 已鉴权对外端点，**每次都丢一次记忆写入**，且 HTTP 层看是 200。归类应为"静默数据丢失"而非"崩溃" |
| B-02 | **S** | `POST /tkg/facts` 每次**静默写入一条空三元组** | `api/endpoints/memory/tkg.py:64-72` 传 `entity/attribute/value/timestamp/source/metadata`，而 `manager.py:2689-2696` 只读 `subject/predicate/obj` ⇒ 全取不到；`modules/tkg_module.py:61-97` 无入参校验 | API 返回 200、记一条 `fact_id="__<ms>"` 的空行；且该库纯内存（`:37/40/43`），进程灭即没 |
| B-03 | **A** | `POST /api/v1/memory/classify` 恒 500 | `api/endpoints/memory/eki.py:102` 以两参调用单参 `manager.classify_memory`（`manager.py:2021`）⇒ TypeError 被 `:118` 吞成 500；且响应取 `result["category"][0]`，真实返回键为 `{"memory_id","categories","tags"}` | 该端点从未能返回过一次正确结果；连带使 §2 的"分类器在跑"不成立 |
| B-04 | **A** | priority 26/27 两条检索分支**恒定返回 0** | `temporal_facts.py:98`、`graph_walk.py:89,98` 过滤 `record_kind='triple'`；实测 triple = 0 | 时效事实与多跳图两条能力对外声明存在、实际不产出；与知识底座批次曾修的"接了但不工作"病灶同形（成因不同：那次是空表自扫，这次是谓词类型不匹配） |
| B-05 | **A** | 底座默认读面恒 0 行 | `knowledge_facts.py:557-575` `includeNarratives=False` + 92/92 为 narrative | 任何走默认读法的消费者都拿到空集 |
| B-06 | **A** | 聚合置信跨层丢失 | 条目层 0.7×126 → 事实层恒 0.5（§3） | 事实级排序无输入差异可分辨 |
| B-07 | **A** | 采纳回写零产出 | `knowledge_facts` 的 `adoption_outcome`/`latest_adoption_outcome`/`last_injected_at` **92/92 NULL**，`injected_count` 92/92 恒 0 | 反馈闭环有列无值；一切"按采纳证据重排/学习"的设计此刻无处起算 |
| B-08 | **A** | 前缀缓存被逐轮追加打破 | `orchestrator.py:583-589` 声称 vs `chat_pipeline.py:1935-1938` 实写 | Hebb 召回非空的每一轮，整段会话前缀缓存失效 |
| B-09 | **B** | 抽取产物进不了被读的图（两面分裂） | §6 三段证据 + 反例排查 | 除非改落地面，图谱能力与问答能力永久错位 |
| B-10 | **B** | 抽取候选类型硬编在 prompt | `graph_bridge.py:26-31/140` | 本体注册表新增术语对抽取不可见 |
| B-11 | **B** | 记忆侧新证据无法取代旧证据 | 内容门 `manager.py:968-986` 保首条；冲突检测 `post_chat_pipeline.py:2222-2300` `blocking=False` | 记忆库只增不改，陈旧事实与最新事实并存且无裁决 |
| B-12 | **B** | 记忆/会话/EKB 无写盘围栏；persist 路径随 CWD 散落 | `storage_fence.py:41-42` pytest-only；全仓仅 1 处 `PYTEST_*`；`manager.py:308-309` `or "."` | 99.37% 污染量的直接成因，且仍会继续发生 |
| B-13 | **B** | 底座读面 `agentId=None` 的跨 agent 锚点（+ 时效段同缺过滤） | `chat_pipeline.py:252/279`；`temporal_facts.py:39-43,103-105`；`graph_walk.py:89-95` | 当前无实际越权（0 triple），灌入 triple 即成真缺口 |
| B-14 | **B** | 版本控制"接了没通电" | `version_control.py:145-183/185-203/236-267` 齐备，`:147/187/242` 因 `storage=None` 短路；`agent_core.py:412-418` | 版本快照与回滚只在进程内，重启即失。修法成本远小于重写（补一个 storage） |
| B-15 | **C** | 文档/注释与实现不符 | "17 维"（§2）、"6 steps"（实为 8）、`base.py:74` 自动推断承诺、`tkg_retriever_adapter.py:4,22,27` 仍声称适配已退役的 `TemporalKnowledgeGraph` | 按文档施工会接到不存在的能力上 |
| B-16 | **C** | 15 个零生产消费者的实现件（含两套 DDL、两套温度、两套 light/REM） | §9 清单 | 主要风险不是"占地方"，是**改实现时改错那一套** |
| B-17 | **C** | 非法枚举值静默回落 | `question_queue.py:509 "system"`、`init_memories.py:36/50/63/77` | 分类信息在写入瞬间即失真，且无告警 |

---

## 9. 零生产消费者清单（判据：类名/工厂名全仓 ripgrep，排除构建副本；
"仅测试"= 只有 `tests/` 引用）

`memory_layer/memory_layer.py`（仅测试）、`modules/temperature_module.py`（**连测试都没有**）、
`schema.py`（仅测试）、`enhanced_context_builder.py`（仅测试）、`memory_rw_manager.py`
（唯一上游是前者 ⇒ 死簇）、`bm25.py`（含测试均无。陷阱：`semantic_search_api` 的
`bm25_results` 来自 `semantic_search.py` 与 `knowledge/hybrid.py`，不是本文件）、
`enhanced_retrieval.py`、`unified_reasoning_engine.py`（仅测试）、`proactive_recall.py`（仅测试）、
`deletion_state_manager.py`（仅测试）、`forgetting_recovery.py`（无。活的是
`modules/forgetting_recovery_module.py`，`manager.py:3435` 懒加载）、
`coreference_resolver.py`（仅测试）、`semantic_edge_filter.py`（仅测试）、
`memory_bus.py`（无。陷阱：`manager.py:172` 的 `self._bus` 是 `bus_event.EventBus`）、
`memory_field.py`（生产 0，但**确实被导出** —— `memory_layer/__init__.py:126-132` 的
`_TORCH_LAZY_EXPORTS` + `__all__:196-200`，`:121` 注释自认"运行时无消费方"）、
`result_processor.py`（仅测试。名字碰撞：活的 `channels/processor.py:32` 是另一个类）。

**"一调就炸"需修正**：`memory_layer.py:360-373` 的 `run_decay_cycle` 确实调用了
`TemperatureEngine` 上不存在的同名方法（`temperature.py` 只有 `on_decay:203`），
但 `:369-374` 包在 `try/except` 里返回 `{"error": ...}` ⇒ 真实症状是
**静默错误字典**，读者按"崩溃现场"去找是找不到的。

---

## 10. 复验记录：原结论中被推翻或收紧的部分

本轮先由子代理产出初稿，再分两路独立复核（消费方计数路 / 数据与存储路），
矛盾类断言由主控亲自读语义确认。**以下 14 条不再沿用初稿口径**：

| # | 初稿说法 | 复验结论 |
|---|---|---|
| 1 | 记忆库污染"engine_it_* 数万个" | **数量级错误**。engine_it_* = 3,689 行（5.14%）；主污源 `test_agent_*` 58,916 行（82.02%） |
| 2 | "confidence 126/130 恒 0.7"（对 `knowledge_facts`） | **层级混淆**。126/130 属条目层 narratives；事实层 92/92 恒 0.5。两者并存，真缺陷是跨层丢失（B-06） |
| 3 | 责任链"priority 首个达标者定主源" | **语义不成立**。恒装 KnowledgeRetriever ⇒ 提前返回永不触发，每轮跑完全部再合并 |
| 4 | "`fireFor` 无事可推、前向链没接上" | **措辞反向**。`admission.py:245` 有生产调用，缺的是规则数据（0 行），不是接线 |
| 5 | `admission.py:34` 默认 `recordKind="triple"` 被当作 narrative 证据 | **方向反了**。narrative 由调用方显式传入 |
| 6 | `memory_layer.py` "一调就炸" | 静默返回 `{"error":...}`，不炸 |
| 7 | `memory_field.py` "零导入者/未导出" | 被惰性导出表 + `__all__` 导出；成立的是"生产无消费者" |
| 8 | `skill.py:338` "调用即 AttributeError" | 被 `except` 捕获成 200 + `success:false` ⇒ **严重性上调**：静默丢写入（B-01） |
| 9 | `version_control.py` "无任何持久化调用" | 持久化 SQL 齐备，因 `storage=None` 集体短路 ⇒ 修法不同（B-14） |
| 10 | light/REM 睡眠"死码" | 死的只是 `manager.py` 那份重复实现；活语义在 `sleep.py:699/704`。且漏计 `idle_tracker.py:273` 这个**主触发方** |
| 11 | `schema.py` "memories 28 列" | **29 列**；另补测：27 个库中 0 个含 FTS5/关系表/触发链表 |
| 12 | `data/knowledge/` 现存 `knowledge.json`/`tombstones.json`/`conflicts.json` | **三文件均不存在**（019b-4b 已退役，路径常量成无主声明）；`memory_storage`、`data/memory_layer` 是 0 文件空壳 |
| 13 | 围栏行号 `:43-44`、读面构造 `:249/:265`、分类器 `:31-40`、枚举行号 `:252-259`、门控 `:2243-2264` | 全部偏移：`:41-42`、`:252/:279`、`:32-39`、`:41-47`、`:3051-3070` |
| 14 | "图谱/事实三套并存" | **三套在写 + 一套已退役残留**：`memory_layer/temporal_knowledge_graph.py:158`（真 SQLite，默认 `:memory:`，仍被 `neurova/memory/__init__.py:57,181` 导出）。按"三套"清理会漏掉它 |

**本次复核新增、初稿未收的缺陷**：B-02（`POST /tkg/facts` 空三元组）、B-05（默认读面恒空）、
B-06（置信跨层丢失）、B-17（非法枚举静默回落）、`DependencyGraph` 有 4 个生产消费点
（不可按死码处置）、`merges.json` 全部缺失（实体消解从未跑）。

---

## 11. 本文未做的事

- 未修改任何代码或数据（本审计只读）。文中 B-01…B-17 未建工单、未排期。
- 未运行测试套件（并发会话会与本工作树互相干扰）；所有读数来自只读 SQL 与静态扫描。
- 未评估 `NeurUI/**` 前端侧的记忆/知识呈现面。
- `docs/specs/2026-09-20-knowledge-foundation-design.md` 与工单索引里的进度性表述
  未与本文交叉核对（那批件在并发会话中仍在改）。
