# 知识库检索准确性与事实守卫升级计划

- **状态**：已实施（B1–B5 五批 + 接线修复全部落地，2026-10-30/31；批次提交、
  偏差归一与 live-verify 补证见 §11 实施台账）。§9 拍板项按建议项执行
  （D1 影子先行 / D2 独立面 / D3 三门槛 / D4 甲案 / D5 确定性规则）。
- **基线日期**：2026-10-29（主干 `295cd0cc`）。
- **输入依据**：
  - 2026-10-29 对知识库检索链路的只读复盘结论（对话记录）；
  - `neurova/knowledge/`、`neurova/agent/knowledge_retriever_adapter.py`、
    `neurova/agent/chat_pipeline.py`、`neurova/agent/post_chat_pipeline.py` 现源码；
  - `docs/specs/2026-10-24-multiformat-kb-upgrade-plan.md`（A4 图谱影子路由、A5 链级 RRF 已落地）；
  - `docs/specs/2026-10-23-knowledge-system-upgrade-design.md`（D6 冲突矩阵、D9 人工回判、D11 评估）。
- 本文是**升级计划，不是实施授权**；每批落地仍按 `AGENTS.md` 先红后绿、A/B 自证、
  live-verify、单任务单提交执行。

---

## 0. 结论摘要

知识库三层权威结构（叙述条目 / 三元组事实 / 图投影）与治理面已闭环；检索是五路 RRF
+ 采纳先验 + 精排。按"事实必须准确、宁可查不出不可答错"的口径衡量，当前有五个实质缺口，
全部集中在**查询侧与生成侧**，底座不用动：

| 编号 | 缺口 | 一句话方案 | 优先级 |
|---|---|---|---|
| W1 | 主体表有别名，检索查询侧不用：用户说黑话/别名时五路混合检索召不回权威条目 | 新增查询侧别名归一（shadow → on），复用 `knowledge_subjects`，不建第二词典 | P1 |
| W2 | 检索脱靶（0 命中）无人登记，别名体系只能靠人工想到才长 | 0 命中登记候选别名 → 人工审批 → 并入主体表，形成写→读→反馈闭环 | P1 |
| W3 | 图谱影子路由已落地（权重 0）但没有"影子 vs 实际排序"的对比读数，转正无判据可依 | 补影子读数 + golden multi-hop 评测量化，按数字门槛转正 | P1 |
| W4 | 同名多口径/未决冲突只在事后裁决账里，检索命中时不暴露，模型默默选一个口径作答 | 命中阶段产出歧义载荷，shadow 先行，on 时注入澄清指引 | P2 |
| W5 | 生成后只有引用句柄防伪（m1/k1），没有"答案中的事实性声明逐条回查证据"的守卫 | 句级确定性回查（数字/日期对事实与命中证据），只标记不重写 | P2 |

落地顺序：B1(W1) → B2(W2) → B3(W3) → B4(W4) → B5(W5)。W1 是 W2 验收闭环与 W4
触发器的前置；W3、W5 相对独立。

---

## 1. 现状锚点（只读复盘证据）

### 1.1 别名"库内有、查询侧无"

- 主体表带别名：`knowledge_subjects.aliases_json`
  （`neurova/knowledge/foundation/knowledge_facts.py:49`），合并语义
  `_mergeAliases`（:508），写入口 `upsertSubject`（:471）。
- 归一消解只服务事实层：`resolveSubjectKey`（:515，规范化 label → 别名表 →
  `merged_into` 链）；图路锚点 `subjectsMentionedIn`
  （`foundation/temporal_facts.py:28`，主体名或别名被查询文本包含）。
- 检索查询侧零展开：全仓无 queryExpansion / alias_expand 类实现；
  `hybrid_search_knowledge`（`neurova/knowledge/hybrid.py:146`）对 `query`
  直接分词打分（jieba 优先、缺席回退 n-gram）。后果：别名只影响事实 walk（默认
  权重 0），条目五路检索对别名查询天然脱靶——别名登记处于"写而不读"状态（断点）。

### 1.2 消歧时机：事后裁决，无事前澄清

- 同词多义：`SubjectResolver`（`identity/subject_resolver.py:41`，auto≥0.92 自动并、
  0.80–0.92 一律 needsHumanReview 宁分勿合）。
- 同主题多口径：冲突账 `knowledge_conflicts` + `KnowledgeConflictJudge`
  （`foundation/conflict_judge.py:24`）——冲突**发生后**裁决。
- 检索命中阶段没有任何歧义信号进入 `RetrievalResult`；模型对"同名多口径"静默取
  top-1，用户无感知（2026-10-23 设计 D9 的人工回判覆盖了治理侧，未覆盖读侧暴露）。

### 1.3 图谱影子有路由、无对比读数

- A4 已落地：`_graphRoute`（`knowledge_retriever_adapter.py:50`，
  `NEUROVA_KB_GRAPH_ROUTE` 默认 shadow）产 `graphRanks/graphSupport`，
  `hybrid.py:320` 仅在 `graphWeight>0` 时计入融合，`hybrid.py:357` 附
  `graph_support`。
- 现有读数：`_recordRetrieval`（`hybrid.py:117`）只记 hits/elapsed/四路计数，
  **不含 graph**；没有"影子候选最终排到第几 / 会不会改变 top-k"的任何记录。
- 2026-10-24 §4.4 的验收（"影子下 recall@k 不降、NDCG 提升才切 on"）因此悬空：
  判据存在，读数不存在。离线评测台架
  `neurova/knowledge/evaluation/retrieval_benchmark.py`（ADR 0016 主锚纪律）已具备
  承载 golden 集的条件。

### 1.4 生成侧只有引用防伪，没有事实回查

- `CitationRegistry`（`chat_pipeline.py:1758`）把条目换成 m1/k1 句柄，防模型伪造
  引用编号；命中条目注入走 `build_context`（:1770）。
- 没有任何环节核对"答案里的数字/日期/关系是否真在命中证据里"。模型凭参数记忆补数
  值时不留痕、不告警。

### 1.5 脱靶查询无登记面

- adapter 0 命中走 `RetrievalQuality.FAILED` 分支
  （`knowledge_retriever_adapter.py:271-279`）后即丢，查询文本只存在于会话日志；
  `retrieval_metrics` 只记 hits=0 计数，没有查询内容与后续处置。别名体系只能靠
  人工"想到才登"，与 W1 组合后本可自生长。

---

## 2. W1 查询侧别名归一

### 2.1 目标 / 非目标

- 目标：查询含主体别名/黑话时，条目五路检索能召回权威条目；匹配到的主体进入
  检索读数与下游（W3 图锚、W4 歧义触发）。
- 非目标：不改打分公式；不改 RRF 权重；不做同义词泛化（那会把"查得准"稀释成
  "查得多"，与事实粒度原则相反）；不动 `resolveSubjectKey` 语义。

### 2.2 方案

新模块 `neurova/knowledge/query_normalization.py`（深模块，小面）：

```python
class SubjectMatch:            # PascalCase 类；字段 camelCase
    subjectKey: str            # 已沿 merged_into 消解到幸存主体
    canonicalLabel: str
    matchedTerm: str           # 命中的别名或规范名原文
    matchedVia: str            # canonical | alias

class NormalizedQuery:
    original: str
    expanded: str              # on 模式下传给 hybrid 的查询
    appendedTerms: List[str]   # 追加的规范名（≤4 个）
    matchedSubjects: List[SubjectMatch]
    changed: bool

def normalizeQueryForRetrieval(
    store,                     # KnowledgeFactStore；duck-typing，测试可注入
    query: str,
    agentId: Optional[str],
    tenantId: str = "default",
) -> NormalizedQuery: ...
def invalidateQueryNormalizationCache() -> None: ...   # W2 审批后调用
```

- **别名映射构建**：一条 SQL 取
  `subject_key, canonical_label, normalized_label, aliases_json, merged_into`
  （agent + tenant 过滤），内存里沿 `merged_into` 链消解到幸存主体（语义与
  `_followMerge` 一致，maxHops 16）。进程内缓存按 `(agentId, tenantId)` 键、TTL
  60 s；`invalidateQueryNormalizationCache()` 供 W2 审批面即时生效。
- **匹配**：查询与候选词（规范名 + 别名）都做 NFKC + 小写归一后做包含匹配，长词
  优先、每词至多命中一次；追加的规范名去重且不得已是查询子串，上限 4 个，
  `expanded` 总长封顶 512 字符（保护 BM25/FTS）。
- **只追加不删改**：`expanded = original + " " + 追加规范名`。原始词永远参与打分，
  归一只提召回，不改写用户意图。
- **fail-soft**：事实库不可用/任何异常 → 返回 `changed=False` 的原查询 + debug 日志，
  检索主路绝不被归一层打死（与 `_graphRoute` 同级纪律）。

### 2.3 接入点

- `KnowledgeRetrieverAdapter.retrieve()`（`knowledge_retriever_adapter.py:172`）：
  在算完 `agent_id`/`tenantId` 之后、调 `hybrid_search_knowledge`（:221）之前归一；
  `on` 传 `norm.expanded`，`shadow/off` 传原文。`norm.matchedSubjects` 原样放进
  `RetrievalResult.metadata["query_normalization"]`。
- v1 只接 chat 主路 adapter；管理端语义搜索 API 是否接入属后续批次（管理面是人工
  操作，不是黑话入口）。
- 图路 `_graphRoute` 维持用原始查询（`subjectsMentionedIn` 已自带别名包含匹配）；
  expanded 喂图锚留作后续观察项，不在本批。

### 2.4 开关与灰度

- `NEUROVA_KB_QUERY_NORMALIZE=off|shadow|on`，**默认 off**。
  - off：逐字不变（A/B 判据同 2026-10-24 的"关闭时逐字不变"）；
  - shadow：只算匹配、只进读数，不改查询；
  - on：追加式展开。
- 默认值翻 on 单独提交，证据 = retrieval_benchmark 台架对照读数（§7 判据）。

### 2.5 判据（先红后绿）

新增 `tests/unit/knowledge/test_querySideNormalization.py`，红灯用例：

1. 别名独有查询（规范词不在正文中）在 off 下 0 命中、on 下命中权威条目；
2. shadow 不改变返回列表（逐项 deep equal），metadata 含 matchedSubjects；
3. 规范词查询 off/on 返回一致（不因追加而劣化排序，top-1 不变）；
4. merged_into 链上的旧别名命中后 subjectKey 指向幸存主体；
5. 事实库抛异常时返回原查询、检索不抛；
6. 追加词上限 4、总长上限 512；
7. 缓存 TTL 过期前不重查库（注入计数器验证），invalidate 后立即重查。

---

## 3. W2 检索脱靶登记与审批闭环

### 3.1 目标 / 非目标

- 目标：0 命中的非平凡查询被登记为候选别名；人工审批通过后并入主体表，下一次同类
  查询经 W1 命中——形成"写入 → 读取 → 反馈 → 再写入"闭环（协作红线断点条款）。
- 非目标：不自动合并、不自动建主体（SkillGLoW P1-3 同款纪律：机器只产候选，人拍板）；
  不登记低命中（<阈值）查询，v1 只收 0 命中，避免队列被噪声灌满。

### 3.2 数据：`knowledge_alias_candidates`（底座 schema 顺延新版）

- 迁移注册在 `foundation/foundation_schema.py`（:44 起的版本域，实施时以现值顺延），
  走 `core/db_migration.py` 注册表，不写裸 `IF NOT EXISTS`。

```sql
CREATE TABLE knowledge_alias_candidates (
  candidate_id     TEXT PRIMARY KEY,
  agent_id         TEXT NOT NULL,
  tenant_id        TEXT NOT NULL DEFAULT 'default',
  raw_query        TEXT NOT NULL,
  normalized_query TEXT NOT NULL,
  proposed_subject_key TEXT,            -- 捕获时 resolveSubjectKey 的命中提示，可空
  evidence         TEXT NOT NULL DEFAULT '{}',  -- json：捕获来源、当次 hits 等
  status           TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|superseded
  occurrences      INTEGER NOT NULL DEFAULT 1,
  first_seen_at    TEXT NOT NULL,
  last_seen_at     TEXT NOT NULL,
  decided_by       TEXT,
  decided_at       TEXT,
  decide_reason    TEXT
);
CREATE UNIQUE INDEX ux_alias_candidate_query
  ON knowledge_alias_candidates(agent_id, tenant_id, normalized_query, status);
```

- 重复脱靶：`occurrences+1`、`last_seen_at` 刷新，不新增行（防灌水）。
- 生命周期：approved/rejected 后同查询再脱靶则新起 pending 行（旧行保留作审计）。

### 3.3 捕获点与审批面

- 捕获在 adapter 0 命中分支（`knowledge_retriever_adapter.py:271`）：
  非平凡过滤（去空白后长度≥2 且含字母/CJK）→ `captureAliasCandidate(...)` →
  若 `resolveSubjectKey` 命中则填 `proposed_subject_key` 提示审批人。捕获失败只
  debug 日志，绝不影响检索返回。开关 `NEUROVA_KB_MISS_CAPTURE=off|on`，默认 off。
- 审批 API 挂现有 `/api/v1/knowledge` 命名空间（端点落 `knowledge_core.py` 同级，
  权限/租户过滤沿既有知识管理面模式）：
  - `GET  /api/v1/knowledge/alias-candidates?status=&agent_id=`（分页列表）
  - `POST /api/v1/knowledge/alias-candidates/{id}/approve`，body `{"subject_key": ...}`
    → 事实库新方法 `attachAlias(agentId, subjectKey, alias, tenantId, operator,
    reason)`：校验主体存在且未 merged，`_mergeAliases` 合并，activity 留痕
    （操作人/动作/依据，同 2026-10-24 S2 模式），随后
    `invalidateQueryNormalizationCache()`；
  - `POST /api/v1/knowledge/alias-candidates/{id}/reject`，body `{"reason": ...}`。
- **实施核对项（教义第 7 条）**：实体消解已有人工回判面
  （`identity/subject_resolver.py` 的 needsHumanReview 队列 + repository 人工 review）。
  实施首日先比对其队列形态能否原样承载本表（同 API 形态/同回判入口）；能承载则并入、
  不并存两套回判面；不能承载（其行由 Resolver 运行派生、无外部写入契约）才用本表，
  并在提交说明里附比对结论。
- 权限：管理面既有 pattern；查询文本属用户输入，租户隔离在 SQL 层强制，审批留
  `decided_by`。

### 3.4 判据

新增 `tests/unit/knowledge/test_aliasCandidateCapture.py` +
`tests/unit/api/test_aliasCandidateEndpoints.py`（红灯用例）：

1. 0 命中 + 开关 on → 落一行 pending；同一查询再脱靶 occurrences+1 不加行；
2. 平凡查询（空/纯符号/单字符）不落行；开关 off 完全不落；
3. W1 shadow 命中主体的查询不落行（归一已知的不算脱靶）；
4. approve → 主体表别名生效 → 同查询重检索命中（闭环判据，与 W1 联测）→
   归一缓存已失效（下次检索立刻命中，不等 TTL）；
5. reject → 无别名变更，activity 有痕；
6. 跨租户同查询互不可见、互不合并；
7. 未授权调用审批端点 4xx（沿知识管理面现有鉴权契约）。

---

## 4. W3 图谱影子读数与转正判据

### 4.1 与既有计划的关系

2026-10-24 §4 两阶段融合（A4 影子路由、A5 `fuseRetrievalResults` 链级 RRF）
**已落地，本文不重做**。本文补的是它 §4.4 验收悬空的部分：影子读数与转正决策程序。

### 4.2 方案

1. **运行时影子读数**（扩展现有单源，不新造账）：
   - `_recordRetrieval`（`hybrid.py:117`）的 route_counts 增补 `graph` 路；
   - `get_retrieval_metrics().record(...)`（`neurova/knowledge/retrieval_metrics.py:85`）
     增可选 `graphShadow` 载荷：`{"candidates": N, "top_candidate_final_rank": int|None,
     "overlap_at_k": int}`——shadow 模式且 `graphRanks` 非空时由 wrapper 从返回行算出
     （graph 候选在最终列表中的名次/是否进 top-k）。指标快照端点
     `knowledge_core.py:682` 顺带透出。
   - on/shadow 关闭（`NEUROVA_KB_GRAPH_ROUTE=off`）时零开销、读数缺省。
2. **离线 golden 评测**（挂 `evaluation/retrieval_benchmark.py`，守 ADR 0016 主锚
   纪律，读数取不到即 unevidenced）：
   - 新增 multi-hop golden fixture（小语料 + 若干必须走关系才能命中的查询 +
     期望条目集），同一语料分别在 `NEUROVA_KB_GRAPH_ROUTE=off` 与 `=on` 下跑
     `hybrid_search_knowledge`，产出 recall@k / NDCG@k 对照；
   - 读数进台架既有报告形态，不另起第二份评测出口。

### 4.3 转正判据（数字门槛，满足才改默认值）

- golden 集：`on` 相对 `off`，recall@10 不降（绝对值 ≥ −0.00）且 NDCG@10 提升
  ≥ 0.05；
- 影子期真实流量（≥ 200 次含 graph 候选的检索）：graph 首候选进入最终 top-5 的
  回合占比 ≥ 10%，且这些回合的采纳 success 率不低于同期全量基线；
- 跨租户图谱命中为 0（A0 已钉，转正前复验一次）。
- 三条全满足 → 单独提交把 `NEUROVA_KB_GRAPH_ROUTE` 部署默认改为 on（代码默认仍
  shadow，灰度由部署配置执行——与 2026-10-24 Kreuzberg 切主路同款收口方式）；
  任一条不满足 → 继续 shadow 并按失败登记（本体缺口补登记 / 权重调参 / 词典登记）。

### 4.4 判据

新增 `tests/unit/knowledge/test_graphShadowReadings.py` +
`test_goldenMultiHopGraphRoute.py`（红灯用例）：

1. shadow 且有候选 → graphShadow 读数存在、返回列表与 off 逐字一致；
2. off / 无候选 → 读数缺省、零额外开销（不触 walker）；
3. route_counts 在 on 模式含 graph；
4. golden multi-hop：off 下不命中、on 下命中且带 `graph_support`；
5. NDCG/recall 计算对同一 fixture 可复现（给定输入唯一输出）。

---

## 5. W4 同名多口径主动澄清

### 5.1 定位

2026-10-23 设计的 P1-A 冲突矩阵（D6）是**写侧**检测/裁决；本文是**读侧**暴露——
消费既有冲突账与消解产物，不另起冲突源（教义第 6 条）。触发器全部来自已有账：

- `multi_subject`：同一匹配词（W1 的 matchedSubjects 或查询原文）消解出 ≥2 个
  幸存主体；
- `open_conflict`：命中主体在 `knowledge_conflicts` 有未决行（判定复用
  `ConflictJudge` 产物/冲突账查询，不重算）。

### 5.2 方案

- 计算点：adapter `_enrich` 之后（已有 lineage 与命中列表）：
  `buildAmbiguityBlock(store, matchedSubjects, hits, agentId, tenantId)` →
  `RetrievalResult.metadata["ambiguity"]`：

```json
{
  "source": "multi_subject | open_conflict",
  "term": "用户查询中的歧义词",
  "candidates": [
    {"subject_key": "...", "canonical_label": "...",
     "caliber_hint": ["口径提示（取该主体事实的 qualifier 去重前 3，或缺省时取
                       命中条目标题）"], "entry_ids": ["..."]}
  ]
}
```

- 三档开关 `NEUROVA_KB_AMBIGUITY_CLARIFY=off|shadow|on`，默认 off：
  - shadow：只写 metadata（API 消费方/前端可读，行为零变化）；
  - on：`chat_pipeline` 组装知识上下文块时（:1770 一带）在块首加一段受控指引
    （模型面向，非用户文案，不涉 11 语言契约）：
    `[检索歧义]「X」在知识库中有 N 个口径：…；用户意图不明时先澄清再作答，不得静默择一。`
  - off：metadata 键不存在，逐字不变。
- 前端结构化澄清卡（NeurUI 聊天组件 + i18n 11 语言）是独立前端批次，见拍板项 D4。

### 5.3 判据

新增 `tests/unit/knowledge/test_ambiguityClarification.py`（红灯用例）：

1. 两主体共享同标签 → multi_subject 载荷含两个 candidate，caliber_hint 非空或显式缺省；
2. 命中主体有未决冲突 → open_conflict 载荷；
3. 单主体无冲突 → 无 ambiguity 键；
4. off 时返回逐字等于现状（含 metadata 键集合）；
5. shadow 不改注入上下文内容；on 时上下文块含指引且引用句柄（m1/k1）不变；
6. caliber_hint 只取证据字段，不调用 LLM、不猜。

---

## 6. W5 生成后事实回查守卫

### 6.1 目标 / 非目标

- 目标：本回合有事实血缘命中时，对草稿答案做句级回查——答案里的数字/日期性声明
  是否能在命中证据（事实 object 值、命中条目 context_passages）中核到；
  核不到的**诚实暴露**（教义第 2 条），不静默、不自动改写。
- 非目标：不做全文事实核对（成本不可控）；不动 `CitationRegistry`；v1 不引入
  额外 LLM 调用（LLM 抽取断言见拍板项 D5）；不阻断消息发送。

### 6.2 方案

- 新模块 `neurova/knowledge/guards/answer_fact_guard.py`：
  `runAnswerFactGuard(draft, hits, store, agentId, tenantId) -> GuardReport`
  （`{checked, supported, contradicted: [{sentence, claim, evidenceStatus}],
  unverified, mode}`）。
- 范围限定：仅当本回合 `lineage_ids` 非空；仅检查包含命中主体规范名/别名的句子；
  断言抽取 v1 为确定性规则（数字/百分比/日期正则），零新依赖（可选依赖纪律）。
- 判定从保守：`contradicted` 仅当同主体同谓词存在数值不同的事实**且**该值不出现在
  任何命中证据文本中；其余归 `unverified`。宁可少报，不可误伤。
- 接线（**实施终态**，与原稿不同——原稿写 post_chat_pipeline，实施钉在回复
  定稿上游，理由见 §11.2）：`chat_pipeline.py` 的 `_applyAnswerFactGuard`
  在 Step 3.5（LLM 调用之后、后处理落盘之前）执行，flag 门控 + 懒 import：
  - 开关 `NEUROVA_KB_ANSWER_FACT_GUARD=off|shadow|on`，默认 off；
  - shadow：报告进回合 metadata/读数，消息零变化；
  - on：在消息末尾追加一行可见核验注记，列出不符声明（"核验注记：以下数值
    未在知识库证据中核到：…"）——以诚实形态暴露，不重写答案。
- 成本：零额外 LLM token；纯 SQLite/文本比对，预算在 post-chat 现有同步段内。

### 6.3 判据

新增 `tests/unit/knowledge/test_answerFactGuard.py`（红灯用例）：

1. 答案数值与同主体同谓词事实值不同且证据中无此值 → contradicted；
2. 答案数值与证据一致 → supported；
3. 无血缘回合 → 整个守卫跳过（不产生读数、不触碰消息）；
4. shadow 消息逐字不变；on 消息仅追加注记行、原句不改写；
5. 事实库异常 → 守卫静默让路（debug 日志），消息照发；
6. 无数字/日期的句子不进 checked。

---

## 7. 分批计划与总判据

| 批 | 内容 | 主要落点 | 前置 |
|---|---|---|---|
| B1 | W1 归一模块 + adapter 接线 + shadow 读数 | `query_normalization.py`、`knowledge_retriever_adapter.py`、`retrieval_metrics.py` | 无 |
| B2 | W2 脱靶登记 + 审批 API + 闭环联测 | `knowledge_facts.py`（attachAlias）、schema 新版、`knowledge_core.py` 同级端点 | B1 |
| B3 | W3 影子读数 + golden 评测 + 转正决策程序 | `hybrid.py`、`retrieval_metrics.py`、`retrieval_benchmark.py` | 无（可并行） |
| B4 | W4 歧义载荷 + 上下文指引 | adapter、`chat_pipeline.py` | B1 |
| B5 | W5 事实守卫 | `guards/answer_fact_guard.py`、`post_chat_pipeline.py` | 无（可并行） |

每批固定动作：

- 红灯先行：§2.5/§3.4/§4.4/§5.3/§6.3 用例先实证红，再最小实现转绿；
  红灯文件转绿前不进 `scripts/ci/protected_tests.txt`。
- A/B 自证：`hybrid.py`、`knowledge_retriever_adapter.py`、`chat_pipeline.py`、
  `post_chat_pipeline.py` 属共享文件，提交前
  `git stash push <files> && pytest <套件> && git stash pop`，失败集合逐行比对
  （预存失败按既有基线，新增失败才算回归）。
- live-verify：后端起 9527 真链路——登记一条带别名的知识 → `POST /v1/chat/stream`
  用别名提问 → off/shadow/on 三态对照捕获检索读数与答案引用；W2 再走一遍
  审批 API 后复测命中。证据（命令+输出原文）进提交说明。
- 净 LOC 按教义第 2 条逐条列去向；测试代码不计入。

---

## 8. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| 展开污染排序（追加词拉偏 top-1） | 只追加、上限 4 词、长度封顶、shadow 先行 | env 切 off，逐字回原 |
| 脱靶登记被噪声灌满 | 0 命中才收、平凡查询过滤、occurrences 去重、默认 off | env 切 off；队列存量保留待清理 |
| 影子读数误读（graph 候选天然偏短文） | 转正看三条数字门槛，不凭单点读数 | 默认值不动，继续 shadow |
| 歧义暴露打扰用户 | 触发器保守（≥2 主体或未决冲突）、shadow 先行 | env 切 off/shadow |
| 守卫误报打脸正确答案 | contradicted 判据从保守、shadow 先行、只注记不改写 | env 切 off/shadow |
| 事实库故障拖累检索 | 全部 fail-soft（debug 日志），主路上抛语义不变 | — |

---

## 9. 拍板项

| 编号 | 问题 | 选项与影响面 | 建议 |
|---|---|---|---|
| D1 | W1 默认值路径 | (a) off→影子攒读数→翻 on（多一次发布周期，风险最低）；(b) 直接 on（立即受益，排序变化无对照基线） | (a)；影子期读数同时是 W3/W4 的输入 |
| D2 | W2 审批面归属 | (a) 并入实体消解现有人工回判面（少一套入口，需扩其写入契约）；(b) 独立表 + 独立端点（本文 §3.3 形态，实现直接）；影响面：resolution 人工 review 契约 / knowledge 管理端点 | 实施首日按 §3.3 核对项比对后定；形态不匹配则 (b) |
| D3 | W3 转正门槛数字 | §4.3 三条（recall 不降 / NDCG +0.05 / top-5 覆盖 ≥10%）；影响面：graph 默认权重与部署配置 | 认可三门槛；流量不足 200 次时以 golden 集读数为准顺延决策 |
| D4 | W4 澄清 UX 形态 | (a) 仅后端上下文指引（模型代问，无前端改动）；(b) 结构化澄清卡（NeurUI 聊天组件 + 11 语言 + 交互契约，独立前端批次）；影响面：前端触点与 i18n 面翻倍 | 先 (a) 验证价值，(b) 另立前端批 |
| D5 | W5 是否引入 LLM 抽取断言 | 确定性规则（零 token，覆盖数字/日期）vs LLM 抽取（覆盖关系性声明，每回合增 token）；影响面：post-chat 延迟与成本 | 先确定性规则；LLM 版等 shadow 读数显示 unverified 占比显著再立项 |

---

## 10. 明确不做的事

- 不建第二份同义词/黑话词典（别名唯一事实源在 `knowledge_subjects`）；
- 不自动合并别名候选、不自动建主体；
- 不在本文改 RRF 权重与融合公式（归 2026-10-24 §4 的既有两阶段）；
- 不重写冲突裁决（读侧只消费冲突账）；
- 不做全文事实核对、不让守卫改写答案；
- 不在 off 档引入任何行为或读数开销。

---

## 11. 实施状态与 live-verify 台账（2026-10-31）

### 11.1 批次与提交

| 批 | 提交 | 内容 | 判据 |
|---|---|---|---|
| B1/W1 | `dc2b24b5` | 查询侧别名归一（`query_normalization` + adapter 接线 + 归一读数） | 9 用例 |
| B2/W2 | `9322b49a` | 脱靶登记与审批闭环（底座 v27 + store 四方法 + 三端点） | 22 用例 |
| B3/W3 | `a1c1f5f1` | 影子读数（graphShadow 四计数）+ golden 多跳评测 | 7 用例 |
| 接线修复 | `d4518d0a` | 检索上下文统一带 agent 域——W1/W2 在聊天主路原是休眠态、图锚跨 agent 挑起点 | 3 用例 |
| B4/W4 | `23e8b7d3` | 同名多口径读侧暴露（`ambiguity_clarification` + 链透传/渲染接线） | 9 用例 |
| B5/W5 | `848e013e` | 生成后事实回查守卫（`guards/answer_fact_guard` + Step 3.5 接线） | 8 用例 |
| 守卫收口 | `2dc05196` | 八档判据入受保护子集（逐文件单跑两轮读数相同） | 58 用例 |
| 遗留收口 | `21e2c755` | legacy 流式装配点接回单源错误分类器（验收中发现的预存雷，连带转绿 12 例预存红） | — |

受保护子集 8 文件单跑复现（2026-10-31）：9/15/7/3/5/2/9/8，共 58 passed 全绿；
全套件 1165 passed、2 failed 均判预存（redundancy 1==2 用例、`_raise_for_llm_error_dict`
悬空引用——后者已由 `21e2c755` 根修，修复后 agent 套件 15 failed/1600 passed，
无改动对照 27 failed，差集恰为修复的 12 例）。

### 11.2 与原稿的偏差（均已在对应提交说明给据）

1. **W5 接线点**：原稿写 post_chat_pipeline 后置步骤，实施钉在 `chat_pipeline.py`
   Step 3.5（回复定稿之前）——post 处理第一步就落盘 reply，事后追加注记会让会话盘
   与返回体各说各话（`848e013e` 提交说明）。本文 §6.2 已按实施终态改写。
2. **W5 开关名**：实现定名 `NEUROVA_KB_ANSWER_FACT_GUARD`（原稿未定名）。
3. **W2 审批面归属（拍板项 D2）**：实施核对结论=消解的 needsHumanReview 只在决策
   对象与 admission 校验里流转，无可承载外部行的人工回判队列——按预案落独立表 +
   独立端点（`9322b49a` 提交说明附比对结论）。
4. **路由快照守护顺手收口**：`test_knowledge_route_order` 的 `_KB_ROUTES` 快照停在
   拆分时 34 条，10-24 批次的 `/ontology/* /mcp/sources* /geo` 等 16 条一直未登记
   （守护带病漂红）——随 B2 收口到实测 84 条。

### 11.3 live-verify 补证（2026-10-31）

`tests/manual/liveVerify_kbW1W2W4.py`（可复跑：`PYTHONPATH=$(git rev-parse --show-toplevel)
.venv/Scripts/python.exe tests/manual/liveVerify_kbW1W2W4.py`；数据根
`isolatedDataRoot()` 单点，`X-Service-Token` 走真管理员通道，真 `create_app()`/
lifespan + 真默认 agent + 真 `ChatPipeline._step_retrieve_and_build_context`）全绿，
补齐 B1/B2/W4 三批此前缺记录的 live 证据（B3/W5 的 live 段见各自提交说明）：

- **W2**：空库真检索脱靶（hits=0）→ 候选捕获 pending（raw_query="跑量"）→
  `POST /knowledge/alias-candidates/{id}/approve` 200 且别名挂上（activity 留痕）→
  复测命中；`/reject` 200 只结行，pending 不含被拒行。
- **W1**：同一查询"跑量"复测 hybrid hits=6、归一读数 `with_matches=1`——别名驱动
  召回在真链生效（条目 knowledge_id 出现在 `ctx.relevant_memories`）。
- **W4**：同名多口径（"跑量"=甲主体别名+乙主体本名，两主体均经真咽喉建边）→
  `multi_subject` 歧义载荷两候选；on 档真 `build_context` 收到受控指引：
  `[检索歧义]「跑量」在知识库中有 2 个口径：客户流失率；跑量；用户意图不明时先澄清再作答，不得静默择一。`
- 探针不证 LLM 生成段（需真模型凭据，与本升级判据无关）与 SSE 传输层
  （与 batch D / W5 探针同形）。

### 11.4 实施中发现的新登记项（不在本升级范围，待立项）

**链采纳门使小语料/低命中回合的知识结果整包被弃。** `MemoryRetrievalChain` 的
采纳条件是 `quality ≥ min_quality(0.3)`，而知识路质量 =
`0.6×命中数/10 + 0.4×词面重合`（`get_quality_score`）——命中 1 条 = 0.06 < 0.3，
被当"不足"整包丢弃，MoE 的 `no_memory` 占位（score=1.0）反而成为主结果。探针实测：
1 条命中时 `ctx.relevant_memories` 只有占位（无知识条目、无歧义载荷）；凑到 6 条
命中（quality 0.36）后知识补入与 W4 载荷才出现。且 quality 打分用原始查询——
W1 展开追加的规范词不计入词面重合，别名驱动的命中被双重折损。影响面：新建
agent 的知识库冷启动期，W1/W4 的用户可见效果被链门挡住（捕获/审批/读数不受影响）。

**销项（2026-10-31，`ee7118ad`）**：根修为三件套——重合按**实跑查询**
（`searchQuery`，含 W1 展开词）计；分词与 bm25 同源走 `tokenize`（CJK 可分词，
旧实现按空格切词，中文重合结构性恒零、relevance 通道对中文是死重）；计数通道
与词面重合通道**取大**替代加和一票否决（重合通道 0.75×重合，≥0.4 即独立过门）。
边界两侧不变：空结果 0、满载 1.0、无重合多命中走计数通道、不相关单命中仍被拒。
`UnifiedRetrieverAdapter` 的同型公式**不动**并登记理由：记忆路无展开机制（同一
触发条件不成立）、其占位 hint 是刻意设计、无缺陷证据——无据不改最热路径。
判据 `tests/unit/agent/test_knowledgeQualityGate.py`（6 用例，已入受保护子集
`8f3b7ab5`）；活体探针降到 1 条条目后全绿，6 条凑数的旧绕法作废。
