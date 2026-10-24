# 多格式文档知识库升级计划（对照 2026-10 设计文档）

> 对照来源：`F:\User Files\xwechat_files\shangdu_ab02\msg\file\2026-10\多格式文档处理与知识库构建系统.md`
> 基线：本仓 2026-10-24 `a5455024` 之后的实现（doc pipeline / WeCom / hybrid / Supervisor / tenant / eval）。
> 本文是**升级计划**，不是实施授权；落地仍按 `AGENTS.md` 的先红后绿、A/B、live-verify、单任务单提交。

## 1. 结论

目标文档的 5 层（接入、处理、加工、存储、检索）在本仓已有实现骨架，但存在 4 个实质缺口：

1. **图谱/时效读面还没有 tenant 过滤**：`subjectsMentionedIn`、`GraphFactWalker` 只按 agent 约束，v23 之后主体已按租户分区，图检索仍可能跨租户命中。这是图谱并入混合检索前必须先修的 P0。
2. **条目级重复内容没有去重**：清洗/页眉去重已有，但相同正文重复导入会各建条目；入站只按 `source` 幂等。
3. **OCR 只有 RapidOCR 一条实现**，PaddleOCR/Tesseract 未做 provider；元数据过滤只覆盖 category/tags/source/时间。
4. **图谱检索是独立责任链分支**，与 `hybrid_search_knowledge` 的条目四路 RRF 不是同一套融合；直接塞入会破坏返回契约。

图谱并入混合检索**可以做**，建议分两阶段：先把图谱事实映射成条目级证据并作为影子路由接入现有 RRF；再把 knowledge/graph/memory/structured 提到链级统一 RRF。直接在图谱分支和知识 hybrid 各调各的，会留下第二套排序口径。

## 2. 当前实现盘点

| 目标层 | 目标文档要求 | 当前实现 | 状态 |
|---|---|---|---|
| 数据接入 | 本地上传、多格式、外部信源 | `/knowledge/import`、`/import-url`、企微入站、持久队列 | 已覆盖 |
| 格式分流 | PDF/Word/Excel/PPT/图片/扫描/MD/JSON | `document_pipeline.parse_document`：docx/xlsx/pptx/pdf/图片/MD/JSON/HTML/CSV/RTF/ODF；`.doc/.ppt/.xls` 走 LibreOffice | 已覆盖，旧格式依赖 LibreOffice |
| OCR | PaddleOCR/RapidOCR/Tesseract | `RapidOcrEngine`，按页渲染 + 置信度 | 部分；只有 RapidOCR |
| 标准化输出 | 标题/类型/处理时间/正文/来源 | `ParsedDocument` + `pages/chunks/parents` + `metadata`（author/page/ocr） | 已覆盖 |
| 清洗 | 噪声、段落、编码、重复 | NFKC、控制字符、页眉/页脚/页码、空行折叠、按页分块 | 部分；无条目级内容去重 |
| 向量化 | 分块 + 语义索引 | `splitter` + tfidf/vector/hnswlib；FTS5/BM25 | 已覆盖；无 Milvus/FAISS 外接 |
| 元数据 | 溯源与检索过滤 | tenant/visibility/category/tags/source/时间；author/source_type/page/ocr 字段已存 | 部分；过滤参数未暴露 |
| RAG | 语义/混合/多 Agent | `hybrid_search_knowledge` 四路 RRF、精排、Supervisor；图谱为独立 Retriever | 部分；无图谱融合 |
| MQTT | Agent 间通信/分布式 | 入站队列 + 可选 MQTT；Supervisor MQTT 可选 | 已覆盖（可选依赖） |
| GIS | 预留地理信息检索 | 无 | 未覆盖 |

## 3. 差距矩阵

| 编号 | 差距 | 证据 | 优先级 |
|---|---|---|---|
| G0 | 图谱/时效读面缺 tenant 过滤 | `subjectsMentionedIn` 与 `GraphFactWalker` 只拼 agent 条件；v23 主体已带 tenant | P0 |
| G1 | 条目级重复内容不去重 | `create_knowledge` 无内容指纹；入站仅 `findBySource` | P1 |
| G2 | OCR provider 单一 | 只有 `RapidOcrEngine`；无 Paddle/Tesseract 可选实现 | P1 |
| G3 | 元数据过滤面窄 | `visible_items/hybrid` 只接 category/tags/source/updated_after | P1 |
| G4 | 图谱未进混合检索 | `hybrid.py` 四路只返回条目；`GraphRetrieverAdapter` 独立分支 | P1 |
| G5 | 链级融合是“选最佳结果” | `MemoryRetrievalChain._retrieve_parallel` 用 `max(quality)`，不是 RRF | P1 |
| G6 | GIS 未预留 | 无 geo 字段/过滤/索引 | P2 |
| G7 | Kreuzberg 未采用 | 当前自建流水线；目标文档列为统一框架 | P2（评估，不强制） |
| G8 | 10M 存储迁移未实施 | FTS 10M p95 2.9s，已判 `migrate_or_shard` | 独立项目 |
| G9 | Docker 真构建未验 | 本机无 docker；CNB 触发缺 `repo-cnb-trigger:rw` | 独立环境 |

## 4. 图谱并入混合检索：设计

### 4.1 为什么不能直接加第五路

目前两套对象不同：

- `hybrid_search_knowledge`：输入条目，输出**条目 dict**（`knowledge_id`、`chunks`、`confidence_breakdown`），四路 RRF。
- `GraphRetrieverAdapter`：输入查询，输出**事实 hop**（`fact_id`、`path`、`hops`），走责任链 `priority=27`。
- `MemoryRetrievalChain`：并行跑所有 retriever 后按 `quality` 选一个，不是融合。

若把 `fact_id` 直接塞进现有 RRF，会出现：ID 命名空间混用、图谱命中无法映射回条目、引用/注入账落错对象、纯事实无 `content` 字段导致下游上下文拼装失败。因此需要显式的证据契约与两阶段融合。

### 4.2 推荐两阶段

**阶段 A（短期，低风险）：条目级图谱证据路由**

1. 图谱 hop 只作为“某条目被关系支持”的证据：沿 `source_turn_id` 的 `entry:<id>` 或断言 `medium_ref` 把 fact 映射到 `knowledge_id`；`narrativeFactForEntry` 只覆盖叙述事实，必要时补 `entryForFact`。
2. 在现有四路 RRF 上新增 `graph` 路由，路由项是**去重后的条目 id**，权重默认 0（影子）；图谱支持在同一结果上附加：
   ```json
   {"graph_support": [{"fact_id": "...", "hops": 2, "path": "A -> B -> C"}]}
   ```
3. 不能映射到条目的纯三元组事实不进入条目 top-k；先记录到 trace/聚合旁路，避免混入条目结果破坏契约。
4. 开关：`NEUROVA_KB_GRAPH_ROUTE=off|shadow|on`，默认 shadow；影子只记录 rank/NDCG，不改变返回。

**阶段 B（中期，统一排序）：链级 RRF**

1. 把 knowledge hybrid、graph walker、temporal facts、memory、structured query 的**秩列表**统一到一个 `retrieval_fusion`；按 route 权重做 RRF，替换 `_retrieve_parallel` 的 `max(quality)`。
2. 统一结果契约：
   ```json
   {
     "id": "entry:<knowledge_id> | fact:<fact_id>",
     "kind": "entry|graph_fact|memory|structured",
     "content": "...",
     "entry_id": "optional",
     "fact_id": "optional",
     "hops": 2,
     "path": "A -> B -> C",
     "score": 0.0123,
     "route": "knowledge|graph|memory|structured"
   }
   ```
3. 去重规则：条目优先；同一 fact 只保留一条；`entry + graph_support` 合并而不是两条并列。
4. 权重单源配置；初始建议 `tfidf .30 / bm25 .30 / vector .25 / fts .15 / graph .10 / memory .10`，先影子后切换；以 golden multi-hop 集做 recall@k/NDCG 门禁。
5. 租户/可见性：图谱 walker 必须同时按 tenant + agent 过滤；纯事实命中若无法映射到可见条目，按租户边界放行或丢弃要显式定策略，不能靠下游过滤补救。

### 4.3 意图门控与预算

- 只有查询出现图谱锚点（主体名/别名）才走图谱路由；无锚点直接返回空，避免全图扫。
- 默认 `maxHops=2`、`limit=10`；图谱路由超时/异常 fail-open（该路为空），不拖垮知识主路。
- 多跳查询才触发阶段 B 的图谱优先；单跳/关键词查询保持现有条目 RRF。
- 观测：图谱路由命中数、跳数分布、p95、无条目映射率、引用 fact_id 数。

### 4.4 验收

- `graph` 路由影子下 recall@k 不降，NDCG 提升才切 on；
- 跨租户图谱命中为 0；图谱 fact 不重复、不串条目；
- 纯图谱多跳 golden 集能命中并带完整 path；
- 引用/注入账记到 fact_id；条目级 `graph_support` 不改变原条目引用 id。

## 5. 分批计划

### Batch A0 · 图谱读面租户隔离（P0）

- `subjectsMentionedIn` 增加 `tenantId`；`GraphFactWalker` 锚点与递归段都带 tenant；`TemporalFactReader` 同源补 tenant。
- 传参链：`GraphRetrieverAdapter`/`TkgRetrieverAdapter` 从 `RetrievalContext.metadata.tenant_id` 取值。
- 验收：同 agent 下 t1/t2 同标签不互见；graph/temporal 查询跨租户 0 命中；现有 933 套件绿。

### Batch A1 · 内容去重（P1）

- 规范化正文指纹（tenant + agent + content hash）；`create_knowledge(dedupe=True)` 先查指纹。
- 精确重复：返回既有 `knowledge_id` 并标记 `duplicate`；跨来源是否保留来源链需拍板（建议第一版只报告/标记，不自动合并 provenance）。
- 近重复：进入现有冲突队列，不自动删。
- 验收：同文重复导入不新建条目；不同租户同文不互斥；回填脚本支持幂等重跑。

### Batch A2 · OCR provider 协议（P1）

- 抽 `OcrEngine` 协议（`available/recognize`），现 `RapidOcrEngine` 作为实现；新增可选 PaddleOCR/Tesseract provider，惰性加载、不可用显式 `ocr_unavailable`。
- 引擎选择：`NEUROVA_KB_OCR_ENGINE=rapidocr|paddle|tesseract|auto`；不自动下载模型。
- 验收：同一 fixture 各 provider 契约一致；缺依赖失败原因可读；OCR 覆盖率/置信度读数不回归。

### Batch A3 · 元数据过滤面（P1）

- `visible_items/hybrid/search_visible_items` 增加 `author/source_type/ocr_used/page_min` 过滤；document 详情已具备，补列表筛选。
- 验收：过滤先于索引；跨租户/可见性不回归；API 文档重生成。

### Batch A4 · 图谱条目路由（P1，影子）

- 按 §4.2 阶段 A 实现 `graph` 影子路由 + `entryForFact` 映射；权重 0，不改变输出。
- 验收：影子 rank/NDCG 有读数；无条目映射的 fact 不进入条目结果。

### Batch A5 · 链级统一 RRF（P1）

- 新增 `retrieval_fusion`；knowledge/graph/temporal/memory/structured 产秩列表；按 §4.2 阶段 B 合并。
- 验收：golden multi-hop 集；recall@k 不降、NDCG 可量化；图谱 fact 去重；p95 预算内；失败隔离。

### Batch A6 · GIS 可选（P2）

- 条目/chunk 增可选 `geo`（lat/lon/bbox/geohash）；检索增加 radius/bbox 过滤；无坐标不参与。
- 验收：无 geo 语料行为不变；过滤先于向量/词法；越权租户不可见。

### Batch A7 · 格式/框架补齐（P2）

- `.xls` 可选直读（否则维持 LibreOffice）；Kreuzberg 仅做适配评估，不整体更换现有流水线（避免双管线）。
- 验收：格式矩阵全部有可解释失败；不新增第二套解析真源。

### Batch A8 · 规模与交付（独立）

- 10M 迁移/分片、Docker 远程构建、生产 MQTT TLS、生产回填按已登记的解封条件执行；不阻塞 A0–A5。

## 6. 数据/API 变更

| 变更 | 说明 |
|---|---|
| `knowledge_entries.content_fingerprint` | 精确去重键（tenant+agent+hash） |
| `entries.graph_support` / fusion item | 图谱证据挂条目；不复制正文 |
| `GraphFactWalker(tenantId=...)` | 图/时效读面租户过滤 |
| `/knowledge/import` 响应 | 增加 `duplicate_of` / dedup 状态 |
| 文档列表过滤 | author/source_type/ocr/page_min |
| 可选 `geo` | 条目/chunk 地理字段与过滤 |
| `NEUROVA_KB_GRAPH_ROUTE` | off/shadow/on，默认 shadow |
| `NEUROVA_KB_OCR_ENGINE` | rapidocr/paddle/tesseract/auto |

## 7. 测试与评估

- 格式矩阵 fixture：每种格式 + 扫描件 + 旧 Office；失败原因逐项断言。
- 去重：同文重复、跨租户同文、跨来源同文、并发双写。
- 图：t1/t2 同标签隔离；多跳 golden；影子 rank/NDCG；fact→entry 映射率。
- 融合：knowledge-only 与 +graph 的 recall@k/NDCG；图谱路由关闭时逐字不变。
- 回归：现有知识库 936、API/Supervisor 63 起步，新增用例进对应模块目录。

## 8. 风险与回退

- 图谱融合改变排序：默认 shadow、权重 0、可 env 关闭；先 golden 后切。
- 去重误合并：第一版只报告/标记；自动合并需 provenance 产品裁定。
- OCR 依赖体积/许可：provider 可选，不可用显式失败，不下载模型。
- GIS 引入索引膨胀：无 geo 不建索引；过滤先于检索。
- Kreuzberg 双管线：只评估适配层，不替换现有单源，除非格式覆盖实测胜出。

## 9. 拍板项

| 编号 | 问题 | 建议 |
|---|---|---|
| D1 | 跨来源完全相同正文：返回既有条目 / 新建 duplicate_of / 保留多来源 | 先报告+标记，不自动合并 |
| D2 | 图谱融合先条目级还是直接链级 | 先阶段 A 影子，再阶段 B |
| D3 | GIS 现在做还是预留接口 | 先预留字段/过滤，不引入空间库 |
| D4 | 是否采用 Kreuzberg | 只评估适配，不整体迁移 |

## 10. 推荐顺序

A0（租户隔离）→ A1（去重）→ A3（过滤）→ A4（图谱影子）→ A5（链级融合）→ S0/S1（2D/3D 只读工作台）→ S2（本体 CRUD）→ S3（实例编辑）→ A2（OCR provider）→ A6（GIS）→ A7（格式/框架）→ S4/S5（3D 规模与替换旧页）→ A8（规模/交付）。

---

## 11. 图谱 2D/3D 建模工作台（取代现有只读图谱页）

说明：工作区与本机未找到 OntoStudio 的源码或仓库地址，因此本节只按“OntoStudio 类
本体建模环境”的**能力层**对照（2D 本体/关系编辑 + 3D 图探索），不复刻其实现、
接口或命名。若需按真实项目对齐，需先提供仓库地址/页面截图确认数据模型。

### 11.0 对附件设计稿的代码校正

附件设计稿有几处按“目标代码”描述，和本仓实际实现不完全同形，落地时必须按实际代码收口：

| 附件写法 | 实际代码 | 计划调整 |
|---|---|---|
| `graph_traversal.py` 24 种关系权重 | `cognitive_layers/memory_layer/graph_traversal.py` 实际 **26 种**（含 `related/supports/derived_from` 等历史项） | 以实际常量为基线；新增关系类别只做单一映射，不再维护第二份 24/26 清单 |
| 新增 `graph_layer/` 与 `QueryRouter` | 已有 `GraphChannel`（六通道之一）读 `KnowledgeGraphManager`；`GraphFactWalker` 读底座事实；`MemoryRetrievalChain` 已有责任链 | 不新建平行图检索层；增强点放进现有 `GraphChannel` 与 `GraphFactWalker`，路由放进现有链 |
| 新增 `reasoning_layer/`、`causal_engine.py` | 已有 `ontology/rule_engine.py` 前向推理、`derivation_ledger` 推导账、`knowledge_facts` 因果三元组 | 因果链查询作为现有 rule/graph 的查询视图，不另起推理事实源 |
| 新 `conflict_detector.py` + CRDT 复用 | 已有 `knowledge/conflict_features.py`、`conflict_judge.py`、repository 冲突账；`neurova/crdt/` 存在但**未接**知识冲突 | 冲突检测接现有冲突账；CRDT 只在确有并发编辑需求时接入，不把两套冲突账并存 |
| `nerf_fusion_with_enhancement` | 已有 `NeurovaRecallEngine`、`RecallChannel` 六通道、`VolumeRenderer.render()` | 图谱增强以 `channel_scores["graph"]` 增量进入现有 VolumeRenderer，不改融合公式 |
| `/api/graph/*` | 现有 `/api/v1/knowledge-graph/{agent}/...`、`/api/v1/knowledge/...` | 扩展现有命名空间；不新增第二套 graph API |
| `neurova_frontend/`、AntV G6 | 实际前端是 `NeurUI/`，现有 `KnowledgeGraphPage.vue` 用 ECharts；`@vue-flow/core` 已装，G6/Three 未装 | 2D 先用 Vue Flow；3D 再引 `3d-force-graph`/Three 懒加载；不引第二套 2D 框架 |
| `SpatialBridge`/Mapbox | 无 geo 字段/空间索引 | 单列 GIS 阶段；不引入 Mapbox 作为默认依赖 |

### 11.1 现状

| 层 | 当前 | 限制 |
|---|---|---|
| 页面 | `KnowledgeGraphPage.vue` + ECharts force 图 | 只读；无节点/边编辑；无 3D |
| 数据 | `/knowledge-graph/{agent}/knowledge-graph` 返回 JSON 投影节点/边 | 投影由 `graph_bridge` 从事实派生，直接改会被 rebuild 覆盖 |
| 本体 | `OntologyTermRegistry` / `ForwardChainingEngine` 有术语、规则、约束表 | 无 CRUD API；2D 编辑器没有写入口 |
| 实例 | `knowledge_facts` + admission gate + assertions/lineage | 图页面不能新建/编辑事实；无“图编辑 → 咽喉”链路 |
| 记忆图 | `graph_traversal.GraphTraversal`：BFS/DFS/加权路径、26 种关系权重；由 memory manager 装载 | 只服务记忆关系；没有知识事实的因果/证据视图 |
| 图通道 | `channels/builtin/graph.py` 读 `KnowledgeGraphManager` 投影，是六通道之一 | 与知识 hybrid 的四路 RRF 各算各的；未与事实 walker 合流 |
| 融合 | `NeurovaRecallEngine` 六通道 + `VolumeRenderer`（legacy/nerf） | 图谱增强没有接入 `channel_scores["graph"]`；知识 hybrid 另有一套 RRF |
| CRDT | `neurova/crdt/` 有 RGA/version vector | 未接知识冲突账；不能把两套冲突源并存 |
| 3D | 无 | 无 WebGL 依赖、无服务端子图裁剪 |

### 11.2 目标架构：双层、两类视图

- **本体层（设计时）**：术语/父类/定义域/值域/基数/不相交/必填属性/规则。写
  `ontology_terms` / `ontology_rules`，全局共享；变更需校验与影响分析。
- **实例层（运行时）**：事实与关系仍以 `knowledge_facts` 为唯一权威；2D 里新建/改边
  必须经 admission gate（断言、来源、租户、本体校验），再触发投影 rebuild。
- **2D 工作台**：用已安装的 `@vue-flow/core` 做可编辑画布：调色板（concept/relation/
  property）、属性面板、连线校验、撤销/重做、影响分析、导入/导出；视图分“本体模式”
  与“实例模式”，避免把 schema 和 instance 合成一张不可判的图。
- **3D 探索器**：WebGL 力导向（Three.js 系）只做读侧探索：按类型/租户/跳数过滤、
  LOD、聚焦路径、2D/3D 视角同步；第一版不允许 3D 写操作，避免在三维画布上做
  不可审计的批量修改。
- **两个现有接口只增强不另起**：记忆侧复用 `GraphChannel` 与 `GraphTraversal`；
  知识侧复用 `GraphFactWalker` 与 `GraphRetrieverAdapter`。因果/冲突/空间增强
  先汇总为 `graph` 通道分数，再交给既有 `VolumeRenderer` 融合；2D/3D 工作台只读
  这些查询面，不自己维护图数据库。

### 11.3 后端 API（新增/收口）

| 端点 | 用途 |
|---|---|
| `GET /knowledge/ontology/schema` | 返回 terms/rules/constraints 与版本，供 2D 调色板 |
| `POST/PUT/DELETE /knowledge/ontology/terms` | 管理员术语 CRUD；删除前返回影响面 |
| `POST/PUT/DELETE /knowledge/ontology/rules` | 规则 CRUD；非法规则写入即拒 |
| `GET /knowledge/ontology/impact?term=` | 引用该术语的事实/规则/条目清单 |
| `POST /knowledge/graph/instances` | 2D 新建/修改实例关系 → admission gate → 返回 fact_id/activity |
| `POST /knowledge-graph/{agent}/projection/rebuild` | 沿用现有；编辑后显式重建并校验 drift |
| `GET /knowledge-graph/{agent}/studio` | 一次性返回子图 + schema + 统计 + 权限/租户过滤 |

所有写端点要求管理员或显式授权；每次 schema/instance 变更必须留操作人、依据、版本。

### 11.4 分阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| S0 | 2D/3D 只读工作台壳；复用现有 graph API；3D 懒加载依赖 | 2D/3D 可切换；空图/大图有提示；旧页面保留 |
| S1 | `ontology/schema` 读 API + 2D 本体树/属性面板 | schema 与 DB 一致；无写入口 |
| S2 | 术语/规则 CRUD + 影响分析 + 版本/回滚 | 非法结构 400；删除前列影响；变更留痕 |
| S3 | 2D 实例编辑经 admission + projection rebuild | 编辑→fact→投影 roundtrip；drift=0；租户隔离 |
| S4 | 3D 大规模探索：服务端子图、LOD、路径高亮 | N 节点渲染在预算内；2D/3D 选中同步 |
| S5 | 新页面替换旧 `KnowledgeGraphPage`，旧图配置/文案退役 | 功能对齐；11 语言；旧路由可回退一个版本 |

### 11.5 验收与风险

- roundtrip：2D 改本体 → 3D 按类型着色/过滤正确；2D 建实例 → 读面/图检索能命中。
- 任何图编辑不得直接写 JSON 投影；否则下一次 rebuild 会静默丢失（必须先写权威）。
- 本体术语目前全局、无 tenant 列；若多租户需要各自本体，先拍板 schema 归属，不能靠
  前端过滤冒充隔离。
- 3D 依赖新增 bundle 与 WebGL 兼容性；懒加载 + 2D 降级，不让管理页因 3D 失败不可用。
- 大图：服务端按 agent/tenant/类型/跳数裁剪，默认节点上限；不做全量 10M 渲染。

### 11.6 与图谱混合检索的关系

2D/3D 工作台只负责“建模与探索”，不改变检索排序。图谱是否进入 hybrid 仍按 §4 两阶段：
先影子条目路由，再链级 RRF；工作台产出的 ontology/rules 通过现有校验与推理链路影响
事实，而不是由前端直接改检索结果。

### 4.5 与现有 NeRF/GraphChannel 的关系

本仓已有两套检索融合，不能再造第三套：

- **记忆侧**：`NeurovaRecallEngine` 六通道（temperature/text/category/graph/emotion/voice）
  + `VolumeRenderer`（legacy/nerf）；`GraphChannel` 已读 `KnowledgeGraphManager` 投影。
- **知识侧**：`hybrid_search_knowledge` 四路 RRF；`GraphRetrieverAdapter` 走
  `GraphFactWalker`，是责任链独立分支。

落地口径：

1. 记忆侧因果/冲突/空间增强只汇总进 `channel_scores["graph"]`，由现有
   `VolumeRenderer` 融合；不改 NeRF 公式、不新增第二套体渲染。
2. 知识侧图谱融合仍按 §4.2 阶段 A/B 接四路 RRF；若后续要做“知识 + 记忆”统一，
   先抽一个 `retrieval_fusion`，而不是让两套融合互相调用。
3. 2D/3D 工作台只读这两套查询面；不把 `GraphTraversal`（记忆关系）与
   `GraphFactWalker`（知识事实）混成同一张可编辑图。

## 12. 已拍板与实施状态（2026-10-24）

| 决策 | 结果 |
|---|---|
| 精确重复 | 返回既有条目、追加来源证据（`sources[]`），不新建重复记录 |
| 图谱融合 | 先条目级影子路由，后链级 RRF |
| 2D/3D 编辑 | 2D/3D 都可编辑（3D 支持批量操作） |
| GIS | 现在接地图与空间视图（MapLibre） |
| 本体归属 | 按租户隔离 |
| Kreuzberg | 迁移到 Kreuzberg 统一解析框架 |

已落地（本批）：

- **A0 图谱租户隔离**：`subjectsMentionedIn`、`TemporalFactReader`、`GraphFactWalker`
  增加 tenant；读面结果带 `tenant_id`；t1/t2 同标签不互见。
- **A1 精确去重**：条目 `content_fingerprint`（tenant + 规范化正文）；
  `dedupe=True` 返回既有条目并追加 `sources[]`；导入/企微/创建入口启用。
- **A3 元数据过滤**：搜索支持 `author/source_type/ocr_used/page_min/source/updated_after`。
- **A4 图谱影子路由**：`hybrid_search_knowledge` 新增 `graphRanks/graphSupport/graphWeight`；
  默认权重 0，结果附 `graph_support`；adapter 从 fact 的 `entry_id` 映射条目。
- **A5 链级 RRF 基础**：`fuseRetrievalResults` + `NEUROVA_RETRIEVAL_FUSION=rrf`
  可选启用；默认 legacy 行为不变。
- **S0 前提读面**：图谱端点统计单源 `manager.get_stats()`，报真总量与 `truncated`。
- **S1 本体读面**：`GET /knowledge/ontology/schema`（术语 + 规则 + 版本 + 值域展开）。
- **S2 本体写面**：`/knowledge/ontology/terms|rules` CRUD（管理员、非法结构 400、
  重复 409、PUT 部分更新保留未声明字段）；`GET /knowledge/ontology/impact` 删除前
  影响面（事实/主体类型/子术语/引用规则四路读数，被引用即 409 不许强删）；写变更落
  activity 留痕（操作人/动作/依据）；删规则由派生账撤回其全部推导结论
  （`retractAllFromRule`）。

尚未落地（依赖后续迁移/前端批次）：

- **按租户本体**：`ontology_terms/rules` 目前以全局 `term_id` 为主键，直接加 tenant
  列无法允许两个租户使用同一 term_id；需要 v25 改主键/引入 tenant 复合键或租户
  独立 schema，属于数据迁移，不能在本批偷偷改。
- **2D/3D 工作台**：后端读/写面已具备（S1 schema / S2 CRUD+影响面 / 图谱真总量）；
  前端仍是只读 ECharts——Vue Flow 2D 画布、3D WebGL、S3 实例编辑（经 admission +
  projection rebuild）、MapLibre 空间视图均待 S0–S5 前端批次。
- **Kreuzberg 迁移**：已安装并验证可抽取 docx/pdf（页标记可用），但尚未替换
  `document_pipeline` 主路；需先做影子对比（页码/标题/OCR/召回）再切。
- **GIS**：geo 字段、空间过滤、MapLibre 视图未落代码。
