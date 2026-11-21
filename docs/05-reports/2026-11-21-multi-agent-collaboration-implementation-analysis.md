# 多 Agent 协作实现路径分析报告

> 日期：2026-11-21 · 性质：代码级实现路径分析（事实源=本仓源码，非设计稿）
> 方法：六路并行逐文件核读（编排核心 / 外部代理接入 / 房间与治理 / 台账可观测 / 工具与权限 / 前端协作面）+ 架构文档交叉核对
> 范围：`neurova/agent/swarm.py` 及 `neurova/agent/` 协作模块族、`neurova/agent/neuacp/`、`neurova/collaboration/`、`neurova/api/endpoints/`（teams/rooms/channels/console/external_agents/acp）、`neurova/core/` 台账与轨迹、`NeurUI/src/` 协作界面
> 文档参照：`docs/01-architecture/04-multi-agent-collaboration.md`（早期设计稿，已标注以代码为准）、`docs/01-architecture/agent-swarm-orchestration.md`
> 配套修复计划：[2026-11-21-multi-agent-collaboration-repair-plan.md](../04-plans/2026-11-21-multi-agent-collaboration-repair-plan.md)

---

## 0. 总览：一套引擎、三个入口簇、两条辅助编排线、一个呈现/裁决面

Neurova 的多 agent 协作不是多套并立系统，而是**以 `SwarmManager` 为唯一编排核心的星型结构**：

```
入口簇                          编排核心                      执行体
──────────────                 ──────────────                ──────────────
① REST /v1/chat(/stream) ─┐                     ┌─ 内置 Agent（chat 管线）
② 房间 @全员/发起协作 ──────┼──▶ SwarmManager ──┼─ 外部编码代理（neuacp/ACP）
③ 渠道 webhook(TG/飞书…) ──┤   (swarm.py:417)   └─ 工作流节点（neurflow）
④ 工具调用(spawn/dispatch)─┘        │
                                    ▼
              治理面：审批链 L0/L1/L2 · 依赖门 · 验收/评审门 · 预算/并发/冷却
              台账面：agent_runs + H-4 事件账本 + span trace + 帧账本 + 协作档案
              呈现面：房间卡片裁决 · ChatPage 浮窗/拓扑 · 帧回放 · 轨迹页
```

两条**辅助编排线**与主链并存但互不接线：Neurflow 画布工作流引擎（静态 DAG 编排，可经 `workflow_as_tool` 反哺为 agent 工具）、进程内 ACP 消息总线（`/api/acp` + `AgentTeam`，协议层预留）。

**贯穿性设计纪律**（多处有注释自证）：

- **单点收口**：状态迁移（`transitionRun`）、邮箱写（`pushParentMail`）、合入判定（`CandidateMergeBoard.mergeCandidate`）、审批裁决（`decideSwarmApproval`）、工具执行（`ToolExecutor.execute`）各只有一个权威函数。
- **零新表复用**：房间持久化复用 SessionRepository、审批单复用 ApprovalManager、团队名册 JSON 单源落盘。
- **fail-open 但留痕**：辅助面（事件镜像、房间投递、outbox、审计）故障不阻断主链，日志/计数可见。
- **不信任外部进程**：能力不声明即拒、帧不脱敏不落盘、审批 fail-closed deny、进程树级回收。

---

## 1. 编排核心：SwarmManager（`neurova/agent/swarm.py`，4027 行）

### 1.1 一次 swarm 运行的完整生命周期

| 阶段 | 入口 | 证据 |
|---|---|---|
| 工具入口 | `ToolExecutor._execute_spawn_subagent` | tool_executor.py:3119（`delegatedModeScope` 保证子代理权限只收窄不升级） |
| 治理闸序列 | `SwarmManager.spawn` | swarm.py:495：task 非空→团队选人→TaskUnit 解析→TASK_TOO_LARGE→深度上限→MAX_ACTIVE_CHILDREN=5→外部成员解析→预算/429 冷却→模型并发帽→派生错峰→类型校验→工具白名单→数据围栏→依赖门（:546-765） |
| 落 run | 构造 `SubAgentRun` 入 `_runs` + RunQueue | swarm.py:767-835（锁内二次核对 active 上限，:801-815） |
| 整队派活 | `dispatchTeam`（command_id 回执幂等） | swarm.py:908；`_dispatchTeamInner`:957 按名册逐成员 spawn，依赖按名册序号映射，后向引用诚实丢弃记 `dropped_dependencies`（:999-1031）；自动选人 `_resolveTeamMember`:1075 |
| 执行 | `_execute` → `_run_member` | swarm.py:3071/3279：卡死看门狗(:3080)→`transitionRun(running)`→开 trace→台账 `openSubagentRun`(:3303)→`started` 事件→广播→绑定深度/谱系/白名单 ContextVar(:3370-3377)→`renderTaskUnitPrompt`(:3416)→预算闸内 `doMemberChat` |
| 汇报（候选制） | 报告先落候选板 | swarm.py:3461→`_submitResultCandidate`(:1541) |
| 验收门 | `runAcceptanceLoop` | swarm.py:3469；acceptance_gate.py:101（不达标回炉 1 次，再不达标 `failed(acceptance_failed)`；判定器坏→诚实降级 completed+skipped） |
| 评审门 | `runReviewLoop`（`reviewMode=supervisor` opt-in） | swarm.py:3485；review_gate.py:71（进 `in_review` 相位，findings 回炉 1 次；评审器坏→`reviewer_unavailable` 诚实放行） |
| 合入定案 | `_mergeCandidateForRun` → CAS | swarm.py:3498-3505：审批分级→`mergeCandidate` CAS→`transitionRun(completed, cause="candidate_merged")` |
| 终态落账 | finally 统一收口 | swarm.py:3526-3558：`closeSubagentRun`→`terminal` 事件→父闲补投→出队→收 trace→释放外部适配器；随后广播 `subagent_completed`、池归档 `_archive_to_pool`、邮箱回灌 `_notifyParentMail` |
| 结算 | `settleIdleRuns`（闲置 run 逐出内存） | swarm.py:1277；判定单源 run_settlement.py:106/127；小时级 job 注册于 `__init__`（:482-489） |

其他派生入口：协作房间（room_turn_router.py:262,283）、工作流节点（neurflow/builtin.py:1235）、fork（neuacp/adapter_surface.py:265）、blocked 放行 `_launchRun`（swarm.py:1784）、续跑 `resumeFinishedRun`（swarm.py:2279）。

### 1.2 运行状态机

- 状态词与迁移表唯一出处 `swarm_support.py:36-66`：`pending→{running,failed}`；`running→{in_review,completed,failed}`；`in_review→{running,completed,failed}`；两终态无出边。
- 唯一迁移收口 `transitionRun`（swarm_support.py:157）：非法迁移抛 `IllegalRunStatusTransition`，同态重申幂等；终态写 `terminal_quality`（strong/weak/none，:122）；每次迁移落 `status_changed` 事件（含 lineage 谱系）。
- 崩溃恢复双层、**只收敛不复活**：台账层 `reconcile_at_startup`（agent_run_store.py:554，running→failed(process_died)，queued→cancelled(server_restart)，parked 保留等人续跑）+ 账本层 `replayRunTailStatus`/`reconcileRunFromEvents`（swarm_support.py:205/223、swarm.py:1407，账本末态校正内存，漂移落 `status_corrected`，刻意不走 transitionRun 因重启期可能存在迁移表不可达跳变）。
- 消费纪律：`_depSatisfied`（swarm.py:1739）把 weak/none 终态判为不合格输入；`pendingBackgroundForSession`（:1439）给 loop 主出口做「假完成」核账。

### 1.3 候选制与 CAS 合入

- `CandidateReport`（candidate_merge.py:58）：content + `artifactKeys`（产物主张键，由 `artifactOwnership` 自由文本切分）+ `baseRevision` + status + conflictWith。
- member 报告必先落候选；同 artifactKey 且同 baseRevision 的在途候选**互相标冲突、双保留**并升级人工（candidate_merge.py:246、swarm.py:1561-1572）。
- CAS 合入 `mergeCandidate`（candidate_merge.py:182）：`baseRevision != 当前 revision` 即抛 `CandidateConflictError`、候选保留不覆盖；一致则 revision+1 置 accepted。冲突/失败经 `_mergeCandidateForRun`（swarm.py:1598）转 `merge_conflict/merge_failed` 并使 run 判 failed（结果未入集成）。
- 合入审批分级读 `NEUROVA_SWARM_MERGE_APPROVAL_LEVEL`（默认 L0，定义 swarm.py:150）。
- 房间直处置 `applyRoomCandidateAction`（swarm.py:1679，intercept=否决 / merge=CAS 合入）。
- 重启后候选板读面：`candidate_projection.projectCandidateBoard`（candidate_projection.py:89）从 H-4 事件同构重放（不落新表，判定权仍在内存板；投影不含正文 content，`integrationReport` 内存板空时兜底并标注 replay 来源）。

### 1.4 依赖门控

spawn 内依赖只能指向已存在 run（结构性防环，swarm.py:698-765）；未知→`DEPENDENCY_UNKNOWN`、重复→`DEPENDENCY_DUPLICATED`、前置已终态但不合格→`DEPENDENCY_FAILED` 即时拒绝（避免永久 blocked）；未满足→登记 `_blocked`（不占派生槽，:722-749）。终态结算 `_settleDependencies`（:1755）：按 `_depSatisfied`（=completed + 终态强可信 + 验收未判不达标，:1739）放行 `_promoteBlockedIfReady`（:1771）或连锁 `_failBlocked`（:1854）。

### 1.5 父代理对子代理的控制

- **取消** `cancel_subagent`→`cancelRun`（swarm.py:1905，command_id 幂等）：blocked 件直接判 failed 落账；活跃件 `call_soon_threadsafe(task.cancel)`（先挂 `_finalizeCancelled` 兜底回调防竞态丢终态，:2023-2025）；外部成员经 `_cancelExternalMember`（:2034）传导进外部进程（ACP `session/cancel` / v2 `$/cancel_request`）。CancelledError 在 `_run_member` 落 `failed(subagent_cancelled)` 并保留部分报告（:3507-3519）。前台无任务句柄的 run 诚实报「不可单独叫停」(:1994-1997)。
- **改需求/续跑** `continue_subagent`→`updateSubagent`（swarm.py:2118，回执幂等）四模式：`steer`（默认，经 `NeuacpMemberSurface.steer` push 进 SteerQueue，成员下一工具轮可见——成员不再调工具则送不到，诚实提示可改 restart）；`restart`（先取消再重派）；`resume`（仅终态）；`fork`（经收敛面派生新分支，原 run 不动）。
- **续跑链** `resumeFinishedRun`（swarm.py:2279）：跨租户红线先判（:2311-2345，非 admin 跨租户按「未找到」同形拒绝、admin 豁免落 `resume_cross_tenant_admin` 事件）→ 按 spawn 时刻执行体快照 vs 名册现值做五结果决策（reuse / switch_model_in_session / restart_and_resume / create_with_handoff / reject，:2351-2411）→ 旧任务书+旧产出经 `_buildResumeHandoff`（:2631）物化成 ContextHandoff 工件（token 预算 `_handoffTokenCap`:314，失败诚实降级不静默截断）→ 以 `reuse_member_session_id`+`resumed_from` 重入 spawn（:2465-2483）。

### 1.6 TaskUnit（任务书）

结构（task_unit.py:22）：`goal`（必填）/`expectedResult`/`acceptanceCriteria`（验收 rubric）/`requiredInputs`/`artifactOwnership`（产物主张键，喂候选制）/`reviewMode`（none|supervisor）/`dependencies`/`untrustedPayload`（渲染时 `fenceUntrustedPayload` 隔离，:120-123）。流转：spawn 解析（swarm.py:571，非法→`TASK_UNIT_INVALID` 结构化拒绝）→ 冻结进 `run.task_unit`（:780）→ member 提示词分节渲染（:3416）→ 验收门/评审门/依赖门/候选键各自消费对应字段。

---

## 2. 父子通信机制

### 2.1 邮箱（唯一写点，三层可靠性）

`SwarmManager.pushParentMail`（swarm.py:3827）是全仓唯一邮箱写点（钉子注释见 :3828 与 approval_chain.py:127）：

1. `MailOutbox.recordIntent`（mail_outbox.py:110，SQLite 持久意图）；
2. `DeliveryLedger.record`（delegated_delivery.py:65，投递单 pending→claimed→acknowledged）；
3. `get_agent_mailbox().push(session_id, envelope, priority, message_id)`（mailbox.py:67，messageId 幂等去重）。

成功后 `markDelivered` 销 outbox + `claim` 投递单；崩溃恢复 `reconcileSwarmRunsAtStartup` → outbox 对账重投（swarm_support.py:285），靠 messageId 幂等**宁重不丢**。消费侧在 agent loop 工具轮间隙 `lease`（按优先级降序 + 至少一次投递）→ `persistModelVisibleAnnouncement` 落盘 → `acknowledge`（loops/base.py:973-1009）；lease 超 TTL 未 ack 自动回收重投（mailbox.py:184-201）。信封只带元数据 + transcript 指针，正文走 spawn 返回值直传与 member 会话落盘两条路。

### 2.2 Steer 队列

`core/steer_queue.py:22` 作「父→子」插话通道，loop 在工具轮间隙 drain（loops/base.py:952-964）——与邮箱（子→父）方向互补。

### 2.3 房间黑板与记忆作用域

不新造共享变量区：run 带房间时 member 记忆按 `room:<room_id>` 作用域读写（`memberChatScope` swarm.py:229，注入 `spawn_metadata["chat_scope"]`）。作用域语义单源 `collaboration/memory_scope.py`：协作房间/蜂群 run 轮读 `{direct, 本作用域}`；渠道外部群**只读本群**（第三方在场不泄露个人记忆）；单聊仅 `direct`。跨成员共享面 = 房间转录（`build_room_history` 注入，room_turn_router.py:115-147）+ 房间作用域记忆。

---

## 3. 入口簇：从用户动作到编排引擎的全部路径

| 入口 | 路径 | 编排触发点 |
|---|---|---|
| REST `/v1/chat`(/stream) | chat.py:294/486 → ChatPipeline（agent_core.py:933 装配/:1754 执行）→ 工具循环 | `spawn_subagent`（tool_executor.py:3119→swarm.spawn）、`dispatch_team`（:3195→swarm.dispatchTeam:908） |
| 房间 @全员 | collaboration_room_api.py:128 → `RoomTurnRouter.handle_user_message`（room_turn_router.py:181） | `isCollaborationTrigger`（@中≥2 且覆盖全部成员，:32-42）→ `orchestrateRoomCollaboration`（:202-328：人类群主跳过、主执行者=房间默认应答者或首成员、支援成员 `dependencies=[leadRunId]` 挂依赖门、`composeRoomCollabBrief`（:45-79）拼统一任务书含近 10 轮房间上下文、预算落 `runtime_budget_sec`、发起事实以 `kind=swarm_collab` 系统消息上墙） |
| 房间「发起协作」端点 | POST `/rooms/{id}/collaboration`（collaboration_room_api.py:154-180） | 同上，可带 `budget_seconds/max_members` |
| 渠道 webhook | channels.py:337 统一入口 → ChannelManager 分发（manager.py:765-818 按 priority 遍历 handler 链）→ ChannelRouter（指挥资格 :176-184、群聊 require_mention :185-189、群领导租约选举 :263-278→group_leadership.py:40-60，默认关 fail-open）→ `agent.chat`（channel_router.py:380） | 与 REST 同一工具循环 |
| MCP 面 | mcp_ontology_server.py:857-866 把 `dispatch_team` 映射到原生工具同一执行体 | 与主代理同管道 |

---

## 4. 团队与外部编码代理（neuacp/ACP）

### 4.1 团队模型

`team.py`（AgentTeam，177 行）是基于 ACP 消息协议的多角色编排抽象（成员=角色+handler，`orchestrate` :88-174 按步骤序列发 TASK_ASSIGNMENT，单步失败不中断，共享 trace_id）——**不接 SwarmManager 治理面**，生产主链在 SwarmManager。角色词表 `agent/templates/collaboration_template.py:31-42`（coordinator/reviewer/author/…），预设模板 4 套（preset_templates.py:394）。

`teams_api.py`（481 行，挂 `/v1/teams`）：CRUD + 成员管理（批量+职责+角色+外部执行体）+ `prompt-context`；成员结构 `members_detail=[{user_id,name,role,prompt,joined_at,executor?}]`；合法角色=FE 三元+AgentRole 全集（:110-120）；租户隔离：读同租户、写同租户且属主/admin（:168-188）。审批内部面：`registerTeamProposal`/`createAgentProposedTeam`（唯一写点，origin=agent_proposed）/`applyTeamProposalDecision`（两裁决入口共用的回灌单源）/`getTeamRoster`（蜂群选人只读单源）。

### 4.2 neuacp 分层架构

`executor.py`（协议：start/prompt/cancel/close）← `acp_client.py`（subprocess.Popen 拉起 + 换行分隔 JSON-RPC 2.0 帧收发 + initialize 整数版本协商（不兼容即 terminate）+ 按 id 配对请求 + agent→client 方向请求处理器 + fail-closed（坏帧/超限/EOF→_failClosed））← `acp_executor.py`（会话执行体，池优先、池故障 fail-open 直启；v1 `session/new`+`session/prompt`，v2 经 codec）← `acp_member.py`（`NeuacpMemberAdapter` 包成 swarm 成员鸭子面：chat/bindRun/cancel/close + 工具镜像 + 审批钩子）← `swarm._resolveExternalMember`（装配点，swarm.py:2922-3020）。

配套：`catalog.py`（能力/预设/探测单源）、`registry.py`（官方目录并入，预设优先，失败 stale 降级）、`adapter_surface.py`（steer/snapshot/handoff/rollback/fork/switchModel 方法级收敛面 + 能力闸）、`process_pool.py`、`process_governance.py`（超时矩阵/进程组树级回收/重试预算/失败诚实分类）、`codec_v2.py`（ACP v2 编解码）、`scripted_executor.py`（内核级同构测试桩）、`frame_log.py`+`redaction.py`（帧账本与脱敏）、`credential_gate.py`（凭据轮换期拒绝新会话）、`child_env.py`（子进程环境白名单）、`ssh_transport.py`（远程传输）。

### 4.3 生命周期与进程池

配置期：`POST /teams/{id}/members` 携带 `NeuacpExecutorSpec`（teams_api.py:66-80），仅平台 admin 可配（:396-397），`refuseExecutorSpec` 违规 422（:403-405）。派活期闸序列（swarm.py:2912-3013）：总开关 `NEUROVA_EXTERNAL_AGENTS_ENABLED`→租户相等（admin 豁免留审计）→能力校验→构造执行体→`applyRemoteTransport`→挂池。退出：run 终态 `_releaseExternalAdapter`（swarm.py:3051-3068、3551-3558）→池 release 归还或 `terminateProcessGroup` 树级回收（Windows taskkill /T /F、POSIX killpg 先 SIGTERM 后 SIGKILL、兜底 proc.kill）。

`NeuacpProcessPool`：池键 `(tenant, tool, command, cwd, transport, remote)` 六元组、**租户段固定首位**（process_pool.py:31-32、59-78）；全局并发上限 `NEUROVA_EXTERNAL_AGENTS_MAX_PROCS` 默认 4、空闲回收默认 600s；acquire 复用同键空闲件→占名额锁外建→到顶排队。

### 4.4 能力声明双闸 + 前端预筛（三道闸）

能力八维单源 `BOOLEAN_CAPABILITY_DIMS`（streaming/resume/session_reuse/handoff_inject/model_switch_in_session/conversation_rollback/steer/fork，catalog.py:37-46）。闸一配置期 422；闸二派活期同一函数再验（"refused before anything opens"，swarm.py:2970-2979）；闸三前端表单从 catalog 读能力集、切换工具即回落（选择期拦截，不等提交 422）。运行期 `capabilitiesFor` 是 run 能力档单源，五结果决策 `decideProviderTransition`（catalog.py:394-432）纯函数消费。

### 4.5 审批报价-应答映射

外部代理发 ACP `session/request_permission` → 泵线程同步裁决钩子 `_approvalPermissionAsker`（acp_member.py:188-231，`run_coroutine_threadsafe` 桥回异步审批链，同步等裁决，失败 fail-closed deny）→ `requestRunApproval` → 房间/父邮箱审批卡 → `decideSwarmApproval` 裁决 → 应答映射回 ACP（v1 `{"outcome":{"choice":"allow"|"deny"}}`；v2 经 `codec.permissionResponse` 映射，匹配不到回 `cancelled`，绝不等于放行）。分级映射 `acpActionLevel`（acp_member.py:40-48）：read/search/fetch/think→L0，其余→L1；链内危险命令再升 L1。

### 4.6 帧账本与脱敏

`<数据根>/swarm_runs/<subagent_id>.frames.jsonl`（frame_log.py:39-46），五键 `{seq, subagent_id, direction, frame, lineage, occurred_at}`，seq 按文件单调（`_SEQ_CACHE`+回扫描续起）；**写盘前必经 `redactFrame`**（结构级字段名闸 + 值级复用安全单源 `sanitizeSensitive`，redaction.py）；保真纪律：不合成、不推断、超限/坏帧不入账、出站帧恒早于应答入帧、每进程代际只记一条 observed/exited。读面：`GET /external-agents/runs/{id}/frames?after_seq`（admin 门 + 租户线索比对）。

### 4.7 租户隔离红线

JWT 部门根→tenant_id claim（auth.py:307-326）→运行期单源 `currentUserTenantId()`。校验点：teams 读写闸同租户（跨租户 404 不泄露存在性）、spawn 发起者租户==团队租户（admin 豁免留审计）、run.tenant_id spawn 时刻钉死、续跑双比对、帧读面租户线索比对、审批裁决人租户==审批单租户。进程池键租户首位；**API-key 身份恒 default 且无 admin 角色，进不了外部成员配置面**（teams 路由 JWT-only + admin 门双保险）；子进程注入 HMAC run 凭据 `NEUROVA_RUN_CREDENTIAL`（run+租户+exp 绑定，缺参 fail-closed 不签发，child_env.py:53-62）。

### 4.8 SSH 远程与子进程环境

`resolveRemoteCommand` 产出 `ssh -o BatchMode=yes … -- <env前缀> <原命令>`（ssh_transport.py:43-107），缺参/port 非法/key_ref 解析不到一律 fail-closed；凭据经 `remote_env` 显式走远端命令面并 shlex.quote；key_ref 只透引用名。子进程环境**白名单拷贝制**（child_env.py:10-28）：只带 PATH/LANG/系统目录等基线键，宿主代理变量（HTTP_PROXY 等）因不在白名单天然被排除；`PYTHONIOENCODING=utf-8` 双头钉；run 凭据后写覆盖不可被 env_extra 覆盖。

---

## 5. 审批与治理（人在环）

- **分级**：L0（自动放行留痕）/ L1（interactive 模式投父邮箱+房间等裁决，auto_approve 放行）/ L2（强制人工，任何模式不放行）。声明只升不降，命中危险命令检测 L0 至少升 L1（approval_chain.py:87-102）。
- **请求主链** `requestRunApproval`（approval_chain.py:650-803）：审批单进既有 ApprovalManager（不建第二套存储）→ 分级分流 → **D1 记忆式批准**（会话档 `acceptForSession` 优先于团队档 `acceptAlways`、`grantCoversLevel` 只降不升、**L2 永不记忆式放行**，:331-592）→ 需人裁时投父邮箱（`pushParentMail` 唯一写点，:124-137）+ 房间上墙 `notifyRoomApproval`（:766→1020-1058）→ 挂 `approval_relay` waiter 等裁决（默认预算 300s，:53-54）。
- **裁决单源** `decideSwarmApproval`（:833-901）：只认 source=="swarm" 的单、幂等、人裁通道校验裁决人租户（admin 查 users 表，:869-879）。两个回灌口：`decide_subagent_approval` 工具（tool_executor.py:2785-2788）与房间裁决端点 `POST /rooms/{id}/approvals/{rid}/decide`（collaboration_room_api.py:216-220）。
- **回灌项目治理**：裁决端点 approve 后依次 `applyTeamProposalDecision`（团队沉淀）+ `applyProjectGovernanceDecision`（带 `decidedByChannel="room"`，tool_executor.py:87-126）；工具路径同构（decidedByChannel="parent_agent"）。治理回灌只动登记过的快照（`_pendingProjectGovernance`）。
- **房间卡片族**：`publishRoomSystemMessage`（room_bus.py:79-110，零新表零新协议）承载审批卡/升级卡/候选卡三类；进程重启凭房间历史补建 pending 索引（`_syncRoomRegistryFromHistory`，approval_chain.py:1115-1142）。
- **审计**：请求/决定成对落 `neurova.security.audit_logger`（`_emitApprovalAudit`，:168-258），decide 记 `decided_by` 与 `decided_by_channel`，fail-open 但计数可见。
- **判定权口径**：平台 admin 或房间群主（project.owner_id）；房间自由文本路径 `_canDecideInRoom`（:973-991）与显式端点 `_require_room_decisioner`（collaboration_room_api.py:76-82）同一口径。

---

## 6. 工具面与权限边界

### 6.1 协作工具清单（16 原生 + 2 组 MCP 壳）

- 蜂群 10：`spawn_subagent` / `subagent_status` / `list_agents` / `escalate`（仅子代理运行内可用） / `submit_result`（仅子代理运行内可用） / `continue_subagent` / `cancel_subagent` / `rollback_subagent` / `request_approval` / `decide_subagent_approval`；编排 1：`orchestrate_tools`（显式步骤表、层内并行/依赖按序）。
- 团队 3：`list_teams` / `dispatch_team` / `propose_team`（**agent 沉淀团队必须过 L1 人审**，不得自行立队）。
- 项目 4：`project_create`（public 直接拒绝留给人、team 可见性走 L1 审批、强制审计+预算入账） / `project_list` / `project_detail` / `room_post`（成员判据 fail-closed + 滑动窗口限频 + 注入特征扫描只标记）。
- 目录：`tools/catalog.py` 三投影层（schema/权限/help）+ `contracts/tool_catalog.json` 快照（139 工具）+ `scripts/check_tool_catalog.py` CI diff 守卫。

### 6.2 单管道（真实收口，旁路已排查）

`ToolExecutor.execute`（tool_executor.py:1435）→ `executeWithJournal`（core/tool_call_journal.py:338；**外部写类工具先记账再执行**，幂等键 sha256(工具名+规范化参数+user:session)，unknown 结果封锁重放换 exactly-once）→ `_execute_single_tool`（:1500，**成员门：先于治理、不可 bypass**）→ PreToolUse hooks + tool_call_start span → `_execute_single_tool_inner`（:1626：参数守卫→arg 校验→MCP 持久授权免审→单调守卫（skip_governance 也不跳，:1723）→治理预检四级裁决（allow/deny/ask/sandbox，:1741）→元认知门→per-tool 超时+转后台）→ `_execute_tool_core`（:1854 四级回退链：workflow→builtin 分派表→skill（服务端注入身份）→MCP router）。

旁路排查结论：原生 function-calling 链经 `native_tool_dispatch` 改道进咽喉；审批带外重放跳治理但保留成员门+单调守卫+`hasApprovalWaiter` 防双跑；CUA MCP 面注释明确「不复制实现、不绕治理」；唯一例外是无 agent 兜底直调治理引擎（api/endpoints/tool_layers.py:608-618，评测场景，ASK/SANDBOX 一律按拒绝处理，只朝保守偏）。

### 6.3 MAIN_AGENT_ONLY_TOOLS 四层防线

声明单源 12 工具（builtin_tools.py:2544）→ ① 派生期白名单剔除（`computeSubagentToolAllowlist`，general=全量−主代理专属−桌面输入族+借用 MCP 快照；explore=只读集不借 MCP，swarm.py:197-226）→ ② spawn 时冻结进 `run.tool_allowlist`（:679-682）、执行前 `set_subagent_tool_allowlist` 绑定 ContextVar、finally 复位 → ③ 执行咽喉结构化拒绝（白名单外拒 `subagent_tool_not_allowed` + 即使白名单快照缺失命中声明集也拒，纵深防御，tool_executor.py:1509-1534）→ ④ MCP 面按「调用方是否正以蜂群成员身份活动」（读 `SwarmManager.list_active` 单源）再拦截（mcp_ontology_server.py:824-832）。反向 role 门：`escalate`/`submit_result`/`request_approval` 仅子代理运行内可用（getRunByMemberSession 判定）——形成「子代理发起、主代理裁决」闭环，杜绝自己批自己。

### 6.4 MCP 对外暴露

只读面 `/v1/mcp/agent-tools`（mcp_agent_tools_server.py：team_list/knowledge_search/memory_search/data_query 四件，全 `readOnlyHint=True`，输出三层有界（单文本 2000 字符/单工具 20 条/整体 200k），鉴权 X-Service-Token / X-API-Key / Bearer JWT 三选一 fail-closed 401，GET 显式 405）；本体面 `/v1/mcp` 团队工具壳两层、机制单源（壳只做参数适配，`_executeViaNativeTool` 统一「身份→成员剔除→载体解析→executor.execute(nativeName)」转交原生管道，描述文案取原生 schema 防漂移）。

### 6.5 工具层租户/属主校验点

`list_teams` 传 `currentUserTenantId()`；`project_list/detail` 复用 `collaboration_isolation._can_access_project`；`room_post` 成员判据 fail-closed；`memory_search` 逐 agent `can_access_agent`；REST `/tools/execute` `_executeOwnershipGate`（stdio MCP 工具仅 admin、user 源工具仅属主/admin）；Skill 路径身份服务端注入（防 LLM 参数伪造）。

---

## 7. 运行台账与可观测性

### 7.1 八类持久面

| 面 | 载体 | 关键写入点 |
|---|---|---|
| `agent_runs` 台账 | SQLite（v2-v6 迁移链：park/subagent_id/parent_session_id/trace_id/project_id/team_id/tenant_id 列） | agent_run_store.py（intake/claim_next/heartbeat/finish/park/takeForResume/reconcile_at_startup） |
| H-4 run 事件账本 | `<数据根>/swarm_runs/<subagentId>.events.jsonl`（一手事实源） | swarm_event_log.py:83-109（全局锁内追加，seq 单调） |
| `swarm_events` 全局事件库 | SQLite（全局 seq + after_seq 重放 + pruned-through + 快照降级） | swarm_event_store.py；镜像入口 `swarm.py:1240-1243`（fail-open） |
| neuacp 帧账本 | `<数据根>/swarm_runs/<subagentId>.frames.jsonl` | frame_log.py:49-79（写前必经 redactFrame） |
| span 轨迹 | `<数据根>/trajectories/`（索引 index.json） | trace_recorder.py（end_trace 自动存档） |
| 请求归档 | `<数据根>/request_archives/<sessionId>.jsonl`（10MB 滚动） | request_archive.py:327-384（后台单写线程） |
| member 会话 + 压缩时间线 | 会话 JSONL + 附属时间线 | 复用 SessionManager，不建第二套管线 |
| usage/cost/审计/outbox/tool_call_journal | 各 SQLite | multi_model_client.py:949-960 / cost_tracking.py:172-218 / audit_logger / mail_outbox / tool_call_journal |

### 7.2 H-4 事件族（约 25 种，单点落账）

写侧单点 `SwarmManager._logRunEvent`（swarm.py:1217-1248，JSONL 先落 + 全局库镜像 fail-open，正文只留摘要，`event_id`/`causation_id` 串因果链 + `lineage` 谱系）。事件族：

- 生命周期：spawned / started / member_chunk（只记 chunk_type+length）/ terminal / cancelled / stalled / status_changed / status_corrected / auto_settled
- 工具审批镜像：tool_call（外部成员工具调用，先脱敏）/ permission_decided（payload 五键 action/approved/pending/denied/reason）
- 候选族 7 种：candidate_submitted / conflict_flagged / revise_required / conflict / merge_rejected / merged / rejected（词表单源 candidate_projection.py:43-51）
- 治理交接族：escalated / result_submitted / rollback(/rejected) / forked(/rejected) / update_injected / resume_decision / resume_cross_tenant_admin / context_transfer(/failed)

读侧：`GET /v1/console/chat/subagents/{id}/events`、启动收敛 `replayRunTailStatus`、候选板重放投影、图投影、协作档案。

### 7.3 trace 三级串联

父请求 ContextVar trace_id（trace_context.py:10-25）→ spawn 时冻结 `parent_trace_id`（只作关联标，不挂父轨迹树）→ member 自开轨迹 `trace_id`（`_startMemberTrace` swarm.py:3169-3216，metadata 带谱系，`start_span("swarm_member_run")` 挂本轨迹根成树）→ `run.trace_id` 写进台账行（排查时从台账行直达 span 树）。外部成员工具镜像同时写 H-4 账本与轨迹事件。OTel 桥（otel_bridge.py:91）投影不另接导出。

### 7.4 协作档案（S12）与图投影

`GET /projects/{id}/collaboration`（projects_api.py:589-601）五类记录**读时 join**（runs 按 project_id 列精确匹配 + 逐 subagent 事件时间线 + 候选记录 + 审计成对 + 房间消息 + 请求归档摘要），不建第二本账；项目 active→archived 迁移时封卷留底写 `metadata["collaborationSummary"]`（重复归档不重算）。`buildSwarmGraph`（swarm_graph_projection.py:95-285）纯折叠产 render-ready `{nodes, edges, meta}`：节点 run/approval/candidate 三类、边 spawn/dependency/approval/candidate 四类，meta 诚实标注 truncated/candidates_incomplete/danglingEdges；契约由 `tests/unit/api/test_swarm_graph_contract.py` 钉红。

### 7.5 usage 归因（两个记账主体，裁定结果非漂移）

用量明细行：`user_id=请求发送者`（缺省 anonymous）、`agent_id=执行 agent`——member 执行时 `_bindMemberCostContext`（swarm.py:3256-3266）把成本上下文覆写为 member agent（属主）+ member_session_id + trace_id，finally 按前值还原。运行台账行：`_subagentAccountingUserId`（:3244-3253）**agent 属主优先**（注释明确「跟着点击者走＝越权面」），缺省退发送者。成本金额另经 `record_llm_cost` 触发预算/告警。

---

## 8. 辅助编排线（与主链并存、互不接线）

1. **Neurflow 画布工作流引擎**（`collaboration/neurflow/execution_engine.py`）：DAG 分层并行（Kahn 分层 + gather，并发上限 `NEUROVA_NEURFLOW_MAX_CONCURRENT_NODES` 默认 8）、condition 真分支（边活跃性不动点传播）、Loop 真循环（回边豁免 `target_handle=="loop_body"`、安全 DSL `safe_eval`、max_iterations≤1000）、幂等节点才准重试（默认拒绝）、checkpoint/事件记录；8+ 领域模板与电商 external_clients；已发布工作流经 `workflow_as_tool.py` 变成 `workflow:{id}` 工具（参数来自 start 节点 fields，天然带输入校验）反哺 agent 工具面；画布桥接 `collaboration/canvas_bridge.py`。
2. **进程内 ACP 消息总线**（`protocols/acp_runtime.py` + `protocols/agent_adapter.py` + `api/endpoints/acp_api.py` 挂 `/api/acp`）：把运行时 Agent 包装成 ACP handler（能力声明 `["chat","status"]`，协作邀请显式拒绝 `COLLABORATION_REJECT` 而非落未知 action 错误），提供 `/send`、`/request`、`/teams/orchestrate`、Supervisor 扇出端点。注意与 neuacp（外部代理接入）撞名但无关。
3. **Supervisor 扇出**（`agent/supervisor/orchestrator.py`）：WorkerBus（进程内/MQTT）扇出、task_id 幂等（内存 cache + SQLite `SupervisorTaskLedger`）、单 worker 失败隔离 + 重试、RRF 融合聚合——与 SwarmManager 两条独立编排线，无共享状态。

---

## 9. 前端协作面（NeurUI，Vue3）

两条主线：**团队/房间线** TeamPage（团队 CRUD + 成员名册 + admin 外部代理池状态卡）→ CollaborationPage（会话列表 + dossier 档案面板）→ CollaborationRoomPage（消息流 + @提及 + 审批/升级/候选卡片裁决 + 发起协作表单 + 协作进度条）；**运行观测线** ChatPage 经 WS `subagent_*` 事件驱动 SubAgentPanel 浮窗（团队徽标/谱系徽标/质量徽标/H-4 事件时间线）+ SwarmFlowPanel 拓扑（vue-flow）+ ExternalAgentFramesPage 帧回放（seq 游标翻页）+ AgentTrajectory/Trace 轨迹页。

- 实时性单通道：`/api/v1/sync/ws/{session_id}`（useSessionSync：JWT query、指数退避重连、seq 跳号 gap 自愈 + `sync_resume` 定向重放 + `sync_hello` 纪元重置）。
- 审批提交：房间审批卡→`POST /rooms/{id}/approvals/{rid}/decide`；候选→`/intercept`|`/merge`；升级卡只读（无前端提交口）。
- neuacp 表单：目录能力预筛（选择期回落）、transport stdio/ssh 切换、凭据只收键名（env_keys tags / key_ref 引用名）、permission_mode auto 仅 admin + 二次确认、`/external-agents/test` 握手预检。
- i18n：团队/协作域约 220+ 键 × 11 语言（collab≈126 / neuacp≈71 / swarmFlow≈17 / trajectory≈10）。
- 页面↔端点映射：详见 `NeurUI/src/api/modules/`（teams.ts / neuacp.ts / collaborationRoom.ts / collaboration.ts / console.ts / trace.ts / audit.ts）。

---

## 10. 全景数据流（一条蜂群任务的生命周期）

以「主代理派两个子代理协作、其中一个是外部编码代理」为例：

1. 用户经 `/v1/chat` 下达 → ChatPipeline 工具循环 → 主代理调 `spawn_subagent`（或 `dispatch_team`）；
2. `spawn` 过九道治理闸 → 落 `SubAgentRun` → 台账 intake→claim → `spawned` 事件；
3. `_run_member`：`transitionRun(running)` → 开 member trace → `openSubagentRun` → 广播 `subagent_started`（房间/聊天页浮窗亮起）→ 绑定白名单/深度/谱系 ContextVar → 渲染 TaskUnit 任务书 → 预算闸内跑 member 会话；
4. 外部成员：池取件/直启 → initialize 握手 → `session/prompt` → 流式 chunk 经 emitter 回传浮窗逐 token 上屏 → 工具调用脱敏镜像进帧账本+span → 权限请求桥回审批链（房间出审批卡，群主裁决）；
5. 完成：报告落候选板 → 验收门（可回炉一次）→ 评审门（opt-in）→ 审批分级 → CAS 合入 → `transitionRun(completed, candidate_merged)`；
6. 终态收口：`closeSubagentRun` → `terminal` 事件 → 广播 `subagent_completed` → 邮箱回灌主代理（outbox 三层可靠）→ 池归档报告 → 依赖门结算放行下游 → 闲置后 `settleIdleRuns` 逐出内存；
7. 全程留痕：agent_runs 行 + H-4 JSONL + span 轨迹 + 帧 JSONL + usage 双维记账（发送者×执行 agent）+ 审计成对记录，最终可被协作档案/图投影/轨迹页回放。

---

## 11. 断点与风险清单

### P0 · 语义不一致/权限面

1. **房间自由文本批准不回灌治理**：`handleRoomSwarmReply`（approval_chain.py:1187-1205）只调 `decideSwarmApproval` + 发确认消息，**不调** `applyTeamProposalDecision`/`applyProjectGovernanceDecision`；而显式端点（collaboration_room_api.py:229-251）与 decide 工具（tool_executor.py:2793-2814）都做——群主在房间回「同意」批掉团队沉淀/项目治理单，审批状态变 approved 但数据不落地，同一裁决两种效力。
2. **MCP 身份缺省回落 admin**：`_currentUserFromContext`（mcp_ontology_server.py:110-120）state 读取失败时以 admin 载体执行——对只读四件套无害（仍受单源租户过滤），但本体面 `team_dispatch` 等写壳在身份通道断裂时会被 admin 化执行。
3. **API-key 租户硬编码 default**（mcp_ontology_server.py:78）：API-key 调用方永远落 default 租户，多租户下 API-key 面的租户隔离依赖「default 租户即唯一数据面」这一前提，仅服务令牌/JWT 能带真实租户。
4. **L2 审批通道故障即放行**：`_approveMerge` 审批基础设施抖动时返回 `approval_channel_unavailable` 并放行合入（swarm.py:1674-1677）——「高危必审」语义存在豁免口子（虽有 warning 留痕）。

### P1 · 多副本/持久化缺口

5. **进程内状态在多副本部署下会裂**：候选板 revision（CandidateMergeBoard）、房间审批 pending 索引、room_post 限频窗口、团队待批登记均为单进程内存；账本重放投影只读不判，跨进程合入互不知情。
6. **`swarm_events` 全局事件库读面无生产消费**：写侧镜像已接线（reference-ac A2 卡已落地），但 `replayThrough`/`snapshotStream`/`readStream` 无生产消费者（mobile_ws_ledger 等仅注释「语义同构」）；`pruneCovered`/`markPrunedThrough` 无周期任务驱动，事件库与 JSONL 账本均无限增长。
7. **`/external-agents/status` 端点是空壳**：找 `poolStatus`、池只有 `stats()`，getattr 落空恒返回占位 note（external_agents_api.py:130-140）——管理面看不到真实池水位。
8. **H-4 `lineage` 的 tenant/room 维度只写不读**（读侧只用台账行 project_id 列与事件 parent/depth）；`member_chunk` 事件纯留痕；`NEUROVA_REQUEST_ARCHIVE_FULL` 是无消费的钩子（fullText 恒 False）。

### P2 · 体验/健壮性

9. **泵线程同步等审批阻塞面**：`_approvalPermissionAsker` 在泵线程 `future.result()` 同步等审批，等待期间同进程帧（含流式 chunk）无法派发，人工审批慢时外部代理表现为「卡住」。
10. **池满 acquire 无超时**：`_ensureClient` 调 `pool.acquire` 未传 waitTimeout（acp_executor.py:256），上限占满时新派活最坏等近 10 分钟空闲清扫。
11. **steer 尽力而为**：成员停止调工具即送不到；前台 spawn 不可取消、自动转后台默认关。
12. **成员声明侧未过滤**：`build_tools_for_llm`（orchestrator.py:4159）不读成员白名单，子代理 prompt/tools 仍可能列出主代理专属工具，靠执行期拒绝兜底（安全性无损，浪费 token 且诱导撞门）；**TEAM 可见性是占位实现**（collaboration_isolation.py:1271-1274 对 TEAM 直接 return False，审批通过后非成员仍不可见）。
13. **前端四小项**：升级无闭环（只读卡片）、`getRoomSwarmPending` 已定义未接线（无待审批角标）、审批后本地态不主动重取（依赖 WS 回声）、房间 user_message 去重过宽（连续同文第二条被吞）。
14. **文档/心智**：`team.py` AgentTeam 与 SwarmManager 两套团队抽象并存无接线；`ToolExecutor.execute` docstring 仍写已拆的 ToolEngine 档；`04-multi-agent-collaboration.md` 设计稿与实现脱节（已有状态标注）。

---

## 12. 总体评价

这套多 agent 协作的**治理密度显著高于常见同类实现**——唯一编排核心、五个单点收口（状态/邮箱/合入/裁决/工具执行）、账本先行、成员四层门、外部进程「不信任到帧级脱敏与树级回收」、租户隔离红线成体系。整体架构取向是「内存单例 + 事件账本 + 发现而不裁决」：控制权始终留给主代理与人，机制故障时诚实降级而非误杀。

主要结构性弱点集中在三处：**单进程内存模型 vs 多副本部署**的裂缝、**身份缺省过宽**的两处 fail-open、以及**回灌路径不闭环**一处语义不一致——均属可定位、可逐项收口的债，而非架构性漏洞。逐项修复方案见配套修复计划。
