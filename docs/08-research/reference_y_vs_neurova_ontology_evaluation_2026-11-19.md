# reference_y vs Neurova：本体（Ontology）域专项对照评测（2026-11-19）

> **性质**：外部参照项目代码级对照评测（研究参考，仅作背景，不可作事实源）。
> **参照项目**：代号 `reference_y`——一个开源（Apache-2.0）的「企业数据→本体→知识图谱」平台：把数据库、SaaS 工具与文档同步进来，由本体 agent 起草本体（`ontology.toml`+`mappings.toml`），经人审后加载进同团队出品的 Rust 图数据库，提供图浏览与带引用问答。Go 后端 + Next.js 16，约 19.9 万行，2,154 星，创建于 2026-10-07。
> **本文纪律**：全文不出现参照项目及所集成第三方产品实名，一律以「参照项目」「本体 agent」「图库」指代。文中 `file:line` 均为**对方仓库内路径**（克隆件当前工作区读数）；本仓侧行号为 2026-11-19 现场读数。
> **口径**：本文是**本体域专项**评测（取代同日已撤回的整体架构评测，撤回提交 `bbd8ccec1`）。评测轴沿用 [reference_n_vs_neurova_ontology_comparison_2026-11-15.md](reference_n_vs_neurova_ontology_comparison_2026-11-15.md) 建立的对照框架（数据模型/构建链路/消费链路/治理），本次补齐**量化评分卡**。本仓侧事实以当前代码为准（44 模块 9,020 行 + `enterprise/` 的 catalog/nl2sql 落点；reference_n §9 回执的 P1–P3 候选已全部现场核实在位）。

---

## 0. 结论摘要

**总分：Neurova 90/100 vs 参照系Y 77/100，Neurova 领先 13 分**（本体专项评分卡，8 维 20 子项，每子项 0–5）。

| 维 | 子项数 | Neurova | 参照系Y | 判 |
|---|---|---|---|---|
| A 本体建模表达力 | 3 | **14** | 8 | 本仓大胜：层次/多语言/单位/形状 vs 扁平类型 |
| B 本体获取与起草 | 3 | **14** | 12 | 本仓胜：对方端到端 agent 起草(5)是全场最强单项，本仓人工构建面(5)更全 |
| C 映射与血缘 | 2 | 8 | **10** | 对方胜：mappings 变换语言 + 字节级 claim 血缘 |
| D 版本化与演化 | 2 | 9 | 9 | 平：本仓回滚+重推闭环 vs 对方不可变版本+CAS 切换 |
| E 治理与准入 | 2 | 9 | 9 | 平：本仓 admission 咽喉 vs 对方 Check 三臂门禁+决策修剪 |
| F 推理与解释 | 2 | **9** | 7 | 本仓胜：溯因+推导账本精确撤销 |
| G 消费与 grounding | 3 | 12 | **13** | 对方略胜：read 七式+Explorer 可视化 |
| H 互操作与工程 | 3 | **15** | 9 | 本仓大胜：九格式导出+Ossie vs 仅私有格式 |
| **合计** | 20 | **90** | **77** | **Neurova 领先 13** |

一句话结论：两者是**互补象限**而非同位竞品——参照系Y 把「从数据到图的自动化生产管线」做到很高完成度（agent 起草、行映射语言、claim 级人审、load 版本工程），但本体模型本身扁平、无标准格式、引擎黑盒；本仓把「本体工程纵深」做得很厚（四层模型、SHACL 形状、分层否定推理、溯因、九格式互操作、CQ 追溯、双时态事实、租户隔离），但在「agent 端到端起草本体」与「映射语言表达力」上落后。**最值得吸收的三件事：Check 三臂门禁、Audit 数据驱动缺口审计、Assess 本体贡献度评估**（详见 §5）。

---

## 1. 对象概况

| 项 | 参照系Y | 本仓（对照基线） |
|---|---|---|
| 本体定位 | 数据图谱本体：把同步来的表/文档建模成图 schema，供浏览与问答 | 治理型知识本体：术语/规则/形状/事实四层，供 agent 知识治理与推理 |
| 本体模型 | 双格式：Definition v1（手写，永不加载）+ agent_bundle（`ontology.toml`+`mappings.toml`，生产格式） | `ontology_terms`/`ontology_shapes`/`ontology_rules` + `knowledge_facts`（事实层在 foundation） |
| 起草方式 | 本体 agent sidecar 多轮 turn（源码不在仓库，Go 侧持 JSON 契约 4.26.0） | schema_suggester（确定性基线+LLM 精化+join 探针）+ 管理面人工构建 + 文档 LLM 抽取 |
| 规则/约束 | Datalog 规则 + 约束（severity warn/block）+ 链接公理（implies/inverse_of/symmetric/transitive/chain） | Datalog 片段前向链（relay/合取/inverse/分层否定/CTE 传递闭包/auto_*）+ SHACL 风格形状五 DSL |
| 版本化 | OntologyVersion 不可变 + CAS 原子切换 + 决策修剪 + impact 四态 | semver + 基线 diff/回滚（逐字恢复+重推+精确撤销） |
| 存储 | MySQL 元数据 + S3 快照 + 图库（图+向量+BM25） | SQLite（knowledge_facts.db），全链 `(tenant_id,*)` 复合主键 |
| 消费 | read 七式（entity/pattern/explain/violations/evidence/query/view）+ Ask + Explorer | MCP 22 工具 + REST 84 路由 + 检索注入三路 + nl2sql（默认关）+ Studio 前端 |
| 互操作 | 无标准本体格式（仅私有 toml/JSON） | 九格式导出（Turtle/JSON-LD/OWL2RL/SHACL/PROV-O/GraphML/GEXF/Cypher/CSV）+ Ossie YAML 进出 + RDF/XML 导入（inert） |

---

## 2. 评分方法

- **评分卡**：本体专项 8 维 20 子项，每子项 0–5 分，满分 100。维度取自本体工程核心关注点，与 reference_n 的对照轴对齐（模型/获取/映射血缘/版本/治理/推理/消费/互操作工程）。
- **锚点**：0=无实现；1=骨架/占位无消费方；2=部分实现仅靠自觉；3=机制化覆盖主链路有明显边界；4=机制化+测试守卫+治理完备；5=机制化+测试+治理+实证闭环。
- **形态校准**：参照系Y 的本体服务于「数据→图」流水线，本仓的本体服务于「agent 知识治理」。评分按**本体工程通用能力**同卡同锚点评，不因形态偏袒任何一方；形态差异在 §4 各维说明。
- **证据**：双方均为本轮代码级深读（对方后端本体域全量；本仓 ontology 域 44 模块全量），引证到 file:line；测试规模、路由数等承重数字经现场 grep/ls 复核。

---

## 3. 逐子项评分表（20 项全表）

### A. 本体建模表达力（Neurova 14 / 参照系Y 8）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| A1 概念与层次 | **5** | 2 | 本仓：parent 层次+环判定（term_registry.py:278-283）、aliases 租户内唯一（:363-368）、多语言 labels/alt_labels BCP47（:337-346）、disjoint、deprecated/replaced_by、upper_lite 七类上层本体（upper_lite.py:24-66）、external_iris SKOS 三档+equivalentClass（:32-33）。对方：`[types.T]` 扁平集合，无 subClassOf/继承（turn_result.json:653-656 仅 description/props/key/names），无多语言、无别名、无弃用链 |
| A2 关系与属性 | **5** | 3 | 本仓：domain/range/range_kinds+cardinality（函数属性）+inverse_of 双向补齐+symmetric/transitive+qualifier_schema+datatype 五值闭集（term_registry.py:717-737、:79-89、:300-308）。对方：links 有 from/to/cardinality(one/many)/required/props（turn_result.json:653-656），属性仅六种标量类型（foundry_review_decisions.go:184-191），关系不带属性、基数只有两档 |
| A3 规则与约束 | **4** | 3 | 本仓：Datalog 片段（≤2 正原子 relay/合取/inverse/分层否定/CTE 传递闭包/auto_*，rule_engine.py:1-18、:377-397、:910-949）+SHACL 形状五 DSL+severity 三态（shapes.py:22-29）；自觉声明不做 OWL DL/SWRL。对方：Datalog 规则+约束带 severity（testdata/revise-entities.json 的 `violation(x,y) :- inside(x,y), inside(y,x).`）+链接公理 implies/chain；无分层否定、无形状校验、无递归控制声明 |

### B. 本体获取与起草（Neurova 14 / 参照系Y 12）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| B1 数据源 schema 摄取 | **4** | 3 | 本仓：describeSchema 已接线——refreshSchemaCatalog 注册即刷新落 `ontology_catalog_tables/columns`（knowledge_enterprise.py:294-326），五驱动统一（connectors_sql.py:203），目录读面 `/enterprise/catalog/*`；但无列画像/采样统计（auto-ontology 式 data profiling 仍无）。对方：实体必须绑已同步表（ontology.go:131-134），同步体系强大，但 schema 目录/列画像不是本体域能力，列级信息在 mappings.bind 里逐列声明 |
| B2 LLM 起草/建议 | 4 | **5** | 本仓：schema_suggester 确定性 humanize 基线必得+LLM 精化失败回退不吞（schema_suggester.py:331-370）+关系候选=声明外键 0.6+命名规约 0.4+join 探针证实升 0.75（:94-129）+复用 relation_candidates 审批（不建第二审批面）；但无「端到端起草整个本体」的多轮 agent。对方：**全场最强单项**——本体 agent 多轮 turn 状态机（done/needs_input/budget_exhausted/stale_draft，generator.go:330-366），问题支持自由/单选/多选/blocking（agentquestion.go:34-77），7 天无答按推荐值自动作答（config.go:906-915），幂等 request_id+预算 Limits+契约版本启动比对 |
| B3 人工编辑与协作 | **5** | 4 | 本仓：Ontology Studio 八分区+REST 84 路由+pipeline 整批原子（中途失败逆序回滚，pipeline.py:225-294）+dry-run 唯一实现（:66-117）；人工从零构建、修订、审批全链自足。对方：以「审 agent 草稿」为中心——revise item 级干跑修订 1–100 条（revise.go:44-100）、review 队列、compare 面板；人工从零手写本体的面弱（且手写格式永不加载） |

### C. 映射与血缘（Neurova 8 / 参照系Y 10）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| C1 本体↔数据源绑定 | 3 | **5** | 本仓：enterprise_source_configs R2RML 风格人工映射（schema_mapping.py:66）+编译期强制 predicate/object 已登记（:109）+schema_catalog 目录 term_id 链接；映射语言朴素（列→术语直配）。对方：mappings.toml 表达力强——`bind.alias` 带 type/key{prop,transform=[upper,collapse_ws]}/lookup{mapping,on} 跨映射查找/missing=create\|report/parse.datetime{format,tz}（mock/fixtures/agent-bundle.json），extractions 按文档集路由（routes.go:28-62），未被路由命中的文档集不入图（graph.go:487-490） |
| C2 值级 provenance 与冲突 | **5** | **5** | 本仓：confidence/evidence_state/assertions/supersedes 链/双时态 valid_from·until（knowledge_facts.py:59-88）+推导账本溯源+PROV-O 导出。对方：ClaimKey(sha256)+ClaimSpan(文档字节区间)+StatementHash（foundry_review_decisions.go:113-119）+S3 快照路径血缘+Ask citations（实体/属性/引文三型，ontologyagent/ask.go:398-445）+值冲突等人审。**双满分**：本仓胜在事实级时效与推导链，对方胜在字节级文档锚定与引用呈现 |

### D. 版本化与演化（Neurova 9 / 参照系Y 9）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| D1 版本管理 | 4 | **5** | 本仓：semver 三件套（semver.py:14-40）+change_log 只追加（change_log.py:1-6）+基线 diff terms/rules 分列 added/removed/changed（pipeline.py:296-353，跨租户拒 :316-319）。对方：OntologyVersion 不可变+每本体递增+FOR UPDATE 锁分配（ontology_versions.go:44-107）+CAS 原子切换并在同事务修剪决策（:232-248）+bundle parent+impact 四态标注（needs_remap/needs_reextraction/needs_rule_build/breaking，turn_request.json:396-420）；compare 仅同版本两 load 对比是边界 |
| D2 回滚与迁移 | **5** | 4 | 本仓：rollback 逐字恢复 terms/rules/shapes 三层+impactOf 影响判据（被引用不删进审计）+恢复后 ensureAutoRules+fireAll 重推+受影响旧推导经账本精确撤销（pipeline.py:355-470）。对方：切回旧版本即回滚（api/ontology.go:218-246 注释 "moving back is how a rollback works"）+决策修剪+多版本共存一库按 load 隔离；但图数据随 load 重建，无「恢复后重推规则」语义 |

### E. 治理与准入（Neurova 9 / 参照系Y 9）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| E1 写入口收口 | **5** | 4 | 本仓：admission 七段编排唯一咽喉（admission.py:15-24、:293-428）——匿名拒、逐字可核闸（:249-267）、本体校验闸（:383-387）、推导/函数结论同咽喉（rule_engine.py:859-894）、批量 SAVEPOINT 隔离（:430-467）。对方：加载门强——LoadRefusal 四条件（generator.go:160-188）、手写格式永不加载、契约版本 4.26.0 启动比对（:231-240）；但「写入咽喉」语义不同：事实写入经 graphproxy 临时 token 到引擎，本体本身无逐条写闸 |
| E2 审批与人审闭环 | 4 | **5** | 本仓：relation_candidates 审批流（approve 回填 promoted_term_id，relation_candidates.py:101-134）+pipeline dry-run 整批闸+决策账本；但人工审阅粒度是「候选/整批」。对方：**更深**——held claim 五类决策（resolve/prop/release/reject/withdraw）+证据三元组绑定+Fits 校验（类型/属性/键/值仍合规才下发，foundry_review_decisions.go:236-254）+键变更 stale 重审（decisions.go:265-271）+resolve 派生 alias+切版本自动修剪（ontology_versions.go:232-248）+Check 三臂上线门禁（agent.proto:215-244） |

### F. 推理与解释（Neurova 9 / 参照系Y 7）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| F1 推理能力 | **4** | 3 | 本仓：分层前向链 semi-naive/rete 双策略+等价性测试（rule_engine.py:524-582）+fireFor 增量点燃（:555-565）+分层否定+CTE 传递闭包+溯因 explainGoal（abduction.py:46-166）+受限函数聚合（function_eval.py）；自觉边界（≤2 原子、无 OWL DL）。对方：Datalog 正程序规则+约束+链接公理（implies/chain/symmetric/transitive）；无否定、无溯因、无函数层；引擎在 sidecar 黑盒，仓库内无法核验其求值实现 |
| F2 可解释性 | **5** | 4 | 本仓：derivation_ledger 精确撤销三入口+折回语义（derivation_ledger.py:213-272、rule_engine.py:896-908）+decision_ledger 因果/判例+abduction 解释树+accountability 五账聚合。对方：read explain（为什么成立，read.go:163-206）+violations 违规页+Ask 逐条查询与引用+Assess 贡献度+audit findings；有解释与审计，但无推导账本级「沿边逐层精确撤销」 |

### G. 消费与 grounding（Neurova 12 / 参照系Y 13）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| G1 查询面 | 4 | **5** | 本仓：SPARQL 只读 SELECT/ASK（写形显式拒，sparql_query.py:43-75）+ontology_query MCP 双时态透传（mcp_ontology_server.py:139）+graph_search/community_search+九格式图导出可供外部图工具；短板：SPARQL 每查询全量重投影 serializeAll（sparql_query.py:59-63），大库有性能边界；无内置图可视化 UI。对方：read 七式（entity/pattern/explain/violations/evidence/query/view）+类型化查询（start+≤8 步+≤20 过滤+聚合，read_request.json）+Explorer 自研 Canvas 力导向图浏览器（GraphCanvas.tsx+d3-force）+compare 并排对比；预算超限绝不返回部分答案（read.go:140-161） |
| G2 问答与问数 | **4** | **4** | 本仓：answerability 实体覆盖预检（answerability.py:106-180）+nl2sql（目录 grounding+BFS join 路径+只读硬闸+一轮修复+诚实拒答，enterprise/nl2sql.py，`NEUROVA_NL2SQL_ENABLED` 默认关）+检索注入三路（chat_pipeline.py:323-370）。对方：Ask 类型化查询读图+图表+每答带 queries[] 与 citations（ask.go:40-105）+Analyst 前端；但问业务库的 NL2SQL 它不做（问的是图）。**平手**：方向不同（问图 vs 问库），完成度同档 |
| G3 agent 工具集成 | **4** | **4** | 本仓：MCP 22 工具 curated 名册+when_to_use 指引+allowlist 守卫双向防漂移（mcp_surface.py:23-68）+skills/neurova-ontology-query 技能包；内置工具面仍无本体工具（reference_n 缺口未变）。对方：MCP 端点+Assistant 对话 agent（agent-host 借外部 CLI）+HTTP Ask 契约+read 服务；工具面比本仓粗（本体操作未拆细粒度 MCP 工具） |

### H. 互操作与工程（Neurova 15 / 参照系Y 9）

| 子项 | Neurova | Y | 证据与理由 |
|---|---|---|---|
| H1 标准格式 | **5** | 1 | 本仓：九格式确定性导出（Turtle 自解析往返无损 turtle.py:151-348/JSON-LD/OWL2RL/SHACL/PROV-O/GraphML/GEXF/Cypher/CSV，export/ 五文件）+Ossie YAML 进出（导入缺省 dry-run，ossie.py:116-190）+RDF/XML inert 导入（XXE 防护，rdf_import.py:57-104）。对方：全仓 grep 无 OWL/RDF/SPARQL/SHACL，唯一交换格式是私有 toml/JSON（深读 §8.1） |
| H2 测试与守卫 | **5** | 4 | 本仓：81 个本体直接相关测试文件（69 单测含金样 golden/、semi-naive 等价性、租户隔离、撤销、导出金样 + 8 个 API 端点测试）+CQ 符号探针自动翻转。对方：Go 测试 1,500 函数（全后端）、contracttest+testdata 回放、store 近半行数是测试；但本体核心语义（TOML 编译/Datalog 求值/消解）在 sidecar 黑盒，仓库内测不到 |
| H3 可观测 | **5** | 4 | 本仓：cq_matrix 25 条 CQ 符号探针自动判定 implemented/partial/planned（cq_matrix.py:300-445）+readiness 双判据（readiness.py:20-69）+quality 结构指标（OOPS 子集）+simulation 克隆世界推演+accountability 五账。对方：Prometheus 指标遍布+audit（数据驱动缺口）/assess（贡献度）/probe（模型体检）三件套——**assess/audit 是本仓没有的独特面**，但无 CQ 级追溯矩阵与质量度量 |

---

## 4. 逐维详析（形态差异与机制对照）

**A 建模表达力（14 vs 8）**：差距最大的一维。参照系Y 的本体本质是「图 schema 描述」——扁平类型+带公理的二值链接+六种标量属性，足以支撑「把表和文档变成可查询图」，但表达不了层级分类、多语言、单位量纲、精确基数、属性约束。本仓是「治理型知识本体」：术语表自带关系代数特征（逆/对称/传递/函数性/不相交）+SHACL 形状+限定符 schema+双时态事实，且单位量纲（quantity.py 七维）、上层本体（upper_lite）、外部本体映射（external_iris）齐备。这一维本仓胜在「本体作为知识模型」的纵深。

**B 获取与起草（14 vs 12）**：对方的最强单项 B2=5——本体 agent 以多轮对话起草本体（给数据与目标→agent 出草稿→人答 blocking 问题→出 bundle），配预算、幂等、7 天自动默认、事件流；本仓是「建议器+人工构建+抽取候选」三链，自动化程度低一档。但本仓 B3=5：人工构建面（Studio+84 路由+整批原子 pipeline）完全自足，而对方人工从零手写的路径事实上不可用（手写格式永不加载，ontology 是「agent 起草、人审修订」单行道）。

**C 映射与血缘（8 vs 10）**：对方胜在映射语言与血缘锚定。mappings.toml 的 transform/lookup/missing/parse 是一套小型数据集成 DSL；本仓映射是 R2RML 风格的人工直配。血缘上双方双满分但侧重不同：本仓是事实级（置信度/双时态/推导链/PROV-O），对方是 claim 级（sha256+文档字节区间+引用呈现）——对方的「每个值可回溯到表行或文档引文」是其产品核心卖点，工程上更贴消费端。

**D 版本化（9 vs 9）**：哲学不同。对方是「不可变版本对象+CAS 切换+决策修剪+impact 预标注」，工程上更严密；本仓是「semver+基线快照+回滚后重推规则+精确撤销推导」，语义上更完整（回滚不是换指针，是把世界恢复并重算）。互补性大于优劣。

**E 治理准入（9 vs 9）**：本仓 E1 强在「一切写入过唯一咽喉」（含推导结论），对方强在「加载门+契约版本比对」；本仓 E2 是候选/整批粒度审批，对方是 claim 级五类决策+证据哈希绑定+三臂上线门禁（Check），人审颗粒度对方更细。

**F 推理解释（9 vs 7）**：本仓有分层否定、传递闭包、溯因解释树、函数聚合、精确撤销；对方是正 Datalog+公理，无否定无溯因，且引擎黑盒无法核验。这是「治理型本体」对「流水线本体」的代差项。

**G 消费 grounding（12 vs 13）**：对方略胜。read 七式+类型化图查询+Explorer 可视化+compare 面板构成完整「图消费」体验；本仓查询面齐（SPARQL/双时态/社区图）但无可视化 UI、SPARQL 有全量重投影性能边界。G2 平手：对方「问图带引用」与本仓「问库带 SQL」方向不同、完成度同档（本仓 nl2sql 默认关是扣分点）。

**H 互操作工程（15 vs 9）**：差距第二大的一维。九格式+Ossie+RDF 导入 vs 仅私有格式；81 个测试文件+金样+CQ 探针 vs 强测试但本体核心黑盒；cq_matrix/readiness/quality/simulation/accountability 五个可观测面 vs 指标+审计三件套。

---

## 5. 对本仓的借鉴清单（按性价比分级；均为候选，待拍板）

### P1-1 Check 式「三臂对照门禁」嫁接进本体 pipeline

- **对方做法**：草稿上线前跑三臂抽取对照——基线重放（$0，缓存）/ 草稿只问改动 / 基线全量重问（噪声对照），产出 shifts/exempt_conflicts/gate pass|fail（agent.proto:215-244、check_result.json）。
- **本仓现状**：pipeline dry-run 是单臂静态校验（findings/violations/verdict），不做「改了之后数据会怎样」的对照。
- **建议**：schema_suggester/关系候选批准前，可对「新旧候选集」做数据侧对照（新关系成立时多少既有事实受影响、多少抽取结论会变）。落点：`pipeline.py` dryRun、`schema_suggester.py`。默认关，灰度开。

### P1-2 Audit 式「数据驱动本体缺口审计」

- **对方做法**：对一页文档零模型调用挖五类信号——路由未覆盖关系（unmatched）、消解失败名字（unresolved）、实体冲突（clash）、映射行错误（row_errors）、源字段漂移（source_drift），每条带跨版本稳定 fingerprint 与可选 Proposal（audit.go:23-120）。
- **本仓现状**：quality.py 是**结构**审计（孤儿类/缺 label/父链环），没有「数据 vs 本体」的覆盖缺口审计；schema_catalog 有目录但无 drift 检测。
- **建议**：给企业源目录加「源 schema 漂移检测 + 术语覆盖缺口报告」（列类型变了/表消失了/高频列无术语映射），产物进建议器审批流。落点：`quality.py`/`schema_catalog.py`/`schema_suggester.py`。这是 P1-1/P1-2 落地后的自然下一步，成本低于对方（本仓已有目录与建议面）。

### P1-3 Assess 式「本体贡献度评估」

- **对方做法**：一次问答运行后，评估本体对答案的贡献度（essential/helpful/marginal/unused/misleading）+逐条 claims+gaps+suggestions（assess.go:29-142）。
- **本仓现状**：cq_matrix 评「能力实现度」，answerability 评「入口覆盖」，但没有「这次回答里本体帮了多少/误导了多少」的回评面。
- **建议**：在问数（nl2sql）与图谱问答链路挂事后评估探针，把「本体缺口导致答错」的案例回灌 suggestion/审计面。落点：`nl2sql.py`/`answerability.py`。默认关。

### P2-1 mappings 式映射增强

- **对方做法**：bind.alias 带 transform（upper/collapse_ws）/lookup（跨映射查找）/missing（create|report）/parse.datetime{format,tz}。
- **本仓现状**：schema_mapping.py 是列→术语直配，无变换/查找/缺省策略。
- **建议**：给企业源映射补「值变换 + 缺省策略」两件（lookup 跨源查找可后置），编译期仍强制术语登记。落点：`schema_mapping.py`。映射面改动需回归企业源域测试。

### P2-2 版本 impact 四态预标注

- **对方做法**：bundle 每 item 带 Effect：needs_remap/needs_reextraction/needs_rule_build/breaking（turn_request.json:396-420）。
- **本仓现状**：semver 判 major/minor/patch，impactOf 报影响面（事实数/主体类型/子术语），但无「这条变更会要求重映射/重抽取/重建规则」的预判标注。
- **建议**：在 pipeline diff 结果上补 impact 分类（纯展示+审批辅助，不改判定链）。落点：`pipeline.py` diff、`semver.py`。

### P2-3 Probe 式「模型能力体检」并入 readiness

- **对方做法**：按 draft/ask/extract/verify 四角色用真实工具与 schema 试调用，失败给具体失败模式（tools_rejected/schema_rejected/context_too_small/unpriced，probe.go:61-193）。
- **本仓现状**：readiness 是数据就绪（术语/事实/目录/源），不探「模型能不能干本体活」。
- **建议**：readiness 增第三判据 model_ready（可选探针，一次廉价试调用），失败给具体原因。落点：`readiness.py`。默认关（避免每次探针花钱）。

### P3-1 血缘（provenance）专项借鉴：决策绑定证据、锚定到字节、引用强制化

> 应用户要求对血缘域单独展开。总判：对方强在「锚定到字节、绑定到决策、呈现到引用」；本仓强在「推导链与时效治理」（推导账本/双时态/PROV-O），对方完全没有规则级推导账本。借鉴方向是补「文档/数据侧证据锚定」，不是重构本仓体系。

**已同构、无需学**（防止重复建设）：推导溯源——本仓 `derivation_edges`+`rule_fires` 两本账、沿边逐层精确撤销（derivation_ledger.py:213-272），对方无；时效治理——双时态 valid_from/until + supersedes 链（knowledge_facts.py:59-88），对方无时态字段；标准化导出——PROV-O（export/prov.py），对方无标准格式；入口诚实闸——逐字可核（admission.py:249-267）。

**差距一：审批决策绑定「证据内容哈希」（StatementHash 模式）——价值最高。** 对方人审五类决策（resolve/prop/release/reject/withdraw）每条必带 `ClaimKey(sha256) + ClaimSpan + StatementHash` 三元组（foundry_review_decisions.go:113-119），StatementHash 绑定「**批准人当时读到的原文内容**」；键变更致决策失配时标记 stale 重审，而非静默丢弃（decisions.go:265-271）。本仓 `relation_candidates`/`schema_suggestions` 的 approve 只回填 promoted_term_id（relation_candidates.py:101-134），不绑定「审批时看到的证据内容」——若候选背后的证据文本后来变了，批准仍然生效。落点与影响面：候选表加 `evidence_hash` 列 + 审批入口校验，涉及 `relation_candidates.py`、`schema_suggester.py` 审批端点，影响面小；与逐字可核闸同一哲学，堵「**批准时看的 ≠ 生效时用的**」这个真实治理洞。此为增强非补缺。

**差距二：事实证据的位置锚定（ClaimSpan 模式）。** 对方每条抽取结论锚定到文档的 `section + 字节区间`，引用时可回跳高亮原文。本仓 `assertions_json` 记录了证据断言、admission 做了「存在性」校验，但没有结构化的「在哪个文档哪个区间」——前端 FactExplorer 展示证据时无法定位回原文。落点与影响面：assertions 元数据增可选 `source_span` 字段（不破坏现有 schema），知识前端可做证据回跳；渐进可做。

**差距三：答案逐论断强制引用（citation marker→target）。** 对方 Ask 解码强制「每个引用必须有 marker 与证据、不得重复」（ask.go:560-566），引用恰好三型——实体/属性/文档引文（section+字节区间），Analyst 页面每条结论旁边就是可点的来源。本仓有 `annotateDerivations` 推导标注与 derivation_citation 读面，但「答案句级引用强制落到源文档位置」未见同等硬约束。落点与影响面：MCP `ontology_query` / 知识问答链路的答案组装处，复用现有 assertions 字段输出 citation 列表；治理上可借鉴其「解码期强制校验，缺失即拒」的姿态。

**远期两项（成本高，暂列不动；原 P3-2 并入此处）**：① **行级数据血缘**——对方 S3 快照 key 自带 `ws/connector/table/row` 路径、批次可回放；本仓企业源事实可补「来源行定位」元数据。② **事实级快照对比**——对方 compare 按证据类型逐类 diff 两次装载；本仓基线 diff 目前是术语/规则级，事实级对比可等同步批次有真实规模后再做（当前回滚+重推已闭环）。另：对方「多版本图数据共存一库+按 load 标记隔离」属数据流水线形态产物，不照搬存储形态。

**一句话**：学它的「证据可定位、决策可绑定、引用可强制」，不必学它的「快照存储形态」——本仓 SQLite 单库+账本体系已能以更轻的方式达到同等工作效果。

**不建议照搬**：手写本体永不加载的单行道（本仓人工构建是正当路径）；闭源 sidecar 依赖（与本仓可选依赖惰性加载纪律相反）；compare 只支持同版本两 load 的限制；把本体治理简化为「证据计数+无新 block 违规」（本仓 admission 六维校验更严）。

---

## 6. 反向借鉴（本仓强项，参照系Y 可学）

简要列出：标准本体格式导出（九格式+Ossie）；SHACL 形状校验；分层否定推理与推导账本精确撤销；溯因解释；单位量纲；多语言标签；租户隔离全链复合主键；CQ 追溯矩阵与质量度量；双时态事实与超替链。

---

## 7. 局限性

- 参照系Y 的本体引擎（TOML 编译/Datalog 求值/实体消解）在**闭源 sidecar** 内，仓库仅有 JSON 契约；其推理/消解的实际能力按契约与 Go 侧驱动代码推断，F1/A3 等子项可能有 ±1 分观察误差。
- 本评分为静态代码级对照，未实机运行对方栈；「实证闭环」维度按仓内可核验事实评分。
- 评分卡为本仓评测序列首次使用的本体专项卡（8 维 20 子项），锚点已写明但无历史轮次可比；后续若复评其他本体项目应沿用同卡。
- 对方迭代极快（六周 2,154 星），读数仅代表克隆时点（2026-11-19）。

---

## 8. 实施回执（2026-11-19，§5 借鉴清单 P1–P3 全部落地）

按用户指令「采纳建议开始实施 P1 到 P3」执行，三批提交、每批先红后绿：

| 批 | 内容 | 提交 |
|---|---|---|
| 批 1（P2×3） | P2-1 映射增强：`VALUE_TRANSFORMS` 闭集（upper/lower/trim/collapse_ws，仅 column/template 派生值，常量对象编译期拒）+ `missing` 三策略（keep 缺省/skip 整行跳过并留名/report 带 objectMissing 标记），摄取链对 skip 行隔离；P2-2 `impactOfDiff` 四态影响预标注（breaking/needs_remap/needs_reextraction/needs_rule_build，纯函数）；P2-3 readiness 增 `model_ready` 可选探针（回调缺省 disabled 零网络，端点 env `NEUROVA_ONTOLOGY_MODEL_PROBE` 默认关） | `dab74d955` |
| 批 2（P1×3） | P1-1 `checkGate` 三臂对照门禁（臂1 基线 dry-run / 臂2 克隆副本应用术语与规则假设后对照、候选经同一咽喉注入并到引擎不动点 / 臂3 基线重放；「基线 pass、草稿 violation」倒退即 fail，纯新增推导不拦，shifts 随报；只读零生产写、副本即删）；P1-2 `auditOntologyCoverage` 五类信号（uncovered/broken_reference/clash/stale/ambiguity，fingerprint 跨轮稳定+建议动作）；P1-3 nl2sql 答案随附确定性 `assessment`（essential/helpful/marginal；拒答 not_assessed+gaps 按拒因归类）。端点 `POST /ontology/check-gate`、`GET /ontology/audit`（均 admin） | `11c050a63` |
| 批 3（P3-1 血缘×3） | a) 审批决策绑定证据哈希（v54：候选/建议两审批面加 evidence_hash=生成时 sha256，人工审批必须回带，不匹配 409；存量空哈希行兼容放行；REST approve/reject 加 evidence_hash 参数）；b) 断言位置锚定（v55：knowledge_assertions.source_span_json，lineage 透传、溯源读面透出）；c) nl2sql 可答结果强制 citations（catalog_table/term/join_path/approved_pattern 四型，SQL 引用表全在目录白名单内故恒非空；拒答 citations 恒空） | `21a7ff7de` |

**测试证据**：新增 6 个测试文件先红后绿（映射/impact 28 例、门禁/审计/评估 14 例、血缘 19 例）；既有用例按新契约跟随（审批补哈希、路由清单补两路由、v25 旧库夹具按真实状态补 v3 断言表、迁移终态断言 53→55、manual live-verify 脚本同步）。回归：knowledge/ontology 全目录 547 passed；knowledge 全域 2,010 passed；tests/unit/api 3,290 passed。A/B 定责（基线 worktree `0dacae4f0` vs 当前）：api 域失败集合 18→19，差额 1 条系并行 mobile/relay 批（`2ecccc2a1` 等）新增未挂门路由所致，与本批无关；其余 18 条逐条相同=预存。

**live-verify（真后端 9761，`start_server.py` 起动，health OK）**：`GET /ontology/readiness` → knowledge_ready=true、model_ready=null(disabled)；`GET /ontology/audit` → 200 findings 结构完整；`POST /ontology/check-gate`（空候选）→ gate=pass 三臂齐整；`POST /ontology/relation-candidates/{unknown}/approve` → 404（路由通、门在、零写入）。

**遗留清偿（2026-11-19，`6ffa82f7b`）**：上述三项遗留已处理——① api 域 19 条预存失败全部清偿（枚举预言机判定器认 admin 门、url_guard DNS mock、webhooks URL 合规化、console_split/authSurface 重生成、evolve 计划镜像按实测定标 24/60/64/32、capability 复合键读取、connection 断言回归错误形态初心、pairingQr host 钉入站回落、route_mount 通配二次判定）；清偿后 api 全量 3,308 passed / 1 failed，仅剩一条为跑测时点仓根在途散件的瞬态污染（单跑通过、现仓根已净，非代码缺陷）。② sourceSpan 生产写入方已接线（企业源摄取断言带行级 span，行级血缘最小形态落地）。③ 远期两项经复评维持缓办：事实级快照对比的主要用例已由 checkGate 的 shifts 覆盖，行级血缘已由 sourceSpan.row 落地；完整事实面基线快照待同步批次有真实规模后再评估。
