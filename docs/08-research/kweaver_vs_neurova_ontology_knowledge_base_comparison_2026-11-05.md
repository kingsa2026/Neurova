# KWeaver DIP × Neurova ontology 知识库对比（2026-11-05）

> **对象（先立证据边界）**：用户给定 `github.com/kweaver-ai/kweaver` = **404**。
> org `kweaver-ai` 存在（45 仓，属爱数/AISHU——`i18n-factory` 描述「爱数出品」可证），
> 但主仓 `kweaver` 与官方 README 指向的 monorepo `kweaver-ai/kweaver-core` **均 404**
> （另探 `kweaver-dip`/`DIP`/`kweaver-open`/`kweaver-platform` 亦 404）。
> `decision-agent` README.md:7 自述已迁入 kweaver-core monorepo——**即对方真正的核心
> （含本体引擎与业务知识网络）不在任何公开仓**。个人镜像 `tangkelu/kweaver-dip`
> （62MB，TS，非 fork）来源不可考且官方未指向，**不采信**。
>
> **实际分析对象 = 公开生态五仓快照**（`--depth 1` 克隆于
> `C:/Users/xccoo/.zcode/tmp/kweaver-analysis/`，逐仓 HEAD 见 §7）：
> `decision-agent`（已弃用归档）、`dolphin`、`dsg`、`studio`、`kweaver-docs-archive`。
> 线上现行文档 docs.kweaver.ai 被 Cloudflare 403 拦截（未走浏览器取证），
> 方法论层证据依赖 0.3.0 旧版文档归档——**新旧文档存在断层**（§2.5）。
>
> **文档定位**：研究参考类，仅作背景，**不可作事实源**（`AGENTS.md` §2 原创性与自主性条款）。
> 对方为 Apache 2.0/MIT 亦不授权任何代码搬运；「对方有 X」只用于**提问**，不用于**规定本仓怎么做**。
>
> **证据分级**：对方侧锚点由四路只读子代理实读（decision-agent / dolphin / dsg / studio+docs），
> 主代理抽验八条（清单见 §7）；本仓侧锚点由一路子代理实读，主代理亲验两条断点
> （N1/N2，grep 消费方）与 dolphin 分发链原文。子代理锚点未逐行复算。

---

## 0. 一页结论

1. **「开源决策智能平台」要拆开读**：org 与周边仓公开，但用户点名的 `kweaver` 与官方
   README 指向的 `kweaver-core` monorepo 都不公开。「ontology 为核心方法论 / DIP 为核心平台」
   的自述目前公开可见的支撑只有：旧版 0.3.0 文档里的知识图谱本体 API、各仓菜单文案
   （studio 里 `ontology` 只是菜单 id：`tool.py:19`）、以及已弃用仓里的死代码。
2. **README 与代码的落差是本次最大的可验证发现**：决策智能体的宣传核心 ContextLoader
   **零实现**；业务知识网络召回 prompt **硬编码返空串**；BKN 证据提取 env 门控**默认关**；
   数据脱敏 / prompt injection 防护 / 多 agent 全局仲裁 **无代码**。这与 dramaclaw、Semantica
   两次对比同一条教训：**「有宣传/有文档」≠「有实现」，「有校验代码」≠「有质量闸」**。
3. **公开碎片里真正有质量的是 dolphin**（编排 DSL/SDK）：协程帧树 + 快照 + 断点续跑 +
   工具中断人工介入 + on_stop hook 质量闸 + 上下文桶/预算/压缩 + lost-in-the-middle 缓解 +
   DebugController，1454 个测试函数——是对方生态的工程高地，也是本仓候选汲取的主要来源。
4. **逐维评分（十维加权，权重归一）**：Neurova **7.5** vs KWeaver 公开生态 **4.4**。
   差距集中在知识层（本体/事实/检索三维，对方公开面近乎空白）；对方在「编排引擎」单维反超
   （dolphin 快照/断点/恢复 vs 本仓回合级 parkTurn）。
5. **本仓新断点两条（主代理亲验）**：`security/cognitive_security.py` 的防注入三件套
   生产侧零消费；`security/data_masking.py` 的出口脱敏生产侧零消费——**有码未接**，
   测试侧都有引用（「有测试无接线」）。见 §6 N1/N2，接/删候选 C1/C2。
6. 候选汲取 C1–C6（**净接线两条 + 新能力四条**，不混批）+ 两条不采纳登记（§5.2）。
7. 本文只出报告，**未改任何代码**。未点单前不动码。

---

## 1. 对方体量与形态

| 仓 | 状态（快照 HEAD 见 §7） | 语言栈 | 体量 | 许可 | 定位 |
|---|---|---|---|---|---|
| decision-agent | **已弃用归档**（末次提交即弃用通知） | Go（agent-factory）+ Python（agent-executor/agent-memory）+ TS（agent-web） | Go 1833 文件 / py 776 / ts 372 | Apache 2.0 | 决策智能体：agent-factory(Gin/DDD) + agent-executor(FastAPI) + agent-memory(mem0 fork) + agent-web(React) |
| dolphin | 活跃 | Python | 341 文件 / 约 1454 测试函数 | MIT | AI 工作流 DSL/SDK（`/explore/` `/if/` `/for/` 块语法 + ReAct 探索块） |
| dsg | 活跃 | Go 微服务 ×12 + React 前端 | Go 2714 / TS 3311 文件 | MIT | 数据语义治理（目录/视图/血缘/搜索/授权/网关） |
| studio | 活跃 | Go + Python(FastAPI) + React | 7 组件（studio-web/business-system/mf-model-api/mf-model-manager/oss-gateway/frontend/deploy-web） | Apache 2.0 | 门户壳 + 模型工厂 + 评测控制台（aievla） |
| kweaver-docs-archive | 归档 | mkdocs（0.3.0 旧版，**非 DIP 文档**） | en/zh 双语 | — | 旧版「知识网络」平台文档（KG+术语库+词库，GraphRAG 式） |

**主仓缺失 probe**（2026-11-05 GitHub API 实测）：`kweaver`/`kweaver-core`/`kweaver-dip`/
`DIP`/`kweaver-open`/`kweaver-platform` 全部 404。org 内与本任务相关的活跃仓另有
`kweaver-admin`（管理 CLI）、`kweaver-examples`、`proton-*-sdk`（rds/mq SDK）、
`helm-repo`、`dip-for-{talent,itops,supply-chain}`（行业方案仓，小体量）。

**中间件足迹**（对方取向）：MariaDB/DM8 双适配、Redis、OpenSearch（检索+向量）、
Kafka/NSQ、Hydra OAuth2、OTel——多服务微服务生态，外部服务十余个
（metadata-manage / virtualization-engine / sailor-service 图检索 / alg-server KG / uniquery 等）。
本仓 `docs/specs/2026-09-20-knowledge-foundation-design.md:11` 明确**禁止外部服务**——
这是取向差异，不是本仓短板（与 Semantica 对比同一条裁定）。

## 2. 对方功能全貌（代码级，按子系统，附接线状态）

### 2.1 decision-agent——决策智能体（公开面最弱）

- **ContextLoader 零实现**（主代理亲验 grep 全仓无 class/function）：README.md:26,69-73,135
  大篇幅主张，代码零命中。业务知识网络召回 = `prompt_builder.py:97-107` 的
  `get_graph_retrieval_prompt()`/`get_doc_retrieval_prompt()` **硬编码 `return ""`**（主代理亲读原文），
  下游拼接分支永不触发——**死代码**。
- **BKN 证据透传（摆设级）**：`evidence_extractor.py` 从 `kn_search` 工具响应抽
  `object_type_id/name/score` 构造 `_evidence{module:"bkn"}`，`ENABLE_EVIDENCE_EXTRACTION`
  默认 false（:18，主代理亲验），唯一消费点 `api_tool.py:431-462` 仅限 kn_search 工具。
- **Agent 主循环不在本仓**：依赖 `kweaver-dolphin==0.4.3`（pyproject.toml:34），
  Plan-Reason-Act 由 DolphinAgent/Executor 承担；本仓做组装（`run_dolphin.py:37`）、
  工具三形态适配（ApiTool 代理 operator-hub / McpTool 代理 / AgentTool HTTP 回调自身递归子 agent）、
  中断续跑（InterruptHandler + resume 端点）。
- **权限链实、其余空**：agent 级权限已接线（executor prepare.py:101-108 → factory
  permissionsvc → 外部 authorization 服务）；数据脱敏/防注入/审批记录存储/全局仲裁——
  grep 零命中；审批仅有 `requires_confirmation` 中断原型，无审批人/审批存储/多级。
- **可观测最实**：OTel GenAI 语义约定（`gen_ai.operation.name=invoke_agent`）、
  OTelTraceListener 注入 Dolphin、uniquery 观测查询面（14 文件）——但导出端点**默认关闭**。
- **可评估几乎为零**：仅 `list_for_benchmark.go` 一个为外部 benchmark 系统供数的列表接口；
  评测控制台在 studio（§2.4），执行服务不在公开仓。
- **存储**：MariaDB 10.6（`adp` 库，10 张 `t_data_agent_*` 表）+ Redis + OpenSearch（mem0
  向量面）；无图库。
- tests：agent-factory 683 个 Go 测试文件、agent-executor 200 个单测、根 tests/ 105 个
  E2E（AT 框架，依赖 K8s 真环境）、agent-web 仅 6 个。

### 2.2 dolphin——编排 DSL/SDK（公开面最强，本仓候选主要来源）

- **语言**：块语法 `/explore/` `/prompt/` `/judge/` `/if/` `/for/` `/parallel/` + `@tool(args) -> var`
  赋值 + `$var` 变量池；**无 AST**（正则切块，块=原文运行时解析，parser.py:281-347）。
  **断层亲验**：`language_rules.md` §7 文档化了 `/def/` 函数封装，parser 也切出
  `def/exit/code/python` 标签，但 `executor.py:245-295` 分发链只有
  if/for/judge/tool/explore/prompt/assign/parallel 八分支（主代理亲读原文）——
  **四种语法被解析后被静默跳过**。
- **执行引擎**：`ExecutionFrame` 帧树 + `ExecutionStateRegistry` + `ContextSnapshot`
  （全量上下文序列化/恢复）；`start/step/pause/resume/terminate_coroutine` 完整 API；
  `DebugController`（块级断点/单步/变量检查/快照剖析）+ CLI debug 子命令。
  快照存储**默认内存**，FileContextSnapshotStore 已实现未默认接线。
- **人工介入三通路**：ToolInterrupt（`requires_confirmation` → 帧挂起 WAITING_FOR_INTERVENTION
  → 恢复注入 tool_result 或 skip）、UserInterrupt（asyncio.Event 块边界检查）、
  on_stop hook（`HookConfig{handler,threshold,max_retries≤10}` 评分不过 → 注入反馈重试）。
  **无自动步骤回滚/补偿**（快照恢复即回滚点）。
- **上下文工程**：BuildInBucket 四桶（system/query/scratchpad/history）+ ContextAssembler
  分节/优先级 + BudgetManager token 预算 + Compressor 四策略（Truncate/Extractive/
  Abstractive/SignatureOnly）+ **lost-in-the-middle 位置缓解**（apply_lost_in_middle_mitigation:567）
  + `COWContext` 写时复制隔离 + 历史裁剪 HistoryProjector。
- **工具/LLM**：Skillkit/SkillFunction（docstring→OpenAI JSON schema）六条注册路径
  （entry-points 9 种内置 skillkit / 目录扫描 / tool dict / Agent-as-Skill 禁自调用 /
  MCP 动态适配 / Resource SKILL.md）；LLM 仅 OpenAI 兼容协议双实现（裸 aiohttp SSE +
  AsyncOpenAI），高层 client 带 self-reflection / best-of-n / majority-voting。
- **结果处理**：skill result 策略注册表（summary/preview）+ 大结果外置引用 +
  缓存 backend（Memory/File/SQLite 三种）。
- **观测**：RuntimeGraph（内存实例树/调用链/剖析/诊断）+ Trajectory 分阶段 JSONL +
  trace listener（Simple/OTel，**默认不启用**）+ rich TUI。
- **测试深度（对方最高）**：93 个单测文件约 3.2 万行 + 集成 runner（MockedSkillkit +
  42 个 `.dph` fixture + JSON 用例集，含 tool_interrupt 人工介入全链路）。
- **裸 eval 三处**（主代理亲验）：assign_block.py:57、executor.py:343、variable_pool.py:253。
- 版本号不一致：VERSION=0.3.3 vs pyproject.toml=0.6.0。

### 2.3 dsg——数据语义治理（权限/脱敏最实，检索最旧）

- 12 个 Go 服务（data-catalog/data-view/data-exploration/basic-search/configuration-center/
  auth-service/data-subject/session/task_center/data-application(-gateway)）， ports & adapters
  + Wire 装配；另有 Java 标准化服务。
- **语义搜索 = 纯关键词 OpenSearch**（主代理亲验 basic-search 全目录 vector/embedding/knn
  零命中）：HanLP 中文分词 + ngram + 多域聚合（`data_search_all.go:74`）；
  索引链路实：各服务改数据 → Kafka `af.{服务}.es-index` → basic-search 统一落 ES，
  mapping 版本 v1~v12。
- **血缘两套**：data-view 活跃（公式解析视图级 lineage processor 族 + 外部 sailor_service
  图检索 `QueryGraph`）；data-catalog 的 anydata_search **整文件被注释、注入点也被注释**——
  孤立路径。
- **授权**：Hydra OAuth2 + PBAC 执行引擎（auth-service enforcer 批量策略判定）+
  RBAC 配置中心（两服务**共享库表**非 REST）+ 行列级：sub_view（行/列规则子视图 SQL 生成）
  + 网关 `genWhereClause` 运行时行级过滤（vitess sqlparser）+ 数据分级标签。
- **脱敏实**：desensitization_rule + data_privacy_policy 表 + `sql_masking.go:50 DoMasking`
  （按字段敏感标志拼 masking SQL）+ 外部脱敏服务。
- **AI 语义理解（data-semantic）孤立**：go-zero 服务，库表 AI 业务对象识别（5 状态流），
  **不在 go.work、无任何跨服务 import**（主代理亲验）——未接线/独立演进。
- 本体/图能力全在外部服务（sailor/alg-server，kg_id 配置传入）——**仓内无本体建模代码**。
- 20 种数据源连接器清单硬编码（oracle/pg/doris/ck/hive/dameng/maxcompute/anyshare7...）。

### 2.4 studio——门户 + 模型工厂 + 评测控制台

- `mf-model-*` 的 model = **model-factory（LLM/embedding/reranker 的注册·配额·用量·提示词）**，
  非业务模型（服务自注册路径 `/api/model-factory/v1`，代码中「语义模型」零命中）。
- **本体建模 UI：没有**（主代理亲验）：ontology 只是菜单 id/权限资源/文案
  （`tool.py:19` "ontology": "本体引擎"）；README.md:58 宣称「Manage DataAgent, DataFlow,
  Ontology, and Operator by business domain」，而后端 `Products()` 硬编码只返回
  `{"dip": DIP}`（helper.go:29-33）——**文档-代码矛盾**。
- **aievla 评测控制台**：Benchmark 配置/任务/榜单/指标库 + 数据集管理（@antv/g6、x6、
  monaco、SSE），调外部 mf-task/benchmark-manager/dataset-manager/agent-factory——
  执行服务不在公开仓。

### 2.5 kweaver-docs-archive——旧版文档（与 DIP 断层）

- 归档仅 0.3.0 一个版本，是**旧版知识网络平台**（知识图谱 + 术语库 + 词库，GraphRAG 式）
  的文档；全站 grep DIP/ADP/Decision Agent/AI Store 零命中——**与 DIP 叙事完全断层**。
- 旧版本体概念模型（API 文档级证据）：实体类 + 关系类(edge) + 本体草稿(otl_temp) +
  画布(canvas) + 领域(domain) + 状态(otl_status)；构建任务 full/increment；**无事件/流程
  概念，无版本化/生命周期设计**。
- 抽取管线 UI 流程：准备→数据源→创建本体→知识抽取→映射生成图谱；API 面 38 个端点。
- 「业务知识网络/BKN」一词只在 studio README 出现——**无方法论文档对应**。

## 3. 本方基线（引用既有摸底，不重复展开）

- **知识库本体**：`neurova/knowledge/` 条目层（KnowledgeRepository，指纹去重/同源重入库/
  冲突建议）+ facts 底座（KnowledgeFactStore SPO/validity window/版本/基线/用量账）+
  ontology 子包（term_registry/前向链推理/派生账/RDF 导出）——详见本次会话 2026-11-04
  摸底报告（探索子代理实读，锚点在案）。
- **决策侧（本次补充摸底）**：chat_pipeline 十阶段回合结构 + ToolExecutor 治理/审批链
  （`_governance_precheck`→ApprovalManager）+ 蜂群 SwarmManager（邮箱回灌+台账）+
  neurflow DAG 工作流（与 RSIOrchestrator 无运行时调用关系）+ run ledger 四入口 +
  TrajectoryRecorder/trace 端点 + retrieval_benchmark（NDCG+基线冻结）+ EKB 读写双向 +
  RSI eval harness（增益<0 自动回滚）+ 上下文责任链优先级 + 窗口预算/折叠分辨率阶梯。
- **本仓已知孤立件（子代理报）**：cognitive_security.py 三件套、data_masking.py、
  otel_bridge（仅桥 neurflow）、SubAgentManager/AgentTeam/SupervisorOrchestrator
  （仅 ACP/测试面）。前两条主代理亲验转正为断点 N1/N2。

## 4. 逐维评分（十维加权，权重 100% 归一；分值为本文判断）

**评分含义声明**：KWeaver 分数 = **公开生态可得性折扣后**的读数——核心本体引擎与 BKN
建模代码不公开，对方真实产品能力可能显著高于公开读数，本文不推断、不回填。

| # | 维度 | 权重 | Neurova | KWeaver 公开生态 | 依据（一句话） |
|---|---|---|---|---|---|
| 1 | 本体/知识网络数据模型 | 20% | **9** | 2 | 本仓 ontology 子包+facts 全链在仓可审；对方公开仓零本体建模代码（外部服务化+菜单 id） |
| 2 | 事实层/时效/冲突治理 | 12% | **9** | 1 | SPO+validity window+版本+基线+冲突建议；对方公开仓无任何 facts 概念 |
| 3 | 检索与融合 | 10% | **8** | 3 | 四路 RRF+真向量+FTS+图影子路；对方 basic-search 纯关键词（无向量），decision-agent 图谱召回恒空串 |
| 4 | 上下文构建与预算治理 | 10% | 7 | **7** | 本仓责任链优先级+折叠阶梯 vs dolphin 四桶+预算+压缩+位置缓解——打平 |
| 5 | 编排引擎（执行/中断/恢复/调试） | 10% | 6 | **8** | dolphin 帧树/快照/断点/DebugController 反超；本仓 parkTurn 是回合级，工具级快照恢复缺位 |
| 6 | 多 agent 协作 | 8% | **6** | 4 | 本仓蜂群+邮箱回灌+深度限制；对方子 agent=HTTP 递归回调，无全局仲裁 |
| 7 | 可观测 | 8% | 6 | 6 | 本仓 run ledger+trace 端点 vs 对方 OTel GenAI+uniquery 查询面（默认关）、dolphin RuntimeGraph（默认关）——双方默认态都不开 |
| 8 | 可评估/回归 | 8% | **7** | 5 | 本仓 benchmark NDCG+基线冻结+RSI 闸+EKB 已接线；对方 aievla 控制台有 UI 但执行服务不在公开仓 |
| 9 | 安全控制 | 8% | 6 | 6 | 双方各有实有虚：本仓审批链实但防注入/脱敏**有码未接**（N1/N2）；对方 dsg PBAC/行列级/脱敏 SQL 实、agent 侧无脱敏防注入 |
| 10 | 工程纪律/测试 | 6% | **8** | 7 | 本仓测:源比 1.0:1+红灯判据；对方 dolphin/factory 测试深但文档-代码断层多（§6.2） |

**加权合计：Neurova 7.5 vs KWeaver 公开生态 4.4**。

（维度 9 双方同分的含义：本仓断点接线后该维立刻领先；对方断点因核心仓不公开无法修复验证。）

## 5. 值得汲取的思路（候选清单）

**立项纪律**：候选项一律写成本仓自身可核实的断点/缺口；「净接/净删」与「新能力」两类分开，
不混批；未点单不动码。

### 5.1 净接线（本仓断点，P1）

- **C1 · 防注入检测三件套接进主链或退役**（断点 N1）。本仓缺口：PromptInjectionDetector/
  CognitiveSafetyChecker/MemorySecurityGuard 生产侧零消费、测试侧有护（7 文件）。
  若接线：chat_pipeline Step 0.5 pre-LLM 检查段（既有 actionability/compact 同位）挂输入检测、
  工具结果/记忆入上下文前挂 MemorySecurityGuard，读数进 governance 面。不可逆点：误拦率
  ——阈值须可配、默认观察态。若删除：三套检测+7 个测试文件退役。
- **C2 · 出口脱敏接线或按第 7 条先比后合**（断点 N2）。本仓缺口：`mask_log_message`
  生产侧零消费、测试侧 2 文件。接线位：TrajectoryRecorder 落盘前 + tool_trace 摘要出口。
  注意本仓已有 `privacy_gate`（工具事件门控）与 `sensitive_info` 在役——三者存在职能重叠，
  按**修复教义第 7 条**先对比后合并，可能由 privacy_gate 吸收并退役 data_masking。

### 5.2 新能力（P2/P3，均需求待拍板）

- **C3 · 工具级断点/快照恢复**（P2）。对照点：dolphin ExecutionFrame+ContextSnapshot+
  WAITING_FOR_INTERVENTION+恢复注入 tool_result/skip。本仓现状：parkTurn/resume_payload
  是**回合级**挂起；审批是「执行前等待」，无执行中快照恢复。影响面：run ledger v3 +
  快照存储 + 恢复 API + NeurUI 面板。不可逆点：快照 schema 落库即成兼容面。
  需求先问：长任务审批等待期间进程重启的恢复诉求是否真实存在（现 approval 请求持久化
  已覆盖一部分）。
- **C4 · 工具大结果外置引用 + 处理策略注册表**（P2）。对照点：dolphin skill result
  策略（summary/preview）+ 外置缓存 backend（Memory/File/SQLite）。本仓现状：tool_trace
  成功留摘要失败落盘、window_compactor 是被动折叠；缺「结果本体不进上下文、句柄进上下文」
  的主动减负机制。影响面：tool_executor 结果出口 + 句柄解析消费点 + 缓存 backend。
- **C5 · lost-in-the-middle 位置缓解进 ContextOrchestrator**（P3）。本仓折叠分辨率阶梯
  决定「留多少」，未见「放哪里」（高权威信源置首尾）。改动小；收益先实测。
- **C6 · 评测面产品化**（P3）。对照点：studio aievla（benchmark 配置/任务/榜单/指标库
  产品级 UI）。本仓 retrieval_benchmark 已有用例库+NDCG+基线冻结+API，缺 NeurUI 控制台页。
  需求待拍板。

### 5.3 不采纳登记（取向冲突/无需动作）

- **Kafka→ES「变更→统一索引」总线**：对方 basic-search 的跨服务索引链路依赖消息中间件
  与独立搜索服务——与本仓「禁外部服务、单进程自持」取向冲突；本仓索引一致性走进程内
  revision 戳 + `_record_index_op`，不采纳。
- **dolphin 文档断层（/def/ 未实现、版本号不一致）、decision-agent 的 data-retrieval
  CI 残留、studio README vs Products() 矛盾**：印证本仓既有纪律（「规则以实际存在的命令
  为准」「有码必须有消费方」），无需动作。

## 6. 本仓断点与对方教训清单

### 6.1 本仓断点（主代理亲验，2026-11-05）

- **N1 · cognitive_security.py 三件套零生产消费**。`PromptInjectionDetector`(:115)/
  `CognitiveSafetyChecker`(:312)/`MemorySecurityGuard`(:452) + 组合器(:530-534)：
  全仓 `neurova/` 消费方 grep 排除自身后**零命中**（唯一外部提及是 sensitive_info.py:10 的注释）；
  测试侧 7 文件引用（`tests/unit/security/test_cognitive_security.py`、
  `tests/auth/test_security_integration.py` 等）。属「只写不读」断点：接线或删除二选一（C1）。
- **N2 · data_masking.py 出口脱敏零生产消费**。`mask_log_message`(:232/:310) 生产侧零命中；
  测试侧 2 文件。接线或按教义第 7 条先比后合（C2）。

### 6.2 对方文档-代码断层清单（供对照自查，不作本仓动作依据）

| 断层 | 锚点 |
|---|---|
| ContextLoader 宣传 vs 零实现 | decision-agent README.md:26,69-73 vs 全仓 grep |
| 图谱/文档召回恒空串 | agent-executor `prompt_builder.py:97-107`（主代理亲读） |
| BKN 证据提取默认关且单工具 | evidence_extractor.py:18 + api_tool.py:431-462 |
| 脱敏/防注入/仲裁主张 vs 无代码 | README.md:90/101/126 vs grep 零命中 |
| data-retrieval 服务残留 | AGENTS.md/CLAUDE.md 提及 + CI workflow，源码不在仓 |
| /def/ 语法文档化 vs 执行层无分支 | dolphin language_rules.md §7 vs executor.py:245-295（主代理亲读） |
| 版本号双源不一致 | dolphin VERSION=0.3.3 vs pyproject.toml=0.6.0 |
| README 宣称 Ontology 管理 vs 硬编码单产品 | studio README.md:58 vs helper.go:29-33 |
| 官方 README 指向的 monorepo 404 | decision-agent README.md:7 → kweaver-ai/kweaver-core 404 |

## 7. 证据清单与亲验范围

- **克隆**：`git clone --depth 1` ×5 → `C:/Users/xccoo/.zcode/tmp/kweaver-analysis/`
  （未进本仓工作树）。快照 HEAD：decision-agent `fed70ec`（2026-04-13，弃用通知）、
  dolphin `cb731b3`（2026-04-29）、dsg `5e825c5`（2026-04-17）、studio `bf9694b`（2026-04-01）、
  kweaver-docs-archive `57ab44e`（2026-01-13）。
- **主仓缺失 probe**：GitHub API `repos/kweaver-ai/{kweaver,kweaver-core,kweaver-dip,DIP,
  kweaver-open,kweaver-platform}` 全 404；`orgs/kweaver-ai/repos` 全量 45 仓清点。
- **主代理亲验八条**：①decision-agent `get_graph_retrieval_prompt`/`get_doc_retrieval_prompt`
  恒 `return ""`（Read 原文）；②`ENABLE_EVIDENCE_EXTRACTION` 默认 false（grep :18）；
  ③ContextLoader 零实现（grep class/def/引用 无命中）；④dolphin blocks_act 八分支无
  def/code/python/exit（Read executor.py:240-304）；⑤dolphin 裸 eval 三处（grep :57/:343/:253）；
  ⑥dsg basic-search 无向量检索（grep vector/embedding/knn 零命中）；⑦dsg data-semantic
  不在 go.work 且无跨服务 import；⑧studio ontology 仅菜单 id（Read tool.py）。
  本仓侧亲验两条：N1/N2 消费方 grep（排除自身）+ 测试侧引用清单。
- **其余锚点**出自五路只读子代理（decision-agent 69 次工具调用 / dolphin 55 / dsg 83 /
  studio+docs 71 / Neurova 决策侧 42），未逐行复算；行号随双方推进漂移，复核请锁上述 HEAD。
- **未取证项（如实登记）**：docs.kweaver.ai 线上现行文档（Cloudflare 403，未走浏览器）；
  kweaver-core monorepo 内容；tangkelu/kweaver-dip 镜像内容（不采信）。
