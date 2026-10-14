# 记忆双库对比档案（§7 先比后合）—— 2026-10-14

> 形态：只读调研。**本档未改任何一行代码**，未跑写入类脚本。
> 取证方式：仓外快照查库（`$LOCALAPPDATA/Temp/nvmem_probe`，`shutil.copy2` 复制 `.db`/`-wal`/`-shm` 后只查副本，
> 避免 `sqlite3.connect` 在生产路径上亲手把文件建出来）+ 源码逐行 + `logs/server.log` 运行时实证 + `git log -S` 来历。
> 证据标注约定：`[实]`=本轮盘上/日志读数；`[码]`=源码默认值或调用行；`[未]`=本轮未覆盖，见 §8 限制。

## 0 结论先行

按 agent 分目录的记忆落点**不止两份，是三处、跨两个根**，且两根的 `memory.db` **同名不同形**：

| # | 绝对落点（默认数据根/工作区根下） | 表 | 今日行数 | 状态 |
|---|---|---|---|---|
| A1 | `agent_workspaces/<agent>/memory/neurova_memories_persist.db` | `memories` | default **12** / kai **4** [实] | **现役真行库**，今天仍在写（-wal 4 MB，mtime 2026-10-14 00:59）[实] |
| A2 | `agent_workspaces/<agent>/memory/memory.db` | `attachments` / `memory_attachments` / `memory_emotions` | default 全 0；kai `memory_emotions` **4**（最近 2026-10-07 17:30:55）[实] | 活的，但**只装情绪与附件**，不含记忆正文 |
| B | `data/<agent>/memory.db` | `memories` + `memories_fts*` | **0**（两个 agent 皆 0）[实] | 引擎被构造、表被建、**行从未落过**（目录下连 `wal.jsonl` 都不存在）[实] |

一句话：**「记忆」这条面今天只有一个事实源（A1），B 是一个从未承载过一次写入的平行体系**；
而 B 的空还不会让召回报错——它只是每轮贡献 0 条（§4-4），所以三年没人看见它。

裁定建议见 §6，其中 B 侧因**全仓唯一实装**（FTS5 / LSM 分层 / 向量列）一律判「**需人裁**」，不进可删清单。

## 1 关键入口（file:line）

- B 侧构造：`neurova/agent_core.py:1419-1425`（`_init_cognitive_graph()` → `ensure_agent_data_dir(agent_id)` → `CognitiveStorageEngine(data_dir=...)`）；
  落账行 `neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py:243`（`self._db_path = data_dir / "memory.db"`）、连接 `:265`、建表 `:276-278`。
  上游触发：`agent_core.py:575`（`enable_memory` 下调用）。**运行时实证** [实]：`logs/server.log:24182` 2026-10-13 09:08:28 `CognitiveStorageEngine 初始化完成: E:\项目\Neurova\data\kai`。
- A 侧真行库落点：`neurova/cognitive_layers/memory_layer/persist_landing.py:23`（`PERSIST_COMPANION_NAME`）+ `:26-28`（`persistCompanionPath()` 主库→同目录配对库，配对规则唯一推导）；
  常驻连接 `manager.py:343-345`，写 `manager.py:757/780/789/820`，读 `manager.py:493/573/1990`。
- A 侧主库路径**有两处定义**（本档顺手挖出，见 §7-1）：`neurova/agent_core.py:289`（`workspace/memory/memory.db`，生产实际走这条）与 `manager.py:4234-4242 _default_db_path_for()`（同形另拼一遍）。
  生产实例建于 `mem_core.py:647`，`db_path=self.config.db_path`（`mem_core.py:639`）**显式传入**，因此 `_default_db_path_for` 在主链路上不被走到——它只在 `home.py:159`、`semantic_search_api.py:67`、`knowledge_integration.py:72`、`neurflow/builtin.py:736` 这些 agent 缺失的降级支和裸 `MemoryManager()`（`tool_executor.py:3526/5628`）里生效，且 `agent_id` 恒为 `default`。
- A2 情绪表的持有者：`manager.py:256`（`EmotionModule(db_path=...)`）→ `emotion_module.py:157` 连接、`:191` 写、`:169` 读。`MemoryManager` 自身**从不打开** `self._db_path`（只 `:310` 取目录、`:322` 判 `:memory:`）。

## 2 五字段档案

### A（`agent_workspaces/<agent>/memory/`）
- **原功能**：按 agent 的记忆正文库 + 情绪 + 附件；`agent_id` 既是目录层级、也是库内列（`manager.py:364` `agent_id TEXT NOT NULL DEFAULT 'default'`），物理分库与逻辑列双层隔离（`isolation.py:23-118`）。
- **关键入口**：见 §1 A 侧各行。API 门面不取工厂，直接返回 `agent.memory_manager`（`memory/base.py:216`、`deps.py:77`、`base.py:180`、`knowledge_common.py:103`）。
- **来历**：`neurova_memories_persist` 首现 `693fa21b`（2026-06-07）[实]；`_default_db_path_for` 入 `e0519c94`（2026-09-02）[实]，动机是灭掉 CWD 相对默认值 `neurova_memory.db`；此后 `dc7e6419`(09-12)→`626e2e88`(09-20)→`619796b8`(09-28) 持续维护 [码]。
- **现役替代**：无替代——它就是现役本体。
- **判定**：**留，作选定那份**。

### B（`data/<agent>/memory.db`）
- **原功能**：`CognitiveStorageEngine` 的 LSM 五层热存储（L0 内存缓冲 + `wal.jsonl` 崩溃恢复 + L1 SQLite + FTS5 + 内存向量索引），意图成为统一记忆层。
- **关键入口**：`agent_core.py:1422`；消费方 4 个（`pattern_crystallizer.py:388/592`、`reasoning_trace_manager.py:174/188`、`sleep_adapter.py:100/159/163/167`、`unified_retriever.py:77`），前三个断点见 §4。
- **来历**：`class CognitiveStorageEngine` 建文件 `33c352b1`（2026-06-04）[实]，**早于 A 侧落点收口（09-02）与 `get_agent_data_dir` 归一（`6fc0fb88`，2026-09-21）**[实]。
  → 定性：不是「新引擎引入后旧路径没退役」，而是**旧引擎的落点被归一进了数据根、却从未承载写入**——落点收编走了形式，功能没接上。
- **现役替代**：**部分替代成立**——持久化与召回两职都已被 A1 承担（A1 有 12/4 条真行、读写双向 `manager.py:493` vs `:780`，且是每轮 `/v1/chat` 实际取用的实例）。B 的 `retrieve()` 那一路（`unified_retriever.py:77`）有 A 侧对应物（同文件 `:81-108` 的 MoE/Recall/Hebb 就是 A 侧 MemCore），且实测 A 侧在 B 为空时照常供数，不构成能力缺口。**唯 FTS5/向量/温度分层无替代**（§5）。
- **判定**：**需人裁**（因 §5 全仓唯一实装，不得进可删清单）。

## 3 四维对比（逐项证据）

**正确性**
- A：真行落库、WAL 活跃、`agent_id` 双维隔离 [实]。缺陷：主库路径两处定义（§7-1），`MemoryManager()` 无参静默回落 `default` 工作区（`tool_executor.py:3526/5628`）——跨 agent 串写风险敞口仍在。
- B：设计上有崩溃恢复（`wal.jsonl` + `_recover_wal()`），但 `wal.jsonl` 从未被创建 [实] ⇒ 恢复路从未运行过；且 `_FLUSH_THRESHOLD = 100`（`:218`）在真实量级（每 agent 个位数~十位数条）下**结构性永不触发**——这不是"数据少所以没写"，是阈值与用量差两个数量级 [实]。

**覆盖面**
- A：全链路。`/v1/chat`（`chat.py:224`）、console（`console.py:608`）、渠道（`channel_router.py:243`）、工具（`tool_executor.py:3541`）、回合后写入（`post_chat_pipeline.py:1182/1189/3345`），API 门面 ~70 处取 `agent.memory_manager`。
- B：写 0 个入口可达（§4），读 2 个可达但恒空。

**可测性**
- A：`tests/unit/memory_layer/` 47 文件 469 例，10 个文件进 `scripts/ci/protected_tests.txt`（含 `:117`、`:1093`）。
- B：`test_cognitive_storage_engine.py`(17)、`test_unified_retriever.py`(15)、`test_pattern_crystallizer.py`(17)、`test_reasoning_trace_manager.py`(15) 等，**仅 4 个文件进门禁**（`protected_tests.txt:1097`、`:362`、`:165`、`:114`），其余未入；且真引擎测试一律 `data_dir=str(tmp_path)` 注入（`test_cognitive_storage_engine.py:107/116/132`），**全仓无一格断言"行落进生产 `data/<agent>/memory.db`"**——主链路 `agent_core.py:1422` 那条构造零覆盖，只有 `test_post_chat_pipeline_tdd.py:57` 的 `MagicMock()` 冒充。§3 教义禁的正是这一形。

**调用方数量**
- A：~70 处（API 门面 + 主链路 + 记忆域端点族）。B：生产构造 2 处（`agent_core.py:1422` 活、`neurflow_api.py:448` 降级支），生产 `store()` 可达 **0/4**。

## 4 B 侧四条链的断点（逐条，含"从哪儿断"）

1. **结晶器（写）**：入口链是活的——`post_chat_pipeline.py:806-807` 背景步 → `:857-866` 派发 → `evolution_facade.py:217` → `closed_loop.py:603-612` → `pattern_crystallizer.py:245-246`。**断在 `:264-267`**：`evidenced = [e for e in entries if e.get("success") is not None]`，无客观回执即 `return`，`_store_candidate`(`:340`)/`engine.store`(`:388`) 从未被调。
   [实] 盘上 `agent_workspaces/kai/data/crystallizer_state.json`：`observations: 1, successes: 0, evidenced: 0, tool: chat` —— 纯对话轮次没有回执，闸永不通过。
2. **推理链（写）**：`reasoning_trace_manager.py:156` `NEUROVA_TRACE_PERSIST != "1"` 即 return。全仓**无任何生产赋值点**（仅 3 个测试文件 `monkeypatch.setenv`）[实]；且 `logs/server.log:13870` 2026-10-08 01:30:55 有该分支的运行时 DEBUG 行——**门在生产每轮被走到并短路** [实]。读侧 `get_recent_traces`(`:178`) 全仓零生产调用方（`:151` 自陈）。
   注：这道门是 2026-09-05 事故的根修（`reasoning_trace_manager.py:150-154` 注释：无条件持久化 + 睡眠翻倍曾造出 4 万行寒暄库）——**门本身是对的，别在收口时把它拆了**。
3. **睡眠适配（读写）**：`neurova/` 源码内**无一处 import** `sleep_adapter`（本轮 grep 仅命中 `__pycache__/sleep_adapter.cpython-312.pyc`）[实] ⇒ 零装配。现役睡眠巩固是原生 `SleepConsolidation`（`agent_core.py:1374`，消费方 `idle_tracker.py:249`、`api/endpoints/sleep.py:191`），不经适配器。
4. **统一检索（读）**：`chat_pipeline.py:244-247` 每轮把 `UnifiedRetrieverAdapter`（priority 10，最高）挂进责任链 [实] → `unified_retriever.py:77` 对空表 `retrieve()` 返回 `[]`，`:78` 不加项 → `:81-108` 仍 extend 上 MoE/Recall/Hebb（A 侧）→ 责任链 `memory_retrieval_chain.py:388` 空结果走 `:399-400` continue。
   ⇒ **B 空不降级、不报错，只贡献 0 条**，这是它长期不被发现的成因。
   第二条读链更值得注意：`chat_pipeline.py:1656`→`:1972`→`crystallized_experience_manager.py:284`→`pattern_crystallizer.py:592 engine.retrieve()` 恒 0 行 → `:300-304` 返回 **SUCCESS/空**；因非异常，`:306` 的 `memory_manager` 回退**永不触发** → `ctx.crystallized_patterns` 恒空 → `context/orchestrator.py:1474-1478` 的「[结晶经验]」注入位**常年无内容**（见 §7-3）。

**设计自陈的迁移从未完成**：`unified_retriever.py:76` 注释「方案A：直接用 CognitiveStorageEngine（新数据）」/ `:80`「方案B：兼容旧检索器（**迁移期间**）」[码]——这是一个「新层先建、旧层待迁」的中间态，A 侧从未被迁进 B，B 侧从未退役。§7 判据（该功能在仓内只剩一处实现被消费）正是在这一态上没闭环。

## 5 取长补短清单（B 不可替代处）

若退役 B，下列能力**全仓唯一实装、无替代**，必须先决定要不要保：

| B 侧能力 | 证据 | A 侧有无 |
|---|---|---|
| FTS5 全文检索 + 3 触发器 | `cognitive_storage_engine.py:201-215`、建表 `:276-278`、检索 `:474-484`；触发器有专测 `memory_layer/test_cse_fts_update_trigger.py` | 无（A 侧 LIKE 检索，`docs/05-reports/上下文三链路修复台账_2026-09-21.md:506` 记过 LIKE 注入） |
| 记忆向量列 + 内存向量索引 | `:248`、`:379`、`:575` | 无（A 侧向量在另一族的 `unified_vector_store.py`，非同一物）[未] |
| LSM 分层 + `wal.jsonl` 崩溃恢复 | `:236-237`、`_recover_wal():256/292` | 无 |
| 温度/layer/access_count 记账 | `:368-369`、`:522`、`:524/527` | A 侧有 `temperature` 列（`memories` 表含该列，max 100.0 [实]），layer/access_count 口径不同 |
| 结晶经验/推理链的**落盘能力本身** | `pattern_crystallizer.py:388`、`reasoning_trace_manager.py:174` | 无 |

⇒ 按修复教义第 7 条，**B 不得进可删清单**；它的正确处置是「取长补短」而非「退役清理」，或先裁「这些能力要不要」。

## 6 待拍板问题（各带影响面）

**Q1 · B 侧三层能力（FTS5/向量/LSM）到底要不要保？**
- 选甲「要保 → 接活」：把 `_FLUSH_THRESHOLD` 从 100 改成与真实量级相称（或写侧即时落 L1），并把 A1 的行迁进 B 或让 B 只承担索引职责不双存正文。代价：动 `cognitive_storage_engine.py` 落盘口径 + 需一次性迁移 12/4 行；**不可逆点**：一旦双存正文，A1/B 会出现两份真行，比现在更难收。影响面：`unified_retriever.py`、`memory_retrieval_chain.py`、结晶/轨迹两个写点。
- 选乙「不要 → 退役」：删 B 及其 4 个消费方与相关测试，只留 A1。代价：永久失去 FTS5 与向量列（上表）；影响面：`agent_core.py:1419-1510` 装配段、`neurflow_api.py:445-448`、约 90+ 个测试用例（其中 4 个在门禁，须同批摘）。
- **推荐**：**先选乙的"最小版"**——即先退役「从未落过行」的**落点**（`data/<agent>/memory.db`），保留引擎的 FTS5/向量能力但把它**接到 A1 的库上**（同根同库、只留一份 `memories` 表）。理由：双根是真病灶，FTS5 是净收益；两者可以分开处置，不必先裁「能力要不要」。
  但这一步要跨 `agent_workspaces` 根与数据根，动的是记忆正文的落点，属**必须人裁**级。

**Q2 · 两根并存（`agent_workspaces/` 与 `data/`）要不要合成一根？**
- 这是上一轮「配置/会话/记忆四根」问题的记忆侧投影。合成一根＝所有 agent 记忆换目录，须走 `adoptLegacyLanding` 收养（`data_root.py:170-187` 已有单点救济语义）。代价：桌面部署侧用户库须按同一 SQL 复测（`simplification-audit-2026-10-05.md:74` 已把这条列为「残留不确定性」）；**不可逆点**：收养只发生一次，路径认错即把旧物搬空。影响面：`agent_workspaces.py`、`data_root.py`、`storage_fence.py:60-68`（围栏**刻意不读 env**、把生产记忆目录硬编在 `agent_workspaces`——动根必须同时动围栏，否则判据与实况分叉）。
- **推荐**：本批**不动根**，只把 Q1 的落点收口做完并在台账登记根级问题。理由：动根会连带牵起会话/文件/配置三张档案，一次做不完就成了半成品；教义第 7 条禁止"两边都留着加同步脚本"，但允许"分批接通、批批闭环"。

**Q3 · `_FLUSH_THRESHOLD = 100` 这种"按量级写死的阈值"要不要留？**
- 事实：当前每 agent 记忆个位数~十位数条，阈值 100 ⇒ 写盘分支结构性不可达 [实]；未 flush 的行只在内存 + `wal.jsonl`，而 `wal.jsonl` 从未出现 ⇒ 现在这个态是**纯内存、重启即失**（靠 `_recover_wal` 也无可恢复）。
- 推荐：不设「不给缺陷现值写判据」的常驻红判据（本仓纪律），改为**登记 + 活体 `[OBSERVE]` 读数**，等接线时一并处置。

## 7 本档顺手挖出的另三档（登记，不在本档处理）

1. **A 侧主库路径两处定义**（§6 单一事实源）：`agent_core.py:289` 与 `manager.py:4234-4242` 各拼一遍 `<workspace>/memory/memory.db`。生产走前者，工厂兜底走后者，二者今天同形——一旦有人改其中一处，降级支与主链路的记忆库立刻分叉。同档另记：`data_root.py:124` 注释自称 `agents.json` 属仓库根资产，全仓无 `repoAsset("agents.json")` 消费方（上一轮已记，非本档新增）。
2. **`memory.db` 一名两形**：`agent_workspaces/<agent>/memory/memory.db`（`attachments`/`memory_emotions`，无 `memories` 表）与 `data/<agent>/memory.db`（`memories`+FTS）同名同后缀、schema 完全不同，且分属两个根。按文件名排查落点的人会两头走错——本档 §0 之所以要点破，是因为**它已经让我们误判过一次**（以为 A 侧主库是 `memory.db`，实际是配对的 `neurova_memories_persist.db`）。
3. **「[结晶经验]」注入位常年为空**：§4-4 第二条读链的回退因返回 SUCCESS 而永不触发，`ctx.crystallized_patterns` 恒空。这是「形状上已接线、实质上无数据」的假接线，与 §7-1 的结晶证据闸同源（无回执）。影响面：`context/orchestrator.py:1474-1478` 的上下文注入。

## 8 取证限制（本轮未覆盖，勿当作已验）

- 行数取自 2026-10-14 08:50 的**仓外副本**；`datadefault_memory-wal` 为 0 字节、`datakai_memory-wal` 为 94,792 字节（mtime 2026-10-04）——后者含未 checkpoint 帧，副本查询已把 WAL 一并计入，读数 0 行是含 WAL 的结果 [实]。
- **未覆盖前端按名调用**：NeurUI 侧是否有端点名指向 B 侧记忆，本轮未查。
- 未跑 pytest，「测试面」维度的用例数来自静态计数，非执行结果。
- 未跑活体 `/v1/chat`：§4 的"每轮可达"依据是 `logs/server.log` 与源码装配行，不是本轮亲发起的请求。若要把它当施工前置，须补 create_app + TestClient 的活体读数。


## 9 落批结果与两处勘误（同日，用户裁「三层能力保」后按推荐档执行）

落地：`4172d3cc`（生产 + 判据 + 活体）、`1ab1691f`（四档入受保护子集，561→565）、本笔
档案与台账 §6-202。

形态按推荐档执行「只收落点、不动两根」：FTS5(trigram) 与 `embedding` 并到 A1 的
`memories` 表上（memory 域迁移 v2/v3，含存量回填与三条触发器 `memories_ai/ad/au`），
检索与记账归 `MemoryManager`（`searchMemoriesFulltext` 不记账 + `creditRecallHits` 由读方
过滤后调用）；引擎退为 L0 缓冲 + 崩溃恢复文件（移正文库同目录）+ 温度分层，裸 SQL 层
整段退役（-416 行）。同根因另收两处：`mem_core._ensure_schema`（生产模块里的第三份建表
定义，只有 2 个测试在调）与 `_PersistDbStore.upsert_row`（按 dict 键名拼列名的测试专用写面）。

### 勘误一：`_FLUSH_THRESHOLD = 100` 不是「缺陷」，上一格把它写重了

§0 与 §6-Q3 把它列成「结构性不可达的写盘分支」。复算后要分三层说：

- `retrieve()` 本来就扫 L0，**未 flush 的节点照样被召回**——阈值不影响读；
- 崩溃耐久由 `wal.jsonl` + `close()` flush 兜住——阈值不影响丢不丢；
- 那张表之所以 0 行，唯一成因是 **`store()` 从来没有可达的生产者**（四道门），与阈值无关。

所以它不是本批要修的缺陷，本批**一个字节没动它**。教训：把「设计上的分层缓冲」按
「用量对不上阈值」写成缺陷，会把下一批引去收紧阈值、反而多出成倍 fsync。

### 勘误二：B 侧那份 FTS5 从未真的能用

§5 把 FTS5 列为「全仓唯一实装、无替代」并据此判「需人裁」。事实更硬一层：B 侧 DDL 用的
是默认分词器（`fts5(content)` → unicode61），本机 sqlite 3.49 实测对**文本里就存在的
5 字中文子串 `MATCH` 恒 0 命中**，而 LIKE 兜底只在 `sqlite3.OperationalError` 时触发、
不在零命中时触发——这张影子表对中文记忆从来没有产生过一次命中。故「保留 B 的能力」若
按字面搬那套 DDL，搬来的是个哑巴；并入 A1 时必须换 `trigram` 才有实质收益。仓内同题已有
先例：`context/eviction_ledger_db.py` 的 v2 就叫 `_rebuildFtsAsTrigram`。本批据此把分词器
取值收成 `sql_like.FTS_TOKENIZER` 单点。

### 落批实测补记（判据之外的三条读数）

- 六处建表定义的宿主：`manager.py`（A1，选定那份）、`cognitive_storage_engine.py`（已退役）、
  `mem_core.py:91`（已退役）、`memory/scripts/{init_db,save_guardian_story,save_vue_frontend_memories}.py`
  （**未动**：建的是 legacy 种子库 `yi_ling_memory.db`，列集另一套，无生产与 CI 入口，另批处置）。
- 本批自伤一处并当场改判：记账原先落在引擎过滤之前，冷档（25.0 衰减到 19.9）被自己这次
  命中 +10 复活 ⇒ `test_pattern_reaping` 两格翻红；改为「检索不记账、由读方过滤后对真
  回出去的行调 `creditRecallHits`」。曾试「行级条件下推 SQL」，实测证伪——`crystallized`/
  `tool_memory` 不在正文闭集，原值活在 `metadata.cse_*` 里，按列筛会整批漏掉。
- 活体第一版只隔了数据根，而记忆正文落在 **agent 工作区根**（另一根），真往生产 A1 写了
  一行 `mem_000019` ⇒ 已按 `id+content` 精确删净（default 回 12 行、影子同数、孤儿 0），
  隔离单点因此补了 `isolatedAgentWorkspaces()`。
- A/B：基线（HEAD 生产 + 铺入本批 16 档判据与共用助手）60 failed/12 errors ↔ 本树
  15 failed/2332 passed，**仅本树红 0 条**；本树余下 15 条逐条回基线单跑 3 次皆红，属预存。

### 仍开（登记，非本批）

① `agent_core.py:289` 与 `manager.py:4234 _default_db_path_for` 仍各拼一遍
`<workspace>/memory/memory.db`（今天同形，改一处即分叉）；② 引擎 L0 的写侧今天仍无可达
生产者，将来开闸时落点已是 A1、无需再造；③ `~/.neurova/` 那族配置是否收进数据根＝另一张
档案；④ `data/<agent>/memory.db` 的 0 行空库残留 default/kai/yi_ling 三处，属运行期产物，
**未替用户删**；⑤ `eviction_ledger_db.py:120 _FTS_TOKENIZE` 未跟随 `sql_like.FTS_TOKENIZER`。
