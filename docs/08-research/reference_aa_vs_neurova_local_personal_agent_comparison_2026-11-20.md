# 参照系 AA（Linger）代码级研读报告

- 研读对象：https://github.com/simplexai-labs/linger （simplexai-labs/linger，下称 Linger）
- 研读日期：2026-11-20；快照：当日 `git clone --depth 1` 主干
- 本地代码根：`C:/Users/xccoo/.zcode/tmp/linger-src`（下文引用路径均相对该根）
- 研读方式：文档通读（README + docs/ 13 篇）+ 5 路并行源码深读（TeamHub 服务端 / node-services 运行时与记忆 / Computer Daemon 与护栏 / CLI·技能·契约 / Web·Desktop·语音·安装器），关键结论均带 `文件:行号` 锚点并经主会话抽查复核
- 定位声明：本文是**代码级理解报告**，非评分评测；§10 给出与 Neurova 的对照启发

---

## 0. 结论摘要

1. **Linger = 本地优先的个人 AI 代理平台**：服务端（TeamHub, Go）+ 代理运行时与记忆（node-services, Node 26）+ 用户电脑执行面（Computer Daemon, Go）+ Web（React 19）+ Desktop（Electron 壳）+ 语音（LiveKit/Soniox）+ CLI（155 级命令面）。Go 2072 文件、TS/TSX 2280 文件的单体仓（pnpm workspace + 独立 Go 模块）。
2. **最核心的架构决策：不自研代理 LLM 循环**。聊天/任务回合由外部编码代理运行时执行——Codex（app-server JSON-RPC）、Claude Code（stream-json）、Pi（RPC）、Antigravity（ACP），由 node-services 的 RunnerGateway 经 Computer Daemon 的单条出站 WebSocket 派发；本地模型（PolyStrata/llama.cpp，另一仓库）经本地网关喂给这些运行时。node-services 自己只做编排、持久状态投影与后台 LLM 任务。
3. **真相单源在 PostgreSQL**：消息→唤起代理→审批→回话全链路以「业务事实 + room_seq 事件 + 幂等回执」同事务落库；`room_events` 上的约束触发器 + LISTEN/NOTIFY + SSE 只做唤醒提示，另有 30 秒兜底扫描。实时通道全部是 SSE，**服务端没有 WebSocket**。
4. **可靠性纪律贯穿三处一致**：先记账再发送、结果 unknown 不重放（连接器执行、屏幕/浏览器操作 journal、decision 执行器三处同构）；写操作全带 operation ID / invocation hash 幂等键。
5. **记忆检索无向量、无 rerank**：PostgreSQL tsvector（simple + CJK bigram）+ 多改写词法路由 + 时间窗投票 + RRF 融合 + BM25 兜底；LoCoMo 95% 由 `scripts/memory-benchmark` 的工具循环跑出。夜间 Wiki 整理是受控 agent 循环（route→consolidate→meeting→batch，失败二分重跑）。
6. **发现两处文档漂移**（诚实记录）：architecture.md 称 event ledger 为 SQLite（代码实为内存账本，SQLite 用于 Context View）；architecture.md 称 CLI 155 条命令（实测 60+52=112）。

---

## 1. 项目定位与仓库概况

- **一句话**：开源个人代理，"Claude 级大脑跑在你自己的 PC 上"，数据（Wiki/记忆/会话/文件）全部留在本机；云端模型或订阅仅按需接入。
- **仓库形态**：pnpm monorepo（`package.json:12` pnpm@11.7.0，Node ≥26.5）+ Go 多模块（`apps/teamhub`、`apps/computer/local-daemon`、`skills`）。顶层：`apps/`（web、desktop、linger-installer、voice-runtime、node-services、teamhub、teamhub-cli、computer）、`packages/`（document-model、document-files、knowledge-format、local-installation、service-kit）、`contracts/`、`skills/`、`e2e/`、`patches/`。
- **许可与成熟度**：修改版 Apache 2.0（附加条件）；desktop 发布刚到 v0.1.5（2026-11-19），年轻但工程化程度高（契约先行、迁移基线 6761 行、`make check BASE=` 快速门、commitlint、husky）。
- **依赖说明**：`patches/` 打了 4 个补丁——`@hocuspocus/server`、`@livekit/agents`（免每 worker 一个 EOT 推理进程）、`playwright-core`（修 CDP 焦点仿真，保证多代理并行浏览器）、`deepagents@1.12.0`（修虚拟 FS glob 路径）。`deepagents` 由 npm 包 `openwiki@0.4.3`（SimplexAI 自家发布，内含 LangChain/LangGraph/checkpoint-sqlite 全家桶）带入，node-services 仅使用其 `mermaid/validate`、`okf/frontmatter`、`visualize/graph` 三个子模块（`apps/node-services/src/llm-wiki/agent-wiki-backend.ts:7` 等 6 处 import）。

## 2. 总体架构与进程拓扑

权威图示在 `docs/architecture.md`。部署形态两条腿：

**服务器侧（docker-compose 5 服务）**：`postgres`（pgvector 镜像 pg17）、`livekit`、`teamhub`（Go）、`teamhub-migrate`（goose）、`node-services`（单进程五角色）、`web`（静态 SPA）。

**用户电脑侧**：`linger-computer-daemon`（Go 常驻进程，Electron 桌面应用把它作为子进程拉起），**整条链路只有一条出站 WebSocket**（`apps/computer/local-daemon/internal/linger/transport/gateway.go:40-83`），本机不开任何网络监听端口；本地控制面用 Unix socket / 具名管道（owner-only）。

数据流三干线（`docs/architecture.md:13-20` 表格）：

```
Rooms/Chat ──SSE 唤醒──▶ node-services(Agent Service) ──WS run.start──▶ Computer Daemon ──▶ Codex/Claude/Pi/Antigravity
    ▲                            │                                           │
    └────── TeamHub REST/SSE ◀───┘◀──── 事件流(operation.event) ──────────────┘
```

- Runtime 直连 LLM Gateway（本地模型或 BYOK），**不经** Computer Daemon 转发模型流量。
- 后台 LLM 任务（记忆/Wiki/评审）走 `model.invoke` 帧到用户电脑上的 Runtime 执行（`apps/node-services/src/runtime-model-call.ts:585-646`）。

## 3. TeamHub：Go 服务端（apps/teamhub）

技术栈：Go 1.26 · Gin · pgx v5 · River v0.49（任务队列）· goose 迁移 · sqlc。**无 WebSocket**（gorilla 仅间接依赖），实时全部 SSE + PostgreSQL LISTEN/NOTIFY。

### 3.1 装配与路由

- 入口 `cmd/teamhub/main.go:13-39` → `app.New`（`internal/app/app.go:281-313`）：校验配置 → 连库（池 max 16）→ 核心服务（agentruntimestate / artifact 对象存储 / document / documenttext / memoryclient / ModelCallClient）→ `registerFeatures`（524-544，按依赖序：voice→reminders→agentauth→composio→tasks→proactive→collaboration→agentTools→accounts）→ `startRealtimeListener`（674-684，独立连接 `LISTEN teamhub_realtime`）。
- `StartWorkers`（706-740）：`skill.Ensure`+`agenttemplates.Ensure` → 注册全部 River worker（document/voice/profile/reminder/proactive/decision/taskexecution 等 8 队列，`internal/jobs/jobs.go:32-59`）→ `jobs.NewDueNotifier`（813-819，把 `work:river-due` 通知接到 broker 唤醒 River fetch，弥补未来到期任务的轮询空窗）。
- 路由四组契约（`internal/app/routes.go:38-98`）：`teamhub-public`（浏览器 cookie session）、`teamhub-internal`（Node Services/Voice，Bearer 共享令牌）、`teamhub-agent-api`（Agent CLI，`/api/agent/v1/*`）、installer。公开路由约 230 条；写操作普遍强制 `Idempotency-Key`。

### 3.2 全链路（用户发消息 → 代理回话 → 审批 → 落库）

以"人类在房间 @Agent，Agent 回复并请求一个连接器写操作"为例：

1. **落库**：`POST /v0/rooms/:roomId/messages` → `collaboration.CreateMessage`（`internal/collaboration/messages.go:34-235`）：幂等 Lock/Replay → 房间/成员/任务锁序 → mention 解析与缺席 Agent 收编 → `messagecreation.Persist`+`Publish`：同一条语句分配 room_seq、插 `room_events`、回填消息 → 幂等 Save → 提交。
2. **唤起（DB 触发器）**：约束触发器 `room_events_queue_agent_inputs`（`migrations/00852_baseline.sql:5953`，仅 `message.created`）→ `queue_agent_inbox_message`（:1367-1390）按 inbox（room/thread/task/meta/taskmeta）找出应接收的 Context；命中在跑 Run → 插 `steering` 输入并发 `run.steered`；否则复用/创建 `queued` 的 `agent_local_runs` 行并发 **`run.queued`**（:1392-1460）。
3. **通知**：`pg_notify('teamhub_realtime',…)` → `realtime.Listener`（`internal/realtime/listener.go:133-175`）→ broker → Agent Service 的 SSE `GET /v0/agent-runtime/wakes`（`handlers_agent_wakes.go:17-54`）。丢失提示由 30 秒兜底扫描 `ListAgentContextsWithWaitingRuns` 补上（`internal/store/queries/agent_context_wakes.sql:22-38`）。
4. **领取执行**：Agent Service `POST /v0/agent-runtime/runs/claim` → `ClaimLocalRun`（`internal/agentruntimestate/run_session.go:21-143`，epoch 事务置 running、返回 initial inputs + profile 更新）→ 经 RunnerGateway 把 `run.start` 发到用户电脑（见 §5）。
5. **回话**：代理经 CLI `POST /api/agent/v1/messages/commit`（multipart）→ `agentsendmessage.Service.Send`（`internal/agentsendmessage/service.go:139-300`）：授权 → 幂等（`command_replays` + advisory lock，同 invocation 换输入=冲突）→ 目标权威校验 → `messagecreation.Create` → `RecordWakeAnswer`（proactive 问答记账）→ 提交。这条消息再次触发第 2 步链路（可继续唤起别的代理）。
6. **审批**：代理调 `POST /api/agent/v1/apps/tools/execute` → `agentconnectedapps.Execute`（`internal/agentconnectedapps/service.go:277-344`）：`accessOf`（`access.go:36-47`，读白名单直行 / 直接写白名单直行 / **其余一律需确认**）→ `prepareConfirmation` 生成动作 JSON+digest → `typedCards.CreateDecision` 同事务发 `connector_write` 卡片 + `decisions` 行 + 24h 到期 job，pending 同类卡复用防刷屏 → 代理立即拿到 `confirmation_pending`（不阻塞）。
7. **人类批准**：浏览器 SSE 看到卡片 → `POST /v0/decisions/:decisionId {decision:"approve",expected_version}` → `decisionRunWorker` → `claimDecision`（`FOR UPDATE`，executing 中断不重跑、记 unknown）→ `ExecuteConfirmed` 复核 grant/连接/pinned tool 版本/draft digest 后调 Composio → `HandOffDecision` 在卡片房间 @Agent 播报结果 → 又经第 2 步唤起代理继续。

### 3.3 关键域包速记

- **agentcredential**（`internal/agentcredential/service.go`）：令牌 `th_agent_`+32B base64url，库中只存 SHA-256；进程内凭据 TTL≤48h（:91,103-109）；Computer 凭据绑定 `assignment_revision`、凭 `held_token_sha256` 幂等续用/轮换（:144-211）；`RevokeAgent` 一键吊销。
- **agentauth**（`internal/agentauth/agentauth.go:87-281`）：每次 CLI 调用做"身份（凭据→registration）+ 成员（目标解析 SQL：房间成员/任务参与者/文档访问 v2）+ 能力（businessAction 白名单）"三查，且与业务同事务、提交前 `RevalidateInTx`；Task 里的 AlterEgo 被禁发言/建文档（`taskContextBlocked` :56-64）。
- **proactive**（`internal/proactive/`）：连接器授权开启后装 `trigger` 型 Routine 监听器（`listener.go:122-147`）→ 轮询事件 `EnqueueEventTx`（River，去重）→ `HandleEvent`（`event.go:122-203`）取 Tracking Items + 指南 → `judge`（跑在赞助人 Runtime 上的 Node Services 判定）→ 静默时段 22:00–08:00 / 每日 5 次上限降级为仅记录 → `quiet_wake`：等房间安静 3 分钟后以隐藏 `agent_runtime` 消息 @AnotherMe。
- **document**（`internal/document/service.go:167-191`）：文档/版本/正文（`document_bodies` 存 Yjs state）+ 资产上传租约/GC/隔离状态机；`documenttext` worker 由 DB 触发器驱动把文档渲染成 Markdown+纯文本供搜索/记忆/Wiki 共用。
- **River 用法**：8 队列 + `FetchOnlyKnownKinds` + `InsertTx` 业务事务内插任务 + `InsertOrWakeTx` 唤醒被 snooze 的同键任务 + `UniqueUnfinished`。

## 4. node-services：代理运行时与记忆（apps/node-services）

单进程五角色，固定序启动逆序关停：`memory → llm-wiki → agent → voice → document`（`src/main.ts:53-103`）；角色间不互相 import，只经 host 注入的 seams 交换（flashback 服务、modelCall 回调）。document 角色跑在独立 worker thread（要装 jsdom 全局）。

### 4.1 代理运行链（Run 生命周期）

- **唤醒**：TeamHub SSE `run.queued/steered/context.changed/context.prepare/task.claimable/reconcile` → `TeamHubAgentWakeStream`（`src/agent/agent-features/inbox-source/teamhub-agent-wake-stream.ts:165-238`）→ `RunWakeDispatcher.wake`。
- **准入**：`bindRuntimeContext → claimByKey → scheduleContextPreparation`（`src/agent/executor/application.ts:414-439`）；`ContextExecutor` 做串行化输入准入与 durable fence（`context-executor.ts:429-570`），queued Run 持久化在 TeamHub（TeamHub 拥有 Context/Inbox cursor/Local Run/Session 的持久态）。
- **RunLoop**（`src/agent/executor/run-loop.ts:711-1098`）：按优先级认领（chat 10 < task/document 12 < routine/proactive 15 < compaction 20，`src/model-tasks.ts:32-41`）→ `#prepareRunInput`（全部 Context 特性的 `prepareInput` 文本贡献合并：flashback/proactive/user-memory/task-progress…）→ `provider.startRun` → 单消费者消费事件流（RunTimeline 记 model_request/tool_call 与 usage；ReplyDelivery 跟踪房间投递；特性投影 RuntimeStatusUpdate 批量 ≤50 发布）→ 终态判定（"回复未送达"→failed `reply_undelivered`；"被提及却从未尝试回复"→failed `reply_not_sent`）→ `finishLocalRun` 落 TeamHub。失败区分"确定未启动"重排队（≤2 次）与可恢复重排。
- **steer/取消/压缩**：活跃 Run 且接受 steer 时注入，否则入队；空闲原生会话压缩 `compactSession` 由维护特性触发（仅 codex/claude 支持）。

### 4.2 RunnerGateway 与外部运行时适配

- **TS 侧**（`src/agent/runner-gateway/`）：`RunnerGateway` 是纯组合器（连接/生命周期/操作分发/会话压缩/模型调用队列/本地模型/调试检查/ContextView 内容）。代理侧统一 Provider 抽象 `AgentProvider`（`executor/provider.ts:352-418`），唯一生产实现 `RemoteRuntimeProvider`（`runner-gateway/remote-codex-provider.ts:138`）：会话延迟物化（首次 run.start 才建）、首事件必须 `run.started`、wire 事件 `status.changed/plan.updated/activity.*/message.delta/tool.called/tool.returned/model.responded/file.*/run.completed/run.failed/human_interaction.requested` 翻译成内部 RunEvent；权限审批走 `onPermissionReview`（tool-approval 特性裁决），人类交互走问题卡。
- **Go 侧**（`apps/computer/local-daemon/internal/provider/native/`，详见 §5.2）：`Runtime.Start(ctx,prompt,spec)` 统一接口 + 8 位驻留进程池。

### 4.3 记忆（写入/建图/检索）

- **写入**：Room 会话/录音/邮件/My Pages/Pocket Note/Profile 统一为 RawSource，写 Postgres `memory_index.sources/source_versions/chunks`，chunk 上加权 tsvector（标题路径 A、正文/标题 B、路径 C，`src/memory/chunk-index.ts:780-798`），版本原子替换失败回滚。Session Facts 仿 Hindsight：3000 字窗口逐窗抽取 `what/when/where/who/why/fact_kind/fact_type/entities`，`MIN_SOURCE_WORD_SHARE=0.35` 拒绝模型翻译漂移。
- **建图**：`graph/build.ts:34-64` 纯读时构建——OpenWiki WikiNode（frontmatter+正文）为节点、页面相对链接为边 + backlinks + frontmatter aliases；`inferred-edges.ts` 按名字模式生成推断边供 Flashback 用。
- **检索**（`memory/knowledge-query.ts:118-220` + `chunk-index.ts:309-1029`）：**双列表分排**（原始证据 items / 摘要 summaries 分开）；每个改写词各成一条词法路由（`ts_rank_cd` + lexical rerank）；事件窗/记录窗时间路由（事件窗只对以自身日期为内容的源投票）；全部路由 **RRF(k=60) 融合**；相邻 chunk 合并、每源限 3 条；索引无命中时对最新 ≤30 源/≤3MB 原文做进程内 **BM25 兜底**；按预算（上下文 15%、≤25k tokens）组页分页。`src/memory/README.md` 明示：**无向量列、无 rerank 模型**；LoCoMo 95% 成绩出自 `scripts/memory-benchmark/`（准备历史→knowledge_search/knowledge_read 工具循环答题→评审）。
- **Flashback**（`memory/flashback/`）：cue（消息点名实体）→ 桥接（cue→bridge tie × fan 抑制枢纽 × bridge→meeting tie × 遗忘因子 `1−e^(−天数/14)`）打分推荐回忆；预算：房间冷却 30min、每日 ≤3 次、cue 冷却 24h、7 天不重复同一 episode。仅 anotherme×meta Context 生效。

### 4.4 夜间 Wiki 整理链

Memory 调度器（持久日历 + 60s 兜底）午夜槽触发 → `runWikiSyncCli` → TeamHub `wiki-refresh` → node-services `POST /internal/v1/wiki-refreshes/:id/candidates`（带冻结源集合）→ `WikiRefreshCandidateService.#generate`（`llm-wiki/wiki-refresh-candidates.ts:171-325`）：物化源文件 → `generateWikiCandidate`（`wiki-initialization.ts:42-200`）**整批先跑一次，校验失败则二分重跑（≤32 个 run），单源仍败即跳过**；预算 150min 模型时间/210min 墙钟，超时源 deferred 留待下夜。真正的生成是 `AgentWikiBackend` 四段：**route**（每源提名实体）→ **consolidate**（合并既有候选页 ≤300）→ **meeting**（每会一张 Session 页）→ **batch**（每批 ≤5 张实体页）；每步是 `runAgentTask` 受控循环（一次结构化 model call 返回 actions，环境执行校验后喂观察）。页全部是 JSON 经 schema 校验渲染；提示词按节点类型从 `prompts/llm-wiki/personal/*.md` 全文注入。候选交 TeamHub 发布为新 Wiki revision 后，Memory 把新 Wiki 页/日报 reconcile 回 `memory_index`，完成"生成→索引"闭环。模型调用全部经 `seams.modelCall` 落到所有者电脑的 Runtime（Pi 优先；Antigravity 无 model.invoke 则用同机 Claude、退 Codex）。

## 5. Computer Daemon：本机执行面与护栏（apps/computer/local-daemon）

### 5.1 连接、账本与队列

- **单条出站 WebSocket**（`internal/linger/transport/gateway.go:40-83`），帧上限 4 MiB；hello 携带协议版本/runner_id/nonce/设备签名/Runtime 清单/workspace grants/活动 Operation 快照（`internal/daemon/connection.go:80-126`）；认证失败/需升级/身份冲突终态处理，网关重启走 2 分钟快速重拨，其余指数退避+抖动（:496-517）。
- **事件账本**：`OperationLedgerStore`（`internal/daemon/operation_ledger.go:23-42`）当前为**内存实现**（进程重启对旧 Operation 报 interrupted 而非谎称可恢复，:18-22）；每 Operation 未确认事件 ≤16384 条/64 MiB。事件**先 `ledger.Append` 拿序列号再发送**（`operation_start.go:187-219`）；网关 `operation.ack` 确认到某序列后释放；重连后 `replayRetainedEvents` 重放未确认事件，重复 start 命中 running → 重放而非二次执行。
- **命令队列**（`internal/daemon/command_dispatch.go`）：每 Context（Tenant+ExecutionContextKey）一条 FIFO 单 worker 队列保序，跨 Context 信号量限流 **8**（`defaultContextDispatchLimit`）；`operation.cancel/input` 挂到同 Operation 的队尾防插队。
- **文档漂移**：`docs/architecture.md:69-70` 称 event ledger 为 SQLite；代码实为内存账本，SQLite 实际用于 **Context View 存储**（`internal/linger/context/view_store.go:267-292` 建 `context_views_v3`）。

### 5.2 四种运行时适配器（`internal/provider/native/`）

| 运行时 | 协议 | 进程模型 | 要点 |
|---|---|---|---|
| Codex | `codex app-server` 换行分隔 JSON-RPC over stdio | 驻留复用（8 位池） | 单写者传输、初始化超时可安全重试一次 |
| Claude Code | stream-json over stdio | 驻留复用 | argv 固定 `-p --input-format stream-json --output-format stream-json --permission-mode acceptEdits --permission-prompt-tool stdio --strict-mcp-config …`；initialize 帧挂 PreToolUse/PostToolUse hooks |
| Pi | 自定义 RPC | 驻留复用 + 探活 | reasoning effort 映射；托管 MCP 经 `tools/pi-mcp.mjs`，只许 `127.0.0.1` 本地代理 |
| Antigravity | ACP（JSON-RPC 2.0 over stdio） | **每 Operation 独起进程，不驻留** | 会话存 Antigravity 自家 store，`session/load` 重开；无 provider prepare |

驻留池 `resident_table.go`：cap=8，超员先回收"预启动未被采用"再回收最久未用；预启动闲置 20 分钟回收；复用前 liveness+形状检查；停止必须确认进程树退出否则 key 保持 fenced。

### 5.3 Agent workspace 与文件安全

- 布局由服务端 View manifest 权威下发（playground 可写；agent/ 是 npm+uv 项目；memory/、llm-wiki/ 只读）。本机 `Ensure` 物化：**只读强制在文件系统层**——只读 mapping 文件 chmod 0400（可执行 0500）、目录 chmod 0500（`projection.go:279-288,503-532`）；可写目录 0700；拒绝只读/可写根互相嵌套、拒绝覆盖非本 View 投影过的文件（SHA-256+大小核验归属）。
- `agent/pyproject.toml` 与 `agent/package.json` 用 `O_CREATE|O_EXCL` 补齐，**绝不覆盖 Agent 已改过的文件**（`agent_project.go:12-68`）。
- 文件下载统一 `writeVerifiedFile`（`view_store.go:910-933`）：`O_EXCL` 独占创建**绝不覆盖已有文件**，边写边算 SHA-256，大小/摘要不符即删除报错；本地拷贝复用同样过校验；并发下载 16、在途 400 MiB 上限。
- 路径安全：`safeJoin` 拒绝绝对路径/反斜杠/`..`；逐级拒绝符号链接。

### 5.4 护栏（Guardrail）

四层，全部在本机 + Agent Service 评审：

1. **确定性规则**（`internal/permission/`）：只读工具白名单（snapshot/screenshot/console/scroll/hover/navigate_back 等）；Shell 走小子集解析器（单引号/无展开双引号/heredoc/续行/重定向），仅只读命令白名单、manifest 驱动的 teamhub 命令、workspace 内文件写放行，混入确认类命令即拒并提示"单独运行"；`tccutil`/osascript 驱动系统设置硬拒；**跟随式浏览**——导航目标是当前页已见链接或同站（registrable domain 相同）免审。
2. **LLM 复核**（`permission/reviewer.go:58-138`）：规则未放行者采集证据（页面 URL/标题、目标元素 role/name、表单字段、低分辨率 JPEG 截图）→ `permission_review` 请求送 Agent Service 评审；**超时/失败一律 Unavailable=不执行**（宁可拒也不跑无人评审的调用）。
3. **车道与焦点门**（`internal/linger/localtools/manager.go`）：`desktop` 一条道 + 每 Agent 浏览器一条道（`browser:<agentID>`）+ 每 Chrome profile×agent 一个"座位"；需要前台窗口/剪贴板的桌面输入与浏览器调用互斥（焦点门）；任何一侧存在"结果未知"动作时直接拒绝对方。
4. **日志先行 + unknown 封道**（`localtools/journal.go`）：**真正发送输入之前**把动作身份原子写盘（桌面 `computer-tools/action.json`、每浏览器道/座位各一份）；只有确认清理成功才删记录；结果 unknown → 记录保留，该桌面/该浏览道/该座位持续封锁返回 `COMPUTER_ACTION_UNKNOWN`，**永不重放**；Daemon 重启会重读记录继续封锁。

### 5.5 本地安全边界

所有 `net.Listen` 均为 `127.0.0.1:0` 临时回环端口（MCP 中继/每 Operation 工具服务/Codex 钩子/CDP 代理/CLI 登录回调）；本地控制面 Unix socket（目录 0700、socket 0600）或 Windows 具名管道（SecurityDescriptor 仅当前用户）；子进程环境白名单净化（不带 NODE_OPTIONS/模型 key/网关凭据）；**线上请求永不决定本地路径/可执行文件/凭据**。

## 6. teamhub-cli / skills / contracts

### 6.1 CLI（apps/teamhub-cli）

- **一条定义三投影**：每个命令一个 `CommandDefinition`（`src/command-definition.ts:56-97`：command/toolName/description/readOnly/approval(allow|confirm|judge)/usage/options/inputSchema/outputSchema/normalize/prepare/execute/project/render），汇聚为唯一 `commandDefinitions`（`domain-commands.ts:28-42`）；help（`domainHelp`）、`--schema`（定义自带或按 toolName 懒加载 zod 转 JSON Schema）、权限清单（`commandManifest()` 构建期生成 `teamhub-commands.json`，"写给宿主做权限预审；TeamHub 仍在每请求真授权"）全部由同一对象投影。help 有 vitest 快照保护。
- **实测命令数 112**（TeamHub 业务约 60 + 连接器 52），architecture.md:92 的"155 commands"与快照不符（见 §9）。
- **执行链**（`src/cli.ts:93-383`）：离线路由（help/schema 不发网络）→ 语法解析 → `loadConfig`（token 文件 `O_NOFOLLOW` 读、限 8 KiB；profile 带 caller Context；`identityKey=sha256(baseUrl+…)` 仅本地缓存命名空间）→ normalize/prepare（连接器账号解析、文件 sha256 快照）→ dispatch：写操作生成 operationId（默认 UUID）以 `x-teamhub-operation-id` 头发送，业务路由把 operation ID 规范化为 `agent-invocation-sha256:<sha256>` 作幂等键。
- **审批等待即结束**：连接器写被 TeamHub hold 时返回 `confirmation_pending`，CLI 输出 `{action:"confirmation_requested", …}` 以退出码 0 结束，提示"批准后代跑、勿重复运行、卡 24h 过期"；**结果 unknown 永不自动重试**（`externalOutcomeUnknown`）。
- **无 run/daemon 也可独立工作**：一次性进程、无本地队列/锁/回执；依赖注入式内核可完全离线测试。

### 6.2 技能（skills/）

- 21 个 builtin 技能，按 `builtin/<name>/<version>/` **不可变版本目录**存放（根文件带 frontmatter 的 SKILL.md + 可选 references/agents/targets），`catalog.yaml` 声明 `skill_id/bootstrap_manifest_id/default_agent_types/manifests`；已发布版本禁原地改，`make check BASE=` 用 `check-builtin-skill-immutability.sh` 强制。
- `skills/embed.go:9-10` `//go:embed all:builtin` 打进 **TeamHub Go 二进制** → 启动 `skill.Ensure/EnsureVerified` 装库并内容寻址入对象存储 → `skill.ResolveEffectiveInTx`（Agent 类型默认 + 显式绑定，去重限 100、冲突即错、算规范 JSON 的 SHA-256 digest）→ 内部契约 `GET /v0/agents/{id}/effective-resources` 暴露给 Agent Service → Computer/Daemon 用 Agent 凭证拉包投喂运行时。`cmd/skill-package-audit` 对全部技能包做对象存储完整性审计 + `--repair-builtin` 修复。

### 6.3 契约（contracts/）

- 5 个 OpenAPI 入口（public/agent-api/internal/node-services-internal/installer）+ `runner-gateway/asyncapi.yaml`（Agent Service↔Daemon 的 WS 协议，protocol_version 2）+ `envelope.schema.json`（全部帧定义）。
- codegen（`contracts/codegen/contracts.ts`）：唯一登记表 `contractEntries` → `redocly bundle` → `openapi-typescript`（TS types）+ `oapi-codegen@v2.7.1`（Go client/types）→ `generate-runner-contract.mjs` 从 envelope+asyncapi 生成 TS types/schema/validator 与无依赖 Go 模块 → prettier+gofmt。`verifyContracts` 静态检查"每个 OpenAPI 文件必须被某入口 $ref 可达、$ref 不得逃出 openapi 树" + 临时目录重新生成与提交产物 `diff -ru` 全目录比对。生成物**只许生成禁止手改**。
- `packages/service-kit`：无运行时依赖的共享工具；`serviceCredential` 用 `LINGER_SECRET_SEED` 经 HKDF-SHA256 派生服务间凭据，与 Go 侧一致性由 `contracts/fixtures/service-credentials/vectors.json` 共享测试向量双侧校验。

## 7. Web / Desktop / Voice / Installer

- **web**（React 19 · Vite · TanStack Query · Tailwind · BlockNote）：`createAppRoutes` 集中路由，落地页重定向到 Another Me 房间；两阶段房间 bootstrap（先消息后房间/成员，失败清缓存防越权缓存）。Yjs 协同：`openRoomDocumentSession` 先建共享 Hocuspocus 传输层、"编辑者才有本地副本"（IndexedDB 持久化），凭据每次重连向 TeamHub 换新。审批卡：`intent==="decision_requested"` 的消息统一走 DecisionCard，按 `card.kind` 分发到 question/connection_auth/computer_permission 等专属视图，`POST /v0/decisions/{id}` 提交。Wiki 界面：wiki-home/collection/profile/preview 页 + 从 Memory 生成的 HTML 里解析内嵌 `const graph={...}` 得到实体图。语音两入口：Voice Mode（聊天听写，LiveKit 麦克风 + `POST /v0/rooms/{id}/voice-sessions` + SSE/轮询收 transcript，幂等键写回房间消息流）与录音/速记。
- **desktop**：Electron 44 壳——加载远程/本地 Web SPA（窗口加载策略模块化管理），把 Go daemon 作为子进程运行（写 `config.json` + `LINGER_COMPUTER_TOKEN` 注入，崩溃退避重启，stdin `permissions.v1` 协议处理 macOS 授权）；`local-server.ts` 拉固定 Node 运行时 headless 跑打包进 app 的 installer 完成 Quick Install；三平台打包脚本 + `distribution/<platform>.json` 钉死组件清单（localmodels 工具、postgres-17.10-pgvector、livekit+ffmpeg，均带 sha256）。
- **voice-runtime**：LiveKit Agents worker 三种（asr/recorder=Soniox，live=xAI Grok 自带转写）；Soniox 固定 `wss://stt-rt.soniox.com`，`RecoveringASRStream` 断线重连+重放、帧缓冲 20s；node-services `startVoiceService` 按 TeamHub 下发的 provider key **对账式监督**（key 变化 → generation 计数作废旧 worker → drain 72s → 替换；每 60s 兜底；key 只进子进程环境）。
- **installer + local-installation（Model Autopilot）**：**硬件探测/模型目录/SimplexAI 打分/装前自检全部委托外部 `localmodels` Python 工具**（按平台从 CloudFront/npm 镜像下载、逐文件 sha256 验证）；本仓只做编排：`setup inspect`（探测+推荐，120s 超时）→ `stack plan`（规划，原子落 `plan.json`）→ **审批门禁**（`plan-inputs.json` 与 planId/shareGpu 一致才算已批准，否则返回 `LOCAL_MODELS_APPROVAL_REQUIRED` 附脱敏摘要）→ `stack apply --approve <planId> --jsonl`（下载/校验进度事件）→ `setup binding`（**只有 `ready:true` 且带出 Pi 可执行文件与配置指纹才算装好**，否则 `LOCAL_MODELS_RECOVERY_REQUIRED`；"答对一题"自检在上游工具内部）。推理引擎本体（PolyStrata/llama.cpp）在另一仓库，本仓边界止于"选择/安装/拉起"。

## 8. 关键机制专题（跨切面）

1. **模型调度**（docs/model-scheduling.md）：每端点一条自适应并发队列（网关/Key 型 1→8，账号直连型 10→10）；按"每千新 prompt token 响应速度"扩缩容，被限流减半并冷却；优先级序：工具审批 > 录制问答 > 聊天 > 任务/文档 > 例行/主动 > 压缩 > 记忆/Wiki 后台；**高优先级可逐单元"换出"最低优先级在跑 Run**（被换出者保持 ID/状态/claim，稍后同会话续跑；Codex 需已产出模型输出或工具事件才可 yield）。
2. **Proactive/Dreaming 递归自改进**：每个自主发出的消息也是测试；夜间 Dreaming 读"消息 + 其后 20 条回复"，"讲方式"的回复成 clue，同 kind 两条 clue 合并成规则（"直接点名"一次成规则）；次日以新规则判定，形成无重训练的隐式强化。规则落 `proactive_guidelines`，判定时只读规则不读 clue。
3. **team.md 团队协议**（docs/team-md.md）：多代理协作时 Another Me 用 `teamhub room collaborate` 把"共同目标 + Coordinator + 每成员职责与交接"发布为 Room 的 `team.md`；**TeamHub 校验每个 Actor ID 都是房间活跃成员否则整体拒绝**；@提醒成员各用 `teamhub room protocol` 读同一页、按自己 ID 条目行动；整体替换式重发布。
4. **Meta/AlterEgo 任务委派**（docs/task-delegation.md）：聊天内是 Meta，每 Task 一个后台 AlterEgo（每 Agent ≤10 并发）；AlterEgo 不读用户聊天、不提问，产出写 `playground/<task-id>/`；同 Room 各 AlterEgo 按同路径互读成果；状态机 idle/waiting_for_approval（卡 10 分钟过期）/running/failed/canceled，取消=暂停可恢复。
5. **知识检索纪律**（docs/wiki-and-memory.md）：`teamhub knowledge` 一次返回两列（Wiki 页/日报概览 + 原始消息/转写/文档/邮件细节）；服务端按代理注册决定"这是谁的知识"（只能搜雇主的知识）；**要求先搜原始记录才能断言"从未记录过"**；关键词 only 无嵌入无 rerank；最多 6 个改写词支持跨语言命中；"个人上下文法"——先搜知识，再只查答案还缺的活源（日历/Slack/邮件），记忆中可变事实必须对最新源复核后才可当作现状陈述。
6. **幂等三件套**：`command_replays` 表（advisory lock + invocation hash + 回执）覆盖所有代理写命令；连接器外部写凭 `x-teamhub-operation-id` 审计 + 确认卡幂等键；decision 执行器崩溃中断记 unknown 绝不重跑。三处与 §5.4 的 journal 同构："先记账、结果 unknown 不重放"。

## 9. 文档与代码不符点（诚实记录）

| # | 文档说法 | 代码事实 | 证据 |
|---|---|---|---|
| 1 | `docs/architecture.md:69-70` "event ledger SQLite; every event is saved before it is sent and replayed after a reconnect" | 账本为**内存实现**（进程重启即失忆、报 interrupted）；SQLite 实际用于 Context View 存储；"先记后发/重放"语义由内存账本 + 单进程内成立 | `operation_ledger.go:18-22,167-182`；`view_store.go:267-292` |
| 2 | `docs/architecture.md:92` "155 commands"（TeamHub 56 + Connectors 99） | 实测 **112 条**（业务约 60 + 连接器 52）；README 自述"8 个专用应用共 50 条 Connector 叶命令" | `apps/teamhub-cli/src/{message,document,business,connector-*}-commands.ts`；`apps/teamhub-cli/README.md:65` |
| 3 | README 称 "95% on the LoCoMo memory benchmark" | 检索管线无向量/无 rerank；95% 出自仓内 benchmark 脚本的特定答题形态，非服务直接能力 | `apps/node-services/src/memory/README.md`；`scripts/memory-benchmark/` |

## 10. 与 Neurova 的对照与可借鉴点

Linger 与 Neurova 同为"个人/团队 AI 代理平台"，但路线不同：Linger 把执行大脑外包给成熟编码代理运行时（Claude Code/Codex/Pi/Antigravity）并围绕它做治理与记忆；Neurova 自研编排与工具回路。值得借鉴的机制（按价值排序）：

1. **单条出站 WebSocket 的本机执行面**：所有代理共一条出站连接 + 不开监听端口 + 本地控制面 owner-only socket，网络面积极小，适合"代理跑在用户 PC"的产品形态。
2. **"先记账再执行、unknown 不重放"三处同构**（连接器执行/操作账本/屏幕操作 journal/decision 执行器）：比单纯幂等键更强——结果未知时封道并显式上报，而不是盲目重试。可与本仓 `ToolExecutor` 单管道与审批链结合。
3. **一条命令定义三投影**（help/schema/权限清单同源生成 + 构建期 manifest + help 快照测试）：本仓工具/命令面持续扩张，此法可消除"文档-实现-权限"三处漂移。
4. **DB 触发器 + LISTEN/NOTIFY + SSE 的唤醒链 + 30s 兜底扫描**：真相单源在库、通知只做提示、丢失有兜底，比纯内存事件总线更抗重启；与本仓任务调度可靠性议题（TaskScheduler 无人 start 的教训）同频。
5. **契约先行 codegen + verify diff 门 + "每个 OpenAPI 文件必须被入口可达"**：契约腐化的自动防线，可借鉴到本仓 API/契约管理。
6. **runtime place 感知的凭据轮换**（凭据绑定 placement + `held_token_sha256` 幂等续用 + 换机即吊销）：外部代理/CLI 凭据治理可参考。
7. **学习规则的记忆化自改进**（Dreaming：回复→clue→规则，判定只读规则）：与本仓 meta_cognition/growth_log 思路同向，其"clue 两次才成规则 + 直接点名一次成规则 + 判定期不读 clue"的准入纪律值得吸收。
8. **护栏的"LLM 复核失败即拒 + 跟随式浏览免审 + 焦点门**"：最小权限与体验的折中设计，可充实本仓 computer_use 的审批策略。

**不宜照搬**：把代理执行整体外包给外部编码代理 CLI（本仓已有自研 swarm/工具回路，且外部代理接入已有 neuacp 线）；关键词-only 检索是在"本地无 GPU 富余"约束下的取舍，本仓已有向量+图谱双通道，不应倒退。

## 11. 研读方法与证据说明

- 文档：README 全文 + docs/ 13 篇（architecture/local-inference/wiki-and-memory/proactive/team-md/task-delegation/model-scheduling/desktop-and-browser 等）由主会话通读。
- 代码：5 路并行 Explore 子代理分域深读（TeamHub 109 次工具调用 / node-services 107 / Computer 90 / CLI·技能·契约 97 / Web·Desktop·语音·安装器 61），全部结论带文件:行号。
- 主会话抽查复核三处硬结论（记忆无向量、触发器链、命令数宣称），均与源码一致。
- 局限：depth-1 快照（无历史演进视角）；`openwiki` npm 包本体未读源码（不在本仓）；`localmodels` 工具与 PolyStrata 引擎在外部仓库，本报告只覆盖其在本仓的编排边界。

---

## 附录 A：TeamHub 服务端八项深读详录

> 应任务书 8 项逐条落档；路径相对 `apps/teamhub/`（另注者除外）。

### A1. 入口与装配

- 进程入口 `cmd/teamhub/main.go:13-39`：解析 `--composio-base-url`（测试适配器）→ `config.Load()` → `app.New(ctx,cfg,app.Deps{})` → `application.StartWorkers`；`TEAMHUB_SKIP_STARTUP_SKILL_RECONCILIATION=1` 可跳过内置技能/模板安装。信号处理在 `cmd/teamhub/shutdown.go`；`cmd/migrate/main.go:17-25` 独立进程只跑 goose 迁移。
- `internal/app/app.go:281-313` `New()` 装配顺序：`validateConfig`（:329-340，DB URL 必填、SessionTTL 上限、Document Runtime 必须配 Node Services token）→ `linkAgentService`（:344-360，配置 NodeServicesURL+token 时建 `roomagent.HTTPGateway`）→ `newSigningKey`（:362-374，`LINGER_SECRET_SEED` 或随机 32B）→ `openDatabasePool`（:376-390，默认 max 16 连接）→ `newCoreServices`（:392-441：agentruntimestate/artifact 对象存储/document（有 Runtime 用 `NewWithRuntime` 否则 `NewWithObjectStore` :445-466）/Wiki 候选生成器/documenttext/memoryclient/ModelCallClient）→ `newApp`（:500-520）→ `registerFeatures`（:524-544）→ retention Sweeper → `compressResponses(a.routes())` → `startRealtimeListener`（:674-684，独立连接 `LISTEN teamhub_realtime`）。
- `registerFeatures`（:524-544）按依赖序：voice → reminders → `registerAgentAuthorization`（:546-551，agentauth+SetConnectedApps）→ externalApps（composio）→ tasks → personalData → `registerProactive`（:597-608，judge=Node Services 网关）→ collaboration（:619-629，含 `runtimeState.OnLocalComputerOnline(a.agents.EnsureAnotherMe)`）→ `registerAgentTools`（:633-645，mcpContexts/agentdocument/agentdirectmessage/agentroomhandoff/agentsendmessage/permissionreview/agentcreationapproval/taskdelegation）→ `registerAccounts`（:649-664）→ voice。
- `StartWorkers`（:706-740）：`skill.Ensure`+`agenttemplates.Ensure` → `startJobs`（:744-821，注册全部 River worker 并启动）→ SkillPackageProbe（:849-877，失败指数退避，`/readyz` :1083-1097 依据审计态拒就绪）→ PresentationLoop（:730-738，分条节奏发送）。
- 路由：`internal/app/routes.go:38-98` 四组契约路由（teamhub-public 浏览器 cookie / teamhub-internal×2 Bearer 服务令牌 / teamhub-agent-api CLI `/api/agent/v1/*`），`bindContractParams`（:107-118）反射绑 header/query；公开路由约 230 条（`routes_public.go:10-254`），写操作普遍强制 `Idempotency-Key`（`requireValidIdempotencyKey` routes.go:176-181）。
- 鉴权中间件：`requireSession`（app.go:1120-1136）+ `optionalPrincipal`（:1147-1165，cookie 32B hex→SHA-256→`sessions.Active`）；`requireAgentService`/`requireMemoryService`（:1167-1199，常量比较 Bearer）；`principal.inSpace`（:185-187）+ `requireSpace`（:200-206）——不属于本 Space 一律 404 防探测。`healthz`（:1099-1118）查 DB ping 与 realtime Listener。

### A2. 核心域包

- **agentcredential**（`internal/agentcredential/service.go`）：令牌 `th_agent_`+base64url(32B)（:259-274），库中只存 SHA-256（`agent_access_credentials.token_hash`，baseline :2786-2800）；`IssueManaged/For` TTL≤48h（:91,97-109）；`EnsureManagedForPlacement`（:111-125）绑定 `assignment_revision`、签发前旧 placement 凭据全部 `expires_at=now()`（:184-187），computer/workspace 不匹配 `ErrForbidden`（:167-170）；`AuthenticateInTx`（:231-257，`FOR SHARE` 联 active registration）、`RevalidateInTx`（:53-68，业务提交前二次校验）、`RevokeAgent`（:130-140）；HTTP 入口 `POST /internal/agents/:agentId/access-credentials`（routes_internal.go:14）。
- **agentauth**（`internal/agentauth/agentauth.go:87-281`）：每次 CLI 调用同事务完成三查——身份（凭据→registration，AgentType 限 general|anotherme :144-146）、成员（目标解析 :149-190：room→`active_room_members`；task→创建者/assignee/grantee/participant :157-163；thread→父房间文档；document→`resolve_agent_document_access_v2`）、能力（`businessAction` 白名单 :220-229 + `businessCapability` 细分 :246-281）；`taskContextBlocked`（:56-64）禁 AlterEgo 发言/建文档/建任务；幂等键 `IdempotencyKey`（operation_key.go:10-21）+ 回执 `command_replays`（operation_receipt.go:20-42）。
- **agentsendmessage**（`internal/agentsendmessage/service.go:139-300`）：`normalizeAtomicInput`（校验 `agent-invocation-sha256:<64hex>`、inbox 格式、segments）→ 事务内 `AuthorizeInTx`（:168-176）→ 幂等 Lock+Replay（:180-194，命中走 `validateSendMessageReplay` :460-502）→ `resolveTarget`（:380-445，thread→父房间+`AllowsRoomTarget`；room→`GetRoomAgentMessageAuthority`+`LockActiveRoomForMutation`）→ 附件/文档引用校验 → `messagecreation.Create` → `proactive.RecordWakeAnswer`（:260）→ `idempotency.Save`（:271-284，唯一约束冲突→`ErrIdempotencyConflict`）→ `RecordPresentationOutput`（:286-294，写 `agent_runtime_status_events`）。HTTP `POST /api/agent/v1/messages/commit`（`internal/app/contract_server_agent_message_commit.go:21-127`，multipart：metadata+files，先存 artifact store 再原子落库）。
- **agentdirectmessage**（`internal/agentdirectmessage/service.go:67-216`）：授权 `send_direct_message` → `resolveAuthorityForShare`（:224-272，registration 联出 agent actor+human sponsor）→ 幂等 → `GetDirectRoomByPair` 无则 `OpenOrCreateDirectRoom`（需 Agent 锁，`agentLockRequired` 重试 :83-115）→ 逐条 `messagecreation.Create` → 回执落 `command_replays`。
- **agentroomhandoff**（`internal/agentroomhandoff/service.go:90-177`）：仅 AnotherMe 的 Meta 且当前在赞助人直聊（`directChat` :181-200）；`requireHumanRequest`（:206-227，`RunClaim`+`IsRunStartedByDirectChatHuman`，proactive/routine/task 回调不算）；确定性消息 ID `sha256("room-handoff:"+agent+invocation)[:16]`（:278-281）；`CardHandoff` 隐藏消息含 `<room-handoff-pattern>` 指令（:283-308）→ 触发目标房间 AnotherMe Context。
- **agentmessages**（`internal/agentmessages/service.go`）：只读（RepeatableRead 快照 :62-75）；`Search/readPage`（:77-177）经 `CanReadAgentHistoryInbox`（:111-120）+ 视图 `agent_history_messages`（inbox 编码 room:|thread:|task:|meta:|taskmeta:）。
- **agentregistry**（`internal/agentregistry/`）：`CreateAgentRegistration`（agent_registration_core.go:26-57）同事务建 actor+registration；placement 校验 `requireAgentPlacementTarget`（:64-93，须 workspace-write）；变更 `NotifyAgentRegistrationChanged`（:99-108）；人类入口 `POST /v0/tenants/:tenantId/agents`（handlers_agent_registration.go:67-125，限 50 个）；`EnsureAnotherMe`（another_me.go:49-67）挂"本地电脑上线"钩子（app.go:625）——首在线创建 AnotherMe+直聊 "Chat"+入职卡片+起步工作区（模板 research-analyst/code-reviewer :42）。
- **agentruntimestate**（`internal/agentruntimestate/`）：表 `agent_execution_contexts`（kind meta|alter_ego|document，baseline :2813-2850）、`agent_runtime_inputs`（:3126-3148，status steering|handled）、`agent_local_runs`（:3064-3089，queued→running→succeeded/failed/canceled）、`agent_local_run_inputs`（:3053）、`agent_runtime_status_events`（:3159）、`agent_service_epochs`（:3179）。`ClaimLocalRun`（run_session.go:21-143，epoch 事务锁配置+Context，处理重复领取=重放、Voice Live 占用、跳过已取消消息的队列 Run）；`FinishLocalRun`（:226-）/`RequeueLocalRun`（:195-224，同时过期该 Run 的 pending native question）/`CancelLocalRun`（:321-）；Session 存 `agent_execution_contexts.session`（Get/Checkpoint/Clear :372-535，凭据泄漏检查 `containsRuntimeCredential` :728-）；`SubmitTrustedTurn/AcceptTrustedNotification`（runtime_input.go:15-145）；本机注册/enrollment PKCE（runner.go:47-466）；状态投影 `run_status_log.go` → `/v0/rooms/:id/run-statuses`。

### A3. 任务队列与 proactive

- **River 用法**（`internal/jobs/jobs.go`）：8 队列（default/maintenance/indexing/personal_wiki/generation/schedule/external/document_input，:32-59；MaxWorkers :126-139）；`NewClient`（:105-122）`FetchOnlyKnownKinds`+`JobTimeout=5m`+`RescueStuckJobsAfter=6m`；`InsertTx`（:182-189，业务事务内插任务，回滚即无任务）；`InsertOrWakeTx`（:200-230，唤醒被 snooze 的同键任务）；`UniqueUnfinished`（:151，唯一性只覆盖未完成态）；`due_notifier.go` 把 `work:river-due` 通知接到 broker 唤醒 fetch（补未来到期任务的轮询空窗）。
- **周期 sweep**（`internal/app/maintenance_jobs.go:128-136`）：文档资产 GC 1m、保留/Wiki 修剪 1h、凭据 GC 1h、schedule repair 5m、连接状态/授权 reconcile 1m、邮件同步 10m、proactive listener 安装 10m。
- **proactive**：连接器授权开启 auto-reminders 后 `InstallListenerTx`（proactive/listener.go:122-147）建 `trigger` 型 Routine（gmail/outlook/gcal/slack :42-49）→ 轮询事件 `RouteListenerEvents`（:151-172）→ `EnqueueEventTx`（proactive/event.go:74-82，River kind `proactive.event`，UniqueUnfinished 去重）→ `HandleEvent`（event.go:122-203：Grant 校验→按 (source,externalID,state,day) 去重→取 Tracking Items+`proactive_guidelines` 规则（service.go:27-47）→ `judge`（=Node Services `AgentEventJudge`，app.go:597-608）→ 静默时段 22:00–08:00/每日 5 次上限降级仅记录（`gated` :207-215））→ `wake`（:220-259）→ `reminder.EnqueueTx`（quiet_wake.go:72-109，`proactive_pending_wakes`+River `proactive.quiet-wake`）→ `Deliver`（:147-200）等房间安静 3 分钟（`Window` :29）→ `deliverOne`（:210-237）以隐藏 `agent_runtime` 消息 @AnotherMe。例程投递 `reminder/scheduler.go:181-238`（直聊 AnotherMe 例行也走 quiet-wake 队列 :198-217）。手动注入 `cmd/proactive-event/main.go:85`（同一 `HandleEvent`+授权校验）。

### A4. 文档协作

- `document.Service`（internal/document/service.go:167-191）：可选 `Runtime`（`roomdocument.HTTPRuntime`，协作编辑后端）+ 本地对象存储；`document_bodies` 存 Yjs state+state_vector（baseline :3413-3425）；`document_events` 事件序列；`document_assets` 上传租约/GC/隔离状态机（:3362-3411）。
- `documenttext`（internal/documenttext/worker.go:1-120）：DB 触发器 `queue_document_text_for_body/for_document`（baseline :1501-1520）→ River `document_text.sync` → 渲染 Markdown+纯文本入 `document_texts`（搜索/记忆/Wiki 共用）；未连 normalizer 时文件版本同步 10 分钟 snooze 等待。
- `collaboration.Service`（internal/collaboration/service.go:19-36）：人类侧房间/成员/消息/线程/历史分享/已读。
- 个人 Wiki：`document/wiki*.go`（wiki.go 1469 行、wiki_dispatcher.go 633 行）——候选生成→派发（`personal_wiki` 长任务队列）→发布后同步 Memory 图（app.go:823-829）。

### A5. 连接器（Composio）与写操作审批

- `internal/composio/client.go:43-63`：Composio REST 适配（tool search/get/execute、connection status、link/OAuth、mail import、polls）；API key 可启动后经产品页保存（`atomic.Pointer`+`composio_settings` 密文表 baseline :3323-3328）；按 provider 分文件（gmail/slack/notion/github/discord/google_calendar/mail_import/polls + tool_search）。
- `agentconnectedapps`：`accessOf` 三分（access.go:36-47）——`readTools` 白名单（:74-157）直行；`directWriteTools`（:164-191，草稿/附件/建文件夹等）直行；**其余一律 `accessConfirm`**（默认按需审批）。`Execute`（service.go:277-344）：`authorizeExecution`（:389-407，事务内 `AuthorizeInTx("execute_app_tool")`+`LockGrantedAgentToolConnectionInTx`）→ 连接状态 → pinned tool 版本校验（:349-378，TTL 10min 缓存，失效报 `tool_version_unavailable`）→ 需确认则 `prepareConfirmation`（confirmation.go:46-76：`confirmationAction` JSON+`ConnectorWriteView` 卡片+`Digest=sha256(connection_id+action)`，草稿类读草稿记 `DraftDigest`）。
- HTTP 层 `writeConnectedAppResult`（contract_server_agent_connector_confirmation.go:22-74）：要求 sponsor、选卡片房间、校验 Run 来源（`RunClaim`），以 `X-TeamHub-Operation-Id`（缺省生成）+`sha256(room+digest)` 作幂等键调 `typedCards.CreateDecision`，返回 `{"status":"confirmation_pending",...}`；调用审计 `logCall`（service.go:141-152）。
- 批准后 `ExecuteConfirmed`（confirmation.go:82-144）：复核 grant/连接/pinned 版本/draft/canvas digest → `provider.ExecuteTool` → `succeeded|failed|unknown`（`failedOrUnknown` :163-169：4xx=failed，其余=unknown 防重放）。
- **幂等落地**：`command_replays` 表（baseline :3306-3321：scope=agent:<actorID>、operation、key、request_hash、resource_id、response_body、state reserved/completed、invocation_id、credential_id）；库层 `internal/idempotency/idempotency.go`（advisory lock :89-94、Lookup/Save/Reserve/Complete/DeleteReserved）；CLI 的 operation ID 用于审计与确认卡幂等键；发送类命令用 `invocation_id` 派生幂等键，同 invocation 换输入=唯一约束 23505→`ErrIdempotencyConflict`（agentsendmessage :278-284）。

### A6. 权限模型与审批卡片

- 三类调用方：①人类浏览器（session cookie→principal，只带 AccountID/HumanActorID/HumanTenantID，app.go:175-187；每请求 `requireSpace` 判 Space 归属，不等返回 404）；②Agent CLI（`th_agent_*`→agentauth 三查，与业务同事务+提交前 RevalidateInTx）；③Node Services（teamhub-internal Bearer 常量令牌）。
- 审批卡：`decisions` 表（baseline :3330-3360），kind ∈ {connector_write, agent_change, question, runtime_permission, profile_setup_apps, profile_setup_sources, connection_auth, browser_connection, room_creation, computer_permission}（typedcard/decisions.go:35-45）；状态机 pending→approved→executing→succeeded/failed/unknown、denied、expired、answered、consumed、authorizing。
- 创建：`typedCards.CreateDecision`（decisions.go:209-359）——锁房间/运行时来源→幂等重放→**同类 pending 卡复用**（:291-302，防刷屏）→以 Agent actor 发 `decision_requested` 卡片消息（带 `message_cards` 行）→插 `decisions`→到期 job（TTL 24h，:52）。
- 人类决策：`POST /v0/decisions/:decisionId`（handlers_typed_card_decisions.go:15-57）→ `DecideDecision`（:478-489）→ `decisionAnswerStep.apply`（:523-595，校验 ExpectedVersion/状态→记 answer→connector_write/agent_change/AlterEgo→插 `jobs.DecisionRunArgs`（decision.run）；connection_auth approve→authorizing，OAuth 回调再 settle）。
- 执行：`decisionRunWorker`（app/decision_workers.go:16-34）→ `RunDecision`（:600-618）→ `claimDecision`（:624-660，`FOR UPDATE`，approved→executing；发现仍在 executing 且 executor 不支持 Rerun→记 unknown **绝不重跑**）→ executor → `finishDecision`（:663-691）→ `HandOffDecision`（:749-，卡片房间 @Agent 播报结果→再唤起代理；代理在跑则走 `run.steered` steering 输入，baseline :1423-1431）。
- 运行时权限评审：`permissionreview.Service.Review`（permissionreview/service.go:83-162）——`ConsumeRuntimePermission`（已批准同 digest 卡直接放行）→复用 pending 卡→调 Judge（跑在赞助人 Agent Runtime 的模型，`TEAMHUB_PERMISSION_REVIEW` 开关 config.go:115-120）→失败/needs_approval→`openCard` 发 `runtime_permission` 卡；`ActionDigest`（:166-）=工具+命令+证据哈希，批准绑定到完全相同的动作。

### A7. 数据模型与 sqlc

- 迁移：goose，`migrations/00852_baseline.sql`（6761 行）+增量至 `00884_allow_antigravity_local_runtime.sql`；`migrations/embed.go` 内嵌。
- 关键表（baseline 行号）：身份/凭据 `actors`:2210（human/agent，agent 必有 handle 无 account）、`accounts`:2761、`agent_registrations`:2223（agent_type general|anotherme、placement 三元组 computer/local_runtime/workspace_grant、assignment_revision、receives_all_messages）、`agent_access_credentials`:2786；运行时 `agent_execution_contexts`:2813、`agent_context_inbox_cursors`:2802、`agent_runtime_inputs`:3126、`agent_local_runs`:3064、`agent_local_run_inputs`:3053、`agent_runtime_status_events`:3159、`agent_service_epochs`:3179、`local_computers`:3798、`local_computer_enrollments`:3774；协作 `rooms`:2368（direct_human/agent、parent_room_id+root_message_id=线程、team_md 字段）、`room_members`:2627、`room_member_states`:4167、`room_events`:2852（room_seq 单调）、`messages`:2310（message_kind conversation|agent_runtime|task_terminal_notice|room_notice、mentioned_actor_ids、fired_routine_id、local_run_id）、`message_cards`:3838、`message_reactions`:3855；任务 `work_items`:2921、`work_item_assignments/access_grants/activities`:4755+、`work_item_room_links`:2909、`task_execution_generations/participants/facts/effects`:4399-4453、`task_meta_messages/callbacks`:2882-2908；审批/幂等 `decisions`:3330、`command_replays`:3306；连接器 `external_connections`:3720、`external_connection_upstreams`:3710、`external_connection_agent_grants`:3694（revision 乐观授权）、`composio_settings`:3323；例程/proactive `room_reminders`:4189、`room_routine_listeners`:4230、`routine_event_deliveries`:4249、`proactive_pending_wakes`:3946、`proactive_potential_items`:3966、`proactive_outputs`:3935、`proactive_conversation_windows`:3927、`proactive_guidelines`:2593；文档/知识 `documents`:2492、`document_versions`:2461、`document_bodies`:3413、`document_texts`:3592、`document_assets`:3362、`document_placements`:3531、`document_wiki_*`:3639-3693、`personal_wikis`:3913、`personal_profile_*`、`personal_insights`、`skills`/`skill_manifests`/`agent_skill_bindings`/`agent_templates`；River 自带 `river_job`/`river_queue`/`river_notification`:3981-4049。
- 关键触发器/函数（"消息唤起代理"的核心）：`publish_teamhub_realtime_wake`（:1286-1308，pg_notify）；`room_events_notify_teamhub_realtime`（:5951）→`notify_teamhub_room_event`（:946-958，每 room 事件发 `room:<id>`）；**`room_events_queue_agent_inputs`**（:5953，DEFERRABLE 约束触发器，仅 message.created）→`queue_room_message_agent_inputs`（:1522-1529）→`queue_agent_inbox_message`（:1367-1390）：`agent_inbox_recipients`（:425-475）按 inbox 找应接收的 meta/alter_ego/document Context；`agent_inbox_message_disposition`（:340-385，ignore/runtime_response/skip/notify——mentioned 或 receives_all_messages 且非线程）；`queue_agent_inbox_notification`（:1392-1460，命中在跑 Run→插 steering 输入发 `run.steered`；否则复用/创建 queued Run+handled 输入发 `run.queued`）；`queue_agent_runtime_response`（:1462-1499，decision 卡运行时应答→steering）；`river_job_due_*_wake`（:5945-5949）；`*_task_claimable`（:5961-6005）；`notify_teamhub_agent_context_changed`（:905-918）。
- sqlc：`sqlc.yaml:1-14`——schema=`migrations`，queries=`internal/store/queries`（78 个 .sql），生成 `internal/store`（pgx/v5，emit_json_tags、emit_empty_slices）；`Makefile:33-45` `make generate`/`sqlc-verify`（版本化二进制）。兜底扫描 `internal/store/queries/agent_context_wakes.sql:22-38`（`ListAgentContextsWithWaitingRuns`，丢唤醒 30 秒兜底）。

### A8. 对外接口形态

- HTTP（Gin）四组契约路由（见 A1）；错误统一 `{error:{code,message,request_id,issues?}}`（app.go:1218-1241）。
- **SSE 是唯一实时通道（无 WebSocket）**：
  - 人类 `GET /v0/events`（handlers_human_events.go:115-194）——`HumanEventsTopic`，`room=<id>:<seq>` 游标；事件 `room.event`（从 PG 补读，sendRoomEvents :277-302）、`resource.invalidated`、`stream.resync`、`session.expired`；心跳补读游标房间防通知丢失。
  - Agent Service `GET /v0/agent-runtime/wakes`（handlers_agent_wakes.go:17-54）——`AgentInboxWakeTopic`；事件 `reconcile|run.queued|run.steered|context.prepare|context.changed|task.claimable`（载荷只含 context_key，内容自取）。
  - 语音 `/v0/voice-sessions/:id/events/stream` 与内部 `/internal/v1/voice/sessions/:id/live-task-events`；语音媒体走 LiveKit（不经 TeamHub）。

---

## 附录 B：Voice 对照——Linger 语音栈 vs Neurova ASR+TTS

### B1. Linger 语音栈概览（深读结论，证据为 Linger 仓 file:line）

**形态**：LiveKit 实时媒体房间（SFU）+ 三个专用 worker 进程族（`apps/voice-runtime`，LiveKit Agents 框架）+ node-services 监督者（key 对账拉起/回收）+ TeamHub 会话/落库/调度。三种 purpose：`chat_dictation`（听写，Soniox ASR）、录音（Soniox+说话人分离+HLS 归档）、`chat_live`（xAI Grok Realtime 语音对话）。

- **流式 ASR**（`apps/voice-runtime/src/soniox.ts`）：WebSocket 到 Soniox；语义端点检测（`endpoint_sensitivity:-0.4`、`max_endpoint_delay_ms:3000`，让模型而非定时器决定一句话结束，soniox.ts:82-92）；说话人分离时段 1.5s 沉默/20s 上限强制落盘（:100-108）；**断线重连+PCM 重放**——保留 ≤65s 未确认音频，从已提交边界重放到新连接并补发 finalize，final 冲突可检（recovering-asr.ts:337-443）；15s 无响应判死、5s ping 保活。
- **media epoch 防复用**：每次消费轨道先向 TeamHub 申领 PostgreSQL 发号的递增 epoch（livekit-worker.ts:297-302；voice_runtime.go:137-149），进程重启/换 key 后绝不复用旧覆盖流。
- **确定性事件 ID 幂等落库**：`event_id=sha256(session,epoch,kind,window,text)`（livekit-worker.ts:1148-1173），TeamHub 端重放天然幂等、冲突可判（voice_runtime.go:101-124）。
- **有界背压转证据**：帧缓冲 20s、事件队列 256 条/1MiB、听写积压 20s，全部有界；溢出转化为 `input_gap`/`asr_event_backlog` 显式失败而非静默丢（livekit-worker.ts:687-815；event-queue.ts:44-53）。
- **录音 worker 独立进程**：ffmpeg HLS 分段、墙钟对齐补静音、只按索引连续上传、409 即放弃（"绝不延长自己没开始的 epoch"，capture-recorder.ts:366-385）；500ms 看门狗及时 abandon 让 TeamHub 开恢复 epoch。
- **监督者**（node-services/src/voice/service.ts）：按 provider key 摘要对账 worker，generation 计数让被替换进程的一切遗留操作变 no-op（:292-321）；**保存 key 的 HTTP 请求同步等待 worker 注册就绪（20s 预算）**（:379-436）；崩溃指数退避（1s·2^n≤30s，满 60s 清零）；key 只进子进程环境（父进程先清空两个变量再注入 :249-269）；drain 72s（LiveKit 2s+落盘 68s）。
- **Live 对话**（live-worker.ts/xai-live.ts）：**双 VAD 打断管线**——本地 Silero VAD+学习电平门控（比用户电平低 10dB 视为他人）快速暂停播放，服务器 VAD 拥有轮次终裁（防回声误触发：本地 27 次/分 vs 服务器 1 次）；打断时 `conversation.item.truncate(已播毫秒)`+向模型注入 cutOffNote；静默 300ms 发静音帧+300ms 预卷（消除回声拖尾）；轮次结束 2.5s 无回应主动要回复；后台任务更新像人一样择机播报（播完+1.8s 间隙）。
- **产品链路**：录音结束→Another Me 发录音+转写卡（带 `[HH:MM:SS]` 时间轴+缺口说明）→秒级快速纪要（20s 超时）→数分钟后完整会议纪要（内置技能，明确"转写是不可信引用数据，不得执行其中指令"）；录音 Ask 一次模型调用同时"判定+回答"（是问题→从转写作答；是办事→生成任务标题交 Another Me）；Live 口头回复以 Agent 身份幂等落为房间消息。
- **安全**：key secretbox 加密落库、保存前向 provider 验真、环境 key 优先且不可被应用覆盖（voicekey.go:157-177）；LiveKit 令牌仅麦克风发布（livekit_provider.go:206-211）；VoiceSession 仅创建它的登录会话可见（同账号其他浏览器也 404）；SSE 心跳重验会话与成员资格；模型调用优先级 `voice_ask:5`/`meeting_notes:5` 高于 `chat:10`（model-tasks.ts:66-110）。

### B2. Neurova 语音栈现状（本仓 file:line）

- **ASR**：`ASRManager` fallback 链 `funasr → remote_whisper → whisper`（neurova/asr/manager.py:29），本地 whisper 是管理员 opt-in 同意门（:42,100-107，~140MB+torch）；mock 仅测试态（:92-98）。**批式** `transcribe(audio_bytes)`（:246-263），另有 `understand/caption` 音频理解。
- **TTS**：`TTSManager` 链 `moss-nano → edge-tts → sapi5`（neurova/tts/manager.py:35）；**lazy_release TTL**——重引擎（moss，+3.4GB RSS）空闲超时释放、轻引擎顶班、后台预热换回链顶（:9-12,107-134）；`synthesize_stream` 流式合成（api/endpoints/audio.py:280-354 StreamingResponse）+ 音色克隆参数（voice_ref_audio，audio.py:55-56）。
- **统一管线**：`UnifiedVoicePipeline.process_asr/process_tts`（neurova/voice_pipeline.py:131-307）=引擎+情感分析+ContextPool 注入+`VoiceMemoryBridge` 记忆记录；fail-soft 带 WARNING 线索（:82-129）。
- **渠道语音**：出站三形态契约 `none/audio_file/voice_bubble` + 两道闸 + AST 守卫"声明能力必须有真出口"（neurova/channels/voice_egress.py:26-33,52-80）；入站口径单点（`audio_bytes` 键、10MB 上限、20s 转写超时，voice_ingress.py:22-36）。
- **前端**：ASR 主路是浏览器 **Web Speech API**（useASRRecording.ts:90,124 `recognition.start()`）+ 录音上传 `/audio/transcribe` 兜底（:158-165）；TTS 逐句保序串行请求 `/synthesize-stream` 播放（useStreamTTS.ts:5）。
- **短板**：后端无 WebSocket 流式 ASR（grep 证实 audio.py 无 websocket）、无服务端端点检测/turn 终结、无说话人分离、无打断（barge-in）控制、无媒体 epoch/事件幂等发号；实时性完全寄托在浏览器私有 API 上。

### B3. 逐维对照

| 维度 | Linger | Neurova | 强者 |
|---|---|---|---|
| ASR 模式 | 流式 WS+语义端点+分离+重放 | 批式上传；"实时"靠浏览器 Web Speech API | Linger |
| ASR 引擎 | Soniox（云端，唯一） | FunASR/Whisper 本地+remote，同意门，mock 隔离 | Neurova（可控性/隐私） |
| TTS | 无自有 TTS（Live 靠 xAI 一体化） | moss-nano/edge/sapi5 链+流式+克隆+TTL 释放 | Neurova |
| 实时对话 | LiveKit 房间+双 VAD 打断+轮次仲裁 | 无 | Linger |
| 可靠性 | media epoch 发号、事件确定性 ID 幂等、背压转证据、断线文本保留 | 引擎 fallback 链、fail-soft 告警（无流式故无此问题） | Linger |
| 录音产品链 | 录音→转写卡→快速纪要→Ask→任务 | voice_memory_bridge 记忆记录、openclaw_transcript 转换器 | Linger |
| 渠道出站契约 | （语音即房间消息） | 三形态+两道闸+AST 守卫 | Neurova |
| Key/权限治理 | 子进程 env 隔离、验真后存、环境优先、会话级 404、心跳重验 | 常规 | Linger |
| 调度 | voice_ask:5 > chat:10 优先级 | 无语音专用优先级 | Linger |

### B4. 可借鉴清单（按价值排序，给 Neurova 落点）

1. **后端流式 ASR 通道**（最高价值）：Neurova 前端实时听写 currently 依赖浏览器 Web Speech API（Chrome 专属、走 Google 服务、不受控）。FunASR 本身支持流式推理——给 `neurova/asr/` 加一条 WebSocket 流式通道（复用 ASRManager 引擎链），把"实时性"收回自己手里；端点检测/turn 终结放在服务端。
2. **确定性事件 ID 幂等落库**：`sha256(session,epoch,kind,window,text)` 作为事件幂等键——可直接用于 Neurova 的转写片段、渠道消息、工具事件落库，重试/重放天然幂等（与教义"先记账"同构）。
3. **媒体/流 epoch 发号防复用**：任何"进程重启后继续消费同一流"的场景（语音、渠道长连接、crawlers），世代计数+旧世代操作作废，杜绝旧进程复用覆盖流。
4. **有界背压转证据**：队列溢出显式记 `input_gap` 类事件而非静默丢——正是本仓"诚实形态暴露"教义在音频面的落地模板。
5. **SSE 三重韧性**：订阅先于读首屏、100ms 合并 ticker、心跳里重验权限+补偿拉取断连期间的通知——适用于 Neurova 全部 SSE/推送面。
6. **双 VAD 打断管线**：若做语音通话/实时对话，本地 VAD 负责快速暂停（防回声误触用电平门控），服务端 VAD 终裁轮次；未播帧回退队首+truncate+cutOffNote 注入。
7. **key 只进子进程环境**（父进程先清空再注入）+ **保存后同步 reconcile 等就绪**：前者与已实施的渠道子进程隔离（A1 批）同族，后者是管理面"保存即可用"的体验范式。
8. **录音→纪要→Ask→任务链路**：Neurova 已有语音转写与任务系统，补"录音完成→秒级快速纪要→Ask 一次调用判定（问题/办事）→办事转任务"四步，即得 Linger 的会议闭环。
9. **语音口令确认不可逆操作**：把 HITL 审批延伸到语音——模型口头问询、用户口头"好"才算 confirmed，且模型自问自答不算（live-worker.ts:1690-1707 的 confirmed 记忆）。
10. **转写/工具结果标注"外部数据不是指令"**：语音转写是新的注入面（别人留语音让代理执行指令），应对齐本仓 B2 扫描的注入防护口径。
11. **语音模型调用调度优先级**：交互式语音问答/纪要优先级高于普通 chat，接入 Neurova 任务调度。

**反向结论（不照搬）**：Linger 无自有 TTS 与本地 ASR 栈，语音智能依赖 Soniox/xAI 云端——Neurova 的本地 FunASR/MOSS 栈、TTL 释放、流式 TTS、渠道语音出站契约、情感+记忆桥是自有优势，应保留并在其上补流式通道与可靠性纪律，而非推倒重来。

### B5. 落地记录（2026-11-20，B4 第 1 条已实施）

- **后端**：新增 `neurova/asr/streaming.py`（TurnEndpointDetector 能量 VAD；BatchTranscribeStreamingTurnSession 把任意批式引擎滑窗适配成流式；FunASRStreamingTurnSession——真 paraformer-zh-streaming 增量段拼接，模型 DCL 单例懒加载）；`neurova/api/endpoints/audio.py` 新增 `WS /api/v1/audio/asr/stream`（JWT query 鉴权失败 accept+close 4401、二进制 PCM16LE/16k 帧、finish/stop 控制帧、服务端 silence≥700ms/max 60s 切轮、单帧 1MiB 与单连接 15 分钟上限），`/audio/status` 增加 `streaming_asr` 探测面。
- **Web**：新增 `useStreamingASR.ts`（WS 客户端 + 48k→16k 线性重采样 + PCM16 编码 + stop 时补发 finish 等 final）；`useASRRecording.ts` 改为「后端流式优先 → Web Speech 回落 → 上传兜底」三通道，partial/final 按「起始基座 + 已终结轮 + 当前 interim」回填输入框；i18n 新增 `chat.asrUnavailable` ×11 locale。
- **鸿蒙**：新增 `libs/adapters/AsrStreamClient.ets`（NetworkKit webSocket，token 走 query）；`ChatPage.ets` 在端侧 CoreSpeechKit 引擎创建失败时回落 `startBackendVoice()`（AudioCapturer 复用、整帧直发、final 成句即 sendMessage）。
- **依赖**：requirements.txt 补登 `funasr>=1.4.27`、`kaldi-native-fbank>=1.23.3`——funasr 此前被 `funasr_engine.py` 裸依赖却从未登记（预存缺口一并收口）；无 torchaudio 时 funasr 必需 knf 作 fbank 后端。
- **验证**：单测 18 绿（新增）+ 既有 ASR/音频面 52 测试零新增失败；`hvigor assembleHap` BUILD SUCCESSFUL；vitest 95 绿 + `vue-tsc --noEmit` 0 错；真后端 live-verify 三项 PASS——无 token close 4401、status 探测 available、moss-nano TTS 合成"你好，今天天气怎么样"→ WS 逐 20ms 帧喂入 → FunASR 流式 partial 单调增长 → silence 切轮 final 命中全文。

### B6. 增强项落地（2026-11-20 同日追加）

1. **语言协商**：`/asr/stream` 新增 `?language=zh|en`（非法值回落 zh，服务端白名单 `_ASR_STREAM_LANGUAGES`）；Web 端按界面 locale 传参（zh-CN→zh，其余→en）。单测 +2（language 透传/缺省 zh），共 20 绿。
2. **Web 录音条通道徽标**：`ChatComposerArea.vue` 录音条在流式通道激活时显示 `chat.asrCloudTag`（"云端识别"）胶囊徽标（仅主题令牌配色）；`usingStreaming` 状态接入 UI。i18n 新键 ×11 locale。
3. **鸿蒙识别通道设置项**：`SettingPage` 分组一新增"语音识别通道"行（AppIcon mic，当前值展示），点按弹 AlertDialog 三选一（自动（端侧优先）/仅设备端/仅后端，`buttons` 数组形态——本 SDK 的 AlertDialog 无 tertiaryButton 字段），写入 `ConfigManager('asr_channel')` 并持久化；`ChatPage.toggleVoice` 遵从该配置（backend=跳过端侧 / device=不回落 / auto=失败回落）。ArkTS 坑两处：`Record` 字面量违反 no-untyped-obj-literals（改 Map.set）；AlertDialog 三按钮须用 WithOptions 的 `buttons` 数组。
- **回归**：后端 54 绿；vitest 96+56 绿；vue-tsc 0 错；hvigor BUILD SUCCESSFUL。
