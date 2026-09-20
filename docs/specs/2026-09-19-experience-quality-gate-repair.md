# 经验知识形成质量门控修复 · 规格说明书

- 日期：2026-09-19
- 上游审计：[`2026-09-19-experience-quality-gate-audit.md`](./2026-09-19-experience-quality-gate-audit.md)
  （本文所有行号与实测数字沿用该文档 §1-§3，可重跑复核）
- 范围：经验/模式/知识的**形成 → 使用 → 度量**三面质量门控可证伪化
- 术语沿用 `docs/CONTEXT.md`「RSI 判据术语」：`passed` / `failed` / `unevidenced` /
  `measurement_blind`，以及"无据即不通过"这条既有约束

---

## 1. 问题陈述

经验形成链路的质量判据**没有输入**：

- 全链路唯一的客观质量位 `success` 由 `post_chat_pipeline.py:1612` 的
  `any(tm.get("success", True) …)` 供给，而 `tool_call` 类记录根本没有 `success` 键
  （`agent/loops/base.py:196-204`）⇒ **结构性恒真**。生产库 91 条经验 `success` 全为 1。
- 真实成败在 `closed_loop.py:506-510` 被算出后**没传进** `process_experience`，
  被 `classify_outcome` 的关键词分类覆盖，而后者在无命中时 `return "success"`
  （`experience_feedback.py:164`）。
- 真正决定经验能否入库的是 `pattern_crystallizer.py:210/230` 的字面量 `3` / `0.6`；
  RSI 可调的 `crystallize_min_*` 挂在 `ExperienceFeedback` 上、只被 `get_feedback()`
  报表消费 ⇒ **幻影旋钮**，且 `agent_core.py:390` 还存着 0.7 的冲突值。
- `experience_knowledge_base.py` 全文零条 `UPDATE`，schema 无 `hit_count/last_used_at`，
  `confidence_score`/`execution_time` 生产 0/91 非空，`agent_id` 仅 25/91 非空 ⇒
  **写入后永不被检验**，66 条归属不明的经验对任何 agent 检索都不可见。
- 消费端只有 `limit=3` 与一个布尔 token 重叠门（`experience_knowledge_base.py:436`）；
  三套质量聚合方法与 `crystallized_experience_manager.get_statistics()` 生产零调用方；
  `metrics.py` 七个指标无一涉及经验。⇒ **"质量"没有可测量定义，改进无法验证**。

值得解决的原因：经验会被注入每轮对话的 prompt（`context/orchestrator.py:645-653`）。
一条恒真判据放行的噪声经验，其代价是持续污染后续所有回合，而系统当前既看不见它、
也删不掉它、更不知道它错。

---

## 2. 方案概述

三条原则，按此顺序：

1. **先修判据的输入，再谈阈值。** 客观证据源在仓库里已经存在且可用：
   `tool_result` 记录携带逐工具成败（`loops/base.py:175-180/333-341/359+`），
   `creation_governance.py:144-155` 还有失败粘性票据（`MIN(success)`）。
   本轮把它们接到经验臂上，取代关键词自述。
2. **无证据不得落成通过。** 取不到客观回执时产出 `unevidenced`（三态），
   而不是 `True`；`unevidenced` 条目可入库但必须被标出、被检索侧降权、被度量面看见。
   这保证"质量收紧"不等于"经验量归零"。
3. **形成 → 使用 → 回写 必须成环。** 注入哪几条经验要带身份，回合结束后把客观成败
   回写到条目；否则任何门槛都只是自我声明。

对应三组 PR（§7）：PR-1 信号与门槛、PR-2 证伪回路与度量、PR-3 生命周期与治理面。

---

## 3. 用户故事

编号即工单候选（`S01…S16`）。每条都可独立验证。

### PR-1 信号与门槛

- **S01** 作为运维，我要"一轮里任一工具结果失败 ⇒ 这轮的经验不得记为成功"，
  以便 `success` 位开始携带信息。
  验收：构造含 1 条 `tool_result(success=False)` 的轮次 ⇒ 落库 `success=0`；
  无工具轮 ⇒ 写入方收到 `None`（无证据）而非 `True`。
  命中点必须一次改全（同根因）：`post_chat_pipeline.py:1612`、
  `:3055`（规则臂字面量 `success: True`）、`pattern_crystallizer.py:308`（见 S04）。
- **S02** 作为维护者，我要真实成败贯通到经验语义，不再被关键词覆盖。
  验收：`process_experience` 新增 `outcome: Optional[str] = None` 参数；
  显式传入时以其为准，`classify_outcome` 只在 `outcome is None` 时作为兜底参与细分；
  `closed_loop.py:507` 必须把 `success` 传下去。断言"传 success=False 而文本含成功关键词"
  ⇒ 关联计数落 `failure_count`。
- **S03** 作为调参者，我要调 `crystallize_min_observations` / `crystallize_min_success_rate`
  能真的改变入库闸，以便 RSI 的调参有语义。
  验收：把 observations 调到 5 ⇒ 4 次观察不结晶（当前必绿在假处）；
  门槛值唯一来源落在参数事实源一侧（ADR 0016 四角色口径），
  `agent_core.py:390` 的 0.7 冲突消除，并由 `test_parameter_source_of_truth.py`
  同族守卫钉住（该守卫只查登记表完整性，需扩一条"字面量门槛不得旁路登记表"）。
- **S04** 作为审计者，我要求结晶成功这一动作不得冒充"任务成功"的票。
  验收：`pattern_crystallizer.py:305-311` 的 `record_experience(..., True, ...)` 改为
  独立事件类型（不进入 `success_rate` 分子），或显式 `outcome=None`；
  断言"结晶 N 次不得抬高任何关联的 success_rate"（防自喂递归的另一形态）。
- **S05** 作为运维，我要 LLM 裁决闸在 judge 缺席时**不得直写**，且缺席本身可见。
  验收：`pattern_crystallizer.py:264-271` 走"留队 + 计数告警"分支；
  `_prune_expired_pending`（`:332-341`）的"超龄自动放行"改为超龄即降置信/丢弃并计数，
  不得绕过裁决入库；时间戳解析失败（`:329-330` 返回 `0.0`）必须落
  `unevidenced`，既不过期也不静默滞留。默认取舍见 D3。

### PR-2 证伪回路与度量

- **S06** 作为系统，我要 `experience_records` 能承载事后证据。
  验收：新增 `hit_count` / `last_used_at` / `adopted_outcome`（命名按 Neurova 风格定稿于工单）
  与幂等 `_migrate_schema()`（`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`），
  91 行量级不需要外部迁移设施；旧行新列为 `NULL`（≠"从未被采纳"，读侧须区分）。
- **S07** 作为系统，我要知道本轮注入了**哪几条**经验。
  验收：`ctx.experience_items` / `ctx.crystallized_patterns` 携带条目身份
  （EKB id / PATTERN 节点 id），并在轮次上下文里可取；
  当前 `chat_pipeline.py:1756`、`:2626` 只带内容与条数，无法回写。
- **S08** 作为运维，我要"采纳后失败"能降低该条经验的可信度。
  验收：回合结束按 S07 的身份集回写（唯一 `UPDATE` 通路），
  并让 `retrieve` 侧的质量列真的参与：`experience_knowledge_base.py:436` 的布尔门改为
  最低分数阈值 + 采纳后证据降权；失败证据条目与成功条目不得同权重注入
  （`chat_pipeline.py:1839-1846`、`context/orchestrator.py:645-653`）。
  存储侧的访问计数**已有能力但没接**：`UnifiedMemoryNode.access_count` 与 `touch()`
  （`cognitive_storage_engine.py:68/71-75`，`store()` 已持久化该列）只被记忆检索路径调用
  （`manager.py:1015/1163/1652`），经验检索路径 `retrieve()`（`:442`）从不调用
  ⇒ 结晶经验被检索不计数。S08 在 `retrieve()` 上补 `touch()` + 落盘，而非新造方法。
- **S09** 作为运维，我要经验质量是可告警的指标，而不是"没人知道"。
  验收：`rsi/metrics.py` 增经验族指标（形成条数、unevidenced 占比、命中率、
  平均采纳后成功率），接进 `check_alerts()` 与 `dashboard.py`；
  对已存在但零调用方的聚合面做**二选一裁决**：接线（`get_statistics()`、
  `get_skill_ranking`、`evaluate_skill_effectiveness`、`recommend_best_practices`）
  或按工单 017 式净删除 —— 不留假观测面。
- **S10** 作为调参者，我要 RSI 的 `crystallize_min_*` 调参有收敛语义。
  验收（D4 采纳后）：经验质量指标进入 RSI 阶段晋升判据面，无读数即 `unevidenced`，
  沿用 `deployment_controller._REQUIRED_EVIDENCE` 的"按阶段声明必需性"形态。
- **S16** 作为负责人，我要能回答"这套门槛真的让经验变好了吗"。
  验收：确定性经验质量基准 —— 真实 agent 经验语料（非 `eval_harness.py:255-265`
  当场合成的 `f"使用 {tool} 成功完成"`）+ 有/无结晶经验的 A/B 对照 +
  `scripts/ci/` 一条经验门禁（与 osv/perf/deploy-config 同形，进 `protected_tests.txt`）。
  依赖 S09（要度量为先）。

### PR-3 生命周期与治理面

- **S11** 作为审计者，我要求三条主经验臂都吃客观票据。
  验收：结晶器 / `ExperienceFeedback` / EKB 复用 `creation_governance` 的逐工具成败票据；
  无票据来源的经验条目必须标 `unevidenced` 并可证伪地入库（伪造一轮自述成功但无票据 ⇒ 判无据）。
- **S12** 作为运维，我要求记忆写入有内容门且类型不丢。
  验收：`memory_layer/manager.py:701-884` 加归一化去重键
  （同一句"你好"不得存 7 条）；`workflow_experience` 进 `MemoryType` 枚举
  （现在 `post_chat_pipeline.py:2908` 传的值不在枚举，被 `manager.py:753-754` 静默降级成
  `SEMANTIC`）；冲突检测（`post_chat_pipeline.py:2217-2248`）要么前移到写入时并可否决，
  要么显式降级为纯观测并在 StepResult 里写明"不阻断" —— 不得维持"检测了但永远不拦"。
- **S13** 作为维护者，我要遗传臂的 seed 用真实成功率。
  验收：`FrequentPattern` 带 `success_rate` 并被 `post_chat_pipeline.py:2003-2015` 消费，
  取代 `getattr(..., None) or 0.5`；注册可达性判据改为可断言
  （当前 `fitness = 0.5 + log1p(reuse)*0.1` 需 reuse≈20 才跨过 0.8，
  且 base 恒为错的 0.5）。
- **S14** 作为运维，我要求 `min_confidence` 是闸而不是提示。
  验收：`nl_synthesizer.py:250-258` 低置信时不得 `success=True` + `COMPLETED`；
  调用方 `chat_pipeline.py:1088-1090` 的判据同步收紧。
- **S15** 作为运营，我要能在界面上处置低质经验。
  验收：`NEUROVA_CRYSTALLIZATION_LLM_GATE`（`pattern_crystallizer.py:109`）与
  `NEUROVA_SKILL_AUTO_RETIRE`（`skill_experience.py:549`）收进 `governance_settings`
  （与 `metacog_gate_enabled` 同口径，优先级 env 显式 > 治理设置 > 默认）；
  EKB 接上技能侧已有的审批机制（`skill_pool_api.py:690/701`），
  前端 `ExperienceKnowledgePage.vue:155-171` 目前只有"查看相似 + 删除"，
  补审核/降权；修掉 `experience_count` 恒为 1 的展示假象
  （`experience_knowledge_api.py:104` 硬编码常量）。

- **S17**（PR-3）作为运维，我要"通过门控的经验"不等于"永久固化的经验"。
  验收：`pattern_crystallizer.py:287` 把成功率写成温度（`rate*100`），而
  `memory_layer/temperature.py:291-297` 对 `>=80` 一律不衰减 ⇒ 一条被判"质量好"的经验
  从此**永不衰减、无任何淘汰路径**（`MemoryType.PATTERN` 全仓仅 2 处引用，无 decay/prune 分支）。
  判据：构造 `success_rate=1.0` 的结晶经验 ⇒ 在时间推进或采纳后证据转差时必须可降权/淘汰；
  豁免只可作用于"人工升格"或"多次采纳成功"，不得作用于单次自述成功率。

## 4. 已定决策

D1-D4 对应审计 §7 的四个待裁决点，**本轮按下列取向定稿；翻案成本写在每条后面**。

- **D1（原 §7.1）不做"砍量换质"，做"标证据"。**
  收紧判据后入库量必然断崖（当前 100% 通过）。取向：无客观回执的条目**照常入库但标
  `unevidenced`**，由检索侧降权、由度量侧计数。
  翻案成本：若改为直接拒写，S06/S08 的列语义与 S09 的指标定义都要重写。
- **D2（原 §7.2）schema 迁移本域自持。**
  91 行量级用幂等 `_migrate_schema()`（`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`）即可，
  不依赖并发工作流的零停机迁移设施（避免跨工作流耦合）。
  翻案成本：低；改挂迁移框架只是 S06 的实现替换。
- **D3（原 §7.3）judge 缺席 ⇒ 留队 + 告警，不直写。**
  现语义"`_llm_judge is None` ⇒ 直写"（`pattern_crystallizer.py:264-271`，注释称"零 LLM 语义"）
  实际是"没有 LLM 就没有闸"。取向：judge 缺席时候选留队并计数告警，
  队列上限与超龄策略由 S05 定（超龄**不得**转为放行）。
  代价与翻案路径：零 LLM 部署下结晶臂停摆 —— 若不可接受，回退方案是
  "直写但落 `unevidenced`"（与 D1 一致，仍不绕过证据标注）。
- **D4（原 §7.4）经验质量进入 RSI 判据面，但排在度量之后。**
  先有指标（S09）再进 `_REQUIRED_EVIDENCE`（S10），避免再造一条读空值的幻影守卫。
- **D5 判据口径统一为三态。** 本轮新增的一切判据（含检索门、审批面展示）
  必须能区分 `passed` / `failed` / `unevidenced`，复用 `gate_verdict.GateVerdict`，
  不发明第二套三态表达。

---

## 5. 测试决策

**主接缝（从上往下选，尽量只跨一个）**

1. **最高接缝：一次真实轮次 ⇒ 落库条目** —— 经 `PostChatPipeline._step_record_experience`
   的生产构造点驱动，断言 `experience_records` 行的 `success` / 证据标注 /
   `agent_id` 归属。S01、S04、S11、S12 全部走这条。
2. **结晶器接缝** —— `PatternCrystallizer.observe(...) → engine.store(...)` 的次数与内容，
   经 `agent_core.py:1506` 的真实构造点装配（含 `crystallizer` 与参数事实源的接线）。
   S03、S05 走这条。
3. **检索→注入接缝** —— `find_similar_experiences` 与
   `context/orchestrator.build_context` 的入参出参（S08 的门与排序）。
4. **回写接缝** —— 一个回合从 S07 的身份集到 S08 的 `UPDATE` 结果（端到端可断言）。
5. **度量接缝** —— `metrics.check_alerts()` 与 dashboard 视图（S09），
   以及基准脚本 exit code（S16）。

**禁止的测试写法**（这几条就是本轮缺陷得以藏身的形态，写进工单纪律）

- 不许用 `MagicMock` 冒充闭环系统/工具消息来验证成败判定 ——
  `MagicMock().get("success", True)` 恒真，正是 G1 藏身 3 个月的原因。
  工具消息必须用 `loops/base.py` 的真实记录字典形态（`type`/`tool_name`/`success`/`timestamp`）。
- 不许在测试里手工传阈值参数来绕过生产装配点（对照反思链B 的教训：
  绿灯覆盖契约却漏掉布线）。S03 的断言必须证明**从参数事实源改起**才生效。
- 不许断言 `outcome in {"success","failure","partial"}` 这类恒真域
  （`test_experience_feedback.py:57,66,75` 现状），必须断言具体分类与其证据来源。
- 不许用"库里能查到一行"代替"质量判据咬合"：每条验收都要给一个**会让判据变红的反例**。

**"完成"的定义**：S01-S09 全绿 + S16 的基准在改动前后给出可比较的质量读数
（而不是"看起来更严了"）。`agent_core.py` 尺寸棘轮（2159 行，净增即红）继续有效：
新增装配逻辑落在独立模块，不写进 `agent_core.py`。

---

## 6. 明确不做

- 不追溯判定历史 91 行的真实成败（证据已丢）。旧行按"新列为 NULL"处理，
  由 S08 的检索降权自然沉底；不做数据伪造回填。
- 不新增常开的 LLM 消耗面（S05/S11 的裁决沿用现有"仅在有候选时一次批量调用"的低频形态）。
- 不动反思链（`growth_log` / V3 教训）—— 已由
  `2026-09-19-reflection-feedback-loop-audit.md` 覆盖，本轮只在 S16 的基准里把它当外部信号。
- 不重构 RSI 参数事实源（ADR 0016 已定），S03 只做"结晶真门槛归入登记表"这一处收口。
- 不在本轮做 CRDT / 协作域的经验共享。
- 不引入向量检索或语义相似度模型来升级 S08 的相关性门（先用现有分数与证据位，
  避免把"质量"与"召回"混成一次改动）。

---

## 7. PR 边界与依赖

工单已切出：[`2026-09-19-experience-quality-gate/tickets/`](./2026-09-19-experience-quality-gate/tickets/000-索引.md)
（001-017，与下表 S 编号的映射见该索引的 S→T 追溯表）。

| PR | 工单（spec 故事） | 阻断关系 | 完成判据（一句话） |
|---|---|---|---|
| PR-1 信号与门槛 | 001(S-基座) 002(S01) 003(S02) 004(S03) 005(S04+S05) 011(S12①) 012(S12②) 014(S14) | 001 为唯一前置，其余只卡 001 可并行 | `success` 首次出现 0 与无证据；结晶闸可调 |
| PR-2 证伪回路与度量 | 006(S06+S07+回写) 007(S08) 008(S09) 009(S16) 010(S11) 013(S13) 017(S17) | 主干 002→006→{007,008}→009；010 卡 002+003+004 | 存在一条 `UPDATE` 通路、一个可比质量读数、一条 CI 门禁 |
| PR-3 治理与运营面 | 015(S15) 016(S10) | 015 卡 007+008；016 卡 008+009 | 开关进治理设置、运营可降权、质量读数进晋升判据 |


**先决提示**：PR-2 未落地前，PR-1 的门槛收紧在观测上不可证伪（看不到"变好了"）。
因此建议按 PR-1 → PR-2 顺序合，但 PR-2 的 S16 基准必须在两者都落地后才作为门禁启用，
以免基准自身成为噪声源。

---

## 8. 补充说明

- 本轮与 RSI 批次（工单 003-008）是**同一类病的不同器官**：
  `get("roi", 0.0)` ≙ `get("success", True)`；幻影守卫 ≙ 幻影门槛；
  度量失明被读成收敛 ≙ 检索成功率被当经验质量。
  审计 §5 给了逐条对照表，修复时可直接复用 `GateVerdict` 与"必需性按阶段声明"的形态。
- 唯一现成的真门对照组是 `creation_governance.py:144-155/182-183/209-215`
  （逐工具票据 + 失败粘性 + ≥3 独立任务成功）。S11 是"把三条臂接到它上面"，
  不是"再造一套判据"。
- 复核命令见审计文档 §8；S01 落地后重跑同一组命令，
  `success` 分布应首次出现非全 1（这是本 spec 的最低有效性证据）。
- 并发工作流提醒：`data/experience_knowledge.db` 属生产运行数据，
  本轮只允许只读查询复核；写入验证一律走临时库
  （`NEUROVA_EKB_DB` 环境变量覆盖，见 `experience_knowledge_base.py:46`）。
