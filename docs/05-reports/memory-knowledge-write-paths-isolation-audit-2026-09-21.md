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

---

## 6. §5.5 五条缺口的处置（2026-09-21 修复批次）

批次的判据是"纪律重新咬合"，不是"报错消失"。逐条对应本报告与
`docs/specs/2026-09-21-memory-knowledge-foundation-audit.md` 的读数。

### 6.1 段可见性：分清「这次装配漏接」与「尚未建成」

`admission.py` 新增 `SEGMENT_STATUS` 名册（每段 `wired` / `planned`，必须穷举 `SEGMENTS`）。
`pendingSegments()` 只报 `wired` 段里协作者缺席的，`plannedSegments()` 另立一栏；
`AdmissionReceipt` 相应分列 `pendingSegments` / `plannedSegments` / `activityId`。

后果：装配齐全的 `productionAdmissionGate` 报**空**缺段，四个真实调用点
（`entry_ledger` / `backfill` / `reconcile` / `rule_engine`）的 `allowPendingSegments=True`
被删干净——「缺段即拒」在真实链路上重新咬合，逃生开关只剩测试搭裸门时用。

### 6.2 活动归属：来路由调用方自陈

`AdmissionRequest` 增加 `activityKind` / `activityBasis` / `activityId`；
`_attachLineage` 优先复用调用方已开的活动，未声明时兜底开 `admit` 且 basis 自陈是兜底。
条目投影 → `import`，回填 → `import`，对账回放 → `import`（basis 区分两条路径）。
"92/92 条活动都等于咽喉自己"在真实链路上不再复现。

### 6.3 校验闭环：结论回写而不是只报

`ActivityDigestChain.attest()` 逐条裁决并**回写** `verification_state`
（正文与哈希 / 摘要与内容 / 链位三样都成立才 `verified`），`unverified` 从此只剩
"还没验过"一义；`setAssertionVerification` 在库层收口值域，`assertionVerificationCounts()`
给出三态分布，`verify()` 与巡检端点一并带出。调用点是条目投影与历史回填两条真实写入链。

### 6.4 有效期窗口：收了就落库，落了就咬合

`upsertFact` 接 `validFrom` / `validUntil` 并落两列，按内容键折回旧行时走
`fillValidityWindow` 只补 NULL。读面 `temporal_facts` 补上"不晚于此刻"的上界——
`valid_from` 此前恒 NULL，这条上界一直空转。至此两列有了写入方、读取方与过滤效果。

### 6.5 读面域与记忆围栏

- `chat_pipeline._factDomain()` 单点解析 agent 域，两条读面（时效 / 多跳）都带上它；
  取不到时落 `"default"` 而**不是** `None`（`None` 正是"不过滤锚点"）。
- `storage_fence` 增 `productionMemoryDir()` / `underProductionMemory()` /
  `assertNotUnderProductionMemory()`；`MemoryManager` 默认路径改为按 agent 工作区推导
  （空串与"没给"分开承载），主库与 persist 库两个写面都在构造处过围栏。

### 6.6 未在本批处置（继续登记，不静默遗留）

- 段7（入索引）仍是 `planned`：本批**如实报出**，不假装接通。
- 生产库既有的 92 条 `unverified` 旧行：`attest()` 已具备重放能力，但存量回写属于运维动作，
  未在本批执行——读数上它们仍如实显示为 `unverified`。
- 仓库根 `neurova_memories_persist.db`（71,831 行历史污染）：围栏已堵住新增，
  删库需人工确认，见 `docs/specs/2026-09-19-experience-quality-gate/tickets/011-记忆写入内容门.md`。

---

## 7. 未处置三项的收口（2026-09-21 第二批，Issue #75 用户点名"历史污染需要清空"）

§6.6 登记的三项逐条处置。判据仍是"纪律重新咬合"，不是"报错消失"。

### 7.1 历史污染：清空**已执行**，且清空动作本身可复核、可回退

`neurova/cognitive_layers/memory_layer/pollution_purge.py`：按**正证据**判定，两条判据都在库里/盘上可查。

- **位置证据**：库文件落在合法根（agent 工作区根 / 数据根）之外 ⇒ 散落物。
- **身份证据**：行 `agent_id` 整段命中 `test_agent_*` / `test_*` / `engine_it_*`（与 §7 的实测口径一致）。
  **不做子串包含、不做比例判断**——不命中的行一律保留。

配套：`scripts/memory_pollution_purge.py`（默认只预报，`--apply` 才落手）。落手先归档整库（含
`-wal` / `-shm`）成 `.pre-purge-<stamp>`，把归档副本改回原名即可回退；目标落在 agent 工作区内
时当场拒（清历史污染不得连带真实 agent 的记忆）。

实测（本仓）：仓库根那份散落库已于本次清除并归档，二次扫描报"未发现历史污染"。

### 7.2 散落根因：默认落点收成单一事实源

污染只堵新增不够——**默认值本身**还在各模块各写一遍，换个工作目录就换个库。本批新增
`neurova/core/data_root.py`（`get_data_root()` / `get_agent_data_dir()` / `ensure_agent_data_dir()`，
`NEUROVA_DATA_DIR` 可注入），并把这一族的默认值全部改为经它推导的**绝对路径**：

`core/database.py`（`defaultDbPath()`）、`core/connection_pool.py`、`core/db_indexes.py`、
`api/endpoints/files_api.py`（`users.db`）、`memory_layer/storage.py`（`defaultStorageDir()`）、
`memory/pending_memory.py`（`defaultPendingDbPath()`）、`cognitive_storage_engine.py`、
`knowledge_graph/manager.py`、`unified_vector_store.py`、`core/env_check.py`。

认知图谱目录的**写入端与删除端改为同一处推导**（`agent_core._init_cognitive_graph` /
`api/endpoints/agent.py` 的删除清理），此前一个拼 `f"data/{agent_id}"`、一个拼 `Path("data")/agent_id`，
CWD 一变就删不掉（幽灵 agent 残留的成因之一）。

live-verify：在任意 CWD 用各默认值取连接 / 建存储引擎，CWD 下**零新增文件**，全部落在数据根内。

### 7.3 段7（入索引）：不是欠账，是**分工**——归属写进名册并受守卫约束

段名册由两态扩为三态：`wired` / `delegated` / `planned`。`indexing` 归入 `delegated`，归属写在
`admission.SEGMENT_OWNERS`：

- `knowledge/repository.py::_rebuild_indexes` / `_apply_pending_ops`（条目与分块两路，挂在
  `search_visible_items` 检索入口上按需维护，向量路落 `UnifiedVectorStore.index_memories`）；
- `knowledge/foundation/read_surface.py::bm25_rank`（事实路查询时实时打分）。

`test_index_segment_ownership` 去这两个文件里查 owner 是否还在、还在不在检索路上；owner 消失即红。
回执分三栏（`pendingSegments` / `delegatedSegments` / `plannedSegments`），`segmentsApplied` 不再冒领别处负责的段。

### 7.4 存量 `unverified`：归正入口已具备并实测闭环

`scripts/knowledge_assertion_regrade.py`（默认只预报，`--apply` 落手；落手前自动归档整库）：
`relinkUnlinked()` 补链位 → `attest()` 逐条裁决并回写。实测（真库真链路）：4 条存量行
`unverified → verified`，`verify()` 无断裂。

**无活动依据的行保持 `unverified`**——那一维确实没依据，不许为了读数好看给个 `verified`；
混合态活动（部分有摘要）不重排，交由巡检报断裂。

### 7.5 被跟踪的运行期残留：清出并加守卫

`sessions/` 与 `trajectories/` 在 `.gitignore` 里本就写着，但更早一次提交把它们的内容一起提交了进来
（一份 2026-06-04 的 "hello" 会话 + 5 份 `session_id=test` 的 anonymous 轨迹），ignore 规则从此看不见它们。
本批将这些文件移出跟踪并删除；`test_tracked_run_residue_guard` 常驻锁住（`git ls-files` 在两个根下必须零命中，
规格说明文档不受影响）。同族的 `agent_workspaces/kai/.../muscle_l2.json`（2 条降级参数脏条目）按 008 的
既定口径归档重攒。

### 7.6 剩余落点全量收口（2026-09-21 第三批，Issue #75 用户点名）

§7.6 原登记为"仍在册"的零散面，本批**全量**处置——不再按"与记忆/知识写入面是否相关"分族，
因为"换个工作目录就换个库"与那件事无关。

判据扩成两条，都由 `tests/unit/core/test_data_root_no_cwd_landing.py` 常驻锁住（扫描面含
`scripts/`）：

- **CWD 相对落点为零**：`"data/x"` / `Path("data")` / `os.environ.get(..., "data/x")` /
  函数默认参数 `db_path="data/x.db"` / f-string 前缀 `f"data/agents/{id}/..."` 一律不得出现；
- **同一根只准一处定义**：`PROJECT_ROOT / "data"`、`Path(__file__).parents[N] / "data"`、
  `os.path.join(dirname(__file__), "..", "..", "data")` 这类"另推一份根"同样不得出现。

起始实测红灯 **156 处**（126 个文件），收口后 **0 处**。数据根模块自身补两件：

- `resolveDataPath()`：**默认值**口径——相对名落数据根，绝对路径原样放行；
- `callerPath(value, *defaultParts)`：**显式入参**口径——调用方给了就用它的（相对/绝对/注入的
  临时目录一字不改），没给才按数据根拼默认名。两者必须分开：把显式入参折进
  `resolveDataPath(x or "y")` 会把测试隔离目录与部署指定落点当场改写（本批实际踩到，
  两条真回归 `test_list_computers` / `test_run_audit_persisted` 即由此而来，已当场修）。

同批把 `test_agent_package_api` 的隔离方式从 `monkeypatch.chdir(tmp_path)` 改为注入
`NEUROVA_DATA_DIR`——"靠 CWD 隔离"本身就是这条纪律要灭的形态。

### 7.7 运行期落点收口（2026-09-21 第五批，Issue #75 用户点名"是否闭环了"）

§7.7 此前把 `auth.py` 的 `.jwt_secret`、`trace_recorder.py` 的 `trajectories/`、
`file_utils.py` 与 `files_api.py` 的 `storage/` 登记为"另一根族、改名会让既有令牌/轨迹失联"。
**那条登记把性质判错了**：它们同样是**真 CWD 泄露**，而非"另一种合理形状"。真构造点 +
临时 CWD 实测（无替身）：

```
LEAK  api.auth 密钥文件             ['.jwt_secret']
LEAK  trace_recorder 轨迹目录       ['trajectories']
LEAK  file_utils 隔离存储           ['storage']
LEAK  files_api 上传根             ['storage']
LEAK  session_manager 会话目录      ['sessions']
LEAK  media.config 配置目录         ['config']
LEAK  infrastructure 配置          ['config']
LEAK  project_to_skill 输出目录     ['generated_skills']
LEAK  app 健康检查连库              ['neurova_memory.db']
LEAK  shutdown_guard 哨兵          ['data']
LEAK  neurflow 库                  ['neurflow.db', ...]
LEAK  zero_downtime 旧库            ['neurova_memory.db']
```

它们比 `data/` 那族**更坏**：`data/` 至少还锚在仓库根（默认启动目录就是仓库根），
这批连仓库根都不锚——落点是"进程碰巧从哪儿启动"。真后端冒烟另实证三处同形落点：
`console.py` 的 `uploads/console`、`media.py` 的 `media_storage`、
`start_server.py` 注入的 `data/evolution/rsi_rollback.json`（后两份是"7 天无回滚"
判据的唯一数据来源，散落等于判据在真实部署里永不可满足）。

判据分流成两类，由 `tests/unit/core/test_runtime_landing_root.py` 常驻锁住：

- **运行期产物**（库、日志、上传件、轨迹、密钥、会话、备份、待办）走 `get_data_root()`；
  新增 `dataLanding(*parts, legacy=...)` 作为统一入口。
- **随代码走的资产**（模型目录、`config/` 配置、`agents.json`）走 `repoRoot()` / `repoAsset()`
  ——镜像里就带、不随 CWD 变、也不受数据根注入影响。两者不能混：把 `models/` 归到数据根，
  容器里就找不到模型。

**既有部署不失联**：`adoptLegacyLanding()` 在新落点**空缺**时把仓库根旧物搬过去一次
（新落点已在则不覆盖，旧物不存在则无操作，搬迁失败只告警不抛）。实测：

```
[4 收养结果] 旧物搬迁 = True  字节一致 = True
[6 库收养]   旧物搬迁 = True  字节一致 = True
[7 幂等]     二次收养 = False（新落点已在）
```

**部署面同步**：会话存档落点从"裸 `sessions/`"改为数据根后，容器里原有的 `/app/sessions`
卷会变成死挂载。已按应用真读的键补上显式落点（`docker-compose.yml` 与 Helm configmap 的
`NEUROVA_SESSIONS_DIR`），由 `deploy_config_consistency_check.py` 的 R5 常驻把关
（反向控制实测：把它换成任意零读取的键，门禁立即报"死配置"）。

活体验证两条独立证据：22 个真构造点 + 临时 CWD + 注入数据根 ⇒ **CWD 泄露 0 / 22**；
真后端 `start_server.py` 子进程 + 真端点（`/health`、`/metrics`、`/health/detailed`）
⇒ **CWD 零新增**（反向控制：把 `start_server.py` 的注入退回原写入法，冒烟立即报
`CWD 出现新增：['data']`）。

- 预存失败口径见 §7.4 与 Issue #80 批次，本批未改。

### 7.8 收口批自身引出的两条 CI 红灯（2026-09-21 第四批）

§7.6 的收口动作有代价，本批把代价补平——两条红灯都不是"缺功能"，一条是本批自己引入的
真回归，另一条是更早就存在的时序脆弱判据被本批的机器负载照出来。

**（1）门禁脚本"导入顺序"回归（真回归，PR #105 引入）**

为把落点收进数据根，`scripts/ci/experience_quality_gate.py` 在文件顶部加了
`from neurova.core.data_root import get_data_root`，**但那一行在把仓库根放进 `sys.path` 之前**。
CI 的 experience-quality 流水线装的是 `requirements-ci.txt`（依赖，未 `pip install -e .`），
脚本靠"从仓库根执行"拿到包，于是必然
`ModuleNotFoundError: No module named 'neurova'` —— **门禁根本跑不起来**（实测退出码 1，
耗时 0.2s）。这条正是"记账齐全、校验从不闭环"的同一形态：读数存在，产生读数的那个门禁没启动。

修法：把 sys.path 那两句提到导入之前。同形脚本一并处置（放大视角那一刀）——同一个"导入顺序"
契约在 6 个脚本上命中：`demo_closed_loop.py`、`demo_optimization.py`、
`diagnostics/check_databases.py`、`diagnostics/check_users_db.py`、
`diagnostics/skill_name_collisions.py`、`diagnostics/_live_verify_growth_split.py`；
另有两个存量同形（`token_estimation_compare.py` 只把**脚本自己所在目录**放进 sys.path，
拿不到 `neurova` 包；`console_api_coverage_script.py` 从未加过）。常驻守卫
`tests/unit/scripts/test_scripts_import_bootstrap.py` 锁住"任何 `import neurova` 之前，
仓库根必须已进 sys.path"，并带反向控制（只放脚本自己目录**不算**数）。

**（2）响应路径耗时判据的时序脆弱（预存族，非本批引入）**

`test_post_chat_p0_latency_observability.py::test_background_response_path_does_not_scale_with_bypass_steps`
断言 `elapsed < STEP_DELAY + 0.1`，把**固定开销**（线程跳、事件循环调度、GC、CI 机器抢占）
也算进了预算。CI py312 实测 0.40s，本机加压实测 0.54s —— 而**干净基线（main）在同一负载下
同样红**（本批 A/B：旧判据 main 1/10 红、本批分支 1/8 红，逐轮交替跑）。该族更早已被登记
（`docs/specs/2026-09-20-knowledge-foundation/tickets/014-*.md`:60 记"全目录并发跑时因机器
负载超时……属已登记的时序脆弱族"）。

修法：判据改为**差分**——空臂（旁路 delay=0）与慢臂（旁路 delay=D）各取 min-of-N、交错取样，
断言 `min(慢臂) - min(空臂) < 4×D`。固定开销在两臂同现而被相减消掉；正确后台化下增量 ≈ 1×D，
泄漏时 ≈ 11×D，2.75 倍分离。**判据没有被放宽**：把 `background_enabled()` 变异成恒 `False`
（后台化关死）后该用例仍红（实测增量 1.81s），复原即绿；对照组
`test_kill_switch_path_pays_all_steps_serially` 原样保留。48 倍过载下新判据连跑 10 轮 0 红
（旧判据同负载 10 轮 1 红）。

**（3）"把 `"data/x"` 改成 `""`"不是收口，是换一种 CWD 相对（本批实测新发现）**

上面两条之外，本批在自查过程中实证了同类病灶的**第三种写法**——它比前两种更隐蔽，
因为字面量扫描器看不见它：`""` 不是 `"data/..."`，于是"扫出 0 处"的字面读数绿灯，
而落点从"仓库根的 `data/`"退化成"**任意进程 CWD**"。

物证：跑一轮 `tests/unit/agent + core` 后，仓库根多出三个 `.git` 目录
（`loop-probe-01.git` / `test-agent.git` / `yi_ling.git`）——由这些默认值建出。
实测落点（真构造点、`os.chdir('/tmp/reg')`）：

- `CheckpointService(base_dir="")` → `/tmp/reg/agentX.git`（原默认 `data/checkpoints`）
- `BackupOrchestrator(work_dir="")` → CWD（原默认 `data/backups`）
- `UserCredentialStore(base_dir="")` / `user_config_path(base_dir="")` → CWD
  （原默认 `data/web_reach_credentials`，加密 keyfile 也会落这儿）
- `DLQConfig.storage_path = ""` → CWD。**配置注释写着"空串 = 数据根下的 dlq
  （resolveDataPath 归一）"，消费端却是裸 `Path(...)`——注释撒了谎**
- `NeuHebbConfig.persistence_path = ""` → CWD，注释写着"空串 = 数据根下的 neurova_hebbs/"

判据补第三类，由 `tests/unit/core/test_data_root_no_cwd_landing.py` 的
`TestEmptyDefaultIsNotACwdLanding` 常驻锁住：**空串默认值当落点用时，要么经数据根归一
（`resolveDataPath` / `callerPath` / `dataPath` / `get_data_root`），要么有缺省判定
（`if not x:` / `x or <默认>`）**。只认"真落点"——`Path(x).name` 取文件名、
`Path(x).exists()` 判存在（如 `plugin_manager` 的 `Path(record.path)`）都不算，
避免误伤；反向控制用六类形态（裸 `Path().mkdir()` / `callerPath` 归一 / `if not` 守卫 /
`or` 守卫 / `Path(raw).name` / 数据类字段消费）锁住"扫描器真认得出"。

五处一律改 `callerPath(x, <默认名>)`：调用方给了就用它的（显式入参一字不改，已实测
注入临时目录仍被遵守），没给才落数据根。改后同一组真构造点 **CWD 零新增**，
数据根下 `checkpoints` / `dlq` / `neurova_hebbs` / `backups` 四个目录如约出现。
