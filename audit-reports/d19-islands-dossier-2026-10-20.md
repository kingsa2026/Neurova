# D19 死岛逐档档案（`ede49184` 那一族 6 档）——2026-10-20

> 只读档案，未动一行代码。判定三态：**删 / 接线 / 需人裁**。铁律：无现役替代不判删；
> 全仓唯一实装且无替代 ⇒ 一律需人裁，并写明"删即永久失去该能力"。
> 置信度标记：**✅＝主会话独立复算**；◑＝子代理取证（给了 `file:line` 与 commit，主会话未逐条复算）。
> ◑ 不得与 ✅ 混在同一置信度里汇总——下面按字段标。
> **后续裁定（2026-10-21）**：用户对四旋钮、A1、A2 均选甲并落地（§6-371）——九档一次退净，
> live 脊柱未动；本档的「需人裁」与 §5 选项保留为当时快照。

## 0. 这一批的前置事实（✅，主会话测实，档案不重复证明）

六个模块都被所在包门面 `__init__.py` 无条件再导出，并在真 `create_app()`＋装配腿
（`neurova.agent.team`、`neurova.api.endpoints.acp_api`）的 `sys.modules` 闭包内；
符号级读者在闭包内为零；运行时 profile 钩子记录"该文件内没有任何函数被调用过"。
运行时覆盖边界：只跑到这些入口，**不含需要真 LLM 回合的流程**。

## 1. 档案

### A1 `memory_layer/causal_reasoning.py`（349 行）◑ 取证，✅ 死面由主会话复算
- **原功能**：①因果链 BFS 全路径枚举（路径长 ≤10、去环、按长度排序）`:43-78`；②前向效应传播，
  `confidence × relation.strength × 0.8^depth`、深度 ≤5、去重保高 `:80-127`；③反向根因追溯
  （入边同式衰减）`:129-176`；④因果链中文渲染，25 项关系译名表 + 单步/链式两种文本 `:178-251`；
  ⑤因果图摘要（前后各截 10、直连因果计数）`:253-280`；⑥全图 DFS 因果环检测 + 规范化去重 `:282-337`。
- **关键入口**：`CausalReasoningEngine:20`、`get_causal_reasoning_engine():340`。
- **来历**：`ede49184`(2026-06-11「更新 .gitignore…优化项目结构」批量 add) 首入库；规格出自
  `docs/01-architecture/memory/upgrade-plan-detailed.md:48` 任务 1.2（验收 4 条）。
  符号级 `git log -S "CausalReasoningEngine" -- neurova/` ＝ **1 笔**（✅ 主会话与子代理各自独立算得同数）
  ⇒ **引入即未接线**。
- **读面的数据生产者核查**（✅ 这条决定"接线"那一支的代价）：它读的内存图**确有生产者**
  （`manager.py:4126 _ensure_graph_traversal` 自 `relation_module.get_all()` 灌入）；但它反向推理依赖的
  `caused_by / enabled_by / prevented_by` 三类关系在生产写侧**无来源**——
  `git log -S 'caused_by' -- neurova/` 全史 2 笔（引入 + `62b084e7` 建表 CHECK 白名单），
  三处关系枚举权威源（`knowledge_graph/manager.py:50`、`temporal_knowledge_graph.py:45`、
  `graph_traversal.py:87-99`）只出正向形态。⇒ 接线的真代价是**补生产写侧**，不是补一个调用。
- **现役替代**：**零替代**（◑）。`graph_traversal` 只有 BFS/DFS 可达遍历，其因果类型表 `:87-99`
  是权重字典不是推理器；`QueryIntent.CAUSAL`（`neurova_recall.py:113/165/395/440`）只做意图→通道加权。
  六项能力（多跳链、置信度传播、根因、解释渲染、摘要、环检测）删则全丢。
- **判定**：**需人裁**——全仓唯一实装。删即永久失去记忆图上的多跳因果推理与因果环自检；
  接线即"给反向关系补生产写侧"（改关系枚举 + 建表白名单），属新能力工作。
  **决策影响面**：影响 `memory_layer/` 检索解释面与任何"为什么这条记忆被召回"的产品承诺；
  不接线留下一个 349 行的、每次进程启动都被执行的孤岛。

### A2 `memory_layer/question_decomposer.py`（311 行）◑ 取证，✅ 关键替代点主会话复算
- **原功能**：①七类问题关键词计分分类 `:48-55`、`:88-114`；②因果/比较/程序/通用四套正则定式拆解
  （含"如何解决"二分、比较三对象、程序"前置条件-步骤-注意事项"三段）`:143-232`；
  ③意图→检索策略字典，携 `max_depth/min_score/diversity/serendipity/time_decay/limit` 六参数
  `:234-280`；④子问题策略聚合与序号编排 `:116-141`。
- **关键入口**：`QuestionDecomposer:41`、`QuestionType:19`、`get_question_decomposer():302`。
- **来历**：`ede49184` 首入库；规格 `upgrade-plan-detailed.md:66` 任务 1.3。符号
  `-S QuestionDecomposer -- neurova/` ＝ 1 笔（✅）⇒ **引入即未接线**。
- **同文件内的死半区（✅ 主会话读码复算）**：`_determine_order():282-299` 先构造
  `type_priority`（`:288-296`）再原序返回 `order`，注释自承"这里可以添加更复杂的排序逻辑"
  ⇒ **算完不用、恒返同值**；`llm_client:57-63` 存而不用（全文件零 LLM 调用）；
  `SubQuestion:31-38` 定义后不使用、也不在门面 `__all__`。三处都是只写不读断点。
- **现役替代**：主干**实质替代成立**（◑，其中 `_decompose_query` 一处 ✅ 主会话核到
  `chat_pipeline.py:1878` 真调用、`:1939` 是 LLM 拆解）——`neurova_recall.py:108-116 QueryIntent`
  ＋ `:119-175 QueryIntentDetector`（同为关键词计分、在活路径）顶替①；
  `:465 get_channel_weights` 与 `enhanced_memory_search_api.py:483-509` 顶替③的加权部分；
  `chat_pipeline._decompose_query` 顶替②的通用拆解。**部分缺**：`PROCEDURAL` 分类无对应、
  定式化三段模板拆解无对应、`diversity/serendipity` 两个参数无对应。
- **判定**：**需人裁（推荐删）**——主干有活实现顶上，但上面三项子能力零替代，
  删＝显式承认放弃"程序类问题的定式化拆解"与那两个权重旋钮，这是产品口径，不由代码审计代拍。
  若裁删：同批连带 `tests/unit/cognitive/test_graph_enhancement.py:203-259` 与门面
  `memory_layer/__init__.py:76/136-138` 三行再导出（不留"实现已删、测试还在引用"）。

### A3 `memory_layer/channels/processor.py`（107 行）◑ 取证
- **原功能**：①按 `memory_id` 保高分去重 `:43-52`；②原地乘 `score × channel_weight × activation`
  `:54-65`；③逐条 `TemporalDecay.compute(timestamp)` 衰减乘分 `:67-72`；④全管道串"去重→加权→
  衰减→排序→冲突检测" `:74-107`；⑤`ProcessOutput` 计数台账（total/deduped/conflicts）`:22-29`。
- **关键入口**：`UnifiedResultProcessor:32`、`ProcessOutput:22`（无工厂函数）。
- **来历**：`ede49184` 首入库；规格 `docs/04-plans/iteration-plan-channel-plugin-moe.md:122` 任务 3.1。
  `--follow` 另三笔里最末 `e30f81c9`(09-02「三冲突检测器正名」) 只改它的 import 别名 ⇒ **被改动 ≠ 被消费**。
  符号 `-S UnifiedResultProcessor -- neurova/` ＝ 1 笔（✅）。**引入即未接线**。
- **现役替代**：①②③有实质替代（`neurova_recall.py:1586 _deduplicate_results` 同语义、
  `:1443-1466 _fusion_score` 同式 `base × channel_weight × time_decay`）；**④⑤零替代**：
  live 召回链里没有"管道内语义冲突检测"这一步（`neurova_recall.py` 内零 `conflict` 引用），
  且 `activations` 乘子**没有生产者**（`WeightAdjuster` 在 `neurova/` 只命中自身与门面，全史 1 笔）。
  `memory_layer/result_processor.py` 已于 `0c333a76`(09-21) 退役，不是替代。
- **判定**：**需人裁**——④⑤两处子能力全仓唯一，且 activation 反馈回路从未接线；
  删即永久失去"检索管道内联冲突检测"与"通道权重反馈乘子"。
  另记一条口径债：`docs/specs/2026-09-21-memory-knowledge-foundation-audit.md:369` 把它写成
  "活的 `channels/processor.py:32`"——**文档名实不符**，任何处置前先改判这句。

### A4 `memory_layer/channels/centroid.py`（53 行）◑ 取证
- **原功能**：①遍历通道注册表、跳过已有质心 `:38-42`；②空描述告警跳过 `:44-46`；
  ③把 description 编码成质心 `:48`；④写回 `register_centroid` `:49`；⑤返回新生成条数 `:53`。
- **关键入口**：`CentroidInitializer.__init__(vector_store)` `:16/:19`；`generate_centroids:26`。
- **来历**：`ede49184` 首入库，规格 `iteration-plan-channel-plugin-moe.md:96`（Phase2 任务 2.2，
  其集成项 2.5 从未落地）；`-S CentroidInitializer -- neurova/` ＝ 1 笔（✅）。**引入即未接线**。
- **现役替代**：**部分缺**——活腿 `unified_vector_store.py:616 initialize_centroids`
  （唯一生产者 `memory_layer/moe_router.py:349`，经 `mem_core.py:824` 装配）只按 Expert 定义表建质心，
  **不覆盖插件通道**；`channels/moe_router.py:99-109 _ensure_centroids` 是同能力平行实现且自身零生产读者。
  丢掉：按通道描述建质心、缺失计数、空描述跳过。
- **判定**：**需人裁**——删即永久失去"插件通道质心自动生成"（它读的 centroids 有生产者，但只喂 expert 域）。

### A5 `memory_layer/channels/threshold.py`（46 行）◑ 取证
- **原功能**：①默认阈值 `:16-17`；②按通道名读 `:20-22`；③按通道名写 `:24-26`；④改默认 `:28-30`；
  ⑤导出 flat dict `:32-36`；⑥`from_dict` 装载 `:38-46`。
- **关键入口**：`ThresholdConfig:13`、`from_dict:38`。
- **来历**：`ede49184`，plan 任务 2.3；`-S ThresholdConfig -- neurova/` ＝ 1 笔（✅）。**引入即未接线**。
- **现役替代**：**部分缺**——`settings_config.py:105` 有同口径 `threshold.default`（一个全局 float），
  `mem_core.py:828` 读它并传进 `memory_layer/moe_router.py:65,88`，但**只作用于 expert 门控**；
  per-channel 覆盖表、`to_dict/from_dict` 序列化零替代，settings 里也没有 per-channel 键位。
- **判定**：**需人裁**——全仓唯一 per-channel 阈值实装；删即把它连同"按通道分别设阈值"这件事一起放弃。

### A6 `memory_layer/channels/weight.py`（62 行）◑ 取证
- **原功能**：①六通道默认权重表 `:16-23`；②读归一化权重 `:37-39`；③正/负反馈 ±learning_rate
  `:41-52`；④未知名补 0.1 `:48-49`；⑤min/max 夹紧 `:55`；⑥总和归一 `:57-62`。
- **关键入口**：`WeightAdjuster:13`、`adjust:41`。
- **来历**：`ede49184`，plan 任务 3.4（集成项 3.5 未落地）；`-S WeightAdjuster -- neurova/` ＝ 1 笔（✅）。
  **引入即未接线**。
- **现役替代**：**部分缺**——静态表被抄了两份（`neurova_recall.py:644-651` 逐值重复、
  `enhanced_memory_search_api.py:477` 又硬编码第三份；**这条本身是双源缺陷，单列见 §3**）；
  动态侧 `IntentAwareRecallStrategy.update_channel_weights`（`neurova_recall.py:489`）有写方法但
  `neurova/` 内**零调用者** ⇒ 从未接的数据面。丢掉：反馈驱动增量调整、夹紧、总和归一。
  `knowledge/rerank/weight_rerank_runner.py` 属另一域（bm25/vector/fts），不算替代。
- **判定**：**需人裁**。

## 2. 事件分组（这一批为什么长成这样）

六个模块同出一次事件：`ede49184`(2026-06-11)「更新 .gitignore：排除临时目录，优化项目结构」——
那一次把整棵 `memory_layer` 子树**升格为跟踪面**，规格来自 `upgrade-plan-detailed.md`（任务 1.2/1.3）
与 `iteration-plan-channel-plugin-moe.md`（Phase2/3 的 2.2/2.3/3.1/3.4）。
**计划里的集成项（2.5、3.5）从未落地**，所以这不是渐进腐烂，是"按计划引入了实现、计划后半段没执行"。
推论直接决定处置顺序：要收就得**整族一起**（6 档 + 同族下游），留一半等于留下互相作证的半成品。

## 3. 本批审计中另外发现的缺陷（单列，不折算成简化收益）

1. **悬空指路**（✅）：`tests/unit/cognitive_layers/memory_layer/test_temperature_single_source.py:235`
   在退役 `unified_reasoning_engine` 时把"因果推理入口"指到 `causal_reasoning`，而该格只验
   "退役文件不存在 + 无人 import"（`:274-286`），**不验指路目标是否活着** ⇒ 指到了一座孤岛。
   同句复述于 `docs/05-reports/memory-temperature-convergence-2026-09-21.md:84`。
   任何处置 `causal_reasoning` 之前必须先改判这条指路。
2. **跨模块直取私有字段**（◑）：`causal_reasoning.py:318-321` 读 `graph._graph` / `graph._reverse_graph`。
3. **权重表三份表示**（◑，撞教义第 6 条）：`channels/weight.py:16-23`、`neurova_recall.py:649`、
   `enhanced_memory_search_api.py:477`。
4. **文档名实不符**（◑）：`docs/specs/2026-09-21-memory-knowledge-foundation-audit.md:369` 称
   `channels/processor.py:32` 为"活的"；`docs/specs` 之外 `iteration-plan-*.md` 仍是计划文本，不算宣称。
5. **测试替身触禁区**（◑）：`tests/unit/memory/test_moe_routing.py` 等用 `MagicMock` 冒充 `vector_store`
   测这六个岛——测的是岛内自洽，不构成生产消费证据（教义第 3 条点名的形态）。

## 4. 主会话对本批两条口径的自纠（写进档案，不留给下一批去发现）

1. **`conflict_detector_v2` 的判活证据作废**。§6-357 曾记它"有活读者：经 `memory/__init__.py:19`
   ＋ `conflict.py:260`"。本批复算：`memory_layer/conflict.py:260` 是**同名别名的定义行**
   （`ConflictDetector = LegacyConflictDetector`，09-02「三冲突检测器正名」留的兼容别名），
   不是对 v2 的取用；`neurova/memory/__init__.py:19` ＋ `__all__:127` 是**聚合门面的再导出**，
   而 `from neurova.memory import ConflictDetector` 在全仓**零消费者**（✅ grep 复算）。
   两条判活证据同时是伪命中（同名不同物 ×2、门面再导出 ≠ 消费者 ×1）⇒ `conflict_detector_v2`
   从"活"回到"待档"，其死列归属另批补档案（它的来历含 `e30f81c9`/`3f1edd57` 两次正名，
   不能按"引入即未接线"一句带过）。
2. **11 档是下限，不是全量**。候选谓词写的是"闭包内的 importers 全是门面"，于是
   **被死岛读**的下游模块直接掉出候选面：`channels/temporal.py` 与 `channels/conflict.py` 的读者是
   门面 + 已判死的 `processor.py`（✅ 复算 import 面），按这条谓词它们连"被审判"的资格都没有。
   正确形制是把"读者是否活"递归进**候选面的构造**（不动点算在候选集上，不是只算在死列上）。
   同族的 `memory_layer/moe_router.py` 由 `memory_layer/__init__.py:18` 门面再导出，
   其与 `channels/moe_router.py` 的分工本批未查。
   ⇒ §6-357 那句"第三例存在＝11 档 2412 行"要按"已扫出的下限"读，不是"扫净了"。

## 5. 处置路线（等拍板后走，本批不动码）

**先纠正一条被问错的路线问题**（2026-10-20 用户质疑后现读复核，台账记于 §6-361）：本档案初版把待裁项
写成"MoE 通道插件化这条路线要不要继续"——**那是伪问题**。现读：

- 通道插件化**已经是记忆检索的现行设计且在服**：`neurova_recall.py:615-626` 在 `use_plugins` 下把
  `BUILTIN_CHANNELS` 自动注册进 `channels/registry.py` 的 `ChannelRegistry`，`:955` 按
  `ch.metadata.name ∈ enabled_names` 取启用通道并并发跑 `retrieve()`。
  ⇒ `base.py`/`registry.py`/`builtin/*` 是活脊柱（与 §6-357 运行时 profile 读到 `metadata()` 被调一致）。
- MoE（expert 域）同样在服：`mem_core.py:824` 构造 `MoEMemoryRouter`、`:925` 挂到 agent，
  `chat_pipeline.py:252-254` 经 `retriever_adapters.MoERetrieverAdapter` 用在检索路上；
  `memory_layer/moe_router.py:350` 是 `unified_vector_store.initialize_centroids` 的唯一生产者。
- 顺带排掉一条双源误报：`neurova/channels/plugin_channels.py` 的 `PluginChannelRegistry` 是
  **消息渠道**插件面（`api/endpoints/channel_config.py:482/1114` 在服），与
  `memory_layer/channels/registry.py` 的 `ChannelRegistry` 同名不同物，**不是**第二份注册表。

**所以真正要裁的问题收窄成一句：这条已在服的脊柱上，四个没接的旋钮要不要接。**

| 旋钮 | 文件 | 今天缺的那半边 |
|---|---|---|
| per-channel 阈值覆盖 | `channels/threshold.py` | 只有一个全局 `threshold.default`（`settings_config.py:105`→`mem_core.py:818`）且只作用于 expert 门控 |
| 反馈驱动的通道权重 | `channels/weight.py` | 权重被手抄成两份静态表（`neurova_recall.py:649`、`enhanced_memory_search_api.py:477`），无人写回 |
| 插件通道质心自动生成 | `channels/centroid.py` | 质心只按 Expert 定义表建（`memory_layer/moe_router.py:350`），不覆盖插件通道 |
| 统一结果管道 | `channels/processor.py` | live 召回链里没有"内联语义冲突检测"那一步，且 `activations` 乘子**在仓内没有生产者** |

- **接** ⇒ 是一批"补 MoE 计划集成项 2.5/3.5"的接线工作，上面这四档的表结构本就是为这条路准备的，
  可直接复用；真正要新增的是**写侧**：反馈事件从哪个咽喉来、per-channel 阈值在哪配、
  插件通道要不要落盘质心——这三件都是产品口径，不由代码审计代拍。
- **不接** ⇒ 这四档 ＋ 同族下游（`channels/temporal.py`、`channels/conflict.py`，以及通道域那份
  `channels/moe_router.py`——它与在服的 `memory_layer/moe_router.py` 是两份东西，读者面待另档复核）
  一次退净，净 LOC 为负。
- 无论哪一路，**`causal_reasoning` 与 `question_decomposer` 另裁**（它们不在这条脊柱上）：
  前者是"要不要多跳因果推理"这项能力（接线要补反向关系的生产写侧），
  后者按 §1·A2 的替代面裁"要不要 PROCEDURAL 定式拆解"。

任何删除都同批退役其专用测试与门面再导出行，并先修 §3 那三条指路/名实缺陷——
顺序反了就会留下"文档说有、代码没有"的更大坏形（§6-115 的教训）。
