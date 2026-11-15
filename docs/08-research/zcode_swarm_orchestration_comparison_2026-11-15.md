# ZCode 子代理（蜂群）与任务编排/拆解机制对照——Neurova 差距与可补充项

- 日期：2026-11-15
- 对象：zai-org/ZCode v3.18.2（克隆件 `E:/项目/_external_repos/zai-org-ZCode`，只读）vs 本仓当前代码
- 方法：ZCode 侧逐文件读取 `apps/zcode-cli/packages/core/src/subagent/*`（23 文件）、`runtime/methods/subagent.ts`（1085 行）、`runtime/helpers/tool-allowlist.ts` 等；Neurova 侧读取 `neurova/agent/swarm.py`、`subagent.py`、`sub_session.py` 及规划/工作流面。只陈述两边代码核实到的事实。
- 关联：[ZCode 对照主报告](zcode_vs_neurova_harness_code_comparison_2026-11-14.md)、[工具清单对照](zcode_tool_inventory_comparison_2026-11-15.md)。

---

## 1. ZCode 子代理机制总览

子代理核心是 **Agent 工具**（`Task` 为其 `providerVisible:false` 的兼容别名，`tool/handlers/agent.ts:332`、`tool/compat.ts`）。`agentHandler`（agent.ts:218）把 `subagent_type/description/prompt/run_in_background` 交给 `SubagentPort.launch`；runner 按前后台分流。

**代理类型**：内置 general-purpose（tools `["*"]`，注入 AGENTS.md）与 Explore（只读搜索，`profile.ts:23`），加用户 `.zcode/agents/*.md` profile 归一（`profile.ts:46` `normalizeAgentProfiles`）。Explore 的工具面白名单在 `explore-tools.ts:5`，刻意不含 Write/Edit/ApplyPatch。

**生命周期**（`subagent/runner.ts:187/220/566`）：registry.register → 写 metadata.json（runner.ts:2347）→ 活动看门狗（runner.ts:1407）→ `runAgentToCompletion`（runner.ts:1330，新建 child runtime，runtime/methods/subagent.ts:305）→ `Promise.race`（完成 / 转后台请求 / autoBackground 定时器，runner.ts:362）。

**前台自动转后台**：前台 run 超时或收到转后台请求即脱离父 turn，完成走通知队列回注——父会话不被长任务阻塞。

**失败交接（handback）**：同步子代理失败也回传**部分报告 + agentId + usage**（agent.ts:162、runner.ts:529-559），父模型可 `SendMessage` 续跑该子代理（终态子代理可复活：`resumeTerminalAgentInBackground`，runner.ts:1156，`resumeFromStore:true` 恢复历史），而非从头重试。

**并发与结果回收**：Agent 工具 `concurrentSafe:true`（agent.ts:276）+ ToolScheduler 默认 maxConcurrency 10（`tool/scheduler.ts:44`）——一条消息多个 tool use 并行。后台完成后 `finalizeBackgroundCompletion/Failure`（runner.ts:1725/1812）写 output.txt/task.output/metadata.json，`enqueueBackgroundNotification`（runner.ts:2106）同步入父 command queue（`notified` 去重）。

**停止/取消**：先提交 killed 再 abort（runner.ts:680、1937）；abort guard 防止 child 永不 settle（runner.ts:1494）。

**工具白名单**（子代理工具面收窄）：`resolveSubagentToolAllowlist`（subagent.ts:660）——`*` 时取父工具 + 父白名单内 MCP，**剔除 Agent/Task 派生工具**，强制剔除 EnterPlanMode/ExitPlanMode（`subagent/tool-policy.ts:7`，因子代理无 plan 审批恢复面，会卡死父 turn），强制补 `RespondToCoordinator`（subagent.ts:711）；Explore 再经 `tool-allowlist.ts:114` 收窄。workflow child 结构性禁 CreateWorkflow/AmendWorkflow/SaveWorkflow/ResumeWorkflowRun/ResolveWorkflowQuestion/FillWorkflowHole 及 run 内省工具（`tool-allowlist.ts:30-72`）。

**MCP 借用**：`resolveSubagentMcpAccess`（subagent.ts:727）→ `createBorrowedSubagentMcpAccess`（borrowed-mcp-port.ts:9）：复用父启动快照、禁生命周期变更、scope 过滤、官方 Computer-Use server/tool/skill 一律拒绝（`computer-use-policy.ts:19`）。

**模型继承**：`createInheritedSubagentModelFactory` / `modelSelectionFromActiveModel`（subagent.ts:587/606）——子代理默认继承父 session 模型；off-peak 任务用 offPeak 选择（subagent.ts:117-131）。

**持久记忆**：`persistent-memory.ts:70`，scope 分 user（storageRoot/agent-memory）、project/local（.zcode/agent-memory[-local]），读 MEMORY.md 注入并自动补 Write/Edit 工具（persistent-memory.ts:40）。

**事件镜像**：`mirrorSubagentToolEvent`（tool-event-mirror.ts:38）把 child 工具事件重写 `toolCallId=tool_subagent_<agentId>_<childId>` 投影进父会话——父会话能看到子代理的每一次工具调用。

**交互与协调**：permission 经 `createSubagentInteractionBroker`（subagent-interaction-broker.ts:17）路由到父 session（origin 保留 child 归属）；`coordinator-response.ts:19` 把子代理 `RespondToCoordinator` 入父队列；`enqueueSubagentMessage`（subagent-messages.ts:25）以 `subagent-message` runtime command 插入。

**完成通知与卡死提醒**：completion-notification.ts:31（killed 按 initiator 措辞）；`background-stall.ts:42` 只认模型请求/完成、工具开始/结束（Bash 心跳不算进展），`BackgroundSubagentStallClock`（background-stall.ts:249）首报 15min、指数退避上限 4h，挂于父 runtime registry 订阅（subagent-stall-reminder.ts:15）——**发现而不裁决**：只提醒，由主代理决定停或等。

## 2. ZCode 的任务编排与拆解（三层分工）

| 层 | 工具/机制 | 职责 |
|---|---|---|
| 会话内推进 | TodoRead/TodoWrite（`tool/handlers/todo.ts:25/47`，读写 sessionStore.todos，全量替换并回 summary） | 当前任务的步骤清单与推进 |
| 先设计后批准 | enterPlanMode → sessionModePort（plan-mode.ts:36）；exitPlanMode 要求 plan 态、先 `writeApprovedPlanFile` 落盘再退出（plan-mode.ts:60、214），输出 "Approved Plan" | 只读设计态：探索与方案设计不改世界，用户批准后转执行 |
| 即席并行委派 | Agent/Task 工具（subagent.ts） | 把子任务派给子代理（可多条并行，maxConcurrency 10） |
| 脚本化编排 | dynamic-workflow 工具族（CreateWorkflow/amendWorkflow/evalWorkflowSnippet/listWorkflowRuns/getWorkflowRun/resumeWorkflowRun/resolveWorkflowQuestion/fillWorkflowHole/listSavedWorkflows/saveWorkflow） | 用户点名的脚本化多代理编排：拓扑、world.run 门控、hole 留白待填 |

**DynamicWorkflow 要点**（create-workflow.ts:86）：流程 = 技能门（未加载 dynamic-workflows 技能拒绝，428）→ `analyzeScript` 静态编译分析（workflow-script-analysis.ts:18，单槽缓存）→ **编不过不弹窗直接回诊断**（create-workflow.ts:351）→ 编译过弹 alwaysAsk 确认窗（仅会话级免确认，create-workflow.ts:441）→ `port.submit` 后台跑，返回 backgrounded+runId 并明令"勿用 TaskOutput 轮询"（create-workflow.ts:242）。脚本为 TS + facade（`agent()/ask/files/git/world.run/report/artifact/phase/hole`），strict + ES2022、无 DOM/Node、禁 declare/import/export；analyzer 产出 **site/causality/flow/handoff 四图**与诊断码 9001-9013。`EvalWorkflowSnippet` 同步试跑片段；`ResumeWorkflowRun` 仅 stopped 可恢复且被 scriptHash 钉死（resume-workflow-run.ts:24-31）。

**拆解与汇合**：todo 管会话内推进；plan mode 管"先设计后批准"；Agent 管即席并行委派（fan-out 搜索、独立子任务）；dynamic workflow 管用户点名的脚本化编排。子代理结果经 handback/通知队列/事件镜像三条路汇合回父会话。

## 3. Neurova 现状（对照面）

**子代理运行时**（`neurova/agent/swarm.py`，~960 行）：`spawn`（task/agent_id/session_id/background/origin/stream/initiator_agent/node_id/execution_id）→ 三明治数据层结构化拒绝（任务过大/深度超限/活跃子代理达硬限/预算超支/模型 429 冷却/模型并发达限/派生过快，全部带 code+message+retry_after_ms）→ SubAgentRun（member_session_id 独立会话，P2-9）→ `_run_member`：台账开行 → subagent_started 广播（载荷带 status/origin/depth）→ 深度绑定（set_subagent_depth，member 内递归派生 = depth+1）→ `agent.chat(stream=True, session_id=member_session_id, metadata=spawn_metadata)` 外包 `asyncio.wait_for(运行窗口预算)`（预算单源 = tool_coordinator 的 spawn_subagent 超时，env 可调）→ 流式 emitter → 完成/失败/超时/取消四态收尾（CancelledError 显式处理）→ 释放模型并发槽 → 邮箱终态回灌 → 上下文池归档。

**fan-out 治理闸**：预算（cost_budget 按小时/按模型）、模型 429 冷却、模型并发上限、派生间隔（防惊群）——全部 fail-open、可 kill-switch（NEUROVA_SWARM_GOVERNANCE=off）。

**增强（本批已落）**：`escalate`/`submit_result` 工具（子代理按 member 会话定位活跃运行；升级/结构化结果信封投递发起者会话邮箱；仅子代理运行内可用，参数校验先于上下文校验）。

**编排与拆解**：planning/update_plan（计划工具）、plan_mode 模块、workflow 画布（neurflow：草稿/运行/发布/回滚/修复/批次补偿）、run_scripted_workflow（P3-14：受限脚本 + AST 白名单 + 子进程隔离 + journal 续跑）。

## 4. 逐机制对照

| 机制 | ZCode | Neurova | 差距/优势 |
|---|---|---|---|
| 子代理类型 | 内置 general-purpose + Explore（只读白名单）+ 用户 profile（.zcode/agents/*.md） | 无类型系统；spawn 按既有 agent_id 选实例 | **差距**：缺内置轻量"探索型"子代理与用户自定义 profile |
| 前台自动转后台 | 有（runner.ts:362 race + 定时器） | 无（background 由调用方一次性决定） | **差距**：前台长任务会阻塞父轮直到预算墙 |
| 失败交接/复活 | handback 携部分报告；SendMessage 可复活终态子代理 | 失败仅 error+邮箱终态；无续跑 | **差距**：失败子代理不能续跑 |
| 卡死提醒 | StallClock 15min 起指数退避至 4h，只认真实进展 | 运行窗口硬墙（超时即杀），无渐进提醒 | 各有取舍；Neurova 缺"发现而不裁决"的提醒面 |
| 工具面收窄 | 按父白名单/任务类型结构性禁用（集中一处） | 子代理为完整 Agent，工具面不收窄（靠权限模式+治理闸） | **差距**：子代理拿到全部 119 工具（含破坏性），仅靠模式与审批拦截 |
| MCP 借用 | borrowed-port：复用父快照、禁生命周期变更、scope 过滤、官方 CU 拒绝 | 子代理 MCP 面未按父收窄（待核） | **差距**（待核） |
| 事件镜像 | tool-event-mirror 重写 toolCallId 投影父会话 | 子代理事件流式广播到父会话（emitter） | 基本对齐（实现路线不同） |
| 升级通道 | escalate → coordinator | escalate → 邮箱（本批已落） | **已对齐** |
| 结构化结果 | submitResult | submit_result（本批已落） | **已对齐** |
| 卡死提醒 | StallClock | 无 | **差距** |
| 编排三层 | todo / plan-mode(批准落盘) / dynamic-workflow(脚本+四图+hole) | planning/update_plan / plan_mode / 画布 workflow / run_scripted_workflow(P3-14) | 形态各异、能力相当；ZCode 的 plan 批准落盘与四图分析更细 |
| 运行治理 | 预算/冷却/并发/间隔闸（fail-open） | 同款四闸（fail-open）+ 深度限制 | **对齐**（Neurova 另有深度与运行窗口硬墙） |
| member 会话 | 无独立 member 会话（child runtime） | member_session_id 独立会话（可查询/审计/跨轮恢复） | **Neurova 优势** |
| 结果归档 | handback/通知队列 | 邮箱回灌 + 上下文池归档 | **Neurova 优势**（池归档） |

## 5. 可补充项（按优先级）

| # | 候选 | 说明 | 优先级 |
|---|---|---|---|
| 1 | **子代理工具面收窄** | 按 ZCode 的 resolveSubagentToolAllowlist：子代理工具面 = 父白名单内工具 − 派生工具 ∓ 计划模式工具；Explore 型只读白名单。这是安全实质差距（当前子代理拿全部 119 工具） | **P1** |
| 2 | **内置 Explore 型子代理** | 只读检索型 agent 类型（explore-tools 白名单），供 fan-out 搜索/侦察；与 1 同批 | **P1** |
| 3 | **失败交接与续跑** | 失败子代理回传部分报告；SendMessage 可续跑终态子代理（复活） | **P2** |
| 4 | **前台自动转后台** | 前台 run 超预算即脱离父轮，完成走通知队列 | **P2** |
| 5 | **卡死渐进提醒** | StallClock：只认真实进展、指数退避、发现而不裁决 | **P2** |
| 6 | **计划批准落盘** | plan-mode 的 Approved Plan 文件化（ZCode writeApprovedPlanFile） | **P3** |
| 7 | **脚本分析四图** | run_scripted_workflow 的静态分析产出 site/causality/flow/handoff 图与诊断码（ZCode analyzer） | **P3** |
| 8 | **MCP 借用收窄** | 子代理 MCP = 父快照借用（禁生命周期变更、scope 过滤） | **P3**（先核实现状） |

## 6. Neurova 独有、无需补的

member 独立会话（可查询/审计/跨轮恢复的普通会话，ZCode 用 child runtime 无持久 member 会话）、上下文池归档、深度+运行窗口双硬墙、四闸治理的 kill-switch、mailbox 终态回灌的持久化形态。这些是 Neurova 的审计与恢复优势，保持即可。

## 7. 结论

ZCode 的蜂群在**类型化子代理、工具面收窄、失败交接/复活、前台自动转后台、卡死提醒**五处领先；Neurova 在**member 独立会话、上下文池归档、双硬墙、四闸 kill-switch、升级/结果协议（本批已对齐）**上有自己的形态。最有价值的补齐是 **#1+#2（子代理工具面收窄与 Explore 型）**——它同时是安全实质差距；其余按上表优先级推进。
