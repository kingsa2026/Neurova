# 本体语义栈能力升级计划（对照评测 6.8 → ≈7.8）

> 依据：`docs/08-research/ontology_landing_video_vs_neurova_knowledge_semantic_stack_comparison_2026-11-05.md`（十维加权实现度 6.8/10）。
> 三目标映射：**高效率高可用** → B7 效率与可用性专项（实测先行）；**可拓展高评分** → B1–B6 对准评测失分维；**系统能力最大化升级** → 补齐"条件类→溯源→四动词"实战闭环。
> 纪律声明：本计划全部新能力**不引入任何第三方依赖**（specs/2026-09-20 六项决策不动）；候选编号沿用评测报告 V1–V5；批次红灯先行（先红后绿），每批可独立回滚。

---

## §0 一页结论

| 批次 | 内容 | 评测维度 | 分数影响 | 规模估计 |
|---|---|---|---|---|
| B1 | 条件类推导模板（V1，视频实战核心） | A3 推理 6.0→8.5 | +3.75 | 中 |
| B2 | ontology validate dry-run 出口（V2） | D1 | +0.8 | 小 |
| B3 | 四动词统一门面 `/v1/knowledge/access/*` | D1 5.5→8.0（含 B2） | +1.2 | 小 |
| B4 | 推理结论溯源进对话 | C2 7.5→8.5 | +1.2 | 中 |
| B5 | Turtle 全库导出＋互操作 golden | A4 4.0→6.0 | +1.6 | 小 |
| B6 | 本体构建流水线（baselines 挂管线） | D2 6.0→7.5 | +0.75 | 中 |
| B7 | 效率可用性专项＋图谱影子转正执行 | B1维 7.5→8.5（判据通过才计） | 0～+1.0 | 中 |

**分数投影：6.8 → ≈7.8**（B7 图谱转正不通过则 ≈7.7）。投影逐维明细见 §3，评分口径与权重沿用评测报告不动。

---

## §2 代码特点适配声明（本方案与仓库纪律的咬合点）

| 仓库特点 | 本方案的适配动作 |
|---|---|
| 规则是数据（`ontology/rule_engine.py:3` "规则形状固定为 Datalog 片段"，明文拒做 SPARQL/OWL DL/外部推理服务） | B1 不破该边界：条件类做成**新规则形状**（限制原子），仍是 ≤2 原子的 Datalog 片段；不引入 OWL 语义，不改头部声明 |
| 唯一写咽喉（`foundation/admission.py:284`，五段：消解→校验→冲突→血缘→置信） | B1 推导事实照旧走 `_admitDerivedFact`（带 `derived_by`），**不开第二个写口**；B2 validate 是纯只读，不经咽喉 |
| 推导账本精确撤销（`ontology/derivation_ledger.py:26` `knowledge_derivation_edges`、`ontology_rule_fires`） | B1 的安全网直接复用：撤规则只撤其结论；B4 溯源直接读账本，不新增溯源存储 |
| schema 变更走 `core/db_migration.py` 域注册表（PRAGMA user_version＋防降级守卫） | 若 `ontology_rules` 现有列不可承载条件参数，走注册表顺延新版本号（以现场现值为准，**不手写 IF NOT EXISTS**） |
| 深模块＋`agent_ref` 注入；`agent_core.py` 尺寸棘轮（只降不升） | B4 检索标注逻辑落独立模块（`neurova/knowledge/` 侧），**不回填 agent_core.py**；一切经既有 adapter（`agent/knowledge_retriever_adapter.py`）接线 |
| 可选依赖惰性 import＋fail-soft | B5 golden 测试的 rdflib 对拍为**可选测试**：未安装则 skip（pytest skipif），产品代码零依赖不变 |
| 灰度三态先例（`security/cognitive_security_gate.py` off/observe/enforce；`hybrid.py` 图谱影子档 `GRAPH_ROUTE_WEIGHT_ENV` 默认 0） | B1 推导默认**观察态**（记账不进检索主路），B7 转正判据通过才翻默认；环境变量命名沿用 `NEUROVA_*` 惯例 |
| 单一事实源（教义第 6 条）、同功能先比后合（第 7 条） | B3 四动词门面是**接线不是第二实现**：路由转发既有端点，零新逻辑；不采纳独立的条件类新表（见 §4 拍板项 1） |
| 测试落位 `tests/unit/<模块>/`、性能落 `tests/performance/`；新端点三处登记（路由＋API 文档＋前端消费） | 每批红灯文件给出确切路径；B2/B3 新端点同步登记 `docs/02-api/API_REFERENCE.md` |
| 提交纪律：净 LOC ≤0 默认、单任务单 commit、`--only -- <paths>` | 每批一个 commit；B3 门面属纯接线（净增少量路由代码），提交说明逐条列明去向 |

---

## §3 分数投影明细（口径：评测报告 §3 十维加权，权重不变）

| 维度 | 权重 | 现值 | 投影 | 驱动批次 |
|---|---|---|---|---|
| A1 本体结构定义 | 12 | 9.0 | 9.0 | — |
| A2 约束规则 | 12 | 8.5 | 8.5 | —（B1 增条件类一致性校验，属 A3 收益） |
| A3 推理能力 | 15 | 6.0 | **8.5** | B1 |
| A4 标准栈互通 | 8 | 4.0 | **6.0** | B5 |
| B1维 知识图谱层 | 10 | 7.5 | 8.5（判据通过才计） | B7 |
| B2维 企业数据层 | 8 | 5.0 | 5.0 | —（V5 缓办） |
| C1 Agent 层 | 10 | 7.0 | 7.0 | —（Planner 抽象不纳入本批） |
| C2 检索价值链 | 12 | 7.5 | **8.5** | B4 |
| D1 四动词访问层 | 8 | 5.5 | **8.0** | B2＋B3 |
| D2 工具链 | 5 | 6.0 | **7.5** | B6 |
| **合计** | 100 | **6.8** | **≈7.8**（图谱不转正 ≈7.7） | |

---

## §4 拍板记录（2026-11-05 已裁：四项均按推荐选项 A 执行）

> 裁决原文："待拍板问题按推荐来"。各选项利弊与不可逆点分析保留如下，作实施对照依据。

1. **条件类的存储形态**——**已裁：选项 A**。扩展 `ontology_rules` 行的形状枚举＋条件参数（列不足则走迁移注册表）。理由：坚持"规则是数据"原则，复用规则生命周期（版本/触发审计/精确撤销），无第二事实源。代价：规则行结构变复杂，引擎求值分支＋1。影响面：改 `rule_engine.py` 求值器＋`validation.py` 一致性项。否决项：独立 `condition_classes` 新表（与规则体系并存即双事实源，违教义第 6 条风险，且落表后收口需迁移）。
2. **B1 推导的默认态**——**已裁：选项 A**。观察态灰度：推导照常记账（账本可查），检索主路默认排除推导事实，环境变量（`NEUROVA_CONDITION_CLASSES_ROUTE`）翻主路。先例：认知门三态、图谱影子档。不可逆点：无（双向可翻）。否决项：直接进主路（误归入面直接暴露给对话）。
3. **四动词门面形态**——**已裁：选项 A**。新增 `/v1/knowledge/access/{query|analyze|validate|use}` 纯转发门面，OpenAPI 汇总，旧路由不动。理由：补"统一入口"评测短板且零迁移成本；旧消费方零破坏。否决项：只补 validate 不做门面（D1 停在 6.5 左右，统一入口短板保留）。
4. **B4 溯源呈现深度**——**已裁：选项 A**。后端契约先行：检索 payload 对 `derived_by` 事实带推导标注（规则号＋前提数），前端本轮只加引用行内标注。完整溯源卡片（规则链可视化）放下一批。不可逆点：无。

---

## §5 批次详设

### B1 条件类推导模板（A3：6.0→8.5）

- **现状与证据**：引擎只认三种形状（二元接力/直接搬移/分层否定，`rule_engine.py:3`）；种子规则仅 `is_a_transitive`（:66）；视频实战 `HighRiskOrder = Order ∩ hasRiskLevel="High"` 无法表达——只能显式写三元组。
- **设计**：
  1. 新规则形状 `restriction`：`head(X) is_a CondClass :- X is_a Base, X <predicate> <value>`（≤2 原子，落在既有形状约束内）；条件参数随规则行存储（形态按 §4 拍板项 1）。
  2. 求值：复用现有递归 CTE 求值管线，产出推导事实 `X is_a CondClass`，照旧经 `_admitDerivedFact` 入库（`derived_by`＝规则号＋版本）。
  3. 观察态（§4 拍板项 2）：`knowledge_retriever_adapter` 对 `derived_by` 非空事实默认过滤（`NEUROVA_CONDITION_CLASSES_ROUTE=0` 默认，翻 1 进主路）；账本与 API 查询不受过滤影响。
  4. `validation.py` 增一致性项：条件类的 Base/predicate 必须为已登记术语（沿用"未登记≠违规"保守原则）。
- **落点**：`neurova/knowledge/ontology/rule_engine.py`、`validation.py`、（如需 schema）`foundation/knowledge_facts.py` 走迁移注册表；`agent/knowledge_retriever_adapter.py` 过滤开关。
- **测试（先红后绿）**：红灯 `tests/unit/knowledge/ontology/test_conditionClassDerivation.py`——视频同款场景：Order＋hasRiskLevel=High 声明后，3 笔订单中 1 笔自动归入 HighRiskOrder；撤规则后该推导事实精确消失（账本断言）；观察态下检索主路不含推导事实、翻开关后含。绿灯后补 `test_ontologyValidateConditionClass.py`（一致性项）。
- **效率与可用性**：条件类求值与既有规则同批执行（无额外全表扫）；规则触发已有 `ontology_rule_fires` 审计；撤销即时。
- **验收（live-verify）**：真后端 9527 → `POST /v1/knowledge/ontology/rules` 建条件类规则 → `/graph/instances` 可见推导实例 → 撤规则复现消失；命令与输出原文进提交说明。

### B2 ontology validate dry-run 出口（D1 分项）

- **现状与证据**：五条校验只在 admission 咙喉内强制（`validation.py:16`），外部无法只读试算；评测 D1"validate 无独立端点"。
- **设计**：`POST /v1/knowledge/ontology/validate`——入参候选 triple（含 draft 条件类规则，B1 联动 preview：该候选会命中哪些条件类）；纯只读调 `validation.py` 校验器＋术语登记表，返回 violation/unregistered 定位串（沿用其消息形态）。不经咽喉、不落库。
- **落点**：`api/endpoints/knowledge_ontology.py`；登记 `docs/02-api/API_REFERENCE.md`。
- **测试**：红灯 `tests/unit/knowledge/test_ontologyValidateEndpoint.py`——domain 违规/未登记/干净三例＋条件类 preview 一例；性能冒烟（<50ms/10 条候选，SQLite 本地读）。
- **效率与可用性**：只读事务＋现有连接池；无状态可水平扩；fail-soft：校验器异常返回显式 5xx 与原因（不吞）。

### B3 四动词统一门面（D1：5.5→8.0，含 B2）

- **设计**：`/v1/knowledge/access/{query|analyze|validate|use}` 纯转发：query→既有 facts 检索路由、analyze→`semantic_search_api.py:549 /analyze`、validate→B2、use→`knowledge_core.py:359 /facts/{fact_id}/adoption`。零新逻辑、零 schema；OpenAPI 汇总一段"四动词语义"。
- **落点**：`api/endpoints/knowledge_access_facade.py`（新模块，避免 knowledge_core 继续膨胀）；注册进 `api/endpoints/__init__.py:233 ENDPOINT_MODULES`；登记 API 文档。
- **测试**：红灯 `tests/unit/api/test_knowledgeAccessFacade.py`——四动词各一例转发断言（复用 httpx 路由测试惯例）＋未知动词 404＋旧路由回归不受影响。
- **纪律**：属"接通"非平行体系（教义第 7 条）——门面不复制任何业务逻辑；旧路由保留为直接入口，两处消费同一实现。

### B4 推理结论溯源进对话（C2：7.5→8.5）

- **现状与证据**：推导事实带 `derived_by` 入库、账本两表在册，但 chat 检索 payload 不区分推导/显式，对话引用无溯源。
- **设计**：
  1. `neurova/knowledge/` 侧新模块 `derivation_citation.py`：输入检索结果集，产出逐条标注（isDerived/规则号/前提事实数），纯函数、深模块。
  2. `agent/knowledge_retriever_adapter.py` 调用该模块把标注带入 payload（经 `agent_ref` 既有管线，不改 agent_core）。
  3. 前端引用行内标注「推导」徽标（最小改动，§4 拍板项 4 选 A）。
- **测试**：红灯 `tests/unit/knowledge/test_derivationCitation.py`（混合集标注正确性＋空集边界）；adapter 层 `tests/unit/agent/` 现有知识检索测试面补断言。
- **效率**：标注为 O(n) 内存计算，无新查询；与 B1 观察态解耦（显式 is_a 推导同样获得溯源）。

### B5 Turtle 全库导出＋互操作 golden（A4：4.0→6.0）

- **设计**：
  1. `ontology/turtle.py` 扩展 `serializeAll(tenantId)`：schema（ontology_terms＋条件类规则）＋全量 facts 逐条三元组，沿用 `@prefix kbg:` 约定。
  2. 端点 `GET /v1/knowledge/ontology/export.ttl`（管理面，走既有鉴权）。
  3. golden 用例：固定小库 → 固定 .ttl 快照（字符级）；互操作对拍为可选测试：`pytest.importorskip("rdflib")` 后 round-trip 解析比对（惰性可选依赖惯例，产品零依赖不变）。
- **测试**：红灯 `tests/unit/knowledge/ontology/test_turtleExport.py`（escape 边界/多租户隔离/round-trip）。
- **登记**：导出承诺面（语法子集边界）写入 `docs/02-api/` 该端点条目。

### B6 本体构建流水线（D2：6.0→7.5）

- **设计**：`POST /v1/knowledge/ontology/pipeline/run`——单事务内：schema/规则变更集 → B2 dry-run 校验（violation 即拒）→ `knowledge_baselines`（knowledge_facts.py:259）快照写入 → 返回基线号＋变更摘要；提供 `GET .../pipeline/diff?fromBaseline=..`（两基线间 terms/rules 差异）。复用 baselines 表，无新表。
- **落点**：`foundation/knowledge_facts.py`（如需列扩展走迁移注册表）、`api/endpoints/knowledge_ontology.py`、`knowledge/ontology/` 新模块 `pipeline.py`。
- **测试**：红灯 `tests/unit/knowledge/ontology/test_ontologyPipeline.py`——违规变更整批拒（不落半态）、基线快照可 diff、幂等重复 run。
- **效率与可用性**：单事务原子（快照即回滚点，对应 ODK"发布"；失败不产生半发布态）；基线查询走只读。

### B7 效率与可用性专项＋图谱影子转正执行

- **实测先行原则**：本批**先建基线，后动优化**；无基线证明的瓶颈不动手。
  1. `tests/performance/knowledge/test_admissionThroughput.py`：批量准入吞吐基线（当前 `admission.admit` 单条路径）；若基线证明批量摊薄事务收益 ≥30%，再落 `admitBatch`（同事务多 triple，逐条 finding 独立返回）；否则登记"实测无瓶颈"收批。
  2. `admitBatch`（若立项）：供 `ingest_worker` 批量路径消费，单条失败不拖批（fail-soft 契约：逐条 finding，不整批回滚语义事实）。
  3. 可用性契约测试：admission 异常→ingest 队列重试路径（`ingest_queue/ingest_worker` 既有件）断言不丢事件；validate/导出只读端点异常显式 5xx。
- **图谱影子转正执行**（引用 `docs/specs/2026-10-30-knowledge-retrieval-accuracy-upgrade-plan.md` 已定判据，不另立标准）：跑 `retrieval_metrics.py` 影子读数（overlap_at_k 等）积累窗口，判据通过 → `GRAPH_ROUTE_WEIGHT_ENV` 类环境变量默认值 0→配置化默认权重（灰度可回滚，双向）；判据不通过 → 登记"未达标原因"收批，B1维 维持 7.5。
- **测试**：性能基线本身即红灯起点（先有数，后有改）；转正开关翻动前后各跑一次检索回归套件（A/B 自证：`git stash push <files> && pytest <套件> && git stash pop`，失败集合逐行比对）。

---

## §6 不纳入本批（登记理由）

| 项 | 理由 |
|---|---|
| C1维 Agent 层 Planner/Reasoner 抽象 | 独立大工程，涉及 chat_pipeline 结构重排与尺寸棘轮联动，另行立项；本批 C1 维维持 7.0 |
| V5 企业数据源接入器（DB/ERP/事件流） | 适用域内无强需求场景，等真实点单（评测报告缓办登记不变） |
| OWL DL 语义/SPARQL 引擎/SHACL 引擎 | 评测报告不采纳三条维持（六项决策＋rule_engine.py:3 边界声明＋单一事实源纪律） |
| A2 固定五条校验的"用户自定义约束" | 与 B1 条件类一致性项有重叠，等 B1 落地后按真实需要重评 |

---

## §7 实施顺序与依赖

```
B2（最小，先行）→ B1（拍板项1/2后）→ B3 → B4 → B5 → B6 → B7
   └─ B1 的 preview 联动可回补进 B2；B7 与 B1–B6 无代码依赖，可并行（先建基线）
```
每批独立 commit、独立可回滚；共享文件（`knowledge_facts.py`、`knowledge_ontology.py`）提交前 A/B 自证。

## §8 验收门（全批收官判据）

1. 每批红灯→绿灯实测输出进对应 commit 说明；净 LOC 去向逐条列明。
2. live-verify（教义第 4 条）：真后端 9527 走真端点——建条件类规则→dry-run 校验→四动词门面→导出 .ttl→流水线基线，全链命令＋输出原文归档。
3. 回归：`tests/unit/knowledge/`、`tests/unit/agent/` 全绿（预存失败清单先行对表，新增失败为零）；前端门 `npm run test`＋`npx vue-tsc --noEmit`（B4/B2 前端消费批次）。
4. 评分复评：按评测报告同一权重口径复算十维，投影偏差 >0.3 的维度写偏差归因。

## §9 台账落格约定

每批闭环后落 `audit-reports/simplification-audit-2026-10-05.md`，编号**自现场现值顺延**（当前已知最大 §6-549；提交前 grep 现值防撞号）；拍板项 1–4 的裁决记录随首批实施条目一并落格。

## §10 实施台账（2026-11-05 复算回写）

| 批次 | 状态 | 红灯→绿灯证据 | live-verify | 与票面的偏差 |
|---|---|---|---|---|
| B1 条件类推导 | 已落（引擎/写面/读面） | `test_conditionClassDerivation.py` 11 格全绿（登记即推导、低风险不归入、不动点、撤规则只撤结论、形状四道写入口拒） | 活体：`POST /ontology/pipeline/run` 建条件类规则 → `/graph/instances` 两笔实例 → `export.ttl` 内 `HighRiskOrder` 命中 4；撤规则后 4→3（差恰为那条推导），原始主体键仍在 | **观察态落点改判**：票面写"检索主路在 `knowledge_retriever_adapter` 过滤"，实测该处今天到不了推导事实（chat 主路只出条目，`mergeIntoLegacy` 生产零调用，推导行是 `record_kind='triple'` 永不成条目的治理行）。唯一"事实→检索条目形状"出口是 `read_surface.FactSurface.search` ⇒ 过滤落在那儿（见 B4 行） |
| B2 validate dry-run | 已落 | `test_ontologyValidateEndpoint.py` 9 格绿（domain 违规/未登记/干净/性能冒烟＋校验器异常显式 500） | 活体 `POST /ontology/validate` status=200 verdict=violation（不抛异常） | — |
| B3 四动词门面 | 已落 | `test_knowledgeAccessFacade.py` 7 格绿 | 活体：query/analyze/validate 各 200、`use/{fact_id}` 200 且回执带 fact_id、未声明动词 404 | — |
| B4 溯源进对话 | **后端契约已落，对话前端本轮不接** | 新判据两档：`test_derivationCitation.py` 7 格（纯模块契约）＋ `test_factSurfaceDerivationGovernance.py` 5 格（读面行为，**不 import 待建模块**，红在断言上：3 failed→5 passed） | 活体：观察态读面 2 条 / 翻主路 3 条 / 其中推导 1 条；标注 `{'derived': True, 'ruleId': 'high_risk_order', 'premiseCount': 2}`；显式 2 条均 `{'derived': False}` | **对话引用行不接线**：chat 回合的引用面（`knowledge_citation_ids`/`knowledge_lineage_ids`）今天只挂条目 id，而条目治理行不是推导事实 ⇒ 徽标接上去就是"永不点亮的面板灯"（§2 断点）。溯源可见面现役在知识工作台 `KnowledgeLineageDrawer.vue`（`knowledge.lineageDerivedBy`，11 语言已在册）。要真做"对话内溯源"，前置是"事实进主路"，那是被 011 用真数据否证过的排序问题，另批 |
| B5 Turtle 导出 | 已落（**端点本轮补上**） | `test_turtleExport.py` 12 格绿（含 `TestExportEndpoint` 3 格：media_type/403/租户隔离；红形态=404 Not Found，绿后逐字节确定性保持）；`test_rdflibInterop.py` 在**未装 rdflib 的本机 skip** | 活体：`GET /ontology/export.ttl` 200＋`text/turtle; charset=utf-8`，文档 8090 字符可被本仓 `parseTurtle` 读回 | 上一批只落模块（测试 docstring 自陈"路由由主会话统一挂"）⇒ 本轮补 `GET /ontology/export.ttl` 并登记语法子集边界。rdflib round-trip 本轮**未实跑**（依赖缺席），"roundtrip 通过"是上一会话读数 |
| B6 构建流水线 | 已落 | `test_ontologyPipeline.py` 13 格绿 | 活体：run 200（applied terms=3 rules=1，基线号 `kb_…`）；违规候选整批拒 400 且**导出逐字不变**（零落盘）；diff 200 | 票面未提的形状缺口本轮补：`PipelineRuleRegistration` 与 `RuleWriteRequest` 都缺 `head_object_const` ⇒ 条件类规则经 REST 登记不出来（活体第一版当场 400 在此）。补栏后 `test_ontologyWriteSurface.py` 新增条件类登记＋PUT 保留现值两格绿；流水线 diff 字段随之加 `head_object_const` |
| B7 效率与可用性 | 已落（含 admitBatch 立项并交付） | 基线 `test_admissionThroughput.py` 实测 185–199 facts/s（落账读数 190.7）；**摊薄实测 +329%**（代理连接形态，反证格抓到"只覆 `commit()` 不改 `__exit__` ⇒ 两侧同路"的假结论后复测）⇒ 过 30% 门槛 ⇒ 落 `admitBatch`；交付判据改向：`admitBatch` vs 逐条 `admit` 实测 **+220%**（199.5→639.2 facts/s），仍过门槛。语义判据 `test_admissionBatchCommit.py` 6 格绿（全批落定／空批／拒因留名／**坏一条连它已写下的半条一起退**／批后不留未提交事务／单条 admit 仍即时提交） | 活体：`admitBatch` 30 条经生产闸全落（ok=30/30）；`data/` 内容指纹跨两次活体一致（`595dbb4e…`）⇒ 仓内真库未被写 | 变异探针：把批量档摘掉（`scope=None`）⇒ 恰红两格（半条回退格＋finding 下标格），证判据咬的是机制不是名字。图谱影子转正**不在本批复算**：已由 `0416a9031`（SAG C1 实测达标，`NEUROVA_KB_GRAPH_ROUTE` 默认 on、权重默认 0.10）闭环 |

**B7 未做的一半（如实登记）**：可用性契约里"admission 异常→ingest 队列重试不丢事件"未新增判据——现役 `test_ingest_queue.py`／`test_ingest_jobs_queue.py` 已钉 lease 过期重取、`nack` 重试到死信、启动对账复位，`test_extractOnUpdateAndAsync.py` 已钉抽取失败 fail-soft 与 `extract_failed` 口径；本轮复算没发现"事件被静默丢弃"的活缺口，故不新造第二套判据（教义第 6 条）。若要把"抽取失败不重试"改判成重试，那是产品语义变更，另批拍板。

## §11 本批扫荡出的三处仍开（2026-11-05 现测）

1. **endpoints 同层交叉常驻红**：`knowledge_core.py:1136` 函数内 import `knowledge_ingestion`（`extract_after_update`/`extract_event_summary`），由 `6632c6560`（SAG C2+C3）带入，守卫 `test_endpoints_module_layering.py[knowledge]` 自此一直红。修法按守卫原话"共享需求下沉共享层"，但要连依赖一起搬（`_try_extract_to_graph`／`_default_llm_call`／`_resolve_runtime_agents`）并改 6 个测试档的 monkeypatch 目标与 `test_knowledge_reexport_contract.py` 的归属表——属另一批的根因，本轮未动，等点单。
2. **PUT 规则省略 body 是坏支路**：`update_ontology_rule` 用 `existing.get("body")` 兜现值，而 `_hydrate` 出来的是 `{kind,predicate,…}` 作者态之外的形状，`_parseBody` 只认 `atom`/`not` ⇒ 省略 body 的改版当场 400。现役测试一律显式带 body，所以从没踩过。本轮只在判据里按实况注明，未修。
3. **身份面两格常驻红**（`test_requestUserIdEntryConsistency`／`test_turnIdentitySingleSource`）：登记表白名单与实装写者不一致，A/B 复算为 HEAD 自带，与本体栈无关。
