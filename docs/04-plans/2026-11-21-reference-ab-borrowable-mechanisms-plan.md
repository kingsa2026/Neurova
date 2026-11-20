# reference_ab 借鉴机制实施细则（除 P2-1 外六项）

> **性质**：实施计划（备稿待拍板 → 按批实施）。
> **来源**：`docs/08-research/reference_ab_vs_neurova_managed_agent_orchestration_evaluation_2026-11-20.md` §6 借鉴清单。按 2026-11-20 拍板：**P2-1（成本透明表进文档）不纳入本批**，其余六项（P1-1/P1-2/P1-3/P2-2/P2-3/P2-4）细化如下。
> **纪律**：每项给出现状锚点（file:line 实测）、实施方案、红绿测试设计与验收判据；不建第二套编排/事实源；外部代理判定不记 token；第三方物仅以功能依赖形态出现。

---

## 0. 总览

| # | 项 | 优先级 | 主要落点 | 依赖 | 待拍板 |
|---|-----|--------|----------|------|--------|
| P1-2 | 外部成员验收/评审判定通道补线 | P1（正确性缺口，最先） | `swarm.py:1985`、`acp_member.py` | 无 | D-B |
| P1-1 | 蜂群协作拓扑图可视化 | P1 | `console.py` 新投影端点 + NeurUI 新面板 | P2-4 同批 | D-A |
| P2-4 | 服务端投影契约钉子 | P2（与 P1-1 同批） | 投影 schema + 对齐钉子测试 | — | 无 |
| P1-3 | 企业源摄取「启动钩子+巡检补跑」双保险 | P1 | `app.py` lifespan + `agent/scheduler.py` + `knowledge/enterprise/registry.py` | 无 | D-E |
| P2-3 | 候选板 H-4 事件重放投影（重启可查） | P2 | 新模块 `agent/candidate_projection.py` + console 读面 | 无 | D-C |
| P2-2 | 企业源 text2SQL 只读分析档接蜂群面 | P2 | `builtin_tools.py`/`tool_executor.py` + `mcp_agent_tools_server.py` | 无 | D-D |

建议批次：**批1 = P1-2**（最小、堵正确性缺口）→ **批2 = P1-1 + P2-4**（投影端点、图、契约钉子同批交付）→ **批3 = P1-3** → **批4 = P2-3** → **批5 = P2-2**。每批按仓内纪律执行：红灯先行 → 最小实现转绿 → A/B 零新增失败 → live-verify 真链路 → `--only` 逐文件提交。

---

## 1. P1-2 外部成员验收/评审判定通道补线

### 1.1 现状锚点（设计-实现落差）

- 设计裁定：外部成员交付物**不降级 skipped**，适配器应提供判定通道（`docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md:174,485`，D2）。
- 实际接线：`swarm.py:1985` 构造 `NeuacpMemberAdapter(executor, name=name, cwd=cwd)` **未传 `verify_channel`**；`acp_member.py:59` 形参默认 `None`、`:66` `self.llm_client = verify_channel`。
- 消费链：`swarm.py:2430` `verifyChannel = getattr(agent, "llm_client", None)` → `:2434/:2450` `getattr(verifyChannel, "chat", None)` → 外部成员恒为 `None`。
- 结果：`acceptance_gate.py:121-132` 判定器不可用 → **judge_unavailable 诚实降级**（completed + skipped 标注）；`review_gate.py:74,95` 同样拿不到通道。外部成员交付物目前**不过验收/评审门**。

### 1.2 实施方案

给 `NeuacpMemberAdapter` 补一个**判定通道对象**（`llm_client` 语义：暴露 `async chat(prompt) -> str`），并在 `swarm.py:1985` 构造时传入。判定通道与成员工作会话**隔离**：

- **ACP stdio 执行体**：在同一 `NeuacpClient` 上开**独立判定会话**（`session/new`），只做文本往返（发判定 prompt → 收集至回合结束的文本）；判定会话上的 `session/request_permission` 一律 **fail-closed deny**（复用 `acp_member.py:118` 审批泵的桥接形态，裁决恒 deny）——判定不需要工具面。
- **plugin 执行体**（单向管道）：每次判定 = 一次独立 headless 调用（`NeuacpPluginExecutor` 本就是一次性提示词模型，天然契合）。
- 判定会话的帧照走 F2 帧留痕（`frame_log.py`）与 tool_call 镜像纪律；**不记 token**（外部代理成本纪律，`cost_source=external` 另批落地时统一收口）。

### 1.3 实施步骤

1. `acp_member.py`：新增 `NeuacpVerifyChannel`（内部类或同模块小类）：持 executor/client 引用，`chat(prompt)` 走独立会话/独立调用；权限请求恒 deny；异常时抛出（由 `goal_verifier` 判 parse_ok=False 走诚实降级，不吞错）。
2. `acp_member.py:59` 构造参数 `verify_channel` 已存在——当调用方未显式传时，**默认自建判定通道**（惰性，首次 chat 才建会话），避免改变既有测试桩行为；`swarm.py:1985` 显式传入或依赖默认均可（推荐显式传 `verify_channel=None` 语义改为"自建"，并在 docstring 注明）。
3. `swarm.py:1985`：构造处补 `verify_channel` 传参（或确认默认自建生效），使 `swarm.py:2430` 的 `getattr(agent, "llm_client", None)` 对外部成员取到真通道。
4. 验收/评审两处消费点（`swarm.py:2434`、`:2450`）零改动——它们已经按 `llm_client.chat` 取通道。

### 1.4 红绿测试设计

- **红灯**：用 F4 同构桩 `NeuacpScriptedExecutor`（内核级同构桩，tests/unit/agent/neuacp/ 既有）脚本化返回一段「未达标」判定文本；跑 `SwarmManager` 派活 → 外部成员 run 现状断言 `acceptance.skipped == "judge_unavailable"`（证明通道缺失，红）。
- **绿灯**：接线后同一脚本 → 断言 `acceptance.achieved is False`、回炉一次、仍不达标则 `failed(cause=acceptance_failed)`；再脚本化「达标」文本 → `completed` 且 `acceptance.achieved is True`。
- **评审相位**：reviewMode=supervisor 的外部成员 run，findings 转修正指令回炉链路同内成员一致。
- **权限面**：判定会话收到 `session/request_permission` → 恒 deny 且不影响判定文本收集。

### 1.5 验收判据

- 外部成员 run 的验收/评审行为与内成员**同判据同链路**（不再出现 judge_unavailable 降级，除非外部代理真的答不出判定——此时降级标注保留，诚实语义不变）。
- A/B：swarm/neuacp 域零新增失败；live-verify 用桩 CLI 走通「派活 → 交付 → 验收判定 → 候选 → 合入」全链。

### 1.6 影响面

`neurova/agent/neuacp/acp_member.py`、`neurova/agent/swarm.py`（仅构造点一行）、对应单测；不改验收/评审门与 goal_verifier 本体。

---

## 2. P1-1 蜂群协作拓扑图可视化

### 2.1 现状锚点

- 数据已齐：H-4 事件账本（`swarm_event_log.py:83`，per-run JSONL，带 seq/lineage/agentPath/depth/trace）；运行台账 `agent_runs`（parent_session_id 读面 `agent_run_store.py:488`，对外路由在 `api/endpoints/console.py` 的 `/console/chat/runs`）；span trace trace_id 落台账（v4 迁移）。
- 实时事件已广播：`swarm.py:2615 _broadcast` → SessionSyncManager（subagent_started/chunk/completed/stalled 等，前端 `useSessionSync.ts` 已订阅、断线续传 `:131`）。
- 前端现状：只有浮窗栈（`useSubAgentWindows.ts:37`）与 TeamPage 状态卡——**没有**「谁委派给谁、依赖谁、卡在哪」的图。
- 图渲染库已在依赖：`@vue-flow/core@^1.41.5`（含 background/controls/minimap）——**零新增依赖**。

### 2.2 实施方案

**服务端只出投影，前端只做渲染**（P2-4 契约）：

1. 新增只读投影端点：`GET /console/chat/runs/{parent_session_id}/graph`（挂 `console.py` 既有读面旁，沿用同一鉴权与会话归属/租户判定，参照 `session_sync.py:148-164` 的归属校验形态）。返回：
   - `nodes[]`：`{run_id, member_name, kind(internal|external), executor_tool, status, depth, team_id, started_at, finished_at, duration_ms, error_type}`——来自 `agent_runs` 台账行 + 内存 run 态；
   - `edges[]`：`{type: spawn|dependency, from, to}`——spawn 边取 parent→child（`parent_subagent_id`/lineage），依赖边取各 run 的 `task_unit.dependencies` 解析结果（`swarm.py:759-791` 同源映射）；
   - `meta`：`{revision, generated_at, truncated}`（runs 超 `MAX_FINISHED_RUNS` 上限时诚实标注截断）。
2. 投影函数落新模块 `agent/swarm_graph_projection.py`（不回填 `agent_core.py`，尺寸棘轮纪律），输入=台账行+事件，输出=纯结构；**不落新表、不写新账**（读投影，事实源仍是台账+H-4）。
3. 前端新组件 `SwarmFlowPanel.vue`（vue-flow）：节点按 status 着色（复用既有状态词汇表，`LEDGER_TO_WINDOW_STATUS` 对齐），spawn 边实线、依赖边虚线；运行中经既有 `useSessionSync` 事件增量刷新（started→建节点、completed/failed→定色）；入口挂运行详情区与 TeamPage。
4. v1 边集 = spawn + dependency；审批/候选边留 v2（见待拍板 D-A）。

### 2.3 红绿测试设计

- **红灯**：投影函数单测先写——给定固定台账行+事件序列，断言 nodes/edges；端点不存在先 404（红）。
- **绿灯**：实现端点与投影函数转绿；契约钉子测试同批落（P2-4，§7）。
- **前端**：SwarmFlowPanel 桩测试——给固定投影 JSON，断言节点/边渲染数量与状态着色；事件增量（started/completed）驱动更新。

### 2.4 验收判据

- 真后端 live-verify：建队 → dispatch_team 三成员（含一条依赖）→ 图端点返回 3 节点 3 边（2 spawn + 1 dependency）；前端面板实时出现并随终态变色。
- A/B 零新增失败；`/openapi.json` 快照若涉及路由登记同步重生成。

### 2.5 影响面

后端：`console.py`（+1 路由）、新模块 `swarm_graph_projection.py`、（可选）`agent_run_store.py` 补一个按 parent_session_id 的批量读函数。前端：新增 `SwarmFlowPanel.vue` + 接线点两处 + i18n 键（×11 语言对齐）。

---

## 3. P2-4 服务端投影契约钉子

### 3.1 动机

对方 2106 行前端 traceParser 与平台私有 trace 结构强耦合，是反面前车。本仓约定：**多代理可视化的一切语义解析在服务端完成，浏览器只拿 render-ready 结构**。

### 3.2 实施方案

1. 投影 schema 服务端单源：`swarm_graph_projection.py` 中以 dataclass/TypedDict 定义 `GraphNode/GraphEdge/GraphProjection`，端点序列化即此结构——字段集固定，不透传原始事件 JSON。
2. **词汇表对齐钉子**（沿用 `LEDGER_TO_WINDOW_STATUS` 先例，`tests/unit/api/test_agentRunStatusVocabularyParity.py` 形态）：新增契约测试钉住「投影字段集 ↔ 前端 TS 类型 ↔ 组件消费字段」三方一致；前端类型手抄对齐，漂移即红。
3. 前端纪律：SwarmFlowPanel 及后续可视化组件**不 import 事件语义、不做 trace 解释**；该条以契约测试 + 评审守护（诚实说明：不做硬性自动化扫描）。

### 3.3 验收判据

- 契约测试进 `tests/unit/api/`；投影字段增删必须同批改三方（后端 schema/前端类型/组件），漏改即红。

---

## 4. P1-3 企业源摄取「启动钩子 + 巡检补跑」双保险

### 4.1 现状锚点

- 同步设施已齐：`knowledge/enterprise/registry.py`——`enterprise_sync_history` 表（`:36-56`，含 tenant_id/source_id/trigger_kind/status/started_at）、`_recordSyncHistory`（`:87`）、`listSyncTenants`（`:128`）、`runOnceAsync(tenantId, sourceId, triggerKind)`（`:480`，trigger 现为 manual|interval）。
- 调度：`agent/scheduler.py:784 addSystemJob(func, jobId, seconds)`（企业源可靠性批已接通，惰性单例已修）。
- 启动钩子先例：`app.py:974-976` lifespan 内 `to_thread(reconcileSwarmRunsAtStartup)`；同文件 `:1005-1020` 一次性收敛模式（底座不起常驻后台线程）。
- 缺口：源配置了同步但「近期无成功记录」时，无巡检兜底——对方 kb-sync-checker（24h 窗口检查 + 指数退避补跑）补的正是这一层。

### 4.2 实施方案

1. 新增 `auditEnterpriseSyncStaleness(triggerKind: str) -> dict`（落 `registry.py` 或新小模块）：
   - 对 `listSyncTenants()` 每租户每个启用源，查 `enterprise_sync_history` 最近一条成功记录；
   - 距今超过 `NEUROVA_ENTERPRISE_SYNC_STALE_HOURS`（默认 24）或从未成功 → 调 `runOnceAsync(tenant, source, triggerKind="audit")` 补跑（内部自带单飞/失败落账）；
   - 返回 `{checked, triggered, skipped, failed}` 汇总，fail-soft（单源异常不阻断其余）。
2. **启动钩子**：`app.py` lifespan 在蜂群收敛之后加一次 `to_thread(auditEnterpriseSyncStaleness, "startup")`——部署/重启后立即补齐过期知识，对应对方「部署后立即同步」custom resource。
3. **周期巡检**：lifespan 起 `addSystemJob(auditJob, jobId="enterprise-sync-staleness-audit", seconds=86400)`（经既有调度器，不另起线程），job 内调 `auditEnterpriseSyncStaleness("audit")`——对应对方 24h sync-checker。
4. `trigger_kind` 为 TEXT 列，新增 `startup`/`audit` 取值无需迁移；admin 同步历史读面天然可见新触发来源。

### 4.3 红绿测试设计

- **红灯**：临时数据根造一租户一源，`enterprise_sync_history` 无成功记录 → 断言「启动钩子未实现时无补跑发生」（以 runOnceAsync 调用计数为 0 证红，或先写期望行为测试直接红）。
- **绿灯**：实现后——无近期成功 → `runOnceAsync(triggerKind="audit")` 被调且历史新增 `trigger=audit` 行；24h 内有成功 → 不触发（`skipped` 计数）；单源 connector 抛错 → 其余源继续、汇总 `failed` 计数。
- **调度**：jobId 注册幂等（重复 start 不双跑），停服不残留。

### 4.4 验收判据

- live-verify：真后端启动日志出现一次 startup 审计（有补跑或 skipped 均可），`enterprise_sync_history` 可查 `trigger_kind IN ('startup','audit')`；A/B 企业源域零新增失败。

### 4.5 影响面

`knowledge/enterprise/registry.py`（或新小模块）、`api/app.py` lifespan 两行、`agent/scheduler.py` 注册一处；不改 connector 协议与既有 interval 调度。

---

## 5. P2-3 候选板 H-4 事件重放投影（重启后可查）

### 5.1 现状锚点

- `candidate_merge.py:19-23` 自注：候选板**不落盘**，持久留痕走 H-4 run 事件账本（candidate_submitted/merged/conflict）。
- `approval_chain.py:697-703` 自注：候选板在 SwarmManager 内存里，**跨进程不可查**——重启后 submitted 卡「诚实报候选不存在」。
- 事件族已全：`swarm.py:1138 candidate_submitted`、`:1147 candidate_conflict_flagged`、`:1178 candidate_revise_required`、`:1203 candidate_conflict`、`:1216 candidate_merge_rejected`、`:1224 candidate_merged`（均带 candidate_id 与相关字段）。
- 内存板结构：`CandidateMergeBoard`（`candidate_merge.py:105`，revision 单源 + CAS + 冲突互标）。

### 5.2 实施方案（推荐：重放投影，不落表）

1. 新模块 `agent/candidate_projection.py`：`projectCandidateBoard(eventsByRun: dict[str, list[event]]) -> CandidateBoardSnapshot`——按 seq 时间序折叠六类 candidate_* 事件，重建 `{revision, candidates:[{candidate_id, run_id, artifact_keys, status, base_revision, conflict_with, note}], conflicts[]}`；折叠规则与 `CandidateMergeBoard` 的状态迁移一一对应（submitted → merged/rejected/revise_required/conflict）。
2. 读面：`GET /console/chat/runs/{parent_session_id}/candidates`（挂 console.py，鉴权同 §2）——按台账取该会话全部 run → 逐 run `readRunEvents` → 投影。跨进程/重启后照常可查。
3. `integrationReport`（`swarm.py:1075`）兜底增强：内存板为空（他进程场景）时以投影补齐 snapshot，标注 `source: "replay"`；内存板在时仍以内存板为准（`source: "live"`）——**不双写、不建第二事实源**，账本仍是唯一持久层。
4. 房间候选处置（`applyRoomCandidateAction`，`swarm.py:1264`）语义不变：处置仍只认内存板；投影只解决「看」，不扩大「判」。

### 5.3 红绿测试设计

- **红灯**：新开 SwarmManager 实例（模拟重启）后，现状查询候选 = 不存在（红）；投影端点 404（红）。
- **绿灯**：临时数据根走真实 `appendRunEvent` 写入完整候选生命周期事件 → 投影结果与内存板状态逐字段一致；重启模拟（新实例+投影）后 submitted/merged/conflict 均可查；乱序/缺事件（账本截断）时投影诚实标注 `incomplete`。

### 5.4 验收判据

- live-verify：派活 → 候选提交 → **重启后端** → 投影端点仍返回该候选（status=submitted）；合入后再查 → merged。A/B 零新增失败。

### 5.5 影响面

新模块 `candidate_projection.py`、`console.py`（+1 路由）、`swarm.py` integrationReport 兜底一小段；不改 CandidateMergeBoard 本体与 CAS 语义。

---

## 6. P2-2 企业源 text2SQL 只读分析档接蜂群面

### 6.1 现状锚点

- NL2SQL 能力**已在仓内**：`api/endpoints/knowledge_nl2sql.py`（`ENV_NL2SQL_ENABLED = "NEUROVA_NL2SQL_ENABLED"` `:27`；未开闸时 ask/suggest 一律 **403 点名** `:48-49`——能力存在、默认关、拒绝诚实）；SQL 生成/执行底座在 `knowledge/enterprise/connectors_sql.py`。
- 蜂群工具面：`builtin_tools.py` 注册 + `tool_executor.py` 执行（执行咽喉 `:1487-1514` 强制成员工具白名单，先于治理不可 bypass）；`MAIN_AGENT_ONLY_TOOLS` 单源 `builtin_tools.py:2498`。
- 反向 MCP 先例：`mcp_agent_tools_server.py:155 knowledge_search` / `:184 memory_search`（双鉴权 fail-closed + 输出三层截断）。
- 对方形态（对照）：OpenAPI 动作组 + schema few-shot 注入提示词 + 只读 SQL 查询引擎。

### 6.2 实施方案

**不动 `NEUROVA_NL2SQL_ENABLED` 总闸语义**（默认关、开即全量可用的口径保持），在其上叠「蜂群只读分析档」：

1. 成员工具面：`builtin_tools.py` 注册 `enterprise_data_query(question, source_id?)` ——走既有 nl2sql 管线生成 SQL，**仅 SELECT 语义**（connectors_sql 层拒绝 DDL/DML，复用其现有校验；如缺则补只读断言），结果截断复用 MCP 面三层截断纪律；成员可用（不进 `MAIN_AGENT_ONLY_TOOLS`），执行咽喉白名单天然生效。
2. 反向 MCP 面：`mcp_agent_tools_server.py` 增只读工具 `data_query`（与 team_list/knowledge_search 同款双鉴权 + 截断），供外部编码代理分析企业数据——租户作用域沿用 `knowledge_search` 的单源过滤形态（`KnowledgeRepository.search_visible_items` 同款租户/可见性判定思路，数据源按租户段过滤）。
3. schema 上下文：工具描述内附数据源表 schema 摘要（few-shot 注入，学对方把 schema 写进提示词的做法），schema 来源=连接器既有 schema 读面，**不新造元数据**。
4. 记账：走本仓 LLM 管线的判定/生成正常记 usage；SQL 执行走连接器只读通道。

### 6.3 红绿测试设计

- **红灯**：总闸关 → 工具调用返回结构化「能力未开启」错误（沿用 403 点名语义，工具面转译为工具错误而非异常）；总闸开 → 现状无此工具（红）。
- **绿灯**：开闸 + 测试数据源（SQLite 内存库）→ `enterprise_data_query("最近 10 笔订单")` 返回行数据；注入 `DROP TABLE`/`INSERT` 意图 → 被只读校验拒绝并点名；越权 source_id（他租户）→ 空/拒绝；MCP 面 `data_query` 双鉴权 401/403 语义与既有三工具一致。
- **成员白名单**：explore 型成员（只读白名单）能拿到该工具；被剔除成员拿不到（执行咽喉拦截断言）。

### 6.4 验收判据

- live-verify：真后端开闸 → 蜂群成员在任务中成功查询演示数据源并引用结果；反向 MCP 用桩外部代理查通；A/B 零新增失败。
- 待拍板 D-D 未定前，默认实现两 face 都接但均可独立关断（工具级 env），出厂默认仅成员面开、MCP 面跟随总闸。

### 6.5 影响面

`builtin_tools.py`（+1 工具 schema）、`tool_executor.py`（+1 执行分支）、`mcp_agent_tools_server.py`（+1 只读工具）、`knowledge_nl2sql.py`/`connectors_sql.py`（补只读断言与可复用入口，不改既有端点行为）、i18n 工具描述键。

---

## 7. 待拍板项（均附推荐与影响面；如无异议，实施时按推荐执行并在执行记录注明）

| # | 问题 | 选项与影响面 | 推荐 |
|---|------|--------------|------|
| D-A | P1-1 图边集范围 | v1=spawn+依赖（端点 schema 小、前端简）；v2 增审批/候选边（需 join approval 审计与候选投影，端点与图例复杂度上升，但一张图看全治理链） | **先 v1**，v2 视使用反馈再议 |
| D-B | P1-2 判定通道形态 | 独立 ACP 判定会话（上下文零污染、多一次会话开销）；复用成员工作会话（省资源，但判定 prompt 污染成员上下文、可能带偏后续交付） | **独立判定会话**（正确性优先） |
| D-C | P2-3 形态 | H-4 重放投影（单一事实源、无新表；大历史重放有读放大）；落 SQLite 新表 candidate_board（查询快，但与账本双写易漂移、违背单一事实源风险） | **重放投影**；若日后读放大实测显著，再议物化 |
| D-D | P2-2 开放范围 | 仅成员工具面 / 仅反向 MCP / 两者（均可独立关断） | **两者都接**，MCP 面跟随总闸默认关 |
| D-E | P1-3 巡检窗口与告警 | 窗口 24h（对齐对方）/12h/可配；告警仅 admin 台账读面 vs 叠加房间通知 | **窗口 env 可配默认 24h，告警先只进 admin 读面**（通知面另批） |

---

## 8. 红线与不做清单

- 不建第二套编排/验收/存储体系；图与候选投影均为**读投影**，不落新表、不写第二本账。
- 判定通道不记 token、不记本仓 LLM 用量（外部代理成本纪律）；判定会话权限请求恒 fail-closed。
- nl2sql 总闸语义不变（默认关、403 点名）；只读断言在连接器层强制，不靠提示词自觉。
- 巡检不自动新建源、不改用户配置；单源失败不阻断其余（fail-soft + 汇总可见）。
- 前端可视化组件不做 trace 语义解释（P2-4 契约钉子守护）。

---

## 9. 执行记录

（待实施批填：每批提交号、红灯/绿灯实测、A/B 域与读数、live-verify 证据、偏离说明。）
