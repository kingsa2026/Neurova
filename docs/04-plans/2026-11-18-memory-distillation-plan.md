# 记忆蒸馏回写立项方案（2026-11-18）

> 状态：已立项待实施。来源：QwenPaw 对照批 B2 的后续裁定——蒸馏回写
> **进记忆温度体系，不进 markdown**（MEMORY.md 已随之退役，见
> `2026-11-18-assistant-harness-adoption-plan.md` 二轮记录）。本文档为实施依据。

## 1. 目标与非目标

**目标**：把对话中"值得长期记住的事实"由 LLM 归纳为记忆候选，走本仓既有
治理链落库：

```
对话轮末（异步） → 取材窗口 → LLM 归纳候选
  → memory_admission 敏感筛查（screenMemoryContent）
  → PendingMemoryStore.propose（指纹去重/tombstone/租约）
  → 人工审阅（pending 审阅面 + S16 纪律转正）
  → memories 表（温度初始化 → 衰减/整合/召回全生命周期）
```

**非目标**：
- 不直写 `memories` 表（必须过候选+审阅；自动转正仅留显式灰度开关）；
- 不写任何 markdown 文件（MEMORY.md 已退役，不复开文件旁路）；
- 不做跨会话批量重构（那是 sleep 整合的既有职责）。

## 2. 触发与取材

- **触发点**：轮末异步任务（`post_chat_pipeline` 之后），不阻塞回复；
- **触发条件**（可配，默认保守）：每 N 轮（默认 6）或会话收尾时执行一次；
  用户显式说"记住…/以后…"的轮次可提前触发（关键词门，Phase 2 再做）；
- **取材窗口**：当前轮 + 近 K 轮对话与工具结果（有界字符窗口，超限截断）；
- **灰度开关**：`NEUROVA_MEMORY_DISTILL`（默认 off；对齐 S16
  `NEUROVA_MEMORY_DISCIPLINE` 先例——先_off_ 观察再翻默认）；
- **预算护栏**：每会话每窗口候选上限（默认 8）、单轮 LLM 调用超时上限、
  失败计数熔断（连续失败暂停蒸馏并留痕）。

## 3. 归纳与准入（单管道，全部复用既有单点）

1. **归纳**：LLM 走 agent 自身 provider 链（复用 multi_model_client 回退
   链；桩测试必须走真 SSE 形态，见 S17 教训），提示词复用
   `memory_admission.admissionChecklistPrompt()` 的口径 + 输出 JSON 数组：
   `{content, category, memory_type, importance 建议, supersede 建议}`；
   输出条数与长度有界；
2. **准入**：逐条 `screenMemoryContent`——命中敏感按现行 policy
   （reject/redact）处理，计数入 `admissionCounters`，审计事件照发；
3. **候选**：`PendingMemoryStore.propose`（`proposed_by="distiller"`）——
   指纹去重、tombstone 拦截、同键 supersede 建议随候选带出；
4. **审阅**：沿用 `api/endpoints/memory/pending.py` 审阅面与 S16 纪律的
   转正/世代失效机制；confirmed → 落 `memories` 表；
5. **落库后**：温度按 importance 规则初始化，进入正常衰减/召回生命周期；
   不做任何"永久免衰减"特判。

## 4. 红线（防退化）

- 绝不绕过候选/审阅直写 memories（`NEUROVA_MEMORY_DISTILL_AUTOPROMOTE`
  显式开启时仅限低敏类别，且逐条留审计）；
- 绝不恢复 MEMORY.md 或任何文件旁路；
- LLM 失败/超时/解析失败一律 fail-soft：计数留痕、不阻断主对话、不重试
  超过 1 次；
- 候选洪水防护：同会话同窗口超上限即丢弃并计数。

## 5. 分批与验收（先红后绿，每批 A/B 零新增 + live-verify）

| 批 | 内容 | 验收判据 |
|---|---|---|
| D1 | 蒸馏器骨架：触发器/取材窗口/LLM 归纳/开关/预算护栏（`neurova/memory/distiller.py`） | 开关关=零行为变化；桩 LLM 真 SSE 驱动产出候选 JSON；超时/失败熔断用例 |
| D2 | 接 admission + pending：敏感拦截、指纹去重、tombstone、propose | 敏感样例被拦/脱敏；重复内容只出一条候选；契约测试红→绿 |
| D3 | 审阅接通 + 转正落库：复用 pending 审阅端点，confirmed → memories 温度初始化 | 端到端：对话→候选→人工确认→memories 可召回；A/B memory/api 域零新增 |
| D4 | 观测面：admission/distill 计数进既有指标读面；方案执行记录 | live-verify：真后端跑"记住这件事"对话，pending 出现候选 |

## 6. 关联裁定记录

- 2026-11-18 用户裁定：蒸馏回写接温度机制，不进 MEMORY.md；
- 2026-11-18 用户拍板：MEMORY.md 退役（`c132f7d64`），本方案为其后继；
- 依据机制：`memory_admission.py`、`memory/pending_memory.py`、
  `memory_discipline.py`（S16）、`cognitive_layers/memory_layer/temperature.py`、
  `sleep_writeback.py`。

## 7. 执行记录（2026-11-18，严格按教义）

| 批 | 结果 | 提交 |
|---|---|---|
| D1–D3 | ✅ 落地：`neurova/memory/distiller.py`（开关 NEUROVA_MEMORY_DISTILL 默认 off/取材窗口 6000 字符有界/LLM 非流式归纳 30s 超时/admission enforce 筛查/propose 候选/连续失败 3 次熔断 300s 冷却/fail-soft）+ PostChatPipeline 注册 `memory_distill` 后台步骤（开关关=不注册零步）；12 契约用例红 12→绿 12（开关关零行为/双候选入队/重复幂等/confirm 转正 remember_fn 三元组/敏感跳过/熔断/超时/坏 JSON/错误信封/接线源码断言） | a2fb8f6a6 |
| D4 | ✅ 落地：`neurova_memory_distill_candidates_total`（outcome=turn/submitted/duplicate/sensitive/failed）进 /metrics 指标读面 + distillCounters 进程内快照；红 1→绿，13/13 | 2fc1240ad |

**A/B**：agent+api+memory 三域（约 6500 用例）前后各一遍——失败集合**逐行
完全一致**（29 个预存失败两侧相同：webhooks/tkg/goal_gate/storage 等），
通过数差恰为新增 13 用例，零新增失败。

**live-verify**：9683 真后端（NEUROVA_MEMORY_DISTILL=1）+ 桩 LLM 驱动真
治理链——蒸馏器在真实数据根产出候选 → GET /api/v1/memory/pending 可见
（proposed_by=distiller）→ POST confirm 200 → GET /api/v1/memory 检索命中
（temperature=75、lifecycle=active、origin=agent）；种子数据已清偿
（memories/pending 零残留）。

**执行期坑**：①多笔提交的 git revert 会因"后笔改过前笔新增的文件"产生
modify/delete 冲突——基线还原改用 checkout 父版文件+删新增文件；
②模块级熔断计数按 agent 维度跨用例存续，测试须用独立 agent_id 隔离。
