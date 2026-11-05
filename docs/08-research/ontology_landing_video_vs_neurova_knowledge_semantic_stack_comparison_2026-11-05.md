# 视频号知识视频《Ontology 本体落地》参考架构 vs Neurova 知识语义栈 对照评测

> **对象与证据边界声明**
> - 对照对象：微信视频号 @相信就是看见 2026-08-22 发布的知识视频《Ontology 本体落地》（4 分 51 秒，1080×1264，链接 `https://weixin.qq.com/sph/ACYXSxMKJc`）。完整逐帧提取稿见 `C:\Users\xccoo\Videos\weixin_sph\ontology-bentiluo-transcript.md`（本机文件，不入仓）。
> - **对象性质**：教学参考架构，非可运行产品——无代码可克隆比对，因此**只评 Neurova 对该参考架构各维度的实现度（覆盖度），不给对象打分**。这与 KWeaver/SAG 篇"双方打分"不同，属框架适配评测。
> - 证据分级：视频侧证据 = 逐帧提取稿（画面文字 + 内嵌字幕，全量）；Neurova 侧证据 = 仓库代码 file:line 锚点 + 既有 specs/台账。研究参考文档，**不可作事实源**（依据 `docs/INDEX.md` 对 08-research 的定位）。
> - 证据边界：视频画面中以通用教学例子（客户/订单/投诉、高风险订单）呈现，未指名任何具体产品；本报告不假设视频与任何第三方产品或本仓既有对比文档有关联。

---

## §0 一页结论

**Neurova 对该参考架构的加权实现度：6.8 / 10**（十维加权，权重 100% 归一，含适用域折扣）。

三句话结论：

1. **本体语义层与入库纪律超出视频所讲**（9 档）：视频用 15 分钟讲的"业务语义 + 约束规则 + 由定义推导隐含事实"，Neurova 已有自研对应物——`ontology_terms`/`ontology_rules` 数据驱动本体、五条约束校验、Datalog 前向链 + 传递闭包 + 推导账本精确撤销，且推导事实经唯一写咽喉（admission gate）入库。这一层不是欠账，是超配。
2. **三处真实短板**，恰好都踩在视频的实战核心上：① **OWL 式条件类自动归入零实现**（视频的 HighRiskOrder `owl:intersectionOf` + `hasValue` 限制场景，Neurova 只能显式写三元组或手写规则）；② **标准栈互通弱**（SPARQL/OWL DL/SHACL 明文拒做，Turtle 仅自制子集）；③ **访问层无统一四动词入口**（query/analyze/validate/use 分散在各域路由，validate 甚至无独立端点——校验只内嵌在 admission 咙喉里）。
3. **视频"三问"Neurova 已回答两问半**：怎么落地（五层架构齐 4.5 层，缺企业数据层直连）；怎么描述（RDF/RDFS 级自研齐、OWL 级缺条件类）；用什么工具（本体工作台有、构建流水线与统一访问口缺）。

**候选 V1–V4 ＋ 缓办 V5 ＋ 不采纳三条**（§5）：补上 V1（条件类推导模板）后，视频的开场实战场景可以在 Neurova 端到端复现——这是本评测认为唯一值得尽快点单的一条。

---

## §1 对象全貌：视频给出的参考架构

视频 12 节内容压缩为一套"企业 AI 应用的 Ontology 落地参考架构"，七条支柱：

| # | 支柱 | 视频内容（对应原片时间码） |
|---|---|---|
| P1 | 本体职责定义 | 业务语义＋约束规则＝本体的职责范围；本体＝写给 Agent 的「业务说明书」（0:13–0:28：结构/含义/约束四组问题） |
| P2 | 价值三级跳 | LV.1 看到文本片段 → LV.2 加本体看懂业务全貌 → LV.3 套规则推导隐含事实；价值落点＝Agent 执行业务操作才准确（0:28–0:42） |
| P3 | 五层工程架构 | 01 Agent 层（Planner/Reasoner/Tool Calling/LLM）→ 02 本体语义层（Class/Property/Relation/Constraints/Rules/Semantic Mapping）→ 03 标准技术层（RDF/OWL 描述语义、SHACL 校验、SPARQL 查询）→ 04 知识图谱层（Customer/Order/Product）→ 05 企业数据层（DB/ERP/CRM/API/Documents/Events）（1:13–1:40） |
| P4 | RDF 三元组 | 主语—谓词→宾语记业务事实；短板＝只有事实没有定义（1:40–2:12） |
| P5 | RDFS 定义能力 | Class/Property/subClassOf/domain/range；定义＋事实→机器推出 C01 是 Customer、D01 是 Order（2:12–2:38） |
| P6 | OWL 复杂逻辑 | 等价类 `owl:intersectionOf` ＋ `owl:Restriction`/`hasValue`：高风险订单自动归入；支持等价/互斥/逆关系/限制/逻辑组合（2:38–3:14） |
| P7 | 工具三连 | Protégé（建模 IDE，HermiT/Pellet 双推理机）→ ODK（构建流水线，类 CI/CD：构建→测试→发布）→ OAK（数据访问层：统一 API 四动词 query·analyze·validate·use ＋ OWL/SPARQL/SQLite 三适配器）（3:35–4:28） |
| P8 | 实战场景 | 一句话任务"找出最近一个月的高风险订单并查看对应客户投诉"→ 拆出 6 条前置知识 → 依赖 OWL 条件类自动归入（0:42–1:01、3:14 收束） |

---

## §2 本方基线（引用既有盘点，不重复展开）

Neurova 知识语义栈现状以下列事实源为准（全部经本报告核对锚点或引用既有已亲验盘点）：

- **双栈结构**：文档 RAG 库（`neurova/knowledge/repository.py`）＋ 三元组事实底座（`knowledge_facts.db`，表清单 `neurova/knowledge/foundation/knowledge_facts.py:42-420`：`knowledge_subjects`/`knowledge_facts`/`ontology_terms`/`ontology_rules`/`knowledge_conflicts`/`knowledge_baselines` 等，租户分区、v1–v27 零停机迁移）。
- **唯一写咽喉**：`neurova/knowledge/foundation/admission.py:284`（`KnowledgeAdmissionGate.admit`）——主体消解→本体校验→冲突判定→血缘→置信聚合五段，`RECORD_KINDS=("triple","narrative")`（:73）。
- **自研本体与推理**：`neurova/knowledge/ontology/rule_engine.py:104`（`ForwardChainingEngine`，Datalog 二元接力片段＋分层否定＋递归 CTE 传递闭包 :484；种子规则 `is_a_transitive` :66；**头部明文声明拒做 SPARQL/OWL DL/外部推理服务** :3）；推导账本 `ontology/derivation_ledger.py`（撤规则只撤其结论）。
- **五条约束校验**：`neurova/knowledge/ontology/validation.py:16`（`RULES = ("domain","range","parentConsistency","disjoint","cardinality","requiredProps")`，"未登记≠违规"保守原则 :1-10）。
- **Turtle 子集**：`neurova/knowledge/ontology/turtle.py`（`@prefix kbg:` 自制序列化/回读，零依赖）。
- **检索**：四路 RRF（`knowledge/hybrid.py:52` tfidf/BM25/FTS5/ONNX bge-small-zh-v1.5 向量）＋采纳先验重排＋歧义澄清＋0 命中脱靶登记；图谱路影子档（`hybrid.py:164-169`）。
- **记忆侧独立分库**：`memory.db` 温度衰减/贝叶斯遗忘，TKG 时序事实独立表，与知识库靠检索责任链＋token 归因桥接。
- **Agent 层**：`agent/chat_pipeline.py` 责任链四路检索＋`tool_executor.py` 治理化执行；无独立 Planner 抽象。
- **前端**：`NeurUI/src/pages/GraphWorkbenchPage.vue`（本体/实例/空间三 tab，消费 `/knowledge-graph/studio`）、`KnowledgePage.vue`、`KnowledgeEvalPage.vue`。
- **设计决策**：`docs/specs/2026-09-20-knowledge-foundation-design.md` 六项已锁定——零新增外部服务、SQLite＋本地 ONNX、**零新增第三方依赖**、形式化本体＋确定性推理属一期范围。
- **台账现状**：KWeaver 候选 C1–C6 已全部处置（`audit-reports/simplification-audit-2026-10-05.md` §6-543..549；C1 认知安全门 commit `da0548ccd` 默认 observe、C2 出口脱敏 `b6fb05379`、C6 评测台 `d9941722f`）。

---

## §3 逐维评分（十维加权，权重 100% 归一）

**适用域折扣声明**：视频面向企业 AI 应用（业务库直连、领域专家建模）；Neurova 是本地部署的多 Agent 助手（文档/对话知识、零外部服务）。涉企维度（B2/D2）按"对该产品形态的合理实现度"折算，不因"没做 ERP 直连"扣到零分。

| # | 维度（视频对应支柱） | 权重 | 实现度 | 依据与判词 |
|---|---|---|---|---|
| A1 | 本体语义层·结构：实体/关系/属性的显式定义（P1/P4） | 12 | **9.0** | `ontology_terms`（kind/parent/required_props，knowledge_facts.py:321）＋`knowledge_subjects` 规范化主体（别名/合并）＋`qualifier_json` 限定符。视频只讲到"定义类和关系"，Neurova 连主体消解、别名候选审批、术语版本都齐了 |
| A2 | 本体语义层·约束（P1"约束规则"） | 12 | **8.5** | 五条校验 domain/range/parentConsistency/disjoint/cardinality/requiredProps（validation.py:16）在 admission 咽喉**强制执行**（先于落库，比视频"事后 SHACL 校验"更硬）；扣分点：约束不可由用户在线增删（固定五条），SHACL 形状的规则化表达缺位 |
| A3 | 推理能力（P2 LV.3/P5/P6） | 15 | **6.0** | 有：Datalog 前向链＋传递闭包（`is_a` 传递 = 视频 RDFS `subClassOf` 推导的同款）＋推导账本精确撤销（比视频讲的更工程化）。**缺：OWL 等价类/限制条件类**——视频实战核心 `HighRiskOrder = Order ∩ hasRiskLevel="High"` 自动归入零实现（rule_engine.py:3 明文拒做 OWL DL，但"限制原子"不等于 OWL DL，可在现有 Datalog 片段上加规则模板而不违决策） |
| A4 | 标准栈互通（P4–P6 W3C 面） | 8 | **4.0** | Turtle 导出/回读（自制子集 `kbg:` 前缀）✓；SPARQL/OWL DL **明文拒做**（rule_engine.py:3）、SHACL 零命中。设计决策使然（零新增第三方依赖），不判为欠账，但与外部语义工具的互操作面确实窄 |
| B1 | 知识图谱层（P3 第 4 层） | 10 | **7.5** | `knowledge_subjects`＋`graph_bridge.py` LLM 抽取落 triple＋投影图（BFS/最短路/合并）＋TKG 时序事实＋`/graph/instances` 实例图 API；扣分：混合检索中图谱路影子档（graphWeight=0，转正判据在 `docs/specs/2026-10-30-knowledge-retrieval-accuracy-upgrade-plan.md`） |
| B2 | 企业数据层接入（P3 第 5 层） | 8 | **5.0** | 有：文档（PDF/MD/DOCX/OCR）/URL（SSRF 防线全接线）/MCP sources/远程 KB（RAGFlow/Dify）；缺：DB/ERP/CRM/API 事件流直连。适用域内（个人知识）属合理覆盖，故不重扣 |
| C1 | Agent 层（P3 第 1 层） | 10 | **7.0** | ChatPipeline Step0.5 安全门→四路责任链检索→Evocate 注入→LLM 循环＋治理化 ToolExecutor；扣分：无独立 Planner/Reasoner 抽象（视频将其列为架构第 1 层，Neurova 规划散在 loop_manager/supervisor） |
| C2 | 检索价值链 LV.1→LV.2→LV.3 进对话（P2） | 12 | **7.5** | LV.1→LV.2 强（四路 RRF＋采纳先验＋歧义澄清＋脱靶登记，Neurova 特色超出视频）；LV.2→LV.3 弱：推导事实虽经咽喉入库、可被 facts 面检索，但"对话中显式引用推理结论（含 derived_by 溯源）"无专门链路 |
| D1 | 访问层统一四动词（P7 OAK） | 8 | **5.5** | query 分散各域路由（/v1/knowledge*、/v1/semantic-search）；analyze 有雏形（semantic_search `/analyze`:549）；**validate 无独立端点**（校验内嵌 admission，外部不可 dry-run）；use 对应 `/facts/{fact_id}/adoption`（knowledge_core.py:359）。四动词全有对应物、无统一入口 |
| D2 | 工具链：建模 IDE ＋ 构建流水线（P7 Protégé/ODK） | 5 | **6.0** | GraphWorkbenchPage 本体工作台 ≈ 轻量 Protégé（类树/图视图/建边须证据）；KnowledgeEvalPage 评测台 ≈ ODK 的"测试"半环；**构建→基线→发布流水线缺**（`knowledge_baselines` 表已在，挂管线是空地）；无 Hermit/Pellet 类双推理机（自研单引擎） |
| — | **加权合计** | **100** | **6.8** | Σ(权重×实现度)=681 → 6.81，取 6.8 |

**分维判读**：A 段（本体语义＋约束，权重 24）均分 8.75，是全栈最强段——Neurova 把视频当"教学内容"讲的东西做成了带治理纪律的生产件。C3（推理，权重 15）是单维最大失分点。D 段（工具面，权重 13）均分 5.75，是覆盖最薄段。

---

## §4 对照视频"三问"的逐问判词

| 视频之问 | Neurova 答案 | 完成度 |
|---|---|---|
| ① 本体到底该怎么落地？ | 五层架构齐 4.5 层：Agent 层✓（无独立 Planner）、本体语义层✓（自研数据驱动）、标准技术层△（自研替代 W3C 栈）、知识图谱层✓、企业数据层△（文档/MCP 有、业务库无）。且有视频没讲的强项：唯一写咽喉＋冲突一等公民＋推导可撤销 | **高** |
| ② RDF/RDFS/OWL 怎么描述业务？ | RDF 级✓（三元组＋qualifier＋时态）；RDFS 级✓（Class/Property/subClassOf/domain/range 全有对应物，`is_a_transitive` 推导同款）；**OWL 级✗**（等价类/限制/hasValue 归入缺）；SHACL 级△（五条固定校验，不可规则化扩展） | **中高** |
| ③ 落地用哪些工具？ | 工作台有（GraphWorkbench/KnowledgeEval）；ODK 式流水线缺；OAK 式统一四动词访问口缺；无可视化推理机（HermiT/Pellet 对应物） | **中** |

---

## §5 候选清单（V 前缀，避开 KWeaver C1–C6 / SAG C1–C5 / Semantica K1–K8 既有编号）

立项纪律沿用本目录既有约定：**净接线与新能力不混批；未点单不动码**。

### 净接线（P1）

无。本报告未发现新的"零消费断点"——KWeaver 篇 N1/N2 已闭环（台账 §6-543/§6-544），视频框架照进 Neurova 未暴露新的"只写不读"。

### 新能力（P2–P3，按性价比排序）

- **V1 ·（P2）条件类推导模板——补齐视频实战核心（对应 A3 短板）**
  - 内容：在现有 Datalog 片段上增设"限制原子"规则形状（`head(X) :- body(X), X.hasRiskLevel = "High"` 同款），或提供"条件类"声明表（class ＝ 基类 ∩ 属性条件），由引擎批量推导 `X a HighRiskOrder` 类事实，推导仍走 admission 咽喉（`derived_by` 可溯、可整批撤销）。
  - 落点：`neurova/knowledge/ontology/rule_engine.py`（规则形状扩展）＋`validation.py`（条件类一致性）＋`/v1/knowledge/ontology/rules` API 与 GraphWorkbench 规则表单。
  - 不可逆点：自动归入的误报面 → 缓解：推导事实带账本、撤规则精确撤销（`derivation_ledger.py` 已有，天然兜底）；建议默认观察态（只推导记读数、不进检索主路）灰度转正。
  - 红灯判据：用视频同款场景——`Order ∩ hasRiskLevel="High"` 声明后，零显式标注自动归入 3 条高风险订单、撤规则后精确消失。
  - 影响：A3 可从 6.0 → 8.5 上下；这是全报告性价比最高的一条。
- **V2 ·（P2）validate 独立出口（对应 D1 短板）**
  - 内容：`POST /v1/knowledge/ontology/validate`——复用 `validation.py` 做 **dry-run 只读校验**（提交候选 triple 返回 violation/unregistered 定位串），供 workbench 建边前预检与外部调用。
  - 落点：`api/endpoints/knowledge_ontology.py` ＋ GraphWorkbenchPage 建边流程预检按钮。
  - 风险：只读复用既有函数，近零风险；补上后四动词中 validate 从"内嵌不可达"变"显式可达"。
- **V3 ·（P3）Turtle 全库导出与互操作 golden 测试（对应 A4）**
  - 内容：`turtle.py` 从单 fact 序列化扩展到整 schema/整库导出端点；用 golden 用例锁住语法子集与 W3C Turtle 的兼容边界（声明"可被标准解析器读入"的承诺面）。零新依赖。
  - 判据：导出文件经外部标准 Turtle 解析器无错读回，round-trip 逐条相等。
- **V4 ·（P3）本体构建流水线（对应 D2，ODK 对应物）**
  - 内容：schema/规则变更 → 五条校验 → `knowledge_baselines` 基线 → 发布 的一键管线（CLI 或管理端点），复用既有 baselines 表（knowledge_facts.py:259）。
  - 价值：把"本体也是要发布评审的工件"的纪律自动化，属治理面锦上添花。

### 缓办登记

- **V5 · 企业数据源接入器框架（DB/API 事件流 → facts）**：与"零外部服务"决策兼容但工作量大，Neurova 当前适用域内无强需求场景，等真实点单再立项。

### 不采纳登记（三条）

1. **引入 rdflib/OWL DL 推理机（Pellet/HermiT 类）**：与 specs 六项决策中"零新增第三方依赖、本地 ONNX"直接冲突；V1 的规则模板路线可拿到八成收益。
2. **SPARQL 文本查询引擎**：`rule_engine.py:3` 头部明文决策"明确不做"，且四路混合检索已覆盖主用途；不推翻既有决策。
3. **SHACL 引擎**：五条校验已覆盖 SHACL 主用途子集，且 admission 咽喉（事前强制）比 SHACL 事后校验更硬；引入第二套约束体系违反"单一事实源"纪律（教义第 6 条）。

---

## §6 本仓断点核对

- 本报告**无新增断点**。视频框架逐层照进 Neurova，未发现新的"只写不读/零调用"形态——最接近的观察是 C2 维度"推导事实进对话无显式溯源链路"，但该链路的底座（推导账本、token 归因）均已存在且被消费，属能力深度问题，归入 V1/V2 候选而非断点。
- 既有断点状态复核：KWeaver N1（cognitive_security 零消费）→ C1 已接线（§6-543，`security/cognitive_security_gate.py` 三态默认 observe）；N2（data_masking 零消费）→ C2 已单源化（§6-544）。SAG 篇 N3（FactSurface.search 零调用）**尚无台账落格条目**，不属本报告范围，此处仅登记提醒。

---

## §7 证据清单与亲验范围

**主代理亲验锚点**（2026-11-05，本报告写作时逐条 grep 复核）：

1. `neurova/knowledge/ontology/rule_engine.py:3`——头部"明确不做：SPARQL 文本查询、OWL DL 完整语义、外部推理服务、任意嵌套聚合"原文；
2. `rule_engine.py:104` `class ForwardChainingEngine`；`:66` 种子规则 `is_a_transitive`；
3. `neurova/knowledge/foundation/knowledge_facts.py:321` `ontology_terms` 表（迁移 v25 段）；`:259` `knowledge_baselines`；
4. `neurova/knowledge/ontology/validation.py:16` `RULES = ("domain","range","parentConsistency","disjoint","cardinality","requiredProps")`；
5. `neurova/knowledge/ontology/turtle.py:21` `@prefix kbg:` 自制序列化。

**引用既有已亲验盘点**（不重复取证）：代码架构全貌引自本会话并行只读盘点（两路 Explore，全部 file:line 可回查）；specs/台账状态引自 `docs/INDEX.md`、`docs/specs/*`、`audit-reports/simplification-audit-2026-10-05.md` §6-543..549。

**未取证项（如实登记）**：视频侧唯一证据源为逐帧提取稿（画面＋字幕），**口播音频未单独转写**，字幕即口播的书面形式；NeurUI 前端页面行数（KnowledgePage 2233 行等）引自盘点未逐行复核；`knowledge_facts.db` 实际库内容（存量事实规模）未取样——不影响各维度实现度判定。

---

*成文：2026-11-05。落格 `docs/08-research/`，登记 `docs/INDEX.md` §2.4。候选 V1–V5 待点单，未点单不动码。*
