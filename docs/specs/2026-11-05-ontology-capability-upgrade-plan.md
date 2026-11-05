# 本体语义栈能力升级计划（对照评测 6.8 → ≈7.8）

> 依据：`docs/08-research/ontology_landing_video_vs_neurova_knowledge_semantic_stack_comparison_2026-11-05.md`（十维加权实现度 6.8/10）。
> 三目标映射：**高效率高可用** → B7 效率与可用性专项（实测先行）；**可拓展高评分** → B1–B6 对准评测失分维；**系统能力最大化升级** → 补齐"条件类→溯源→四动词"实战闭环。
> 纪律声明：本计划全部新能力**不引入任何第三方依赖**（specs/2026-09-20 六项决策不动）；候选编号沿用评测报告 V1–V5；工作包红灯先行（先红后绿）；所有工作包按 §16 在同一次执行内完成，不分批交付，整次收口。
> **交付模型**：一次执行、一次收口；B1–B14 与 UI-0–UI-4 是工作包编号，不是交付批次；执行顺序与停止条件见 §16。本文的“批次”只在两处使用：①“交付批次”＝禁止，统一一次执行；②“数据批次/source batch”＝适配器一次 fetch 的行集，与交付无关；“本批/批次详设”等残留一律指工作包。
> 2026-11-05 复核新增 **B8 关系映射层补全**（关系层级/逆/对称/传递/函数（`cardinality=1`）/别名/外部 IRI/未知关系候选；待拍板项见 §4，详设见 §5 B8）。B8 为增补工作包，不改变 B1–B7 已落状态与 6.8→≈7.8 的既有投影，增量按 §8 第 4 条复评后另计。
> **L0–L9 分层目标架构**（CQ/upper-lite/TBox/ABox/约束/推理/访问/互操作/治理/评估）见 §12；B9–B13 是工作包；B14 见 §14。
> **B14 企业数据源接入器＋源库 schema 映射**只预留接口与映射描述符，不接真实 DB/ERP/事件流；详设见 §14。
> **前端 UI 对齐设计**见 §15；UI-0–UI-4 在同一次执行内跟随 B9–B14 完成。
> 知识库未接线/默认关闭审计的核实结论与并入点见 §13（K-01–K-10、D 组）；非本体项不重复立项。
> **执行入口**：执行 Agent 先读 §16（一次性顺序/停止条件/收口），再按 §5、§12、§14、§15 的详设落码。

---

## §0 一页结论

| 工作包 | 内容 | 评测维度 | 分数影响 | 规模估计 |
|---|---|---|---|---|
| B1 | 条件类推导模板（V1，视频实战核心） | A3 推理 6.0→8.5 | +3.75 | 中 |
| B2 | ontology validate dry-run 出口（V2） | D1 | +0.8 | 小 |
| B3 | 四动词统一门面 `/v1/knowledge/access/*` | D1 5.5→8.0（含 B2） | +1.2 | 小 |
| B4 | 推理结论溯源进对话 | C2 7.5→8.5 | +1.2 | 中 |
| B5 | Turtle 全库导出＋互操作 golden | A4 4.0→6.0 | +1.6 | 小 |
| B6 | 本体构建流水线（baselines 挂管线） | D2 6.0→7.5 | +0.75 | 中 |
| B7 | 效率可用性专项＋图谱影子转正执行 | B1维 7.5→8.5（判据通过才计） | 0～+1.0 | 中 |
| B8 | 关系映射层补全（层级/逆/对称/传递/函数/别名/外部 IRI/候选） | A1/A2/A3/A4 结构补全 | 复评后计（不预设） | 中 |
| B9 | L0/L1 基础层：CQ 目录＋领域边界＋术语表＋upper-lite＋身份判据 | A1/D1 基础补全 | 复评后计（不预设） | 中 |
| B10 | L2/L4 术语与约束层：SKOS 多语言/版本化 IRI/模块化＋形状注册表 | A1/A2 | 复评后计（不预设） | 大 |
| B11 | L3/L5 断言与推理层：双时态查询/限定关系 schema/事件时间＋OWL 2 RL 子集/解释链 | A3/B1维 | 复评后计（不预设） | 大 |
| B12 | L6/L7/L8 访问互操作治理：稳定 IRI/分页投影＋JSON-LD/OWL/SHACL/PROV＋回滚/审计/语义版本 | A4/D1/D2 | 复评后计（不预设） | 大 |
| B13 | L9 评估层：CQ 测试/负例/golden/OOPS!/OntoClean/OQuaRE/NDCG A/B | D2/评估面 | 复评后计（不预设） | 中 |
| B14 | 企业数据源接入器＋源库 schema 映射（接口预留，不接真实源） | A4/D2/B2维 接口骨架 | 复评后计（不预设） | 中 |

**分数投影：6.8 → ≈7.8**（B7 图谱转正不通过则 ≈7.7）。投影逐维明细见 §3，评分口径与权重沿用评测报告不动。
**B8–B14 为 2026-11-05 增补工作包，与 B1–B7 在同一次执行内完成（§16）；不改变上述 B1–B7 基线，增量按 §8 第 4 条同一权重口径复评后另计，不预先承诺分数。**

**一次性执行顺序（速览）**：Preflight → B8(v29) → B9(v30) → B10(v31) → B11(v32) → B12(v33) → B14(v34) → B13 → UI-0→UI-4 → Final gates（详见 §16）。

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
| 测试落位 `tests/unit/<模块>/`、性能落 `tests/performance/`；新端点三处登记（路由＋API 文档＋前端消费） | 每个工作包红灯文件给出确切路径；B2/B3 新端点同步登记 `docs/02-api/API_REFERENCE.md` |
| 提交纪律：净 LOC ≤0 默认、单任务单 commit、`--only -- <paths>` | 每个工作包一个 commit（同一分支，最终统一收口）；B3 门面属纯接线（净增少量路由代码），提交说明逐条列明去向 |
| 关系词表与抽取映射（`ontology_terms(kind='relation')`＋`graph_bridge` 的 1:1 名称映射） | B8 只扩词表与映射元数据，不新建第二套关系体系；未知关系进候选面而非静默丢弃；函数属性复用既有 `cardinality=1`，不新增同义列 |
| L0–L9 分层架构（CQ/upper-lite/TBox/ABox/约束/推理/访问/互操作/治理/评估） | B9–B13 逐层落，B14 预留企业源接口；新能力零新增第三方依赖；upper-lite 不整包引 BFO，形状不引第三方 SHACL 引擎，导出只作互操作声明；每层缺口先有红灯判据再落码 |
| 企业数据源接入（V5）与源库 schema 映射 | B14 只预留 `EnterpriseSourceAdapter` Protocol、JSON 映射描述符、fake adapter 与 admission 接线；不引 DB 驱动/消息中间件，真实连接器另立项 |

---

## §3 分数投影明细（口径：评测报告 §3 十维加权，权重不变）

| 维度 | 权重 | 现值 | 投影 | 驱动工作包 |
|---|---|---|---|---|
| A1 本体结构定义 | 12 | 9.0 | 9.0 | — |
| A2 约束规则 | 12 | 8.5 | 8.5 | —（B1 增条件类一致性校验，属 A3 收益） |
| A3 推理能力 | 15 | 6.0 | **8.5** | B1 |
| A4 标准栈互通 | 8 | 4.0 | **6.0** | B5 |
| B1维 知识图谱层 | 10 | 7.5 | 8.5（判据通过才计） | B7 |
| B2维 企业数据层 | 8 | 5.0 | 5.0 | B14 只预留接口，不接真实源，分数不预设 |
| C1 Agent 层 | 10 | 7.0 | 7.0 | —（Planner 抽象不纳入本次执行） |
| C2 检索价值链 | 12 | 7.5 | **8.5** | B4 |
| D1 四动词访问层 | 8 | 5.5 | **8.0** | B2＋B3 |
| D2 工具链 | 5 | 6.0 | **7.5** | B6 |
| **合计** | 100 | **6.8** | **≈7.8**（图谱不转正 ≈7.7） | |

> B8–B14 为增补工作包，上表未计其增量；复评时按 §12 的层维映射（B14 按 A4/D2/B2维 的接口骨架计）并入对应维度，按 §8 第 4 条同一权重口径复算，偏差 >0.3 写归因。

---

## §4 拍板记录（一次性执行口径：全部按推荐选项 A 执行）

> 裁决原文："待拍板问题按推荐来"。各选项利弊与不可逆点分析保留如下，作实施对照依据。
> **一次性执行口径**：以下所有“推荐选项 A”视为执行默认，不再逐项等待拍板；若现场证据与推荐冲突，按 §16.2 停止并报告，不静默改方向。

1. **条件类的存储形态**——**已裁：选项 A**。扩展 `ontology_rules` 行的形状枚举＋条件参数（列不足则走迁移注册表）。理由：坚持"规则是数据"原则，复用规则生命周期（版本/触发审计/精确撤销），无第二事实源。代价：规则行结构变复杂，引擎求值分支＋1。影响面：改 `rule_engine.py` 求值器＋`validation.py` 一致性项。否决项：独立 `condition_classes` 新表（与规则体系并存即双事实源，违教义第 6 条风险，且落表后收口需迁移）。
2. **B1 推导的默认态**——**已裁：选项 A**。观察态灰度：推导照常记账（账本可查），检索主路默认排除推导事实，环境变量（`NEUROVA_CONDITION_CLASSES_ROUTE`）翻主路。先例：认知门三态、图谱影子档。不可逆点：无（双向可翻）。否决项：直接进主路（误归入面直接暴露给对话）。
3. **四动词门面形态**——**已裁：选项 A**。新增 `/v1/knowledge/access/{query|analyze|validate|use}` 纯转发门面，OpenAPI 汇总，旧路由不动。理由：补"统一入口"评测短板且零迁移成本；旧消费方零破坏。否决项：只补 validate 不做门面（D1 停在 6.5 左右，统一入口短板保留）。
4. **B4 溯源呈现深度**——**已裁：选项 A**。后端契约先行：检索 payload 对 `derived_by` 事实带推导标注（规则号＋前提数），前端本轮只加引用行内标注。完整溯源卡片（规则链可视化）放下一批。不可逆点：无。

**B8 待拍板项（2026-11-05 关系映射复核后新增；一次性执行按推荐 A）**：

1. **关系属性的存储形态**——**推荐选项 A：扩展 `ontology_terms`（迁移 v29），关系专用列可空**。理由：关系术语已在该表内，复用同一注册表、同一租户分区、同一读写面；`parent_term_id` 直接复用为关系父属性（把"只有 concept 能有父类"放宽为 concept/relation），不另起 `parent_relation_id`；函数属性不新增布尔列，直接用既有 `cardinality=1` 表达，避免同一约束两份定义。否决项 B：新建 `ontology_relation_profiles` 1:1 表——更规范，但引入第二写口与 join，且 `parent` 仍要回连 `ontology_terms`，违反单一事实源优先。不可逆点：v29 为加列迁移，可回滚；关系父属性一旦发布即成为语义承诺，退役走 `deprecated/replaced_by`，不删行。
2. **未知关系的落点**——**推荐选项 A：进 `ontology_relation_candidates` 候选表，人工批准后才升为术语**。理由：与 v27"候选别名只进人工审批面"同口径；候选表只存 surface/来源/置信度/状态，不是第二事实源；抽取链不再静默丢弃，避免"模型说了、图上没有、无人知道"。否决项 B：直接落 `custom` 后丢弃——现状即如此，会持续制造不可见缺口；否决项 C：自动登记为术语——把模型幻觉直接写进本体，不可逆。影响面：新增候选表与两个审核端点，`graph_bridge` 未知关系分支改道；批准动作仍是 `registry.register`，事实仍走唯一写咽喉。

**L0–L9 待拍板项（2026-11-05 增补；一次性执行按推荐 A）**：

1. **L1 上层本体**——**推荐选项 A：只落 upper-lite**（Entity/Agent/Event/Document/Concept/Relation + 连续体/发生体两类），BFO/ISO 21838 只做 `external_iris_json` 导出映射，不整包引入。否决项 B：整包引入 BFO/SUMO/DOLCE——会改变现有术语语义、校验口径与导出承诺，且与"零新增第三方依赖"冲突。不可逆点：upper-lite 术语一旦发布即成为租户类型根；退役走 `deprecated/replaced_by`。
2. **L4 形状引擎**——**推荐选项 A：自研 JSON 形状注册表**（target/path/severity/message）＋写入前与 dry-run 共用同一求值器；SHACL 只导出、不引第三方引擎。否决项 B：引 pySHACL/Java SHACL 引擎——新增依赖、闭合世界语义与现有 admission 写前强制重复，违反单一事实源。不可逆点：形状表是新增语义承诺；SHACL 导出为只读契约，可回滚。
3. **L2 版本化 IRI**——**推荐选项 A：默认导出保持 `kbg:<term>` 稳定**，版本只进 `owl:versionInfo`/基线号；需要冻结版本时用可选 `.../v1/<term>` 导出，不改默认 IRI。否决项 B：默认 IRI 直接带版本——现有 Turtle 子集、测试与外部消费方全部要迁移，收益不抵成本。不可逆点：默认 IRI 一旦变更不可撤回；A 案可随时加版本导出。
4. **L9 质量门**——**推荐选项 A：CI 内收 CQ 覆盖＋OOPS! 结构子集＋NDCG/A-B**，不做完整 OQuaRE 认证。否决项 B：完整 OQuaRE 认证——指标多、主观项重、当前团队无认证流程；A 案能先咬住可执行的质量回归。不可逆点：质量门一旦进 CI，新增失败即红；阈值可按实测调。

**B14 接口预留（2026-11-05 已定方向，细节待实施拍板）**：

- 用户要求把 **V5 企业数据源接入器（DB/ERP/事件流）** 与 **源库 schema 映射（表/列 → 主体/谓词/客体，R2RML 类）** 纳入本计划，但**只预留接口**。
- **推荐选项 A**：`EnterpriseSourceAdapter` Protocol＋JSON 映射描述符＋fake adapter＋admission 接线；真实 DB/ERP/事件流连接器、全量 R2RML 解析、CDC 游标另立项。
- 否决项 B：本工作包直接接真实源——新增 DB 驱动/消息中间件依赖，违背零外部服务与零新增依赖。
- 否决项 C：继续排除——与用户指令冲突。
- 不可逆点：Protocol 与描述符一旦发布即成为外部契约；真实连接器只能按此契约接入，不能另造第二套写口。

---

## §5 工作包详设（同一次执行）

> B9–B13 是 L0–L9 分层工作包，详设见 §12；B14 企业源接口预留见 §14；本节 B1–B8 是纵切工作包。编号不是交付批次，执行顺序见 §16。

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

- **现状与证据**：6 项校验只在 admission 咽喉内强制（`validation.py:16`），外部无法只读试算；评测 D1"validate 无独立端点"。
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

- **实测先行原则**：本工作包**先建基线，后动优化**；无基线证明的瓶颈不动手。
  1. `tests/performance/knowledge/test_admissionThroughput.py`：批量准入吞吐基线（当前 `admission.admit` 单条路径）；若基线证明批量摊薄事务收益 ≥30%，再落 `admitBatch`（同事务多 triple，逐条 finding 独立返回）；否则登记"实测无瓶颈"收批。
  2. `admitBatch`（若立项）：供 `ingest_worker` 批量路径消费，单条失败不拖批（fail-soft 契约：逐条 finding，不整批回滚语义事实）。
  3. 可用性契约测试：admission 异常→ingest 队列重试路径（`ingest_queue/ingest_worker` 既有件）断言不丢事件；validate/导出只读端点异常显式 5xx。
- **图谱影子转正执行**（引用 `docs/specs/2026-10-30-knowledge-retrieval-accuracy-upgrade-plan.md` 已定判据，不另立标准）：跑 `retrieval_metrics.py` 影子读数（overlap_at_k 等）积累窗口，判据通过 → `GRAPH_ROUTE_WEIGHT_ENV` 类环境变量默认值 0→配置化默认权重（灰度可回滚，双向）；判据不通过 → 登记"未达标原因"收批，B1维 维持 7.5。
- **测试**：性能基线本身即红灯起点（先有数，后有改）；转正开关翻动前后各跑一次检索回归套件（A/B 自证：`git stash push <files> && pytest <套件> && git stash pop`，失败集合逐行比对）。

### B8 关系映射层补全（增补工作包，2026-11-05 复核新增）

- **现状与证据**：关系词表由 `term_registry.legacyGraphTerms()` 把 `RelationType` 枚举收编成 `ontology_terms(kind='relation')` 行，再由 `seedBuiltinTerms()` 补 `documented_as/is_a` 两条种子；抽取侧 `graph_bridge.extractionPrompt()` 把注册表关系术语作为候选，LLM 输出命中则直接作 `predicate_term_id`，未命中落 `custom`，而 `admitExtractedFacts()` 对 `custom` 直接跳过（`graph_bridge.py:278`），投影侧也只铺权威接纳的边（`graph_bridge.py:486`）。因此当前只有"抽取关系类型 → 谓词 term_id"的 1:1 名称映射：没有关系层级（`parent_term_id` 只允许 concept）、没有逆/对称/传递声明、没有关系别名归一，也没有按语言的 `prefLabel/altLabel` 词形归一、没有外部 IRI 映射、没有源库 schema 映射（B14 只预留接口，见 §14）；未登记关系不是进审核面，而是两层都消失。`relation_kind` 只是 literal/entity/document 的存储类别，不是语义关系。
- **设计**（按 §4 B8 拍板项，推荐 A/A）：
  1. **术语层扩展（迁移 v29，加列不删列）**：`ontology_terms` 增 `inverse_of TEXT NOT NULL DEFAULT ''`、`symmetric INTEGER NOT NULL DEFAULT 0`、`transitive INTEGER NOT NULL DEFAULT 0`、`aliases_json TEXT NOT NULL DEFAULT '[]'`、`external_iris_json TEXT NOT NULL DEFAULT '{}'`、`deprecated INTEGER NOT NULL DEFAULT 0`、`replaced_by TEXT NOT NULL DEFAULT ''`；复用 `parent_term_id` 作关系父属性，`register()` 把"只有 concept 能有父类"放宽为 concept/relation，父类 kind 必须一致、注册时判环。函数属性不新增列：`cardinality=1` 即同一语义，导出时映射为 `owl:FunctionalProperty`；逆函数属性由逆关系的 `cardinality=1` 表达。
  2. **关系层级与特征**：`A parent_term_id=B` 表示 `A rdfs:subPropertyOf B`，求值时生成 `auto_subproperty:<term>` 直接搬移规则（`X A Y ⇒ X B Y`）；`transitive=1` 生成 `auto_transitive:<term>` 二元接力规则；`inverse_of`/`symmetric=1` 生成 `auto_inverse:<term>` 变量交换规则。现有求值器 `_fireRule` 按"首原子主语→head 主语、末原子客体→head 客体"落库，`head_subject_var` 只存不读，`head(Y,X) :- body(X,Y)` 会被写成 `X B Y` ⇒ B8 必须新增 `inverse` 形状并让求值器显式按变元映射落 head，不把反向补边散落到消费方；`registerRule` 同时增显式 `shape` 入参（缺省仍 `relay`，存量零漂移）。派生规则由引擎 `ensureAutoRules(tenantId)` 在每轮求值前幂等对齐（与 `seedBuiltinRules` 同一 owner 纪律，不在 `term_registry` 里反向依赖引擎）；删声明/改特征时禁用旧 `auto_*` 行并走账本精确撤销其结论。全部规则行落 `ontology_rules` 同表同引擎。
  3. **别名归一**：`aliases_json` 存关系 surface form（如"属于/隶属于"），`label` 保持规范名；抽取前先做归一：精确 term_id → 别名精确匹配 → 规范化 surface（小写/去空白/去标点）→ 规范 label；仍不命中才进候选。别名按租户唯一，冲突登记为候选而非覆盖。多语言 `prefLabel/altLabel` 的独立存储与 SKOS 导出由 B10 承接（见 §12.3）。
  4. **未知关系候选**：新增 `ontology_relation_candidates`（`candidate_id`、`tenant_id`、`surface`、`normalized_surface`、`source_entry_id`、`source_text`（抽取出的 source/type/target 原文或上下文片段）、`confidence`、`status` pending/approved/rejected、`promoted_term_id`、`created_at`、`reviewed_at`、`reviewed_by`），按 `(tenant_id, normalized_surface, source_entry_id)` 去重；抽取只写候选、不写事实；批准动作走 `registry.register` 并回填 `promoted_term_id`，事实仍由后续抽取或补抽经唯一咽喉落库；拒绝保留审计不删行。
  5. **外部 IRI 映射**：`external_iris_json` 存导出用映射（如 `rdf_type`/`rdfs_subClassOf`/`owl_inverseOf`/`prov_wasDerivedFrom`/`skos_exactMatch` 槽位），运行时零新依赖；`turtle.py` 增"有外部 IRI 用外部 IRI、否则 `kbg:`"的导出模式，并保持逐字节确定性。`is_a` 事实在导出层只对应实例类型（`rdf:type`）；概念父类来自 `ontology_terms.parent_term_id`，导出为 `rdfs:subClassOf`；内部事实层仍只保留一条 `is_a` 谓词，不改语义。
  6. **校验**：`register()` 拒绝逆/对称/传递/关系父属性用在非 relation 上、逆关系目标不存在/非 relation、`inverse_of` 指向自身但未声明 `symmetric`、`symmetric=1` 却声明了另一个 `inverse_of`、父关系成环；`validation.py` 增逆关系一致性（A inverse_of B ⇒ B inverse_of A，登记时双向补齐或拒绝单边）、子属性沿 `parent_term_id` 继承有效 domain/range、`cardinality=1` 的函数冲突沿用现有基数判定；transitive 闭包设行数/深度上限，超限显式报错，不静默截断。
  7. **与既有种子规则的关系（先比后合）**：`is_a` 的结构性传递性从手工种子 `_SEED_RULES['is_a_transitive']` 收口到术语属性 `transitive=1`；v29 迁移按租户回填 `is_a.transitive=1`，`_SEED_TERMS['is_a']` 同步带 `transitive=1`（非 default 租户首跳补种即带上），`ensureAutoRules` 生成同 `rule_id='is_a_transitive'` 的规则行，删除手工种子。判据要求结论集与撤规则行为逐条不变（A/B 对拍），且 `ontology_rules` 中同 id 只有一行——避免同一蕴含两套规则（教义第 6 条）。
  8. **种子关系的特征默认全关**：迁移只加列，不给 `part_of/contains/...` 擅自声明传递/逆/对称；`is_a` 的传递性按第 7 条收口。领域确认后经 API 开启——把领域假设写进默认数据，等于让所有租户继承同一套未经验证的语义。
  9. **现有种子关系的处理口径**：`RelationType` 收编值去掉 `custom` 后 13 个，加 `documented_as` 共 14 个关系术语。`is_a` 按第 7 条收口传递性；`documented_as` 是结构谓词（条目录入），不参与关系特征；其余 12 个（`has_a/part_of/related_to/causes/similar_to/opposite_of/temporal/spatial/causal/depends_on/used_by/contains`）只登记为术语，B8 不擅自加特征；未知 surface 走候选。
- **映射层次（本工作包范围）**：①词形映射 surface/alias → `term_id`（`aliases_json`，未命中进候选）；②语义映射 term → parent/inverse/symmetric/transitive/functional（`ontology_terms` 列，函数用 `cardinality=1`）；③标准映射 term → RDF/RDFS/OWL/PROV/SKOS IRI（`external_iris_json`，仅导出）；④导出映射 term/事实 → Turtle/JSON-LD（`turtle.py`，概念父类与实例类型分流）；⑤源数据映射表/列 → 主体/谓词/客体（R2RML 类，§6 缓办）。
- **落点**：`neurova/knowledge/ontology/term_registry.py`（register/读取/归一）、`validation.py`（一致性项）、`rule_engine.py`（`inverse` 形状、`ensureAutoRules` 与 `auto_*` 规则生成）、`foundation/knowledge_facts.py`＋`foundation_schema.py`（v29 迁移与候选表）、`knowledge/graph_bridge.py`（别名归一与候选分支）、`api/endpoints/knowledge_ontology.py`（术语字段与候选审核端点）、`ontology/turtle.py`（外部 IRI 导出）。新逻辑落 `neurova/knowledge/ontology/` 独立模块，不回填 `agent_core.py`。
- **测试（先红后绿）**：红灯 `tests/unit/knowledge/ontology/test_relationMapping.py` 至少十组——①关系层级：`part_of ⊑ related_to` 登记成功，成环拒；②逆关系：`depends_on inverse_of used_by` 双向成立且方向不被照抄（`X depends_on Y ⇒ Y used_by X`），单边拒；③对称：`similar_to` 双向物化；④传递：`part_of` 闭包，撤声明后推导事实经账本精确消失；⑤函数属性：`cardinality=1` 冲突被拒，且不新增 `functional` 列；⑥别名：`"属于"` 归一为 `part_of`，冲突别名进候选；⑦未知关系：`"telepathizes"` 只进候选表，事实/投影均无，批准后成术语；⑧导出：`.ttl` 含 `rdfs:subPropertyOf`/`owl:inverseOf`/外部 IRI，逐字节确定；⑨租户隔离与存量兼容：关系特征/候选按租户隔离，concept 父类与既有事实零漂移；⑩种子收口：`is_a_transitive` 由 `is_a.transitive` 生成、同 id 单行，结论集与旧手工种子逐条一致；其余种子关系 `inverse_of/symmetric/transitive` 默认全关。绿灯后补 `tests/unit/api/test_ontologyRelationCandidates.py`（候选列表/批准/拒绝/越权）。
- **效率与可用性**：关系元数据按抽取批读一次，不逐条查表；`auto_*` 规则与手工规则同表同求值管线，不新增第二套推理；候选表按 `(tenant_id, status, created_at)` 建索引，审核分页；transitive 闭包上限可配，超限报错；全程零新增第三方依赖。
- **验收（live-verify）**：真后端 9527＋确定性 `llm_call`（不联网）走真实抽取函数：①登记 `part_of ⊑ related_to`、`part_of transitive`、`depends_on inverse_of used_by`、别名"属于"、外部 IRI；②抽取一条含"属于"的条目 → 事实谓词为 `part_of`，`/graph/instances` 可见；③抽取一条含"telepathizes"的条目 → 候选表有行、事实与投影均无；④批准候选 → 术语表新增、后续抽取可命中；⑤`GET /v1/knowledge/ontology/export.ttl` 含 `rdfs:subPropertyOf`、`owl:inverseOf`、外部 IRI；命令与输出原文进提交说明。
- **风险与不可逆点**：v29 为加列迁移，可回滚；`parent_term_id` 语义放宽会触及现有"只有 concept 能有父类"的判据与测试，需同批改判据而非放宽校验；`is_a_transitive` 种子退役需新旧结论集 A/B 对拍，避免类型层级推导回归；别名冲突与候选表增长需审核/保留策略；外部 IRI 映射错误只影响导出，不影响运行时；关系特征一旦发布即语义承诺，退役走 `deprecated/replaced_by`，不删行。
- **分数影响**：不预设；复评时并入 A1/A2/A3/A4，按 §8 第 4 条实测口径复算。

---

## §6 不纳入本次执行（登记理由）

| 项 | 理由 |
|---|---|
| C1维 Agent 层 Planner/Reasoner 抽象 | 独立大工程，涉及 chat_pipeline 结构重排与尺寸棘轮联动，另行立项；本次执行 C1 维维持 7.0 |
| OWL DL 语义/SPARQL 引擎、第三方 SHACL 引擎 | 评测报告不采纳三条维持（六项决策＋`rule_engine.py:3` 边界声明＋单一事实源纪律）；B10 自研 JSON 形状注册表、B12 只导出 SHACL shapes，不引第三方引擎；OWL DL/SPARQL 仍不做 |
| 真实 DB/ERP/事件流连接器与全量 R2RML 解析 | B14 只落适配器契约、JSON 映射描述符、测试替身与 admission 接线；真实驱动/CDC/凭据接入另立项 |
| 完整 Protégé/OWL DL 编辑器、SPARQL 控制台、全量 R2RML 编辑器、真实企业源连接器 UI | UI 只做任务面（§15）；这些超出产品形态，另立项 |
| 外部上层本体对齐（BFO/SUMO/DOLCE 整包引入） | 只保留最小 upper-lite 与导出映射；整包引入会改变现有术语语义与校验口径，另行拍板 |
| `owl:sameAs`/`equivalentProperty` 自动合并 | 强等价会传播闭包，误合并不可逆；跨词表用 `skos:exactMatch/closeMatch`，实体合并仍走 canonical ID + 人工审批 |
| RDF 1.2 生产化 | 目前仍为 W3C CR 快照（2026-04）；生产互操作以 RDF 1.1 为基线，RDF 1.2 只做观察与导出兼容性测试 |
| 完整 OWL 2 RL 完备性 | B11 只实现可规则化子集；domain/range 默认只做写入校验、functional 用 `cardinality=1` 做闭合世界拒写（不推 `sameAs`），导出仅作互操作声明；unionOf/complementOf/oneOf/等价类等不纳入 |
| 完整 OQuaRE 认证 | B13 只收可执行的 CQ/OOPS! 结构子集/NDCG A-B；完整认证与主观评分不在 CI 内 |
| 重开 011 已否证的"事实池＋叙述池按秩交织" | 011 实测 recall@5 0.8555→0.7604；`FactSurface` 只做零锚点种子与治理富化（K-10）；重开即回退已否证路径 |
| gaps/learn 伪造数据 | `/gaps/analyze`、`/learn` 保持 501；`/gaps`、`/learning-records` 保持空；不做数据生产端（K-07） |
| 默认关闭能力打包全开 | D-01/D-02/D-03/D-04/D-06/D-08/D-11/D-16/D-19 逐项 shadow/on，不打包；默认关是产品/成本/安全决定，不是断点（§13） |
| 知识库死码卫生/联邦 KB/memory_links/非飞书同步/gaps-learn | 非本体项，归 KB 计划 P0/P1/P3（K-07 保持 501/空）；本体计划只在 §13 引用结论，不重复立项 |

---

## §7 一次性执行顺序与依赖（Runbook 见 §16）

```
Preflight（B1–B7 已落核验）
  → B8(v29) → B9(v30) → B10(v31) → B11(v32) → B12(v33) → B14(v34) → B13
  → UI-0 → UI-1 → UI-2 → UI-3 → UI-4
  → Final gates（§8 / §15.7 / §16.3）
```

- **迁移号是硬约束**：v29→v30→v31→v32→v33→v34 单调；B13 无 schema，放后端工作包最后做评估；UI 在后端端点全落后一次完成。
- **B1–B7 已落**：Preflight 只核验与跑回归；若缺失，按 B2→B1→B3→B4→B5→B6→B7 补齐后再进入 B8。
- **B8 是 v29 的起点**：B9/B10/B11 的关系特征与自动规则依赖它；不得先加 v30 再补 v29。
- **B13 在 B14 之后**：这样 v34 已落，评估可覆盖企业源接口；B13 无 schema，不影响迁移号。
- **UI 最后**：UI-0–UI-4 一次完成，避免每个后端工作包都返工前端。
- 同一次执行内可按工作包分笔提交到同一分支，但**不推送、不交付**；最终门全绿后一次性收口。共享文件（`knowledge_facts.py`、`knowledge_ontology.py`）提交前 A/B 自证。

## §8 一次性执行验收门（收官判据）

1. 每个工作包红灯→绿灯实测输出进同一分支的对应 commit 说明；净 LOC 去向逐条列明；中间不推送、不交付。
2. live-verify（教义第 4 条）：真后端 9527 走真端点——建条件类规则→dry-run 校验→四动词门面→导出 .ttl→流水线基线，全链命令＋输出原文归档。
3. 回归：`tests/unit/knowledge/`、`tests/unit/agent/` 全绿（预存失败清单先行对表，新增失败为零）；前端门 `npm run test`＋`npx vue-tsc --noEmit`（B4/B2 前端消费工作包）。
4. 评分复评：按评测报告同一权重口径复算十维，投影偏差 >0.3 的维度写偏差归因。
5. B8 关系映射：层级/逆/对称/传递/函数（`cardinality=1`）、别名归一、未知关系候选、外部 IRI 导出全部有判据；live-verify 覆盖"别名抽取→归一→事实→导出"与"未知关系→候选→审批→术语"两条链。
6. L0/L1：每条 CQ 有唯一查询与测试（追溯表零孤儿）；upper-lite 种子齐、类型/实例不混用、身份判据可执行；BFO/ISO 21838 映射只作导出。
7. L2/L4：属性特征、SKOS 多语言标签、版本化 IRI、core/domain 模块、deprecated/replaced_by 全部可登记；形状注册表的 target/path/severity/message 在写入前与 dry-run 共用同一求值器，推理与校验分离。
8. L3/L5：双时态 `asOf/knownAt` 可查；限定关系有 schema；事件/时间模式可落；OWL 2 RL 子集逐条有判据，解释链可回溯到规则与前提，撤销精确。
9. L6/L7/L8：四动词有统一分页/投影/租户隔离；稳定 IRI 可解析；Turtle/JSON-LD/OWL 公理/SHACL/PROV-O 导出逐字节确定；提案→dry-run→基线→发布→diff→回滚全链可跑，变更审计与语义版本在册。
10. L9：CQ 测试全绿（P1）、负例按预期拒、golden 无漂移、OOPS!/OntoClean 子集零高危、NDCG/A-B 无回归。
11. B14 企业源接口预留：适配器 Protocol、JSON 映射描述符、fake adapter、admission 接线全部有判据；默认无真实连接器/零外部依赖；真实 DB/ERP/事件流连接器与全量 R2RML 解析明确不在本工作包。
12. UI 对齐（§15）：UI-0–UI-4 在同一次执行内完成；`npm run test`＋`npx vue-tsc --noEmit`；浏览器走通「术语→校验→关系→查询→解释链→导出→发布→回滚」「CQ→质量→A/B」「企业源→fake adapter→事实」三条链；默认关/观察态可见，不伪造已接入。
13. 一次收口（§16.3）：以上 1–12 全绿才推送/交付；中间可按工作包提交到同一分支，不推送、不交付。任何一门未过，停在原地修复并如实报告，不交付半成品。

## §9 台账落格约定

每个工作包闭环后落 `audit-reports/simplification-audit-2026-10-05.md`，编号**自现场现值顺延**（当前已知最大 §6-549；提交前 grep 现值防撞号）；拍板项 1–4、B8 项 1–2、L0–L9 项 1–4 与 B14 接口预留的裁决记录随对应工作包条目一并落格；整次执行完成后一次性收口，不在中途交付。

## §10 实施台账（2026-11-05 复算回写）

| 工作包 | 状态 | 红灯→绿灯证据 | live-verify | 与票面的偏差 |
|---|---|---|---|---|

> B8–B14＋UI 按 §16 一次完成；“待实施”不代表分批交付；待拍板项按 §4 推荐 A 执行，现场证据冲突时停止并报告。
| B1 条件类推导 | 已落（引擎/写面/读面） | `test_conditionClassDerivation.py` 11 格全绿（登记即推导、低风险不归入、不动点、撤规则只撤结论、形状四道写入口拒） | 活体：`POST /ontology/pipeline/run` 建条件类规则 → `/graph/instances` 两笔实例 → `export.ttl` 内 `HighRiskOrder` 命中 4；撤规则后 4→3（差恰为那条推导），原始主体键仍在 | **观察态落点改判**：票面写"检索主路在 `knowledge_retriever_adapter` 过滤"，实测该处今天到不了推导事实（chat 主路只出条目，`mergeIntoLegacy` 生产零调用，推导行是 `record_kind='triple'` 永不成条目的治理行）。唯一"事实→检索条目形状"出口是 `read_surface.FactSurface.search` ⇒ 过滤落在那儿（见 B4 行） |
| B2 validate dry-run | 已落 | `test_ontologyValidateEndpoint.py` 9 格绿（domain 违规/未登记/干净/性能冒烟＋校验器异常显式 500） | 活体 `POST /ontology/validate` status=200 verdict=violation（不抛异常） | — |
| B3 四动词门面 | 已落 | `test_knowledgeAccessFacade.py` 7 格绿 | 活体：query/analyze/validate 各 200、`use/{fact_id}` 200 且回执带 fact_id、未声明动词 404 | 仓内零消费者（K-08）：按对外契约保留；L6 补 OpenAPI/SDK 契约测试，不宣称已闭环 |
| B4 溯源进对话 | **后端链路通到回合元数据**（本轮二次改判） | 判据三档：`test_factSurfaceDerivationGovernance.py`（读面）＋ `test_graphWalkDerivationGovernance.py`（走查灰度与 via_derived）＋ `test_derivationReachesTurnMetadata.py`（真装配点串联：真库→真走查→真 `_graphRoute`→真 `_normalize_item`→真 `ChatPipeline._recordKnowledgeLineage`）；契约档 `test_derivationCitation.py` | 活体见 §6-551 | **二次改判（同一格纠正两次，记下来免得再踩）**：第一轮把过滤落在 `FactSurface.search` 就宣布"对话侧够不着"。桥接场景实测推翻：推导行 `订单D01 is_a HighRiskOrder` 自己不带条目（medium_ref 是 `rule:<id>`），但走查拿它当**跳板**，第二跳落在挂 `entry:doc1` 的显式事实上 ⇒ 条目以图谱权重（默认 on，0.10）进 RRF 并随条目注入对话。真实漏点在递归段，读面那条只管种子锚点。⇒ 观察态排除落 `graph_walk._walk` 的锚段与递归段（SQL 片段由账本单源 `derivedExclusionClause` 生成，别处不抄那张表）；翻主路态给每个叶子跳挂 `via_derived`（跳板本身不在返回里——只回 hop>=2 的叶子，标志不随叶子走等于没标）；再经 `_graphRoute` 支撑→`_normalize_item`→`ctx.metadata["knowledge_derivation"]`→`post_chat_pipeline` 落盘，对话引用面第一次真拿到"这条是推出来的" |
| B5 Turtle 导出 | 已落（**端点本轮补上**） | `test_turtleExport.py` 12 格绿（含 `TestExportEndpoint` 3 格：media_type/403/租户隔离；红形态=404 Not Found，绿后逐字节确定性保持）；`test_rdflibInterop.py` 在**未装 rdflib 的本机 skip** | 活体：`GET /ontology/export.ttl` 200＋`text/turtle; charset=utf-8`，文档 8090 字符可被本仓 `parseTurtle` 读回 | 上一批只落模块（测试 docstring 自陈"路由由主会话统一挂"）⇒ 本轮补 `GET /ontology/export.ttl` 并登记语法子集边界。rdflib round-trip 本轮**未实跑**（依赖缺席），"roundtrip 通过"是上一会话读数 |
| B6 构建流水线 | 已落 | `test_ontologyPipeline.py` 13 格绿 | 活体：run 200（applied terms=3 rules=1，基线号 `kb_…`）；违规候选整批拒 400 且**导出逐字不变**（零落盘）；diff 200 | 票面未提的形状缺口本轮补：`PipelineRuleRegistration` 与 `RuleWriteRequest` 都缺 `head_object_const` ⇒ 条件类规则经 REST 登记不出来（活体第一版当场 400 在此）。补栏后 `test_ontologyWriteSurface.py` 新增条件类登记＋PUT 保留现值两格绿；流水线 diff 字段随之加 `head_object_const` |
| B7 效率与可用性 | 已落（含 admitBatch 立项并交付） | 基线 `test_admissionThroughput.py` 实测 185–199 facts/s（落账读数 190.7）；**摊薄实测 +329%**（代理连接形态，反证格抓到"只覆 `commit()` 不改 `__exit__` ⇒ 两侧同路"的假结论后复测）⇒ 过 30% 门槛 ⇒ 落 `admitBatch`；交付判据改向：`admitBatch` vs 逐条 `admit` 实测 **+220%**（199.5→639.2 facts/s），仍过门槛。语义判据 `test_admissionBatchCommit.py` 6 格绿（全批落定／空批／拒因留名／**坏一条连它已写下的半条一起退**／批后不留未提交事务／单条 admit 仍即时提交） | 活体：`admitBatch` 30 条经生产闸全落（ok=30/30）；`data/` 内容指纹跨两次活体一致（`595dbb4e…`）⇒ 仓内真库未被写 | 变异探针：把批量档摘掉（`scope=None`）⇒ 恰红两格（半条回退格＋finding 下标格），证判据咬的是机制不是名字。图谱影子转正**不在本次执行复算**：已由 `0416a9031`（SAG C1 实测达标，`NEUROVA_KB_GRAPH_ROUTE` 默认 on、权重默认 0.10）闭环 |
| B8 关系映射层补全 | **待实施（按 §4 推荐 A 执行）** | 红灯文件：`tests/unit/knowledge/ontology/test_relationMapping.py`（十组）＋`tests/unit/api/test_ontologyRelationCandidates.py` | 待实施 | 本工作包为 2026-11-05 关系映射复核新增，不在原评测 V1–V5 内；分数不预设，复评时并入 A1/A2/A3/A4 |
| B9 L0/L1 基础层 | **待实施（按 §4 L1 推荐 A 执行）** | 红灯文件：`test_cqTraceability.py`、`test_upperLite.py` | 待实施 | CQ 目录与 upper-lite 先行；BFO/ISO 21838 只做导出映射 |
| B10 L2/L4 术语与约束层 | **待实施（按 §4 L2/L4 推荐 A 执行）** | `test_termSkosLabels.py`、`test_ontologyShapes.py`、`test_shapeDryRun.py` | 待实施 | 依赖 B8 关系属性列；shape 与既有 6 项校验同求值器 |
| B11 L3/L5 断言与推理层 | **待实施** | `test_bitemporalQuery.py`、`test_qualifiedRelationSchema.py`、`test_owl2rlProfile.py`、`test_explanationChain.py` | 待实施 | OWL 2 RL 只做可规则化子集；不引外部推理机 |
| B12 L6/L7/L8 访问互操作治理 | **待实施（按 §4 L2 推荐 A 执行）** | `test_stableIri.py`、`test_accessProjectionPagination.py`、`test_interopExports.py`、`test_governanceRollback.py` | 待实施 | 导出格式以 RDF 1.1 为基线；RDF 1.2 只观察 |
| B13 L9 评估层 | **待实施（按 §4 L9 推荐 A 执行）** | `tests/unit/knowledge/ontology/cq/`、`tests/unit/knowledge/ontology/golden/`、`test_ontologyQuality.py` | 待实施 | CQ 测试依赖 B9；质量门阈值按实测调 |
| B14 企业数据源接入器＋源库 schema 映射（接口预留） | **待实施（只预留接口）** | 红灯文件：`tests/unit/knowledge/enterprise/` 下 `test_enterpriseSourceProtocol.py`、`test_sourceSchemaMapping.py`、`test_enterpriseIngestAdmission.py` | 待实施 | 对应评测 V5；只落 Protocol/JSON 描述符/fake adapter/admission 接线，真实连接器另立项 |
| UI 对齐（§15） | **设计稿已入（待实施）** | 前端门：`npm run test`＋`npx vue-tsc --noEmit`；新页组件测试覆盖空态/错误态/权限态 | 待实施 | UI-0–UI-4 跟随 B9–B14；不新增 B15 |

**B7 未做的一半（如实登记）**：可用性契约里"admission 异常→ingest 队列重试不丢事件"未新增判据——现役 `test_ingest_queue.py`／`test_ingest_jobs_queue.py` 已钉 lease 过期重取、`nack` 重试到死信、启动对账复位，`test_extractOnUpdateAndAsync.py` 已钉抽取失败 fail-soft 与 `extract_failed` 口径；本轮复算没发现"事件被静默丢弃"的活缺口，故不新造第二套判据（教义第 6 条）。若要把"抽取失败不重试"改判成重试，那是产品语义变更，另行拍板。

## §11 本次执行扫荡出的三处仍开（2026-11-05 现测）

1. **endpoints 同层交叉常驻红**：`knowledge_core.py:1136` 函数内 import `knowledge_ingestion`（`extract_after_update`/`extract_event_summary`），由 `6632c6560`（SAG C2+C3）带入，守卫 `test_endpoints_module_layering.py[knowledge]` 自此一直红。修法按守卫原话"共享需求下沉共享层"，但要连依赖一起搬（`_try_extract_to_graph`／`_default_llm_call`／`_resolve_runtime_agents`）并改 6 个测试档的 monkeypatch 目标与 `test_knowledge_reexport_contract.py` 的归属表——属另一批的根因，本轮未动，等点单。
2. **PUT 规则省略 body 是坏支路**：`update_ontology_rule` 用 `existing.get("body")` 兜现值，而 `_hydrate` 出来的是 `{kind,predicate,…}` 作者态之外的形状，`_parseBody` 只认 `atom`/`not` ⇒ 省略 body 的改版当场 400。现役测试一律显式带 body，所以从没踩过。本轮只在判据里按实况注明，未修。
3. **身份面两格常驻红**（`test_requestUserIdEntryConsistency`／`test_turnIdentitySingleSource`）：登记表白名单与实装写者不一致，A/B 复算为 HEAD 自带，与本体栈无关。

## §12 L0–L9 分层目标架构与 B9–B13 工作包（2026-11-05）

> 定位：B1–B8 是纵切工作包，L0–L9 是横切架构视图；同一计划的两个坐标，不新增第二套实施体系。每层"现状"只写可核实锚点，"缺口"才进工作包；已有能力不重复立项（教义第 6/7 条）。L0–L9 的分层定义来自 2026-11-05 架构评审，B9–B13 是工作包；B14 企业源接口预留跨 L3/L7/L8，见 §14；执行顺序见 §16。
>
> **语义边界**：本计划的"OWL 2 RL 子集"指**可规则化且与现有写前校验不冲突的子集**；每条公理在 profile 文档标注 `物化/校验/仅导出` 三态，禁止把校验当推理、把导出当运行时承诺。`functional` 用 `cardinality=1` 做闭合世界拒写，不推出 `owl:sameAs`；`domain/range` 默认只做写入校验，不物化为 `is_a`；导出 OWL 公理是互操作声明，不承诺运行时完整 OWL 2 RL 语义。

### §12.0 分层落地矩阵

| 层 | 目标 | 现状（证据） | 缺口 | 工作包 |
|---|---|---|---|---|
| L0 范围 | CQ ＋领域边界＋术语表；CQ→查询/测试追溯 | `docs/` 无 CQ 目录（2026-11-05 `grep -Ri 'competency question' docs/` 零命中）；现有 specs 只有设计叙述，无本体术语表与追溯表 | CQ 目录、边界、术语表、追溯 | B9 |
| L1 上层 | upper-lite：Entity/Agent/Event/Document/Concept/Relation；类型/实例、连续体/发生体、身份判据；对齐 BFO/ISO 21838 不整包 | `term_registry.py:24` 只有 concept/relation/property 三类；`knowledge_subjects` 有规范化主体/别名/合并；无 upper-lite、无身份判据、无 punning 判据 | upper-lite、身份判据、punning 守卫 | B9 |
| L2 术语 | 类层次、属性特征、domain/range、disjoint、cardinality、required、别名、SKOS 多语言、deprecated/replacedBy、版本化 IRI、core+domain 模块 | `ontology_terms` 已有类层次/domain/range/disjoint/cardinality/required；`label` 单语、`version` 字符串、无模块；B8 **计划**补属性特征/别名/外部 IRI/deprecated（待实施） | SKOS 多语言、版本化 IRI、模块化 | B8＋B10 |
| L3 断言 | 规范化主体＋限定三元组＋双时态＋置信＋来源＋冲突＋租户 | `knowledge_facts.py:58` 已有 subject/predicate/object/qualifier_json/confidence/valid_from/valid_until/recorded_at/retracted_at；`knowledge_conflicts`、`knowledge_assertions/activities`、tenant v20 在册；无 `asOf/knownAt` 查询；K-09/K-10：TD②/FTS/facts 源钟未实现，`FactSurface` 只做零锚点种子 | qualifier schema、双时态查询、事件/时间、稳定 IRI、时间感知 | B11 |
| L4 约束 | SHACL 语义形状注册表（target/path/severity/message），写入前强制＋dry-run；推理与校验分离 | `validation.py:16` 固定 6 项；admission 写前强制；B2 已有 dry-run 端点；无形状表 | 形状注册表、target/path/severity、SHACL 导出 | B10 |
| L5 推理 | OWL 2 RL 可规则化子集＋分层否定＋传递闭包＋条件类＋物化＋账本＋精确撤销＋解释链 | Datalog 片段（`rule_engine.py:3`）、条件类 B1、传递闭包、`derivation_ledger`、B4 引用；B8 **计划**补 inverse/subproperty/transitive 自动规则（待实施）；D-06 条件类路由仍 off（K/D-06）；无 profile 声明/解释链/物化模式 | OWL 2 RL 子集声明、解释链、物化模式、转正评估 | B11 |
| L6 访问 | 四动词 query/analyze/validate/use；稳定 IRI；投影/分页；租户隔离 | B3 四动词门面已落但仓内零消费者（K-08），按对外契约；知识条目端点有 page/page_size 与 limit/offset（`knowledge_core.py:139`）；`turtle.py:26` 有 `kbg:` 命名空间；无 IRI 解析端点；ontology 列表无分页 | 统一分页/投影、稳定 IRI、ontology 列表分页、门面租户契约、SDK 契约测试 | B12 |
| L7 互操作 | Turtle/JSON-LD、OWL 2 RL 公理、SHACL shapes、PROV-O；RDF 1.1 基线，RDF 1.2 观察 | B5 Turtle 子集；`API_REFERENCE.md:99` 明示不出 IRI 客体/owl 词汇；B8 **计划**补外部 IRI（待实施）；产品代码无 JSON-LD/OWL/SHACL/PROV | JSON-LD、OWL 公理、SHACL shapes、PROV-O、RDF 1.1 合规声明 | B12 |
| L8 治理 | 提案→dry-run→基线→发布→diff→回滚；变更审计；弃用；语义版本 | B6 pipeline/baseline/diff；`pipeline.py:221` 有事务内失败回滚 `_rollbackApplied`；B8 **计划**加 deprecated/replaced_by（待实施）；无基线回滚/变更审计/语义版本 | 基线回滚、变更审计、语义版本、发布审批 | B12 |
| L9 评估 | CQ 测试、负例、golden、OntoClean/OOPS! 子集、OQuaRE、NDCG、A/B | 单测＋Turtle golden＋`retrieval_metrics.py`/benchmark；CQ/OOPS!/OntoClean/OQuaRE 在产品代码零命中；默认关矩阵 D-01/D-02/D-04/D-06/D-08/D-11/D-16/D-19 | CQ 测试、负例、golden 扩展、质量指标、A/B 门、默认关评估 | B13 |

> B14（V5 接口预留）跨 L3/L7/L8：只落适配器契约、JSON 映射描述符与 admission 接线，不接真实源；详见 §14。

### §12.1 L0 范围层

- **目标**：能力问题（CQ）＋领域边界＋术语表；每条 CQ 必须映射到查询与测试，做需求追溯。
- **现状**：`docs/` 无 CQ 目录（`grep -Ri 'competency question' docs/` 零命中，2026-11-05）；`docs/specs/2026-09-20-knowledge-foundation-design.md` 只有设计叙述，无本体术语表与追溯表。
- **设计**：
  1. 新增 `docs/specs/2026-11-05-ontology-cq.md` 并登记 `docs/INDEX.md`，CQ 表字段：`cq_id/question/actor/scope/query/expected/test_id/status/owner`；P1 CQ 必须有查询与测试。
  2. 领域边界：in/out of scope、数据源、租户、语言、时效；术语表：term/definition/aliases/owner/linked term_id/status。
  3. 追溯矩阵：CQ → API/查询 → 测试节点 → 术语/规则 → 发布基线；CI 脚本检查零孤儿、零无测试 P1。
- **测试/验收**：`tests/unit/knowledge/ontology/test_cqTraceability.py` 解析 CQ 文件，断言每条 P1 CQ 有查询与测试；TestClient 冒烟执行查询；覆盖率报告进 CI。
- **工作包**：B9。

### §12.2 L1 上层层

- **目标**：最小 upper-lite——Entity/Agent/Event/Document/Concept/Relation；区分类型与实例、连续体与发生体、身份判据；对齐 BFO/ISO 21838 概念，不整包引入。
- **现状**：`term_registry.py:24` 只有 concept/relation/property；`knowledge_subjects` 有 canonical_label/aliases/merged_into/type_term_id；无 upper-lite、无身份判据、无 punning 守卫；全仓无 BFO/ISO 21838 代码。
- **设计**：
  1. 种子 upper-lite：`Entity` → `Continuant`（`Agent`/`Document`/`Concept`）＋ `Occurrent`（`Event`）；`Concept` 是类型根，不与 `ontology_terms.kind='concept'` 的字段值混同；`Relation` 不建成 concept 类（避免把关系实例化），仍是 term kind，导出为 `owl:ObjectProperty`；不新增 `Role/Situation` 等未点单类。
  2. 身份判据：`ontology_terms` 增 `identity_keys_json`（v30），如 `["external_id","canonical_label"]`；`SubjectResolver` 按类型读判据，缺省回退 canonical label＋aliases。
  3. 类型/实例：term 与 subject 双向守卫；term_id 当 subject_key 或 subject_key 当 predicate 记 `punning` finding（warning，不阻断存量）。
  4. BFO/ISO 21838：只在 `external_iris_json` 填导出映射（Entity/Continuant/Occurrent/Event 等），不 import、不做运行时推理。
- **测试/验收**：`tests/unit/knowledge/ontology/test_upperLite.py`（种子齐、父链正确、punning 守卫、identity_keys 解析、BFO 映射可选导出）。
- **工作包**：B9。

### §12.3 L2 术语层（TBox）

- **目标**：类层次、属性特征（transitive/inverse/symmetric/functional）、domain/range、disjoint、cardinality、required、别名、SKOS 多语言标签、deprecated/replacedBy、版本化 IRI、模块化（core＋domain）。
- **现状**：`ontology_terms` 已有类层次/domain/range/disjoint/cardinality/required；B8 **计划**补 inverse/symmetric/transitive/aliases/external IRIs/deprecated/replaced_by，并复用 `parent_term_id`（B8 待实施）；`label` 单语、`version` 字符串、无模块字段。
- **设计**：
  1. v31 增 `labels_json`（lang→prefLabel）与 `alt_labels_json`（lang→list）、`module`（core/domain）、`namespace`/`iri_base`；`version` 新登记按 semver 校验，存量 `vN` 继续可读（不强制迁移）；`deprecated/replaced_by` 由 B8 提供（B8 待实施）。
  2. 模块：core 只放结构谓词＋upper-lite＋种子；domain 放业务术语；domain 不得覆盖 core 同 id；导出可按模块过滤。
  3. 版本化 IRI：默认保持 `kbg:<term>` 稳定（§4 L2 拍板项 3），`owl:versionInfo` 带版本；需要冻结版本时导出 `.../v1/<term>`，不改默认。
  4. SKOS：`prefLabel/altLabel` 只做词表与导出，不参与推理；概念 `broader/narrower` 由 `parent_term_id` 派生，不另存。
- **测试/验收**：`test_termSkosLabels.py`、`test_termModules.py`、`test_versionedIri.py`；断言 domain 不覆盖 core、多语言标签可查、版本化导出可回读。
- **工作包**：B8（关系属性）＋B10（SKOS/模块/IRI）。

### §12.4 L3 断言层（ABox）

- **目标**：规范化主体＋限定三元组（N 元关系）＋双时态（valid time/transaction time）＋置信＋来源＋冲突＋租户。
- **现状**：`knowledge_facts.py:58` 已有 subject_key/predicate_term_id/object_term/qualifier_json/confidence/evidence_state/valid_from/valid_until/recorded_at/retracted_at；`knowledge_subjects` 有 canonical/aliases/merged_into；`knowledge_conflicts`、`knowledge_assertions/activities`、tenant v20 在册。`qualifier_json` 是自由 JSON；无 `asOf/knownAt` 查询参数。
- **设计**：
  1. 限定关系 schema：关系术语增 `qualifier_schema_json`（v32，allowed keys/types/required）；admission 校验，未知键记 finding；N 元关系继续用限定三元组，不新造 reification 表。
  2. 双时态查询：`asOf`（valid time）与 `knownAt`（transaction time）参数；valid 过滤 `valid_from/valid_until`，transaction 过滤 `recorded_at/retracted_at`；API 在 facts/query 面暴露。
  3. 事件/时间：`Event` 类型＋`hasParticipant/hasTime` 关系；Allen 关系（before/after/overlaps/during）作为受控关系术语；可选 OWL-Time 导出映射，不做运行时时间推理。
  4. 稳定 IRI 与 PROV-O 导出归 B12；本层只保证事实字段与查询语义。
  5. **不新增事实池**：`FactSurface` 只做零锚点种子与治理富化（`graph_walk._seedAnchors`），不新增独立事实召回池；011 已否证两池按秩交织（recall@5 0.8555→0.7604）。TD② recency、FTS `source_modified_at`、facts 源钟按 K-09 单独立项，默认 0/关。
- **测试/验收**：`test_qualifiedRelationSchema.py`（合法/缺必填/未知键）、`test_bitemporalQuery.py`（asOf/knownAt 四象限）、`test_eventTimePattern.py`（事件参与者/区间关系）。
- **工作包**：B11。

### §12.5 L4 约束层

- **目标**：SHACL 语义的形状注册表（target/path/severity/message），写入前强制＋dry-run；推理与校验分离。
- **现状**：`validation.py:16` 固定 6 项（domain/range/parentConsistency/disjoint/cardinality/requiredProps）；admission 写前强制；B2 已有 dry-run 端点；无形状表、无 target/path/severity。
- **设计**：
  1. `ontology_shapes` 表（v31）：`shape_id/tenant_id/target_kind/target_term_id/path_json/constraint_kind/constraint_json/severity/message/enabled/version`；`severity`＝violation/warning/info。
  2. 求值器：写入前与 dry-run 共用同一函数；既有 6 项固定校验作为内置 shape 收编进同一求值器；同一 target/path/constraint 只保留一个来源，用户 shape 与内置 shape 撞车时登记即拒；violation 阻断、warning 记账、info 遥测；不复制第二套规则。
  3. 形状 DSL 是 JSON 子集（minCount/maxCount/class/datatype/in/pattern/propertyPath），不引第三方 SHACL 引擎；B12 导出 SHACL shapes。
  4. 推理与校验分离：shape 只判数据，不触发推导；rule 只推导，不做完整性校验。
- **测试/验收**：`test_ontologyShapes.py`（CRUD/目标/路径/严重级）、`test_shapeDryRun.py`（同 finding 同定位串）、`test_shapeSeverity.py`（warning 不阻断）。
- **工作包**：B10。

### §12.6 L5 推理层

- **目标**：OWL 2 RL 可规则化子集＋分层否定＋传递闭包＋条件类＋物化＋推导账本＋精确撤销＋解释链。
- **现状**：`rule_engine.py:3` 固定 Datalog 片段；B1 条件类；`transitiveClosure`；`derivation_ledger`；B4 引用；B8 **计划**补 inverse/subproperty/transitive 自动规则（待实施）；无 profile 声明、无完整解释链、无按规则类的物化模式。
- **设计**：
  1. `docs/specs/2026-11-05-ontology-owl2rl-profile.md` 明确子集：subClass/subProperty/domain/range/inverse/symmetric/transitive/functional（`cardinality=1`）/受限 hasValue（条件类）；本实现不支持 unionOf/complementOf/oneOf/等价类/`sameAs`，登记即拒。
  2. 规则形状：relay（含单原子直接搬移、双原子接力、分层否定）/conjunction（条件类）/inverse（B8 新增）；传递闭包；全部落 `ontology_rules`，由 `ensureAutoRules` 与手工规则同引擎；不新增任意嵌套/聚合。
  3. 物化：按规则类 observe/enforce（复用 B1 灰度）；推导事实走 `_admitDerivedFact`；撤销沿账本精确走。
  4. 解释链：`GET /v1/knowledge/ontology/derivations/{fact_id}` 返回规则 id/版本、前提 fact_id、derivation_kind、confidence；B4 的引用标注复用该数据；端点登记 `docs/02-api/API_REFERENCE.md`。
  5. **条件类灰度**：`NEUROVA_CONDITION_CLASSES_ROUTE` 仍默认 off（D-06）；B1 已落不等于已转正，转正须 L9 的 CQ/检索 A-B 读数。
- **测试/验收**：`test_owl2rlProfile.py`（支持/不支持逐条）、`test_explanationChain.py`（链可回溯）、`test_materializationModes.py`（observe 不进主路、enforce 进）。
- **工作包**：B11。

### §12.7 L6 访问层

- **目标**：四动词 query/analyze/validate/use；稳定 IRI；投影与分页；租户隔离。
- **现状**：B3 四动词门面已落；知识条目端点有 page/page_size 与 limit/offset（`knowledge_core.py:139`）；`turtle.py:26` 有 `https://neurova.local/knowledge/` 命名空间；`knowledge_ontology.py` 的列表无分页；无 IRI 解析端点。
- **设计**：
  1. 四动词统一契约：`query` 支持 `limit/cursor/fields/asOf/knownAt`；`analyze` 返回图指标；`validate` 走 B2/形状 dry-run；`use` 走采纳；响应统一 `{items,total,next_cursor}`。
  2. 稳定 IRI：默认单租户导出用 `kbg:<subject_key>`/`kbg:<term_id>`；跨租户导出必须带租户段（`kbg:<tenant>_<id>`；`turtle.py:63` 的 `iri()` 会把 `:`/`/` 等非 `[A-Za-z0-9_.-]` 收成 `_`，不要依赖这些分隔符），否则同 id 跨租户互撞。新增 `GET /v1/knowledge/ontology/iri/{iri}` 解析；IRI 策略与端点登记 `docs/02-api/API_REFERENCE.md`；版本化导出见 L2。
  3. 分页/投影：ontology terms/rules/candidates 补 cursor 分页与 `fields` 投影；默认字段最小化，不泄露内部列。
  4. 租户隔离：门面从请求身份解析 tenant，所有转发带 tenant；跨租户 404/403，不静默混读。
  5. **对外契约**：B3 四动词门面仓内零消费者（K-08），按对外/SDK 契约管理；补 OpenAPI 示例与契约测试，不把"端点存在"当"链路闭环"。
- **测试/验收**：`test_stableIri.py`、`test_accessProjectionPagination.py`、`test_facadeTenantIsolation.py`。
- **工作包**：B12。

### §12.8 L7 互操作层

- **目标**：Turtle/JSON-LD、OWL 2 RL 公理、SHACL shapes、PROV-O 导出；RDF 1.1 生产基线，RDF 1.2 只观察。
- **现状**：B5 Turtle 子集（`turtle.py:26`；`API_REFERENCE.md:99` 明示不出 IRI 客体/owl 词汇）；B8 **计划**补外部 IRI（待实施）；产品代码无 JSON-LD/OWL/SHACL/PROV。
- **设计**：
  1. `ontology/export/` 增 `jsonld.py`（@context＋term IRI）、`owl.py`（OWL 2 RL 子集公理）、`shacl.py`（形状注册表）、`prov.py`（assertions/activities/derivations → PROV-O）。
  2. 所有导出逐字节确定，排序固定；golden 快照进测试；rdflib round-trip 仅可选 skip。
  3. RDF 1.1 基线；RDF 1.2 只做解析兼容性观察，不引入 triple terms/生产依赖。
  4. `is_a` 事实→`rdf:type`；概念父类（`parent_term_id`）→`rdfs:subClassOf`；关系特征→`owl:*Property`。
- **测试/验收**：`test_interopExports.py`（五格式 golden：Turtle/JSON-LD/OWL/SHACL/PROV）、可选 rdflib round-trip；无新运行时依赖。
- **工作包**：B12。

### §12.9 L8 治理层

- **目标**：提案→dry-run→基线→发布→diff→回滚；变更审计；弃用策略；本体语义版本。
- **现状**：B6 pipeline/baseline/diff；`pipeline.py:221` 有事务内失败回滚 `_rollbackApplied`；B8 **计划**加 `deprecated/replaced_by`（待实施）；无基线回滚、变更审计表、语义版本。
- **设计**：
  1. 生命周期：提案（draft terms/rules/shapes）→ dry-run（B2＋L4）→ 基线（B6）→ 发布（active）→ diff → 回滚（到基线）。
  2. `ontology_change_log`（v33）：change_id/tenant/actor/action/target_type/target_id/before_json/after_json/reason/baseline_id/created_at；只追加。
  3. 基线回滚：`knowledge_baselines` 快照扩到 terms/rules/shapes（旧基线按 terms/rules 兼容），回滚恢复三者并追加变更日志，不物理删除；同时按 `derivation_ledger` 撤销受影响推导，避免规则回退后旧结论残留；失败整批回滚。
  4. 语义版本：major/minor/patch 规则（破坏性＝重大、增术语＝次、修标签＝补丁）；`owl:versionInfo` 与基线号绑定；弃用走 `deprecated/replaced_by` 与宽限期。
- **测试/验收**：`test_governanceRollback.py`（回滚逐字恢复/失败不回半态）、`test_changeAudit.py`（审计只追加）、`test_semver.py`（规则判定）。
- **工作包**：B12。

### §12.10 L9 评估层

- **目标**：CQ 测试、负例、golden、OntoClean/OOPS! 子集、OQuaRE 指标、检索 NDCG、A/B。
- **现状**：单测＋Turtle golden（B5）＋`retrieval_metrics.py`/benchmark；CQ/OOPS!/OntoClean/OQuaRE 在产品代码零命中。
- **设计**：
  1. CQ 测试：`tests/unit/knowledge/ontology/cq/` 按 CQ 文件生成用例；P1 CQ 100% 通过；负例（非法事实/坏形状）按预期拒。
  2. golden：Turtle/JSON-LD/OWL/SHACL/PROV 固定小库快照，字符级比对；变更需显式更新。
  3. OOPS! 结构子集：孤儿类、缺 label/definition、domain/range 不匹配、缺 disjointness、父链成环、逆关系单边、冗余子类；按 severity 报告。
  4. OntoClean 子集：对 upper-lite 与核心类标注 rigidity/identity/unity/dependence；只做人工可复核的矩阵，不自动改类。
  5. OQuaRE 风格指标：coverage/consistency/conciseness/expandability，进 CI 报告；不做完整认证（§4 L9 拍板项 4）。
  6. 检索 NDCG/A-B：ontology 变更前后跑 benchmark，NDCG 下降超阈值即红；与 B7 的 `retrieval_metrics` 同源。
  7. **默认关矩阵**：D-01/D-02/D-03/D-04/D-06/D-08/D-11/D-16/D-19 逐项 shadow/on，不打包全开；默认关是产品/成本/安全决定，不是断点；501/空列表是诚实状态。
- **测试/验收**：`test_ontologyQuality.py`、`tests/unit/knowledge/ontology/cq/`、`tests/unit/knowledge/ontology/golden/`；CI 报告 CQ 通过率/质量分/NDCG delta。
- **工作包**：B13。

### §12.11 B9–B14 工作包卡

| 工作包 | 层 | 范围 | 红灯文件 | live-verify |
|---|---|---|---|---|
| B9 | L0/L1 | CQ/边界/术语表/追溯；upper-lite/身份判据/no-punning | `test_cqTraceability.py`、`test_upperLite.py` | 跑 CQ 目录全量；seed upper-lite；导出 BFO 映射 |
| B10 | L2/L4 | SKOS 多语言/模块/版本化 IRI；shape 注册表/写入前/dry-run | `test_termSkosLabels.py`、`test_ontologyShapes.py`、`test_shapeDryRun.py` | 建 shape → 拒非法事实 → dry-run 同 finding → 导出 shapes |
| B11 | L3/L5 | 限定关系 schema/asOf/knownAt/事件时间；OWL 2 RL 子集/解释链 | `test_qualifiedRelationSchema.py`、`test_bitemporalQuery.py`、`test_owl2rlProfile.py`、`test_explanationChain.py` | 写双时态事实→asOf/knownAt；逆/传递推导→解释链→撤销 |
| B12 | L6/L7/L8 | 稳定 IRI/分页投影；JSON-LD/OWL/SHACL/PROV；发布/回滚/审计/语义版本 | `test_stableIri.py`、`test_accessProjectionPagination.py`、`test_interopExports.py`、`test_governanceRollback.py` | 建术语→基线→改动→diff→回滚；五格式导出；IRI 解析 |
| B13 | L9 | CQ 测试/负例/golden/OOPS!/OntoClean/OQuaRE/NDCG A-B | `tests/unit/knowledge/ontology/cq/`、`tests/unit/knowledge/ontology/golden/`、`test_ontologyQuality.py` | 跑 CQ 全量；质量报告；ontology 变更 A/B |
| B14 | 跨 L3/L7/L8 | 企业源 Protocol/JSON 映射描述符/fake adapter/admission 接线；真实连接器另立项 | `tests/unit/knowledge/enterprise/` 下 `test_enterpriseSourceProtocol.py`、`test_sourceSchemaMapping.py`、`test_enterpriseIngestAdmission.py` | fake adapter→facts→既有查询面；默认关零调用 |

> 依赖：B9 → B10 → B11 → B12 → B13；B10 依赖 B8，B11 依赖 B1/B8，B12 依赖 B10/B11，B13 依赖 B9–B12。B14 依赖 B10/B11，且在 B13 之前（v34 先落，B13 无 schema，放最后评估）。B14 详设见 §14；一次性执行顺序见 §16（编号不是交付批次）。

### §12.12 设计依据与边界

- **语义上界选 OWL 2 RL 而非 OWL 2 DL**：RL 是面向规则引擎/RDBMS 的多项式时间档；本仓已有 Datalog 片段与 SQLite 递归 CTE，演进成本最低。OWL 2 DL/HermiT/Pellet 与"零新增第三方依赖、本地单进程"冲突。
- **推理与校验分离**：OWL 2 RL 子集负责可规则化推导（物化）；SHACL 语义负责闭合世界完整性（写入前/dry-run）。两者共用事实但不共用执行路径，避免"用推理做校验"或"用校验冒充推理"。
- **溯源与时间是一等公民**：PROV-O 对齐断言/活动/推导；valid time 与 transaction time 双轴；推导走账本、撤销精确。没有这两条，本体只能"看起来对"，不能审计。
- **标准只作互操作与导出**：SKOS/OWL-Time/PROV-O/SHACL 的词汇与形状只进对齐层/导出层，不引第三方实现；RDF 1.1 为生产基线，RDF 1.2 只观察。
- **CQ 驱动、先红后绿**：每条 CQ 有查询与测试；每个能力先有失败判据再落码；L9 用 CQ/负例/golden/NDCG 把"完整"变成可回归的读数，而不是词表规模。
- **明确不做**：整包 BFO/SUMO/DOLCE、OWL DL/SPARQL 引擎、第三方 SHACL 引擎、`owl:sameAs` 自动合并、RDF 1.2 生产化、重开 011 两池交织、gaps/learn 伪造数据；默认关不是断点。理由见 §6；这些不是"以后再做"，是当前产品约束下的边界。
- **B14 只预留接口**：真实 DB/ERP/事件流连接器、全量 R2RML 解析、CDC 游标另立项；本工作包不引 DB 驱动/消息中间件，只落 Protocol/JSON 描述符/fake adapter/admission 接线。
- **UI 只做任务面**：UI-0–UI-4 跟随 B9–B14；默认关/观察态必须在界面可见，不伪造已接入/已启用；后端端点未落不做假 UI。

## §13 知识库未接线与默认关闭审计并入（2026-11-05）

> 复核对象：`docs/specs/2026-11-05-知识库未接线与默认关闭修复计划.md`（并发会话产出，工作树未跟踪）。本文只并入与本体语义栈相关的结论；死码卫生、联邦 KB、`memory_links`、非飞书同步、gaps/learn 等非本体项仍以该计划为权威，不在本计划重复立项。
> 复核方法：文件存在性＋生产导入/调用 grep＋关键环境变量默认值读取＋端点消费者搜索；未跑测试、未改码。

### §13.1 核实结论

| 编号 | 原结论 | 复核 | 关键证据 | 对本体计划的影响 |
|---|---|---|---|---|
| K-01 | `knowledge/config.py` 零生产导入 | **属实** | 无 `from neurova.knowledge.config` 生产导入；`knowledge/__init__.py` 不导入；仅测试路径落点引用 | 非本体项；不并入，按 KB 计划 P0 退役 |
| K-02 | 联邦 KB／多库路由零生产消费者 | **属实** | `federated_kb.py` 只被自身内部导入 `multi_kb_router`；`kb_catalog_tool` 仅 `multi_kb_router` 内部使用；无生产调用 | 非本体项；作为 L9"测试绿≠生产接线"的评估案例，不新增本体工作包 |
| K-03 | `FoundationReconciler` 类零调用 | **属实（有导出面）** | `foundation/__init__.py` 仍导出该类；生产代码无调用；`_assertionFor`/`_requestsFromRepository` 仍被 `backfill`/`entry_ledger` 使用 | 非本体项；不并入 |
| K-04 | `LegacyFactBackfill` 仅诊断脚本 | **属实** | 唯一调用 `scripts/diagnostics/_kb_backfill_rerun.py:36`；`neurova/` 零导入 | 非本体项；不并入 |
| K-05 | `memory_links` 只写不读、无属主 | **部分属实，口径需修正** | `/sync/links` 会读（`knowledge_integration.py:179-185`），但没有聊天/检索消费者；链接无 `user_id/agent_id`，列表端点返回全量（`storage.py:258-280`）⇒ 跨用户元数据泄露面 | 非本体项；不并入；作为 L3 租户隔离的反例，安全修复以 KB 计划 D-3 为准 |
| K-06 | 非飞书远程源同步被 400 拒绝 | **属实** | `knowledge_remote.py:146-147` 仅 `source_type=="feishu"` 放行 | 非本体项；不并入 |
| K-07 | gaps/learn 恒 501/空 | **属实** | `knowledge_integration.py:219-264`：`/gaps/analyze`、`/learn` 501；`/gaps`、`/learning-records` 空；`evolution/progress` 计数 0 | 非本体项；不并入；L9 不把 501 当成功 |
| K-08 | `access`/`integration` HTTP 面仓内零消费者 | **属实（保留为对外契约）** | 生产代码仅 `api/endpoints/__init__.py:302` 注册；`NeurUI/src`、`neurova/agent`、`context`、`post_chat_pipeline` 无调用 | **并入 L6**：B3 四动词门面按对外契约管理，补 OpenAPI/SDK 契约测试；不宣称"已闭环" |
| K-09 | TD② recency／FTS 源时间／facts 源钟未实现 | **属实** | `hybrid.py` 无时间因子；`fts_index.py` 表无 `source_modified_at`；`conflict_judge.py:118` 按 `recorded_at` 选 most_recent；TD① 仅在 `POST /knowledge/search` 接 `source_modified_after/before`（`knowledge_core.py:199`），GET 列表未接 | **并入 L3/L7**：B11 补时间因子/FTS 源时间/facts 源钟，默认关；B12 导出带源时间 |
| K-10 | `FactSurface` 窄接线，不是死码；011 已否证两池交织 | **属实** | `read_surface.py:29` 默认 off；`graph_walk.py:115` 只在强判据零锚点时调用；`read_surface.py:172` 注释记 011 实测 recall@5 0.8555→0.7604 | **并入 L3/L5**：FactSurface 只做零锚点种子与治理富化；不重开两池交织；不新增事实池 |
| D-01/D-02/D-03/D-04/D-06/D-08/D-11/D-16/D-19 | 默认关/legacy；shadow 先行 | **抽查属实** | `query_normalization.py:40` off、`ambiguity_clarification.py:39` off、`knowledge_retriever_adapter.py:33` off、`read_surface.py:36` False、`derivation_citation.py:37` off、`vector_index.py:57` off、`retrieval_fusion.py:1` 默认关、`knowledge_common.py:275` off、`parser_shadow.py:51` legacy | **并入 L9**：默认关矩阵与 shadow/on 评估门；D-06 条件类仍 off，B1 已落≠已转正 |

> 其余 D 组抽查：D-05/D-07/D-09/D-12/D-13/D-14/D-15/D-17/D-18/D-20/D-21 的默认值与文档一致（off/weight/local/空集）；D-10 精修四连仍在 per-request 旁路。未逐项跑测。
> 汇总：4 个零消费模块/类中 K-01/K-02/K-03 属实，K-04 为"保持不启用"而非死码；4 处半接线中 K-05 摘要口径需修正（有 `/sync/links` 读取，但无检索消费者且无属主），K-06/K-07/K-08 属实。关键默认值抽查与代码一致；未逐项跑测。

### §13.2 并入点

| KB 项 | 并入点 | 具体动作 |
|---|---|---|
| K-08 | §12.7 L6、§10 B3 行 | B3 四动词门面按对外契约保留；补 OpenAPI/SDK 契约测试；"端点存在"不当作"链路闭环" |
| K-09 | §12.4 L3、§12.8 L7、B11/B12 | TD② recency、FTS `source_modified_at`、facts 源钟按独立工作包；默认 0/关，先测后开 |
| K-10 | §12.4 L3、§12.6 L5、§6 | `FactSurface` 只做零锚点种子与治理富化；不重开 011 两池交织；不新增事实池 |
| D-06 | §12.6 L5、§12.10 L9 | 条件类推导主路仍默认 off；B1 已落不等于转正，须 L9 的 CQ/检索 A-B 读数 |
| D-01/D-02/D-04/D-19 | §12.10 L9 | 默认关矩阵；shadow→on 逐项独立，不打包全开 |
| K-02 | §12.12、L9 | "测试绿≠生产接线"案例；CQ 除测试外还要核生产调用方 |
| K-01/K-03/K-04/K-05/K-06/K-07 | §13.3 | 非本体项，不在本计划重复立项 |

### §13.3 不并入项

- **K-01 `knowledge/config.py`、K-03 `FoundationReconciler`、K-04 `LegacyFactBackfill`**：属死码卫生/迁移工具，归 KB 计划 P0；本体计划不重复开批。
- **K-02 联邦 KB、K-05 `memory_links`、K-06 非飞书同步、K-07 gaps/learn**：属远程检索、关联簿记、数据源同步与学习闭环，归 KB 计划 P1/P3（K-07 保持 501/空，不改）；本体计划只在 L3/L9 引用其结论（租户隔离反例、测试绿≠接线），不复制实施步骤。
- **K-05 的 `memory_links` 安全修复**：`/sync/links` 无属主过滤是独立的跨用户读取面，必须在 KB 计划 D-3 处理；本体 L3 的租户隔离判据可把该案例列为反向样本。

### §13.4 对现有计划的修正

- **B3 不是"闭环已完成"**：四动词门面已落，但仓内零消费者（K-08）；在 §10 B3 行标注为对外契约，L6 补 OpenAPI/SDK 契约测试。
- **B1 不是"条件类已转正"**：`NEUROVA_CONDITION_CLASSES_ROUTE` 仍默认 off（D-06）；观察态是默认，转正须 L9 评估。
- **L3 不新增事实池**：`FactSurface` 只做零锚点种子与治理富化（K-10）；011 已否证两池按秩交织，重开即回退已否证路径。
- **L9 增加默认关矩阵**：D-01/D-02/D-03/D-04/D-06/D-08/D-11/D-16/D-19 逐项 shadow/on，不打包；501/空列表是诚实状态，不是成功。
- **评估口径**：测试绿不等于生产接线；K-02 联邦 KB、K-08 四动词门面是反例，L9 的 CQ 除测试外还要核生产调用方。

## §14 B14 企业数据源接入器与源库 schema 映射（接口预留，2026-11-05）

> 定位：对应评测 V5。用户要求纳入本计划，但只预留接口；本工作包不接真实 DB/ERP/事件流，不引 DB 驱动/消息中间件，所有新能力默认关闭。真实连接器另立项，只能按本工作包发布的 Protocol 与描述符接入。

### §14.0 目标与边界

- **目标**：把企业源（SQL/ERP API/事件流）到 facts 的接入面固定为可测试契约：适配器 Protocol、映射描述符、游标/幂等、admission 接线。
- **边界**：无真实连接器、无 CDC、无全量 R2RML 解析、无写回源；只读适配器；默认 `enabled=False`；不新增第三方依赖。
- **落点**：`neurova/knowledge/enterprise/`（新子包）——`protocols.py`、`schema_mapping.py`、`registry.py`、`fake_adapter.py`（测试替身）；不碰 `agent_core.py`。

### §14.1 适配器 Protocol

```python
class EnterpriseSourceAdapter(Protocol):
    async def describeSchema(self) -> SourceSchema: ...
    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch: ...
    async def health(self) -> SourceHealth: ...
    async def close(self) -> None: ...
```

- `SourceSchema`：逻辑表/列或事件 schema；只读元数据，不含凭据。
- `ChangeBatch`：`rows/events`、`next_cursor`、`has_more`、`fetched_at`；空批必须显式 `has_more=False`，不得用空列表冒充成功。
- `SourceCursor`：不透明字符串，由适配器解释；核心层不解析成 SQL。
- `SourceHealth`：`ok/degraded/error`＋原因；失败显式，不静默空批。
- 适配器按 `sourceType` 注册（`sql`/`erp_api`/`event_stream`），注册表只允许白名单类型；默认不注册任何真实适配器。

### §14.2 源库 schema 映射描述符

R2RML 风格的 JSON 子集，不做完整 R2RML/SPARQL 引擎：

```json
{
  "sourceId": "erp_prod",
  "tenantId": "default",
  "sourceType": "sql",
  "logicalTable": "orders",
  "subject": {"template": "order:{order_id}", "typeTerm": "Order", "identityKeys": ["order_id"]},
  "predicate": {"termId": "has_status"},
  "object": {"column": "status", "kind": "literal"},
  "qualifiers": {"channel": "channel_code"},
  "validFrom": "valid_from",
  "validUntil": "valid_until",
  "cursorColumn": "updated_at",
  "idempotencyKey": ["order_id", "updated_at"],
  "enabled": false
}
```

- 映射种类：subject 模板、predicate 常量（必须是已登记 `term_id`）或列映射（列值必须命中白名单 `term_id`，未命中记 finding，不猜）、object 列/模板/常量术语/字面量、qualifiers 列、valid time 列；事件源另有 `eventType/occurredAt/participantColumns`。v1 只支持单逻辑表/单事件流；跨表 join、聚合、子查询另立项，映射里不写 SQL。
- 编译期校验：模板占位符必须是已声明列；predicate 必须已登记；object 的 `kind` 与术语/字面量匹配；不允许任意 SQL、子查询、函数调用；不许把未声明的列写进 qualifier。
- 配置与游标：优先复用现有 source config 存储；若现有表不能承载 `descriptor_json`/`cursor`，走 v34 迁移新增 `enterprise_source_configs`（`source_id, tenant_id, descriptor_json, cursor, enabled, created_at, updated_at`）。不另造第二套凭据存储，复用 `NEUROVA_KB_SECRET`。
- 映射描述符按租户隔离；`sourceId` 在租户内唯一；同一 source 的 descriptor 版本变更走 L8 的治理与 diff。

### §14.3 写入路径与安全

- **唯一写口**：`adapter.fetchBatch → mapping.apply → AdmissionRequest → admission gate`；不直插 SQL，不新开第二个写口。`fetchBatch` 为 async；mapping 与 admission 是同步 SQLite 写，放 worker 线程执行，避免阻塞事件循环。每行一条 `AdmissionRequest`，批量用 B7 的 `admitBatch` 语义；坏一行只退它自己，逐条 finding 留名。
- **来源与时间**：`activityKind="import"`，`actorType="importer"`，`mediumRef="source:<sourceId>:<cursor>"`；valid time 从映射列取，缺省留空（不猜）；transaction time 由 admission 写。
- **幂等与游标**：`(sourceId, idempotencyKey)` 去重；游标在 **source batch 处理完成** 后推进——逐行 admission 拒绝要留名但不阻塞游标，只有 fetch/事务/系统级失败才不推进；重放不产生重复事实。
- **安全**：适配器只读；sourceType 白名单；映射不允许任意 SQL/模板表达式；凭据只从 `NEUROVA_KB_SECRET` 解密；tenant/user 作用域在配置读取与 admission 两处校验；日志不落凭据与原始行全文。
- **观测**：sourceId、cursor、rows_fetched、facts_admitted、rejected、latency；失败原因显式；默认关闸时零调用、零网络。

### §14.4 测试与验收

- 红灯 `tests/unit/knowledge/enterprise/test_enterpriseSourceProtocol.py`：fake adapter 的 describeSchema/fetchBatch/health/close；空批/错误/游标形状。
- 红灯 `tests/unit/knowledge/enterprise/test_sourceSchemaMapping.py`：合法/缺列/未登记 predicate/未知 object kind/模板注入/租户隔离/默认禁用。
- 红灯 `tests/unit/knowledge/enterprise/test_enterpriseIngestAdmission.py`：fake adapter → mapping → admission；事实落库；坏行不拖 source batch；游标在 source batch 完成后推进/source batch 级失败不推进；重放幂等；跨租户不可见；零外部依赖。
- live-verify：进程内 fake adapter＋夹具表，不联网、不接真实 DB；映射到 facts 后经既有查询面读回；命令与输出原文进提交说明。
- 验收：Protocol/描述符稳定；fake adapter 端到端；默认关零调用；真实连接器与全量 R2RML 解析明确不在本工作包。

### §14.5 不纳入真实连接器

- 真实 DB 驱动（PostgreSQL/MySQL/Oracle）、ERP API、Kafka/MQTT/CDC、全量 R2RML 解析、写回源，均另立项；本工作包不新增依赖、不接外部服务。
- 未来真实连接器必须实现同一 Protocol、输出同一 `ChangeBatch`、经同一 admission 写口；不得另造第二套摄取路径。

## §15 前端 UI 知识库功能对齐与页面重构设计（2026-11-05）

> 定位：前端不是把后端能力"画出来"，而是按 TBox（类型/约束/推理/发布）与 ABox（事实/时间/溯源/查询）分离重排任务面。现有三页保留为数据管理、本体工作台、评测质量；新增事实浏览、互操作/导出、企业源接口预留。UI 作为 B3 四动词的首个仓内消费者（落地前 K-08 的零消费者结论仍成立）。
>
> **参考原型**：[2026-11-05-knowledge-ui-prototype.html](assets/2026-11-05-knowledge-ui-prototype.html)。自包含 HTML，浏览器直接打开；默认本体工作台，7 页可切换（知识库 / 本体工作台 / 事实浏览 / 互操作导出 / 评测质量 / 企业数据源 / 观测开关）。交互为原型级，不接后端、不写数据；不作为 §15.7 的验收证据。

### §15.0 现状与结论

- **`/knowledge` KnowledgePage**：条目列表/搜索/导入、MCP 源、冲突队列、墓碑、revision、chunk 预览、远程 KB 配置、ingest 任务——是**数据管理页**，不承担本体语义。
- **`/agent/:id/knowledge-graph` 与 `/graph-workbench` GraphWorkbenchPage**：2D/3D 图画布＋术语 CRUD（仅 id/kind/label/basis）＋规则 JSON 文本域＋实例建边＋空间页签——是**图/本体雏形**，但缺 L2 字段、形状、CQ、推理解释、发布治理。
- **`/knowledge-eval` KnowledgeEvalPage**：基线、检索快照、A/B 对比，且结果以原始 JSON 呈现——是**检索评测页**，不覆盖 CQ/质量/OOPS!/OntoClean/OQuaRE。
- **`KnowledgeLineageDrawer`**：事实血缘抽屉，已可作为 L3/L5 的事实详情底座。
- **结论**：不需要推倒三页重做；需要把 GraphWorkbench 拆成 **Ontology Studio（TBox）＋ Fact Explorer（ABox）**，KnowledgePage 保留数据管理并加深链接，KnowledgeEval 升级为质量仪表盘，新增互操作/导出、企业源接口预留两页。

### §15.1 能力 → 页面矩阵

| 能力（层/批） | 现有 UI | 目标 UI | 动作 |
|---|---|---|---|
| L0/B9 CQ 目录与追溯 | 无 | Ontology Studio「概览/CQ」：CQ 表、查询/测试状态、覆盖率 | 新增 |
| L1/B9 upper-lite、类型/实例、身份判据 | 仅 kind 下拉 | 术语树显示 upper 根（Entity/Continuant/Occurrent/…）、类型/实例切换、identityKeys | 扩展 |
| L2/B8/B10 类层次、属性特征、别名、SKOS、模块、版本化 IRI、弃用 | 仅 id/kind/label/basis | 结构化术语编辑器：parent/domain/range/disjoint/cardinality/required/aliases/多语言 label/module/deprecated/replacedBy/external IRI/version | 重做 |
| B8 关系映射与候选 | 无 | Relations 页：关系 profile（inverse/symmetric/transitive/functional=cardinality 1）＋候选审批队列 | 新增 |
| L3/B11 限定三元组、双时态、置信、来源、冲突、租户 | 条目列表＋冲突队列＋血缘抽屉 | Fact Explorer：qualifiers、valid/transaction time、asOf/knownAt、confidence、provenance、conflict、tenant | 新增 |
| L4/B10 形状注册表、写入前/dry-run | 无 | Shapes 页：target/path/severity/message 构建器＋dry-run 结果面板 | 新增 |
| L5/B11 条件类、物化、账本、精确撤销、解释链 | 规则 JSON 文本域 | Reasoning 页：规则/条件类构建器、observe/enforce、推导账本、解释链抽屉 | 重做 |
| L6/B12 四动词、稳定 IRI、分页/投影、租户 | 条目 GET/POST；无统一查询面 | Query Workbench：query/analyze/validate/use＋asOf/knownAt＋fields/cursor＋IRI 解析 | 新增 |
| L7/B12 Turtle/JSON-LD/OWL/SHACL/PROV 导出 | 单 fact Turtle | 互操作/导出页：格式卡、租户/模块范围、确定性预览、下载 | 新增 |
| L8/B12 提案→dry-run→基线→发布→diff→回滚；审计；语义版本 | 无 | Release 页：步骤时间线、diff 视图、回滚、审计、弃用策略 | 新增 |
| L9/B13 CQ/负例/golden/OOPS!/OntoClean/OQuaRE/NDCG A-B | 基线/快照/对比原始 JSON | Evaluation 页：CQ 通过率、质量卡、golden diff、NDCG/A-B、默认关矩阵 | 重做 |
| B14 企业源接口预留 | 无 | Enterprise Sources：源列表、描述符编辑器、fake adapter 演示、「接口预留/未接入真实源」 | 新增 |
| D 组默认关/观察态 | 无 | 观测与开关面板：D-01/D-02/D-04/D-06/D-08/D-11/D-16/D-19 状态与 shadow 读数；不做一键不安全开启 | 新增 |

### §15.2 信息架构（导航）

```
知识与认知
├─ 知识库            /knowledge                     条目、导入、来源、冲突、MCP
├─ 本体工作台        /agent/:id/ontology-studio     概览/CQ、术语、关系、形状、推理、发布
├─ 事实浏览          /agent/:id/facts               ABox 查询、双时态、溯源、解释链
├─ 互操作与导出      /knowledge/interop             Turtle/JSON-LD/OWL/SHACL/PROV
├─ 评测与质量        /knowledge-eval                 CQ、质量、NDCG、A-B、默认关矩阵
└─ 企业数据源        /knowledge/enterprise-sources  接口预留、描述符、假适配器
```

- `/agent/:id/knowledge-graph` 保留为 `ontology-studio` 的兼容入口（书签不失效）；旧页签内容迁入 Studio 的 Terms/Relations/Reasoning。
- `KnowledgePage` 不改成图编辑器；通过「查看语义」跳到 Fact Explorer / Ontology Studio。
- 导航沿用 `MainLayout.vue` 与 `config/modules.ts`；「知识图谱」标签改为「本体工作台」（旧 URL 不变），新增「事实浏览」「互操作/导出」「企业数据源」，同步 11 语言 i18n。

### §15.3 页面设计

- **KnowledgePage（保留）**：条目表格继续承担导入/搜索/分享/冲突/墓碑；补派生/观察态徽标（有则显示），保留既有源时间列与 `source_modified_after/before` 过滤（TD① 已有）、「查看语义」深链；冲突队列直接打开 Fact Explorer 的解释链。
- **Ontology Studio（由 GraphWorkbench 重做）**：
  - 左：图画布（类型图/实例图切换，2D/3D/空间保留）。
  - 右：纵向分区导航（概览/CQ/术语/关系/形状/推理/发布），避免 7 个横排 tab 挤压画布。`概览`（upper 树、术语/规则计数、schema 版本、CQ 健康、候选/发布状态）、`术语`（树/表、搜索、模块/弃用过滤、结构化编辑器）、`关系`（profile＋候选审批）、`形状`（构建器＋dry-run）、`推理`（规则/条件类、observe/enforce、账本、解释链）、`发布`（提案→dry-run→基线→发布→diff→回滚、审计）、`CQ`（表＋运行＋追溯）。
  - 所有写操作前提供「校验」按钮；校验结果与写入路径同一 finding 形态。
- **Fact Explorer（新增）**：四动词查询条（query/analyze/validate/use）＋`asOf`/`knownAt`＋tenant＋`fields`/cursor；结果表格＋图视图；事实详情展示 qualifiers、confidence、evidence、provenance/assertions、conflict、derivation；动作：采纳/使用、查看血缘、导出、打开解释链；时间轴明确区分「业务时间」与「记录时间」。
- **互操作/导出（新增）**：Turtle/JSON-LD/OWL/SHACL/PROV 格式卡；租户/模块范围；确定性预览与下载；RDF 1.2 仅显示「观察」不提供生产开关。
- **Evaluation（由 KnowledgeEval 重做）**：CQ 覆盖率/通过率、负例结果、golden diff、OOPS!/OntoClean 子集、OQuaRE 风格指标、NDCG/A-B；原始 JSON 收进「高级」抽屉，不再作为主界面。
- **Enterprise Sources（新增，B14）**：源列表显示「接口预留/未接入真实源」；描述符编辑器（subject/predicate/object/qualifiers/cursor/idempotency）；fake adapter 演示；不提供假装已连接的真实源按钮。
- **观测与开关（新增，管理员）**：D 组默认关/观察态、shadow 读数、一键回退；不在普通用户面暴露写入开关。

### §15.4 交互与诚实性规则

- **派生/观察态必须可见**：推导事实带「推导」徽标；`NEUROVA_CONDITION_CLASSES_ROUTE` 等默认关状态显示「观察态/默认关」，不得显示为绿色已启用。
- **校验分级**：violation 红色阻断、warning 黄色记账、info 灰色遥测；dry-run 与写入必须返回同一 finding 定位串。
- **双时态不混轴**：`asOf` 与 `knownAt` 两个独立控件，结果表头标明当前查询轴；不允许把两者合成一个「时间」下拉。
- **候选只人工批准**：关系候选/别名候选只能 approve/reject，不自动升格；批准动作显示来源文本与置信度。
- **企业源不伪装**：B14 页面只能显示「接口预留」，真实连接器未接入时禁用「连接/同步」并给出原因。
- **稳定 IRI 可复制/可解析**：详情页显示 `kbg:` IRI 与复制按钮，解析失败显式报错。
- **i18n/主题/响应式**：新增文案进 `zh-CN` 并同步 11 语言；复用 `GlassPanel/GlassCard/GlassButton`，只用 `src/styles/variables.css` 令牌，不硬编码色值；窄屏下表格转卡片、图与详情可切换。
- **权限**：写入/发布/回滚仅管理员；普通用户只读与 use；租户隔离在 API 与 UI 两处校验。

### §15.5 API 契约与缺口

- 现有可复用：`GET /knowledge-graph/{agentId}/studio`、`/knowledge/ontology/terms|rules`、`/knowledge/graph/instances`、`/knowledge/conflicts`、`/knowledge/facts/{factId}/lineage`、`/knowledge/facts/{factId}/turtle`、`/knowledge/evaluation/baseline|audit/evaluation/compare|audit/retrieval-metrics`。
- 随 B 批新增的 UI 契约：B2 `POST /knowledge/ontology/validate`；B3 `/knowledge/access/{query|analyze|validate|use}`；B8 关系候选列表/审批；B9 CQ 目录与运行；B10 shapes CRUD/dry-run；B11 `asOf/knownAt` 与 `GET /knowledge/ontology/derivations/{fact_id}`；B12 稳定 IRI 解析、五格式导出、发布/diff/回滚/审计；B13 CQ/质量/NDCG；B14 企业源描述符与 fake adapter。
- **B3 消费面**：UI-2 起以 `/knowledge/access/*` 作为四动词主入口（UI 成为首个仓内消费者）；在 UI 落地前，K-08「仓内零消费者」仍成立，落地后同步更新 §13.4 与 KB 计划。
- 类型与信封：新增 `ontology.ts`/`knowledgeInterop.ts`/`knowledgeGovernance.ts` 等模块，禁止 `any` 直塞；统一 `{items,total,next_cursor}`、severity、derivation、bitemporal 类型；API 文档同步 `docs/02-api/API_REFERENCE.md`。

### §15.6 UI 实施顺序（同一次执行内完成）

| UI 步骤 | 对应工作包 | 交付 |
|---|---|---|
| UI-0 | B8/B9/B10 | Studio 壳、术语/关系、CQ、Shapes；KnowledgePage 深链 |
| UI-1 | B11 | Fact Explorer、双时态、解释链、qualifier 详情 |
| UI-2 | B12 | 四动词 Query Workbench、IRI 解析、互操作/导出、Release |
| UI-3 | B13 | Evaluation 仪表盘、默认关矩阵、质量门 |
| UI-4 | B14 | Enterprise Sources「接口预留」页与 fake adapter 演示 |

> UI-0–UI-4 不是交付批次；在后端工作包全部落定后按序完成，最后与后端一起收口（§16）。

- 后端端点未落前不做假 UI；测试可用 fixture，生产不得用 mock 数据冒充已接入。
- 旧 URL 保留；旧页退役前先加 redirect，不直接 404。
- 视觉参考：`assets/2026-11-05-knowledge-ui-prototype.html`；真实页面仍按 UI-0–UI-4 落，原型不替代浏览器实测。

### §15.7 验收

- `npm run test`（vitest）＋`npx vue-tsc --noEmit`；新页组件测试覆盖空态/错误态/权限态。
- 前端实跑：浏览器走通「建术语→校验→建关系→查询→解释链→导出→发布→回滚」「CQ→质量→A-B」「企业源→fake adapter→事实」三条链。
- i18n 11 语言一致性、主题令牌无硬编码色值、窄屏可用、键盘可达。
- 不把原始 JSON 作为主界面；不把默认关/观察态显示为已启用；不把 B14 显示为已接入。

### §15.8 非目标

- 不做完整 Protégé/OWL DL 编辑器、SPARQL 控制台、全量 R2RML 编辑器、真实 DB/ERP/事件流连接器 UI。
- 不把 KnowledgePage 改成第二个图编辑器；不新造第二套知识数据页。
- 不改造 `ExperienceKnowledgePage`（EKB）；它属于经验知识，不经本体 TBox/ABox。
- 不隐藏默认关/观察态，不以 UI 动画或文案掩盖后端未接线。
- 原型文件不是生产页面，不进入前端构建；不得以原型演示替代真实页面验收。

## §16 一次性执行 Runbook（给执行 Agent，2026-11-05）

> 本文不再按 B1–B14 分批交付。B1–B14 是工作包编号；所有工作包在同一次执行内按本节顺序完成，最后统一收口。每个工作包的门是继续条件，不是交付节点；门失败就在原地修复，不带病进入下一步。

### §16.0 执行口径

- **拍板**：§4 的待拍板项按推荐选项 A 执行；现场证据与推荐冲突时停止并报告，不静默改方向。
- **B1–B7**：已在 HEAD；Preflight 只核验与跑回归，不重做。若缺失，按 B2→B1→B3→B4→B5→B6→B7 补齐后再进入 B8。
- **迁移硬序**：B8 v29 → B9 v30 → B10 v31 → B11 v32 → B12 v33 → B14 v34；不得跳号、不得先加高版本再补低版本。
- **提交**：同一次执行内可按工作包分笔提交到同一分支，但**不推送、不交付**；最终门全绿后一次性收口。
- **红绿**：每个工作包先红后绿；红灯必须落在行为断言；禁止用 import/collection error 冒充红灯；装配噪声（401/dependency_overrides）先排。
- **数据根**：live-verify 走 `_liveVerifyIsolation.isolatedDataRoot`；探针 `.tmp_*` 即用即删，不写仓内真库。
- **回退**：工作包内部失败可 `git revert` 该包提交；整次执行失败不交付，不回滚已落的 B1–B7。

### §16.1 执行顺序

| 步骤 | 工作包 | 迁移 | 依赖 | 继续门 |
|---|---|---|---|---|
| S0 | Preflight：B1–B7 已落核验 | — | HEAD | `tests/unit/knowledge/`、`tests/unit/agent/` 基线；预存红清单与 HEAD 对号；工作树/数据根隔离；B1–B7 缺失则按 B2→B1→B3→B4→B5→B6→B7 补齐 |
| S1 | B8 关系映射 | v29 | B2/B1 | `test_relationMapping.py` 十组＋`test_ontologyRelationCandidates.py`；live-verify 别名/未知关系/导出；`custom` 不再静默丢弃 |
| S2 | B9 L0/L1 基础层 | v30 | B8 | `test_cqTraceability.py`、`test_upperLite.py`；P1 CQ 全绿；upper-lite/no-punning/identity；BFO 仅导出映射 |
| S3 | B10 L2/L4 术语与约束 | v31 | B9/B8 | `test_termSkosLabels.py`、`test_termModules.py`、`test_versionedIri.py`、`test_ontologyShapes.py`、`test_shapeDryRun.py`、`test_shapeSeverity.py`；既有 6 项校验收编为内置 shape，撞车即拒 |
| S4 | B11 L3/L5 断言与推理 | v32 | B8/B10 | `test_qualifiedRelationSchema.py`、`test_bitemporalQuery.py`、`test_eventTimePattern.py`、`test_owl2rlProfile.py`、`test_explanationChain.py`、`test_materializationModes.py`；不支持的公理登记即拒 |
| S5 | B12 L6/L7/L8 访问互操作治理 | v33 | B10/B11 | `test_stableIri.py`、`test_accessProjectionPagination.py`、`test_interopExports.py`、`test_governanceRollback.py`、`test_changeAudit.py`、`test_semver.py`、`test_facadeTenantIsolation.py`；五格式导出逐字节确定；回滚逐字恢复 |
| S6 | B14 企业源接口预留 | v34 | B10/B11 | `tests/unit/knowledge/enterprise/` 三档；Protocol/描述符/fake adapter/admission；零真实驱动、零外部网络 |
| S7 | B13 L9 评估 | — | B9–B12/B14 | CQ 全量、负例、golden、OOPS!/OntoClean 子集、OQuaRE 风格指标、NDCG A-B；原始 JSON 只作高级抽屉 |
| S8 | UI-0 Studio 壳 | — | B8/B9/B10 | 术语/关系/CQ/Shapes 页面；`npm run test`＋`npx vue-tsc --noEmit`；组件测试覆盖空态/错误态/权限态 |
| S9 | UI-1 Fact Explorer | — | B11 | 四动词查询、`asOf/knownAt`、解释链、qualifier 详情；浏览器走通 query→detail→explain |
| S10 | UI-2 访问/互操作/发布 | — | B12 | Query Workbench、IRI 解析、五格式导出、Release/diff/rollback；UI 成为 B3 首个仓内消费者 |
| S11 | UI-3 Evaluation | — | B13 | CQ/质量/NDCG A-B 仪表盘、默认关矩阵 |
| S12 | UI-4 Enterprise Sources | — | B14 | 「接口预留/未接入」页、描述符编辑器、fake adapter 演示；真实连接按钮禁用 |
| S13 | Final gates | — | S1–S12 | §8 第 1–13 条、§15.7、浏览器三条链、i18n/主题、API 文档、台账、评分复评；全绿后一次性收口 |

### §16.2 停止条件

- **门不过**：同一工作包修复两轮仍红，停止并报告 `step / command / 输出 / 根因 / 剩余项`；不进入下一步。
- **推荐被推翻**：现场证据与 §4 推荐 A 冲突（如迁移号冲突、`head_subject_var` 行为不符、B3 消费面不可用），停止并报告，不擅自改设计。
- **schema 风险**：迁移非单调、需要改写已发布迁移、或可能写仓内真库，停止。
- **测试噪声**：新失败无法归因、或预存红未做 A/B 分离，停止。
- **后端缺失**：UI 所需端点未落，停止在 UI 步骤，不造假 UI/假数据。
- **纪律红线**：不使用 `--no-verify`、不 force push、不 `git add -A`；提交只带显式路径。

### §16.3 最终收口（一次性交付）

- S1–S13 全绿后，才允许推送/交付；推送与 PR 仍需用户授权。
- 同一分支内可按工作包分笔提交；提交正文逐包附红→绿实测、live-verify、净 LOC 去向。
- 若中途停止：**不交付半成品**；报告停止点、已落工作包、未落工作包、下一步最小动作。
- 最终产物：代码＋测试＋live-verify 输出＋UI 浏览器三条链＋API 文档＋i18n/主题门＋台账＋评分复评。

### §16.4 为什么是这个顺序

- **迁移号**：B8 是 v29，必须先于 B9(v30)/B10(v31)/B11(v32)/B12(v33)/B14(v34)；先做 B9 会把 v30 顶到 v29 前面，迁移注册直接失败。
- **依赖**：B10 依赖 B8 关系列与 B9 术语；B11 依赖 B8 自动规则与 B10 shapes；B12 依赖 B10/B11；B14 依赖 B10/B11。
- **评估最后**：B13 依赖 B9–B12/B14 的产物；放最后才能一次评估。
- **UI 最后**：后端端点全落后一次完成，避免每落一个后端就返工前端。
- **B1–B7 不重做**：它们已落；Preflight 只核验与回归，避免重复实现。

### §16.5 “一次做完”的交付定义

- “一次做完”＝所有工作包实现、所有门全绿、最终一次性收口；**不要求只有一个 commit**。
- 允许同一分支内逐工作包提交，但不得按工作包推送/交付/等待拍板；中途失败即停，不带病交付。
- 若执行 Agent 无法在单次会话内完成，按 §16.2 停在第一个失败门，报告剩余项；不得把未接线代码当“已完成”交付。
