# reference_ae vs Neurova：本体（Ontology）域专项对照评测（2026-11-22）

> **性质**：外部参照项目代码级对照评测（研究参考，仅作背景，不可作事实源）。
> **参照项目**：代号 `reference_ae`——semantica-agi/semantica（官网 getsemantica.ai，文档 docs.getsemantica.ai）。MIT 许可、Python ≥3.11.5、创建于 2025-06-25、14,719 星 / 1,749 forks（GitHub API 2026-11-22 现场读数）、主分支当日仍有推送。定位是「图原生的语境与知识基础设施」：数据摄取 → 本体（OWL/SHACL/SKOS）→ 知识图谱 → 确定性推理 → PROV-O 溯源 → 决策智能，主张「图构建/推理/溯源不依赖 LLM」的确定性内核，面向高风险合规行业，商业模式为开源获客 + 托管云/企业前向部署。
> **本文纪律**：正文一律以「参照系 ae」「对方」指代；所涉第三方库（rdflib、pySHACL 等）按功能依赖如实登记。文中 `file:line` 分两类：`semantica/...` 为**对方仓库内路径**（main 分支 tarball 快照，v0.8.0-dev，最新 tag 0.7.0=2026-09-22）；`neurova/...` 为本仓路径（2026-11-22 现场读数）。
> **口径**：本文是**本体域专项**评测，评测轴延续 reference_n/reference_y 建立的对照框架（模型/获取/存储/推理/治理/版本/消费/工程），本次将「存储查询与规模」独立成维以匹配对方的基础设施形态。本仓侧事实以当前代码为准（`neurova/knowledge/ontology/` 45 个 .py 共 9,604 行）。
> **取证方式**：对方主包 1,019 个 .py（约 140,930 行）+ 测试 541 文件（190,519 行）做结构盘点后，三个并行深读分别覆盖「推理/溯源/变更/冲突/上下文/KG/存储」「产品面/生态/文档站」「（本仓）本体全模块」，主控另对 ontology 生成/校验/质量门/词表、MCP 工具表、Explorer 鉴权等承重点做了一手精读与抽查复核（抽查点全部命中，见 §7）。

---

## 0. 结论摘要

**总分：参照系 ae 89/100 vs Neurova 83/100，对方领先 6 分**（本体专项评分卡，8 维 20 子项，每子项 0–5）。

> **2026-11-23 复评（§10）**：十三卡+连接器扩容+前端增强全落地后重测——**Neurova 92 vs 参照系 ae 89，本仓反超 3 分**（区间 90–93；逐子项证据见 §10）。下文首评表格与结论保留为 2026-11-22 快照，不改动。

| 维 | 子项数 | Neurova | 参照系ae | 判 |
|---|---|---|---|---|
| A 本体建模表达力 | 3 | **14** | 13 | 本仓微胜：多语言/领域包/公理面更全；对方胜在 SHACL 运行时校验 |
| B 本体获取与起草 | 3 | **13** | 12 | 本仓微胜：审批链+原子管线；对方胜在数据源摄取广度 |
| C 存储查询与规模 | 2 | 6 | **10** | 对方大胜：RDF 五后端+LPG 四后端+图分析+GraphRAG vs 单一 SQLite |
| D 推理与一致性 | 2 | 8 | **9** | 接近：对方广（Rete/反向链/定理证明），本仓深（分层否定/函数引擎/咽喉治理） |
| E 溯源治理与冲突 | 2 | 9 | **10** | 接近：双方 PROV-O/审计账双满分；对方冲突消解体系更宽 |
| F 版本化与演化 | 2 | **9** | 6 | 本仓大胜：写前门禁+三臂对照+回滚重推 vs 事后严重级分类+两套并行 API |
| G 消费与集成 | 3 | 11 | **14** | 对方胜：框架适配器+Explorer 十工作区+双 MCP；本仓胜在治理（鉴权/allowlist） |
| H 工程质量与生态 | 3 | 13 | **15** | 对方微胜：连接器矩阵+教程体系+部署矩阵+供应链安全；本仓测试纪律更严 |
| **合计** | 20 | **83** | **89** | **参照系 ae 领先 6** |

一句话结论：两者是**「专用知识基础设施」与「平台内嵌治理本体栈」**的形态差，不是同位竞品。参照系 ae 把「数据→图→推理→溯源→可视化→生态」的全链路基础设施做到很高完成度（多后端存储、图分析、Explorer 工作台、十余种连接器、40 本教程、六云部署），并在本体系最薄弱的**存储查询规模**与**消费集成**两维全面领先；但其治理面明显松（MCP 无鉴权、双 MCP 实现并存且工具数漂移、版本表内存态、OWL 一致性校验是占位桩、宣称与实现存在落差）。本仓把「治理纵深」做得很厚——准入咽喉单写点、append-only 审计账、写前破坏性变更门禁、三臂对照、推导精确撤销、78 个专测文件——但在存储后端、查询规模、可视化与生态连接器上是明确短板。**最值得吸收的五件事：运行时 SHACL 校验档、确定性质量门阈值化、带失效的查询缓存、完整 Rete 求值档、Allen 区间代数引擎**（详见 §5）。

---

## 1. 对象概况

| 项 | 参照系 ae | 本仓（对照基线） |
|---|---|---|
| 形态定位 | 独立知识基础设施库/平台：摄取→本体→图→推理→溯源→决策→可视化→MCP，pip 安装即用 | Agent 平台内嵌本体域：术语/规则/形状/事实四层，供 agent 知识治理与推理 |
| 规模 | 主包 1,019 个 .py 约 140,930 行；测试 541 文件 190,519 行；28 个子模块；11 条 CI 工作流 | `neurova/knowledge/ontology/` 45 个 .py 共 9,604 行；专测 78 文件 539+ 测试函数 |
| 本体模型 | 本体=字典结构（classes/properties/individuals/axioms + namespace/version），面向 OWL/RDF 序列化 | `ontology_terms` 单表三类术语（概念/关系/数据属性）+shapes+rules+state_machines+functions，全部「类型即数据」 |
| 起草方式 | 六阶段确定性推断管线（实体/关系→概念→OWL 类型→层级→TTL→校验）+LLM 单轮结构化生成+bootstrap 草稿人工批准 | schema_suggester 确定性基线+LLM 精化+join 探针+关系候选审批；管理面人工构建；文档 LLM 抽取 |
| 规则/约束 | 前向/反向链+Rete+半朴素 Datalog+动作体系；SHACL 由本体自动派生并经 pySHACL 运行时校验 | Datalog 二原子片段前向链（relay/合取/inverse/分层否定）+受限 AST 函数引擎+SHACL 风格 JSON DSL 五约束 |
| 版本化 | 版本 IRI+字段级 diff+严重级分类（BREAKING/POTENTIALLY_BREAKING/NON_BREAKING）+快照存储/恢复/剪枝 | semver+四态影响预标注+基线快照+逐字回滚+重推+三臂对照门禁 |
| 存储 | RDF 三元组库五后端（四服务型+一嵌入式）+LPG 图库四后端（含云 IAM 认证）+向量库 extras | SQLite 单后端（WAL+RLock+迁移注册表），全链 `(tenant_id,*)` 复合主键 |
| 溯源 | W3C PROV-O qualified 全套+哈希链+墓碑+bundle+跨域桥接公理 | 推导账本+变更账（append-only）+决策台账（因果/判例）+五账聚合追责+PROV-O 导出 |
| 消费 | Python API+5 个 CLI+MCP 双实现（16/22 工具）+Explorer 本地 Web（10 工作区）+四家多代理框架适配器+九生态 IDE 插件包 | MCP 22 curated 工具（allowlist+双鉴权 fail-closed）+REST 84 路由+检索注入三路+Studio 前端 |
| 生态 | 十余种数据源连接器、四家框架适配器、40 本 cookbook、97 篇仓内文档、Docker/Helm/K8s/六云部署 | 企业源连接器（SQL 五驱动）、九格式导出、Ossie YAML 互操作、领域包（GB/T 48000.3 底本 102 术语） |

---

## 2. 评分方法

- **评分卡**：本体专项 8 维 20 子项，每子项 0–5 分，满分 100。维度取自本体工程核心关注点，与 reference_n/reference_y 的对照轴同构；「存储查询与规模」独立成维，因对方是基础设施形态，该维是其主要价值主张，不独立则评分会系统性失真。
- **锚点**：0=无实现；1=骨架/占位无消费方；2=部分实现仅靠自觉；3=机制化覆盖主链路有明显边界；4=机制化+测试守卫+治理完备；5=机制化+测试+治理+实证闭环。
- **形态校准**：参照系 ae 的本体服务于「企业数据→图→合规决策」基础设施，本仓的本体服务于「agent 知识治理」。评分按**本体工程通用能力**同卡同锚点评，不因形态偏袒任何一方；形态差异在 §4 各维说明。
- **证据**：双方均为本轮代码级深读（对方 28 个子模块结构盘点+八域精读；本仓 ontology 45 文件全量），引证到 file:line；星数/测试数/工具数等承重数字经 GitHub API、`wc -l`、工具表逐项现场复核。

---

## 3. 逐子项评分表（20 项全表）

### A. 本体建模表达力（Neurova 14 / 参照系ae 13）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| A1 概念与层次与词表 | **5** | 4 | 本仓：三类术语单表+父链环登记即拒（term_registry.py:227-415、:452-468）、多语言 label/altLabel BCP47、disjoint/deprecated/replaced_by、模块不可互翻、upper_lite 七类上层本体（upper_lite.py:24-66）、领域包 102 术语 SHA-256 锁定（domain_pack.py:55-69）。对方：层级构建含环检测+传递闭包、命名规范强制、命名空间管理、SKOS 词表 SPARQL 级 CRUD（engine.py:406-590）、N 元关联类（associative_class.py）、五域模板（domain_ontologies.py，模板级非维护映射）、bootstrap 草稿制（bootstrap_schema.py:14-22 草稿不自动生效）；但 label/comment 单语言、无弃用链 |
| A2 关系与属性约束 | **5** | 4 | 本仓：domain/range/rangeKinds+基数（函数属性）+inverse_of 登记处双向补齐（term_registry.py:408-414，抽查命中）+symmetric/transitive+qualifier_schema（N 元限定）+身份键+datatype 闭集（:33-39）。对方：domain/range/基数检测/required/enum（llm_generator.py:116-121 保留 required/cardinality/enum）+SHACL 生成三档质量位（engine.py:209-236 basic/standard/strict）+严重级；但对称/传递/互逆等属性公理的声明面未见，约束表达主要靠 SHACL 派生 |
| A3 标准形式化与公理 | 4 | **5** | 对方：OWL 生成 rdflib 四格式（owl_generator.py:95-127）、**SHACL 自动派生+pySHACL 运行时校验+违规自然语言解释**（engine.py:200-402、ontology_validator.py:148-273）、SKOS 词表管理、本体对齐（owl:sameAs/skos:matching 八谓词，engine.py:104-196）、PROV-O；扣分点：OWL 一致性/可满足性校验是占位桩（ontology_validator.py:340-354 `pass`、:371-382 恒真），docstring 宣称 HermiT/Pellet 未兑现。本仓：九格式导出（owl.py:42-127/shacl.py/prov.py/graph_exchange.py:64-144）+金样逐字节对拍+RDF/XML inert 导入（XXE 防护，rdf_import.py:57-104）；但运行时 SHACL 仅 JSON 子集五约束、`path_json` 存而未用（shapes.py:169-171），诚实声明不做 OWL DL（rule_engine.py:3-4） |

### B. 本体获取与起草（Neurova 13 / 参照系ae 12）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| B1 数据源 schema 摄取与映射 | 4 | **5** | 对方：摄取模块 41 文件，十余种数据源连接器（云数仓/SAP/Salesforce/Cassandra/BigQuery/Redshift/Dynamics365/Looker/Tableau/ServiceNow/Airflow/Git 等，pyproject extras 全清单）+`RelationalSchemaMapper` 行→实体/外键→类型化关系/连接表→纯关系+来源标记供冲突消解用（schema_mapper.py:83-373）+normalize 6.3k 行+dedup 4.6k 行，形成「库表→图」完整流水线。本仓：describeSchema 五驱动统一注册落目录+R2RML 风格人工映射+编译期强制 predicate/object 已登记+企业源同步体系；但无列画像/采样统计，映射语言朴素 |
| B2 LLM 起草/建议 | **4** | 3 | 本仓：schema_suggester 确定性 humanize 基线必得+LLM 精化失败回退不吞+关系候选=声明外键 0.6+命名规约 0.4+join 探针证实升 0.75+约束推荐器+偏好提取+缺口审计。对方：LLM 单轮结构化生成（llm_generator.py:27-76，prompt→JSON→归一）+六阶段确定性推断管线（ontology_generator.py，频率门+层级 DFS+传递闭包）+bootstrap_schema「草稿不自动生效、人工批准」——与本仓 relation_candidates 审批同构；但无多轮 agent 起草、无人机问答交互 |
| B3 人工编辑与协作 | **5** | 4 | 本仓：Ontology Studio 八分区+REST 84 路由（knowledge_ontology.py 共 2,112 行）+pipeline 整批原子（中途失败逆序回滚）+dry-run 唯一实现+审批链+审计账。对方：Explorer 的 Ontology 工作区（Monaco 编辑器+SHACL 生成/校验 UI，explorer/src/workspaces/）+草稿批准流+module_manager 导入解析（module_manager.py:86-206）；但无审批链/审计工作流/多人协作治理 |

### C. 存储查询与规模（Neurova 6 / 参照系ae 10）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| C1 存储后端与持久化 | 3 | **5** | 对方：RDF 三元组库五后端（四服务型+一嵌入式，triplet_store.py:44-49）+LPG 图库四后端（graph_store.py:577-615，含云托管图库的 SigV4 IAM 认证自动刷新 amazon_neptune.py:125-330）+向量库 extras 多种+溯源 SQLite/内存双存储（storage.py:191/:391）。本仓：SQLite 单后端（WAL+RLock+connection_pool+迁移注册表），租户复合主键贯彻；但无图库/向量库可插拔面，跨 agent 全局图查询不在承诺内 |
| C2 查询能力与规模工程 | 3 | **5** | 对方：SPARQL 查询引擎（校验/图子句注入/计划/缓存/统计，query_engine.py:74-112）+批量装载器（bulk_loader.py:57-360，进度回调+载入前校验）+图分析（中心性/社区/链路预测/路径）+GraphRAG 四模式检索（local/global/drift/hybrid）+检索结果信任分层（trust_tier：quarantine/bronze/silver/gold）；扣分：缓存无失效机制（sparql_reasoner.py:433-437 自述）。本仓：SPARQL 只读投影（仅 SELECT/ASK，200 行/10s 上限，每次全量重投影+重解析，sparql_query.py:19-75）+递归 CTE 传递闭包（行数上限显式报错，rule_engine.py:928-967）+semi-naive/rete 双策略等价性钉住（:74）+TFIDF 判例检索；无缓存、无图分析、无增量装载 |

### D. 推理与一致性（Neurova 8 / 参照系ae 9）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| D1 规则与符号推理 | 4 | 4 | 双方形态不同、各有所长。本仓：Datalog 二原子片段前向链（relay/合取/inverse）+**分层否定**（成环报错，rule_engine.py:153-267）+受限 AST 函数引擎（白名单无 eval，function_eval.py:35-43）+溯因解释树（abduction.py:48-170）+**推导结论强制过准入咽喉**（rule_engine.py:877-912，抽查命中「推理未接咽喉写入口即 RuleError」）+自动规则随声明生灭（:812-875）；边界：≤2 正原子、无聚合/算术入规则。对方：前向/反向链+生产规则动作体系（reasoner.py:226-321）+**完整 Rete 网络**（alpha/beta/token/terminal，rete_engine.py:360-708）+半朴素 Datalog（datalog_reasoner.py:242-339）+演绎定理证明+解释生成器+SPARQL is_a 物化；边界：字符串模式无类型/否定/聚合，归纳推理评分是常量桩（abductive_reasoner.py:263-267、:376-380），`_has_type` 占位恒真（sparql_reasoner.py:327-330） |
| D2 真值维护与时间推理 | 4 | **5** | 对方：**源支持真值维护会话**（不变式 `facts == closure(rules, supported)`，原子 apply+脏规则重匹配+检查点+差分测试，truth_maintenance.py:148-503）+双时相 TMS 适配器（temporal_truth_maintenance.py:45-168）+**Allen 区间代数 13 关系完整引擎**（kg/temporal_reasoning.py:43-341）+`state_at` 历史状态视图。本仓：推导账本**精确撤销**（前提撤销/规则删除/改版沿边撤销、深先浅后，derivation_ledger.py:217-278）+物化档 observe/enforce 读侧排除单源（:149-201）+双时态事实（valid_from/until/known_at）+Allen 四关系仅作词汇声明不推理（upper_lite.py:24-66「不得生成传递规则」） |

### E. 溯源治理与冲突（Neurova 9 / 参照系ae 10）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| E1 溯源与审计 | 5 | 5 | 双满分。本仓：变更账 append-only（change_log.py:1-5「能删就不是审计账」）+推导账本（前提粒度推导边+点火账）+决策台账（caused/influenced/precedent 无环硬校验+TFIDF 判例，decision_ledger.py:146-302）+五账聚合追责（accountability.py:25-51）+PROV-O 导出。对方：**PROV-O qualified 全套**（qualifiedAssociation/Generation/Derivation/Usage/Invalidation+hadRole+actedOnBehalfOf，manager.py:1294-1456）+**哈希链完整性**（sequence_id/previous_checksum+verify_chain 整行删除可检出，manager.py:104-109/:1506）+invalidation 墓碑+bundle 分区+跨域桥接公理（DOI+页码引文，bridge_axiom.py）+lineage 双向+revision_history+audit_log |
| E2 冲突检测与质量门 | 4 | **5** | 对方：五类冲突检测（值/类型/关系/时间/逻辑）+七种解决策略（投票/可信度加权/最新/首见/最高置信/人工/专家，conflict_resolver.py:102-111）+调查指南生成+源可信度跟踪+**确定性质量门**（阈值 min_coverage/max_errors+metrics，CI 友好，quality_gate.py:93-120）+本体评估器（覆盖度/粒度/缺口建议）；扣分：逻辑冲突规则硬编码小表（conflict_detector.py:1048-1053）、conflicts 测试仅 2 文件。本仓：六条内置校验+用户 shapes 三态严重级+**违规即在准入咽喉拒写**（admission.py:383-387）+缺口审计五信号（audit.py:42-133）+质量报告（OOPS!/OQuaRE 可计算子集）；扣分：consistency 指标恒 1.0 静态值（quality.py:61，抽查命中）、无冲突消解策略族 |

### F. 版本化与演化（Neurova 9 / 参照系ae 6）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| F1 版本/diff/迁移 | **4** | 3 | 本仓：semver 判定/比较/推进（semver.py:14-62）+diff→四态影响预标注（breaking/needs_remap/needs_reextraction/needs_rule_build，:65-122）+基线快照（terms/rules/shapes 全量）+逐字回滚+重推+精确撤销（pipeline.py:356-471）；边界：术语级版本历史缺、基线全量 JSON 线性成本。对方：版本 IRI+字段级 diff（classes/properties/individuals/axioms 增删改，ontology_version_manager.py:299-389）+快照存储（SQLite/内存）+tag+恢复（需确认）+剪枝（managers.py:253-480）；扣分：主版本表内存态进程重启即失（:97）、迁移仅改元数据三字段不做实例迁移（:405-431）、内存版与持久化版两套并行 API 概念重复 |
| F2 破坏性变更门禁与回滚 | **5** | 3 | 本仓：**写前门禁**——dry-run 整批拒绝零落盘（pipeline.py:188-201）+应用失败逆序回滚（:226-230）+三臂对照（baseline/draft/replay，副本库演假设，replay 漂移即 fail，:474-606）+审计账 append-only。对方：变更严重级分类（约束收紧=BREAKING、层次变化=POTENTIALLY_BREAKING，change_log.py:132-273）+影响报告+建议+恢复需确认（managers.py:480）；但属**事后分类**，无写前拦截、无对照臂、无重推语义 |

### G. 消费与集成（Neurova 11 / 参照系ae 14）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| G1 Agent/上下文集成 | 4 | **5** | 对方：AgentContext 门面（store/retrieve/forget/record_decision/因果链）+**四家多代理框架真适配器**（深度不一：全家桶/Retriever+VectorStore/工具三件套/函数工具+会话服务）+GraphRAG 四模式+信任分层+决策记录可挂评估器钩子。本仓：MCP 22 curated 工具（allowlist+when_to_use 行为指引+双鉴权 fail-closed，mcp_surface.py:23-68）+检索注入三路；Agent 侧零直接 import、全走 MCP/REST 序列化层——治理收益换调用开销（设计取舍） |
| G2 工具面（API/MCP/CLI） | 4 | 4 | 本仓：MCP 22 工具+REST 84 路由+双鉴权+curated 名册单源。对方：5 个 CLI 入口+MCP 双实现（自包含 16 工具+模块化 22 工具，均仅 stdio、**均无鉴权**）+Explorer REST 13 组+Python API 全面；扣分：双 MCP 并存工具集漂移（16 vs 22，第三方集成文档还写 15）、模块化版不入 wheel 分发受限 |
| G3 可视化与探索 | 3 | **5** | 对方：**Explorer 本地 Web 工作台**——FastAPI+React/Vite 前后端分离、10 个工作区（图/本体/决策/血缘/diff 合并/富化/导入导出/SPARQL/词表/管理）、sigma+graphology 图渲染、vis-timeline 时间线 scrubber、WebSocket 实时推送、API-Key fail-closed 鉴权（未配置即 503，dependencies.py:48-74，抽查命中）。本仓：Studio 管理面前端八分区+REST 读面；无图谱级交互探索/时间线/血缘视图 |

### H. 工程质量与生态（Neurova 13 / 参照系ae 15）

| 子项 | Neurova | ae | 证据与理由 |
|---|---|---|---|
| H1 测试与 CI/安全 | 5 | 5 | 双满分、路线不同。本仓：78 专测文件 539+ 函数、**真咽喉测试纪律**（「绕开咽喉的测试等于没测」）、金样逐字节对拍、差分/等价性测试、commit 期红绿证据门+protected_tests 收录门、租户隔离复合主键。对方：541 测试文件 19 万行、差分测试（TMS/时序/工件索引）、注入回归（SPARQL/Cypher）、issue 回归命名、11 条 CI 工作流（CodeQL/OpenSSF Scorecard/容器扫描/依赖哈希锁定/安装矩阵）+pre-commit |
| H2 文档/示例/部署 | 4 | **5** | 对方：仓内 97 篇 md+文档站全章节+**40 本 cookbook 教程**（26 入门+11 高级+3 集成）+7 个离线可跑示例+CI 模板+Docker 多阶段（依赖哈希锁定/非 root/健康检查）+Helm/K8s/六云部署矩阵+九生态 IDE 插件包。本仓：docs/ 编号分层+INDEX+架构文档 26 篇+API 参考；部署形态单一，本体域缺独立教程/示例集 |
| H3 生态连接器与互操作 | 4 | **5** | 对方：十余种数据源连接器 extras+四家框架适配器（含「写后用独立引擎复核」的独特互操作姿态，open_ontologies）+九生态 IDE 分发+五 RDF+四 LPG+多向量库。本仓：九格式导出（Turtle/JSON-LD/OWL2RL/SHACL/PROV-O/GraphML/GEXF/Cypher/CSV）+Ossie YAML 进出+RDF/XML inert 导入+企业源 SQL 五驱动；连接器广度与框架适配面窄于对方 |

---

## 4. 逐维详析（形态差异与机制对照）

### 4.1 建模：字典结构 vs 类型即数据（A 维）

对方本体是「字典结构 + rdflib 序列化」路线：classes/properties 是 Python dict，生成管线（六阶段）把实体/关系频率统计成概念与层级，再映射为 OWL 类型。优点是**从数据到本体的自动化程度高**、SKOS/SHACL/OWL 三件套齐且 SHACL 能真的跑运行时校验；缺点是字典结构无强约束，术语合法性靠约定与校验器。本仓是「类型即数据」路线：术语/规则/形状/状态机/函数/领域包全部是表行，登记处硬拒非法结构，公理（逆/对称/传递）在写入点收口成不变式（如 inverse_of 单边态在存储层不存在）。**本仓胜在模型治理与不变式，对方胜在标准格式运行时与自动生成**。

### 4.2 获取：连接器矩阵 vs 审批管线（B 维）

对方的摄取→映射→建图流水线是全仓最大资产之一：十余种连接器把库表/SaaS/文档吸进来，`RelationalSchemaMapper` 把行变成带来源标记的实体关系，normalize/dedup 两模块 1.1 万行做清洗与去重。本仓的获取面窄但治理深：每个本体变更走 dry-run→原子应用→审计→基线的流水线，关系候选要过证据哈希绑定的审批。**对方回答「数据怎么进来」，本仓回答「变更怎么被管住」**。

### 4.3 存储与查询：本体系最明确的差距（C 维，6 vs 10）

这是全场分差最大的维度。对方以注册表模式提供 RDF 五后端+LPG 四后端（含云 IAM 认证实现），查询引擎带计划/缓存/统计，外加图分析与 GraphRAG。本仓本体域锁定在单机 SQLite：SPARQL 每次查询都把全库重投影成 Turtle 再交 rdflib 解析执行（无缓存），200 行/10s 上限是诚实但保守的边界。需要说明：这是**形态决定的设计取舍**——本仓本体域服务单实例 agent 治理，SQLite+租户复合主键在小规模下足够且免运维；但「可插拔图存储门面」的缺位使本仓无法随数据规模横向扩展，是真实的架构短板而非纯形态差。

### 4.4 推理：广度 vs 深度（D 维，8 vs 9）

对方的推理模块是教科书式全家桶：前向/反向链、完整 Rete、半朴素 Datalog、演绎定理证明、解释生成、Allen 时间代数、真值维护会话——且 TMS 有差分测试护航，实现是真材实料；但归纳推理评分是常量、SPARQL 推理仅 is_a、规则语言无否定/聚合。本仓规则语言表达力保守（二原子片段），但有三个对方没有的点：**分层否定**、**受限 AST 函数引擎**（聚合/算术）、**推导结论强制过准入咽喉+精确撤销**（治理与可追责）。真值维护双方同构（对方会话式+检查点，本仓账本式+沿边撤销），时间推理对方明显更完整。

### 4.5 治理：双方哲学不同（E/F 维）

溯源上双方都是 PROV-O 级别：对方的差异化在 **qualified 全套+哈希链+墓碑+跨域桥接公理**（面向监管审计），本仓的差异化在**推导账本+决策台账+五账聚合**（面向 agent 行为追责）。冲突与质量上，对方有完整的「检测→七策略消解→调查指南」族 + 确定性质量门；本仓把校验嵌进准入咽喉（违规拒写），治理更硬但消解策略族缺失。版本演化是本仓明显强项：**写前门禁（dry-run 整批拒绝）+三臂对照+回滚重推** vs 对方的**事后严重级分类**；且对方版本管理存在内存版/持久化版两套并行 API、主版本表不持久化、迁移不做实例迁移三处实债。

### 4.6 消费与生态：平台化程度差（G/H 维）

对方的「库→工具→平台」三层产品化是本体系没有的形态：Explorer 十工作区可视化、双 MCP、框架适配器、IDE 插件分发、40 本教程、六云部署。本仓的消费面（MCP 22 工具+REST 84 路由）功能覆盖不弱，且在**鉴权/allowlist/审计**上比对方严格（对方 MCP 无鉴权、Explorer 靠单一静态 Key）；但可视化、教程、连接器、部署矩阵的广度差距是真实的。值得肯定对方的一点：Explorer 鉴权 fail-closed（未配置密钥即 503 拒服务，需显式开匿名），与本仓同姿态。

---

## 5. 对本仓的借鉴清单（按性价比分级；均为候选，待拍板）

> 纪律：每项须过修复教义——不新造平行体系（单一事实源）、先红后绿、live-verify。凡 reference_y 批已落地的（三臂门禁/缺口审计/贡献度评估/映射 transform/impact 预标注/证据哈希绑定/位置锚定/逐论断引用）不再重复列入。

### P1-1 运行时 SHACL 校验档（补 A3 最大缺口）
本仓 shapes 是 JSON DSL 五约束子集且 `path_json` 存而未用；对方证明「本体→SHACL 自动派生→pySHACL 运行时校验→违规自然语言解释」可低成本落地（engine.py:200-402 单文件编排）。
**落点**：`export/shacl.py` 已能产出标准 sh: Turtle；新增可选依赖 extras（SHACL 校验库）+`validateDataGraph()` 读面，作为 admission 段3 之后的可选第 4 段（`NEUROVA_ONTOLOGY_SHACL_RUNTIME` 默认 off）或导出前校验档。shapes 仍只有 shapes.py 一处定义，运行时引擎只是**新增求值器**，不造第二事实源。

### P1-2 质量门阈值化（补 E2 静态指标）
本仓 `quality.py:61` 的 consistency 恒 1.0 是静态值；对方的确定性质量门（阈值+metrics+threshold_failures，quality_gate.py:93-120）可直接借鉴形态。
**落点**：`ontologyQualityReport` 的 metrics 换成可计算指标（孤儿率/缺 label 率/逆关系单边数/引用完整率/环数——判据全部现成于 quality.py findings），加 `min_coverage/max_findings` 阈值参数，报告进现有 quality 端点；CI 侧接一条阈值判据。

### P1-3 SPARQL 查询缓存（带失效；补 C2）
本仓每次查询全量重投影+重解析；对方有缓存但**无失效机制**（其自述已知缺陷）——本仓借鉴时必须补上失效。
**落点**：投影图按 `(tenant_id, terms_version, facts_watermark)` 键缓存（进程内 LRU 即可起步），术语/事实/规则任一写入即失效；`sparql_query.py` 单文件改动，行为不变、命中即免重投影。

### P2-1 规则求值 Rete 化 v2（补 D1 表达力）
本仓规则限 2 正原子、逐事实 fireFor 全规则扫描；对方的完整 Rete（alpha/beta/token/terminal+激活去重）是成熟参照。
**落点**：`EVALUATION_STRATEGIES` 增第三档 `"rete_network"`（默认仍 semi-naive，等价性测试沿用 test_semiNaiveEquivalence 模式钉住）；规则形状先放宽到三原子合取与 relay 链式；分层否定与咽喉强制语义不变。

### P2-2 Allen 区间代数引擎（补 D2 时间推理）
本仓 upper_lite 已有 before/after/overlaps/during 词汇但不推理；对方 13 关系判定+合并+覆盖+时间线引擎（kg/temporal_reasoning.py:43-341）可整体借鉴为可插拔模块。
**落点**：本仓 temporal_reasoner 现为待接线状态，先接线再挂 Allen 引擎；输入即事实层 valid_from/until，输出入推导账本（过咽喉），不另起事实源。

### P2-3 图存储门面（补 C1 架构短板）
**落点**：以注册表模式抽象 `graph_backend`（SQLite 为默认唯一生产实现），预留嵌入式 RDF 库第二实现（fail-soft 可选依赖）；导出面已产出 GraphML/GEXF/Cypher，缺的只是运行时挂接面。该项动存储层，须单独立项评审。

### P2-4 Studio 决策/血缘/时间线视图（补 G3）
决策台账+推导账本+双时态事实的数据面全部现成，前端补三个只读视图（因果链图/推导谱系/时间线），对齐对方 Explorer 的 Decision/Lineage 工作区；不动后端契约。

### P2-5 批量装载与进度契约（补 C2/B1）
企业源初始化同步缺 bulk loader 形态。借鉴对方「分批+进度回调+载入前校验+失败回滚」契约（bulk_loader.py:57-360），落在本仓 ingest 通道与 pipeline 的 dry-run 语义上。

### P3-1 IDE 技能包分发层（产品化）
对方把 17 个技能+3 个子代理+hooks 按九个 IDE 生态的清单格式打包分发（提示词层，非代码插件），是低成本扩生态触达的范式。本仓 MCP 工具面可同法包装 skills/agents 清单，优先覆盖本仓已支持的生态。

### P3-2 供应链安全加固
对方的依赖哈希锁定、OpenSSF Scorecard、容器扫描、安装矩阵 CI 值得对齐；本仓 CI 已有基础门，补安全扫描档与依赖锁定策略即可。

### P3-3 贡献度评估器吸收粒度维度
对方评估器有 class granularity / relation completeness 指标（ontology_evaluator.py:300-364）；本仓贡献度评估（reference_y 批2 已落地）可吸收粒度维度作为第四个信号。

### 不照搬清单
- **双 MCP 实现并存**（16/22 工具两套+文档第三套数字）：正是本仓 §6 单一事实源纪律防的病，勿学。
- **OWL 一致性校验占位宣称 HermiT/Pellet**：本仓诚实形态纪律（不做就声明不做）优于对方姿态，勿学。
- **MCP 无鉴权/Explorer 单一静态 Key**：本仓双鉴权 fail-closed 是正确基线。
- **版本管理两套并行 API**：同上，单一事实源。
- **进程内内存图为主的知识图谱**（Explorer GraphSession 默认内存态）：本仓写入即落库+审计的路线更符合治理定位。

---

## 6. 反向借鉴（本仓强项，参照系 ae 可学）

- **准入咽喉单写点**：本仓所有写入（含推理结论）收口 `productionAdmissionGate`，校验/血缘/置信/冲突同链完成；对方 MCP 的 add/update/delete 直接改图，无统一校验审批咽喉。
- **append-only 审计账 + 哈希链**：本仓变更账不可删改；对方版本表内存态可失。
- **写前破坏性变更门禁**：dry-run 整批拒绝 + 三臂对照 replay；对方是事后严重级分类。
- **测试纪律**：本仓「绕开咽喉的测试等于没测」+金样对拍+commit 期红绿门，与对方差分测试/注入回归互补。
- **诚实边界声明**：本仓「不做 OWL DL/完整 SHACL」写在模块头；对方的占位桩与文档宣称落差是反面教材。

---

## 7. 局限性

- **快照时效**：对方读数取自 main 分支 tarball（2026-11-22 拉取，pyproject 自述 0.8.0-dev，最新 tag 0.7.0=2026-09-22）；上游当日仍有推送，行号为快照读数。
- **深读覆盖**：三个并行深读覆盖对方八域与产品面，主控对承重结论做了抽查复核（本仓 term_registry.py:408-414 / rule_engine.py:877-912 / quality.py:61；对方 mcp_server 工具表 16 项、explorer 鉴权 fail-closed 逻辑——全部命中），但未逐行复核对方全部 14 万行；子代理报告中的行号按原样采信，个别可能有 ±数行漂移。
- **静态评测**：本文是代码级静态分析，未做运行时基准（大规模图/并发/性能）、未接付费模型对比 LLM 起草质量；C 维的「规模」判断基于代码结构而非压测。
- **跨报告不可直接比分**：本评分卡与 reference_y 轮同构但子项划分有差异（本次「存储查询与规模」独立成维，替换了该轮的「映射与血缘」维）；Neurova 本轮 83 与 reference_y 轮 90 的差异主要来自维度构成与对手形态（ae 在 C/G/H 三维远强于 Y），**不代表本仓能力回退**；同卡内（本文两列）对比有效。
- **判断成分**：4/5 分界、权重与锚点含专业判断，所有高分项均列了机制证据，可复核可反驳。

---

## 8. 与本系列前报的衔接

- 本体域序列：reference_l（2026-11-05，本体+知识库）→ reference_n（2026-11-15，本体对照框架）→ reference_y（2026-11-19，本体专项 90 vs 77，借鉴 P1–P3 已全部落地）→ **本文 reference_ae（2026-11-22）**。
- 相对 reference_y，参照系 ae 强得多（89 vs 77）：Y 的短板（扁平类型/无标准格式/引擎黑盒）在 ae 上全部不成立——ae 有完整 OWL/SHACL/SKOS、多后端存储与开放 Python API；因此本文对本仓的借鉴清单重心从「建模表达力」转向「**基础设施宽度**（存储/查询/可视化/生态）与**标准运行时**（SHACL 校验/时间推理）」。
- 关联专项：reference_s（知识图谱，2026-10-09）、reference_i（时序 KG，2026-11-13）、reference_r（事件图检索，2026-11-05）已覆盖图存储与检索的更多侧面，本文不重复其结论。

---

## 9. 实施回执（2026-11-23，§5 借鉴清单十三卡全量落地）

用户拍板「不分批不留候选，一次全做」后，十三卡（U1–U11 + 增补 U12/U13/U14）全部实施完毕并逐卡提交（20 笔，本地 main）：

| 卡 | 提交 | 交付 |
|---|---|---|
| U1 SHACL 运行时 | `049e53672` | shacl_runtime.py（形状单源→pyshacl）+ 咽喉段 3 后半三档闸 + export/shacl rdf 前缀修复 |
| U2 查询缓存 | `ed2bddec4` | query_cache.py 库指纹进键（terms+rules+facts 水位），失效与写路径解耦 |
| U3 批量装载 | `bffefcd30` | bulk_load.py 两段式，逐行过咽喉+整批零落盘+补偿撤销 |
| U4 Allen 引擎 | `547981aef` | temporal_algebra.py 13 关系判定+程序化完整合成表（169 格对拍） |
| U5 Rete v2 | `60456672a` | rete_network.py 完整网络 + rete_network 第三档 + 3 原子显式放宽 + v58 迁移 |
| U6 质量门+冲突建议 | `753a2eba7` | 可计算指标+阈值门（退役恒 1.0）+ 只读建议面五策略 |
| U7 Studio 三视图 | `9f39a44e1` | 决策因果图/推导谱系/双时态时间线 + i18n 25 键×11 locale |
| U8 图存储门面 | `0f49f6128` | GraphBackend 契约 + SQLite 默认 + oxigraph 可选第二实现 |
| U9 教程示例 | `cc7ab6c7b` | 教程 5 篇 + 离线示例 3 个（逐个真跑） |
| U10 列画像 | `d727d4d4f` | 采样画像入目录（v59）+ suggester 证据消费（权重全序不倒挂） |
| U11 CLI | `34eb736cc` | neurova-ontology 四命令薄壳 + pyproject 入口 |
| U12 反向链 | `443b5b79d` | backward_chaining.py 目标证明树，与前向链对拍 |
| U13 解释生成器 | `6a61405b5` | explanation.py 账本/证明树统一投影 + 中文模板 |
| U14 差分测试 | `65fda2e32` | 随机序列对拍——**首跑即抓出两处真引擎缺陷**（否定后到不退场、环形推导边递归爆栈）并根修 |
| 收口 | `ee189a045` | 五条新 REST 路由 + 干跑形状闸根因修复（新主体逃过形状闸）+ 路由判据测试 |

**复评（同卡同锚点）**：A3 5、B1 5、C1 4、C2 4、D1 5、D2 5、E2 5、G2 5、G3 4、H2 5（其余子项不变）——**总分 91～93（保守 91 / 全量 93） vs 参照系 ae 89，反超成立**。保守与全量的差值在 E2（冲突消解仍为只读建议+人工，未做自动改写——有意取舍）与 G2（MCP 未扩容，仅 CLI+REST）。**第二轮落地后实测复评见 §10：92，区间 90–93。**收口后全量回归：ontology+api+enterprise+迁移守卫 **1146 passed** 零新增失败；前端 vitest **2910 passed** + vue-tsc 0 错；live-verify 真后端（create_app 工厂，启动 183s）五路由全过。

**过程新增的实测教训**（已写入教程/注释）：① export/shacl 形状文档缺 rdf 前缀（rdflib 必炸）；② minCount/maxCount 导出为 NodeShape 过不了 pyshacl（ConstraintLoadError），sh:in 字符串值导出非法 Turtle——教程 5 已注明边界；③ validation.findings 对新主体跳过形状求值的干跑保真缺口（本批根修）；④ 差分测试抓出否定后到不退场与环形推导边递归爆栈两处引擎缺陷；⑤ 跨进程 live-verify 的 401 排查链：僵尸 uvicorn 顶替端口（netstat+taskkill 清场）+ 签发/验签数据根必须一致 + 签发子进程 stdout 会被导入期日志污染（取 tail -n 1）。

---

## 10. 复评（2026-11-23 第二轮：十三卡+连接器扩容+前端增强全落地后重测）

> 应「重新测评」要求做的第二轮同卡复评。方法与锚点不变（§2：0–5 锚点、同卡同轴）；**参照系 ae 侧分数维持 2026-11-22 快照读数不动**（上游当日在途变化不在本轮范围），本仓侧 20 个子项全部按当前代码现场重验——不是对 §9 投影的抄写。自 §9 回执之后又有两批落地并入本轮重验：**连接器扩容批**（后端 `30a904dcb` + 前端 `19610fa00`：8 个新 sourceType 与变体闭集根因修复）与**前端增强四项**（`b0fec1a1d`：Studio SHACL 体检/质量阈值门/prove·explain 面板/企业源目录页重构）。

### 10.1 维度汇总（首评 → 复评）

| 维 | 首评（11-22） | 复评（11-23） | 参照系ae | 复评判 |
|---|---|---|---|---|
| A 本体建模表达力 | 14 | **15** | 13 | 胜面扩大：运行时 SHACL 补齐最大缺口 |
| B 本体获取与起草 | 13 | **14** | 12 | 连接器矩阵+列画像补齐摄取广度 |
| C 存储查询与规模 | 6 | **8** | 10 | 仍落后 2：门面/缓存/批量装载落地，图分析与多后端生产化未做 |
| D 推理与一致性 | 8 | **10** | 9 | **反超**：Rete 三档+反向链+差分测试抓真缺陷 |
| E 溯源治理与冲突 | 9 | **10** | 10 | 追平：阈值化质量门+只读建议面 |
| F 版本化与演化 | 9 | 9 | 6 | 不变（本仓既有强项） |
| G 消费与集成 | 11 | **13** | 14 | 仍落后 1：CLI+5 路由+Studio 五面板落地，Explorer 级探索面未做 |
| H 工程质量与生态 | 13 | 13 | 15 | 不变：教程/示例补齐，框架适配器/IDE 分发/部署矩阵未动 |
| **合计** | **83** | **92** | **89** | **本仓反超 3 分**（区间 90–93，见 10.3） |

### 10.2 逐子项变化（9 项上调、11 项不变；ae 侧全部不动）

| 子项 | 首 | 复 | 证据（2026-11-23 现场读数） |
|---|---|---|---|
| A3 标准形式化与公理 | 4 | **5** | `shacl_runtime.py`：形状单源 `exportShaclShapes` → pyshacl 运行时校验，off/shadow/enforce 三档（`NEUROVA_ONTOLOGY_SHACL_RUNTIME`），挂准入咽喉段 3 后半（admission.py:388-397）+ REST `/ontology/validate/shacl` + Studio SHACL 体检面板；`pyshacl>=0.25.0` 进 requirements 双清单（首启自动安装）。原「仅 JSON 五约束子集、path_json 存而未用」缺口关闭；诚实边界保留（不做 OWL DL——对方该项同样是占位桩，不构成对方加分） |
| B1 数据源 schema 摄取与映射 | 4 | **5** | SOURCE_TYPES 17 类（protocols.py:20-23）：新增 bigquery/databricks/cassandra/salesforce/servicenow/looker/airflow/git 八类（connectors_saas/nosql/git 三模块，registry.py:194-206 分派；专测 test_saasConnectors/test_nosqlConnector/test_gitConnector/test_lakehouseConnectors）；U10 列画像采样入目录（v59 迁移）+ suggester 证据消费（test_schemaProfile）。残余差：对方 normalize/dedup 万行级清洗与来源标记冲突管线 |
| C1 存储后端与持久化 | 3 | **4** | `graph_backend.py`：GraphBackend 最小契约 + SQLiteBackend 唯一默认实现（读行与既有 SQL 逐字节一致）+ OxigraphBackend 可选第二实现（惰性 import+fail-soft，`NEUROVA_ONTOLOGY_GRAPH_BACKEND`，未安装显式 GraphBackendNotSupported 不静默降级）。生产仍 SQLite 单后端，多后端生产化未做——不给 5 |
| C2 查询能力与规模工程 | 3 | **4** | `query_cache.py`：投影缓存以 terms+rules+facts 水位指纹进键、写路径解耦失效（补上对方缓存都没有的失效机制，test_sparqlQueryCache）；`bulk_load.py`：两段式批量装载，逐行过准入咽喉+任一违规整批零落盘+补偿撤销+进度回调（test_bulkLoad）。图分析/GraphRAG/增量装载仍缺 |
| D1 规则与符号推理 | 4 | **5** | `rete_network.py`：完整 Rete（AlphaNode/BetaNode/TerminalNode）为第三求值档（rule_engine.py:84 `EVALUATION_STRATEGIES = ("full_replay", "rete", "rete_network")`；默认档不变，等价性对拍钉住），档内显式放宽 3 正原子；`backward_chaining.py`：反向链证明树（环剪枝+深度上限，只读与前向分轨，对拍）；U14 差分测试首跑抓出并根修两处真引擎缺陷。对方扣分点仍在（归纳评分常量桩、`_has_type` 占位、规则语言无否定/聚合）——本子项反超 |
| D2 真值维护与时间推理 | 4 | **5** | `temporal_algebra.py`：Allen 13 关系判定+程序化生成完整合成表（169 格对拍，test_temporalAlgebra）；temporal_reasoner 死码退役承接，结论过咽喉入推导账本；精确撤销账本由差分测试护航。与对方会话式 TMS 形态不同、完成度同档 |
| E2 冲突检测与质量门 | 4 | **5** | quality.py 恒 1.0 静态值退役；可计算指标+阈值门（min_coverage/max_findings/max_orphan_rate 闭集按序输出 threshold_failures，quality.py:25-26，test_qualityGate）+ 只读冲突建议面五策略；校验嵌准入咽喉（写前拦截）vs 对方事后消解，自动改写有意不做。本项是保守/全量分界之一 |
| G2 工具面（API/MCP/CLI） | 4 | **5** | neurova-ontology CLI 四命令薄壳（pyproject console_scripts 入口）+ 5 条新 REST 路由（/ontology/validate/shacl、facts/bulk、quality/gate、prove、explain/{fact_id}，knowledge_ontology.py:2119-2224，live-verify 真后端全过）；MCP 22 工具单一事实源+双鉴权 fail-closed 不变。对方双 MCP 工具数漂移+无鉴权扣分仍在 |
| G3 可视化与探索 | 3 | **4** | Studio 三视图（StudioDecisionGraph/StudioDerivationGenealogy/StudioBitemporalTimeline，各带专测）+ SHACL 体检/质量阈值门/prove/explain 面板 + 企业源目录页重构。仍非对方 Explorer 级交互式图探索工作台（sigma 图渲染/时间线 scrubber/十工作区），不给 5 |

不变子项（11 项）：A1/A2、B2/B3、E1（双满分）、F1/F2（本仓强项）、G1、H1（双满分）、H2、H3——逐项核对无状态变化。其中两点说明：H2 的「本体域缺教程/示例」缺口已关闭（docs/03-user-guide/ontology-1..5 五篇教程 + examples/ontology/ 三个离线示例，均真跑过），但部署矩阵仍单一（对方 Docker/Helm/K8s/六云），H2 维持 4；H3 连接器广度已追平（17 类 vs 对方十余种），但框架适配器（0 vs 4 家）与 IDE 分发（CLI vs 九生态插件）仍窄，维持 4。

### 10.3 总分与区间

**复评总分：Neurova 92 vs 参照系 ae 89——反超 3 分**（首评 83 落后 6 → 复评 92 领先 3，净摆动 9 分）。

- 保守下界 **90**：E2、G2 两处判断项若各持 4（冲突消解未做自动改写、CLI 面仍薄）；
- 本评 **92**：按「机制化+测试+治理+实证闭环」锚点逐项重验的取值；
- 上界 **93**：若 H2/H3 按「点名缺口已关闭即满分」口径计（本评未采用——部署矩阵与框架适配器差距是真实的）；
- 与 §9 回执的投影区间（91～93）相容，本评 92 落在区间内。

**仍未追的差距（有意保留，非遗漏）**：多后端生产化与图分析/GraphRAG（C 维余 2 分）、Explorer 级交互探索（G3）、四家框架适配器与九生态 IDE 分发（H3）、六云部署矩阵（H2）、OWL DL 一致性校验（双方均无真实现，本仓诚实声明不做）。

### 10.4 复评现场验证读数（2026-11-23）

- 后端（本机有并行会话重载，默认 30s 档误杀建 app 用例，改 `--timeout=120` 分批串行）：**ontology + enterprise + 迁移三件套 = 1025 passed / 0 failed**（3 分 25 秒）；**api 套件 = 553 passed / 2 failed**——2 失败均为 `test_authSurfaceFreshness`（API_REFERENCE 鉴权面机器段与路由表脱节：文档 1062 条 vs 实际 1065 条，设备桥批新增移动端点后未再生机器段），按守卫自身指引运行 `scripts/generate_api_auth_surface.py --write` 再生后该文件 **7 passed** 归绿。合计 **1580 passed / 0 失败**。
- 前端：vitest **2948 passed / 1 skipped / 16 todo**（2965 总），vue-tsc **0 错**（本机现场重跑）。
- 关键路径 live-verify 见 §9 回执（真后端 create_app 工厂，五条新路由全过）；本轮另现场抽查：SOURCE_TYPES 17 类、8 个新模块在盘、5 条新路由在册、教程 5 篇+示例 3 个离线可跑、Studio 四组件+专测在盘、graph_backend/quality 阈值门/admission SHACL 闸逐处 file:line 命中。
