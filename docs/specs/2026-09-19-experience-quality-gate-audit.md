# 经验知识形成 · 质量门控审计

- 日期：2026-09-19
- 触发：负责人反馈"agent 形成经验的质量并不高"，要求检查经验知识形成的质量门控
- 范围：经验/模式/知识的**形成（写入）— 使用（消费）— 度量（治理）**三面。
  不含反思链（`growth_log` / V3 教训，见 `2026-09-19-reflection-feedback-loop-audit.md`，
  那条链已单独审过，本文只在必要处对照）
- 性质：只读审计。本次不改代码、不出修复结论之外的产物。

---

## 0. 结论

**质量门控不是"太松"，而是它的核心输入信号恒为真、真正生效的那道闸不归门控体系管、
并且写入之后没有任何回路能证伪它。**

生产库实测（`data/experience_knowledge.db`，91 条 `experience_records`，35 个会话）：

| 观测 | 值 | 含义 |
|---|---|---|
| `success` 取值分布 | **91/91 全为 1** | "成败"这个唯一质量位从未携带过信息 |
| `confidence_score` 非空 | **0 / 91** | 质量列被 schema 定义、被展示层读取，生产从不写 |
| `execution_time` 非空 | 0 / 91 | 同上 |
| `agent_id` 非空 | **25 / 91** | 66 条归属不明；检索按 `agent_id` 精确匹配 ⇒ 这 66 条对任何 agent 永不可见 |
| 同一 `context` 重复 | 最高 **7 次**（如"你好"）| 去重只挡"全字段完全相同"，同一句无信息复述反复入库 |

也就是说：经验条目里被当作质量证据的东西，一条都没有区分力。

---

## 1. 五层根因

### L1 `success` 信号结构性恒真（不是"偶尔判错"）

三处叠加，任一处都足以污染，三处串成一条：

1. `neurova/post_chat_pipeline.py:1612`
   ```python
   tool_success = any(tm.get("success", True) for tm in tool_messages) if tool_messages else True
   ```
   - `tool_call` 类记录**没有** `success` 键（`neurova/agent/loops/base.py:196-204` 只写
     `type/tool_name/params/timestamp`）→ `.get(..., True)` 恒 True；
   - `any()` ⇒ N 次调用里 1 次成功即整轮成功；
   - 无工具轮直接 `True`。
   注释自称"P-5: success 基于工具实际成败"，与实现相反。同文件
   `:2115` 已有正确写法：`tm.get("type","") == "tool_result" and tm.get("success", False)`。
2. `neurova/evolution/experience_feedback.py:163-164` —— 关键词一条都没命中时
   `return "success"  # 默认为成功`。判据是对经验文本做关键词计数（`:151-153`）。
3. `neurova/evolution/closed_loop.py:506-510` —— 调用方算好的真实 `success`
   **没有传下去**：
   ```python
   outcome = "success" if success else "failure"
   result = self.experience_feedback.process_experience(experience_text=text, task_type=task)
   ```
   `process_experience` 内部自行 `classify_outcome(text)` 覆盖（`:261`），
   返回值里的 `outcome` 即关键词版。真实成败只用于 `tool_weights` 更新，不进经验语义。

**级联后果**：`success` 恒真 ⇒ 结晶成功率 `rate` 恒接近 1（`pattern_crystallizer.py:226-227`）
⇒ 温度 `rate*100` ≥ 80 时命中"高温不衰减"豁免（`memory_layer/temperature.py:291-297`）
⇒ 通过门控的结晶经验**永不衰减、也无淘汰路径**（`MemoryType.PATTERN` 全仓仅 2 处引用，
无任何 decay/prune 分支按它筛选）。门越好⇒越固化，判据方向反了。

### L2 真正生效的那道闸，不在可调参数面上

| 旋钮 | 值 | 定义处 | 谁实际消费 |
|---|---|---|---|
| `crystallize_min_observations` | 3 | `experience_feedback.py:109`；`agent_core.py:389`；`rsi/system_performance.py:27` | 只进 `get_feedback()` 报表与 RSI 评测 |
| `crystallize_min_success_rate` | **0.6** / **0.7** 冲突 | `experience_feedback.py:110` = 0.6；`agent_core.py:390`（占位替身）= 0.7 | 同上 |
| 结晶实际门槛 | 字面量 `3` / `0.6` | `pattern_crystallizer.py:210`、`:230` | **决定经验是否入库的唯一硬门槛** |

RSI 参数面登记的是 `ExperienceFeedback` 上的属性，结晶器读的是自己的常量 ——
调 `crystallize_min_*` 只改报表数字，改不动入库闸。这与 RSI 批次的"幻影守卫"同型
（工单 006 的 `get("roi", 0.0)`：读点和写点不是同一个东西）。

### L3 写入之后零证伪（门控永不被事后检验）

- `neurova/skills/experience_knowledge_base.py` 全文 **没有一条 `UPDATE`**（实测 grep 零命中）
  ⇒ 一行的 `success/confidence_score/feedback` 自写入那刻起不再改变。
- schema 无 `hit_count` / `last_used_at` / `use_count`（`:136-152`）⇒ 数据层就不支持
  "按热度/新鲜度/有用度"排序。
- 节点模型本身**有**访问计数能力：`UnifiedMemoryNode.access_count`（`cognitive_storage_engine.py:68`）
  与 `touch()`（`:71-75`，同时抬温度并刷新 `updated_at`），且 `store()` 的 INSERT 会持久化
  `access_count` 列。但 `touch()` 的调用方全部在**记忆**检索路径
  （`memory_layer/manager.py:1015/1163/1652`、`neuHebb_curator.py:102`），
  经验检索路径 `cognitive_storage_engine.retrieve()`（`:442`）从不调用它
  ⇒ 结晶经验被检索不计数，`access_count` 停在写入时的 0。
  （此条曾被我误记为"有 `record_access()` 方法未被调用"；全仓 `def record_access`
  只存在于无关的 `core/module_tracker.py:236`。）

- 三套质量聚合逻辑 —— `get_skill_ranking:639`、`evaluate_skill_effectiveness:444`、
  `recommend_best_practices:521` —— **生产零调用方**（API 的 `/ranking` 端点
  `experience_knowledge_api.py:149` 名字像，实际调 `get_experience_records`）。
- 已建好但未接线的观测面：`crystallized_experience_manager.py:408` `get_statistics()` 零调用方；
  且其 `success_rate`（`:416`）分母是**检索调用次数**，不是"采纳后是否更好"。

### L4 消费端不按质量决策，也没有出口把结果传回去

- 唯一消费点在 Step 1：`chat_pipeline.py:1747-1752`（结晶，limit=3）、
  `:1798-1803`（EKB，limit=3）。
- 相关性门是布尔的：`experience_knowledge_base.py:436`
  `if keyword_score > 0 or topic_score > 0` —— 单个 token 重叠即入选；
  `similarity_score` 算出后除排序外无人读，**没有最低分数阈值**。
- 质量在相似度里只占 10%，且是 0/1 位（`:432`）—— 又因 L1 恒为 1，等于 0 区分力。
- 失败经验与成功经验同权重进 prompt（`chat_pipeline.py:1839-1846`，仅加 `✗` 前缀）；
  注入侧无置信阈值（`context/orchestrator.py:645-653` 无条件 `[经验]` 前缀拼接，
  priority 硬编码 70/80，与条目质量无关）。
- 内容侧：写入的是 `context={"user_input": 用户原话}`、`feedback=user_input[:100]`
  （`post_chat_pipeline.py:1644-1650`）—— 把**用户提问**当"反馈"存，
  经验文本里没有工具、没有结果、没有成败证据。

### L5 质量本身没有可测量定义

- `rsi/metrics.py:39-45` 七个指标全为周期/ROI/回滚/候选，**无一条涉及经验**；
  阈值（`:48-52`）也全是 ROI 与门失败。
- RSI 评测集里经验族 2 个用例（`eval_harness.py:320-330`）只验门槛算术，
  语料是当场合成的 `f"使用 {tool} 成功完成"`（`:255-265`），不碰真实经验。
- `scripts/ci/` 三个门禁（osv / perf / deploy-config）无经验门禁；
  `tests/benchmarks/` 仅多智能体一题；`neurova/evolution/eval/` holdout 框架对
  experience 零引用。
- 现有测试断言的是"写进去了/参数被同步了"，不是"经验变好了"：
  `test_experience_feedback.py:57,66,75` 三处断言 `outcome in {success,partial,failure}`
  —— 该函数返回域本就是这三个值，任何输入都通过（无法失败的门禁测试）。
- 时序判读：门控**参数面** 09-12~09-16 密集动过（旋钮接活、LLM 裁决层、自喂递归修复），
  **度量面** `metrics.py` 最后改动是 06-25，治理面
  （`governance_settings.py:25-29` / `app_settings.py:26-67` / `evolution_settings.py:36-44`）
  无任何经验质量项。改的是"让门槛可调"，没做"让质量可测"。

---

## 2. 门控清单：真门 / 幻影门 / 恒真门

| # | 门控 | 位置 | 判定 |
|---|---|---|---|
| G1 | `tool_success` 基于工具实际成败 | `post_chat_pipeline.py:1612` | **恒真**（缺键默认 + `any()`） |
| G2 | `classify_outcome` 关键词分类 | `experience_feedback.py:151-164` | 无命中即 success，**默认放行** |
| G3 | 真实 `success` 传入经验处理 | `closed_loop.py:506-510` | **参数被丢弃**（判据被关键词覆盖） |
| G4 | 结晶门槛 3 次 / 60% | `pattern_crystallizer.py:210,230` | **生效**，但是硬编码字面量，不在可调面 |
| G5 | RSI 调 `crystallize_min_*` | `integration_manager.py:220-222` → `ExperienceFeedback` | **幻影**：调不动 G4 |
| G6 | 结晶 LLM 可复用性裁决 | `pattern_crystallizer.py:264-271` | 部分生效：需 `_llm_judge` 已注入，而唯一注入点 `post_chat_pipeline.py:2647` 只在 `list_pending()` 非空时执行 ⇒ **首批候选必直写** |
| G7 | 超龄候选处理（48h） | `pattern_crystallizer.py:332-341` | **自动放行**（绕过裁决）；时间戳解析失败返回 `0.0` ⇒ 既不过期也永不被裁决 |
| G8 | 结晶成功后回灌经验 | `pattern_crystallizer.py:305-311` | 位置参数硬写 `True` ⇒ **自喂成功票** |
| G9 | EKB 写入门槛 | `experience_knowledge_base.py:259-273` | 仅"全字段完全相同"去重，无阈值/无最小样本 |
| G10 | 记忆写入内容门 | `memory_layer/manager.py:701-884` | **无 dedup/相似度/冲突判断**；非法类型静默降级（`:753-754`） |
| G11 | `memory_type="workflow_experience"` 类型隔离 | `post_chat_pipeline.py:2908` + `models.py:15-23` | 不在枚举 ⇒ 每条工作流经验静默写成 `SEMANTIC`，类型区分消失 |
| G12 | 记忆冲突检测 | `post_chat_pipeline.py:2217-2248` | 只 `logger.warning`，不否决不回滚，且执行时机在 `save_memory` **之后** |
| G13 | PatternMiner `min_success_rate` | `pattern_miner.py:176,184` | 形参零消费（docstring 自陈"暂未使用"），导出 `success_rate: 1.0` 字面量（`:201`） |
| G14 | 遗传臂 seed 真实成功率 | `post_chat_pipeline.py:2003-2015` | `FrequentPattern` 无 `success_rate` 字段（`pattern_miner.py:26-31` 只有 `tools/support/context`）⇒ `getattr(..., None) or 0.5` **恒 0.5**；`fitness = success_rate*time_penalty + log1p(reuse)*0.1`（`genetic_engine.py:39-55`），注册门槛 0.8（`:77,517`）⇒ 新挖出的模式**当轮必被跳过**，只有同一条工具序列被 `record_reuse` 累计约 20 次后才可能跨过（base 仍是错的 0.5，不是真实成功率） |
| G15 | NL 合成 `min_confidence` | `nl_synthesizer.py:250-258` | 低置信只 `warnings.append`，随后无条件 `success=True` |
| G16 | 技能经验自动淘汰 | `skill_experience.py:549` | 默认关（需 `NEUROVA_SKILL_AUTO_RETIRE=1`，未进 `.env.example`） |
| G17 | 封装臂客观票据 | `creation_governance.py:144-155,182-183,209-215` | **真门（对照组）**：服务端 SQLite 逐工具成败 + 失败粘性 `MIN(success)` + ≥3 独立任务成功 |
| G18 | 评审闸 | `skill_review_gate.py:35` | 生效（默认开）——唯一默认收紧的门 |

G17/G18 证明一件事：**这套仓库里已经有可用的客观证据机制**（工具级成败票据），
只是结晶器 / `ExperienceFeedback` / EKB 三条主经验臂**都没接它**。

---

## 3. 写入臂地图（8 条，判据强度差异极大）

| 臂 | 触发 | 成败依据 | 客观回执 | 证伪回路 |
|---|---|---|---|---|
| 结晶器 `PatternCrystallizer` | Step9 → `closed_loop.py:524` | 关键词 + 恒真 success | 无 | 无 |
| `ExperienceFeedback`（工具权重/关联） | Step9 → `closed_loop.py:507` | 关键词 | 无（真实 success 被丢） | 权重侧有计数，经验侧无 |
| 模式挖掘 `PatternMiner` | Step9.6 → `:1927` | 无 | 无 | 无 |
| EKB `experience_records` | Step9 → `:1642-1655` | G1 恒真 | 有 `session_id`，无成败证据 | 无（全表无 UPDATE） |
| 工作流经验 | Step9.05 → `:2872,2894-2910` | `status == completed` + 成功节点计数 | **有** | 无；且类型静默降级（G11） |
| 规则提取 / 记忆融合 | Step9.96 | 恒真（`post_chat_pipeline.py:3055` 字面量 `success: True`） | 无 | 无；**治理默认关**（`governance_settings.py:26`） |
| 技能封装 / 改进 / 归因 | `skill_encapsulation`、`skill_improver`、`skill_attribution` | **服务端票据**（G17） | 有 | 有（`record_usage` 累计正负样本） |
| 反思 `growth_log` | Step8.5 → `:1404` | 关键词触发；`confidence = 0.5` 常数（`:1392`） | 无 | 半有（仅负反馈降权 `growth_log.py:469-483`） |

**质量从低到高的排序，恰好与"是否使用客观票据"完全一致。**
这不像是阈值调错，像是三条主臂从来没接上客观证据源。

---

## 4. 已核对为"非问题"的两点（避免误判）

1. **LLM 裁决闸未被本批 008 的降频巡检节流**：`set_llm_judge` /
   `review_pending_with_llm`（`post_chat_pipeline.py:2640-2657`）位于
   `_step_rsi_iteration`（`:2473` 起）内、在 cadence 判定（`:2741`）**之前**，
   每轮 Step11 都会走。故"降频巡检"不影响经验裁决可达性 —— 但 G6 的
   "首批候选必直写"仍成立（与节流无关）。
2. **`_NullSystem` 上的 0.7**（`agent_core.py:390`）不是运行值：占位替身不供参数面
   （工单 018 后其 `rsi_placeholder` 生效），0.6/0.7 的冲突目前只构成"文档性不一致"，
   仍应消除以免被读成真实门槛。

---

## 5. 与既有批次的同构关系

本审计发现的根因形态，与 RSI 批次（工单 003-008）修的是同一类病：

| RSI 已修的形态 | 经验侧的对应命中 |
|---|---|
| `get("roi", 0.0)` 把"无数据"写成 0 参与判定（工单 006） | `.get("success", True)` 把"无成败"写成成功（G1） |
| 幻影守卫：守卫读点与写点不是同一处（工单 006） | 幻影门槛：可调旋钮与真门分离（G5 / L2） |
| `insufficient_data` 被读成"没发散所以可晋升"（工单 003/008） | 无关键词命中被读成"success"（G2） |
| 度量失明被读成"已收敛"（工单 007/008） | 检索成功率被当经验质量（L3） |
| 判据与推进分离、三态 `GateVerdict` | 经验侧尚无对应物 |

反思链B 的教训也适用：**测试全绿覆盖了契约，却漏掉布线**（L5 的三套聚合逻辑零调用方）。

---

## 6. 修复方向候选（未实施，待裁决）

按"最小可证伪切片"排，每条给出**完成后能被什么判据证伪**：

**P0-A 让 `success` 成为携带信息的信号**
- 复用同文件已有的正确写法（`post_chat_pipeline.py:2115`）：只统计
  `type == "tool_result"` 的记录，取 `all(...)` 语义而非 `any(...)`；无工具轮不得默认成功，
  应产出 `None`（无证据）而不是 True。
- `closed_loop.py:507` 把真实 `success` 传进 `process_experience`；
  关键词分类降格为"分类细化"，不得覆盖客观票据。
- 判据：注入一条含失败工具结果的轮次 ⇒ `experience_records.success` 必须为 0；
  无工具轮 ⇒ 写入必须携带 `outcome=None`/unevidenced 而非 success。
  生产库现状（91/91 全 1）应变成可分布。

**P0-B 让唯一硬门槛回到可调参数面上**
- 结晶器读 `ExperienceFeedback`/治理登记的同名旋钮（消灭 G4/G5 双写），
  并消除 0.6 vs 0.7 冲突（按 ADR 0016 的四角色唯一性）。
- 判据：把 `crystallize_min_observations` 调到 5 ⇒ 4 次观察不得结晶（当前必失败）。
  已有 `test_rsi_param_governance.py:68-75` 的同类形态可参照。

**P0-C 质量必须能被测量（否则 A/B 无法验证）**
- 给 EKB 加 `hit_count` / `last_used_at` / `outcome_after_use`（或等价列）与一条 UPDATE 通路：
  注入哪条经验、该轮成败如何 ⇒ 回写。
- 把 `metrics.py` 的经验质量指标接进 `check_alerts()` 与 dashboard；
  把 `crystallized_experience_manager.get_statistics()` 接线（或删掉，不留假观测面）。
- 判据：一次注入被采纳且该轮失败的会话，必须能让对应条目的采纳率下降。

**P1-D 检索按质量截断，失败经验不得与成功经验同权重**
- `experience_knowledge_base.py:436` 的布尔门改成最低分数 + 置信阈值；
  注入前按 `success`/置信/新鲜度排序截断。
- 判据：一条低质/失败经验在同 query 下应排在高质量条目之后或被截断。

**P1-E 客观票据覆盖三条主臂**
- 让结晶器 / `ExperienceFeedback` / EKB 复用 `creation_governance` 的逐工具成败票据（G17 形态），
  取代关键词自述；G8 的自喂 `True` 改为携带"结晶这一动作"的独立事件，不冒充任务成功。
- 判据：无票据来源的经验条目不得入库（可证伪：伪造一轮自述成功但无票据 ⇒ 被拒）。

**P1-F 固化经验也要有生命周期**
- "温度≥80 不衰减"的豁免不得同时命中结晶经验，或给 PATTERN 节点接淘汰/复核路径；
  G7 的超龄自动放行改为"超龄即丢弃 + 计数告警"或"超龄仍走裁决但降低置信"，不得绕过闸。
- 判据：构造 rate=1.0 的结晶经验 ⇒ 在时间推进后必须可被淘汰或降权（当前永不被处理）。

**P2-G 治理面收口**
- `NEUROVA_CRYSTALLIZATION_LLM_GATE`（`pattern_crystallizer.py:109`）与自动淘汰 env
  纳入 `governance_settings`；前端补审核/降权（当前只有 delete，
  `ExperienceKnowledgePage.vue:155-171`），EKB 接上技能侧已有的 approve/reject 机制
  （`skill_pool_api.py:690/701`）。

**P2-H 去重与冲突**
- EKB 去重键从"全字段相同"改为语义/归一化键（现同一句"你好"存 7 条）；
  冲突检测要么前移到写入时并可否决，要么明确降级为纯观测（现在是"检测了但不拦"）。

---

## 7. 风险与待裁决

1. **收紧门槛会让经验量骤降**：当前 100% 通过率，任何真实判据接上后入库量必然断崖。
   需先决定：要"少而真"还是"保留量、把不确定项标 unevidenced"。建议后者
   （与本批 RSI 的三态裁决同一口径）。
2. **P0-C 需要 schema 迁移**（`experience_records` 加列 + 一条 UPDATE 通路）；
   本仓已有零停机迁移设施（`neurova/Storage/zero_downtime_migration.py`），
   属并发改动域，需确认由谁做。
3. **LLM 裁决闸的覆盖策略**：G6 的"首批必直写"要不要改成"judge 未注入则留队不直写"？
   后者在零 LLM 环境下会让整条结晶臂停摆 —— 与 `:110` 注释声明的"零 LLM 语义"目标冲突，
   需要明确取舍（成本 vs 质量）。
4. 是否把经验臂纳入 RSI 的晋升判据面（`_REQUIRED_EVIDENCE` 思路）：
   一旦经验质量成为可测量指标，`crystallize_min_*` 的调参才有收敛语义可言。

---

## 8. 复核方法（本文所有数字可重跑）

```bash
# 生产库分布（只读）
./.venv/Scripts/python.exe -c "import sqlite3;c=sqlite3.connect('file:data/experience_knowledge.db?mode=ro',uri=True);\
print(c.execute('select count(*), sum(success) from experience_records').fetchone());\
print(c.execute('select count(*) from experience_records where confidence_score is not null').fetchone());\
print(c.execute('select count(*) from experience_records where agent_id is not null').fetchone());\
print(c.execute('select context,count(*) c from experience_records group by context having c>1 order by c desc limit 3').fetchall())"

# 全表无写回
grep -nE "UPDATE " neurova/skills/experience_knowledge_base.py     # 期望：零命中

# 幻影门槛
grep -n ">= 3\|rate < 0.6" neurova/cognitive_layers/memory_layer/pattern_crystallizer.py
grep -n "crystallize_min" neurova/evolution/experience_feedback.py neurova/agent_core.py

# 恒真 success
grep -n "success.*True" neurova/post_chat_pipeline.py
grep -n "默认为成功" neurova/evolution/experience_feedback.py
```
