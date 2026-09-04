# Neurova vs OpenOcta 代码级对比与启发（2026-09-04）

> 对象：https://github.com/openocta/openocta （Apache-2.0，3.1k★，v1.0.6）
> 方法：浅克隆全仓 + 两个并行探索代理深读核心包（agent/swarm/session/gateway/channels/a2a/a2ui/cron/config/ui/prompt），关键引用已在源码中逐条核验（文件行数、struct 定义属实）。

## 0. 项目定位与体量

OpenOcta 是 Go 编写的**桌面 AIOps Agent**（Wails 壳 + 内嵌 HTTP/WS Gateway + Lit 前端），OpenClaw/clawdbot 一脉 TS 版本的 Go 重写。Agent 内核不自研循环，构建在字节 Eino ADK（含 prebuilt/deep DeepAgent）之上，周围叠加自有中间件、会话持久化与多 agent 编排。

- 427 个 Go 文件 / 66,986 行；最大单文件 `gateway/handlers/chat.go` 3840 行
- 无数据库：transcript(JSONL append-only) + sessions.json + swarm store(JSON) + 审批快照(JSON)，全部文件化
- 单二进制 + go:embed 前端，~30MB 安装包，local-first
- 垂直领域：ITOps（巡检/告警分析/数据问答/修复），766+ 技能市场，"数字员工"角色系统，蜂群多 agent

与 Neurova 同为"桌面安装的本地 agent 应用"，产品形态高度可比；但 OpenOcta 垂直于 ITOps，Neurova 是通用陪伴型 agent。可借鉴的主要在**工程架构层**而非领域层。

---

## 1. OpenOcta 架构要点（代码级事实）

### 1.1 Agent 核心（src/pkg/agent/）

- **工具抽象 36 行**：`tool.Tool` 接口 = Name/Description/Schema/Execute，`ToolResult{Success, Output, OutputRef, Data, Error}`；大输出用 `OutputRef{Path, SizeBytes, Truncated}` 落盘引用而非塞进上下文。
- **run 生命周期**：`Runtime.RunStreamTurn` → TurnLoop（支持抢占，preempt 语义="等当前工具执行完再切换"）→ `session_turn_loop.go:TurnSession`：PushMessage 入队 → genInput 从 transcript 构造历史 → Eino DeepAgent 跑 模型→工具→模型 循环（MaxIteration 50）→ `event_bridge.go:StreamEventsFromIterator` 翻译成自有 StreamEvent（thinking 增量前缀合并去重、finish_reason 映射 stop reason）。
- **每 turn 预算**：默认 10 分钟 `AgentRunBudget` 注入 RunCtx。
- **审批 = 可持久化的中断点**：`approval_middleware.go` 对 execute 工具包装 `WrapInvokableToolCall`，首次调用抛 `StatefulInterrupt(ApprovalInfo)`；恢复时 `GetResumeContext[ApprovalResult]` 读用户决定——批准续跑，拒绝把拒绝原因作为工具结果喂回模型继续推理。中断点经 CheckPointStore 落盘，**跨进程重启可恢复**。
- **中间件栈**（`context_middleware.go:buildAgentMiddlewares`，按序）：toolsearch（工具多时动态检索）→ skill → summarization（token 达 65% 触发 LLM 摘要）→ reduction（单消息 8KiB 截断、总 token 45% 清理旧工具结果，清理产物存目录可用 read_file 找回）→ execute-tool-hint → toolArgumentsGuard → approval → toolTurnRepair（修复压缩后断裂的 tool-call 配对）。
- **工具参数防御中间件**（`tool_arguments_guard.go`，225 行）：把生产踩过的 LLM 坑做成中间件——参数别名重映射（`path/file/filename/filepath/filePath` → `file_path`）、截断 JSON 检测（手写括号/引号配平计数）、失败时返回带修复建议的错误文案回灌模型，而不是让工具报错消耗迭代次数。
- **Runtime 池**（`runtime/pool.go`）：按 sessionKey 缓存含 MCP 连接的重型 Runtime，`fingerprint` 不匹配才重建；`poolEntry.mu` 天然实现同会话 turn 串行化。
- **有界进化记忆 + 会话快照冻结**（`evolution/store.go`）：memory 2200 / user 1375 / soul 4000 / prompt 2000 字符上限四类 markdown；`SnapshotForSession` 保证会话中途写入不改变当前 system prompt，**下次会话生效**——自进化与 prompt 可复现性的平衡。
- **提示词即工作区文件**：SOUL/IDENTITY/TOOLS/BOOT 等 10 个中文 Markdown，用户可编辑、agent 可自写；workspace 目录覆盖内置（basename 去重）；`SystemPromptVersion` 参与 runtime fingerprint——改提示词即触发池重建。

### 1.2 Gateway（src/pkg/gateway/）

- **三帧协议**（`protocol/frames.go`，PROTOCOL_VERSION=3）：`req/res/event`；错误信封 `ErrorShape{Code, Message, Details, Retryable, RetryAfterMs}`；`ConnectParams` 支持协议版本区间协商、Role/Scopes、ed25519 设备配对；`HelloOk` 握手响应下发 `Features{Methods[], Events[]}` 能力发现 + 初始 Snapshot + `Policy{MaxPayload 1MB, MaxBufferedBytes 4MB}` —— 服务端把自身限制显式告知客户端。
- **WS Hub 背压三段式**（`ws/hub.go`）：每连接 2048 发送队列 + atomic 字节水位统计 → 慢消费者（>4MB）丢事件 → 更慢踢线 → 队列满 drop-oldest 保 newest（无锁 select 循环实现）。全局事件单调 `seq`，前端 gap 检测（onGap 回调）。
- **chat.go 3840 行的核心工程防御**：
  - 每 runId 单调 seq（配 mutex 防并发 map panic——注释自述踩坑）
  - 幂等：idempotencyKey 即 runId，重复提交返回 `{"status":"in_flight"}`
  - 抢占：新消息到达时终止旧 run → 等 runtime 池释放 → 超时强制驱逐
  - panic recover 后冲刷半截输出；取消/超时区分文案；**空回复也广播 complete**（否则 UI 永远转圈——注释原文承认这一踩坑）；错误也写 transcript
  - 事件帧带服务端算好的性能拆分：`durationMs / firstTokenMs / toolDurationMs / outputDurationMs`
  - 附件白名单 + MIME 双校验 + 大小分级（图片文档 5MiB / 视频 50MiB）
- **入口归一**：`ctx.InvokeMethod` 把 Registry.Dispatch 变成内部同步 RPC，cron、webhook hooks（`/hooks/wake|agent`）、swarm、agent 工具全部复用同一条 `chat.send` 通路——幂等/抢占/transcript/投递逻辑只写一次。
- **会话 Key 归一**（`sessions.go:resolveSessionStoreKey`）：canonical `agent:<agentId>:<rest>` 命名空间；IM 通道、cron（`agent:main:cron:<jobId>`）、数字员工（`agent:main:employee:<id>`）、手动 run（`:run:<uuid>`）共用一套存储与归档；`storeKeys` 多候选兼容磁盘上无前缀的旧数据。

### 1.3 Token 记账：写读分离

- **写侧**（`eino/usage_callback.go`）：全局 callback 在每次 LLM 请求结束时往 transcript 追加独立行 `{"type":"token_usage", input, output, cacheRead, cacheWrite, totalTokens, model, requestId}`；工具调用追加轻量 `{"type":"tool_call", name}` 行。零侵入、context 开关控制。
- **读侧**（`session/usage.go` 1201 行）：`LoadSessionCostSummary` 单趟扫描聚合出日/模型/工具/延迟 p95 多维报表；`hasTokenUsageLines` 双源去重（有 token_usage 行就以它为准、跳过 message.usage）。
- 每条消息还记录 `durationMs / firstTokenMs / toolDurationMs`，延迟报表由真实数据聚合。

### 1.4 蜂群多 agent（src/pkg/swarm/）

- **Member 即 SessionKey**：每个 swarm 成员只是一条 `agent:<id>:employee:<emp>:swarm:<ws>:<member>` 命名空间的普通会话，完全复用单 agent 的 Runtime 池、transcript、usage 管线——多 agent 编排不引入第二套运行时。
- **spawn 三明治治理**：硬限制常量（树深 10 / 直接子数 5 / 工作区 55 成员）→ `store.AddMemberIfSpawnAllowed` **数据层**结构化拒绝（`SpawnRejectReason{Code, Message}`）→ SWARM.md 提示词纪律（"任务要求 N 个就只调 N 次""未指定数量每层 1-3 个"）+ 工具描述内嵌配额与反重复 hint + 返回值带 `directChildren/limit` 闭环。LLM 自主繁殖子 agent 时，"提示词约束必然被忽略"由数据层硬拒绝兜底。
- A2A 标准化出口：`a2a/executor.RuntimeExecutor` 把成员任务包装成官方 a2a-go Task（Submitted→Working→Completed/Failed/Canceled），支持按 TaskID/整 Workspace 批量取消。

### 1.5 A2UI：LLM 生成 UI 的修复管线（最精致的包）

`a2ui/repair.go` 631 行实现 A2UI v0.9 协议（服务端→客户端声明式渲染）：agent 输出 `createSurface/updateComponents/updateDataModel/deleteSurface` 消息，前端用 @a2ui/lit 渲染。核心是 **RepairMessages 修复链**：合并同 surface 消息 → 缺 createSurface 自动补 → 内联组件提升 → 无 child 的 Button 自动合成 label Text → 压扁文本重排 → 引用了未定义 id 时最多 4 轮合成占位组件 → root 推举/造 Column root → 尾部按钮自动包 Row。反序列化层就开始容错（数组/`{"item":[]}`/id-keyed 对象三态）。流式侧 `LineBuffer` 做跨行不完整 JSON 回退重缓冲。**把"模型生成的 UI 不可靠"这个本质问题工程化解决**。

### 1.6 其他

- **channels 双接口分层**：元数据层 `ChannelPlugin`（ID/Meta/能力接口切片，handler 类型断言按需取用）与运行时层 `RuntimeChannel`（Start/Stop/Send/SendStream/IsAllowed + `RuntimeStreamChunk`）分离；入站统一 `InboundSink.Deliver`，出站统一 `Manager.Get(channel).Send()`，新增 IM 通道 gateway 主流程零改动。
- **cron**：三种调度语法（at/every/cron 表达式+时区）；payload 二分（systemEvent/agentTurn）；`CronRunConfig` 支持**定时任务指定模型/技能/MCP**；sessionKey 决策树与会话归档/运行历史对齐；执行走完整 chat.send 有 transcript。
- **embeddedmodels**：进程内 llama.cpp（yzma 绑定）暴露为 OpenAI 兼容端点，再经网关代理统一进 ChatModelFactory——云/本地模型零分叉；模型广场 + 硬件画像（手写 GPU 数据库）+ S-F 六档显存适配评级。
- **localagents**：探测本机第三方 CLI agent（codex/cursor/hermes…）包装成一个 `local_agent` 工具（status/run/run_many），"agent 调 agent"的 CLI 级 A2A，白名单控制。
- **config/schema.go 1667 行 33 个顶层域**：几乎全指针字段 + `IsEnabled()` nil-safe 方法实现"未配置即默认值"三态语义；安全三档 preset（off/loose/standard/strict）；`ToolsConfig.Profile: minimal|coding|messaging|full` 工具档位。
- **成熟度注记**：plugin-sdk 只有 ~80 行占位（无调用方）、acp 全是 stub、hooks 的 HOOK.md 机制未在 Go 侧落地、chat.go 3840 行待拆。代码注释保留大量真实踩坑记录（并发 map、abort 竞态、scanner 64KiB、seq gap），参考价值高。
- 已知 bug：`session/usage.go:583-584` CacheRead 连写两遍双倍计。

---

## 2. 对 Neurova 的启发改进点（按性价比排序）

### P0 —— 直接对症 Neurova 已知痛点

| # | 启发点 | Neurova 现状 | 建议 |
|---|--------|--------------|------|
| 1 | **WS 全局单调 seq + 前端 gap 检测** | WS 通道无 seq（grep 零命中），断线重连 replay 是拍脑袋补偿 | 事件帧加服务端单调 seq，前端检测缺口提示"有事件丢失"；这是断线重连可靠性的地基。改动小、收益大 |
| 2 | **流式 run 的幂等 + 防转圈兜底** | SSE/WS 流式链路出错时前端可能永远"思考中"（TTS 416 事故同型问题） | 借鉴三条：runId 幂等（重复提交返回 in_flight）；空回复也广播完成事件；错误写入历史可查。均为收尾防御，不动核心 |
| 3 | **审批从"内存等待"升级为"可恢复中断点"** | `approval_manager.py` 已有 requests.json 落盘（领先多数项目），但恢复路径是轮询 API，非 checkpoint 续跑 | 对齐方向：审批拒绝时把拒绝原因作为工具结果喂回模型（拒绝也可继续推理，而非终止）；中断点持久化后跨重启可 approve 续跑。增量改造，勿推翻现有落盘 |
| 4 | **每 turn / 每 run 预算** | Agent run 无显式时间预算（运行卡死史：MoE 索引 2 分钟烧 12 核） | 给 agent run 注入默认超时预算（OpenOcta 10min/turn），超时区分"已取消/已超时"文案。符合"增量实施约束"：机制已存在缺传动轴 |

### P1 —— 上下文与工具层纵深

| # | 启发点 | Neurova 现状 | 建议 |
|---|--------|--------------|------|
| 5 | **工具参数防御中间件** | tool_executor 无别名重映射、无截断 JSON 检测；LLM 传错参数直接报错消耗轮次 | 加一层参数守卫：常见别名归一（path/file→file_path 类）、半截 JSON 配平检测、失败时返回带修复建议的错误文案。独立中间件可单独关闭，符合新扩展点默认关约束 |
| 6 | **大输出 OutputRef 落盘引用** | 工具大输出直接进上下文/历史 | 工具结果超过阈值落盘为文件，上下文只放 `{path, size, truncated}` 引用，模型可用 read 工具按需取。与 context_pool 的溢出摘要互补（一个管工具输出、一个管对话历史） |
| 7 | **压缩后 tool-turn 修复** | context_pool 已有 rollup_overflow_digest 摘要，但摘要后历史中的 tool_use/tool_result 配对可能断裂 | 借鉴 toolTurnRepair：折叠历史时保证 tool-call 回合完整性（或修复配对），否则后续 LLM 调用报 orphan tool_result |
| 8 | **token_usage 独立事件行（写读分离记账）** | usage_history SQLite 已落地（09-03），但粒度与延迟指标 | 可补：每条消息记 firstTokenMs/durationMs/toolDurationMs，usage 统计页可出延迟 p95 报表；无需改存储，加字段即可 |

### P2 —— 多 agent 与编排

| # | 启发点 | Neurova 现状 | 建议 |
|---|--------|--------------|------|
| 9 | **Member 即 SessionKey 的多 agent 模型** | 多 agent 隔离靠 scope 注册表 + 每工作区记忆库；无编排层 | 若做子 agent/编排，学"成员只是一条命名空间会话"，复用现有会话/记忆/记账管线，不建第二套运行时。命名规范可直接借鉴 `agent:<id>:swarm:<ws>:<member>` |
| 10 | **spawn 三明治治理** | 无自主 spawn 子 agent 的工具 | 一旦引入子 agent 工具，必须三层同时上：常量硬限制 + 数据层结构化拒绝 + 提示词纪律与工具描述内嵌配额。这是现成答案 |
| 11 | **进化记忆会话快照冻结** | 记忆温度/结晶引擎写入即时生效，长会话中 system prompt 可能漂移 | `SnapshotForSession` 模式：会话开始时冻结注入 prompt 的记忆/人设快照，写入下次会话生效。对"可复现性"价值大，实现只需快照字段 |

### P3 —— 桌面产品形态

| # | 启发点 | Neurova 现状 | 建议 |
|---|--------|--------------|------|
| 12 | **本地模型即 Provider（OpenAI 兼容端点统一抽象）** | MOSS/ONNX 嵌入模型直连代码路径，与云 provider 分叉 | 学 OpenOcta：本地推理进程暴露 OpenAI 兼容 `/v1/chat/completions|/embeddings`，云/本地同走一条 provider 抽象。P0-3 已做 RAG 分块，此项可让本地模型接入零分叉 |
| 13 | **会话 key canonical 归一 + 多候选兼容** | memory API 层有路由 shadowing 教训，scope 键多套口径 | 借鉴"canonical key + storeKeys 多候选"解决历史兼容的模式，收敛 scope 命名规范 |
| 14 | **A2UI 修复管线**（长线） | 画布/组件由前端固定 schema 生成，模型不直接产 UI | 若未来做"模型生成 UI"（NL 设计器深化），repair 链（补 surface/合成占位/推举 root）是必须品，631 行可参考移植思路 |
| 15 | **cron 任务绑定运行资源** | 调度器已复活（cron/handlers/agent 绑定），但任务不能指定模型/技能集 | `CronRunConfig{ModelRef, SkillKeys}` 语义可加：定时任务指定用哪个模型跑、带哪些技能。小改动 |

### 反面教材（勿学）

- chat.go 单文件 3840 行的"上帝 handler"——Neurova 的 post_chat_pipeline 2210 行已是同类问题（DSH 对比已记录），不要再造。
- `sessions_spawn` 别名与主工具并存导致重复 spawn（swarm_tools.go 注释自述）——工具集收敛时别留语义重复的别名工具。
- usage.go CacheRead 双计 bug——聚合逻辑改动要有双源对账测试。
- plugin-sdk/acp 是无调用方的 stub——Neurova 的 evolution/ 曾被误判为骨架，教训一致：stub 要么删除要么标注 Phase。

## 3. 与既有对比报告的关系

- Dify 对比（09-03）指出"执行流式化"缺口已由 P0-1 落地（eb5791c0）；OpenOcta 的 seq/幂等/防转圈是流式化的**可靠性收尾**，是下一步。
- DSH 对比指出"turn 边界事件化"；OpenOcta 的 StopReason 映射（tool_use/end_turn/preempted/aborted）与 `messageStopEndsAgentEventStream`（区分模型回合边界 vs run 结束）是现成的边界语义设计参考。
- QwenPaw 对比记录的"断线重连 replay"遗留项，本报告 #1 seq/gap 是其正解。
