# SAG（SQL-Retrieval Augmented Generation）× Neurova 知识检索对比（2026-11-05）

> **对象（先立证据边界）**：用户投递稿指认 SAG 为「新一代 RAG 开源解决方案」，给三路证据：
> 论文 arXiv:2606.15971（v1 2026-06-14 / v2 2026-08-25，期间一次修订误发为 arXiv:2608.12129
> ——该号 API 实测存在且内容即 SAG v2，abs 页标注撤回）、开源仓 `github.com/Zleap-AI/SAG`（本次克隆 HEAD `e68cdeb`，v1.9.2，2026-10-22）、
> 及一条宣传话术（含「数亿级生产环境验证」「1.6k stars」）。
>
> **本次最重要判定——「开源」要拆开读**：MIT 开源的是**应用壳**（FastAPI 后端 +
> Next.js web + Electron desktop），论文核心（事件-实体索引、SQL JOIN 动态超边、
> 检索扩展算法、抽取提示词）全部封装在闭源 PyPI 包 `zleap-sag==0.15.0` 中
> （`apps/api/pyproject.toml:25`、`uv.lock` source=PyPI，主代理亲验），仓内零源码可见。
> 形态是「pip 可装、黑盒可用、不可审计」——比 KWeaver 主仓全 404 好，比真开源弱。
>
> **文档定位**：研究参考类，仅作背景，**不可作事实源**（`AGENTS.md` §2 原创性与自主性条款）。
> 对方 MIT 不授权任何代码搬运；「对方有 X」只用于**提问**，不用于**规定本仓怎么做**。
>
> **证据分级**：对方侧锚点由一路只读子代理实读（47 次工具调用），主代理亲验五组
> （pyproject pin / uv.lock 来源 / README 数字 / 本仓权重表与 adapter 默认态 / FactSurface
> 消费方 grep，清单见 §8）；本仓侧锚点由一路只读子代理实读（61 次工具调用），主代理
> 亲验三处。**复核轮（2026-11-05 当日）**：主代理对全部承载结论的锚点重验——SAG 仓
> 十组（pin/uv.lock/README 数字/唯一 adapter 宣称/import 清单/策略映射/防线/测试规模/
> 规模宣称 grep/fixture）、GitHub API 两仓实测、本仓六组，并逐字核 v1 表 2；修正三处
> 子代理转述偏差（测试规模 935→1030、SAG-Benchmark commits 4→11、「唯一 adapter」
> 精确化）后重新提交。论文数字取自 v1/v2 全文 HTML 的表格转述，未逐页核对 PDF。

---

## 0. 一页结论

1. **「开源解决方案」打折成立**：应用壳 MIT 开源且工程质量高（后端 125 个测试文件约
   1030 个测试函数，web+desktop 另 109 个；pgvector 真容器 E2E、CI 全 pin SHA）；
   论文核心引擎**闭源**（`zleap-sag==0.15.0`
   wheel，事件-实体 DDL、JOIN 扩展函数体、抽取提示词全部不可见）——其论文数字在仓外
   仅以截图呈现，复现指向外部 `SAG-Benchmark` 仓（55 stars / 11 commits，API 实测）。
2. **技术主张在黑盒层面证实**：chunk→语义事件（1:N）＋多维实体→潜在超边；查询时把
   共享实体当 JOIN keys 动态构图（策略名 `full_expand`/`pruned_expand_rff`/
   `pruned_expand_jev` 在应用侧可见、函数体在 wheel 内不可见）；增量只插自身行、
   无全局重算。「存储事件化、查询图谱化」成立，但算法本体不可审计。
3. **宣传数字逐条对账（§3）**：Recall@2「79.30 vs 68.14、提升 16.4%」「MuSiQue 提升
   29.3%」出自 **v1 表 2 的相对提升换算**（论文原文是绝对 11.1/14.6 个百分点）；
   与现行 v2 已漂移 0.4 点。「数亿级生产环境验证」**论文与仓内双零命中**
   （论文自述 larger-scale deployments 列为 future work）。stars 实测 2.6k（宣传稿 1.6k 过时）。
4. **公道面（对方论文自己承认）**：召回优势伴随明确代价——在线每查询 15.93 s 检索 +
   6.75 s QA、11,536 tokens（HippoRAG 2 为 9.16 s / 4,788），离线索引 28.26M tokens；
   原文「SAG does not yet show a clear end-to-end cost or latency advantage」。
   本仓「本地 ONNX 小模型 + SQLite 单进程自持」取向不容纳该成本模型。
5. **对本仓的最大启示不是引入对方，而是三条「已建成、未生效」面的对标**：图影子路由
   （递归 CTE 2–4 跳，融合权重 0）、事实池召回 `FactSurface.search`（零调用）、
   条目更新不重抽实体关系——SAG 的 SOTA 数字恰好为第一条提供了外部证据
   （共享实体 JOIN 路线在多跳 QA 有效）。另：对方在入库抽取链路有 prompt-injection
   防线，本仓 KB 链路为零（N1 的一个新落点）。
6. **逐维评分（检索子域八维加权，权重归一）**：Neurova **8.3** vs SAG **6.6**
   （SAG 分数为黑盒可用性折扣后读数，§5 有声明）。
7. 候选 C1–C5（**净接线三条 + 新能力两条**，不混批）+ 不采纳三条 + 断点 N3
   （接 KWeaver 对比 N1/N2 序号）。
8. 本文只出报告，**未改任何代码**。未点单前不动码。

---

## 1. 对方体量与形态

| 件 | 状态 | 栈 | 体量 | 许可 | 定位 |
|---|---|---|---|---|---|
| Zleap-AI/SAG | 活跃（v1.9.2，2026-10-22，261 commits，API 实测 2,650 stars/186 forks） | Python 3.11+（FastAPI）+ TS（Next.js 15/React 19/Electron） | 后端 125 测试文件约 1030 测试函数；web+desktop 109 个测试文件 | MIT | **开源应用壳**三端 |
| `zleap-sag==0.15.0` | PyPI wheel（`uv.lock` source=pypi.org） | Python | 源码不可见 | wheel 内未读 | **闭源引擎**：事件-实体索引/JOIN 扩展/抽取提示词/schema |
| Zleap-AI/SAG-Benchmark | 公开（55 stars / 11 commits，API 实测） | Python 脚本 | `main-results.json`/`verify_paper_results.py`/外部五方法复现指南 | MIT | 论文复现仓；**同仓已分层出 SAG2（embedding-free：SQLite FTS5+BM25+JEV）** |

- 应用侧依赖闭源件两个：`zleap-sag==0.15.0`（引擎）、`octx[vectors]==0.1.6`（知识包导入导出）。
  引擎自身再依赖 lancedb/openai/json-repair/aiosqlite（`uv.lock:4181-4197`）。
- **中间件足迹**：关系库 SQLite（默认）→ Postgres/asyncpg（生产 extra）→ MySQL/OceanBase；
  向量 LanceDB（默认）→ pgvector/pg16（生产 compose）→ Elasticsearch；LLM API（论文配置
  Qwen3.6-Flash 抽取/作答）；JEV 独立精排服务（30s 限时）。外部服务十余件——本仓
  `docs/specs/2026-09-20-knowledge-foundation-design.md:11` 明确禁止外部服务，
  这是取向差异，不是本仓短板（与 KWeaver/Semantica 对比同一条裁定）。
- README 宣称「sag/ 是唯一 import zleap-sag 之处」——**全仓 grep 21 个文件直接
  import zleap**（sag/ 适配层内 14 个，适配层**之外另有 7 个**：jobs/tasks、
  generation/llm、services/{chatbot,document,source,octx_gc}_service、
  upgrades/fresh_workspace）。「唯一」是宣传性说法；引擎触点确实以 sag/ 为主体。

## 2. 对方技术拆解（按子系统，标注可见性：仓内可审 / wheel 内不可见 / 论文级）

### 2.1 事件-实体数据模型（列名可还原、DDL 不可见）

- **SourceEvent**：`id/data_source_id/source_id/title/summary/content/category/rank/
  parent_id/chunk_id/start_time/created_time/status`（软删 "DELETED"）——一个 chunk
  关联多个事件（按 rank 取前 N），事件携带 LLM 生成的 title+summary
  （`universe_reader.py:740-754`、`content_reader.py:131-143` 还原）。
- **EventEntity**（关联表）：`event_id/entity_id/weight/description/created_time`；
  **Entity** + 类型契约 **EntityType**（type/name/description/value_format/value_constraints）。
- **向量不进 SQL 列**：LanceDB 四表（`source_chunks` 每 chunk 双向量 heading+content、
  `event_vectors_wide` title_vector+content_vector、`entity_vectors`、
  `event_entity_vectors`）；生产覆盖 pgvector。
- **实体归一/别名/大小写：仓内零代码**（grep alias/merge/canonical 无命中）；
  EventEntity JOIN 依赖精确 `entity_id` 匹配，引擎内部是否做归一不可验证。

### 2.2 抽取（提示词模板不可见，参数与防线可还原）

- per-chunk LLM 抽取 + 结构化输出 JSON Schema 校验（`StructuredOutputMode.JSON_SCHEMA`，
  auto 按模型能力降级）；`ExtractionLimits(max_events_per_chunk=20,
  min_entities_per_event=1, max_entities_per_event=8|20)`；chunk 1000 tokens。
- 应用注入 `guidance_rules`（zh/en：非新闻文档的「事项」扩展定义——观点/事实/定义/
  机制/因果）进引擎提示词。
- **`_UNTRUSTED_DOCUMENT_CONTENT_GUARDS`（`incremental_processor.py:58-78`）**：
  把入库正文当不可信输入加 prompt-injection 防线——对方在抽取链路防注入；
  本仓 KB 入库正文原样进索引与提示词、链路上无任何注入筛查（§7.1）。

### 2.3 查询路径（JOIN 核心不可见）

- 种子选择双通道：事件双向量并行召回（title_vector 1.0 / content_vector 0.95，
  双通道命中 +0.03，相关性下限 `max(0.20, 0.55*top)`，`search_reader.py:491-595`）
  + 应用侧 jieba 词法信号。
- SQL JOIN 扩展：应用侧只见策略映射 `_FACADE_TO_ZLEAP_STRATEGY = {vector→vector,
  multi→full_expand, multi_es_fast→pruned_expand_rff, multi_jev→pruned_expand_jev}`
  （`engine_manager.py:313-318`）；跳数/扩展开销在 wheel 内，**无法代码审计**。
- 重排三层：JEV 外部精排服务（`multi_jev`，30s 限时）→ 应用侧词法融合 + 样板噪声
  过滤（`rerank_sections`/`_is_boilerplate`）→ 生成阶段 LLM 带引用作答。
- 返回物：`RetrievedSection`（chunk_id + **原始 chunk content** + score + 事件回链
  metadata）——证据保持原文形态，事件只作索引与路由。
- 韧性：精确模式超时/失败/空结果回退 vector（`search_reader.py:191-236`）；
  `multi_jev` 不降级（任一源失败整体失败）。

### 2.4 增量更新（对方叙事的最实部分）

- 每文档独立 `input_id` + sha256 摘要 + 幂等键 + fence token（`tasks.py:615-629`）；
  chunk 级断点保存（每 chunk 完成即存）；**无全局重算**——文档完成后仅重建
  「知识宇宙概览」派生聚合视图，不动图数据。
- 删除：`DeleteSourceRequest` 携带幂等回执校验，级联清理文件/应用行/向量，
  回执不匹配即 ConflictError；向量局部自愈（load 阶段被吞的索引失败从权威 chunk 行
  重建缺失向量，非全量重建）。

### 2.5 论文实验与成本（v2）

- 基线 15+：BM25/Contriever、BGE-Large-EN-v1.5/GTE-Qwen2-7B/GritLM-7B/NV-Embed-v2、
  GraphRAG/LightRAG/**HippoRAG 2**/HyperGraphRAG/HyperRAG（无 RAPTOR）。
  结构增强方法统一 BGE-Large-EN-v1.5 做检索器。
- 主表（R@5/F1）：SAG 90.07/72.96，较最强基线 +6.79/+4.33 点；MuSiQue +11.52/+7.01 点
  （README.md:137-138 与论文一致）。R@2（表 4，v2）：SAG 63.62/83.93/91.55（均值 79.70）
  vs HippoRAG 2 49.52/76.55/78.35（均值 **68.14** 精确）。
- **成本表 8**：离线索引 4.57 h / 28.26M tokens；在线每查询 15.93 s 检索 + 6.75 s QA、
  11,536 tokens（Kcand=100）vs GraphRAG 12.79 s/11,438、HippoRAG 2 9.16 s/4,788。
  论文自认无端到端成本/延迟优势；Kcand=50 时 22.68 s/8,236 tokens/60.41 F1。
- **无生产实验**：全部为基准规模（每数据集 1,000 题）；语料增长模拟
  （NQ/MuSiQue 25%→100%，SAG R@5 87.90→82.57）仍为离线基准；
  larger-scale deployments 列为 future work。
- 仓内自测补充：v1.9.0 JEV 段——MuSiQue JEV Recall@10 81.27% vs LLM CoT 82.77%，
  耗时 1.1 s vs 36.8 s，约 $0.00048/次搜索。

## 3. 宣传数字逐条对账（用户投递稿 → 论文 v1/v2 → 判定）

| 宣传稿 | 核实结果 | 判定 |
|---|---|---|
| 「新一代 RAG **开源**解决方案」 | 应用壳 MIT 开源（261 commits/v1.9.2/935 测试）；引擎 `zleap-sag==0.15.0` 闭源 wheel，JOIN 扩展与抽取提示词零源码 | **打折成立**：应用壳开源、引擎闭源 |
| 「存储事件化」 | 论文摘要 + schema 还原（chunk→事件 1:N、事件带 LLM 摘要、潜在超边不拆三元组） | 成立（黑盒层） |
| 「查询图谱化」SQL JOIN 动态构图 | 论文摘要「shared entities as join keys」+ 应用侧四策略映射可见；JOIN 函数体 wheel 内不可审 | 成立（**不可审**） |
| 「增量更新零成本」 | 仓内证实：只插自身行、无全局重算、幂等+fence+chunk 断点 | 成立 |
| 「Recall@2 平均提升 **16.4%**（SAG 79.30 vs HippoRAG 68.14）」 | v1 表 2：SAG 64.1/82.3/91.6（均值 **79.3**）vs HippoRAG 2 49.5/76.6/78.4（均值 ≈68.2）——数字吻合；(79.3−68.2)/68.2≈16.3%。**论文原文表述是绝对「11.1 percentage points」**，16.4% 是相对提升换算 | 数字有出处（v1+换算）；「提升 16.4%」**非论文表述**；v2 已漂移至 79.70/68.14 |
| 「最难数据集 MuSiQue 提升达 **29.3%**」 | v1 MuSiQue R@2 64.1 vs 49.5 = **+29.5% 相对**（论文原文绝对 14.6 点） | 同上：相对换算，非论文表述 |
| 「已在**数亿级**生产环境验证」 | 仓内 grep 亿/million/billion 零命中；论文无生产实验（future work 才提 larger-scale） | **不成立**（无出处） |
| 「GitHub 获 1.6k stars」 | API 实测 2,650 stars / 186 forks | 已过时 |

**对账结论**：数字本身未造假（v1 表 2 可对上），但宣传稿把**绝对百分点换算成相对
提升**来放大（11.1 点→16.4%、14.6 点→29.3%），并**虚构了生产规模验证**。
采用其结论前须以 v2 表 4（R@2 79.70 vs 68.14）与成本表 8 为准。

## 4. 本方基线（本次盘点锚点，不重复展开）

- **「事件化存储」的近亲**：SQLite 权威库 + facts 底座（SPO/validity window/版本/基线/
  用量账）+ `knowledge_subjects` 实体表 + 消解三件套（`knowledge/identity/`）+ 三时间戳
  （source_created/source_modified/入库钟）——治理账比对方厚；缺的是「事件」摘要层
  与实体级向量。
- **召回融合**：`hybrid.py:37` 权重 `{tfidf .30, bm25 .30, vector .25, fts .15, graph 0.0}`
  四路 RRF(k=60) + main_path 精排（weight/local/llm 三 provider）+ 采纳先验重排；
  向量侧挂 JSON 分片（`knowledge_vectors_{uid}.json`），ONNX bge-small-zh-v1.5 本地推理。
- **图能力已建成**：`GraphFactWalker` 递归 CTE 在 facts×subjects 上走 2–4 跳
  （`foundation/graph_walk.py:91-150`）+ adapter `_graphRoute`（`agent/
  knowledge_retriever_adapter.py:84` 默认 `shadow`，`NEUROVA_KB_GRAPH_ROUTE=on` 才融合，
  权重 env 默认 0.10）+ 一跳时效读面 `TemporalFactReader` 分离；无共现统计。
- **事实池召回面零调用**：`FactSurface.search`（`foundation/read_surface.py:73`，含
  180 天半衰期衰减）全仓零调用方——011 实验否证「facts 交织进主召回池」后改为治理富化
  形态（adapter `_enrich`），排序面成为遗留（§7.1 N3）。
- **增量**：指纹去重 + 同源覆盖（旧值进 revisions 账）+ 三级索引各自增量
  （TF-IDF pending ops / 向量指纹增量 / FTS reconcile）；**条目更新不触发实体关系
  重抽**（抽取只在同步导入与手动 backfill 端点），旧 facts 与新正文漂移靠 drift 读数
  被动暴露。
- **KB 链路安全面**：只有 SSRF（`url_guard.py`）；无注入筛查、无脱敏（N1/N2 复确认，
  §7.1）；入库正文原样进索引与提示词。

## 5. 逐维评分（检索子域八维加权，权重归一；分值为本文判断）

**评分含义声明**：SAG 分数 = **黑盒可用性折扣后**的读数——引擎闭源使论文核心算法
不可审计不可复现，其真实能力可能高于可验证读数，本文不推断、不回填。

| # | 维度 | 权重 | Neurova | SAG | 依据（一句话） |
|---|---|---|---|---|---|
| 1 | 索引数据模型 | 15% | **9** | 7 | 本仓 SPO+subjects+版本/血缘/用量账全链在仓可审；对方 schema 只能从应用侧查询代码还原，DDL 在 wheel 内 |
| 2 | 召回与融合 | 15% | 8 | **9** | 对方论文 R@5 90.07（+6.79 点）有 SOTA 证据（截图+复现仓）；本仓四路 RRF+精排扎实但无公开基准证据 |
| 3 | 多跳/图检索 | 15% | 7 | **9** | 对方核心卖点（R@2 +11.1 点，v1 表 2）；本仓递归 CTE 2–4 跳已实现但默认 shadow 权重 0、无共现、一跳时效面分离 |
| 4 | 增量更新 | 10% | 7 | **8** | 对方幂等+fence+chunk 断点+级联回执+只插自身行；本仓指纹/同源覆盖/三级索引增量但 facts 不随更新重抽 |
| 5 | 时效语义/冲突治理 | 10% | **9** | 3 | 本仓 validity window+三时间戳+冲突裁决阶梯+墓碑/擦除喉/血缘链；对方仅 start_time/软删标志，无 validity/冲突概念 |
| 6 | 成本与自持性 | 15% | **9** | 4 | 本仓本地 ONNX+SQLite 单进程零外部服务；对方在线 15.93 s/11,536 tokens 每查询（论文自认无成本优势）+LLM API 依赖 |
| 7 | 工程纪律/测试 | 10% | 8 | 8 | 本仓测:源 1:1+红灯判据；对方 935 测试+pgvector E2E+CI pin SHA（扣：版本号双源、golden fixture 未提交、「唯一 adapter」宣称不实） |
| 8 | 可审计/可复现 | 10% | **9** | 3 | 本仓全仓可审；对方引擎闭源、主表结果仅截图、复现指外部 55-star 仓（11 commits） |

**加权合计：Neurova 8.3 vs SAG 6.6。**

（第 3 维的含义：对方证明的是「共享实体 JOIN 路线」的上限，本仓同构能力已建成、
差的是一次实测与权重决定——这正是候选 C1。）

## 6. 候选清单

**立项纪律**：候选项一律写成本仓自身可核实的断点/缺口；「净接/净删」与「新能力」
两类分开，不混批；未点单不动码。

### 6.1 净接线（本仓断点/缺口，P1）

- **C1 · 图影子路由 benchmark 实测→转正或退役**（SAG 对比的最直接动作项）。
  本仓缺口：`GraphFactWalker` 递归 CTE 2–4 跳 + `_graphRoute` + hybrid graph 权重位
  全部已建成，默认 shadow（权重 0），从未在真实用例上量过收益。SAG 论文的 SOTA 数字
  是「共享实体作 JOIN keys 连接 chunk」路线有效性的外部证据。动作：retrieval_benchmark
  建多跳用例（基线冻结纪律）→ `NEUROVA_KB_GRAPH_ROUTE=on` 对比 shadow → 收益成立则
  调权重转正，不成立则影子路退役（省维护）。影响面：`hybrid.py:37` 权重表、adapter
  env 三处、benchmark 用例库。不可逆点：无（env 门控可回退）。
- **C2 · 同源更新触发增量 facts 重抽**（补齐「增量叙事」里本仓缺的那块）。
  本仓缺口：条目更新（同源覆盖/update_knowledge）不重抽实体关系，旧 facts 与新正文
  漂移只能靠 drift 读数被动发现；手动 backfill 管线已有（`graph_bridge.py:308` 复用）。
  动作：同源覆盖路径挂异步重抽（走 backfill 同管线）+ 异步队列路径补
  `skipped_async` 的补偿抽取。影响面：`repository.py` 覆盖段、ingest 队列、graph_bridge。
  不可逆点：LLM 成本随更新量走，须开关+异步+失败兜底（漂移读数保留）。
- **C3 · KB 抽取链路不可信文档防线**（N1 断点的 KB 落点，与 KWeaver 对比 C1 相邻、
  落点不同——那边是 chat 输入面，这边是摄取面）。对照点：对方
  `_UNTRUSTED_DOCUMENT_CONTENT_GUARDS` 把入库正文当不可信输入进抽取提示词。
  本仓缺口：入库正文原样进索引与提示词，KB 链路无任何注入筛查。动作：抽取提示词
  加不可信内容防线；N1 三件套在 KB 摄取口评估接线（按教义第 7 条先比后合，勿三套并存）。
  影响面：`graph_bridge` 抽取提示词、ingestion 入口、N1 三件套装配位。不可逆点：
  误拦率——阈值可配、默认观察态。

### 6.2 新能力（P2/P3，均需求待拍板）

- **C4 · 双向量索引**（P3）。对照点：对方每 chunk heading_vector+content_vector 并行
  召回（title 1.0/content 0.95），事件层再双向量。本仓现状：单向量（索引输入单源
  `build_index_content`＝标题+context_header+正文合成）。改动面：`vector_index` 分片
  schema、`onnx_embedding` 批量、JSON 分片体积翻倍；bge-small 512 维下存储成本可控。
  收益先实测（本仓索引输入已含标题成分，增益可能小于对方）。
- **C5 · 事件摘要索引增强**（P3，需求先问）。对照点：对方 chunk→事件（LLM 生成
  title+summary）作索引主载体。本仓现状：原文切片直接进索引。代价：LLM per chunk
  （对方离线 28.26M tokens 的量级）；收益：检索命中从「字面重叠」升到「语义事件」。
  需求先拍板：大库场景的检索质量瓶颈是否真实存在，再谈成本。

### 6.3 不采纳登记（取向冲突/无证据）

- **引入 `zleap-sag` 引擎依赖**：闭源 wheel 不可审计（供应链风险+原创性纪律）；
  其能力本仓已有同构实现（facts+CTE 图走查+消解三件套），不引入。
- **ES/MySQL/LanceDB/JEV 精排服务多件套**：与本仓「禁外部服务、单进程自持」取向冲突。
- **「数亿级生产验证」话术**：无论文/仓内证据，不采信（对账见 §3）。

## 7. 断点与教训清单

### 7.1 本仓断点（主代理亲验，2026-11-05）

- **N1/N2 复确认**（接 KWeaver 对比 §6.1）：`cognitive_security.py` 三件套、
  `data_masking.py` 出口脱敏——生产侧仍零消费；且本次确认 **KB 摄取/检索链路**两者
  皆不覆盖（入库正文原样进索引与提示词，链路上无注入筛查）——C3 是 N1 的新落点。
- **N3 · `FactSurface.search` 零调用**（本次新精确化登记）：`FactSurface` 类的 enabled 闸
  已被 adapter 消费（`knowledge_retriever_adapter.py:134-146` 作治理富化开关），
  但**事实池 BM25 召回方法 `search`（`foundation/read_surface.py:73`，含 180 天半衰期
  衰减）全仓零调用方**——011 实验否证「facts 交织进主召回池」后的遗留排序面。
  出路二选一：删除（教义第 6 条）或以「多跳事实种子查询」新形态接线
  （C1 实测时一并裁定，SAG 的种子→JOIN 扩展两段式是其参照形态）。

### 7.2 对方教训清单（供对照自查，不作本仓动作依据）

| 断层/手法 | 锚点 |
|---|---|
| 「开源」叙事：MIT 仓 ≠ 核心开源（引擎闭源 wheel） | `pyproject.toml:25` + uv.lock PyPI source + 仓内零引擎源码 |
| 「唯一 adapter」宣称 vs 7 模块直接 import | README.md:415 vs jobs/tasks、generation/llm、services/*、upgrades/* |
| 「数亿级生产验证」无论文/仓证据 | 仓 grep 零命中 + 论文 future work 自述 |
| 宣传把绝对百分点换算成相对提升放大 | 论文原文「11.1 percentage points」→ 宣传「提升 16.4%」 |
| 版本号双源 + 陈旧注释 | `pyproject.toml:3` 0.1.0 vs 产品 1.9.2；`config_builder.py:1` docstring 写 0.8.2 实 pin 0.15.0 |
| eval 脚本引用的默认 fixture 未提交 | `eval_retrieval.py:521` → `tests/fixtures/golden_queries.yaml` 不在仓 |
| 一次修订误发他号（abs 页标注撤回；该号 API 实测仍存在） | arXiv v2 说明 + arxiv API feed |

## 8. 证据清单与亲验范围

- **克隆**：`git clone --depth 1 https://github.com/Zleap-AI/SAG` →
  `C:/Users/xccoo/.zcode/tmp/sag-analysis/SAG`（未进本仓工作树），HEAD `e68cdeb`
  （2026-10-22，v1.9.2）。
- **论文**：v1/v2 全文 HTML 转述（abs 页 + html 版各一）；v1 表 2 用于宣传对账，
  v2 表 1/4/8 用于现行数字与成本。SAG-Benchmark 仓仅页面级取证（未克隆）。
- **主代理亲验（SAG 侧，首轮＋复核轮）**：①`apps/api/pyproject.toml` zleap pin
  （grep :25/:40）；②uv.lock zleap-sag 段（source=PyPI，:4181-4197）；③README.md:137-138
  性能数字；④README.md:415「唯一 adapter」原文＋全仓 import zleap 清单（21 文件）；
  ⑤`engine_manager.py:313-318` 策略映射原文；⑥`incremental_processor.py` 防线段原文；
  ⑦测试规模复数（`^\s*(async )?def test_` ＝ 1030，递归 125 文件；web+desktop 109）；
  ⑧README 双语 grep 亿/billion/hundreds of millions 零命中；⑨eval_retrieval.py:521
  fixture 默认值＋tests/fixtures/ 实际内容（无 golden_queries.yaml）；⑩GitHub API 两仓
  实测（stars/forks/commits）；⑪arxiv API 2608.12129 原始 feed；⑫v1 表 2 逐字引用
  （SAG 64.1/80.0、82.3/88.0、91.6/96.5、Avg 79.3/88.2；HippoRAG 2 49.5/65.1、76.6/90.4、
  78.4/94.4、Avg 68.2/83.3）。
- **主代理亲验（本仓侧）**：④`hybrid.py:37` 权重表与影子读数机制；⑤adapter:84/:122
  默认 shadow 与权重 env；⑥FactSurface 消费方 grep（neurova/ 与 tests/ 全量）+
  adapter:134-146 引用性质（富化闸，非调 search）。
- **其余锚点**出自两路只读子代理（SAG 仓 47 次工具调用 / 本仓 61 次），未逐行复算；
  行号随双方推进漂移，复核请锁上述 HEAD。
- **未取证项（如实登记）**：`zleap-sag` wheel 内部实现（未拆包；黑盒边界即本次判定
  依据）；SAG-Benchmark 的 `main-results.json` 数值（未下载核对）；JEV 精排模型细节
  （v1.9.0 CHANGELOG 转述）；对方引擎内部是否做实体归一（不可见）；2608.12129 的
  withdrawn 标记仅见 abs 页转述（arxiv API feed 无状态字段，该号实测存在且内容为
  SAG v2）。
