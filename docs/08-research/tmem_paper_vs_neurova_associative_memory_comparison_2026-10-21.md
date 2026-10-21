# T-Mem 论文与 Neurova 记忆系统代码级对比（2026-10-21）

> **性质声明**：本文属 `docs/INDEX.md` §2.4「竞品/外部对标」——**研究参考，仅作背景，不可作为本仓设计的事实源或对齐依据**（`AGENTS.md` 协作红线 §2：外部项目只作功能依赖或背景登记，严禁在代码、注释、文档中引用/模仿/对齐第三方实现，不搬运其命名、结构与措辞）。文中候选若要落地，一律按本仓修复教义独立立项（先红后绿 + live-verify），本文不构成对齐承诺，**也不授权搬运其代码或提示词**。每条候选的立项理由均写成本仓自身可核实的断点，「对方有 X」只出现在提问语境，不出现在理由列。
>
> **对比对象**：`github.com/Sherlockwz/T-Mem`（MIT，作者署 Tencent，shallow clone @ commit `dd9e1527bc75908485809580c9520af5a9a42879`，提交日 2026-09-09；抓取日 2026-10-21）。论文 `arXiv:2606.15405`「T-Mem: Memory That Anticipates, Not Archives」，EMNLP 2026 Main。仓内 12,465 行 Python（`T_mem/`）+ `benchmark_eval/` 判分适配。
>
> **方法**：两侧独立代码细读，证据一律 `文件:行号`。外部仓行号绑定上述 commit；Neurova 行号绑定 2026-10-21 工作树，后续会漂。**外部仓未实跑**（需 OpenAI 兼容 LLM/Embedding/Rerank 三套端点，且 `locomo10.json`/`locomo_plus.json` 数据集不随仓分发），凡未实跑处均标注为「仅代码读」。论文正文表格未能机读，公开可读读数只取自其 project page（`docs/index.html`）与摘要，已逐处标注。
>
> **阅读对象**：`neurova/cognitive_layers/memory_layer/`、`neurova/context/`、`neurova/post_chat_pipeline.py` 的维护者。
>
> **前作指针**：本域前作 `agent-memory-cutting-edge-research-2026.md`（论文综述型，未做代码级对比、未覆盖联想召回议题）与 `mflow_vs_neurova_memory_comparison.md`（**该文件现不存在，§2.4 列表为悬空引用**，另批处理）。本文只记前作未覆盖项，候选编号另起 `TM-1..TM-6`，不占前作号位。

---

## 0. 结论摘要

- **一句话画像**：T-Mem 是一个**离线基准上的检索构造法**——把「未来可能怎么被问到」在写入时就写成一条只参与检索、不作为证据的旁路文本，再用 主题→场景→条目 三层级联把候选收窄；它的贡献是把「查询与记忆无表面重合」这一类召回做成了可复现的工程形态。Neurova 是一个**生产常驻的记忆系统**——写侧刻意零 LLM、检索走本地 ONNX + 关键词的加权 RRF、带温度/结晶/生命周期/来源信任/作用域/反馈学习六通道治理；它缺的恰好是 T-Mem 有的那一维（写入侧预演），而 T-Mem 缺的恰好是 Neurova 的全部治理面。

- **最重要的四个判断**：
  1. **它的增益高度集中在一个组件上，不在「四族触发器」这个对称结构上**。公开可读的消融只有一个方向：去掉 Horizon 一族，LoCoMo 从 80.26 → 80.18（**几乎不动**），LoCoMo-Plus 从 74.81 → 62.34（**−12.47pp**）；去掉 Scene+Horizon 两族 −22.19pp（`docs/index.html:118`，commit `dd9e152`；该图注未注明后一项属哪个基准，且**未公开 w/o Entity、w/o Bridge、w/o 主题层、w/o 重排各自的行**）。也就是说「前瞻性描述」是联想召回承重墙的直接证据；**条目级 Entity/Bridge 的贡献量属未知，不可读成「它没用」**，只能说没有公开证据显示它撑住了主表分。**本仓若只借一样，就该借前瞻线索，而不是照着四族对称建四套索引。**
  2. **它的写入成本与本仓的写侧架构直接冲突**。构建一条 400 轮对话约 **800–900 次 LLM 调用**（边界检测每轮 1 次 `stage1_memory_extraction.py:131-173` + Entity/Bridge 每条记忆 1 次 `build_trigger.py:43-63`，二者不可批量），≈ **2.1 次 LLM/轮**。而本仓写侧的实体与依赖提取**显式声明零 LLM**（`moe_dependency_extractor.py:1-4`「运行时成本: $0」），嵌入走本地 ONNX（`unified_vector_store.py:11`），相邻后台步骤还把「全确定性零 LLM」当作刻意约束（`post_chat_pipeline.py:3261`）。**照搬即把每轮对话的记忆写入从 $0 变成 2 次模型调用**，这不是优化能弥合的，是量级选择。
  3. **它没有增量写入路径，这是与本仓最硬的不兼容**。每个 stage 都是「整段对话重跑」，幂等只做整文件跳过：stage1 见 `scene_list_conv_*.json` 即跳（`stage1:224-237`），stage2 见 `memory_graph_conv_*.json` 即跳（`stage2:387-397`），索引是**每会话一个 pickle 的 BM25Okapi + 向量表**（`stage3_index.py:164-166`），无 schema 版本、无 append（`build_memory.sh:133-160`）。`--resume` 是崩溃续跑，不是「新轮次并入既有记忆图」。本是在线系统，这一条决定了：**任何落地都必须重设计成「追加式派生工件」，不能移植它的构建形态。**
  4. **它的读数不能当作本仓的期望涨幅**。LoCoMo-Plus 的构造方式（`stage0_locomo_plus_stitch.py:1-23`）是**为每个问题单独合成一座记忆库**：把该样本的 cue 对话插进基座会话、把 `trigger_query` 追加在 7 天之后，样本 i 只用样本 i 自己的库检索（`stage5_retrieval_locomo_plus.py:80-170`）。它测的是「小库 + 无表面重合」的可达性，**不测「几万条跨会话、带作用域与信任来源的候选里还能不能捞准」**——后者的主要矛盾是精度与成本，不是可达性。另外 Scene/Horizon 通道的候选是**按问题字符串离线预计算**并存进 `scene_horizon_topk_per_qa.json`，stage6 以 `(conv_id, question)` 精确字符串查表（`stage6_retrieval.py:202-208, 1176`），查不到就退回基线——生产环境不可能预知未来问题串，等价实现只能改成在线「一次嵌入 + 一次矩阵乘」，可行但**报告的消融差值不能直接换算成本仓收益**。

- **明确不建议照搬**（逐条理由见 §5）：逐轮 LLM 边界检测、整会话重建 + pickle 索引、无主题即中止的级联回落、开放标签集的主题层（LLM 自拟主题名、**无主题间去重合并** `topic_extractor.py:481-528`）、按问题字符串预计算的关联通道、把 persona 折进证据链（其默认关闭，`stage8_qa_locomo.py:92-110`）、以及它的提示词与命名。

- **本仓已有、不需要引进来的**：加权 RRF 融合（向量 0.7 / 关键词 0.3，k=60，再乘 `MemoryOrigin` 信任权重，`manager.py:2104-2115`）——**在融合这一步本仓实装强于它**（它是 k=60 的无权 `1/(60+rank)`，`stage6:220-248`）；多通道并发召回与意图条件权重（可反馈学习）、下钻阶段、温度/结晶/生命周期、作用域隔离、11 语言。

### 0.1 对用户所述落地流程的事实核对

用户给的八步骨架与代码大体一致，四处需要更正，否则按错的口径施工会白建索引：

1. 「触发器四类」的**粒度是成对的**：Entity/Bridge 是**条目级**、Scene/Horizon 是**场景级**（`trigger_prompts.py:1-9` 的映射注释 + `stage4_associative_extract.py:99-146`）；不是四个同级旋钮。
2. 「Bridge 和 Horizon 绕过主题过滤直接注入候选」——**绕过点在层内注入候选池，且不注入结果**：Scene/Horizon 注入场景池（`stage6:626-660`），Entity/Bridge 注入**条目**池（`stage6:792-832`，不是场景级）；被注入的候选**仍要过 BM25/向量/RRF/重排才进提示**（`stage6:804-811`）。
3. 「阈值 0.85 筛高置信项」——0.85 **不是条目置信阈值**，是 Entity/Bridge 通道上「查询向量 ↔ 触发器向量」的余弦门（`stage6:67-75, 793-803`；`trigger_recaller.py:147-180`）。条目侧的置信门是 **0.70 且作用在写入时**（`build_trigger.py:267-271`；`trigger_extractor.py:214-227`）；另有 0.90 的 fuzzy 去重门（`trigger_index.py:138-183`）。**最终进提示的场景与条目上没有任何分数阈值**，只有截断（5 场景 / 15 条，`config.py:99-101`，且由正则重写已格式化的字符串实现，`io/truncate_search_results.py:149-185`）。
4. 「检索组件全程 CPU 可跑」——成立的是「不需要本地 GPU」：BM25/numpy 确在 CPU；但嵌入与重排都是 **HTTP 调用**（`llm/embedding_provider.py:77-108`、`llm/reranker_provider.py:82-135`），每查询发 **4 次嵌入 POST（同一查询向量不复用，`stage6:337, 699, 796, 876`）+ 3 次重排 POST**。主题层 250→15 的收窄依赖重排（重排关闭时该层直接用 `topic_top_k`）。本仓记忆主路**当前不接重排器**（`knowledge/rerank/rerank_factory.py:11` 默认 dependency-free 加权，只接在知识库面）。

---

## 1. 它在解决什么问题，以及它怎么解决

### 1.1 问题切分：descriptive ↔ associative

论文的立论是「相似度记忆有**可达性上界**」：查询与存储内容若不共享词面（措辞、实体名），稠密向量与词法检索一同失效，而这类「无表面重合但相关」的提问真实存在（同事三个月前说过的虾过敏 ↔ 今天问团队聚餐餐厅）。本仓代码可核实地复现了这个上界的形态：chat 主路的记忆候选来自 `injector.py:1016` → `MemoryManager.recall`，其排序只由**向量命中 + 整句查询子串命中**两路融合（`manager.py:2098-2101` 的关键词路是 `query_lower in m.content.lower()`——查询整串包含，连分词都没有）；提示拼装阶段再加一层「主题相关性」，实现是**关键词子串计数**（`injector.py:568-573`）。写侧实体走正则关键词表（`moe_dependency_extractor.py:24-40`，person/event/concept 靠「张三/Alice/会议/部署」这类硬编码词表）。**这三处相加，本仓的可达性完全由词面与嵌入决定，不存在任何「由写入时生成的一条抽象文本承载的第二访问路径」。**

### 1.2 解法的两个承重设计

- **写入时预演（write-time rehearsal）**：写入时不摘要，而是生成「在什么情况下这条记忆会重要」。条目级产出 2–6 词的上位名或强关联情境（Route A/Route B，`trigger_prompts.py:25-37`），场景级产出 5 个前瞻通道——个人转变弧、回避/警觉习惯、目标弧及其代价反弹、行动中信念的脆弱面、可能复现的具体遗存锚（`trigger_prompts.py:117-145`）。条目侧还额外生成 `query_patterns`（假想未来问句），并以 **×2 权重直接混进检索文本**（`stage3_index.py:75-78, 388-390`）——这是全部机制里最便宜、也最容易借的一条。
- **访问路径与证据分离（type segregation）**：触发器**永不进 QA 提示**，主题标签**永不进 QA 通道**（README「三处设计承诺」），进提示的只有原始场景与条目。这条纪律的价值在于：用抽象文本提高召回，同时不让抽象文本污染答案的事实依据——本仓若引入线索，这条纪律必须一并引入，否则线索文本会退化成又一层摘要并被当成证据引用。

### 1.3 公开读数与口径限制

| 口径 | LoCoMo | LoCoMo-Plus | 来源 |
|---|---|---|---|
| T-Mem 主表（GPT-4.1-mini 构建 / GPT-4o-mini QA+判） | 80.26（token F1 51.96） | 74.81 | `README.md:111-116`、`docs/index.html:39-40` |
| 去 Horizon 一族 | 80.18 | 62.34 | 同上 |
| 跨基准落差 | 5.45pp（其他系统 28–50pp） | — | `docs/index.html:87-89` |
| 换 GPT-5.1 构建+QA | 84.85 | 未报 | `docs/index.html:105-109` |

限制四条：① 判分模型两套不同（Plus 用 GPT-4o QA + Gemini-2.5-Flash 判），跨列比较不可靠；② 无 Recall@k / NDCG 等检索本体指标，全部结论经 QA 分间接得出（论文页可机读部分未报检索指标）；③ 无公开的写入 token/延迟核算，仓内 `utils/cost_ledger.py:52-57` 仅在 `T_MEM_COST_LOG` 置位时记账，默认 no-op；④ 800–900 次调用/构建 这个数字是本仓按 stage 调用面**复算**的（见 §2.1 逐档算式），论文未给。

---

## 2. 它的实状（构建 / 检索 / 成本 / 工程缺陷）

### 2.1 构建侧逐档算式（400 轮 ≈ 40 场景 ≈ 200 条目 ≈ 20 主题的一条会话）

| 档 | 调用粒度 | 次数估算 | 证据 |
|---|---|---|---|
| 边界检测 | **每轮 1 次** | ≈ 398 | `stage1:131-173`；`conv_scene_extractor.py:201-246` |
| 场景生成 | 每闭合场景 1 次 | ≈ 40 | `conv_scene_extractor.py:239-356` |
| 主题匹配 | 每场景 × ceil(主题数/10) | ≈ 80–150 | `topic_extractor.py:97-99, 464-477` |
| 主题更新/新建 | 每匹配主题 1 次 | 含上行 | `topic_extractor.py:481-528` |
| 条目抽取 | **每主题 1 次（可批量）** | ≈ 20 | `memory_item_extractor.py:165-292` |
| Scene/Horizon 线索 | 每场景 1 次（>10 轮跳过） | ≤ 40 | `stage4:99-146, 178-188` |
| Entity/Bridge 线索 | **每条记忆 1 次 × 5 条** | ≈ 200 | `build_trigger.py:43-63`；`trigger_extractor.py:103-117` |
| Persona | 每窗口 2 次 | ≈ 14 | `profile_memory.py:439-465`；`persona/common.py:28-32` |
| **合计** | | **≈ 800–900** | 只有主题匹配、条目、persona 三处可批量 |

**两个不可批量的成本大头（逐轮边界、逐条 Entity/Bridge）恰是本仓最不该碰的两处**：本仓记忆原子单位是「一条消息」，比它的 scene 粒度小 3–5 倍，按它的形态套过来，单位成本还要再乘一个粒度失配的倍数。边界检测机制也值得记住：它**不是**嵌入断点也不是启发式，是每轮问一次模型「该不该收尾」（`should_end/confidence/reasoning/topic_summary`），时间差只作为提示里的文字线索喂给模型（`conv_scene_extractor.py:149-198`），解析失败时默认「继续等待」`should_wait=True`（`:232-238`）——即**故障方向是悄悄把整段对话并成一个场景**。

### 2.2 检索侧的真实形态

`stage6_retrieval.py:443-956` 三层：主题层 BM25∪向量→RRF→重排取 15 → 场景池 = 命中主题的 `scene_ids` ∪ Scene/Horizon 关联场景 → RRF→重排取 24 → 条目池 = 入选场景的 `item_ids` ∪ Entity/Bridge 召回条目 → RRF→重排取 40 → 格式化为文本串 → 截断为 5 场景/15 条 → 1 次 LLM 生成答案。

四条必须记住的形态：
- **回落是「断」不是「宽」**：主题层为空即直接返回空结果，二三层不再执行（`stage6:580-583`）；场景层同理（`:762-765`）。本仓主路的降级形态相反——向量服务不可用时回落关键词单路（`manager.py:2078`）。**级联一旦作为主路，预过滤失败的用户可见后果是「完全没有记忆」。**
- 重排重试耗尽时返回**全零分**并按原序切片（`llm/reranker_provider.py:176-177`），此时排序无信号但仍产出结果；
- 重排会**丢弃文本字段为空的文档**（`stage6:385-392`）——场景缺 `scene_description` 就在开启重排时凭空消失；
- 嵌入重试耗尽抛异常，会话级 `except` 吞掉并返回 `[]`（`stage6:1228-1232`）——**整段会话的检索结果静默丢失**。

---

## 3. 本仓的自有断点（候选的立项理由都在这里，与 T-Mem 无关）

按 `AGENTS.md` §核心原则 7/§2「断点」口径，每条写清：现状证据 / 接通后实现什么 / 不接留下什么 / 影响面。

**D1 · 名义存在关联、实为别名。** `manager.py:4547-4557` 的 `recall_with_associations(query, depth=1, **kwargs)` 直接 `return self.recall(query, **kwargs)`，`depth` 在文档串里自称「保留参数, 当前实现等价于 recall」。影响面：任何按「关联展开」语义调用它的面（含 `neurova/memory/` 门面再导出的兼容别名）都拿不到任何关联结果，而调用方从签名看不出来。不接：一个名字承诺了能力、实现不兑现的公开 API 常驻在记忆门上。

**D2 · 检索可达性无第二访问路径（承重）。** 三处证据见 §1.1：RRF 两路输入皆词面/嵌入、主题相关性是子串计数（`injector.py:568-573`）、写侧实体靠硬编码词表（`moe_dependency_extractor.py:24-40`）。接通后：查询与记忆无共同词面时，仍有「写入时生成的抽象线索」可被命中；不接：这类提问只能靠运气落在 embedding 的近邻上。影响面：`MemoryManager.recall`、`NeurovaRecallEngine` 六通道、`context/injector.py` 记忆段拼装。

**D3 · 写侧没有场景/事件边界层。** 每轮严格落 2 行（`post_chat_pipeline.py:1292-1304`，`content="用户: …"` / `"助手: …"`，`memory_type="episodic"`），`episodic` 只是类型标签不是分段单位；唯一的窗口行为是缓冲区写满即刷（`mem_core.py:1126`）；`sleep.py:303 cluster_by_similarity` 是**离线事后**聚类，不产出可寻址的段落单位。影响面：任何「按事件闭合预演」的工作都缺承载体——这是 D2 的下游前置。

**D4 · 多标签分类器已实装，但主路恒关。** `auto_classifier.py:332` 有 `classify_category_multi_label`（阈值 0.3），却只被内部打分处消费（`:259`）；对外入口 `remember(auto_classify=False)` 默认关（`manager.py:1380`），而 chat 写侧两处 `remember(...)` 调用都没传该参数（`post_chat_pipeline.py:1292, 1299`）；`manager.py:1361` 注释自陈「99% 的行因此恒 general」，API 侧才显式打开（`:1402` 文档）。影响面：写侧落库的 99% 记忆不带推断类别 → 任何按类别收窄的候选池（含 `recall(category=...)` 过滤，`manager.py:1729`）对主线数据实际失效。这是「只写不读 / 只造不接」的现役样本，不是新能力缺口。

**D5 · 记忆检索质量没有任何常驻判据（最高优先）。** `tests/performance/longmeval_simple.py` 是一个 6 维 LongMemEval 形状的手写件，但 `pyproject.toml:102-103` 规定 `python_files=["test_*.py"]`、`python_classes=["Test*"]`，该文件名与其类 `SimpleLongMemEval` 双双不匹配；实测 `pytest tests/performance/longmeval_simple.py --collect-only` 返回 **collected 0 items**——**这份测量件今天跑不起来，也从没进过门禁**。全仓无 LoCoMo 类基准，`benchmark/rag_eval.py` 与 `knowledge/evaluation/retrieval_benchmark.py` 只覆盖知识库面。影响面：D2/D3 的任何改动都无法证明有效；按 §3 红灯教义，**没有红可咬的改动不许开工**。这条是本文所有候选的前置。

**D6 · 「线索/trigger」概念在本仓已有同名死物。** `memory_layer/schema.py`（285 行第二份 DDL，零 importer，其 `trigger_chains`/`memory_relations` 表在活库中不存在）、`explainability.py`（646 行 trigger-chain DAG，`start_chain/add_step` 无生产调用，档案 `audit-reports/cognitive-layer-zero-reader-dossier-2026-10-20.md:27`）。影响面：若新增一套叫「trigger」的东西，即制造 §6 双源与 §7 并存，且让退役档案更难读。**落地时不得复用 trigger 命名，且同批要按 §7 处理这两处死物。**

**D7 · `temporal_reasoner.py` 是零读者孤岛，今日刚裁定「暂留」。** 台账 §6-380 的裁定原文：「`security`＝丙 暂留、`temporal_reasoner`＝丙 暂留……**保留期间不改 live 行为；未来若要接/删，按上面三态影响面另批走**」（`audit-reports/simplification-audit-2026-10-05.md:9422-9424`）。它已实装 Allen 区间关系的推断/传递闭包/约束/矛盾/排序五类。含义：前瞻线索需要「时序之后发生什么」的承载体，本仓**已有唯一实装**——这是 §6-380 三态票里「甲 接线」的天然消费者，但**必须另批立项**，不得借本文名义顺手动它。

---

## 4. 候选清单（TM-1..TM-6）

每条只写：立项理由（本仓断点）/ 落地面 / 成本 / 判据 / 风险。编号另起，不与前作 `P1-*`、`K1-*`、`M-*`、`N-*`、`C-*` 号位冲突。**未点单不动码**（与用户既有纪律咬合）。

**TM-1 · 记忆检索质量的常驻判据集（前置，必做）**
理由：D5。落地面：新增 `tests/performance/memory/test_*`（或先把 `longmeval_simple.py` 改名+改类以进收集），含一维「无表面重合联想召回」子集——构造 `(记忆行, 词面不相交却相关的查询, 干扰项)` 三元组，判据咬 `MemoryManager.recall` 与 `context/injector._retrieve_memories` 两处的 Recall@k 与命中位次；数据集本仓自建（中文/双语、跨会话、带作用域与 `origin` 干扰项），**不引入外部数据集与其判分提示词**。成本：纯测试基建。风险：合成集可能过易 → 判据须先用现状实跑取基线读数，读数不为零区分度即重造。
**这是唯一「不做就没法证明其它任何一条」的候选。**

**TM-2 · 条目级抽象线索入检索文本（最便宜的一条可达性改造）**
理由：D2 + 现状关键词路是整句子串匹配（`manager.py:2098-2101`）。做法（本仓自设，非移植）：写入时对**新行**生成 1–2 条短语级上位/情境线索，以带权字段并入既有嵌入文本与关键词索引，不新建第二份索引、不改排序公式；沿用 D4 已有的 `auto_classifier` 多标签结果作为廉价上位来源可先验证价值。成本：每行 1 次小模型调用（可批量到「一次多行」，与它 per-topic 批量抽条目的形态同理），或先走零 LLM 的规则上位以守住 $0。判据：TM-1 的联想子集在改动后由红转绿。风险：线索进嵌入文本会稀释原句语义 → 须限权重并复测标准召回不回退。

**TM-3 · 前瞻线索：追加式、离线窗口、只检索不作证据**
理由：D2+D3，以及 §0 判断 1（增益集中在前瞻）。落地面：复用**已接线**的 10 轮低负荷固化窗口（`post_chat_pipeline.py:3251-3260` → `idle_tracker.trigger_consolidation()`）与其相似聚类产物（`sleep.py:303`）作为生成时机，对「已成段」的记忆批量产出少量前瞻线索，存为独立表（**经 `core/db_migration.py` 注册表加 schema，PRAGMA user_version**，不得写进 D6 的死 DDL），检索侧作为**旁路注入候选池**、与既有平路 RRF 取**并集而非替换**，并强制「线索文本永不进提示证据」的纪律。成本：必须设**每次运行的 LLM 调用上限 + 配置键默认关**（比照 `auto_apply_skill_evolution` 的 pending/自动二选一先例），并按段落批量。判据：TM-1 联想子集显著提升且标准子集不降；固化窗口耗时上界有常驻守卫。风险：最高的一条——写入成本、窗口预算、与 `temporal_reasoner` 的接线边界（D7）都需人裁；建议以 TM-1→TM-2 的实测数据回来再拍。

**TM-4 · `recall_with_associations` 二选一（接线或退役）**
理由：D1，属 §7「同功能先比后合」与 §2「断点」的直接命中。甲 接：让它真的走 `DependencyGraph` 上下游展开（`neurova_recall.py:1360 _channel_graph` 已有该逻辑可收口为单一实现）；乙 删：连同门面别名与测试一并净删。判据：不允许第三态（保留别名）。影响面：`manager.py`、`neurova/memory/` 门面、相关 API。

**TM-5 · 场景层的派生工件形态（TM-3 的前置）**
理由：D3。约束（与它相反的设计选择，须写死）：**append-only、增量、可失效重建**，段边界优先用已有信号（会话/作用域切换、`session_id` 边界、时间差、主题跳变）而不是逐轮 LLM 判定。成本：零 LLM 起步。风险：分段质量决定 TM-3 的天花板，须由 TM-1 的段落指标先给基线。

**TM-6 · chat 主路是否打开类别推断（产品语义裁定票）**
理由：D4 的「99% 恒 general」是现役事实，但把它打开会改变存量记忆的可见性与过滤行为，属产品语义。三态票：甲 开（新行按推断打标，存量不回填）/ 乙 关并删掉多标签实装的悬空面（`auto_classifier.py:332` 若仍只内用则收敛为内部函数）/ 丙 开且回填存量（代价最大，需迁移与回滚方案）。**推荐甲**，因为它同时是 TM-2 的零成本上位来源。

**推荐起手序**：`TM-1 → TM-2 → TM-6(甲) → TM-4 → TM-5 → TM-3`。前四条为净测/净接，不新增重依赖可各自独立成批；TM-3 必须带 TM-1 的实测涨幅再来拍板。

---

## 5. 不照搬清单（每条都写「照了会退步在哪」）

| 它的形态 | 证据 | 本仓照搬的后果 |
|---|---|---|
| 逐轮 LLM 边界判定 | `stage1:131-173` | 写侧从 $0 变 ≈1 次调用/轮（`moe_dependency_extractor.py:1-4` 的零成本纪律被推翻）；解析失败默认「继续等」会把整段并成一个场景 |
| 整会话重建 + per-conv pickle 索引 | `build_memory.sh:133-160`、`stage3_index.py:164-166` | 无 append 语义；在线系统每轮都要重建，且 pickle 无版本与 schema 约束，属 §6 之外的第二份存储口径 |
| 主题层为空即整体返回空 | `stage6:580-583` | 预过滤失手的用户可见症状是「记忆全丢」，比本仓现有的关键词单路降级更脆 |
| 开放标签主题（LLM 自拟名、无主题间合并） | `topic_extractor.py:481-528` | 生产规模下主题随会话数线性碎裂，预过滤召回反噬；本仓 `MemoryCategory` 是有界枚举（7 值），治理性优于它 |
| 按问题串预计算关联候选 | `stage6:202-208, 1176` | 生产无未来问题串可索引；等价实现须走在线嵌入，其报告差值随之失效 |
| 截断靠正则重写已格式化字符串 | `io/truncate_search_results.py:149-185` | 在 LLM 面向文本上做结构截取，token 预算与证据完整性不可控；本仓已有 `_foldMemoryLineToBudget`（`injector.py:583-600`）走对象级 |
| 会话级异常吞掉返回空 | `stage6:1228-1232` | 直接违反修复教义第 2 条（不得吞异常/降级为静默） |
| persona 折进证据链 | `stage8_qa_locomo.py:92-110`（默认关） | 与本仓 `personality.md` / `UserProfile` 的既有分域冲突，制造第二份画像事实源（§6） |
| 其提示词、四族命名、字段名 | `prompts/*` | `AGENTS.md` §2 原创性条款明禁引用/模仿/对齐第三方实现；且 trigger 命名撞 D6 死物 |

---

## 6. 未验证项（不冒充已核）

1. **论文 Table 4 全表不可机读**：本文只有两条消融方向来自其 project page 图注与文字（`docs/index.html:118`），Entity/Bridge/主题层/重排各自的独立贡献量**未取到**，因此「只借前瞻」的判断建立在你已经能复核的 0.08pp vs 12.47pp 这一对上，不是完整消融。
2. **T-Mem 未实跑**：需三套 OpenAI 兼容端点且数据集不随仓分发，本文全部外部结论为代码读。其 `--mode locomo_plus` 端到端是否能跑通、重排/嵌入服务的具体吞吐，均**未验证**。
3. **LoCoMo-Plus 数据集本体未获取**：§0 判断 4 关于「每题一库」的表述取自 `stage0_locomo_plus_stitch.py:1-23` 的 docstring 与 `stage5_retrieval_locomo_plus.py:80-170` 的绑定实现，**未与原始 benchmark 论文核对**。
4. **本仓行号会漂**：Neurova 侧证据绑定 2026-10-21 工作树；并发会话可能重写历史，落地前须按 `merge-base --is-ancestor` 复核所引提交可达。
5. **本文未登记台账、未建判据、未改任何代码**——纯只读对比档案。TM-1..TM-6 各自落地时按八段流水线另批开工并回写 `audit-reports/simplification-audit-2026-10-05.md`（下一枚空号现查 §6-381）。
