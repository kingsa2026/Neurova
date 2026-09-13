# Neurova × OpenAI Codex 代码级对比（2026-09-14）

> 对比对象：openai/codex @ main `516f2780`（2026-09-13 快照，7804 文件，`codex-rs/` 下 100+ crate）。
> 上游源码位置：`E:\项目\codex-compare\codex`（浅克隆，供后续翻阅）。
> 本文所有 Codex 侧引用均为该仓库内路径:行号；Neurova 侧引用为本地仓库路径:行号（同日核实）。

---

## 0. TL;DR

Codex 已经不是"一个 CLI"，而是一个**以协议为中心的 agent 平台**：core 只认 Op/Event 双队列，TUI、IDE(app-server)、非交互 exec 三种客户端形态全部走同一套 RPC 面（`thread/start|resume|fork` + item 事件），客户端只是渲染器差异。沙箱三平台真隔离 + 审批升级梯 + "审批即策略持久化"，是这个仓库最扎实的部分；会话式 shell、apply_patch、auto-compact 阈值、AGENTS.md 层级注入、hooks 兼容 Claude Code，都是可以直接抄作业的成熟设计。

**评分（10 分制）**：

| 维度 | Codex | Neurova | 一句话 |
|---|---|---|---|
| 任务模型与 turn 循环 | 9.5 | 6.5 | Codex 任务抽象（TaskKind+abort 生命周期）+ steer 语义成体系 |
| 沙箱与审批 | 9.5 | 5.5 | Codex 三平台真隔离默认开；Neurova 沙箱默认关、审批有但无归因升级链 |
| 协议与客户端形态 | 9.5 | 6.5 | Codex 事件按 item 建模、重放式可靠性；Neurova SSE 裸事件流 |
| 上下文工程与压缩 | 9 | 7 | Codex 90%/95% 双阈值+handoff 压缩；Neurova 超预算即折叠无阈值语义 |
| 会话持久化与恢复 | 9 | 6.5 | Codex rollout JSONL 多类型行、fork 无损截断；Neurova JSON 快照+fork 有 |
| 流式与重试韧性 | 9 | 6.5 | Codex 重试白名单+WS→HTTPS 降级+配额事件化；Neurova 有 retry_status 雏形 |
| 工具面 | 9.5 | 7 | 会话式 shell/head+tail 截断/apply_patch/tool_search 分层全面领先 |
| Skills/MCP 扩展面 | 9 | 7.5 | SKILL.md 三层注入、MCP oauth 齐全；Neurova SKILL.md 已支持、oauth 已有 |
| 记忆系统 | 8 | **8.5** | **Neurova 领先**：17 维分类/MoE/温度/结晶 vs Codex 简单两阶段笔记 |
| 配置与认证 | 8.5 | 6.5 | Codex 九层 precedence+keyring；Neurova 两层 JSON、密钥明文字段 |
| 多 agent | 8.5 | 7 | Codex mailbox+trigger_turn 解耦；Neurova swarm/team 已有但嵌套阻塞 |
| 代码评审/评测 | 8.5 | 7 | Codex /review 受限子会话+结构化 findings；Neurova 有 benchmark 无 review 会话 |
| **综合** | **9.0** | **6.9** | Neurova 记忆/渠道/中文生态领先，harness 硬件层全面落后 |

**十大启发（按杠杆排序）**：

1. **协议即产品**：core 对外只有 `Op`（21 个变体）/`EventMsg`（50+ 变体）两个 `#[non_exhaustive]` 枚举 + 提交/事件双队列（`protocol/src/protocol.rs:600,1357`），任何传输（进程内/stdin/UDS/WebSocket）都能承载；TUI/IDE/exec 复用同一 RPC 面（app-server-protocol 共 166 个方法），可靠性靠"**重放而非重传**"——断线后 `thread/resume` + `thread/items/list` 拉历史重建，事件本身无 seq。
2. **事件按 item 建模**：`item/started|updated|completed` + 各 item 专有 delta 通道（agentMessage/plan/commandExecution output/reasoning），UI 分区渲染与历史回放天然成立，比 Neurova 现在的裸 chunk/reasoning/tool_call 事件流结构化得多。
3. **沙箱默认开、网络默认关**，审批升级梯完整：`AskForApproval{UnlessTrusted,OnRequest,Granular,Never}` + 每命令 `SandboxPermissions` 覆盖 + 沙箱拒绝启发式归因 → 带 reason 的自动升级审批（`core/src/tools/orchestrator.rs:122-540`）。
4. **审批即策略持久化**：用户批准 execpolicy 修正/网络放行后自动追加规则到用户级规则文件并热加载（`core/src/exec_policy.rs:464-558`），"accept for session" 用规范化命令做 key 缓存（`core/src/tools/sandboxing.rs:39-116`）。
5. **会话式 shell 是长任务最大杠杆**：`exec_command` 返回 `session_id` + `write_stdin` 轮询，yield 分级 250ms~30s、head+tail 双端缓冲、64 进程上限（`core/src/unified_exec/mod.rs:73-82`）。
6. **上下文工程三板斧**：`<environment_context>` 首次全量后续只发 diff；AGENTS.md 根→cwd 层级拼接+字节预算；auto-compact = `min(config_limit, window×90%)` 触发、×95% 硬顶、压缩 prompt 是"给下一个 LLM 的交接摘要"、压缩自身失败则删最旧一条重试保证收敛（`protocol/src/openai_models.rs:521`、`core/src/compact.rs:235-353`）。
7. **加密 reasoning 回放**：`store:false` + `include=["reasoning.encrypted_content"]`，思维链以密文形式随客户端历史回放，跨重试/跨压缩不丢（`core/src/client.rs:862-889`）。
8. **hooks 直接兼容 Claude Code wire 格式**：12 种事件、stdin JSON/stdout JSON、matcher 分组、600s 超时、sync 有控制权/async 仅副作用、大输出 spill 到磁盘回灌路径（`hooks/src/schema.rs:279`、`hooks/src/output_spill.rs:11-131`）。
9. **工具/技能注入分层省 token**：工具分 `ToolExposure{Direct,Deferred,CodeModeOnly,Hidden}`，Deferred 工具经 `tool_search` 按需加载（`tools/src/tool_executor.rs:51-63`）；skills 三层注入（目录清单+超预算自动别名压缩 → `$mention` 全文注入 → shell 隐式调用遥测）。
10. **memories 是后台双阶段管线**：租约认领防重 → 模型抽取 → git 基线工作区 diff → consolidation 子代理重写 MEMORY.md，输出 `<memory_citation>` 行级溯源（`memories/README.md:29-152`）。

---

## 1. Codex 快照与仓库布局

- 入口多形态：`codex`（TUI，ratatui）、`codex exec`（非交互，`--json` JSONL 事件流/`--output-schema` 结构化输出/`resume`/`fork`/`review`）、app-server（IDE，166 方法 JSON-RPC）、`codex mcp`（oauth 管理）、cloud-tasks（ChatGPT 云端任务浏览/apply）。
- core 之外的重量级 crate：`sandboxing/`（+`linux-sandbox/`、`windows-sandbox-rs/`、`windows-sandbox-service/`、`mxc-sandbox/`、`network-proxy/`）、`execpolicy/`（Starlark）、`hooks/`、`skills/`、`apply-patch/`、`rollout/`、`thread-store/`、`config/`、`code-mode/` 四件套（V8 内跑模型生成 JS 编排工具）、`agent-roles/`/`agent-graph-store/`（多 agent）、`memories/`、`guardian`（风险审查）、`models-manager/`、`otel/`。
- 文档齐备：`docs/sandbox.md`、`docs/execpolicy.md`、`docs/skills.md`、`docs/agents_md.md`、`docs/config.md`、`codex-rs/docs/protocol_v1.md`。

---

## 2. 机制深读 × Neurova 现状

### 2.1 协议与客户端形态

**Codex 做法**
- `Op`（UI→core）全量：Interrupt / CleanBackgroundTerminals / Realtime* / **TurnInput{request,mode}**（mode = StartOrSteer/StartIfIdle/Steer，"插话"是一等语义）/ RecoverTurn / SuspendTurnAndShutdown / ThreadSettings / TurnSettings / InterAgentCommunication / **ExecApproval/PatchApproval** / ResolveElicitation / UserInputAnswer / RequestPermissionsResponse / DynamicToolResponse / RefreshMcpServers / ReloadUserConfig / Compact / SetThreadMemoryMode / Review / ApproveGuardianDeniedAction / Shutdown / RunUserShellCommand（`protocol/src/protocol.rs:600-760`）。
- `EventMsg`（core→UI）按生命周期/流式 delta/审批/执行过程/TokenCount 分组；TurnItem 18 变体；审批请求是 **server→client 的 RPC 请求**（`item/commandExecution/requestApproval` 等），天然配对响应与超时（`app-server-protocol/src/protocol/common.rs:1751-1817`）。
- 事件无 seq，可靠性 = rollout 持久化 + resume 重放（`docs/protocol_v1.md:61`）。
- exec 非交互 = "无 UI 的 app-server 客户端 + 两个事件渲染器"，`--json` 输出极简 schema：`thread.started → turn.started → item.started/updated/completed → turn.completed{usage}`（`exec/src/exec_events.rs:11-133`）。

**Neurova 现状**
- SSE 裸事件流：chunk/memory_progress/reasoning/retry/usage/tool_call/tool_result/approval_required/artifact + done/stopped/error（`neurova/api/endpoints/console.py:360,895-916`）；另有 WS 广播（`neurova/agent/chat_pipeline.py:1720,1791`）。
- 中断有真实现：`POST /chat/stop` → `task_tracker.request_session_stop` 真取消 asyncio task + 落库取消意图（`console.py:925,948,957`）。
- run 台账 `agent_runs` 表有 queued/running/finished 状态机 + 同 session 单活唯一索引 + 启动 reconcile，但**无跨重启续跑**（`neurova/core/agent_run_store.py:20-23,61`）。
- 插话：无 steer 语义；有队列卡片（pending 队列）但不是"注入进行中 turn"。

**差距**：事件无 item 身份（前端只能靠拼对话）、审批不是请求-响应配对、无断线重放、无 steer。

### 2.2 会话核心与任务模型

**Codex 做法**
- `ThreadManager → CodexThread::submit(Op)`；空闲开新 turn、进行中则 steer 进 pending input（`core/src/codex_thread.rs:227,328`）。
- `SessionTask{kind,run,abort}` 统一抽象，`TaskKind = Regular | Review | Compact`；spawn_task 先 `abort_all_tasks(Replaced)`；中断走 cancel token → 100ms 优雅退出 → force abort → **写模型可见中断 marker** → TurnAborted 事件（`core/src/tasks/mod.rs:178,276,878-981`）。
- 工具编排：读写锁——声明可并行的工具拿读锁并发、其余写锁串行；流结束后统一按序收集（`core/src/tools/parallel.rs:124-177`）。
- turn 级 token 记账 = 快照差值，TokenCount 事件刻意推迟到用户等待点之后发，携带 rate_limits（`core/src/tasks/mod.rs:691-749`、`core/src/session/mod.rs:4705`）。

**Neurova 现状**
- ChatPipeline 六步（`_init_agent_state → _step_activity_tracking → _step_pre_llm_checks → _step_inject_attachments → _step_retrieve_and_build_context → _step_llm_call → _step_post_processing`，`neurova/agent/chat_pipeline.py:374`）；文本工具续调上限 5 轮（chat_pipeline.py:2011）。
- 原生并行工具是声明制：同轮全部 concurrency-safe 才 gather，否则串行（`neurova/agent/loops/base.py:94-104`）。

**差距**：任务抽象/中断 marker/记账事件化基本可比，主要差 steer、TaskKind 化（compact/review 复用同一生命周期）。

### 2.3 上下文工程与压缩（Neurova 已有底子，差阈值语义与收敛保证）

**Codex 做法**
- 环境上下文：`<environment_context>` 首次全量（cwd/shell/date/timezone/network/filesystem/subagents），后续 turn 只发 WorldState diff（`core/src/context/world_state/environment.rs:317`、`session/mod.rs:3597`）。
- AGENTS.md：cwd 向上找项目根（`.git` 标记），**根→cwd 逐级拼接**，每级优先 `AGENTS.override.md`；`project_doc_max_bytes` 总预算截断；untrusted 项目不加载（`core/src/agents_md.rs:186-267,65`）。
- auto-compact：`auto_compact_token_limit() = min(config_limit, resolved_window×9/10)`，硬顶 = window×`effective_context_window_percent`(默认 95)（`protocol/src/openai_models.rs:521-533,966`）；触发点三处：pre-turn / mid-turn roll-over / 手动 `Op::Compact`。
- 压缩 prompt（已核实原文）：*"You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task…"*，产物 = 最近用户消息（20k 预算）+ 前缀 + 摘要，开新 window（window_id 递增）（`prompts/templates/compact/prompt.md`、`core/src/compact.rs:60,353`）。
- **压缩失败收敛保证**：压缩请求自身 `ContextWindowExceeded` 时删最旧一条重试（`compact.rs:307-315`）；mid-turn 压缩后用 `InitialContextInjection::BeforeLastUserMessage` 精确控制初始上下文重注入位置（`compact.rs:71-77`）。

**Neurova 现状**
- 上下文池 + 语义选取（`neurova/context/orchestrator.py:349`、`semantic_drawer.py:167` 向量+关键词+新鲜度打分，默认 16000 tokens）。
- 压缩 = `_apply_window_budget` 超预算折叠老消息 + 尾窗，跨轮增量摘要缓存（`orchestrator.py:995`）；预算 = 模型预算×60% 钳 [3000,100000]（`orchestrator.py:929`）；手动 `/compact` 有（`orchestrator.py:1092`）。**无自动压缩开关、无 90%/95% 双阈值语义、压缩失败无收敛保证**。
- **AGENTS.md/workspace 文档不自动注入**（全库无读取进 prompt 的代码；system prompt 只拼 soul/性格/宪法/环境段/工具描述，`neurova/context/orchestrator.py:1192`）。

### 2.4 会话持久化与恢复

**Codex 做法**
- rollout JSONL 多类型行：`SessionMeta | ResponseItem | InterAgentCommunication | Compacted | TurnContext | TokenUsageRecord | WorldState | SecurityRiskScore | RetainedContext | EventMsg | RealtimeItem`（`codex-rs/history/src/lib.rs:122`）；入队+异步写手，turn 终止事件前后强制 flush（`rollout/src/recorder.rs:1748,1031`）。
- resume = 纯历史重放重建 session（`thread_manager.rs:1118`）；fork 三入口，可截到最后 N 个用户 turn，Interrupted fork 追加 TurnAborted+中断 marker（与 live 中断**同构**）（`thread_manager.rs:1342-1425,2401`）。

**Neurova 现状**
- JSON 文件快照（sessions/<agent_id>/<date>/<sid>.json，原子写+RLock+坏文件隔离，`neurova/session_manager.py:191-355`）；fork 已有（`POST /chat/sessions/fork` 按 until_timestamp 截取，`console.py:1474`）；轮次编辑仅 metadata，无正文改写（`session_manager.py:1690`）。
- 差距：不是 append-only 事件流 → 无法断线重放/无 timeline 接口；fork 有了但无中断 marker 同构。

### 2.5 流式与重试韧性

**Codex 做法**
- 重试白名单（`is_retryable`：Stream/Timeout/ConnectionFailed/InternalServerError…可重试；UsageLimit/QuotaExceeded/ContextWindowExceeded/InvalidRequest/TurnAborted 不可重试，`protocol/src/error.rs:372-407`）。
- 退避 200ms×2 + jitter 0.9-1.1；连接类错误可无限重连（5s→60s 封顶）；重试耗尽尝试 WebSocket→HTTPS 粘性降级并清零计数（`core/src/responses_retry.rs:17-107`）。
- 配额：响应头 `x-codex-*` 解析为 `RateLimitSnapshot` 冒泡成事件；`UsageLimitReached` 携带细分类型（credits 耗尽/用量上限）。

**Neurova 现状**：openai_loop 已 yield `retry_status` 事件（`neurova/agent/loops/openai_loop.py:583-677`），但无错误分类白名单、无配额快照事件、无传输降级。

### 2.6 沙箱与审批（差距最大的一维）

**Codex 做法**
- 双轨：`SandboxPolicy`（read-only / workspace-write / danger-full-access）+ 新 `PermissionProfile`；平台后端 Seatbelt(sbpl 拼接)/Linux(bwrap+seccomp，自调用 helper)/Windows(RestrictedToken 默认关→Elevated 服务/MXC)。**网络默认禁**，域名管控走 network-proxy（deny 优先 glob、Limited 模式仅 GET/HEAD/OPTIONS、Ask 决策冒泡成审批）（`sandboxing/src/manager.rs:41-83`、`protocol/src/permissions.rs:78-90`、`network-proxy/src/config.rs:22-28`）。
- 可写根白名单：Root 读 + ProjectRoots 写 + /tmp；`.git`（解析 gitdir 指针）/`.agents`/`.codex` 默认只读 carveout；保护祖先禁 rename；symlink 规范化防提权（`protocol/src/permissions.rs:799-893,2212-2255`）。
- 审批升级梯：`ExecApprovalRequirement{Skip,NeedsApproval{reason},Forbidden}` → 首跑沙箱内 → 失败若疑似沙箱拒绝 → `SandboxErr::Denied{output 截断 512 字符}` → 带 retry_reason 请求审批 → 批准后无沙箱重跑；deny-read 生效时禁止绕过（`core/src/tools/sandboxing.rs:152-295`、`orchestrator.rs:372-447`）。
- 归因启发式（已核实）：exit≠0 且输出含 `operation not permitted/permission denied/read-only file system/seccomp/landlock/sandbox` 关键词 → 判沙箱拒绝；先排除 2/126/127；Linux `128+SIGSYS` 直接判定（`sandboxing/src/violation.rs:33-183`、`denial.rs:50-71`）。
- `ReviewDecision` 全量：Approved / ApprovedExecpolicyAmendment / **ApprovedForSession** / ApprovedMcpPolicyAmendment / NetworkPolicyAmendment / Denied / TimedOut / Abort（`protocol.rs:4090-4141`）。
- execpolicy = **Starlark DSL**（已核实 Cargo.toml 依赖 starlark）：`prefix_rule(pattern, decision, match 示例自校验, justification)` + `network_rule(host, protocol, decision)`；决策三值 Allow/Prompt/Forbidden；`bash -lc` 先解析成命令序列再逐段评估；仓库**不内置任何 .rules**，默认行为靠启发式+审批策略（`execpolicy/src/parser.rs:347-473`、`core/src/exec_policy.rs:662-855`）。
- 风险双层：异步评分器（不进模型上下文）+ 阻塞 guardian 审查（Low/Medium/High/Critical → Allow/Deny），deny 可被用户 `ApproveGuardianDeniedAction` 人工覆盖（`protocol/src/security_risk.rs:12-24`）。

**Neurova 现状**
- 沙箱骨架已有：`neurova/sandbox/exec_sandbox.py`（ProcessSandbox/Bubblewrap/Seatbelt/Windows RestrictedToken，`SandboxSeverity{NONE,NETWORK_OFF,READ_ONLY,FULL}`:29），但强制开关**默认关**（`NEUROVA_TOOL_SANDBOX_ENFORCE=="1"` 才生效，`neurova/security/governance.py:86-95`）。
- 审批：`ApprovalManager` SQLite 状态机（`neurova/security/approval_manager.py:187,245`）+ `ApprovalLevel{NONE,SMART,ALWAYS}` + `DangerousCommandDetector` + 审批记忆/白名单；治理四级裁决 allow/deny/ask/sandbox（`tool_executor.py:1328`）。
- 差距：**没有"沙箱拒绝归因→带 reason 自动升级审批→批准重跑"链**；审批记忆 key 未规范化（无命令规范化）；无网络域名策略；风险评级无。

### 2.7 工具面

**Codex 做法**
- 内置工具：`exec_command`+`write_stdin`（会话式 shell，yield 250ms~30s、空轮询 5s 起、Windows 首轮 10s 地板、输出 1MiB head+tail、默认 10k tokens、64 进程上限，已核实常量 `core/src/unified_exec/mod.rs:73-82`）/ `apply_patch`（freeform grammar 非JSON，四级模糊定位：精确→rstrip→trim→Unicode 标点归一；内存推导新内容后**一次性原子写盘**；`<<'EOF'` heredoc 自动剥离容错，`apply-patch/src/parser.rs:145-191`、`seek_sequence.rs:12-80`）/ `update_plan`（`{plan:[{step,status}]}`，**至多一个 in_progress**，Plan 模式下禁用）/ `view_image` / `request_permissions` / web_search / file_search 等。
- 注册统一走 `dispatch_any_with_terminal_outcome`：PreToolUse hook（可改写参数）→ 执行 → PostToolUse hook（可拦截/替换结果）（`tools/src/registry.rs:495-756`）。
- 工具输出 token 预算 `tool_output_token_limit` 按模型下发。

**Neurova 现状**
- `BuiltinToolRegistry` OpenAI function schema（`neurova/builtin_tools.py:1012,1069`）+ Anthropic/Google 转换（`tool_layers/openai_schema.py`）+ `ToolCapabilityGraph` topo 分层并行（`capability_graph.py:179,262`）。
- 输出溢出：大结果 offload 落盘+指针（`loops/base.py:270-280`），SSE 展示截断 [:2000]；超时 30s 默认（`execution_engine/tool_engine.py:477`）。
- 差距：**截断未告知模型被截**（SSE 的 [:2000] 只是展示层，但工具结果进模型时无 head+tail 结构、无 original_token_count）；无会话式 shell（长命令只能一次性等完或超时）；文件编辑无 apply_patch 式原子性。

### 2.8 Skills / MCP

**Codex 做法**
- SKILL.md frontmatter：`name`(≤64)/`description`(必填)/`metadata.short-description` + 扩展 `interface{display_name,icons,…}`、`dependencies.tools[{type=mcp,…}]`、`policy{allow_implicit_invocation}`；YAML 解析失败逐行加引号自修复（`skills/src/parser.rs:44-181`）。
- 发现路径（已核实）：配置层 skills/ → `$CODEX_HOME/skills`(弃用) → `~/.agents/skills` → 系统层 → 插件根 → **cwd→项目根逐级 `.agents/skills/`**，按路径去重（`ext/skills/src/host_roots.rs:24-71`）。
- 注入三层：目录清单（超 `skills.max_context_tokens` 自动改用别名渲染）→ `$mention` 全文注入 → shell 隐式调用遥测并自动拉起 MCP 依赖（`ext/skills/src/render.rs:492-536`、`core/src/session/turn.rs:941-1050`）。
- MCP：工具按 server 命名空间注册、server 级 deny/omit 策略、oauth 动态注册+回调端口、elicitation 通道；TUI 动态工具经进程内 MCP server 注入 core（`codex-mcp/src/tools.rs:108-147`）。

**Neurova 现状**
- SKILL.md 已支持（`hub_client._parse_skill_md:674`，注册为 SkillDocSkill 指令型，`market_registry.py:13`），安装走 security/skill_scanner 注入扫描+权限门（`hub_client.py:479`）；MCP 客户端+PKCE/授权码 oauth 均已有（`neurova/tool_layers/mcp_oauth.py:50,296`）。
- 差距：技能注入无 token 预算/别名压缩；无 `$mention` 全文注入语义；MCP 无 elicitation。

### 2.9 Memories（Neurova 领先的一维，但可抄两点）

Codex memories = 后台两阶段：租约认领 rollout → 模型抽取 raw_memory/rollout_summary → 全局锁按 usage_count 选 top-N → **git 基线工作区 diff** → consolidation 子代理重写 MEMORY.md（无审批无网络）（`memories/README.md:29-152`）；读取时 `memory_summary.md` 注入开发者指令（超限截断）+ 可选 `memories.list/read/search` 工具命名空间；输出 `<memory_citation>`（MEMORY.md 行区间+thread_ids）流式解析溯源。
Neurova 的 17 维分类/MoE/温度/结晶远比这复杂——**可抄的是：租约认领防重（对应我们修过的 UNIQUE fingerprint 事故）、`<memory_citation>` 行级溯源块、外部上下文污染时自动 disable memory**。

### 2.10 配置、认证与多 agent

- Codex 配置九层 precedence 数值化：PackagedDefaults(-10)→Mdm(0)→System(10)→Enterprise(15)→User(20/21 profile)→项目 .codex/(25)→`-c` SessionFlags(30)→LegacyManaged(40/50)（`config/src/config_layer_source.rs:6-48`）；密钥 keyring（服务名 "Codex Auth"，键含 codex_home 哈希）+ auth.json 0600 回退（`login/src/auth/storage.rs:39-46`）。
- **Neurova**：两层（`neurova/shared_config.py:37` 全局 + agent 级），provider `api_key` 是**明文 JSON 字段、无 keyring/Fernet**（`neurova/shared_config.py:15,109-127` 已核实）——与 09-03"密钥不在项目内泄露"的排查结论不冲突（那次是泄露面排查），但存储形态本身是安全债。
- 多 agent：Codex `AgentRegistry`（spawn 深度限制/昵称去重）+ **邮箱+trigger_turn 解耦**（子 agent 完成消息进父线程 mailbox，父空闲时统一调度唤醒，不嵌套阻塞）+ Role 覆盖只能收窄不能越权（`core/src/agent/registry.rs:17,87-91`、`session/mod.rs:2340-2430`）。Neurova 有 SubAgentManager/SwarmManager（配额硬限+流式透传）/AgentTeam(ACP)/scheduler（`neurova/agent/subagent.py:103`、`swarm.py:120`、`team.py:88`），但完成回传是嵌套等待模式。

---

## 3. 可落地清单

> 遵守项目约束：只提升不下降、不动核心框架、修复类净 LOC≤0 不适用于新增功能但每条都给最小验收。P0 = 低风险高杠杆可立即做；P1 = 中等工程量；P2 = 观望或大件。

### P0（建议立刻排队）

| # | 事项 | 现状锚点 → 做法 | 验收 |
|---|---|---|---|
| P0-1 | **AGENTS.md/workspace 文档自动注入** | 现状无注入（§2.3）。做法：`ContextOrchestrator.build_system_prompt`(orchestrator.py:1192) 前加 workspace 文档收集器——agent_workspaces/<agent_id>/ 下 AGENTS.md/CONTEXT.md 根→子目录层级拼接 + 字节预算截断（默认 16KB） | agent 带 AGENTS.md 时 system prompt 可见其内容；预算超限有截断标记；无文档零开销 |
| P0-2 | **压缩双阈值+失败收敛** | orchestrator.py:995/929。做法：折叠触发 = `min(模型预算×60%, window×90%)`；新增"压缩摘要生成失败→丢最旧 1 条重试"循环（上限 3）；暴露 `auto_compact_enabled` 配置 | 人为触发窗口溢出：90% 即压缩；摘要模型失败时仍能收敛不崩 |
| P0-3 | **会话式 shell 工具** | builtin_tools.py 新增 `exec_command{cmd,workdir,yield_time_ms,max_output_tokens}` + `write_stdin{session_id,chars}`；Python 侧 pty/ConPTY 常驻进程表（上限 64）+ head+tail 缓冲 + yield 分级 250ms~30s | 长命令（npm run dev）可分多轮读取输出并可 Ctrl+C（chars='\x03'） |
| P0-4 | **工具结果截断显式化** | loops/base.py:270-280 现有 offload 指针。补：进模型的结果超限时给 head+tail 两段 + `"[truncated N tokens, full: path]"` 标注（模型必须知道被截了） | 任意 100KB 工具输出进模型为 head+tail+标注；模型追问时可引导用读文件工具 |
| P0-5 | **审批缓存 key 规范化** | approval_manager.py:570 审批记忆/640 白名单。做法：key = (规范化的可执行名+参数骨架, cwd, 权限级别)——抹平 `/bin/bash -lc`、绝对路径差异（对齐 codex `canonicalize_command_for_approval`） | 同一命令换路径/换 shell 包装不重复审批；新危险形状仍触发 |

### P1（1-2 个迭代内）

| # | 事项 | 要点 |
|---|---|---|
| P1-1 | SSE 事件 item 化 | 事件升级为 `item_started/item_delta/item_completed`（item 类型=agent_message/reasoning/command_execution/file_change/plan/usage）+ thread_id/turn_id；旧事件名保留别名兼容前端渐进迁移 |
| P1-2 | 会话 JSONL 追加流 + timeline 接口 | session_manager 在 JSON 快照外补 append-only `sessions/<sid>.jsonl`（消息+工具事件+compact 事件），新增 `GET /chat/sessions/{id}/timeline`；断线重连用 |
| P1-3 | 重试分型+配额事件化 | openai_loop retry_status 升级：错误分类白名单（可重试：超时/5xx/断流；不可重试：配额/参数/取消）；配额错误带 `{type, reset_at}` 事件 |
| P1-4 | 沙箱拒绝归因+升级审批 | exec_sandbox.py 失败输出跑归因启发式（关键词+退出码，照抄 §2.6 判据）→ 命中则把"沙箱拒绝原因+原文片段"作为 retry_reason 走 ApprovalManager ask；这是把 `NEUROVA_TOOL_SANDBOX_ENFORCE` 从全有全无变成可用功能的前提 |
| P1-5 | tool_search/Deferred 工具 | 工具注册表加 `exposure: direct/deferred`；deferred 工具不进首轮 prompt，新增 `tool_search` 工具按需加载（54+ 工具全量进 prompt 的 token 立省一半以上） |
| P1-6 | 技能注入预算+$mention | skill_service 技能清单注入加 `max_context_tokens`+超限别名压缩；聊天消息 `@技能名` 全文注入该轮 |
| P1-7 | update_plan 工具+PlanUpdate 事件 | 新工具 `{plan:[{step,status}]}` 约束至多一个 in_progress + SSE plan 事件；与现有 /plan 计划模式互补（运行时可视化） |
| P1-8 | /review 受限子会话 | rubric 模板 + 禁工具/禁网 + 强制 JSON findings `[{title,body,priority P0-P3,code_location},overall_correctness]` + 容错解析（容忍裸 JSON） |
| P1-9 | steer 插话 | chat_pipeline 进行中 turn 暴露 pending-input 队列；`POST /chat/steer`（与现有 stop/队列卡片共存） |

### P2（观望/大件）

- hooks 引擎（Claude Code 兼容 wire 格式）——Neurova 无 hooks；若做先从 legacy_notify 式"回合完成回调"起步。
- memories `<memory_citation>` 溯源 + 租约认领（配合既有 fingerprint unique 经验）。
- 密钥 keyring 化（`data/shared_config.json` api_key 明文字段 → keyring/0600 回退；安全债，见 §2.10）。
- 环境上下文 diff 注入（rules_sections 后续轮只发增量）。
- 多 agent mailbox 化（swarm 完成回传从嵌套等待改邮箱+唤醒）。
- 加密 reasoning 回放（依赖 provider 能力，与 reasoning 归一化主线合并做）。

### 不建议照搬

- **Starlark execpolicy 全家桶**：Rust 生态专属，Python 复刻成本高；`DangerousCommandDetector` + 前缀规则 JSON + P0-5/P1-4 可达成 80% 价值。
- **V8 code-mode**：重（独立 host 进程+gRPC），收益未在本项目验证。
- **九层配置 precedence**：过度工程，Neurova 两层+profile 足够。
- **Seatbelt/landlock 复刻**：Neurova 已有 bubblewrap/seatbelt/restricted-token 雏形，重点是把默认开起来 + 归因链（P1-4），不是重写隔离层。
- cloud-tasks / realtime voice / MXC Windows 沙箱：超范围。

---

## 4. 术语与锚点速查

| 概念 | Codex 锚点 | Neurova 锚点 |
|---|---|---|
| Op/Event 枚举 | protocol/src/protocol.rs:600,1357 | console.py:360（SSE 事件清单，待 item 化） |
| 任务生命周期 | core/src/tasks/mod.rs:178,878 | chat_pipeline.py:374 + agent_run_store.py:40 |
| auto-compact | protocol/src/openai_models.rs:521 + core/src/compact.rs | orchestrator.py:995,929,1092 |
| rollout | codex-rs/history/src/lib.rs:122 + rollout/ | session_manager.py:191 |
| 审批升级梯 | core/src/tools/orchestrator.rs:122-540 | approval_manager.py:187 + governance.py:237 |
| 会话式 shell | core/src/unified_exec/mod.rs:73-82 | （缺）builtin_tools.py |
| apply_patch | apply-patch/src/parser.rs + seek_sequence.rs | （缺，file_operation 系工具） |
| AGENTS.md | core/src/agents_md.rs:186-267 | （缺注入）orchestrator.py:1192 |
| skills 注入 | ext/skills/src/host_roots.rs + render.rs:492 | skill_service.py:22 + market_registry.py:13 |
| memories | memories/README.md:29-152 | mem_core.py:438（领先） |
| 配置分层 | config/src/config_layer_source.rs:6-48 | shared_config.py:37 |
| 多 agent | core/src/agent/registry.rs + mailbox | agent/subagent.py:103 + swarm.py:120 |
| hooks | hooks/src/schema.rs:279（Claude Code 兼容） | （缺） |
| review 子会话 | core/src/tasks/review.rs:109-127 | （缺） |
