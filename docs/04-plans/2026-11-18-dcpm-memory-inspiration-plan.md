# DCPM 启发落地清单（记忆与睡眠体系进化方案）

- 日期：2026-11-18
- 依据：
  - 论文：*Memory Beyond Recall: A Dual-Process Cognitive Memory System for Self-Evolving LLM Agents*（DCPM，arXiv:2606.09483，腾讯，2026-06-08）
  - 本仓对照分析（2026-11-18 会话内完成，结论要点见 §1.2；高阶认知模块接线审计见 §1.3）
- 性质：**启发与改进方向清单，待拍板后逐项立项**。本文档只细化"论文带给本仓什么"，不重复完整对照评分。
- 执行者须知：文中所有 `file:line` 以 2026-11-18 工作树现场读数为锚，**行号会漂移，符号名是锚**——开工任何一项前先对目标文件做撞车复核（`git log --oneline -5 -- <file>` + `git status`）。每项先红后绿、live-verify 自证、净新增 LOC 尽量为负或逐条列明去向；同一事实源不建第二份。

---

## 0. 总原则

1. **不推翻现有体系，只补"认知型夜间引擎"这一层。** 本仓睡眠的"维护型"半边（阶段链/去重/衰减/晋升/隔离分桶）经对照确认已超越 DCPM，全部保留；要补的是 DCPM System2 的"归纳"半边。
2. **所有 LLM 归纳一律默认关。** 沿用本仓治理闸先例（`crystallization_llm_gate_enabled`、`conversation_rules_enabled`、`NEUROVA_MEMORY_DISCIPLINE`）：新归纳相位挂治理设置 + env 强制开关，关闭态行为与现状逐字节一致。
3. **归纳产物必须带证据回指。** DCPM 每个图节点带 `evidence_vdb_ref` 边回指支撑事实；本仓任何 schema/规则/意图产物一律携带来源 memory_id 列表，可溯源、可硬删（呼应 DCPM 伦理节的级联硬删除要求）。
4. **读路径保持零 LLM。** 本仓 recall（向量 0.7 + 关键词 0.3 RRF + 联想线索第三路 + MoE 路由）已是零 LLM，新增产物只准"加分/浮出"，不准在召回关键路径上引入模型调用。
5. **先还债再扩建。** T4（断链清偿）是 T2/T3 的地基：归纳产物要有统一读面，先把三套互不相通的 DependencyGraph 与空转的 NeuHebb 收口，否则新产物又添一套孤儿结构。

### 批次总览与依赖

```
T4 断链清偿（地基：图单源/NeuHebb 二选一/死码拍板）
T1 supersedes 链读路径化（最独立，可先行）
T2 睡眠归纳相位（依赖 T4 的图单源；LLM 闸默认关）
T3 跨域碰撞 sweeper（依赖 T2 的 schema 产物；同窗口低频）
T5 identity 层（依赖 T2 归纳器的产出通道；借 S16 候选转正）
T6 intention 层（差异化，与 question_queue 合流；最后做）
```

- T1 与 T4 互不碰文件域，**可并行**；T2→T3 **串行**（同一睡眠窗口内先归纳后扫碰撞）；T5/T6 依赖 T2 的归纳器成型。
- 每项独立可交付、可红绿验证、可单独提交。

---

## T1 · supersedes 链读路径化

**论文依据**：DCPM 用 `Supersedes/SupersededBy` 双向指针记录信念修订，**不删前驱**；读时一次命中沿链 O(k) 遍历即可恢复完整演化弧线。其实测：LongMemEval 知识更新子集上，答对查询 78% 触碰过 supersedes 指针（答错仅 31%）；消融中该链贡献 2.9 分。

**本仓现状（链已存在，只写不读）**：
- S16 世代失效：`memory_discipline.py` `_supersedeContradictions` 把矛盾旧行写 `metadata.memoryDiscipline = {status: "superseded", supersededBy, supersededAt, supersededBasis}` 且 `lifecycle_stage=forgotten`；
- 导入声明取代：`manager.py` `_retireSuperseded` 写 `metadata["superseded_by_ingest"]`；
- pending 确认覆盖：`pending_memory.py` `supersede_same_key` 按同 normalized_key 软遗忘旧行；
- 睡眠合并：`sleep_writeback.py` `_write_back_product` 产物带 `metadata.merged_from`，源行 soft-forget；
- 但 `manager.py` `recall()` 直接排除全部 `FORGOTTEN` 行——链永远沉在审计里，用户问"这个结论以前是什么、为什么变了"无法回答。

**差距本质**：DCPM 的修订是"记录"，本仓的修订是"收缩"。字段齐全，缺一个读面出口。

**方案**：
1. 新增**统一的链读取函数**（单源，建议落 `memory_layer/`，消费上述四类字段，不另立第四种取代语义）；
2. 暴露只读端点（如 `GET /api/v1/memory/{memory_id}/lineage`），返回演化弧线（旧值/新值/依据/时刻），严格按请求作用域三元组过滤；
3. recall 命中的行可在结果附 `lineage` 摘要（深度上限具名常量，如 5 跳）——**不改变 FORGOTTEN 排除语义**：旧行仍不进召回结果集，只作为 lineage 附带信息按 id 精确读出。

**影响面**：`memory_layer/`（新读取函数）、`api/endpoints/memory/`（端点）、`manager.py` recall 附带面、前端记忆详情页（可选）。

**风险与边界**：lineage 读的是软删行（本就按 id 可 `get_memory`），不新增泄露面，但仍须过隔离三元组与既有鉴权；敏感内容写入时已过准入闸。

**验收判据（红灯方向）**：写入矛盾事实触发 S16 世代失效后，新行 lineage 能读出旧行 id 与 `supersededBasis`；recall 结果集始终不含 FORGOTTEN 行（既有不变量不回退）。

---

## T2 · 睡眠归纳相位（把 System2 装进深睡）

**论文依据**：DCPM System2 三阶段——① 无 LLM 预处理（筛"未被任何上层结构引用"的事实 + 两段 DBSCAN 聚类）；② LLM 归纳 agent 每簇一次，用 `create_schema / create_intention / add_evidence / add_edge` 四工具把簇固化成图节点，图跨夜**增量**演化；③ 跨域碰撞（见 T3）。收益集中在隐式跨会话个性化（PersonaMem-v2 +5.20）。

**本仓现状**：睡眠四阶段链（浅睡→REM→深睡→休眠，`sleep.py` `_PHASE_CAPS` + `idle_tracker.py` `_trigger_consolidation`）只做聚类合并、温度衰减、归档；REM 洞察是从合并统计派生的**模板句**（"N 条同类记忆收敛为 1 条…"），诚实但零新信息。真正做 LLM 归纳的能力散在 post-chat 后台且半数断链（见 T4）。

**差距本质**：本仓睡眠会"打扫房间"（收缩冗余），DCPM 夜间会"做梦复盘"（从事实里长出行为规律）。归纳与睡眠窗口天然契合：空闲、异步、低频、可预算。

**方案**：
1. 在 `_PHASE_CAPS["deep_sleep"]` 与 `"hibernate"` 增加可选 `"induce"` 相位（门控 `NEUROVA_SLEEP_INDUCTION`，默认 off）；
2. 选材：取**未被任何上层结构引用**的事实（无 PATTERN 关联、无联想线索、非 crystallized/consolidated），按隔离三元组分桶（沿用 `consolidate` 的分桶纪律，绝不跨作用域归纳）；
3. 聚类：起步用现有余弦贪心聚类即可（本仓已有 embedding），不必先上 DBSCAN；簇内事实数 < 2 不归纳；
4. 归纳：每簇一次 LLM 调用，产出 schema 节点（名称/规律描述/来源 memory_ids），写入统一图存储（T4 收口后的那份），带 evidence 回指；
5. 消费：schema 节点进检索浮出面——对齐既有"结晶经验"注入通道（`chat_pipeline.py` `_retrieve_crystallized_patterns` → `context/orchestrator.py` 的 `[结晶经验]` 块），只加分不重排。

**影响面**：`sleep.py`（相位扩展）、`idle_tracker.py`（透传）、`memory_layer/`（归纳器与图写入）、`chat_pipeline.py`/`context/orchestrator.py`（浮出）、治理设置面。

**风险与边界**：LLM 成本（默认关 + 每周期簇数上限具名常量）；幻觉 schema 污染检索（产物带 evidence + 检索只加分 + 人工可下架）；归纳失败不阻断整理主流程（fail-soft，与写回同纪律）。

**验收判据**：门控关=整理行为与现状逐字节一致；开+桩 LLM=深睡后产 schema 节点且 evidence 回指可查、跨重启可读；同一簇重复归纳幂等。

**执行记录（2026-11-18，会话内实施）**：
- 落地 `sleep_induction.py`：门控（`NEUROVA_SLEEP_INDUCTION`，默认 off）→ 选材（活跃+有嵌入+未被既有 schema 证据引用，系统面全量后按隔离三元组分桶，温度优先取舍，上限 400）→ 贪心语义聚类（阈值 0.75，真嵌入实测标定：同主题句对 ≈0.84-0.86、无关句 <0.5；区别于去重的 0.98 近等价）→ 每簇一次 LLM（严格 JSON name/pattern）→ schema 实体落统一依赖图（entity_type="schema"，metadata 带 evidence/scope/induced_at，每周期上限 8、同作用域同 pattern 去重、fail-soft 逐簇跳过）。
- 触发接线两条：自动周期（`idle_tracker._trigger_consolidation` 深睡/休眠写回后）与手动深睡会话（`SleepConsolidation.start_sleep` 写回后）；LLM 客户端经 `set_induction_llm_provider` 注入、`buildSyncLlmFn` 桥接成同步调用（睡眠线程无事件循环）。
- 读面：schema 经既有 `/neuron` API（entity_type 过滤）可查；检索浮出随 T3 的行为嵌入匹配一并落地（本批诚实边界：归纳产物已可查、尚未进召回加分面）。
- 验证：红灯 12 用例（门控直通/选材排除/分桶不串域/证据回指/LLM 失败跳过/上限顺延/幂等去重）→ 绿 12/12；A/B 零新增（memory 套件 1179 过仅 2 预存；integration+execution_engine 失败集合与 T4 批逐项相同）；live-verify 隔离真后端 6/6 PASS——门控开+无 LLM 时相位真实运行（日志：候选 3/簇 1/失败 1 如实计数）、诚实不产 schema。
- 坑：真嵌入的同类句对余弦（0.84-0.86）低于拍脑袋阈值 0.86 导致簇恒空——阈值必须经真实嵌入标定；`/sleep/{id}/status` 返回裸 Pydantic 模型（无 data 包络）。
- 净 LOC：生产池 +438/−1（sleep_induction.py +343、idle_tracker +43、sleep.py +42、agent_core +10）；测试 +271 不计入。

---

## T3 · 跨域碰撞 sweeper（core schema）

**论文依据**：DCPM 对每个 schema 生成两份表示——**行为描述嵌入** E_beh（如"沉没成本后加码"）与**语义嵌入** E_sem；当 `cos(E_beh)>θ_beh(0.72)` 且 `cos(E_sem)<θ_sem(0.40)` 判为碰撞（行为像、话题远），union-find 聚合碰撞对后由 LLM 归纳更高层 core schema。消融中贡献 **4.1 分（最大单项）**，而 core schema 仅占节点 1.3%——少量高杠杆结构。

**本仓现状**：PATTERN 节点已有（pattern_crystallizer 产物），但无双空间表示、无跨域扫描、无更高层抽象。

**差距本质**：本仓的归纳停在"单域内同主题收敛"，缺"跨域同行为"的抽象步。

**方案**：
1. 挂在 T2 归纳相位之后（同一异步窗口，低频：每完整睡眠周期至多一次）；
2. 对 PATTERN/规则节点补两份嵌入：行为描述由 LLM 生成（或先由规则模板生成，省一次调用）、语义嵌入复用内容编码（`_embeddingForNewRow` 同源）；
3. 双空间判碰撞（阈值具名常量，初值取论文 0.72/0.40，可在治理设置里调）；union-find 聚合；
4. 碰撞簇交 LLM 归纳 core pattern 节点，连边到全部成员，evidence 回指；进同一浮出面。

**影响面**：同 T2，外加 pattern_crystallizer 产物面。

**风险与边界**：扫描是 O(D²·s̄²)——论文实测 D≤20、s̄≤30 可容忍，本仓 PATTERN 数量级更小；跨域推断**不得**用于高风险自动决策（准入/权限），仅作检索与呈现（DCPM 伦理节红线，直接采纳）。

**验收判据**：构造两个语义远、行为像的 PATTERN → sweeper 判碰撞 → 产 core pattern 且 evidence 含两成员 id；两空间都高的平凡冗余对不被误并。

---

## T4 · 断链清偿（地基，先于 T2/T3）

**性质**：不是新功能，是按修复教义第 5 条（同一根因全命中点扫荡）还债。2026-11-18 接线审计结论如下，逐项拍板**接线或退役**，不许静默遗留：

1. **NeuHebb/Evocate 全链空转**：`agent_core.py` 装配 `NeuHebbManager` 不传 `llm_fn/embed_fn` → forge 走缺省 `_default_llm` 恒返 "I don't know" → 被无效答案拦截 → **生产每轮 0 产物**；embed 缺省零向量 → 检索相似度恒 0。二选一：注入真 client（agent llm_client + 与 `_embeddingForNewRow` 同源编码）救活，或整体退役（含 `chat_pipeline.py` evocate 注入步与 `unified_vector_store.py` 的 `add/search_neurova_hebb*` 死方法）。按教义第 7 条先比后合。
2. **DependencyGraph 三套实例互不相通**：conversation_rule_extractor 用的模块单例（`agent_core.py` `get_dependency_graph()`）、neuron.py 的 `_shared_graph`、neurova_recall 自建实例。收口单源，图谱类产物才有统一读面——这是 T2 schema 落点的前置。
3. **conversation_rule_extractor**：LLM 因果/条件规则归纳，治理闸默认关，且产物入图后无读方。拍板：接读方（recall 按实体查规则边加分）或退役。若接，先做第 2 条。
4. **零散死面**（逐项拍板）：`temporal_reasoner`（生产零调用死码）、`moe_dependency_extractor`（每条记忆都跑但产物即弃——`manager.py` 建提取器不传图，每次新建临时图丢弃）、`version_control`（快照只写不读：rollback/history/compare 无生产调用方）、`meta_cognition`（memory_layer 版；写路径活、读/分析 API 全仓零调用）。

**验收判据**：每项要么给出生产消费链证据（file:line），要么删除干净（含测试与导出面）；A/B 零新增失败。

**执行记录（2026-11-18，会话内实施）**：
- 拍板：NeuHebb **退役删净**；依赖图 **收口单源**；规则提取器 **并入 T2**（代码与默认关闸保留，归纳能力由 T2 夜间相位覆盖）；零散死面四项 **逐项再议**（本批不动码，登记待专项清偿：temporal_reasoner 死码 / moe_dependency_extractor 产物即弃 / version_control 只写不读 / meta_cognition 读面死）。
- T4a 已落地：删除 neuHebb 四模块（manager/forge/curator/neurova_hebb，−914 行）与全部装配/注入/生成步（agent_core、chat_pipeline Step2、post_chat_pipeline 步 9.1、unified_vector_store hebb 索引），清理 20 余处测试引用，新增退役守卫 `tests/unit/memory/test_neuhebb_retired.py`（8 用例钉"不可复活"）。
- T4b 已落地：`neuron.get_shared_graph()` 委托 `get_dependency_graph()` 模块单例、`neurova_recall` NEURON 组件挂同一份图；新增 `tests/unit/memory/test_dependency_graph_single_source.py`（4 用例钉单源与跨面可见）；`test_neuronSharedGraphHandlers` 的打断缝隙随单源迁移（patch `_graph_instance`）。
- 验证：先红后绿（守卫 8 红→绿、单源 4 红→绿）；A/B 精确比对（stash 前后 integration/execution_engine/test_memory + 六个静态守卫：基线 73 项失败/错误 vs 实测 72 项，仅基线多出一条 flaky 项，**零新增失败**）；`test_agent_public_contract` 快照按规程移除 `NEUHEBB_AVAILABLE` 与 `neuHebb_manager` 两项（快照中 chat_stream/spawn_subagent 漂移为并行批次预存失败，不属本批）。
- 净 LOC：生产池 +34/−1149（净 −1115）；测试另计。

---

## T5 · identity 层（用户身份项）

**论文依据**：DCPM 的 identity items 是长期用户属性与持久偏好，设计上稳定（<3% 带修订指针），与 atomic facts 在**同一次抽取调用**中产出，检索时常驻。

**本仓现状**：无身份层。用户长期偏好散在 semantic 记忆里靠召回碰运气；`metadata.sender_type` 只标说话人。

**方案**：metadata 增 `identity` 维度（或独立 `category="identity"`）；打标来源接 T2 归纳器（从事实簇里识别"关于用户是谁/偏好什么"的子簇）或写入侧轻量规则先行；召回对 identity 行加权/常驻（具名常量，只加分）；生命周期直接复用 **S16 候选转正**——跨 ≥3 独立任务复现才转正为持久身份项，与 DCPM"稳定"语义天然契合。

**风险与边界**：身份推断属敏感面——写入过准入闸（已有），推断面在治理设置登记，用户可见可删（对齐 DCPM 分层 opt-in 建议）。

**验收判据**：同一偏好多轮/多任务出现 → identity 行转正 → 检索常驻可见；单次偶发不转正。

---

## T6 · intention 层（主动关怀，差异化不做照抄）

**论文依据**：DCPM 的 latent intentions 是"用户未来可能面对的事件的潜在关切"，与 schema **平级**（sit beside, not above），支撑主动式关怀。

**本仓现状**：`question_queue_manager`（好奇问题队列）已是"对未来事项的主动关心"雏形；growth/evolution 面已有主动行为通道。

**方案**：不照搬 DCPM 的独立 intention 节点层，而是**与本仓 question_queue 合流成单一事实源**：intention 定义为"从记忆里长出来的、值得主动跟进的未决事项"，由 T2 归纳相位或结晶器派生（带 evidence），进问题队列的既有呈现/裁决面，人在环（可见、可关、可删）。

**边界**：无证据不推断、不展示；不做未经用户同意的主动打扰（频控挂既有渠道纪律）。

**验收判据**：归纳产出的 intention 落问题队列且带来源；用户关闭后同源 intention 不再复现。

---

## 附：诚实边界

- DCPM 的 +5.20 是其自身消融在 PersonaMem-v2 上的读数，**不是与本仓的对测**；本仓未跑 LongMemEval/PersonaMem，本文所有"差距"均为结构对照，非分数对照。
- 若需量化，可复用真模型基线批（`docs/08-research/multi_agent_bench_baseline_2026-11-17.md`）的执行方式，在 PersonaMem-v2 上做一次同框复跑；先行条件是 T1/T2 落地。
- 本文为启发清单：每项开工前须按当时代码现场复核行号与接线状态，并按仓库纪律先红后绿、live-verify 自证。
