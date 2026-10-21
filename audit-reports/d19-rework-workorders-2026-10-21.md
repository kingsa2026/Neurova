# D19 重做·第 2 组三份并入施工单 —— 2026-10-21

> 按教义 7 的「对比优劣 → 取长补短 → 接通 → 退役」出的施工单，**只读，不改码**。
> 对象：`vector_search`（726）、`vector_index_manager`（431）、`memory_index`（277）。
> 三档当前生产读者都是 0；下面逐档写清"活替代是谁、唯一部分是什么、并入哪里、怎么接通、
> 怎么验证、什么条件下才允许退役"。

## 0. 共同前提

- 活脊柱：`UnifiedVectorStore`（`unified_vector_store.py`，ONNX/TF-IDF 双后端、增量索引、
  嵌入缓存）＋ `MemoryStorage`（CRUD/query/tags）＋ `MemoryManager`（recall/query 公开面）。
- 这三档不是"整档都比活实现强"，也不是"整档都可删"：先取长补短，**没有并进去之前不许退**。

## 1. `vector_search.py`（726 行）

- **读者**：生产 0；测试 2（`test_vector_search.py`、安全网）。
- **活替代**：`UnifiedVectorStore` 已有 `_tfidf_encode`（稳定哈希兜底）、`_extend_idf`
  （增量 IDF）、`index_memories(incremental=True)`、`remove_documents`、`search`、嵌入缓存。
- **逐项对比**：

| 能力 | 现役是否覆盖 | 备注 |
|---|---|---|
| TF-IDF 编码 | ✅ `_tfidf_encode` | 单字粒度；与本档分词不同但同语义 |
| 增量索引/IDF | ✅ `index_memories(incremental=True)`＋`_extend_idf` | 本档 `add_texts` 是同步重建 |
| 文档 CRUD/统计 | ✅ 索引/删除/计数；统计由 store 派生 | 本档 `get_documents/update_document` 只是薄包装 |
| **持久化索引** | ❌ | 本档 `save_index/_load_index` 用 pickle 落盘；活实现**不落索引**，启动从 DB 重建＋嵌入缓存 |

- **唯一部分**：持久化索引（含 documents/tf/idf/vocabulary）。它也是风险：索引文件与 DB
  是两份状态，DB 变更后需一致性键，否则"搜到已删记忆"。
- **并入目标**：`UnifiedVectorStore`。加 `saveIndex/loadIndex`，文件头存
  **DB 指纹（行数＋最大 updated_at 或内容哈希）**；指纹不符即丢弃重建。只保留一份索引状态。
- **接通点**：`UnifiedVectorStore.__init__` 或 `index_memories` 首次调用；启动时先尝试
  指纹命中的索引，否则从 DB 重建（现有路径）。
- **测试**：①落盘→重启→同向量命中；②DB 变更→指纹不符→重建（不得返回已删记忆）；
  ③无索引文件→回退重建。红→绿各一枚。
- **决策点**：先量真实库 `index_memories` 的启动重建 p95。若可接受，**显式放弃持久化**
  （不并入，直接退档，理由＝第二份状态的风险大于收益）；若不可接受，按上面并入后再退。
- **不可逆点**：持久化能力随档消失；重建成本要用真实库量出来再决定。

## 2. `vector_index_manager.py`（431 行）

- **读者**：生产 0；测试 1（`test_m24_vector_wait_inflight.py`）。
- **活替代**：`UnifiedVectorStore.index_memories(incremental=True)` 同步增量；
  `knowledge/vector_index.ensure_indexed` 按用户持久化增量（知识库域）。
- **唯一部分**：异步队列/worker、`wait_for_completion` 的 in-flight 语义（M-24）、
  `IndexState` JSON 持久化/重启恢复。这些是"同步活实现"没有的。
- **并入目标**：若产品要异步索引，应把队列/worker/in-flight 收进
  `UnifiedVectorStore` 的单一索引入口（`index_memories` 的异步变体），状态文件只保留一份；
  不要另养第二套索引状态。若不要异步，**显式放弃**，不得写成"取长补短后退役"。
- **接通点**：无（当前没有调用方）；若并入，由 `index_memories` 的调用方选择同步/异步，
  保持默认同步以不改变现役行为。
- **测试**：先量真实库同步 `index_memories` 的 p95 与最大批大小。若 p95 可接受 ⇒ 放弃异步；
  若不可接受 ⇒ 红格：①in-flight 未清零时 `wait_for_completion` 不得提前 True（M-24 原案）；
  ②重启后 pending 恢复；③与同步入口同结果。
- **决策点**：同步成本 vs 异步复杂度。没有真实延迟证据前，默认**显式放弃**。
- **不可逆点**：异步/重启恢复能力消失；M-24 的 in-flight 教训随测试保留在台账。

## 3. `memory_index.py`（277 行）

- **读者**：生产 0；测试 2（`test_memory_index.py`、`test_memory_index_simple.py`）。
- **活替代**：`MemoryStorage.query(memory_type/owner/start/end/tags/limit/isolation)`、
  `list_by_tags`、`list_all`、`get`、`get_stats`；`MemoryManager.search_memories`（recall）、
  `query_memories`（只传 query/category/limit）。
- **逐项对比**：

| 能力 | 现役是否覆盖 | 唯一部分 |
|---|---|---|
| `query`（类型/owner/时间/tags/隔离/limit） | ✅ `MemoryStorage.query` 直通 | 无（本档就是 delegation） |
| `search_by_tags`（AND/OR＋隔离） | 部分：`list_by_tags` 无隔离参数 | 隔离过滤这一层 |
| `search_by_text`（子串） | ❌ recall 是语义检索，不是子串 | **唯一** |
| `get_by_ids`（按请求顺序） | ❌ `storage.get` 单条 | **唯一** |
| `get_stats`（隔离统计 `isolated_total/by_type`） | 部分：`storage.get_stats` 无隔离切片 | 隔离统计这一层 |

- **并入目标**：`MemoryStorage`（低层原语）＋`MemoryManager.query_memories`（公开面）。
  - `list_by_tags` 增加 `isolation_context`（与 `query` 同一过滤实现，不另写一套）；
  - `search_by_text` / `get_by_ids` 仅在"产品需要子串/按序取 id"时并入；否则显式放弃；
  - 隔离统计只在需要时并入 `get_stats`，与 `query` 用同一个 `_apply_isolation_filter`。
- **接通点**：`MemoryManager.query_memories` 增加 tags/text/ids 参数并委托 storage；
  没有消费方之前不新增公开参数。
- **测试**：①tags＋隔离与 `storage.query` 同结果；②text 子串命中/不命中；③ids 顺序；
  ④隔离统计与逐条过滤一致。各一枚红→绿。
- **决策点**：`query`/tags 已覆盖，可退；`text`/`ids`/隔离统计是产品口径，先问"有没有人要"。
- **不可逆点**：子串检索与按序取 id 能力消失；重建是薄实现，但要重新接 API。

## 4. 建议顺序

1. **先量后裁**：`vector_search` 启动重建 p95、`vector_index_manager` 同步索引 p95
   （真实库，记录命令与读数）。
2. `memory_index` 先并 `list_by_tags` 的隔离过滤（低风险、与 `storage.query` 同源），
   再按产品口径决定 `text`/`ids` 是否并入。
3. `vector_search` 若重建可接受，显式放弃持久化并退休；否则先并 `saveIndex/loadIndex`。
4. `vector_index_manager` 无延迟证据前不并异步，按显式放弃处理。
5. 任何一档在没有完成"并/接/测"之前，**不许删**；删除时同批退役其专用测试与门面导出行。

## 5. 实施记录（2026-10-21，§6-376）

- **测量**（隔离数据根、只读真实库）：真实库 19 条（default 15＋kai 4）；
  `UnifiedVectorStore(backend="auto")` 索引 p50 3.4ms、冷启动 615.9ms；
  合成 5000 条 TF-IDF p95 292.4ms。⇒ 持久化索引的收益不足以抵第二份状态，
  `vector_search` 按"显式放弃持久化"处理。
- **`memory_index`**：隔离过滤抽成 `MemoryStorage._passesIsolation`（`query`/`list_by_tags`
  共用）；`list_by_tags` 新增 `isolation_context` 并测（摘掉过滤即跨 agent 泄漏＝红，
  恢复＝绿）；随后退役，`search_by_text`/`get_by_ids`/隔离统计显式放弃。
- **`vector_index_manager`**：显式放弃异步（无调用方；同步索引 p95 可接受）；
  退役模块与 M-24 测试；`knowledge/vector_index.py` 的"闲置"注释改指本次放弃。
- **`vector_search`**：显式放弃持久化索引；退役模块、专用测试与
  `neurova/memory` 再导出；活实现 `UnifiedVectorStore` 承担。
- 口径：`memory_index` 的隔离 tags 是**并入**；`vector_search`/`vector_index_manager`
  是**用户显式放弃**，不写成"取长补短后退役"。
