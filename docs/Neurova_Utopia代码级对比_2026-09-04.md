# Neurova vs Utopia（deeplethe/utopia）知识库代码级对比 — 2026-09-04

> 对比对象：[deeplethe/utopia](https://github.com/deeplethe/utopia)（"World's first open-source enterprise world model"，Rust + Postgres + pgvector，Apache-2.0，3.7k★，v0.1，dev 分支 2026-09-04 仍在推送）。
> 定位：与 Neurova 知识库是直接对位关系——主题标签 knowledge-base / rag / graphrag / ontology / bitemporal / agent-memory。
> 方法：Utopia 侧读源码（migrations/0003_graph.sql、0005_resolution.sql、0013/0015/0018/0020/0022、adjudication.rs、audit.rs、retrieval.rs、chunker.rs、utopia-search/lib.rs、19 篇 ADR）；Neurova 侧全量摸底 neurova/knowledge/ 九个模块 + 摄取/检索链路。

---

## 0. 一句话总评

Utopia 的核心主张是：**向量库和知识图谱只管"把现在的知识存对"，而它把"时间"和"本体"放进底座，记录的是"认知变化的全过程"**。它的知识是 append-only 的事实账本（双时间轴），Neurova 的知识是可覆盖的文档条目——这是最根本的哲学差。Neurova 在检索工程上不输（三路 RRF + rerank 双模 + 块级溯源都有），输在**知识治理层**：无版本、无冲突处理、无实体消解、无审计。

---

## 1. 两侧现状速览

| 维度 | Neurova | Utopia |
|---|---|---|
| 存储 | JSON 文件全量加载（`data/knowledge/knowledge.json`），向量 tfidf/ONNX 两套并存 | 单 Postgres（pgvector）+ 内嵌 Tantivy，作业队列是一张表 |
| 检索 | BM25+向量+FTS 三路 RRF（k=60, 0.4/0.4/0.2）+ rerank 双模（model 模式无 provider，占位） | BM25(Tantivy+jieba)+pgvector 两路 RRF；embedding 失败静默降级纯 BM25 |
| 分块 | 段落→句子→硬切，800/120，偏移量存储，块级溯源 | text-splitter 语义分块 1200/150，同偏移量思路 |
| 知识组织 | 扁平条目 category/tags | 本体驱动：entity_types/relation_types + 公理 + 冷启动包（schema.org/FOAF/PROV-O/W3C Org/IOF Core） |
| 图谱 | graph_bridge LLM 抽取写入 KnowledgeGraphManager，**单向只写，检索从不查图** | 图即主存储，检索/对话/数据库挂载全部走图 |
| 时效性 | 仅 created_at/updated_at，update 直接覆盖，delete 物理删除 | **双时态事实账本**：append-only，supersedes 链，永不 DELETE |
| 冲突处理 | 无 | 三类冲突三组出路 + 本体自洽性预检 |
| 实体消解 | 仅 (label,type) 节点复用 | 精确名→embedding→LLM 攒批裁决三段式，合并可精确回滚 |
| 审计 | 无 | 决策台账 append-only，AI 动作 actor=NULL 也记录 |
| 权限 | public/private/shared_with + 三分片索引 + 公开审批 | owner/admin/editor/viewer + KB 级成员制 + 数据源级授权 |

## 2. Utopia 十条可搬的机制（按性价比排序）

### 2.1 双时间轴知识账本（最大差距，P0 启发）
`facts` 表 append-only 永不 DELETE（migrations/0003_graph.sql）：
- **世界轴** `valid_from/valid_to`（这件事在现实中何时成立）+ 每端独立精度列，包括 `unknown`——"结束了但不知道哪天" 和 "仍在持续" 是两种事实，`valid_to IS NULL` 一个值承载不了两个意思；
- **认知轴** `recorded_at/invalidated_at`（系统何时开始相信/何时不再相信）；
- 修正不覆盖：`supersedes UUID REFERENCES facts(id)`，新事实链到旧事实，旧版本闭合 `valid_to` 而不是消失。

Neurova 的 `update_knowledge` 直接覆盖字段（repository.py:624-637）、删除物理删（639-648）——知识被新事实推翻时**什么痕迹都不留**。轻量版启示：给知识条目加 revision 链（supersede 而非 overwrite）+ tombstone 删除，不必上 Postgres，SQLite 一张 revisions 表即可起步。

### 2.2 失败方向设计原则（工程哲学，零成本可搬）
pending_facts 迁移（0018）的原话：把"待确认事实"塞进 `facts` 加标记列，40 多处读 facts 的查询漏一处过滤就有一条没人点头的事实混进图里——**忘了读的后果是"混进去"而非"看不见"**。所以独立成表：分开之后，忘了读它的后果是"待确认队列看不见"，不是"未确认的进了图"。
> 迁移原则：新加的任何标记/状态，问一句"调用方忘了读它，出错方向是什么？"——宁可错误表现为"缺一个可见物"，不可表现为"脏数据静默混入主流"。这条对 Neurova 的 17 维记忆、知识条目、图抽取全部适用。

### 2.3 "说的不是断言的"（0015 ADR / pending_facts）
对话里说"记住 Acme 总部搬到深圳"，助手回"已记录"，图里落的却是一条空谓词 0.9 置信的边——人无从发现。于是交互式单条写入必须进 `pending_facts` 等人点头，确认界面**原句和三元组并排显示**（只列三元组等于要人凭空判断对错），`rejected_facts` 防止拒绝过的被下一轮重抽刷回来。批量摄入不拦（一万条没法逐条确认），走乐观写入+事后审阅。
Neurova 的聊天记忆链路（mem_core）正好缺这个中间态：一次一句、人就在对话里、确认成本最低的那一刻就在眼前。

### 2.4 实体消解三段式 + 裁决缓存（0005 + adjudication.rs）
精确名/别名 → embedding 相似 → 灰区对 LLM 攒批裁决（一次裁 12 对）。三个可白嫖的细节：
- **裁决缓存键与实体 ID 无关**：`sha256(名字小写|类型|top_facts)` 排序后哈希——重传文档不重复付费；
- **高置信（≥0.8）自动执行，低置信转人工，未配模型全部转人工**——裁决任务失败或缺席不影响抽取与查询；
- **合并可精确回滚**：`entity_merges` 记录 moved/invalidated 的事实名单 + 目标画像快照 + 类型快照，撤销按名单原路读回。
Neurova 图谱只有 (label,type) 精确复用，同名实体条目直接重复堆积。缓存键模式可以先用起来（零 LLM 成本的那部分）。

### 2.5 矛盾可见化："矛盾指向上游"（0020）
派生事实撞上断言时不落地（asserted > derived），但**这一步从静默变成可见**：记一条 `derived_contradiction`，left 是被撞的断言、right 是派生的最后一条前提、path 是全部前提。因为人需要知道该去查什么：抽取错了？旧断言该闭合了？还是两个"Mira"其实是一个人？
Neurova 知识更新连冲突检测都没有——新条目进来旧条目既不闭合也不报警。哪怕只做"同一 subject+predicate 出现新值时给旧条目打 superseded 标记 + 进待审列表"，也是从 0 到 1。

### 2.6 本体冷启动包 + 本体增长回路（0003/0008 ADR）
新知识库没有自己的词表——从五个内置本体包起步；包外的术语先计数，人工确认常见者收编入本体。`entities.proposed_type` 记"模型要的东西本体里没有"，`specific_type` 记"模型心里那个更准的词"，且**两列不合用**（合用会让增长回路给每个实体提议建新类）。
Neurova 的 graph_bridge 抽取没有词表契约，label 自由生长。冷启动包（哪怕是 30 条中文常用实体/关系类型）+ 计数收编回路，是图谱质量的地板。

### 2.7 删除是事件，不是减法（0022）
删文档级联掉 chunks/evidence，图里的事实"活着却没了出处"，隐私承诺"事实连同出处保留"直接破产。现在：文档打墓碑 `deleted_at`，只作废"每条出处都已删除"的事实，`document_deletions` 记录这次作废了哪些事实/打标了哪些分块——**撤销、同步复活、同内容重传复活都从名单里原路读回，不多不少**（之前就已作废的不在名单里，不会被误救）。
Neurova 的 `delete_knowledge` 物理删除，连 tombstone 都没有。

### 2.8 决策台账（audit.rs）
append-only，`actor_label` 现场快照用户 email（人被删了台账还认得出是谁），IP/UA 走 task_local 由 HTTP 层统一 scope（25 个调用点不用各带参数），AI 自动动作 actor=NULL 照记，**记录失败绝不影响业务（调用方一律 `let _ =`）**。
Neurova 知识条目无任何变更审计。admin 审批闭环（pending/approved/rejected）已有，差的只是把"谁在何时对什么做了什么"落到一张 append-only 表。

### 2.9 检索工程三个细节
1. **存"当时嵌的是什么"而不是时间戳**（entity_types.embedded_text/embedded_model）：时间戳只答"嵌过没有"，答不了"嵌的还是不是现在这段文字"——描述改了、模型换了，向量就是陈的而时间戳看不出来。Neurova 的 fingerprint（updated_at+长度）是同一思想的弱化版，建议存原文+模型名。
2. **"短查询配短文档"**：类型消解有两种查询形状（短说法/长画像），文档侧就该有两份向量（label_embedding + 全文 embedding）。Utopia 注释自述这条规律栽过四次。Neurova 双向量索引并存但粒度不一致（整条 vs 块级），同源问题。
3. **静默降级是特征**：embedding 未配置/请求失败 → 纯 BM25，warn 一条日志，检索照常。另外 Tantivy 用 **jieba 真分词**，Neurova FTS 是 2-4 字 n-gram 片段（search.py:68-78）——中文检索质量的地板差距，jieba 有现成 Python 包，性价比极高。

### 2.10 ADR 文化 + 迁移注释即设计文档
19 篇决策记录，标题即结论："0009-no-type-is-a-type"（"还没判出来"不是一个类，NULL 没有名字撞不着也忘不掉）、"0010-no-relation-is-no-relation"（related_to 假词表盖住了 acquired/runs_on/sued 的原意）、"0014-identity-from-the-person-scope-from-the-token"、"0017-a-contradiction-points-upstream"。每个 schema 注释都是踩坑复盘（"这条规律本仓库栽过四次"）。
对 Neurova 的直接启示：docs/decisions/ 空缺，而项目里"机制存在但没人消费"的 split-brain（AdaptiveToolWeights、rerank model 模式）正是缺 ADR 评审的症状。

## 3. Neurova 已经领先、不必搬的部分

- **rerank 双模**（加权融合 + 模型重排扩展点）——Utopia 检索链里根本没有 rerank；Neurova 缺的只是给 model 模式接一个真 provider；
- **块级溯源已在检索结果里**（chunk_hits 带块序号+得分）——Utopia 的 citations 是 chat 层做的；
- **三路融合**（BM25+FTS+向量）比 Utopia 两路多一路；
- **知识-记忆联动、17 维情感记忆、MoE 检索隔离**——Utopia 的 agent-memory 还在 Roadmap（"Agent memory over MCP"未做）；
- **可见性模型严格程度相当**（Utopia owner/admin/editor/viewer vs Neurova public/private/shared_with+审批），但 Utopia 的"数据源级授权"（0014/0018 least privilege）值得后续补。

## 4. 建议落地清单（遵守增量约束：先找"机制已存在缺传动轴"，新扩展点默认关）

| 优先级 | 事项 | 现成基础 |
|---|---|---|
| P0 | jieba 真分词替换 FTS n-gram | search.py:68-78 换分词器，idf 覆盖评分框架不动 |
| P0 | 知识条目 revision 链 + tombstone 删除 | update/delete 两处改造，revisions 表一张 |
| P0 | 同值冲突可见化（subject 轻量版：新条目与旧条目相似+矛盾 → 打 superseded 候选 + 待审列表） | 复用现有 pending_submissions 审批 UI |
| P1 | 图谱实体消解：缓存键 + 高置信自动/低置信转人工 | graph_bridge 已有节点复用入口，KnowledgeGraphManager 加 aliases/merged_into |
| P1 | 交互式记忆写入加"待确认"中间态（原句与结构化结果并排） | mem_core 保存链路加一张 pending 表 |
| P2 | 图谱冷启动本体包 + proposed_type 计数收编 | builtin.py / graph_bridge |
| P2 | 知识变更决策台账（append-only，AI 动作照记） | 新表一张，`let _ =` 纪律 |
| P2 | 向量行存 embedded_text+model 替代 fingerprint | vector_index.py:159-168 |
| 观察 | sqlite/faiss 后端接线（config.py 已声明未接线）；multi_kb_router 生产装配 | 声明与实现脱节是债务不是功能 |

## 5. 附：Utopia 值得一读的文件清单

- `migrations/0003_graph.sql` — 双时态 facts 全 schema + 设计注释（本体公理、精度列、哨兵之死）
- `migrations/0005_resolution.sql` + `crates/utopia-server/src/adjudication.rs` — 消解三段式
- `migrations/0018_a_fact_awaiting_a_nod.sql` — 失败方向设计原则的最佳教材
- `migrations/0022_deleting_is_an_event.sql` — 删除事件化
- `docs/decisions/` — 19 篇 ADR
- `crates/utopia-server/src/retrieval.rs` — 全文仅 60 行，降级写法范例
