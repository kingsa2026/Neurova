# 知识库系统升级设计

- **状态**：方案稿，未实施；本文只定义目标、差距、分期与验收，不改代码。
- **基线日期**：2026-10-23
- **输入依据**：
  - 用户提供的《智能知识库系统架构设计.md》（v1.0，2026-10-23）；
  - 当前仓源码与已落地的知识治理实现；
  - `docs/specs/2026-10-23-knowledge-governance-remaining-design.md`；
  - `audit-reports/knowledge-governance-rag-audit-2026-10-23.md`。
- **关联审计**：本文的差距矩阵是只读比对结论，不是实施授权；每批落地仍需先红后绿、A/B、
  live-verify 与单任务单提交。

> 输入文档存在多处重复/截断（1.3、3.1、4.4、7.5、7.6 等），本文按可读语义提炼，
> 不把损坏片段当作硬性契约。

---

## 0. 结论摘要

当前知识库的**治理、检索、反馈与可观测面已经闭环**，但输入文档描述的是一条更完整的
“文档生产 + 多 Agent 蜂群”系统。按目标架构衡量，主要不足集中在三层：

1. **文档进入知识库之前的标准化层**：OCR、旧版 Office、图片/扫描件、清洗、页码/标题元数据不完整；
2. **企业微信信源到知识库的入站链路**：当前企微消息主要进聊天，不自动成为知识资产；
3. **多 Agent 蜂群与分布式存储/消息总线**：当前是单主 Agent + retriever 适配器 + 嵌入式
   SQLite/FTS/hnswlib，不是 Supervisor-Worker + MQTT + Milvus/Neo4j/MySQL 的形态。

建议按 **P0 文档标准化与企微入站 → P1 冲突矩阵/精排/版本 → P2 多 Agent 与分布式存储**
推进；多 Agent 与外部存储不应先做，先由规模和产品形态触发。

---

## 1. 范围与原则

### 1.1 本文覆盖

- 文档标准化流水线（格式分流、OCR、清洗、结构化 schema、分块元数据）；
- 企业微信等消息信源进入知识库；
- 语义去重/冲突判别、精排、版本回滚；
- 多 Agent 蜂群、MQTT 任务总线、存储与索引进阶；
- 评估、租户隔离、可观测性与迁移策略。

### 1.2 不在本文范围

- 重写当前已闭环的检索责任链、生命周期、采纳反馈、质量事件；
- 在未拍板前引入新外部服务；
- 把聊天渠道消息无差别地复制进知识库；
- 用模型猜测补齐缺失的元数据（页码、作者、OCR 文本）。

### 1.3 设计原则

- **单一事实源**：同一能力只保留一处实现；新流水线复用现有解析、分块、入库、检索。
- **缺失可观测**：OCR/旧格式/链接抓取失败必须显式返回原因，不静默生成空知识。
- **先影子后接管**：新流水线与新排序先影子运行、对照基线，再切主路。
- **能力触发存储迁移**：先量化 p95、语料规模与并发，再决定是否引入外部数据库。
- **不伪造**：没有平台事件、没有 OCR 结果、没有版本记录时，读面明确标注，不回默认值。

---

## 2. 现状基线

### 2.1 已具备能力

| 能力 | 当前实现 | 证据 |
|---|---|---|
| 四路混合检索 | TF-IDF/BM25/FTS/向量 + 加权 RRF，`RRF_K=60` | `neurova/knowledge/hybrid.py:36`、`:297` |
| 末端精排 | 默认加权精排，model provider 可注入；事件循环内禁用同步 model 通道 | `neurova/knowledge/rerank/main_path.py`、`model_rerank_runner.py` |
| 分块 | 父子块、偏移、表头上下文 | `neurova/knowledge/splitter.py:266` |
| 时间感知 | 事实 `valid_from/valid_until`，条目 `valid_until/lifecycle_status` | `neurova/knowledge/foundation/knowledge_facts.py:73`、`repository.py:1433` |
| Ontology | 术语、规则、推导账本、静态本体 + 动态事实 | `neurova/knowledge/ontology/`、`foundation/` |
| 冲突治理 | 同主体/谓词冲突分类、严重度、策略、人工兜底 | `neurova/knowledge/foundation/conflict_judge.py` |
| 人工审核 | 条目冲突账本、实体消解人工 review | `neurova/knowledge/repository.py:1701`、`resolution.py` |
| 反馈闭环 | 点赞/纠错 → fact/entry 三态 → 下次检索重排；entry token 分表 | `feedback_prior.py`、`repository.py`、`knowledge_facts.py` |
| 检索评估 | 黄金集、recall@k/MRR/unhit、baseline 对比 | `neurova/knowledge/evaluation/retrieval_benchmark.py` |
| 索引规模 | FTS5 持久倒排、可选 hnswlib/faiss、JSON 回退 | `fts_index.py`、`vector_ann.py` |
| 质量事件 | 接管/完成态事件、管理员分析页、质量 metrics | `neurova/quality/`、`api/endpoints/quality.py` |
| 渠道接管 | MQTT/飞书服务台/微信客服 kf 原生事件 | `channels/mqtt.py`、`feishu.py`、`wechat_kf.py` |

### 2.2 当前拓扑

```text
聊天/渠道消息
    │
    ▼
AttachmentParser（docx/xlsx/pptx/文本型 PDF/html/csv/rtf/odf）
    │  图片/扫描件/旧版 Office 不支持
    ▼
KnowledgeRepository（JSON/SQLite 条目、父子块）
    │
    ▼
Hybrid 检索（TF-IDF + BM25 + SQLite FTS5 + JSON/hnswlib 向量）
    │
    ▼
RRF → 加权/model 精排 → 采纳先验重排 → 上下文注入
    │
    ▼
反馈（fact/entry adoption）→ 重排与 token 账
```

### 2.3 当前验证读数

- 知识全量 843 passed；渠道 695 passed；entry/重排/token 合并 62 passed；
- 前端全量 2165 passed、0 failed；`vue-tsc` 通过；
- FTS 1M：构建 58.4s、查询 577.6ms；ANN 1M：构建 52.5s、查询 0.41ms；
- 当前没有 OCR、企微入库、分布式消息总线的端到端读数。

---

## 3. 差距矩阵

| # | 目标能力 | 当前状态 | 差距 | 级别 |
|---|---|---|---|---|
| D1 | PDF/Word/Excel/PPT/图片/扫描件/MD/JSON 全格式标准化 | docx/xlsx/pptx/文本 PDF/html/csv/rtf/odf 可用；图片/扫描件/.doc/.ppt/.xls 不可用 | 缺 OCR、旧版 Office 转换、图片流水线 | P0 |
| D2 | 清洗：全半角、页眉页脚、水印、断行、OCR 纠错 | 基本只做解码与解析 | 无可测清洗层 | P0 |
| D3 | 标准 schema：doc_id/source_type/source_path/ingest_time/author/page_count/ocr_used/pages/chunks(page/heading/embedding) | 条目字段与 chunks 偏移、表头上下文 | 缺文档级元数据、页码/标题、OCR 标记 | P0 |
| D4 | 企业微信群消息作为知识信源 | 企微/微信客服接聊天；知识导入只支持文件/URL | 无图片/文件/链接/语音入知识库；无 `kb/ingest/wecom` | P0 |
| D5 | Supervisor-Worker 蜂群 + MQTT 任务总线 | AgentTeam（ACP 顺序编排）、SwarmManager 派生子 Agent | 无 MQTT Supervisor/Worker、无独立检索/图谱/记忆/结构化 Worker | P2（若必须多节点则 P0） |
| D6 | 三层语义去重/冲突矩阵（哈希、Jaccard、实体、数字、向量） | 事实冲突按 slot 分类；条目冲突用标题/正文 SequenceMatcher | 缺 NER/数字匹配/向量矩阵与“相似 vs 对冲”判定 | P1 |
| D7 | bge-reranker/LLM 精排 | 加权精排默认；model provider 仅注入式，无内置模型 | 无内置 rerank 模型与 LLM 精排段 | P1 |
| D8 | 事实版本历史、对比、回滚、业务基线 | 条目有 revisions；事实有 supersedes/valid 窗口，无版本表/回滚 API | 事实级版本与基线缺失 | P1 |
| D9 | 设计时/运行时/质检/合并四类人工回判 | 冲突/实体消解人工 review 已有 | 低置信/质检触发未统一 | P1 |
| D10 | Milvus/Qdrant、Neo4j、MySQL、对象存储、Redis | SQLite/JSON/FTS5/hnswlib，嵌入式单机 | 未采用外部存储；分布式/多租户能力受限 | P1/P2（按规模决策） |
| D11 | 自动 A/B、冲突检出率、相关性评估 | recall@k/MRR/unhit、质量事件 | 无冲突检出率/自动权重调优 | P2 |
| D12 | 部门/租户隔离、更多信源、自动裁决 | user/agent + visibility | 无 tenant 维度；自动裁决有限 | P2 |

---

## 4. 目标架构

```text
信源层
  本地文件 / 企微消息 / 网页 / 手工录入
        │
        ▼
知识接入网关
  鉴权 / 去重键 / 大小与类型校验 / 入队 / 失败可见
        │
        ├── 文档标准化流水线
        │     格式识别 → 解析 → OCR 兜底 → 清洗 → 结构化 → 分块
        │
        └── 消息信源桥
              媒体下载 / 链接抓取 / 语音转写 / 统一成文档事件
        │
        ▼
知识治理层（沿用现有）
  admission → 事实/条目 → 时间窗 → 冲突 → 人工回判 → 版本
        │
        ▼
索引与存储层
  条目/事实库 + FTS + 向量索引 + 原始文档存储
  （达到规模阈值后可替换为 Qdrant/Milvus、Neo4j、对象存储）
        │
        ▼
检索与生成层
  RRF → 精排 → 采纳先验 → 上下文 → 引用/反馈
        │
        ▼
应用层：问答 / 检索 / 决策支持 / 自动化
```

### 4.1 与当前实现的关系

- 继续复用：`KnowledgeRepository`、`KnowledgeFactStore`、`hybrid`、`rerank`、
  `feedback_prior`、`quality`、生命周期与冲突账本。
- 新增层集中在**接入网关 + 文档标准化**与**可选的分布式总线/存储**。
- 不在聊天管线里再写一套解析或检索；新流水线只产出统一文档事件，交给现有入库咽喉。

---

## 5. 分阶段路线

### 5.1 P0（先做，直接补设计目标）

| 批次 | 内容 | 退出判据 |
|---|---|---|
| P0-A | 文档标准化与 OCR | 6 类格式 fixture 全通过；扫描 PDF/图片可入库；失败原因可见 |
| P0-B | 企微消息→知识入站 | 文本/图片/文件/链接/语音至少各 1 条端到端；重放幂等 |
| P0-C | 标准 schema 与页码/标题元数据 | 文档/块可回指页码、标题路径、OCR 标记 |
| P0-D | 清洗规则与质量门 | 全半角/页眉页脚/水印/断行的固定样本通过 |

### 5.2 P1（让知识更准、更可追溯）

| 批次 | 内容 | 退出判据 |
|---|---|---|
| P1-A | 冲突特征矩阵 | 规则矩阵四象限各有 fixture；冲突检出率与误合并率有读数 |
| P1-B | bge/LLM 精排 provider | 影子对照 recall/NDCG 不降；provider 失败可见并回退 |
| P1-C | 事实版本/回滚/业务基线 | 任一事实可查历史、可回滚；回滚留操作人与依据 |
| P1-D | 存储规模决策 | 1M/10M 基准与 p95 读数；达到阈值才迁移外部存储 |

### 5.3 P2（按产品形态决定是否做）

| 批次 | 内容 | 决策点 |
|---|---|---|
| P2-A | Supervisor-Worker + MQTT | 是否真的需要多节点 Worker；否则保留 AgentTeam/Swarm |
| P2-B | 多租户/部门隔离 | 是否需要 tenant 维度的数据与权限 |
| P2-C | 自动 A/B/权重调优 | 是否有稳定人工标注与足够流量 |
| P2-D | 更多信源（钉钉/邮件等） | 每个信源单独评估平台事件与权限 |

---

## 6. 详细设计

### 6.1 文档标准化与 OCR（P0-A/C/D）

#### 6.1.1 流水线

```text
receive(original)
  → detect_format(扩展名 + magic bytes)
  → extract_text_layer
  → needs_ocr? → render_pages → ocr → merge
  → clean_text
  → structure(pages/headings/tables)
  → chunk + metadata
  → persist document + chunks + provenance
```

#### 6.1.2 格式矩阵

| 输入 | 解析 | OCR/转换 | 输出 |
|---|---|---|---|
| txt/md/json/yaml/csv | 直接解码/结构化 | 无 | 文本/表格 |
| docx | python-docx 段落/表格 | 无 | 文本 + 标题层级 |
| doc | LibreOffice headless 转 docx（可选依赖） | 无则 `unsupported_legacy_office` | 同 docx |
| xlsx | openpyxl 逐 sheet | 无 | 表格文本 + sheet 元数据 |
| pptx | python-pptx 逐页 | 无 | 文本 + slide 页码 |
| ppt/xls | LibreOffice 转换 | 无则诚实失败 | 同新格式 |
| 文本型 pdf | pypdf 按页 | 无 | 按页文本 |
| 扫描 pdf | PyMuPDF 渲染 | OCR | 按页 OCR + 置信度 |
| 图片 | — | OCR | 文本 + OCR 标记 |
| html/链接 | 抓取 + 正文提取 | 可选 OCR 图片 | 文本 |

#### 6.1.3 OCR 适配层

新增 `neurova/knowledge/ingest/ocr.py`，定义单一接口：

```python
class OcrEngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def recognize(self, image: bytes, *, lang: str = "ch") -> list[OcrBlock]: ...
```

- 首选 RapidOCR（ONNX Runtime、CPU 可跑、依赖轻）；PaddleOCR 作为可选高质量后端；
- 惰性 import、超时、单页/单文档大小上限；不可用或失败返回显式 reason；
- OCR 结果保留 `page`、`block bbox`、`confidence`，不得只回一段拼接文本。

#### 6.1.4 清洗规则

按顺序、可单测：

1. Unicode NFKC；全角/半角统一；
2. 去控制字符/分页符；
3. 页眉页脚/水印/版权声明：按页首尾重复行与模板正则；
4. 合并被硬换行打断的段落，保留 `\n\n` 段落；
5. OCR 噪声修正词典（可配置、可关闭，不凭模型猜）；
6. 表格：保留行列关系，输出 Markdown/CSV 文本，不丢表头。

#### 6.1.5 统一 schema

```json
{
  "doc_id": "uuid",
  "source_type": "pdf|docx|xlsx|pptx|md|json|image|url|wecom",
  "source_path": "原始文件/链接/消息 id",
  "ingest_time": "ISO8601",
  "content": "清洗后的正文",
  "metadata": {
    "title": "",
    "author": "",
    "page_count": 0,
    "created_at": "",
    "modified_at": "",
    "ocr_used": false,
    "ocr_engine": "",
    "ocr_confidence_avg": null
  },
  "pages": [{"page": 1, "text": ""}],
  "chunks": [{
    "chunk_id": "uuid",
    "text": "",
    "page": 1,
    "heading_path": ["第一章", "1.1"],
    "char_start": 0,
    "char_end": 100,
    "embedding_ref": "vector-index-key"
  }]
}
```

**存储边界**：正文/页码/标题存条目与块元数据；向量不塞进 JSON 正文，统一由向量索引按
`chunk_id` 管理，避免第二份向量事实源。

#### 6.1.6 与当前代码的接入方式

- 把 `attachment_parser` 升级为“结构化解析 + 兼容文本包装”：
  - 新入口 `parse_document(data, filename) -> ParsedDocument`；
  - 现有 `extract_attachment_text` 保留为薄包装，聊天附件行为不变；
  - 知识导入、企微入站、网页导入统一调用新入口。
- 扩展 `splitter`：在现有 `content/index/char_start/char_end/context_header` 上增加
  `page/heading_path`；旧读取方保持兼容。
- `KnowledgeRepository.create_knowledge` 增加文档级元数据字段；不新建第二套条目库。

#### 6.1.7 验收

- 每种格式一条 fixture：文本、页码、标题、OCR 标记正确；
- 扫描 PDF/图片：有 OCR 结果时入库，无引擎时显式 `ocr_unavailable`，不生成空知识；
- 旧 `.doc/.ppt/.xls`：LibreOffice 可用则转换，不可用则明确失败；
- 清洗样本：全半角、页眉页脚、水印、断行、OCR 噪声各一条；
- 同一文件重放不产生重复文档（内容/来源幂等键）。

### 6.2 企业微信消息入站（P0-B）

#### 6.2.1 链路

```text
企微消息/事件
  → 渠道适配器（已有）
  → 知识入站桥（新）
       过滤：仅配置了 ingest_to_kb 的群/应用
       媒体：下载图片/文件/语音
       链接：SSRF 安全抓取
       语音：ASR → 文本
  → 统一文档事件（source_type=wecom）
  → 知识摄取队列
  → 标准化 → 入库
```

#### 6.2.2 MQTT 契约

| 主题 | 方向 | 载荷 |
|---|---|---|
| `kb/ingest/wecom` | 信源 → 知识库 | `event_id, channel, chat_id, sender_id, message_type, media_ref, text, occurred_at` |
| `kb/ingest/result` | 知识库 → 信源 | `event_id, status(accepted|duplicate|failed), doc_id, reason` |
| `kb/conflict/notify` | 知识库 → 运营 | `conflict_id, subject, predicate, severity` |

- `event_id` 是幂等键；重复投递返回 `duplicate`，不重复入库；
- 失败进 DLQ/重试队列，读面报队列积压与失败原因；
- 消息默认只进聊天，只有显式开启的群/应用才进知识库，避免把闲聊灌入知识资产。

#### 6.2.3 与当前代码的接入方式

- 在 `ChannelManager` 的 `MESSAGE_RECEIVED` 后增加可选 `KnowledgeIngestBridge`，
  只消费 `metadata.ingest_to_kb=True` 的消息；
- 复用现有知识摄取队列（`ingest_queue.py`）与入库咽喉；
- 媒体下载复用渠道适配器已有能力；缺失的媒体接口必须补，不能只存占位；
- 不修改聊天主链行为；入站失败只记知识任务失败，不影响聊天回复。

#### 6.2.4 验收

- 文本、图片、文件、链接、语音各一条从企微到知识条目的端到端；
- 同一 `event_id` 重放两次只产生一份文档；
- 媒体下载失败、链接被 SSRF 拒绝、ASR 失败均有明确状态；
- 未开启 `ingest_to_kb` 的群消息不进入知识库。

### 6.3 语义去重与冲突矩阵（P1-A）

#### 6.3.1 三层验证

1. **指纹预筛**：规范化内容哈希；精确重复直接拦截；近重复进入候选。
2. **多指标**：
   - 字符/词 Jaccard；
   - 实体重叠（先做确定性词表/规则，NER 作为可选增强）；
   - 关键数字/日期/金额/阈值匹配；
   - 向量余弦。
3. **规则矩阵**：

| 向量相似 | 实体重叠 | 关键数字 | 判定 |
|---|---|---|---|
| 高 | 高 | 一致 | 真相似 → 合并去重 |
| 高 | 高 | 冲突 | 事实对冲 → 冲突裁决 |
| 高 | 低 | — | 主题不同 → 保留 |
| 低 | 高 | — | 表述差异大 → 人工复核 |

#### 6.3.2 与现有冲突判定的关系

- 现有 `KnowledgeConflictJudge` 继续做“同主体/谓词 slot”的 value/qualifier/type/temporal/
  cardinality 分类；
- 新特征层只补充 `similarity/entity/number/vector` 证据与“相似 vs 对冲”判定，
  不另起一套冲突账本；
- 低分/证据交织进入现有冲突/消解人工队列；LLM 只做仲裁建议，最终留操作人依据；
- 不把“引用过”当“采纳成功”，三态仍由服务端血缘与反馈写回。

#### 6.3.3 验收

- 矩阵四个象限各一条 fixture；
- 关键数字冲突不得被判成“同义改写”；
- 合并/拆分都写冲突账本与依据；
- 冲突检出率、误合并率进入评估读数。

### 6.4 精排（P1-B）

- 现有 `rerank_factory` / `ModelRerankRunner` 作为唯一装配口；新增具体 provider：
  - `bge-reranker`（本地/ONNX 可选）；
  - LLM 打分 provider（走现有 LLM 客户端，带超时/降级）；
- 主路严格要求：模型调用不得在事件循环内同步执行；失败回退加权并记录 `last_error`；
- 先影子运行（不改变最终 top-k），对比 recall@k、NDCG、人工抽检；达标后切主路；
- 不在调用点各写权重；权重与阈值仍单源配置。

### 6.5 版本、回滚与业务基线（P1-C）

- 条目：沿用 `revisions`；
- 事实：新增 `knowledge_fact_versions`（v19）：
  - `fact_id, version_no, change_type(create|supersede|retract|expire|rollback),
    snapshot_json, operator, reason, recorded_at`；
  - 每次 `upsert/supersede/retract/expire/rollback` 写一行；
- API：
  - `GET /knowledge/facts/{fact_id}/history`
  - `POST /knowledge/facts/{fact_id}/rollback`（管理员、带 reason）
- 业务基线：`knowledge_baselines`（baseline_id, scope, snapshot_ref, created_by, created_at），
  支持按 agent/category/时间窗冻结；不复制正文，只存引用。
- 验收：任一事实可查历史并回滚；回滚写操作人/依据/版本号；历史与当前一致。

### 6.6 存储与规模（P1-D）

#### 6.6.1 决策矩阵

| 条件 | 当前嵌入式方案 | 外部方案 |
|---|---|---|
| 单机、<100 万块、p95 可接受 | SQLite + FTS5 + hnswlib | 不迁 |
| 向量查询成为瓶颈 | hnswlib/faiss | Qdrant/Milvus |
| 多跳关系成为主查询 | SQLite + graph_walk | Neo4j（可选） |
| 多节点/高可用 | 不满足 | 外部库 + 队列 |
| 工作记忆需要跨进程 | 内存/SQLite | Redis |
| 原始文件需要共享 | 本地文件 | 对象存储 |

#### 6.6.2 边界

- 先抽 `KnowledgeStore` / `VectorIndex` / `GraphStore` 接口，迁移时替换实现，不重写业务；
- 以 1M/10M 基准、p95、并发、重建时间作为迁移门槛；
- 不把 Milvus/Neo4j 当作“设计里有就必须上”；当前 SQLite/FTS/hnswlib 已能覆盖单机中规模；
- 任何迁移都要保证回退路径与双读校验。

### 6.7 多 Agent 蜂群与 MQTT（P2-A，需拍板）

当前已有 `AgentTeam`（ACP 顺序编排）与 `SwarmManager`（主 Agent 派生子 Agent）。
若目标确实是多节点 Worker：

- Supervisor：意图理解、任务拆解、路由、结果聚合；
- Worker：检索、图谱、记忆、结构化查询、生成；
- MQTT 主题：
  - `agent/supervisor/task`
  - `agent/worker/{id}/result`
  - `agent/memory/update`
- 消息契约：`task_id, trace_id, role, payload, deadline, retry`；幂等键 `task_id`；
- 传输由 `NEUROVA_AGENT_BUS=inproc|mqtt` 装配，MQTT 参数走 `NEUROVA_MQTT_*`；
- 复用现有 ACP 消息协议作为进程内实现，MQTT 只做跨进程传输；
- 验收：任务扇出、失败隔离、重试、结果 RRF 聚合、trace 可回放。

**建议**：先用现有 AgentTeam/Swarm 满足单机需求；只有出现多节点/独立扩缩容/跨团队 Worker
时才启动本项。否则会引入消息总线运维成本而没有对应收益。

### 6.8 评估、反馈与多租户（P2-B/C）

- 评估指标：recall@k、MRR、unhit、NDCG、冲突检出率、误合并率、rerank 增益；
- 黄金集按 domain 分片；每次排序/模型/权重变更跑 baseline 对比；
- 自动 A/B：按流量分桶，先影子后切换；没有足够样本时只报“样本不足”；
- 多租户：在条目/事实/事件/索引增加 `tenant_id`，权限门在请求边界；先做读隔离，再做写隔离；
- 不把 user/agent 可见性当租户隔离的替代品。

---

## 7. 数据与 API 变更清单

### 7.1 数据

| 变更 | 类型 | 说明 |
|---|---|---|
| 条目字段 `source_type/source_path/ingest_time/author/page_count/ocr_used` | 扩展 | 文档级元数据，不新建条目库 |
| chunk `page/heading_path` | 扩展 | 与现有偏移/表头上下文字段兼容 |
| `knowledge_fact_versions` | 新表（v19） | 事实变更历史/回滚 |
| `knowledge_baselines` | 新表 | 业务场景基线引用 |
| `knowledge_ingest_jobs` | 新表 | 企微入站持久作业（dedupe/attempts/lease/dead/result） |
| `knowledge_subjects.tenant_id` | 新列（v23） | 主体消解字典按租户分词；图谱按 `agent+tenant` 分目录 |
| `tenant_id` | 后续迁移 | 先读隔离，后写隔离 |

### 7.2 API

| 端点 | 变更 |
|---|---|
| `POST /knowledge/import` | 增加 `ocr=auto|on|off`、`engine=structured|legacy`；响应返回 `document_id/pages/ocr_used` |
| `GET /knowledge/documents/{id}` | 已实现：文档级元数据、页码/块映射、租户/可见性门 |
| `GET /knowledge/facts/{id}/history` | 事实版本历史 |
| `POST /knowledge/facts/{id}/rollback` | 管理员回滚，带 reason |
| `GET /knowledge/conflicts/{id}` | 已实现：条目/事实两轴冲突详情，带特征证据/裁决依据，按租户过滤 |
| `GET /knowledge/audit/ingest` | 队列积压、失败原因、订阅者数 |
| `POST /knowledge/audit/ingest/resume` | 显式补跑待处理入站作业 |
| `POST /knowledge/audit/conflict-eval` | 带真值的四象限准确率/误合并率 |
| `POST /knowledge/audit/conflict-metrics` | 给冲突账本附人工标签，计算误合并率 |
| `POST /knowledge/audit/evaluation/compare` | 两个评测 run 的样本诚实 A/B 对照 |
| `GET /knowledge/audit/entry-feedback` | 已有；保留 |
| `/v1/quality/metrics` | 已有；保留接管/完成态/token 读数 |

---

## 8. 可观测性与 SLO

| 指标 | 采集点 | 目标 |
|---|---|---|
| 文档解析成功率/失败原因 | 标准化流水线 | 失败可归因；无静默 0 |
| OCR 覆盖率/平均置信度/耗时 | OCR 层 | 扫描件可解释 |
| 入站队列积压/重试/DLQ | 知识入站桥 | 积压可报警 |
| 检索 p95 | hybrid + API | 目标 <500ms（按规模复测） |
| 冲突检出率/误合并率 | 冲突账本 + 人工结果 | 有基线、可回归 |
| rerank 增益 | 影子/A-B | 不降 recall@k |
| 反馈采纳率/token 未归因 | 质量/token 指标 | 有分母才报率 |

---

## 9. 测试与迁移策略

### 9.1 测试

- 每种格式/OCR/清洗的 fixture 单测；
- 企微入站：文本/图片/文件/链接/语音端到端；重放幂等；失败可见；
- 冲突矩阵：四象限 fixture；数字冲突不得误合并；
- 版本回滚：历史、回滚、再读取一致；
- 检索/精排：黄金集 baseline 对比 + 影子 A/B；
- live-verify：`create_app` + `TestClient`，走 `tests/manual/_liveVerifyIsolation.isolatedDataRoot`。

### 9.2 迁移

1. 新流水线影子写入（旁路文档/块），不影响现有召回；
2. 对比新旧解析的页码/标题/召回与成本；
3. 达标后切换知识导入入口；
4. 旧数据回填按内容幂等键去重，失败项进报告；
5. 任何阶段保留关闭开关与回退到旧解析的路径。

---

## 10. 风险与回退

| 风险 | 处理 |
|---|---|
| OCR 依赖/模型体积/许可 | 可选依赖 + 特性探测；不可用诚实失败；不把 OCR 结果伪装成原文 |
| 旧版 Office 转换依赖 LibreOffice | 镜像可选安装；缺失返回 `unsupported_legacy_office` |
| 企微媒体/链接抓取安全 | SSRF 校验、大小/类型限制、隔离下载、恶意文件扫描 |
| 冲突矩阵误合并 | 先影子、阈值可回退；保留冲突账本与人工复核 |
| 多 Agent 引入运维复杂度 | 先拍板；不达标不启动；复用 ACP/现有队列 |
| 外部存储迁移 | 双读校验、可回退；按 p95/规模阈值触发 |
| 租户字段迁移 | 先读隔离、灰度写；保留旧权限语义 |

---

## 11. 待拍板事项

| 编号 | 问题 | 选项 | 拍板结果 |
|---|---|---|---|
| U1 | OCR 引擎与部署 | RapidOCR 基础 / PaddleOCR 基础 / 两者可选 | **RapidOCR 先落**（PaddleOCR 仍可选） |
| U2 | 旧版 Office 支持 | LibreOffice 进镜像 / 外部转换 / 不支持 | **LibreOffice 进镜像**（缺失时诚实失败） |
| U3 | 文档 schema 落点 | 扩展现有条目/chunks / 新建规范化文档表 | **扩展现有条目，避免双库** |
| U4 | 多 Agent/MQTT | 现在做 / 规模触发后做 / 不做 | **现在做**（进程内 ACP 默认，MQTT 可选） |
| U5 | 存储迁移 | 保持嵌入式 / Qdrant+Neo4j+MySQL / 分阶段 | **先基准，后按阈值** |
| U6 | 多租户 | 现在加 tenant / 后续产品需要再加 | **现在加 tenant**（先读隔离） |
| U7 | NER 依赖 | 规则/词表 / spaCy/Stanza / 可选模型 | **先规则，NER 可选** |

---

## 12. 建议的首批工单

1. **P0-A1**：`parse_document` 结构化接口 + 页码/标题元数据（不改聊天附件行为）；
2. **P0-A2**：RapidOCR 适配层 + 扫描 PDF/图片入口 + 失败原因；
3. **P0-A3**：清洗规则与固定样本；
4. **P0-B1**：企微 `ingest_to_kb` 配置 + `kb/ingest/wecom` 契约 + 文本入站；
5. **P0-B2**：企微图片/文件/链接/语音入站；
6. **P1-A1**：冲突特征提取（Jaccard/数字/向量）与四象限矩阵；
7. **P1-B1**：bge/LLM rerank provider + 影子对照；
8. **P1-C1**：事实版本表/历史/回滚 API；
9. **P1-D1**：1M/10M 基准与存储决策报告；
10. **P2-A1**：仅在 U4 拍板后启动 Supervisor-Worker/MQTT。

---

## 13. 实施状态（2026-10-24）

| 批次 | 状态 | 落点 |
|---|---|---|
| P0-A1/A2/A3 | 已完成 | `neurova/knowledge/document_pipeline.py`：`parse_document`、页码/标题/元数据、RapidOCR 适配、清洗；旧版 Office 走 LibreOffice |
| P0-B1/B2 | 已完成 | `ingest_bus.py`、`ingest_bridge.py`、`ingest_jobs.py`：`kb/ingest/wecom` 契约、文本/图片/文件/链接/语音、按 `source` 幂等；SQLite 入站队列（attempts/退避/dead/lease）、`GET /audit/ingest`、`POST /audit/ingest/resume` |
| P0-A 迁移回退 | 已完成 | `parse_document(engine_mode="legacy")` 运行时回退 + `scripts/knowledge_parse_compare.py` 影子对比；Docker 构建需有 Docker 环境时另跑 |
| P1-A1 | 已完成 | `neurova/knowledge/conflict_features.py` + `repository._detect_conflicts`：四象限特征与 decision |
| P1-B1 | 已完成 | `local_rerank_provider.py`（bge 本地模型，可选）、`llm_rerank_provider.py`（注入式 LLM 打分）、`main_path` 影子对照；HTTP provider 沿用 `llm/rerank_client.py` |
| P1-C1 | 已完成 | 事实库 v19：`knowledge_fact_versions`、`knowledge_baselines`；`GET /facts/{id}/history`、`POST /facts/{id}/rollback`、基线端点 |
| P1-D1 | 已完成（10M 已实测，越线） | `scripts/knowledge_scale_benchmark.py` + `knowledge_vector_benchmark.py`；FTS 100 万 p95 314.96 ms、**1000 万 2,907.58 ms**（`migrate_or_shard`）；向量 100 万 p95 0.67 ms / 1.6 GB |
| P2-A1 | 已完成 | `neurova/agent/supervisor/`：扇出、`task_id` 幂等、重试、失败隔离、RRF 聚合、trace；`buildWorkerBus` 按 `NEUROVA_AGENT_BUS=inproc|mqtt` 装配；HTTP 面 `POST /api/acp/supervisor/dispatch` |
| P2-B | 已完成 | 事实库 v20-v23：条目/FTS/事实/活动/冲突账/业务基线/主体 `tenant_id`；图谱按 `agent+tenant` 分目录；`can_view`、FTS SQL、事实读面/治理端点/图谱端点按租户过滤（跨租户 404） |
| P2-C | 已完成 | 评测：NDCG@k、按域切片、精排增益、冲突度量/标注评估端点、`compareVariants` 离线 A/B 端点与 `gateNoRegression` CI 门；A/B 改为 Welch t 检验并诚实报样本不足 |
| P0 治理租户化 | 已完成（expiry） | `/audit/expiry`、`/foundation/expiry`、`/audit/lifecycle` 按当前 tenant 过滤；`/audit/reindex` 仍为派生索引整库维护 |
| Supervisor 持久幂等 | 已完成 | `agent_supervisor_tasks` SQLite 账本；生产端点装配，跨进程/重启重放 |
| 入站常驻消费者 | 已完成 | `runIngestWorker` 随 app 启动/关停，周期补跑 pending |
| 文档详情/OCR 聚合 | 已完成 | `GET /knowledge/documents/{id}`、`/audit/ingest` 的 `documents` 统计 |
| 评估入口接线 | 已完成 | `POST /audit/evaluation/compare`、`POST /audit/conflict-metrics` 带标签；LLM 精排由 hybrid 端点注入 `llm_call` |
| 入站 MQTT 跨进程 | 已完成（可选） | `ingest_mqtt.py`：作业/结果主题、生产者与订阅端；`NEUROVA_KB_INGEST_TRANSPORT=mqtt` |
| 旧数据回填 | 已完成（工具） | `scripts/knowledge_reparse_backfill.py` dry-run/apply；`replaceDocumentParsing` 保留页码块与 revision |
| 冲突详情/基线时间窗 | 已完成 | `GET /conflicts/{id}`；`createBaseline` 支持 `time_from/time_to` |

仍留的口子（不是静默遗留）：

- 1000 万条已实测 p95 2,907.58 ms，判 `migrate_or_shard`；外部存储/分片迁移未在本轮
  实施（无部署目标），达到该规模前先按报告启动迁移批次并保留双读/回退；
- 入站队列为 SQLite 单机语义；常驻消费者已接，跨进程传输已提供可选 MQTT
  （`NEUROVA_KB_INGEST_TRANSPORT=mqtt`），但真实 broker 端到端未在本机验证；
- `/audit/reindex` 是派生索引整库维护，未按租户切分（不写业务内容）；
- 冲突详情端点、基线时间窗已补；基线 category 维度因事实行没有 category 列未做；
- 旧数据批量回填已提供 dry-run/apply 脚本（`--source-root` 解析相对 source_path），
  但未在生产语料上执行；
- MQTT 入站端到端未接真实 broker；paho 未装时生产者/订阅端显式报依赖缺失；
- `compareVariants` 已接 API，但尚未作为 CI 回归门；
- 向量路 hnswlib 已实测（100 万 p95 0.67 ms / 1.6 GB）；多进程并发与重建时间未测；
  外部存储迁移未实施（10M FTS p95 已越线，需单独立项）；
- MQTT 传输保持可选（按拍板）：未装 `paho-mqtt` 时 `dependency_missing` 显式报错，
  进程内 ACP 路径不受影响；`NEUROVA_AGENT_BUS=mqtt` 时读 `NEUROVA_MQTT_*` 配置；
- NER 保持规则/词表（按 U7），模型实体识别列为后续可选；
- 渠道租户来自适配器 `extra.tenant_id`，未配置时落 `default`；
- 事实回滚语义已拍板为**只恢复目标事实**：派生事实与推导账本不自动复活，
  历史保留/压缩策略未做自动清理（保留全量历史）；
- Docker 镜像未在本机构建（无 Docker），镜像内 LibreOffice/OCR 库真跑未验；
- 文档核心属性已从 DOCX/PDF 读取（标题/作者/创建/修改）；扫描型 PDF 的元数据
  依赖渲染器返回，缺失时为空；
- 主体/图谱租户隔离已完成（v23 + per-tenant 图目录），旧默认图谱保持原路径。

> 本文是升级设计，不是实施授权。落地时仍按 `AGENTS.md`：单任务单提交、先红后绿、
> A/B、live-verify、变更可回退。
