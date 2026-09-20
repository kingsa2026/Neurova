# 019b-4b JSON 条目路径退役（默认翻向底座库）

**Blocked by**: 019b-4
**阶段**: E3 收缩（§4.1「不持第二权威」、G01、G12）
**状态**: 完成（生产已搬家；见文末读数）

## 这一刀做的四件事

1. **默认值翻向**：`_narrativeStoreEnabled()` 从"显式开才开"改成"显式关才关"
   （`off/0/false/no/json` 五个值认作回退意图）。不设环境变量 = 底座库，
   设成 `off` = 一次**有意的**回退，日志与报错按后者的措辞走，两者不再混为一谈。
2. **写入围栏上移到构造**：默认权威已在底座库后，`KnowledgeRepository(...)` 一建就跑
   迁移建表 + 一次性搬家，只守 `_save` 等于没守。代价如实写在 §10 R5：
   测试里"只读生产目录"也不再可行——构造即写，读与写分不开。
3. **诊断通路跟着改口径**（`scripts/diagnostics/_kb_backfill_rerun.py`）：条目权威与治理行
   现在同居一个 DB 文件，老脚本"把整个 DB 改名重建"会连权威一起搬走。改成就地清
   **治理面五张表**（facts/subjects/assertions/activities/conflicts），叙述面三张表
   （narratives/tombstones/entry_conflicts）不动，旧库改成**复制**留档。
4. **一处前提被否证**：工单原文写"顺带收编 12+ 直连写入方"。grep 加逐点核实后的结论是
   **生产代码里没有任何绕过 `repository.py` 的条目写入方**——11 个消费方全部走
   `get_knowledge_repository()` 的公开动词。那片切片不存在，不做。

## 顺带挖出的两处根因（都是真数据与默认翻向之后才现形的）

### A. 围栏只守了一个对象，路径却抄了四份

`data/knowledge` 这个字面量在四处各抄一份：条目仓库 `DEFAULT_STORAGE_DIR`、
事实底座 `DEFAULT_FACT_DB`、评测账本 `DEFAULT_EVAL_DB`、向量索引 `DEFAULT_STORAGE_DIR`。
抄一份就漏一个入口——实测证据：仓库围栏加上之后，`data/knowledge/knowledge_facts.db`
**仍然被建了出来**，来源是 `get_knowledge_fact_store()` 无参取单例时的默认路径
（`knowledge_retriever_adapter.py:50/79`、`knowledge_core.py:247` 都这么调）。

修法：新建 `neurova/knowledge/foundation/storage_fence.py` 同时拥有"生产目录是谁"
和"pytest 会话内不许碰它"这两件事，四个模块一律从它派生；判据从"等于生产目录"
扩成"生产目录本身或其中任何文件"，四个构造入口（仓库/事实库/叙述库/评测台架/向量缓存）
全在落盘之前拦。常驻判据：`TestFenceCoversEveryProductionWritingSurface`（4 例），
其中一条专门盯"路径只准有一份"，防止第五份被抄出来。

### B. 条目正文之间不该按三元组口径互相取代

`KnowledgeConflictJudge` 在 (主体, 谓词) 上聚合新旧事实判 value 冲突并按 `most_recent` 取代，
这条对三元组是对的，对叙述记录是错的：`documented_as` 基数天然不限，
**三条都叫 `note` 的条目是三份文档，不是同一说法的三个值**。真数据实测：生产 130 条
搬进底座后 5 行叙述被这样裁决成 superseded，10 条条目永远查不到 active 治理行——
`_load` 每次装载都报"投影分叉且补投没收敛"，因为 admit 按内容键折回的还是那条非活动行。

根因不是"叙述行不该参与裁决"（第一版这么改，当场把 019b-2 的
`test_BodyEditReplacesTheGovernanceRow` 打红——条目改正文必须留下被取代的旧说法），
而是**分歧的范围划错了**：分歧的前提是"两条说法在说同一件事"，条目正文的那件事是
**这一条条目**，不是它的标题。改成叙述行按条目 id 分组（`source_turn_id` 去掉
`entry:` / `legacy:` 前缀；溯源为空的退回自己的客体自锁），三元组分组行为逐字不变。
判据：`TestNarrativeConflictScope`（6 例，含"前缀不同不许分家""三元组自称 document
照旧判""无溯源叙述行不与任何行打架"）。

**同一个洞的另一张嘴已登记未修**：两条正文相同的条目共享一行，其中一条改正文会把共享行
判成 superseded，另一条因此查不到 active 行。它和 019b-3 撤回的 A→B→A 代际方案是同一个根
（唯一索引把去重做成了裁决顺序的函数，130 行：预测 92、实跑 102）。注记落在
`tests/unit/knowledge/test_read_merge_019b3.py::TestContentDedupeIsNotAnOrderFunction` 抬头。

## 事故登记：我自己把生产库搬了

`test_fenceIsWhatStopsTheWrite` 为了证明"围栏是唯一拦阻者"，把 `PYTEST_CURRENT_TEST` /
`PYTEST_VERSION` 清掉后**指向了真生产目录**。默认值一翻，这条用例就在测试会话里跑了真的一次性搬家。

证据（不是推测）：
- 归档文件名 `knowledge.json.pre-narrative-store-2026-09-20T095630001368+0000`、
  `knowledge_conflicts.json.pre-narrative-store-2026-09-20T095630564987+0000`——时刻与用例窗口重合；
- 隔离库 `knowledge_facts.db.polluted-20260920T1005` 的 `knowledge_narratives` 是 **131 行** =
  130 行真数据（`default` 104 / `kai` 24 / `ag` 2）+ 1 行
  `agent_id='guard-probe', knowledge_id='k1', title='t'`，与那条用例 `_withItem()` 探针逐字同名；
- 治理面同步长成 93 事实 / 88 主体，比基线 92 / 87 各多 1，多的正是探针那一行。

处置：污染库改名留证未删；`knowledge.json` 与 `knowledge_conflicts.json` 从归档改回
（哈希回到登记值 `e0ea2a4524e7`，130 条）；用例改成指向 `tmp_path` 下的假生产目录，证明力不减；
并补一条专名反向判据 `test_readPathCutoverIsRealAndUnfencedOutsidePytest` 盯住搬家机制本身。
完整登记见设计文档 §11.7。

## 验收标准与实测

| 判据 | 结果 |
|---|---|
| 不设任何环境变量 → 权威在底座库，`knowledge.json` 不被创建 | 通过（`test_defaultIsTheStoreAfterRetirement`） |
| 生产按设计搬家一次 | 130 条叙述 / 92 事实 / 87 主体 / 待审冲突 0 / **投影分叉 0** |
| 离线评测基线不降（A 侧显式 off、B 侧默认开） | 两侧同为 **0.855489 / 0.83 / 0.1**，与冻结值逐位一致，未命中仍是同样 3 例 |
| `_item_index_docs` 逐字节相同 | 通过（A/B 两侧 130 份索引文档全等） |
| 除 confidence/source 外条目逐字段相等 | 通过（差异字段数 0；130/130 的这两个字段按派生归正） |
| 三方同数复核（plan / reconcile / backfill） | 92 = 92 = 92，主体 87 = 87 = 87，叙述行 92 全 active |
| 关闸在搬家后被拒并指名回退步骤 | 通过（`_load` 的 RuntimeError 分支，019a 既有用例仍绿） |
| 围栏：构造期 + 三个写边界 + 四个存储面 + 无参工厂 | 通过（11 例） |
| 冷启动等价（门面 + 无参事实库 + 真检索） | items=130 drift=0 facts=92 subjects=87，检索 5 条命中 |
| 爆炸半径套件 | `tests/unit/knowledge` + 条目/向量/评测消费方 **488 passed / 46 skipped / 0 failed** |

## 留下的一刀没做

JSON 分支代码仍在（`off` 时走 `atomic_write_text`）。彻底删掉它要等 E4 之后再确认
没人靠 `off` 做临时回退——删早了回退路就没了，与"扩展-收缩"的收缩条件不符。
