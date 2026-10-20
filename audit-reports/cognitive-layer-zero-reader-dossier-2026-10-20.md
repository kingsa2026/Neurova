# 认知层"零读者"6 档五字段档案（2026-10-20）

> 只读档案，未动一行代码。判定三态：**删 / 接线 / 需人裁**。铁律：无现役替代不判删；
> 全仓唯一实装且无替代 ⇒ 需人裁，并写明"删即永久失去该能力"。
> 置信度：**✅＝主会话独立复算**；◑＝子代理取证（给了 `file:line` 与 commit，主会话未逐条复算）。

## 0. 前置事实

这 6 档由 `scripts/ci/cognitive_component_table.py` 的**静态**聚合索引判为"零读者"
（`neurova/` 与 `tests/` 都无 import）。该索引**不含动态装配**，所以本批专门补了三件事：

1. **两个 mixin 有没有被动态组合**（`type()` / `__init_subclass__` / `__mro_entries__` /
   字符串注册表 / `exec`）——✅ 全仓复算：`RelationMixin` / `ForgettingRecoveryStorageMixin`
   除自身文件外只有 `tests/unit/memory/test_storage_comprehensive.py:685` 一句**注释**提到，
   无任何类继承/装配它们。
2. **`proactive_question` 的动态装载**——✅ 发现它在 `neurova/memory/__init__.py` 的 `_MODULE_MAP`
   里，经 `importlib.import_module` 装进 `sys.modules["neurova.memory.proactive_question"]` 别名。
   ⇒ "静态零 import"成立，**"从没 import 过"不成立**；但这只是别名装载，不产生任何符号读取，
   组件表"零读者"的定性不变。
3. **反向守卫**——✅ `tests/unit/cognitive_layers/test_memoryLayerGenerationResidue.py` 的
   `PENDING`（:57）**专门钉住 `relation_mixin` 与 `forgetting_recovery_storage_mixin`**：
   "仍在位（未裁不许删）且仍零消费者（不许偷偷接线后再裁）"，该档在受保护子集
   （`scripts/ci/protected_tests.txt:2143`）。⇒ 这两档的处置**必须**走人裁，且裁后同批改该守卫与台账 §6-113。

## 1. 档案

### Z1 `memory_layer/explainability.py`（646 行）◑ 取证，✅ 写侧零调用复算
- **原功能**：TriggerNode／6 类节点与 DAG 父子链（`:24/:35/:83/:97`）；链生命周期
  start/add/complete ＋ memory→链索引（`:199/:235/:294`）；`explain_memory` 与根路径回溯
  （`:359/:404`）；树形可视化（`:444/:479`）；计数清理（`:518`，年龄上限只进统计 `:195`）；
  统计与 JSON 导入导出（`:544/:561/:581`）；DCL 单例（`:617`）。
- **关键入口**：`ExplainabilityManager:158`、`get_explainability_manager():617`。
- **来历**：`7835c367`(06-04) 骨架、`806c7047`(06-06) 补实装；`-S ExplainabilityManager -- neurova/`
  全史仅这两笔 ⇒ **引入即未接线**。
- **现役替代**：**部分缺**。`modules/explainability_module.py` 只做扁平 Explanation
  （`:99/:157`），没有 DAG／记忆关联／根路径／导入导出／树可视化；且它自己的三个写入口
  在生产侧零调用（仅测试调），`manager.py:4364/:4370` 的委托也只被测试调（✅ 复核：
  `manager.py:4353 explain_memory` 委托的是 `modules/` 那个扁平模块，不是本档）。
- **判定**：**需人裁**——全仓唯一 DAG 触发链实装。删即永久失去"这条记忆为什么被召回"的链式追溯；
  接线要补的是**整条写侧**（`start_chain/add_step` 目前生产零调用）＋读面，属新能力工作。

### Z2 `memory_layer/proactive_question.py`（940 行）◑ 取证，✅ 动态装载复算
- **原功能**：Question/状态/5 类 `CuriosityType`（`:29/:38/:48/:62`）；队列增删改查、优先级、
  过期（`:183/:203/:248/:351`）；好奇心强度（`:413`）、探索史与统计（`:479/:502/:582`）、
  模板提问（`:532/:561`）、质量/有用性（`:695/:857`）、会话回调（`:903-918`）。
- **关键入口**：`ProactiveQuestionManager:614`、`QuestionQueueManager:183`、`CuriosityDrive:399`。
- **来历**：`7835c367` 骨架 → `65309f6b`(06-05) 扩写 → `33b71a25`；无真实消费者。
  旧门面曾按不存在的 `ProactiveQuestion` 名称导入（恒 None，教义第 2 条的形态），
  `b2d7acf9`(10-14) 把这类 None 兜底拆掉时一并摘除。⇒ **引入即未接线**。
- **现役替代**：**部分缺**。队列部分有活替代：`meta_cognition_layer/question_queue.py:97`
  经 `mem_core.py:661`、`post_chat_pipeline.py:2659/:2672`、`orchestrator.py:1047`、`growth.py:489` 在役；
  **好奇心驱动、探索史、提问质量分零替代**（`intrinsic_motivation.py:427` 只调整机、不产问题）。
  本档自身亦含空壳：`:459` 恒 0.5、`:474` 恒 `[]`、`_knowledge_gaps` 无写点（`:409/:526`）。
- **判定**：**需人裁**——队列四符号可随替代删，`CuriosityDrive/ProactiveQuestionManager/ExplorationRecord`
  全仓唯一。删即永久失去"好奇心驱动的主动提问/探索史/质量分"；
  接线要先补知识缺口的**写侧**（今天无 setter）与触发点。

### Z3 `memory_layer/relation_mixin.py`（400 行）◑ 取证，✅ 守卫与组合面复算
- **原功能**：uuid4 多边 ＋ 双向索引（`:28`）；按条/按记忆查询，支持方向/类型/强度
  （`:78/:90`）；DFS 多层（`:135/:159`）；增改删清（`:195/:229/:260/:387`）；BFS 最短路（`:286`）；
  图统计（`:335`）。
- **关键入口**：`RelationMixin:15`。
- **来历**：`7835c367` 一行桩 → `65309f6b` 补 392 行 → `33b71a25` 重排；全史无 import
  ⇒ **引入即未接线**。
- **现役替代**：**部分缺**。`relation_module.py:52` 覆盖 CRUD/深度 1/BFS（`:90/:168/:215`），
  经 `manager.py:3905/:4475`、`memory/crud.py:287→:4160` 在役；`graph_traversal.py:72` 有 BFS/DFS
  与节点边统计（`:182/:241/:367`）。**丢掉**：uuid4 多边（复合键覆盖）、密度/均强/top5/unique、
  方向＋类型同次过滤。
- **判定**：**需人裁（已被守卫钉死）**——`PENDING` 明写"未裁不许删"。
  删即永久失去多边语义与图密度/连通统计；接线要补写侧（本类字典只自写、无持久化）。

### Z4 `memory_layer/forgetting_recovery_storage_mixin.py`（347 行）◑ 取证，✅ 守卫复算
- **原功能**：`archive_memory:29` 建归档记录；`delete_memory:65` 软删入队（`permanent` 只记记录
  不写盘 `:99`）；`recover_memory:109` 先查归档、再查软删并写恢复历史（`:127/:148`）；
  `get_archived_memories:165`／`get_deleted_memories:193` 分页；`get_recovery_history:221`；
  `search_archived_memories:234`；`get_forgetting_statistics:261`（原因分布＋恢复率 `:297`）；
  `cleanup_old_archives:300`；`clear_all:326`。
- **关键入口**：`ForgettingRecoveryStorageMixin:15`（无工厂、无 `__init_subclass__`/`type()` 装配）。
- **来历**：`7835c367` 引入；`-S` 全史仅此一笔 ⇒ **引入即未接线**。同能力的
  `forgetting_recovery.py`(346) 在 `0c333a76`(09-21) 被删，本件未随批清退——属"删主体留副本"；
  但主体是独立实现的 `ForgettingRecoveryManager`（删除前无 import 本 mixin），不是"删父类留 mixin"。
- **现役替代**：**部分缺**。`manager.py:4394 archive_memory`／`:4409 delete_memory_soft`／
  `:4418 recover_from_archive`／`:4430/:4440` 用 `LifecycleStage` 落盘，覆盖归档/恢复/列举；
  **`cleanup_old_archives:300` 与 `get_forgetting_statistics:261` 全仓唯一**；
  数据面 `_archived_memories` 只在本文件读写（零生产者）。
- **判定**：**需人裁（已被守卫钉死）**——删即永久失去恢复率与 30 天清理。

### Z5 `memory_layer/emotion_adapter.py`（241 行）◑ 取证，✅ 转发目标复算
- **原功能**：`analyze:84`（含 `use_legacy` 分支）＋ `_analyze_legacy:102`（16 词关键词匹配）、
  `batch_analyze:134`、`get_emotion_tags:148`、`get_emotion_score:162`、`get_detailed_scores:176`、
  `get_emotion_hierarchy:189`、`get_emotion_stats:199`、`get_emotion_distribution:212`——
  八个方法 1:1 转发；`_create_simple_analyzer:47` 在 ImportError 时恒返 neutral/0.0（`:53`，
  教义第 2 条点名的假成功）。
- **关键入口**：`EmotionAnalyzerAdapter:14`、`get_emotion_analyzer():231`（lazySingleton）。
- **来历**：`7835c367` 骨架、`65309f6b`(06-05) 补齐转发面与工厂；`-S EmotionAnalyzerAdapter`
  全史仅这两笔、且都只改本文件 ⇒ **引入即未接线**。旧卷 A10 的"向后兼容门面、从无人迁入"
  **成立**（方法数校正为 8 转发＋1 分支）。
- **现役替代**：**全量**。转发目标 `memory_layer/emotion.py:101 EmotionAnalyzer` 活着且被直连
  （`api/endpoints/memory/emotion.py:157`、`tool_executor.py:5381`），八个方法在目标侧
  `:132/:269/:290/:310/:328/:352/:361/:397` 一一存在；adapter 净增能力为零，
  唯一"独有"的 `_analyze_legacy` 是玩具分支。
- **判定**：**删**——转发面 100% 有活替代，留着只会把假成功兜底再带一层。
  前提：删除前确认 `memory/__init__.py` 的 `_MODULE_MAP` 不含它（✅ 已核，不在）。

### Z6 `memory_layer/modules/emotion_conduction_module.py`（233 行）◑ 取证，✅ 文件面复算
- **原功能**：`set_emotion:67` 钳 `[-1,1]`；`get_emotion:78`；`add_association:83` 建无向邻接；
  `conduct_emotion:102` BFS 沿邻居按 `rate×decay^hops` 扩散、0.7/0.3 加权（`:146`）；
  `aggregate_emotion:156` 极端值加权平均；`get_positive/negative/neutral_memories:182/:189/:196`；
  `remove_memory:202`；`get_stats:213`。
- **关键入口**：`EmotionConductionModule:16`，`name="emotion_conduction_module":51`，`init/shutdown:56/:62`。
- **来历**：`7835c367` 引入、`806c7047`(06-06) 补 name/init/shutdown；两笔均只改本文件
  ⇒ **引入即未接线**。装配面：`modules/__init__.py` 仅 6 行、零导出（docstring 仍写"集中导出"）；
  `manager.py` 对 `modules/` 的 21 处 `_ensure_*` 懒导入**不含本件**；唯一能按字符串装载的
  `memory_bus.py` 已随 `0c333a76` 删除。
- **现役替代**：**部分缺**。`emotion_context_layer/emotion_conduction.py:28` 是 **agent 级心情**
  （`update_emotional_state:65`），与"记忆间 BFS 传导"不同物；`modules/emotion_module.py` 只做
  单记忆存值，没有传导/聚合/极性列举（`aggregate_emotion:156` 全仓唯一）。
  **更正一处子代理误判**：它说"`neurova/channels/builtin/emotion.py` 不存在"——
  ✅ 实读：`cognitive_layers/memory_layer/channels/builtin/emotion.py`（2595 B）**存在**且是
  活通道（`BUILTIN_CHANNELS` 之一）；它查的是漏了包前缀的另一条路径。该误判不影响
  "传导能力无替代"的结论（通道只做情感匹配，不做邻居扩散）。
- **判定**：**需人裁**——全仓唯一"记忆间情感传导"实装，删即永久失去传导/聚合/极性列举；
  接线需先给 `set_emotion/add_association` 生产者（今天零调用方）。

## 2. 汇总

| 档 | 行数 | 判定 | 关键依据 |
|---|---|---|---|
| `explainability` | 646 | 需人裁 | DAG 触发链唯一；写侧生产零调用 |
| `proactive_question` | 940 | 需人裁 | 队列有活替代；好奇心/探索史/质量分零替代 |
| `relation_mixin` | 400 | 需人裁（守卫钉死） | 多边/密度/连通统计唯一 |
| `forgetting_recovery_storage_mixin` | 347 | 需人裁（守卫钉死） | 恢复率/30 天清理唯一 |
| `emotion_adapter` | 241 | **删** | 8 方法 100% 转发到活实现；净增能力为零 |
| `modules/emotion_conduction_module` | 233 | 需人裁 | 记忆间传导唯一 |

合计 2,807 行。**只有 Z5 一档可径退役**；其余五档要么被守卫钉死，要么是"全仓唯一实装"。

## 3. 处置次序（等拍板）

1. **Z5 可先做**（纯转发退役，同批改任何引用、并把"删净"写进台账）；它的前置只有一条：
   核实没有外部包按 `neurova.memory.emotion_adapter` 路径 import（今天仓内 0，外部无登记）。
2. **Z3/Z4 必须先人裁**，且裁决后同批改 `test_memoryLayerGenerationResidue.py` 的 `PENDING`
   与台账 §6-113——那格是"防裁决未下代码先没"的反向守卫，绕过它等于绕过裁决留痕。
3. **Z1/Z2/Z6 是能力题**（链条追踪/好奇心提问/情感传导要不要），接线都不是补调用而是补写侧，
   按 §6-361 的口径：先答"要不要这项能力"，再谈接。
4. 任何删除都同批退役其专用测试与文档宣称；本批**未动任何代码与测试**。

## 4. 与方法边界

- 本档的"零读者"来自静态聚合索引（`scripts/ci/cognitive_component_table.py`），
  **不含运行时调用与动态装配**；本批已对 6 档逐一补查动态面（见 §0）。
- ◑ 标记的字段来自子代理，未逐条复算；✅ 标记的是主会话复算过的关键读数。
  子代理的一处路径误判已在 Z6 就地更正——**子代理的结论不能整段直接进主表**。
