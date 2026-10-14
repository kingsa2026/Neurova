# 睡眠固化族对比档案（§7 先比后合；2026-10-14）

> 缘起：用户 2026-10-14 对台账 §6-206 第三张票的裁定是「先比后合」。本档案只做一件事——
> 把仓内四份名字里带「固化/睡眠/整理」的实现按**正确性、覆盖面、可测性、调用方数量**四轴
> 逐项摆证据，然后给三态判定（可退役 / 应接线 / 需人裁）。本档案**不改码**。
> 所有读数均为本轮现场实算（grep/AST/直读），标 `[实]`；没验到的标 `[未]`。

## 0. 结论先给

1. `neurova/cognitive_layers/memory_layer/sleep_adapter.py`（`SleepConsolidationAdapter`）
   **可退役** `[实]`：生产调用方 **0**，且它是现役 `SleepConsolidation` 的**更窄**的壳，
   没有任何不可替代能力（逐项见 §3、§4）。
2. 另外三份**不是同一功能**，不许并成"四份重复实现" `[实]`：
   `modules/sleep_module.py`（判据器，无写回）与 `core/flow_orchestrator.py`（同族判据器，
   生产零消费者）各自是另一层职责；它们的去留**另批处理**。
3. 连带裁：`sleep_adapter.py:189` 是 `CognitiveStorageEngine.get_statistics()` 的
   **生产侧唯一调用者** `[实]`；壳退役后该方法生产零消费者，但本仓活体
   `tests/manual/traceGateGovernanceFaceLive.py:96` 仍在读它取 L0 计数 ⇒ 建议**保留**，
   并把"生产零消费者"登记为待裁（不是顺手删）。

## 1. 调用方数量（生产 / 测试 / 触发面）

| 实现 | 生产调用方 | 触发面 | 测试 |
|---|---|---|---|
| `sleep.py:116 SleepConsolidation`（现役） | `agent_core.py:1373` 构造、`:1382` 挂 `idle_tracker`、`agent_shutdown.py:72`、`post_chat_pipeline.py:3130`（每 10 回合低负荷）、`api/endpoints/sleep.py:182` 经鸭子类型取 `agent.sleep_manager`/`sleep_consolidation`（该文件 13 个端点） `[实]` | 空闲、关机、回合计数、HTTP 四类都有 | `tests/unit/.../test_sleep_and_graph.py` 等，**0 格进 `protected_tests.txt`** `[实]` |
| `sleep_adapter.py:21 SleepConsolidationAdapter` | **0**（全仓双名 grep，剔 `__pycache__` 与档案后只剩定义档自己 + 一档测试） `[实]` | 无 | `tests/unit/cognitive/test_cognitive_graph_integration.py:185-261` 5 格（自测自） |
| `modules/sleep_module.py:120 consolidate_memory()` | 唯一调用者是同类 `:265`；上翻到 `manager.py:4174/4188/4213/4241` 四个 `run_*_sleep_cycle` 门面——**生产 0**（只被测试调）；`set_callbacks:287` 零调用者 `[实]` | 无 | 有（未进门禁） |
| `core/flow_orchestrator.py:476 consolidate_memories()` / `:667 SleepConsolidationCoordinator` | `FlowOrchestrator` 与 `get_flow_orchestrator:848` **生产 0** `[实]`；台账 `simplification-audit-2026-10-05.md:263` 早已判此族"需人裁偏删" | 无 | 有 |

## 2. 数据源与写回（判"能不能退役"的硬证据）

- **现役**：读 `memory_manager.get_all_memories()`（`manager.py:2287`，其 dict 由 `:734
  _load_from_db` 从 A1 `memories` 表按 agent 全量装载，`:759 reload_memories` 对账）`[实]`；
  写回走 `sleep_writeback.py:19` 直落 A1（`remember:59` / `update_memory:70,106` /
  `forget(soft):119`），并带两条根修契约：**≥2 源才新增**（`:55`）、**按闲置降温度**（`:105`）`[实]`。
- **壳**：`_fetch_memories:89` → `cognitive_storage_engine.py:411 retrieve("")`，正文那半进
  `manager.py:536 searchMemoriesFulltext`，而 `:555` 对空查询 `if conn is None or not text: return []`
  **恒返回空** ⇒ 壳**只看得到 L0 缓冲**，拿不到 §6-202 之后的 A1 正文库 `[实]`。
  这不是"更宽的读法"，是**错读面**。附带：`retrieve()` 对回出的每条 `touch()`（`:441`→`:103`
  温度 +10）+ `creditRecallHits:442`——用检索口做全量列举会把整层 L0 暖一遍、
  把工单 017 的冷档闲置判定踩死；只读列举的正确口是 `iter_nodes:445`（不过滤、不记账）`[实]`。
- 壳的写回：`_apply_results:134` → `engine.store` 只进 L0 + wal，要攒到 `_FLUSH_THRESHOLD=100`
  才落 A1；`:171-175` 那句"删源记忆"只改内存对象、无写面＝空转；`:141`、`:157` 是废表达式 `[实]`。

⇒ **两侧取到的集合实质不等价**（壳更窄），且壳的"删源"是空转。按 §7 的判据"该功能在仓内
只剩一处实现被消费"，退役壳不丢能力。

## 3. 覆盖面（谁有而谁没有）

现役 `sleep.py` 全集：聚类 `:246`、衰减委托 `:398-402`、归档 `:426`、梦境 `:656`、
洞察 `:726`、合并史 `:703`、冲突审计 `:346-369` + 真写回 `:969/:999`、相位链 `:555`、
设置与日志持久化 `:164/:204`、唤醒 `:790/:889` `[实]`。
壳只有：聚类 + 合并 + 衰减 + 归档，**是现役的真子集** `[实]`——它在 `:48` 另
`new SleepConsolidation(...)` 时**不传** `memory_manager`/`settings_store`/日志路径，
那些能力在它手里根本取不到数据。
Coordinator 唯一独有：否定词冲突表 `:513` + 四策略 `:526-541`（不落盘）`[实]`——属另一族，别并进来。

## 4. 取长补短清单（壳里有、现役没有的）

1. `get_stats():187-189` 的口径本身不独有，但它**是** `CognitiveStorageEngine.get_statistics()`
   的生产唯一调用者——退役时要一并处置这条引用关系（见 §0.3）。
2. `_record_to_node:117` 会把 `merged_from` / `is_archived` 写进节点 metadata（`:127-130`），
   现役从不落这两个键。**建议不取**：§6-202 已把 metadata 的键名收在
   `cognitive_storage_engine.py:66-75` 的 `cse_*` 单点上，另起一套未经批准的键名
   等于把刚收口的第二表示换个地方再建一遍（教义第 6 条）。桥的等价物现役已有：
   `sleep.py:49 from_dict`，CSE 自身也有 `to_memory:131` / `from_memory` `[实]`。
3. 未发现其它独占能力 `[实]`；**没验到**：L0 在生产里的实际条数（要活体读数才能说"壳只看 L0"
   到底少看了多少）。

## 5. 退役判据与同批动作（供点单后执行，本档案不动手）

- 删 `neurova/cognitive_layers/memory_layer/sleep_adapter.py`；
- 同批删 `tests/unit/cognitive/test_cognitive_graph_integration.py:185-261` 那 5 格
  （该档其余格属 CSE 图谱，留）；
- 改指文档三处：`docs/0-index/README.md`、`docs/01-architecture/cognitive_graph_storage_architecture.md:24/:110/:187`、
  `docs/11-legacy/源码图谱.md` `[实]`；
- 退役判据钉法（教义第 7 条"该功能在仓内只剩一处实现被消费"）：`.py` 面按**两个名字**
  （`sleep_adapter` / `SleepConsolidationAdapter`）grep，命中数 0（含定义档删除后）——
  注意 `from a.b import m` 与 `from a.b.m import X` 两种写法都要认，只认一种会让扫描面
  静默缩水造出假"零引用"；
- `CognitiveStorageEngine.get_statistics()` 的去留**需人裁**（生产零消费者 vs 活体读数口）；
- 顺手登记（不在本裁内）：睡眠固化族**0 格进 `protected_tests.txt`** `[实]`，而它有
  HTTP 面（13 端点）+ 每 10 回合自动跑 + 写回正文库——这条链一旦退化没有任何门禁会红。
  该补的那格属另一批（要点：断"`run_sleep_cycle` 真把合并结果写进 A1 且 ≥2 源才新增"，
  不能只断返回值形状）。

## 6. 来历（git 配方实证）

`sleep_adapter.py` 三次入库记录：`33c352b1`（Hebb 记忆系统那批）→ `33b71a25`
（Agent/记忆/工具/语音重构那批）→ `7f8c7660`。即它是**重构期搭的桥**，桥的两端后来各自长大：
现役那侧接上了 `memory_manager`/写回/日志，壳这侧停在"L0 + 自建实例"上没人再碰 `[实]`。
