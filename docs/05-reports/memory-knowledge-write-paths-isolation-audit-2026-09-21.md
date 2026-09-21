# 写入路径与隔离审计报告（记忆 / 知识子系统 · 第 7 节）

> 审计日期：2026-09-21
> 范围：记忆 SQLite、记忆 JSON 存储、知识 JSON+SQLite 底座 + 向量缓存、会话、EKB、睡眠日志、依赖图、Hebb

## 结论

写入面很广，路径全部由常量或工作区推导，无 HTTP 参数注入面；但「生产目录写围栏」只覆盖知识库一处，记忆库无围栏且已被测试/基准污染 7.1 万行。此外 Temporal / Graph 两条读面以 `agentId=None` 构造，锚点跳转不带 agent 约束。

---

## 1. 落盘位置

### 记忆

| 存储 | 路径 | 出处 |
|------|------|------|
| 主记忆库 | `agent_workspaces/<agent>/memory/neurova_memories_persist.db` | `manager.py:287-319`；`get_memory_manager` `manager.py:3636-3674` + `_default_db_path_for(agent_id)` |
| 情感 / 附件 | `…/memory/memory.db`（`memory_emotions` / `attachments`） | — |
| JSON 镜像 | `<db_dir>/memory_storage` | `manager.py:289`，`storage.py:269-280` |
| 进程级单例 | `./data/memory_layer` | `storage.py:693-702` |

### 知识

| 存储 | 路径 | 出处 |
|------|------|------|
| 唯一答案底座目录 | `data/knowledge/` | `foundation/storage_fence.py:25` |
| 文件集 | `knowledge.json` / `knowledge_tombstones.json` / `knowledge_conflicts.json` / `knowledge_facts.db` / `knowledge_vectors_*.json` | `repository.py:188-204` |

### 其他

- **会话**：`neurova/session_manager.py` + `session_repository.py`
- **睡眠**：`workspace/sleep_logs.json`（`agent_core.py:1434`）
- **EKB / 元认知账**：`skills/experience_knowledge_base.py:131`、`meta_cognition_layer/ledger.py:90`

---

## 2. 路径注入面

- `MemoryManager(db_path=...)` `manager.py:157`、`get_memory_manager(db_path="")` `:3639`、`MemoryStorage(storage_dir)` `storage.py:274` 均可注入。
- `:memory:` 现已整条关闭持久层（`manager.py:298-306`，注释记录曾落仓库根共享库、实测 7 万余行）。
- `KnowledgeFactStore` 不留默认值，无 `db_path` 直接 `ValueError`（`knowledge_facts.py:182-189`，注释指名灭 B01）；`get_knowledge_fact_store()` 单例冻结 `DEFAULT_FACT_DB`（`:30,:1020-1025`，由 CWD 解析）。

---

## 3. 写围栏（storage fence）

**有：** `storage_fence.assertNotUnderProductionStorage`（`repository.py:197`、`knowledge_facts.py:189`、`vector_index.py:26`）

- 但 **pytest-only**（`storage_fence.py:43-44`，无 pytest 环境变量即 `return`）。
- 只守 `data/knowledge`。

**无：** 记忆库、会话、EKB、`sleep_logs`、依赖图均无同类围栏。

**物证：** 仓库根 `neurova_memories_persist.db` 现存 **71,831 行**，`agent_id` 大量为 `engine_it_*`（基准/集成测试残留），`metadata` 全 `{}`、`origin` 全 `agent` —— 与 `manager.py:298-301` 记述的事故同形。

---

## 4. 隔离 / fence（逻辑层）

- **三元组隔离** `neurova user_id / user_id / agent_id`：`memory_layer/isolation.py:23-118`；读侧双保险 `manager.py:1364-1373`；删侧强制带作用域 `manager.py:609-631`；跨会话 `chat_scope` `post_chat_pipeline.py:1063-1065` + `collaboration/memory_scope.py`。
- **写入并发围栏**：`agent/history_fence.py`（claim/check + generation 换代，`:40` 自陈「纯内存」）。
  - 生产链：`chat_pipeline.py:656-658` → `mem_core.update_history:1341-1350` / `save_to_session:1396,1444` → `agent_core._save_to_session:1922-1934`。
  - **【已接线，进程内有效，重启后无围栏】**
- **底座读面 agent 约束缺口**：`chat_pipeline.py:249`（`TemporalFactReader(store)`）与 `:265`（`GraphFactWalker(store)`）都传 `agentId=None` → `temporal_facts.py:39-43`、`graph_walk.py:90-94` 的锚点跳不加 `agent_id` 过滤（递归段才靠 `f2.agent_id = s2.agent_id` 锁域）。当前因 0 条 triple 而无实际后果，一旦有 triple 即跨 agent 读。
- **第二套 DDL 死码**：`memory_layer/schema.py`（285 行：memories 28 列 + FTS5 + `dream_reports` + `memory_relations` + `trigger_chains`/`trigger_chain_nodes`）零导入者。真实 persist 表是另一套 19 列（`manager.py` 内建，实测 `PRAGMA table_info` 一致），FTS5 / 关系表 / 触发链表在运行库里不存在。**【只有骨架，且与实现不符的第二套 DDL】**

---

## 5. 最弱 / 最可疑的 5 处

### 5.1 「17 维分类」与实现不符 + 唯一分类器是死码 + 声称能分类的 API 是坏的

- 「17」只能凑自 `auto_classifier.py:27/39/50` 的 7+6+4 枚举值，而该类全仓零消费者。
- 生产真正用的是 `modules/classifier_module.py:31-40` 的 6 个硬编码关键词桶（与 `MemoryCategory` 的 7 桶不同名不同集）。
- `manager.remember` 根本不自动分类（`manager.py:843` 提的 `auto_classify` 无实现分支），所以库里 99% 是 `general`。
- **必坏端点**：`api/endpoints/memory/eki.py:102` 以 `classify_memory(content, context)` 两参调用 `manager.py:2021` 的一参方法，并按 `result["category"][0]` 取值 —— 真实返回是 `{"memory_id","categories","tags"}`，必 `TypeError`/`KeyError` → 该端点恒 500。

### 5.2 本体层「有 schema 无人口」，两条 RAG 分支对着空表跑

- 底座实况：92 条事实全是 `narrative`/`documented_as`、0 triple、`ontology_rules` 0 行、87 主体 `type_term_id` 全 NULL、23 术语无任何父类/domain/range/required_props。
- 后果：`admission.py:204-208` 的本体硬拒永远无违规可判（免检面 = 全集，见 `validation.py:43-58`）。
- priority 26（`temporal_facts.py:98`）与 priority 27（`graph_walk.py:89,100`）两条检索分支按 `record_kind='triple'` 过滤 → 每轮恒定返回 0。这与 `chat_pipeline.py:243-252` 刚修掉的 B01 病灶（「接了但不工作」）形状相同、只是换了成因。
- `term_registry.registerRule/register` 的生产调用方为零，`graph_bridge.py:26-31` 还把候选类型清单硬编在 prompt 里。

### 5.3 图谱/事实「写面与读面分裂」，记忆侧冲突消解是设计性 no-op

- 唯一受类型约束的抽取 `graph_bridge.extract_knowledge_to_graph` 写 JSON 属性图（`knowledge_graph/manager.py:278-351`），而答题明确不读它（`graph_walk.py:6-8`）。
- 底座唯一写入口 `upsertFact` 只有 `admission.py:209` 一个调用者、其生产调用参数全是 `recordKind="narrative"` → 抽取出的实体/边永远进不了被读的那张图。
- `modules/tkg_module.py:37-43` 是第三套内存事实库（API 能写、进程灭即没、检索链不读）。
- 记忆侧矛盾处理只有日志：`post_chat_pipeline.py:2222-2300` 自陈「纯观测、`blocking=False`、不回滚」，重复事实由内容门「保首条、只刷 `updated_at`」吞掉（`manager.py:968-986`）—— 即新证据无法在记忆层取代旧证据。

### 5.4 主干旁 6 处成建制死码 / 坏码，其中两处「一旦被调必炸」

整文件零生产消费者：

- `memory_layer/memory_layer.py`（`MemoryLayer` 门面；其 `run_decay_cycle:360-373` 还调用 `TemperatureEngine` 上不存在的 `run_decay_cycle`）
- `modules/temperature_module.py`（第二套温度衰减实现）
- `memory_layer/schema.py`（第二套 memories DDL + FTS5 + `memory_relations` + `trigger_chains`，全都没人建表）
- `neurova/enhanced_context_builder.py` + `neurova/memory_rw_manager.py`（旧上下文/读写栈，仅测试引用）
- `memory_layer/{bm25, enhanced_retrieval, unified_reasoning_engine, proactive_recall, deletion_state_manager, forgetting_recovery, coreference_resolver, semantic_edge_filter, memory_bus, memory_field, result_processor}.py`（逐个按类名复核零消费者）

调用即 `AttributeError` 的两处：

- `mem_core.py:1009-1016`（`self.recall` 不存在）
- `api/endpoints/skill.py:338`（在 `MemoryManager` 上调 `save_conversation_memory`，该法只在 `MemCore` 上）

### 5.5 可观测/可信链路「记账齐全、校验从不闭环」，且记忆库无测试围栏已被实证污染

- 92/92 断言 `verification_state='unverified'`、92/92 活动 `activity_kind='admit'`（即咽喉自开活动，非真管线埋点：`admission.py:269-287` 注释自陈「2026-09-20 冒烟实测到这一点」）。
- `knowledge_conflicts` 0 行、`supersedes`/`valid_from`/`valid_until` 全 NULL。
- `admission.pendingSegments()` 因 `indexing` 恒缺（`admission.py:123-128`）而永远非空，于是「缺段即拒」的纪律在每个真实调用点都被 `allowPendingSegments=True` 绕过（`entry_ledger.py:62`、`backfill.py:41`、`reconcile.py:147`、`rule_engine.py:349`），回执里的 `pending_segments` 因此不再区分「真缺段」与「设计上缺段」。
- 隔离侧：`TemporalFactReader`/`GraphFactWalker` 以 `agentId=None` 装配（`chat_pipeline.py:249,265`）留下跨 agent 锚点读口。
- 记忆库完全没有 `storage_fence` 的对等物，仓库根 `neurova_memories_persist.db` 里 71,831 行（其中 `agent_id LIKE 'engine_it_%'` 数万个、`metadata` 全 `{}`、`origin` 全 `agent`，真实用户数据仅 `agent_workspaces/*` 下 324+988 行）就是这条缺口留下的物证。
