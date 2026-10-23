# 知识治理四项剩余缺口设计（设计先行，未实施）

- 文档性质：目标态设计 + 决策票，不是工单，不落实现
- 成文日期：2026-10-23
- 基线：[知识库治理与 RAG 闭环审计](../../audit-reports/knowledge-governance-rag-audit-2026-10-23.md)
- 约束：`AGENTS.md` 修复教义/协作红线；[知识底座目标态设计](2026-09-20-knowledge-foundation-design.md) 的“零新增外部服务、零新增第三方依赖”取向
- 当前状态：**D1 丙 / D2 乙 / D3 乙 / D4 甲 已按推荐方案落地工作树**（2026-10-23）；实现、判据与剩余生产者见 §11

---

## 0. 范围与非目标

本文只覆盖四项在上一轮实施后仍然只能登记、不能在本层硬做的缺口：

1. **人工接管率**：渠道没有结构化接管事件。
2. **一般拒答率**：目前只有 `finish_reason=content_filter` 这个硬信号。
3. **token 归因精度**：当前是按命中事实均分（`even_split`），不是真实逐条成本。
4. **更大规模**：100k 已从 4.67s 降到 1.02s，但再往上仍靠全量/有界扫描，不是索引结构升级。

**非目标**：

- 不在本文里改代码、加表、改 API 或写迁移。
- 不把“模型说不知道”“回答很短”“没有引用”这类文本特征直接当拒答——那会制造不可复核的指标。
- 不为人工接管/拒答制造默认 0；没有事件源就是 `unknown`，并单独报出。
- 不在未拍板前引入 ANN/外部搜索服务或新第三方依赖。

---

## 1. 现状基线（可核）

### 1.1 人工接管

- 全仓检索 `takeover` / `handoff` / `转人工` / `human agent`：没有渠道侧“人工接管开始/结束”的结构化事件；`转人工`只出现在知识消解、进化复核等旁路队列，不是会话接管。
- `retrieval_metrics` 的 `uninstrumented.human_takeover_rate` 明确标为未接（[retrieval_metrics.py:64 附近](../../neurova/knowledge/retrieval_metrics.py)）。
- 现有可用数据只有会话、消息、助手回复；**没有“谁在何时接管了哪一轮”的事实**。

### 1.2 一般拒答

- 目前唯一可复算的硬信号是模型完成态 `finish_reason=content_filter`：聊天管线在完成态处记 `outcomes.model_refusal`（`neurova/agent/chat_pipeline.py:102`，两处调用在 `:2488`、`:2750`）。
- 没有“无答案 / 证据不足 / 知识库没有 / 主动拒答”的结构化 `TurnOutcome`；`should_need_more_context` 只用于是否二次检索，不是回答完成态。
- 因此当前只能报“模型内容过滤事件数”，不能报一个可解释的 `refusal_rate`。

### 1.3 token 归因（含当前实现的已知缺陷）

- v14 已有 `knowledge_fact_usage`（[knowledge_facts.py:170](../../neurova/knowledge/foundation/knowledge_facts.py#L170)），`recordTokenUsage`（`:574`）按命中事实均分 prompt/completion，`attribution='even_split'`。
- post-chat 在会话保存成功后调用（[post_chat_pipeline.py:1161](../../neurova/post_chat_pipeline.py#L1161)），usage 取 `usage_accounting.last_call()`，指标由 `tokenUsageMetrics`（`:624`）聚合。
- **已知缺陷（P0，必须先修）**：`sourceTurnId` 现在传的是 `result_session_id`（`:1161`），而 `recordTokenUsage` 用 `source_turn_id` 做幂等（`:594`）。同一会话的第二轮会被当成“已记录”直接跳过——当前 `even_split` 读数实际只覆盖每个会话的第一轮。这个缺陷不是精度问题，是**归属错误**；在它修好前，不能把当前读数当多轮成本。
- 另外，当前没有区分“检索输入 token（注入了多少上下文）”与“生成 token（LLM 实际用量）”，两者被混在一条均分记录里；也没有按引用关系归因。

### 1.4 更大规模

- 主路是分片 TF-IDF（`repository.search_visible_items`），辅助 BM25/FTS 对可见语料逐次 tokenize；大语料时辅助路被 `NEUROVA_KB_AUX_SCAN_LIMIT`（默认 10k）限制在主索引候选上（[hybrid.py:39](../../neurova/knowledge/hybrid.py#L39)、`:201`）。
- 规模探针（合成语料，`tests/manual/knowledgeRetrievalScaleProbe.py`）：1k→500 候选/526.6ms；10k→5,000/463.8ms；100k→50,000/1,021.5ms。100k 的 1.02s 是“有界辅助路”读数，不是索引结构升级。
- 向量索引仍是每用户 JSON 全量余弦扫描；主 TF-IDF 仍是内存分片。没有持久化倒排、分片路由或 ANN；更大规模会先撞主索引扫描与进程内存。

---

## 2. 共同设计纪律

这四条共用一个“质量事件/指标”底座，先定纪律，避免四个功能各长一套。

1. **事件是事实，指标是投影**：先落不可变事件（谁、何时、哪一轮、什么类型、来源），再从事件算比率。禁止在读取时用文本猜事件。
2. **每个指标必须有分子、分母、窗口、维度**；没有分母或没有事件时返回 `unevidenced`，不回 0。
3. **unknown 是一等状态**：无法分类的轮次进 `unknown`，不混进“已回答”或“拒答”。分母默认排除 unknown，同时单独报 unknown 率。
4. **单一事实源**：一种事件只有一个生产者契约、一张账、一处聚合；不在 knowledge、chat、channel 各记一份计数。
5. **幂等**：事件用 `(source, source_event_id)` 或 `(turn_id, phase, fact_id)` 唯一键；重放不重复计数。
6. **隐私最小化**：只存 id、类型、时间、原因码、模型/通道维度；不存消息正文、不存用户隐私。操作者 id 走既有权限域。
7. **先契约后接线**：渠道/管线先按 schema 产出事件，再开指标面；没有生产者的字段不进“已测”指标。
8. **可回退**：新表/新事件全部可双写、可关闸；旧读数不被新口径覆盖，口径变更带版本号。

---

## 3. 人工接管率

### 3.1 定义

- `human_takeover_started`：一条会话/一轮对话从“Agent 自动应答”切到“人类操作者接管”的事实。
- `human_takeover_ended`：人类交还或会话结束；可与 started 配对算时长，但首期只算次数/率。
- **接管率**（推荐）：窗口内“至少发生过一次 takeover_started 的会话数” / “窗口内至少有一条 assistant 回复的会话数”。事件数作为辅助读数，不拿它当率。
- 维度：渠道、agent、source（`channel_event` / `console_mark` / `api`）、原因码。
- 分母排除：无 assistant 回复的会话、测试/内部会话（用既有隔离标记）、无法确认身份的匿名渠道（单列 `unknown`）。

### 3.2 方案对比

| 方案 | 做法 | 代价 | 风险 |
|---|---|---|---|
| A 渠道原生事件 | 渠道适配器在人工客服接手/转接时发标准事件 | 每个渠道适配器各接一次；部分渠道没有该事件 | 最准确；渠道覆盖不全 |
| B 控制台人工标记 | 运营在会话页点“人工接管/结束” | 需要前端入口和权限 | 通用但会漏标，不能当唯一口径 |
| C 从消息/角色推断 | 看到“human”角色或某类消息就判接管 | 无 | 身份与语义都不稳，**不做** |

**推荐：A + B，`source` 区分。** A 是主口径，B 是兜底；C 明确不做。首期即使只有 B，也必须把 source 标成 `console_mark`，不能冒充渠道全量。

### 3.3 数据模型（目标态）

新增一个**会话质量域**，不塞进知识事实表：

```sql
CREATE TABLE conversation_quality_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,        -- human_takeover_started / human_takeover_ended
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,            -- channel_event / console_mark / api
  source_event_id TEXT NOT NULL DEFAULT '',
  actor_id TEXT NOT NULL DEFAULT '',
  reason_code TEXT NOT NULL DEFAULT '',
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX ux_quality_source_event
  ON conversation_quality_events(source, source_event_id)
  WHERE source_event_id <> '';
CREATE INDEX idx_quality_session_time
  ON conversation_quality_events(session_id, occurred_at);
```

- `metadata_json` 只放渠道/工单号等低敏维度，不放正文。
- 事件由 `conversation_quality` 服务写入；knowledge/chat 只读聚合，不各自写计数。

### 3.4 API 与生产者

- 写：`POST /v1/quality/outcomes`（service/admin；渠道适配器与控制台共用）。
  - body：`event_type`、`session_id`、`agent_id`、`channel`、`source`、`source_event_id`、`actor_id`、`reason_code`、`occurred_at`、`metadata`。
  - 幂等：`(source, source_event_id)` 冲突返回已有事件，不重复插入。
- 读：`GET /v1/quality/metrics?window=7d&group_by=channel`。
- 生产者：
  - 渠道适配器：飞书/企业微信等人工客服转接事件（有则接；没有则显式标 `unsupported`）。
  - 控制台：会话页“人工接管/结束”按钮（首期可先落这个）。
  - 外部 API：只给受信服务令牌，不允许普通用户伪造接管。

### 3.5 指标口径

```
human_takeover_rate = distinct(sessions with takeover_started) /
                      distinct(sessions with assistant reply)
```

- 窗口：默认 7 天，支持 24h/30d；同一会话多次接管只计一次（率），另报事件数。
- 同时报：`takeover_sessions`、`takeover_events`、`takeover_sources{channel_event,console_mark}`、`takeover_unknown_channels`。
- 没有事件源/没有回复的窗口返回 `unevidenced` + `missing_reason`，不回 0。

### 3.6 验收

- 同一 `source_event_id` 重放两次，事件数不变。
- 两个渠道来源写同一会话，率仍按会话去重。
- 无 assistant 回复的会话不进分母；`console_mark` 不冒充 `channel_event`。
- 关闸后读面返回旧口径/unevidenced，不伪造。
- 活体：控制台标记 + 一条合成渠道事件 → 率与来源分布可复算。

### 3.7 风险与回退

- 渠道事件缺失会导致低估：在响应里返回 `coverage`，不把覆盖不足读成“接管少”。
- 人工误标：`reason_code` + actor 留痕，可撤销（追加 `..._ended`/修正事件，不物理删）。
- 回退：关闭写入口，保留表；读面回落旧口径并标 `measure_state`。

---

## 4. 一般拒答率

### 4.1 先定义，再统计

“拒答”至少有三类，混成一个率不可解释：

1. **安全拒答**：模型/网关 `content_filter` 或安全门拒绝。
2. **证据不足**：检索/记忆没有足够证据，Agent 按策略不编造。
3. **工具/执行失败**：不是拒答，是失败；应单独报。

推荐拆成两个主指标 + 一个未分类：

```
safety_refusal_rate = turns_with(safety_refusal) / turns_with_known_outcome
insufficient_evidence_rate = turns_with(insufficient_evidence) / turns_with_known_outcome
unknown_outcome_rate = turns_with(unknown) / all_turns
```

`turns_with_known_outcome = all_turns - unknown`；分母、unknown 分开报，避免拿 unknown 当“已回答”。

### 4.2 方案对比

| 方案 | 做法 | 代价 | 风险 |
|---|---|---|---|
| A 管线显式 TurnOutcome | 回答装配处写枚举，硬信号驱动 | 需要改 chat pipeline 的完成态；需要产品定义“证据不足”阈值 | 可复核；最推荐 |
| B 事后 LLM 判官 | 对回复+检索证据分类 | 成本/延迟/漂移 | 只能作辅助，不能当事实源 |
| C 文本关键词 | “不知道/抱歉/无法”命中即拒答 | 零成本 | 误报高，**不做** |

**推荐：A，B 只作旁证。** 枚举建议：

```text
answered
safety_refusal       # content_filter / 安全门
insufficient_evidence# 检索 gate 判定无足够证据且按策略不编造
tool_failure         # 工具失败，单列，不算拒答
handoff              # 人工接管（与第 3 节事件对齐）
unknown              # 管线未分类
```

- `content_filter` 继续由 `finish_reason` 产生；安全门拒绝由现有错误策略的 `content_safety` 产生。
- `insufficient_evidence` 必须引用一个**确定性 gate**（例如现有 `should_need_more_context` 的阈值 + 本轮无知识/记忆命中的事实），不能由文本长度或“看起来像拒答”推断。
- `tool_failure` 不并入拒答率；否则工具坏了会被读成模型不愿回答。

### 4.3 数据与 API

- 首期事件可随 assistant metadata 落盘（`turn_outcome` + `outcome_reason_code` + `outcome_source` + `turn_id`），同时进 `conversation_quality_events`（与第 3 节同库）。
- 读：`GET /v1/quality/metrics` 返回 `safety_refusal_rate`、`insufficient_evidence_rate`、`tool_failure_rate`、`unknown_outcome_rate`、分母与窗口。
- 生产点：chat pipeline 完成态（流式 done / 非流式 response）统一调用一个 `finishTurnOutcome()`；不允许各分支各写一份。
- `content_filter` 已有硬信号；其余枚举只有在管线能确定时写，否则 `unknown`。

### 4.4 验收

- 每种枚举各一条行为判据；`content_filter` 仍只由 finish_reason 产生。
- 同一轮不会同时计入 `safety_refusal` 与 `insufficient_evidence`。
- `unknown` 不进入两个率的分母，但出现在 `unknown_outcome_rate`。
- 工具失败不被计入拒答率。
- 无事件时 `unevidenced`，不回 0；与知识指标共用窗口/维度。

### 4.5 风险与回退

- “证据不足”阈值是产品语义：先给阈值票（按检索质量/命中数/证据态），不把某个阈值写成契约。
- 过度分类会制造假阳性：首期只接硬信号，`insufficient_evidence` 可先标 `experimental`。
- 回退：关闭枚举写入，旧 `model_refusal` 计数保留，读面标 `legacy`。

---

## 5. token 归因精度

### 5.1 成本分解

一次知识回答至少有四层成本，不能混成一条均分：

| 层 | 来源 | 首期可否精确 |
|---|---|---|
| 检索输入 | 注入的父/子块 token、查询改写 token | 可按 tokenizer 精确计数（与模型 tokenizer 对齐时标 true，否则 estimated） |
| 向量/重排 | embedding/rerank 调用 | 有 usage 才记；没有就 `unmetered`，不摊到 fact |
| 生成 | LLM prompt/completion usage | `usage_accounting` 有真值；无 usage 时 estimated |
| 后处理 | 反思/摘要等旁路 | 不属于本轮回答，单列或不进 fact |

### 5.2 P0 缺陷：turn_id

**P0 已修（2026-10-23）**：`post_chat_pipeline.py` 现在每轮生成 `turn_id`（trace_id/uuid），v15 以 `(turn_id, fact_id, phase)` 做幂等；两轮同会话判据已绿。下面保留缺陷描述作为设计依据。

目标态：

- 每轮生成唯一 `turn_id`（优先 `trace_id`，否则 `session_id + assistant timestamp/uuid`）。
- `knowledge_fact_usage` 增加 `turn_id`、`phase`、`model`、`estimated`、`attribution` 列；唯一键 `(turn_id, fact_id, phase)`。
- `source_turn_id` 保留为兼容/溯源，不再承担幂等。
- 修好前，当前 `even_split` 读数不得用于多轮成本结论。

### 5.3 归因策略

按可信度从高到低：

1. **显式引用**：回答/标注里明确引用了哪条 fact → 生成 token 归到被引用 fact；未被引用但注入的只计检索输入。
2. **证据态/置信加权**：无引用但有 fact 级证据态/重排分 → 可按权重分摊，标 `weighted_estimate`。
3. **均分**：无引用、无权重 → `even_split`（当前口径），明确是估计。
4. **不归因**：没有 lineage / 没有 usage → 不写 fact 行，只能记 turn 级 `unmetered`。

**不变量**：

- 同一 `(turn_id, phase=generation)` 的 fact 分摊之和 ≤ 该轮生成总 token；差额进 `unattributed`，不丢。
- 检索输入 token 独立记录，**不加进**生成总量，避免双计。
- 每条 fact 行带 `estimated`/`attribution`；UI/报表不得把 estimate 画成 true。
- 重放按唯一键幂等；模型/价格变化不改历史行。

### 5.4 数据模型（目标态 v15）

在 v14 表上扩展（迁移只增列/加索引，不改旧行）：

```sql
ALTER TABLE knowledge_fact_usage ADD COLUMN turn_id TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_fact_usage ADD COLUMN phase TEXT NOT NULL DEFAULT 'generation';
ALTER TABLE knowledge_fact_usage ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_fact_usage ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_fact_usage ADD COLUMN unattributed_tokens INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX ux_fact_usage_turn_phase
  ON knowledge_fact_usage(turn_id, fact_id, phase)
  WHERE turn_id <> '';
```

- `phase`：`retrieval` / `generation` / `rerank`（可选）。
- `attribution` 已有，值扩展为 `explicit_citation|weighted_estimate|even_split|unattributed`。
- 历史 v14 行 `turn_id=''`，迁移后标 `legacy`，不重算、不冒充。

### 5.5 指标与 API

- `GET /v1/quality/metrics` 增加：
  - `token_cost_per_fact`（按 fact 聚合，区分 estimated/true）；
  - `token_cost_per_turn`；
  - `unattributed_token_share`；
  - `estimated_token_share`；
  - 维度：model、agent、channel、window。
- 现有 `/knowledge/audit/retrieval-metrics` 保留 `knowledge_token_usage` 只读快照；两者共用同一表，不各算一套。
- 价格（USD）只在有定价表时计算，并标 `pricing_source/version`；没有定价就只报 token，不报钱。

### 5.6 验收

- 同一会话两轮：产生两个 `turn_id`，usage 行数随轮次增长（回归当前只写第一轮的缺陷）。
- 同一 `turn_id` 重放：行数/总量不变。
- 生成分摊总和 + `unattributed` = 该轮 usage；检索 token 不计入生成总和。
- 无 usage/无 lineage：不写 fact 行，返回 `unmetered`；不伪造 0。
- 显式引用、加权、均分三条路径各有一条行为判据；`estimated` 标对。
- 迁移后旧行可读、不重算；A/B 不回归。

---

## 6. 更大规模索引

### 6.1 目标与 SLO（待拍板）

建议先定可验收的 SLO，而不是“支持 1M”这句话：

- 100k 文档：检索 p95 ≤ 300ms（当前合成 1.02s）。
- 1M 文档：检索 p95 ≤ 1s；内存有上限；召回@5 不低于当前基线的可接受容差。
- 更新/删除后索引可见延迟 ≤ 一次检索/维护周期；不出现已删除文档命中。
- 权限隔离：private/public/shared 分片不串。

这些都需产品拍板；未拍板前不写死实现。

### 6.2 方案对比

| 方案 | 做法 | 代价 | 风险 |
|---|---|---|---|
| A SQLite FTS5 持久倒排 | 内置 FTS5，按 agent/scope/category 分片，增量 outbox；中文用预分词/trigram | 需要索引表、迁移、双写、重建；FTS5 中文分词要处理 | 无新依赖；最符合“零外部服务” |
| B 继续主 TF-IDF + 辅助 cap | 只做 tokenize 缓存/候选上限 | 小改 | 仍是线性扫描，100k 以上不可持续 |
| C ANN 向量索引 | hnswlib/faiss 等可选依赖 | 新依赖、模型/索引版本管理 | 依赖政策需改；只解向量路，不解词法路 |
| D 外部搜索服务 | ES/OpenSearch 等 | 新服务、运维 | 与底座约束冲突，**不选** |

**推荐：A 优先，C 仅在基准证明词法路已达标、向量路成为瓶颈且依赖政策放开时再议。** B 只作过渡。

### 6.3 索引模型

- 先做**词法倒排**：
  - doc 粒度 = `knowledge_id#chunk_index`（与现有 `_item_index_docs` 单源）。
  - 列：`knowledge_id`、`agent_id`、`visibility/scope`、`category`、`tags_json`、`source`、`updated_at`、`content_tokens`。
  - 中文：优先用仓库现有 `search.tokenize`（jieba 可选，缺席 n-gram）生成空格分隔的索引文本；FTS5 用 `unicode61` 吃预分词；不使用未验证的 FTS5 中文分词假设。
  - 查询：FTS5 MATCH 先过滤 `agent/scope/category/tags/time`，再 BM25；与现有 `visible_items` 的隔离口径逐条对齐。
  - 分片：至少按 `public` / `user:<uid>` / `shared` 与 agent 分；分片路由与现有 `_get_shard_scope` 同源，不另写一套。
- 增量：
  - 写路径落 outbox（现有 `_pending_ops` 的持久化版本），索引器批量应用；失败重试、幂等、可重建。
  - 删除/归档/过期条目走同一 outbox；after delete 不命中。
- 向量：
  - 首期保留每用户 JSON；引擎指纹已有；规模再大时再评估 ANN。
- 迁移：
  - E0 只建表/双写；E1 双读对账（FTS 结果 vs 旧 scan）；E2 切换主路；E3 删除旧全量扫描；E4 退役旧索引。
  - 每一步都有回退开关；迁移期间不改变可见性。

### 6.4 基准矩阵（必须现跑，不入估值）

| 维度 | 取值 |
|---|---|
| 文档量 | 1k / 10k / 100k / 1M |
| 查询 | 关键词、自然语言、标签/分类、权限隔离、无答案 |
| 读数 | recall@5、MRR、p50/p95 延迟、内存、索引大小 |
| 写面 | 新增/更新/删除/归档后可见性；重建耗时 |
| 并发 | 单路/8 路；不把并发抖动当索引收益 |
| 对照 | 当前主路 + aux cap（HEAD 态） |

### 6.5 验收

- SLO 达标；召回不低于基线容差；无答案不返回已删/越权条目。
- 双读对账零差集；重建与增量结果一致；索引健康度可读（现有 `/audit/index-health` 扩展）。
- 失败回退到旧路且读数标 `fallback`；不静默返回空。
- 1M 未实测前不宣称支持 1M。

---

## 7. 统一指标面

建议新增一个**质量域**读面，而不是继续把所有东西塞进知识检索端点：

```
GET /v1/quality/metrics?window=7d&group_by=channel,agent
{
  "measure_state": "measured|unevidenced",
  "window": {...},
  "conversation": {
    "turns": ...,
    "human_takeover_rate": ...,
    "safety_refusal_rate": ...,
    "insufficient_evidence_rate": ...,
    "tool_failure_rate": ...,
    "unknown_outcome_rate": ...,
    "denominators": {...},
    "coverage": {"channel_event": ..., "console_mark": ...}
  },
  "tokens": {
    "per_fact": {...},
    "per_turn": {...},
    "estimated_share": ...,
    "unattributed_share": ...
  },
  "missing": {...}
}
```

- 知识检索端点保留现有 `retrieval`/`lifecycle`/`token_usage` 快照；质量端点只读质量账，不重复知识索引读数。
- 每个指标带 `definition_version`；口径变更不覆盖历史读数。
- 保留期：事件账至少 90 天（可配置）；聚合快照可短；不存正文。

---

## 8. 分期与依赖

### P0（先决，不做完不进入精度/规模）

1. **修 turn_id**：当前 token 归因只覆盖每会话第一轮；先改成每轮唯一 id，补两轮同会话判据。
2. **定事件 schema**：`conversation_quality_events` 与 `TurnOutcome` 枚举；只建契约，不接渠道。
3. **拍板三项语义**：人工接管来源、拒答分类/分母、规模 SLO 与依赖政策（见 §9）。

### P1（token 精度）

- v15 迁移；检索/生成分层；引用优先 → 加权 → 均分；`unattributed`；质量端点 tokens 段。
- 验收：两轮、幂等、分摊不变量、estimated 标记。

### P2（接管/拒答事件）

- 控制台人工接管入口（先落地，source=console_mark）。
- 聊天完成态写 `TurnOutcome`；安全拒答/证据不足硬信号；unknown 单列。
- 渠道适配器按能力接 `human_takeover`；无能力标 `unsupported`，不造事件。
- 验收：来源覆盖、去重、分母、unknown、工具失败不混入。

### P3（大语料）

- FTS5 倒排 + 分片 + outbox；双写/双读/切换/回退；1k–1M 基准。
- ANN 只在基准与依赖政策都通过后另立票。

### 依赖关系

```
P0 turn_id/schema/decisions
   ├─▶ P1 token 精度
   ├─▶ P2 接管/拒答事件
   └─▶ P3 索引（SLO/依赖政策拍板后）
```

---

## 9. 决策票（需拍板）

### D1 人工接管来源

- 甲：只接渠道原生事件（准确但覆盖不全）。
- 乙：只做控制台人工标记（通用但会漏标）。
- 丙：甲＋乙，`source` 区分（推荐）。
- 代价/风险：甲要逐渠道接；乙依赖运营；丙需要覆盖率读数，不能把覆盖不足当“接管少”。

### D2 拒答口径

- 甲：只报 `safety_refusal`（content_filter/安全门），最保守。
- 乙：拆 `safety_refusal` + `insufficient_evidence` + `unknown`（推荐）。
- 丙：合成单一 `refusal_rate`（不建议；会把证据不足与安全拒答混在一起）。
- 需要产品定义“证据不足”的阈值；未定前该枚举标 `experimental`。

### D3 token 归因策略

- 甲：保留 even_split，只修 turn_id（最低成本，仍是估计）。
- 乙：引用优先 → 加权 → 均分，分层记录（推荐）。
- 丙：只为显式引用的事实记生成成本，其余进 `unattributed`（最保守，覆盖率低）。
- 需要决定是否把检索输入 token 计入“知识成本”（建议单列，不并入生成）。

### D4 规模 SLO 与依赖

- 甲：只做 FTS5 内置倒排，零新依赖（推荐先做）。
- 乙：FTS5 + ANN 可选依赖（需改依赖政策）。
- 丙：继续 aux cap，不换索引（只适合 100k 以内）。
- 需要给出 100k/1M 的目标 p95 与召回容差；未定前不写“支持 1M”。

---

## 10. 证据附录

### 10.1 当前实现位置

| 主题 | 证据 |
|---|---|
| content_filter 拒答计数 | `neurova/agent/chat_pipeline.py:102`；调用 `:2488`、`:2750` |
| 检索指标未接项 | `neurova/knowledge/retrieval_metrics.py` 的 `uninstrumented` |
| v14 token 表 | `neurova/knowledge/foundation/knowledge_facts.py:170` |
| 均分与幂等缺陷 | `knowledge_facts.py:574`、`:594`；`post_chat_pipeline.py:1161`、`:1189` |
| token 指标端点 | `neurova/api/endpoints/knowledge_core.py:322` |
| aux cap | `neurova/knowledge/hybrid.py:39`、`:201` |
| 周期维护/全量重算 | `neurova/knowledge/maintenance.py:21`、`:49`；`knowledge_core.py` 的 `/audit/reindex` |
| 索引健康 | `neurova/knowledge/vector_index.py:327`；`/audit/index-health` |
| 规模探针 | `tests/manual/knowledgeRetrievalScaleProbe.py` |

### 10.2 当前读数

- 宽域回归：217 passed（2026-10-23）。
- 100k 合成检索：50,000 候选 / 1,021.5ms（aux cap 前 4,672.3ms）。
- token usage：v14 表可读；`attribution=even_split`；**多轮只记第一轮**（见 §5.2）。
- 人工接管/一般拒答：无结构化事件；`uninstrumented` 明确点名。

### 10.3 设计边界

- 本文不把“模型回答看起来像拒答”当拒答；不把“没有接管事件”当 0。
- FTS5 是 SQLite 内置；ANN 的 hnswlib 已按拍板收进基础 `requirements.txt`
  （部署镜像内置），代码仍保留 faiss 探测与未安装时的 JSON 全量余弦回退。
- 所有表/事件/API 都需按 `AGENTS.md` 的单一事实源与先红后绿纪律落地；本文只是目标态与决策依据。

---

## 11. 实施状态（2026-10-23，D5–D10 已拍板并落地）

- **D1 人工接管（D5 甲）**：`conversation_quality_events`、`/v1/quality/outcomes`、`/v1/quality/metrics`、
  `GET /v1/quality/sessions/{id}/takeover` 已落。控制台会话页有接管/结束开关
  （`console_mark`，刷新按后端最近事件恢复）；`ChannelAdapter.humanTakeoverEvents`
  是渠道能力位，管理端渠道状态原样报出，**没有平台原生事件的渠道标 False，不伪造**。
  渠道侧 `human_takeover_started/ended` 经 `ChannelManager` 统一入账（`channel_event`）；
  三条原生 producer 已接：MQTT 协议事件、飞书服务台工单 `stage 1→2`/关闭态、
  微信客服 `session_status_change`（回调解密 + sync_msg，change_type 1/4 开始、2 转接、3 结束）。
  钉钉/Telegram/Discord 等没有可接的原生事件，能力位保持 False；
  质量 metrics 与管理员分析页都读这份能力读数。
- **D2 拒答与 tool_failure（D6 丙）**：分类仍只吃硬信号；执行链自身崩溃的工具记录显式带
  `turn_outcome: "tool_failure"`，由管线转成 `turn_outcome_override`；普通工具
  `success=False` 不整轮判失败。`POST /turn-outcomes` 写 `explicit_api` 来源，
  指标按 `turn_id` 去重且显式来源优先（后写不会被自动分类的幂等吞掉）。
- **D7 handoff**：维持乙案——接管事件单列，不改写任何轮的 `turn_outcome`。
- **D3 token（D8 甲 / D9 乙）**：检索结果的 `lineage_id` 作为结构化 `fact_id`；
  回答中的 citation 经既有 registry 抽成 `knowledge_citation_ids` 随 assistant metadata 落盘，
  生成侧归因按“引用优先→加权→均分”分摊。检索 token 使用当轮运行模型的 `tiktoken` 编码器；
  无官方编码的非 OpenAI 模型回退 `cl100k_base` 并标 estimated，tiktoken 缺席再回退 jieba；
  检索阶段模型名随 `knowledge_retrieval_tokens_model` 落账，不与生成阶段模型混用；
  无 fact lineage 的文档命中成本进 v17 `retrieval_unattributed_tokens`，不摊到任何 fact。
- **D4 规模（D10 乙 / 部署拍板）**：FTS5 持久倒排已落；ANN 优先 hnswlib、
  其次 faiss，按用户建索引，低于 `NEUROVA_KB_ANN_MIN_RECORDS` 不建，
  构建/查询失败均回退 JSON 全量余弦。**hnswlib 已收进基础 `requirements.txt`**，
  部署镜像内置；代码仍兼容未装环境。
  开发环境已装 hnswlib 0.8.0：`tests/manual/knowledgeAnnScaleProbe.py`
  10k/100k/1M 构建 125ms/1.93s/52.5s、查询 0.14/0.24/0.41ms、精确内积 top-10
  召回 1.0；live 索引健康报 `enabled=true backend=hnswlib`。1M FTS 构建
  **58.4s**、查询 **577.6ms**；100k 为 5.7s/58ms。部署侧未装 ANN 依赖时自动回退
  JSON 路径，功能不减。
- **闭环复核**：写入→读取→反馈的逐链状态见审计报告 §13.4。主链已闭；
  飞书服务台、微信客服、MQTT 三条原生接管 producer 已接，质量 metrics 已进管理员
  分析页，ANN 已实测（含 1M 与精确召回对照）并进基础部署依赖，文档命中的检索 token
  已进未归因桶。仍开项只剩：钉钉/Telegram/Discord 等平台没有可接的原生接管事件
  （能力位 False）；未装 hnswlib 的环境自动回退 JSON。
- **验证**：知识/质量/渠道/API 子集 996 项 + 渠道全量 695 项全绿；前端质量契约/
  组合式/i18n/分析页 34 项与 `vue-tsc --noEmit` 通过；live 探针实测接管写入→状态恢复→
  显式 outcome→指标、飞书服务台与微信客服 webhook、索引健康（hnswlib enabled）、
  双 lifespan 事件账持久化全 PASS；ANN 探针 10k/100k/1M 与精确召回对照见上。
  本批收尾改动已提交推送 `92da4050`；最终提交账见审计报告 13.5。

---

## 12. 收口决策票（剩余 producer 与提交）

> 这些已不属于“实现机制缺失”，而是**事件从哪来/口径怎么定/是否加依赖/何时落库**。
> 2026-10-23 用户拍板：**D5 甲、D6 丙、D7 乙、D8 甲、D9 乙、D10 乙**，落地状态见 §11；
> D11 未拍板（工作树未提交）。下表保留选项与代价，作为后续复核依据。

| 票 | 选项 | 代价/影响 | 推荐 |
|---|---|---|---|
| D5 接管生产者 | 甲 控制台 UI + 渠道适配器逐个接（`channel_event`/`console_mark`） | 最准确；每渠道/前端各一次改造 | 甲，分阶段：控制台先接，渠道按能力接 |
| | 乙 只做控制台 UI（`console_mark`） | 通用但漏掉未标记的接管 | 过渡可用 |
| | 丙 只接渠道原生事件 | 覆盖不全，无前端兜底 | 不单独用 |
| | 丁 保持现状（只有 API） | 无 UI/渠道 producer，读数覆盖不足 | 不推荐 |
| D6 tool_failure | 甲 任一工具失败即整轮 tool_failure | 简单，但“工具失败但回答成功”会被误记 | 不推荐 |
| | 乙 仅最终回答失败才记 | 需要产品定义“最终失败” | 可选 |
| | 丙 只接受显式 outcome metadata（管线/工具声明） | 最诚实，需 producer | 推荐先做 |
| | 丁 不做该指标 | 少一维 | 可接受 |
| D7 handoff outcome | 甲 接管会话的所有轮都标 handoff | 会回改历史轮语义 | 不推荐 |
| | 乙 接管事件单列，不改 turn outcome（当前） | 诚实，turn 与接管分账 | 推荐 |
| | 丙 只标接管后的第一轮 | 需要定义“第一轮”边界 | 可选 |
| D8 citation producer | 甲 模型/工具返回结构化 citation ids | 最准确；需改回答协议 | 推荐（长期） |
| | 乙 解析回答里的 `[n]`/来源标记 | 零协议改动，误报/漏报需判据 | 可作过渡 |
| | 丙 用用户纠正/标注反推引用 | 只有反馈样本，覆盖低 | 辅助 |
| | 丁 保持加权/均分 | 当前行为，明确是估计 | 可接受 |
| D9 tokenizer | 甲 继续 jieba/字符估计（当前） | 无依赖；非模型精确 | 可接受 |
| | 乙 有 tokenizer 就用模型 tokenizer，否则估计 | 更准；需资产/依赖政策 | 推荐若允许 |
| | 丙 只认 provider usage，不做检索估计 | 最保守；失去逐条检索成本 | 可选 |
| D10 规模/ANN | 甲 FTS5 持久倒排（当前，1M 查询 578ms/构建 58s） | 无新依赖；构建成本线性 | 推荐先做 |
| | 乙 FTS5 + ANN 可选依赖 | 解向量路；改依赖政策 | 基准证明向量路成瓶颈后再议 |
| | 丙 按 agent/category 再分片 | 降低单分片延迟，增加路由/迁移 | 1M 以上再议 |
| | 丁 外部搜索服务 | 新服务/运维，违背底座约束 | 不选 |
| D11 提交 | 甲 按 8–9 笔单任务单 commit 落库 | 需先做 hunk 归属核对 | 推荐 |
| | 乙 先审 diff 再提交 | 更慢，但可见性最高 | 可选 |
| | 丙 暂不提交 | 继续攒工作树，后续并发风险上升 | 不推荐长期 |

**执行前统一前置**：`scripts/ci/protected_tests.txt` 登记、共享文件 hunk 归属核对、最终 A/B 与 live 证据随提交正文。
