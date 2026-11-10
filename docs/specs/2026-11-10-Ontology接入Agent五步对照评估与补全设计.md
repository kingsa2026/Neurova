# Ontology 接入 AI Agent 五步对照评估与补全设计（2026-11-10）

- **来源**：用户点单——按"Ontology 作为企业业务语义层与操作约束层接入 AI Agent"的五步接入框架（对象建模 → 关系与逻辑建模 → 动作与权限建模 → 封装成工具交给 Agent → 运行反馈）评估 Neurova 是否符合，缺失处形成详细补全设计。
- **纪律**：本档评估与设计，**不实施**；补全项（A1–A5）按批点单，每批独立红绿＋提交。引用外部框架仅为评估依据（评估对象即该五步框架），不构成对任何第三方项目的对齐表述。
- **实施台账**（落格即更）：评估与设计落格 `6632117d1`；开放形态改 MCP server（拍板落格 `be27f7baa`）；**P1 落地 `440c51e06`**（M0 基座＋A1 查询/校验＋A2 事实写入——streamable-http stateless＋json_response，鉴权三段 fail-closed，app.py 挂 /v1/mcp＋on_event 钩子手动驱动子 Starlette lifespan，transport run() 一次不可复用 ⇒ build 返回 (asgi, lifespan) 二元组）；**P2 落地 `5e007b947`**（A3 ontology_derive 求值＋溯源＋materialization 标注；A4 ontology_actions v42 声明表＋ActionRegistry 悬空拒/风险档闭集＋REST CRUD＋MCP 查询分支）；**P3-A5 活体闭环走查**（真后端 /v1/mcp/ 完整序列：initialize 200 / tools 四件 / validate pass / fact_submit 落库＋采纳建议读数；JWT 段修复——_identityFromCredentialsOr401 是同步函数，await dict 被 except 吞成 401 的坑实证修入）。回归：本体 MCP 契约测试 10 格全绿；全族 351 passed（双时态 1 格预存）。
- **关联**：`docs/specs/2026-11-10-GB48000-3-本体建模符合性评估与补齐设计.md`（建模元数据/流程标准面，五项差距已全部关闭）；`docs/specs/2026-11-05-ontology-capability-upgrade-plan.md`（B1–B7 语义栈）；`docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md`（审批收口/指挥资格）。

## 0. 结论摘要

五步框架说的是：Agent 面对的应是**有业务语境的模型**而非原始数据；Ontology 提供统一的业务能力与权限控制，Agent 负责理解需求与调度。按此对照，Neurova 的实况是一条**"建模强、运行时断"**的链：

- **第 1 步 对象建模 ✅ 符合**：术语注册表（类型系统是数据）、事实底座、主体消解（身份判据）、上层本体、领域包全部在位（证据见 §2.1）。
- **第 2 步 关系与逻辑建模 ✅ 符合**：关系类型系统完整，规则面＋前向链推理引擎＋条件类推导＋物化档位（observe/enforce）＋推导账本，是五步里最厚的一段。
- **第 3 步 动作与权限建模 ⚠️ 半缺**：**权限侧厚**（治理工具策略/审批流/指挥资格判定/渠道准入，fail-closed）；**动作建模缺**——本体里"动作"只是领域包的静态词汇，没有运行时的动作登记（动作 → 参数 schema → 绑定工具 → 风险档/审批级），权限绑定停留在**工具名粒度**，业务动作（"取消订单"）没有本体面表达。
- **第 4 步 封装成工具交给 Agent ❌ 核心缺失**：内置工具注册表 **91 个工具中知识/本体相关为 0**（实测 `get_registered_tool_names()`）；四动词门面 `/v1/knowledge/access/{query|analyze|validate|use}` 是 REST——Agent 不能调用；Agent 对本体的唯一接触是 chat 管线的知识检索注入（被动 RAG）；规则推理结论不进 Agent 运行时。
- **第 5 步 运行反馈 ⚠️ 部分**：工具链的治理预检/审批重放/审计/指挥资格判定成熟；admission 唯一写咽喉逐字可核；但 Agent **没有本体写回通道**（事实写入的生产调用面＝kb_builder/抽取链，不经交互式写入），"Agent 处理任务 → 关键变更走权限与人工审核"在本体侧不闭环。

**总读数：2 符合 / 2 半缺 / 1 缺失。断点不在建模面，在"最后一公里"——本体能力全部长成 REST 形态，没有一件被封装成 Agent 可调用的工具（2026-11-10 拍板：以 **MCP server 形态**开放，详见 §3 设计通则）。** 补全方案 A1–A5（§3）按三批切分：P1 基座＋只读三工具＋事实写入（A1＋A2）、P2 推理与动作（A3＋A4）、P3 反馈闭环确认（A5，大部分是既有组件的接线确认）。

## 1. 五步框架与对照口径

| 步骤 | 框架要求 | 判定口径 |
|------|----------|----------|
| 1 对象建模 | 梳理客户、订单、库存等业务对象与数据来源 | 建模机制是否支撑任意业务对象的登记/消解/来源链 |
| 2 关系与逻辑建模 | 定义对象关联和业务规则 | 关系类型系统＋规则/推理是否可用且被消费 |
| 3 动作与权限建模 | 明确可执行动作和审批流程 | 动作是否有运行时登记形态；审批流是否与动作绑定 |
| 4 封装成工具 | 查询、判断、动作封装成工具交给 Agent | **判定硬口径：工具注册表里有没有、Agent 能不能调** |
| 5 运行反馈 | Agent 调工具处理任务，关键变更走权限校验和人工审核 | 写回通道＋权限/审批咬合＋反馈进对话 |

## 2. 逐项对照（现场证据，2026-11-10）

### 2.1 第 1 步 对象建模 —— ✅ 符合

- 术语注册表：`ontology_terms`（kind/label/labels_json/definition/datatype/namespace/iri_base/external_iris/identity_keys/qualifier_schema/版本语义），"类型系统是数据，不是 Enum"（`neurova/knowledge/ontology/term_registry.py` 头注）；
- 事实底座：`knowledge_facts` 三元组（租户/agent/时效/来源链/evidence_state），主体消解字典（v23）；
- 身份判据：`identity_keys_json`（B9 L1）——canonical_label/aliases/attributes 键名，`SubjectResolver` 按类型读判据；
- 领域扩展：领域包（G5，101 条 so: 词汇只补缺导入）＋upper-lite（BFO 对齐七类）；
- 数据来源面：知识库摄取（22 格式/连接器/企微存档/企业源）→ kb_builder 咽喉。

### 2.2 第 2 步 关系与逻辑建模 —— ✅ 符合

- 关系类型：domain/range/range_kinds/cardinality/disjoint_with/inverse_of（双向自动补齐）/symmetric/transitive，父子 kind 一致校验、禁环（`term_registry.py` register）；
- 规则面：`ontology_rules`（head/body/negated_predicates/stratification_level/materialization observe|enforce v35）＋`ForwardChainingEngine`（`rule_engine.py`）＋条件类规则形状（B1，relay/conjunction）；
- 完整性约束：SHACL 语义 shapes 注册表（内置 6 维＋用户 DSL，三态严重级）；
- 记账：推导账本 `derivation_ledger.py`（结论从哪条规则来）、变更审计 `change_log.py`（只追加）、质量报告 `quality.py`（OOPS! 子集＋OQuaRE 两指标）。

### 2.3 第 3 步 动作与权限建模 —— ⚠️ 半缺

- **权限侧（厚）**：
  - 治理工具策略：`security/governance.py` `evaluate_tool_call`（白名单 CRUD＋审批流：pending/approve 后重放/reject，`api/endpoints/governance.py` 头注）；
  - 指挥资格：`security/command_authority.py` `resolveCommandAuthority`（渠道门＋治理门组合，任一拒即拒、缺事实 fail-closed、判定落台账 H1/H2）；
  - 渠道准入：`channels/access_policy.chatAccessDecision`；
  - 审批基础设施：`security/approval_manager.py`/`approval_relay.py`/`approval_continuation.py`（审批等待双链/一次一问/线程不泄漏，2026-11-03 档批 H）。
- **动作建模（缺）**：本体里"动作"仅是领域包静态词汇（`ActionClass/Action/Path/JudgementCondition`，G5 引入）；没有运行时**动作登记**（动作 → 参数 schema → 绑定工具 → 风险档/审批级）；治理策略按**工具名**判（`resolveCommandAuthority` 的 `toolName` 参数），业务动作没有本体面表达——"取消订单"这类动作的权限语义现在只能塌缩到"某个工具允许不允许"。

### 2.4 第 4 步 封装成工具交给 Agent —— ❌ 核心缺失

- **硬证据**：`neurova/builtin_tools.py` `get_registered_tool_names()` 实测 **91 个内置工具，知识/本体相关 0 个**（grep knowledge/ontology/fact/kb_ 均无）；
- 四动词门面 `/v1/knowledge/access/*`（`knowledge_access_facade.py`，B3）是 REST：query→search_knowledge、analyze→analyze_query、validate→validateOntologyCandidates（B2 dry-run）、use→record_fact_adoption——**四个动词没有任何一个进 Agent 工具目录**；Agent 无法经 tool_search/tool_call 触达；
- Agent 对本体/知识的唯一接触＝chat 管线检索注入（`agent/knowledge_retriever_adapter.py` → hybrid 三路 → 可见域检索），**被动 RAG**：检索什么由管线决定，Agent 不能主动查本体术语、验证一条断言、或指定谓词查主体；
- 规则推理（ForwardChainingEngine）消费方仅 API/管线（pipeline/admission/lineage），**推导结论不进 Agent 运行时**——Agent 判断时用不上 enforce 级规则的结论；
- 采纳写回 `record_fact_adoption`（`knowledge_core.py:416`，admin-only 403 门）是治理动作——这个定位本身合理，但意味着 Agent 侧连"建议采纳"都没有表达通道。

### 2.5 第 5 步 运行反馈 —— ⚠️ 部分

- **已有（厚）**：工具链治理预检→审批（等待/重放/一次一问）→审计日志全链（tool_executor :489/:965）；admission 唯一写咽喉逐字可核闸（`admission.py`）＋未知关系候选审批面（`relation_candidates.py`）＋冲突审批（conflicts 三态票）＋溯源进对话（`chat_pipeline.py:2280-2300` knowledge_derivation/lineage_ids 随最终注入记账）；
- **缺**：Agent 无本体写回工具（2.4）⇒ "Agent 处理任务产生的关键变更"不存在本体侧通道，自然谈不上"走权限校验与人工审核"的闭环；事实采纳/use 的治理动作与 Agent 会话脱节（无"Agent 建议采纳→人审→落账"流）。

## 3. 补全设计（A1–A5）

### 3.0 设计通则——以 MCP server 形态开放（2026-11-10 拍板）

工具化的承载形态从「内置工具注册」改为 **MCP server**（用户裁定）：Neurova 内嵌一个
MCP server（`mcp` SDK 已在依赖，`requirements.txt:92-95` 四处声明纪律；client 侧
stdio/sse/streamable-http 三 transport 全备，`tool_layers/mcp_client.py`），本体四动词
作为 **MCP tools** 暴露。一次封装，两面受益：

- **内部 Agent**：`mcp_servers` 共享配置加一条 loopback 指向自身（streamable-http），
  `mcp_bootstrap` 启动自动连接 → 工具挂载进各 agent 的 ToolRouter → 经 A6 tool_search
  目录延迟暴露 → `tool_call`（`mcp.` 前缀）执行——**治理预检/审批/审计/mcp_grants
  （(server, tool) 粒度授权铸造，`security/mcp_grants.py`）全链复用，零新权限机制**；
- **外部 MCP 宿主**（Claude Desktop/Cursor 等任意 MCP client）：同一端点可连（鉴权边界
  见 §5.4），本体能力成为对外标准协议面。

通则各条：

- **接线不是第二实现**（B3 门面先例）：MCP tool handler 是四动词既有处理函数的封装，
  零业务逻辑复制；治理/审批/审计由既有链自带；
- **鉴权与租户**：MCP 端点复用服务令牌/API key 鉴权（`get_current_user_or_service` 同款
  身份解析），租户按凭据——不设无鉴权口；
- 只读工具（query/analyze/validate/derive）默认免审批档；写工具（fact_submit）走治理
  策略＋mcp_grants 授权铸造（既有机制，按需收紧）。

### M0 内嵌 MCP server 基座（P1，A1–A4 的共同前置）

- **动机**：Agent 侧既有 MCP client 链（bootstrap→ToolRouter→tool_search→tool_call，
  治理/授权全链）只认 MCP server——本体能力上 MCP 协议的最短路径是自建 server 端点。
- **设计**：
  - 主 app 挂 **streamable-http** MCP 端点（如 `/v1/mcp`，mcp SDK server 面）；鉴权复用
    服务令牌/API key；租户按凭据解析（与 REST 同源）；
  - server 内工具按 §3.1–§3.4 注册（A1–A4），handler 转交既有处理函数；
  - 内部 Agent 接入：`mcp_servers` 共享配置加 loopback 条目（url=
    `http://127.0.0.1:9527/v1/mcp`＋服务令牌 header）——bootstrap 自动连接，工具经
    `mcp.ontology_*` 名进目录；**不新造权限机制**；
  - 进程内 ASGI 直连可作优化（免网络环回），首版走标准 HTTP 环回（与外部宿主同一协议面，
    自测即互操作测试）。
- **测试口径**：红——端点不存在；绿——MCP client（项目自有的 `MCPToolClient`）连
  loopback → list_tools 见 A1 工具 → call 一只读工具返回与 REST 同源数据；鉴权失败 401。
- **影响面**：`neurova/api/app.py`（挂载）、新 `neurova/mcp_ontology_server.py`（server
  面，约 150 行）、`shared_config` 示例配置。工作量 ≈ 0.5–1 人日。

### A1 本体查询/校验工具化（只读，P1）

- **动机**：§2.4 核心缺失的最小闭合——Agent 获得"有业务语境的模型"的第一步是能**问**。
- **设计**（MCP tools，挂 M0 server）：
  - `ontology_query`（只读）：参数 `query`（term_id/label/别名模糊）、`kind`（可选过滤）、`namespace`（可选）；实现转 `OntologyTermRegistry.term()/listOntologyTerms`（按租户），返回术语行（含 definition/datatype/关系类型声明）＋按 identity_keys 命中的主体摘要；
  - `ontology_validate`（只读 dry-run）：参数 `subjectLabel/predicateTermId/objectTerm`（＋可选 qualifier）；实现转 `validateOntologyCandidates`（B2 dry-run 路径，`pipeline.py dryRunFactCandidates`）——Agent 写入前自查"这条断言合不合法、为什么"，判据五条唯一事实源仍是 validation.py；
  - 工具 description 按 MCP 规范写清何时用/何时不用（既有 builtin description 的格式纪律平移）。
- **测试口径**：红——MCP list_tools 未见工具；绿——M0 client list_tools 在册＋call 返回与 REST 同源数据＋租户隔离（跨租户术语查不到）。
- **影响面**：`neurova/mcp_ontology_server.py`（handler 转交，约 80 行）。工作量 ≈ 0.25 人日（M0 之外）。

### A2 事实写入工具化（受咽喉＋治理链，P1）

- **动机**：第 5 步的通道前提——Agent 处理任务产生的业务断言（"客户 X 升级为 VIP"）应有本体侧表达通道，且天然走权限/审核。
- **设计**（MCP tool，挂 M0 server）：
  - `fact_submit`（写）：参数 `subjectLabel/predicateTermId/objectTerm（＋qualifier/evidenceText）`；实现转 **admission 咽喉**（`productionAdmissionGate.admit`）——逐字可核闸、主体消解、未知谓词落候选审批面（relation_candidates）全部既有；
  - **审批咬合（不新造，且 MCP 化后更顺）**：工具名 `mcp.ontology.fact_submit` 走 ToolExecutor 既有治理策略；用户审批时经 **mcp_grants** 铸造 (server, tool) 粒度持久授权——后续同名调用免审批直达（`security/mcp_grants.py` 既有机制）；admission 侧的候选审批（新谓词）与冲突审批（conflicts 三态票）是第二道异步人审，双层互不替代；
  - 回执：写入成功返回 fact_id＋溯源（lineage/derivation 钩子），Agent 可在对话里引用（第 5 步反馈）。
- **测试口径**：红——list_tools 未见；绿——call 转交 admission（mock）＋evidenceText 缺失被 `_checkVerifiability` 拒（契约继承）＋未知谓词落候选（不消失）＋审批 remember 后 grants 命中。
- **影响面**：`neurova/mcp_ontology_server.py`（约 80 行）。工作量 ≈ 0.25 人日（M0 之外）。

### A3 规则推理查询工具化（P2）

- **动机**：第 2 步的产出（规则/推理）目前到 API 为止——Agent 判断时用不上 enforce 级结论（如"高风险订单必须人工审核"这类业务规则的可推导结论）。
- **设计**（MCP tool，挂 M0 server）：
  - `ontology_derive`（只读）：参数 `subjectLabel`（＋可选 `predicateTermId`）；实现转 ForwardChainingEngine 的结论查询（materialization=**enforce** 的规则结论直接可用；observe 态结论标注"观察态"防误导）＋`derivation_ledger` 溯源（结论由哪条规则/哪些事实推出）；
  - 输出带 `materialization` 标记与溯源链——Agent 引用结论时可给用户"为什么"。
- **测试口径**：红——list_tools 未见；绿——enforce 结论返回＋observe 标注＋溯源链非空＋无规则时空结果不炸。
- **影响面**：`neurova/mcp_ontology_server.py`（约 60 行）＋ForwardChainingEngine 只查询口（若缺，加一个只读查询函数）。工作量 ≈ 0.25 人日（M0 之外）。

### A4 动作建模最小面（P2）

- **动机**：第 3 步的动作建模缺——把"业务动作"从工具名粒度升到本体面表达，同时**不推翻**既有权限设施。
- **设计（最小面，克制版）**：
  - 新表 `ontology_actions`（v42，迁移注册表）：`action_id/tenant_id/label/definition/param_schema_json/bound_tool/risk_tier(low|medium|high)/enabled`——动作＝**声明**：它绑定一个既有工具（bound_tool；G4/M0 后可为 `mcp.ontology.*` 本体工具或任意内置/MCP 工具名）与参数模板，风险档由登记者声明；
  - 联动：`resolveCommandAuthority`/`evaluate_tool_call` **不改判定逻辑**——动作声明作为治理侧的**元数据读数**（治理中心可按 risk_tier 过滤展示、按动作名配白名单/审批），Agent 侧经 `ontology_query(kind='action')`（MCP tool）可查动作清单与风险档（决策时知道哪些动作要审批）；
  - **刻意不做**（本轮）：动作编排/回滚/事务——那是工作流引擎的领地（NeurFlow），越界即平行体系；动作运行时执行仍走既有 tool_call 单工具边界。
- **测试口径**：红——表/端点缺；绿——CRUD＋risk_tier 闭集校验＋bound_tool 必须是已注册工具名（防悬空动作）＋ontology_query 可查。
- **影响面**：`knowledge_facts.py`（v42 迁移）＋`term_registry.py` 或独立 `action_registry.py`（读写面）＋`knowledge_ontology.py`（CRUD 端点，admin）＋前端（本体工作台动作分区或治理中心展示，最小＝只读列表）。工作量 ≈ 1 人日。

### A5 反馈闭环确认（P3，以接线确认为主）

- **动机**：第 5 步的多数组件已存在（§2.5）；A2 落地后闭环只差**确认与一处补线**。
- **设计**：
  - 闭环走查（活体验收脚本）：Agent 经 fact_submit 写断言 → admission 逐字可核 →（新谓词）候选审批 → 事实投影 → 后续检索命中 → 溯源（knowledge_derivation）进对话——全程已有组件，脚本化取证一次；
  - 补线一处：`fact_submit` 的回执里带 `fact_id`，与 `record_fact_adoption`（admin 治理动作）之间加"**采纳建议**"读数——Agent 对话里可建议，人审仍是 admin（不放宽权限，只给表达通道）；
  - 治理中心展示 fact_submit 的审批/写入台账（既有台账面读数，零新表）。
- **工作量** ≈ 0.5 人日（脚本＋一处回执补线）。

## 4. 批次切分与验收

| 批次 | 内容 | 依赖 | 工作量 | 验收 |
|------|------|------|--------|------|
| P1 | **M0 内嵌 MCP server 基座** ＋ A1 查询/校验 ＋ A2 事实写入 | 无（MCP SDK 已在依赖） | 1–1.5 人日 | 项目自有 MCPToolClient 连 loopback：list_tools 见三工具、call 与 REST 同源、鉴权 401；fact_submit 经咽喉写入（活体取证）|
| P2 | A3 推理查询 ＋ A4 动作建模最小面 | P1（M0 server 已挂） | 1.5 人日 | enforce 结论可查带溯源；动作 CRUD＋risk_tier 闭集＋bound_tool 悬空拒 |
| P3 | A5 反馈闭环走查＋采纳建议读数 | A2 | 0.5 人日 | 闭环走查脚本取证；采纳建议只读不放宽 |

总工作量 ≈ 3–3.5 人日。每批独立提交（`feat(ontology): ...`），红绿实测随提交说明。

## 5. 待拍板项与不做什么

1. **A2 fact_submit 的默认审批档**：默认直写（admission 逐字可核＋候选/冲突异步人审兜底，**推荐**——写入面已有三层异步闸，再加同步审批会让 Agent 每次写断言都卡人）、默认全审批（严，交互卡顿）、按谓词风险级（中，需先给谓词加风险列）。推荐第一项，运维可经治理白名单随时收紧。
2. **A4 动作的 bound_tool 粒度**：绑定到既有内置工具（推荐，最小面）vs 引入"动作执行引擎"（新平行体系，不做）。推荐前者。
3. **A1–A3 工具的启用范围**：MCP server 层全部开放＋Agent 侧按 mcp_servers 配置选择性挂载（推荐——server 层不做 per-agent 裁剪，挂载面即开关；治理/授权在调用链按既有机制生效）。
4. **MCP 端点鉴权边界**：服务令牌/API key（推荐，与 REST 同源）vs 公开无鉴权（不做）。外部宿主接入时按此边界发放凭据。
5. **不做的事**：不做动作编排/回滚/事务（NeurFlow 领地）；**不做对外公网无鉴权开放**（MCP 端点先内网/loopback＋令牌，公网暴露须先过反代鉴权评审）；不做"Agent 自主改术语/规则"（术语/规则登记仍是 admin REST——类型系统的变更权限不随 Agent 开放）；MCP server 首版不做 resources/prompts 面（只做 tools，增量按需）；不在本档实施。
5. **与 GB/T 48000.3 评估档的关系**：那边管"建模元数据/流程标准"（已全落地），本档管"运行时接入"——两档正交，A1–A5 不依赖那边任何未落项。
