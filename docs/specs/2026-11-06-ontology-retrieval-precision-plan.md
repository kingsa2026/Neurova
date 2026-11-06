# Agent × Ontology 知识库检索精准度分析与改进方案

> 定位：回答"Agent 调用 ontology 知识库是否精准、能否根据用户问题和场景输出最佳答案"，逐层审计现有链路，给出可落地的改进策略。
> 事实源：`neurova/agent/chat_pipeline.py`、`neurova/agent/knowledge_retriever_adapter.py`、`neurova/knowledge/hybrid.py`、`neurova/knowledge/derivation_citation.py`、`neurova/context/injector.py`、升级计划 §12（B8–B14 已落格，v29–v34）。
> 前置：本体语义栈升级 B1–B14 全部落格（台账 §6-552..568），评分 6.8→8.0。

---

## §0 一句话结论

**检索"能找到"但"找不准、注入"知有但不知其义"**——本体语义栈（类型层级/关系特征/条件类/推导账本）在数据层已完备，但**从用户问题到 LLM 上下文之间缺了三座桥**：① 用户语言→本体术语的桥（语义归一/查询扩展）；② 本体语义→检索策略的桥（类型感知路由/多跳遍历）；③ 检索结果→LLM 结构化上下文的桥（类型分层注入/推导标注可见）。三座桥不通，本体的语义能力只在写面生效（写入时校验/物化），读面仍然是"纯文本相似度 + 扁平列表"。

---

## §1 现有链路逐层审计

### §1.1 用户问题 → 检索入口（精确度 ★★★☆☆）

| 环节 | 现状 | 精准度影响 | 证据 |
|---|---|---|---|
| 查询归一（W1） | `NEUROVA_KB_QUERY_NORMALIZE` **默认 off**；on 时把命中主体的规范名追加进检索词 | 别名/异写不归一 ⇒ "工行"查不到"中国工商银行"的主体 | `query_normalization.py:31` |
| 歧义澄清（W2） | `NEUROVA_KB_AMBIGUITY_CLARIFY` **默认 off**；on 时同名多口径主体弹澄清 | 同名主体（"张三"两人）不澄清 ⇒ 检索混合两人的事实 | `ambiguity_clarification.py:31` |
| 脱靶登记（D-04） | `NEUROVA_KB_MISS_CAPTURE` **默认 off**；on 时 0 命中落候选 | 检索不到时无反馈环 ⇒ 用户反复问同 miss 的词，永远命不中 | `knowledge_retriever_adapter.py:33` |
| 本体感知查询扩展 | **不存在**：用户说"高风险订单"，检索词就是"高风险订单"四字，不会扩展为 `HighRiskOrder` 的实例集或 `hasRiskLevel=High` 的三元组 | 本体语义对检索词零影响 ⇒ 类型层级/关系特征/推导只影响写入，不影响读取 | 全仓无 query expansion 代码 |

**结论**：检索入口是纯文本相似度驱动，本体词表（别名/层级/关系）没有参与查询侧。

### §1.2 检索执行 → 结果排序（精确度 ★★★☆☆）

| 环节 | 现状 | 精准度影响 | 证据 |
|---|---|---|---|
| 四路 RRF | tfidf + BM25 + FTS5 + 向量，k=60 | 文本相似度融合，无语义加权——"高风险"与"风险"的 BM25 分数差异大于语义差异 | `hybrid.py:52` |
| 图谱路 | 已转正（weight 0.10），`graph_walk` 从查询词起步走 BFS | 图谱贡献仅 10% 权重，且 walk 的锚点靠文本匹配不靠本体类型 | `hybrid.py:164-169`；`graph_walk.py:115` |
| 多源融合 | `NEUROVA_RETRIEVAL_FUSION` **默认关**；on 时 memory/knowledge/TKG/graph 四源 RRF 聚合 | 多源不融合 ⇒ 知识命中可能被记忆命中淹没（或反之），没有统一排名 | `retrieval_fusion.py:1` |
| 采纳先验 | `rerankByAdoption`：success 升 / failure 降 | 用户反馈历史参与重排 ✓ | `feedback_prior.py` |
| 推导事实 | `filterConditionClassFacts` **观察态**（D-06 off）——推导事实不进检索主路 | "甲 is_a HighRiskOrder"（推导）被过滤 ⇒ 问"哪些是高风险"时这条不在结果里 | `derivation_citation.py:37` |
| FactSurface | `FactSurfaceConfig.fromEnv().enabled` **默认 False** | 事实不作为检索条目出去 ⇒ facts 面完全不参与 chat 检索 | `read_surface.py:29` |

**结论**：四路 RRF 是纯文本融合，本体语义（类型层级/关系特征/推导结论）对排序权重为零；多条默认关开关把事实面/推导面/多源融合全部挡在主路外。

### §1.3 检索结果 → LLM 上下文注入（精确度 ★★☆☆☆）

| 环节 | 现状 | 精准度影响 | 证据 |
|---|---|---|---|
| 载荷形状 | `_normalize_item` 输出 `{memory_id, content, title, category, tags, source, confidence, ...}` | 纯扁平文本条目——**没有类型标签、没有关系上下文、没有推导标注到 LLM 可读文本** | `knowledge_retriever_adapter.py:507-538` |
| derivation 标注 | `annotateDerivations` 给每条 hit 挂 `derivation: {derived, ruleId, premiseCount}` | 标注存在于 payload 字典，但 **injector 不消费它**——LLM 看到的只是 content 文本，不知道哪条是推出来的 | `derivation_citation.py`；`injector.py` 零 derivation 命中 |
| 上下文组装 | `ctx.relevant_memories` → `ContextOrchestrator` → 注入 prompt | 记忆/知识/经验按分数混排，**没有按本体类型分层的结构化注入**（比如"以下是 Order 类型的实例事实"） | `chat_pipeline.py:2104` |
| 多跳遍历 | 检索只做一跳（查询词→直接匹配的事实/条目），**不做沿关系的多跳遍历** | "与高风险订单关联的客户投诉"需要 Order→Customer→Complaint 两跳，现有检索找不到 | 全仓无 multi-hop retrieval |
| 解释链 | `GET /ontology/derivations/{fact_id}` 端点在册，但 **不注入 LLM 上下文** | LLM 不知道"这条结论由规则 R 从前提 P 推出" ⇒ 无法在回答中引用推理依据 | `knowledge_ontology.py` 端点；injector 零命中 |

**结论**：LLM 收到的是"一堆文本段"，不是"按本体结构组织的知识"。推导标注/类型层级/关系上下文在 payload 里存在但 injector 不消费——**数据在管道里，语义在门外**。

### §1.4 端到端场景推演

用户问："找出最近一个月的高风险订单，并查看对应客户出现的投诉。"

| 步骤 | 理想路径 | 现实路径 | 断点 |
|---|---|---|---|
| 1. 理解"高风险订单" | 查条件类 `HighRiskOrder` → 自动归入的实例 | 文本匹配"高风险订单"→ 命中 `HighRiskOrder` 术语行 → 但 **不展开实例** | ①无 query expansion |
| 2. 找出近一个月 | 读 `valid_from >= 一个月前` | asOf 查询在 facts 层，但 **chat 检索不走 bitemporal** | ②bitemporal 不在 chat 面 |
| 3. 关联客户 | 沿 `has_customer` 关系跳到 Customer | **无多跳遍历** | ③无 multi-hop |
| 4. 找投诉 | 沿 `has_complaint` 跳到 Complaint | 同上 | ③ |
| 5. 注入 LLM | 按类型分层：Order 事实 + Customer 事实 + Complaint 事实 + 关系路径 + 推导依据 | **扁平文本列表**，LLM 自己猜哪些是订单哪些是客户 | ④无结构化注入 |

**四个断点 = 精准度损失的四个来源。**

---

## §2 改进策略（按投入产出比排序）

### 策略 A：开闸已有能力（改动最小，收益立现）

已有机制只是默认关——翻开关不需要新代码，需要 A/B 实测确认无回退。

| # | 动作 | 影响 | 风险 | 判据 |
|---|---|---|---|---|
| A1 | `NEUROVA_CONDITION_CLASSES_ROUTE=1`（D-06 翻主路） | 条件类推导实例（如 HighRiskOrder）进检索 → 用户问"高风险订单"能直接命中 | 误归入推导污染检索 | L9 CQ 通过率不降＋NDCG A/B |
| A2 | `NEUROVA_KB_QUERY_NORMALIZE=on`（W1 开） | 别名/异写归一进检索词 ⇒ 别名命中 | 覆盖率不足时误归一 | shadow 读数→A/B |
| A3 | `NEUROVA_KB_AMBIGUITY_CLARIFY=shadow→on`（W2 分阶段） | 同名多口径主动弹澄清 | 打断用户流 | shadow 读数 |
| A4 | `NEUROVA_KB_MISS_CAPTURE=on`（D-04 开） | 0 命中落候选审批 ⇒ 持续补别名 | 候选面噪声 | 审批量监控 |
| A5 | `NEUROVA_RETRIEVAL_FUSION=rrf`（D-19 开） | memory/knowledge/TKG/graph 统一排名 | 跨源分数可比性 | NDCG A/B |

**优先级**：A1 > A2 > A5 > A4 > A3（A1 直接命中"高风险订单"场景；A2 消别名鸿沟）。

### 策略 B：本体感知查询扩展（新增，中等投入）

**核心思想**：在 `knowledge_retriever_adapter.retrieve()` 入口，用本体词表对查询词做语义扩展——不是全文匹配，是**经过注册表和推导事实的结构化展开**。

| # | 机制 | 实现 |
|---|---|---|
| B1 | **别名→规范名归一**：查询词命中关系/概念的 `aliases_json` → 替换为 term_id / canonical_label | 调 `resolveRelationAlias()`（B8 已有）扩展到 concept 术语 |
| B2 | **子类展开**：查询词命中 concept 术语 → 沿 `parent_term_id` 向下收集子类实例（`subjectKeysOfType`） | `registry.subjectKeysOfType(agentId, [termId])` 已有 |
| B3 | **条件类实例注入**：查询词命中条件类 → 从推导账本取归入的 fact_id 集 → 直接作为检索种子 | 条件类路由 A1 开启后自然生效 |
| B4 | **关系邻域注入**：查询词命中 relation 术语 → 取该谓词下的 top-N fact_id 作为扩展检索种子 | `activeFactsForPredicate` 已有 |

**落点**：`neurova/knowledge/ontology_query_expander.py`（新模块，纯函数）；`knowledge_retriever_adapter.retrieve()` 在 `hybrid_search_knowledge` 之前调用，扩展词追加进 `searchQuery`（与 W1 归一同一通道）。

**判据**：用 CQ-01 场景——"高风险订单"→ 扩展出 HighRiskOrder 实例 → BM25 命中率显著高于纯文本。

### 策略 C：多跳关系遍历（新增，中等偏高投入）

**核心思想**：用户问"与高风险订单关联的客户投诉"——这是一个**关系路径**问题，不是文本匹配问题。现有检索做不到。

| # | 机制 | 实现 |
|---|---|---|
| C1 | **检索后遍历**：hybrid 检索返回种子实体 → 沿注册表关系走 1–2 跳 → 补充邻域事实进结果 | `graph_walk.walkFromQuery` 已有骨架，扩为"从检索结果实体出发走关系" |
| C2 | **类型感知路径**：遍历时按 ontology_terms 的 domain/range 约束剪枝——has_customer 的 range 是 Customer，只沿该方向走 | `domainOf/rangeOf`（B8 继承链已有） |
| C3 | **路径标注**：走出的每条补充事实带 `hop_path: [{predicate, direction}]` 让 LLM 知道是怎么跳过来的 | 新字段 |
| C4 | **可控深度**：默认 1 跳，env 可配 2；不贪深——深遍历成本指数增长且引入噪声 | config |

**落点**：`graph_bridge.py` 或新模块 `ontology_path_traversal.py`；在 `knowledge_retriever_adapter` 的 `_enrich` 之后、`rerankByAdoption` 之前插入。

### 策略 D：结构化上下文注入（新增，中等投入，LLM 侧收益最大）

**核心思想**：不改检索逻辑，改**给 LLM 看的形态**——把扁平文本列表重组为按本体类型分层的结构化上下文。

| # | 机制 | 实现 |
|---|---|---|
| D1 | **类型分层注入**：检索结果的每条 hit 已有 `category`（本体类型）→ 按类型分组 → prompt 里以标题分区（"## 订单事实\n…"、"## 客户事实\n…"） | `injector.py` 或新模块 `ontology_context_builder.py` |
| D2 | **推导标注可见**：`derivation.derived=True` 的条目在 prompt 中前缀 `[推导:规则 R]`——LLM 能说"这是系统推导的"而不是当成用户输入的事实 | derivation 字段已存在，injector 消费 |
| D3 | **类型层级上下文**：注入当前查询涉及的类型子树（"HighRiskOrder ⊑ Order"）——LLM 能理解类型包含关系 | `registry.terms()` + `isSubtypeOf` |
| D4 | **解释链可引用**：premiseCount > 0 的条目，在注入文本末尾附 `(由规则 {ruleId} 从 {premiseCount} 条前提推出)` | `premisesOf` 已有 |
| D5 | **qualifier 透传**：qualifier 里的业务限定（如 `channel: web`）以键值对形式注入——LLM 能引用"渠道为 web 的订单" | qualifier 字段已存在 |

**落点**：`neurova/context/ontology_context_builder.py`（新模块）；`injector.py` 或 `chat_pipeline.py` 在 `_step_evocate_injection` 之后调用。

**这是 LLM 侧收益最大的一招**——不改检索，改给 LLM 看的东西，模型能直接利用结构化信号。

### 策略 E：检索反馈环（长期）

| # | 机制 | 说明 |
|---|---|---|
| E1 | 采纳→先验 | 已有（rerankByAdoption）✓ |
| E2 | 纠正→别名候选 | 用户纠正答案中的实体名 → 落 alias candidate → 审批后下次命中 |
| E3 | 纠正→新关系候选 | 用户指出"甲和乙是竞争关系"但 `competes_with` 未登记 → 落候选 → 审批 |
| E4 | NDCG A/B 门 | ontology 变更前后跑 benchmark，NDCG 下降即红（B13 框架已落） |

E2/E3 是新能力，需要对话面→候选表的通道；E4 的框架 B13 已落，只差接入。

---

## §3 实施路线（分三批，每批独立可验证）

| 批次 | 内容 | 前置 | 红灯判据 |
|---|---|---|---|
| **第一批**：开闸＋结构化注入 | 策略 A 全量（A1–A5 逐项 A/B）＋策略 D 全量（D1–D5） | 无——已有代码翻开关＋新 injector 消费模块 | A/B 前后 CQ 通过率＋NDCG；D2/D4 的 prompt 快照测试 |
| **第二批**：查询扩展 | 策略 B 全量（B1–B4） | A2 开（归一先通） | CQ-01 场景：扩展后 BM25 命中率 > 纯文本 |
| **第三批**：多跳遍历 | 策略 C 全量（C1–C4） | B8 关系特征已在册 | CQ "关联客户投诉"场景：两跳后命中投诉事实 |
| **长期** | 策略 E（E2/E3） | 用户反馈通道 | 反馈→候选→审批→命中的闭环端到端 |

---

## §4 不做什么（边界声明）

| 项 | 理由 |
|---|---|
| 把本体嵌入向量库（term embedding） | 本体术语量小（<1000），别名+层级已够归一；向量化引入第四路检索的成本大于收益 |
| SPARQL 查询引擎 | 评测报告不采纳（零依赖决策）；策略 C 的关系遍历覆盖主用途 |
| LLM 自主规划多跳路径（ReAct 式） | 需要工具调用循环，当前管线不支持；策略 C 的确定性遍历更可靠且成本可控 |
| 重开 011 两池交织 | 已否证（recall@5 0.8555→0.7604） |
| 全量 prompt 重写 | 只在本体知识命中时追加结构化段，不动非知识回合的 prompt 形态 |

---

## §5 与已有工作的关系

| 已有机制 | 在本方案中的角色 |
|---|---|
| B8 关系特征（transitive/inverse/subproperty） | 策略 C 遍历时按特征剪枝/扩展——inverse 关系反向可达，transitive 关系闭包可达 |
| B9 upper-lite（Entity/Agent/Event…） | 策略 D1 类型分层时按 upper 树归类 |
| B1 条件类 | 策略 A1 翻主路后，B3 条件类实例注入成为检索种子 |
| B11 双时态 | asOf/knownAt 已在 facts 层，策略 D1 注入时标注时间轴 |
| B4 溯源标注 | 策略 D2/D4 消费——推导事实在 LLM prompt 中可见且可溯 |
| D-06 默认关 | 策略 A1 的对象——翻转须 L9 A-B 读数确认 |
| 011 否证 | 策略 C 的遍历**不是**两池交织——遍历走的是关系图不是检索池，且是检索后的补充不是替代 |
