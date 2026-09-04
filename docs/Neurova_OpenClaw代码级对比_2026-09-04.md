# Neurova × OpenClaw 代码级对比（2026-09-04）

> 对比对象：`github.com/openclaw/openclaw`（本地浅克隆 `E:/项目/openclaw-compare/openclaw`，commit 快照 2026.8.1）× `E:/项目/Neurova`
> 方法：四路并行代码探索（Gateway/Agent 运行时、工具/技能/安全、渠道/记忆/语音、LLM 层/工程纪律）+ 官方文档（docs/concepts、docs/security、docs/gateway）交叉核对 + Neurova 侧对位核实。
> 所有 openclaw 侧结论均给出文件路径证据；Neurova 侧结论来自本次实测与既有台账。

---

## 0. 元数据与体量

| 项 | OpenClaw | Neurova |
|---|---|---|
| 定位 | 运行在用户自己设备上的个人/团队 AI 助手（"The AI that really does things"），单 Gateway 连接消息渠道+设备+模型 | 多用户 AI 助手平台（知识库/工作流/技能/多渠道/桌面版） |
| 语言/栈 | TypeScript + Node 22+，pnpm monorepo（23 个 packages） | Python 3.10+（FastAPI+SQLite）+ Vue3/Vite |
| License | MIT（OpenClaw Foundation，非营利） | 私有项目 |
| 星数/commits | 388.8k★ / 81.6k forks / 87,525 commits | 私有 |
| 版本策略 | CalVer（2026.8.1），人工门控发布链 | 1.0.0-beta1 |
| 代码体量 | src 非测试 **200.6 万行**（16,310 文件）+ 测试 **298.2 万行**（6,940 文件）；ui 2,830 文件 | 769 个 py 文件，约 **27.7 万行** |
| 测试体量 | 全仓约 **11,500 个 .test.ts**（测试:代码 ≈ 1.49:1） | 1,018 个测试文件 |
| CI | **95 个 workflow**，主 ci.yml 5,400+ 行 **35 个 job**（含 CodeQL/OpenGrep/dependency-guard/全平台 release 矩阵） | 本地 pytest 套件为主 |
| 插件 | **162 个内置 extensions** + ClawHub 市场 | plugins/ 管理器 + 内置市场（阿里/讯飞源） |
| 渠道 | **27 个渠道插件**（whatsapp/telegram/discord/slack/signal/imessage/line/matrix/msteams/feishu/irc/nostr/zalo…） | 14 个渠道适配器（feishu/dingtalk/telegram/discord/qq/mqtt/sip/qclaw…） |
| LLM 接入 | 8-9 种 wire 协议、**79+ 内置 provider overlay**、70+ provider 插件 | 多模型路由 + 80+ 厂商 preset 三元组 |
| Schema 版本化 | state DB v15 / agent DB v19（package.json 声明 + 更新器预检） | 无系统性版本化 |

**一句话画像**：OpenClaw 是"把一个 AI 助手当成一个操作系统来写"的项目——体量是 Neurova 的 7 倍、测试是 11 倍，把幂等、围栏、沙箱、审批、审计做到了个人助手赛道罕见的深度；但在**知识库/RAG、可视化工作流、多用户三层隔离**上明显弱于 Neurova。两者是"个人助理纵深"与"平台化广度"的镜像。

---

## 1. 逐项评分表

> 10 分制，对"该维度绝对完成度+工程质量"打分，不做相对扭曲。加权即简单平均。

| # | 维度 | OpenClaw | Neurova | 一句话裁决 |
|---|---|---:|---:|---|
| 1 | 架构分层与代码组织 | **9.5** | 7.0 | 一职责一文件 vs 大文件巨石残留 |
| 2 | Agent 循环与会话管理 | **9.5** | 7.0 | steering/围栏/压缩质量闸全面领先 |
| 3 | 事件系统与实时通信 | **9.0** | 7.5 | Neurova 新做的 seq/gap/sync_resume 已追平骨架，缺慢消费者策略 |
| 4 | 工具系统与治理 | **9.5** | 7.0 | 每 run 动态装配+五层策略管道；Neurova 棘轮/肌肉记忆是独有面 |
| 5 | 安全/沙箱/审批 | **9.5** | 6.0 | 差距最大维度：Docker 沙箱+命令分段审批+ATLAS 威胁模型 |
| 6 | 记忆系统 | **9.0** | 7.5 | Dreaming+来源信任分级 vs 17 维情感+温度，各有纵深 |
| 7 | 知识库与 RAG | 5.5 | **8.5** | Neurova 压倒性优势：openclaw 无独立 KB/图谱/重排子系统 |
| 8 | 消息渠道 | **9.0** | 6.5 | 持久化入站队列+回执 vs 内存态分发 |
| 9 | LLM 接入与路由 | **9.5** | 7.5 | 声明式 compat 开关+tool-call-repair+真账单拉取 |
| 10 | 语音与媒体 | **8.5** | 4.5 | 实时语音+barge-in+16 TTS；Neurova ASR 仍是占位 |
| 11 | 工作流与自动化编排 | 6.5 | **8.0** | Neurova 优势面：NeurFlow 画布+双轨引擎+评估器 |
| 12 | 可观测性 | **9.0** | 7.0 | trajectory 全链路+审计假名化 vs 新落地 OTel bridge |
| 13 | 插件与生态 | **10** | 6.0 | 162 扩展×60+ 扩展点×42 hooks×ClawHub 市场 |
| 14 | 工程纪律（测试/CI/发布/供应链） | **10** | 6.5 | 11,500 测试+发布证据链+依赖冷却期+补丁退场条件 |
| | **平均** | **8.9** | **7.0** | |

口径说明：openclaw 是单用户/互信团队边界（`SECURITY.md` 明言 "local-first agent infrastructure for trusted operators"，多用户共享同一 Gateway 被列为"不算漏洞"），Neurova 的多用户三层隔离、知识库归属、技能权限声明在它那里没有对位物——第 7/11 维的分差与第 5 维的差距应结合这一点读。

---

## 2. 分维度代码级对比

### 2.1 架构分层与代码组织（OC 9.5 / NV 7.0）

**OC 的做法**
- 全库"一职责一文件"极限拆分：`src/gateway/` 1,000+ 文件（`approval-channel-custody.ts`、`active-sessions-shutdown-drain.ts`…每个文件头注释写明唯一职责），agent 旅程按 phase 拆为 `src/gateway/agent-turn/` 下的 preflight→dedupe→admission→dispatch→execution 各文件，每阶段可独立测试。
- Gateway=准入/投递/状态层，Agent 运行时=执行层，同进程分层，桥接链清晰：`agent-turn/agent-run-dispatch.ts: dispatchAgentRunFromGateway()` → `src/agents/agent-command.ts` → `runEmbeddedAgent()`（`src/agents/embedded-agent-runner/run-orchestrator.ts`）。LLM 循环本体独立成 workspace 包 `packages/agent-core/src/agent-loop.ts`。
- 懒加载贯穿全库：`src/gateway/server.ts` 动态 import 壳、`packages/ai/src/providers/register-builtins.ts` 8 个协议适配器全部懒注册、prepared model runtime lease。
- 每个子目录自带 `AGENTS.md`/`CLAUDE.md` 给 AI 贡献者讲本目录宪法。

**NV 现状**：deep module + agent_ref 注入的分层是健康的，但 `post_chat_pipeline`（2,210 行硬编码 19 依赖）、`agent_core.py`（1,621 行 37 方法）两处巨石仍在（DSH 对比时已记录）。

**差距本质**：不是行数，而是"单文件可独立测试+文件头自述职责"的纪律。OC 一个 522 行的 `run-orchestrator.ts` 旁必有同名 test；NV 的 2,210 行 pipeline 无从下测试钳。

### 2.2 Agent 循环与会话管理（OC 9.5 / NV 7.0）

**OC 的做法**
- 循环：`agentLoop()` 返回 `EventStream<AgentEvent>`，`stopReason==="toolUse"` 时执行工具（before-tool-call 准入 + steering 插队 + tool-loop 防死循环告警）再续环；中断走 `turn-interruption.ts` 生成 interrupted turn。
- **队列四模式**：消息并发进同一会话时可选 steer/followup/collect/interrupt（`docs/concepts/queue-steering.md`）。steer 模式下新消息在**工具启动边界**插队：已启动的调用跑完，未启动的尾部调用拿到合成结果 `Skipped due to queued user message.`（保持 tool-call/tool-result 成对），然后把用户插队消息追加到下一次 LLM 调用前——"已请求"与"已启动"严格区分，转录永远结构配对。
- **写入围栏**：transcript 落盘带 `expectedWriterRunId` claim，SQLite 事务内写前写后双重断言，被抢占则抛 `SessionTranscriptWriterClaimReboundError` 回滚（`src/config/sessions/session-accessor.sqlite-transcript-write.ts`）——被夺权的 run 永远写不进陈旧数据。
- **压缩三闸**：压缩分割点若落在工具块内则移动边界保持 tool 配对；CJK 字符感知的分块估算；`safeguard` 模式（默认）对摘要做质量审计——必需标题/待办/精确标识符必须保留，校验不过的输出只有有限次纠正机会，最终失败则**不写压缩条目保留原历史**（`docs/concepts/compaction.md`）。
- 会话剪枝：只剪旧工具结果不动对话文本，感知 Anthropic prompt cache TTL（`docs/concepts/session-pruning.md`）。
- 每 agent 一个 SQLite DB（schema v19），`session_nodes.entry_json` 为 canonical 记录；state DB v15 迁移是"事务内收敛"（重放 canonical SQL + strict 迁移 + 幂等），`user_version` 高于当前版本直接拒绝打开（防降级损坏），更新器预检 `package.json` 的 `schemaVersions`。

**NV 现状**：ChatPipeline 六步稳定；OpenOcta P2 刚落地快照冻结（身份层 LRU、检索层不冻）与 spawn 三明治；上下文池有轮次配对/FTS 台账/溢出恢复，但没有 steer 类插队语义、没有写入围栏、没有压缩质量闸。

### 2.3 事件系统与实时通信（OC 9.0 / NV 7.5）

**OC 的做法**（`src/infra/agent-events.ts`、`src/gateway/server-broadcast.ts`、`packages/gateway-client/src/protocol-client.ts`）
- **双层 seq**：per-run seq（run 内事件有序）+ per-client seq（WS 帧全局有序）。
- 慢消费者策略：`bufferedAmount` 超限的客户端，丢帧**也消耗 seq**（让客户端 gap 探测器看见丢失），不丢帧则 `close(1008,"slow consumer")`；序列化失败**不推进 seq**——防止所有客户端同时触发 gap → 重连风暴。这是把"seq 语义"推到崩溃/慢读边界的设计。
- gap 后不做服务端 replay：重连 + RPC 拉历史 + 客户端**幂等投影合并**（消息身份去重、`hasTransportGap` 标记、run 状态机合并），帧内带 `stateVersion`（presence/health 版本号）做状态级对账。
- WS 帧过 JSON Schema 校验；认证类错误永久暂停重连。

**NV 现状**：OpenOcta P0-1 已落地 per-session 单调发号（add_event 咽喉盖章）+ sync_hello 纪元帧 + sync_resume 补发 + 前端 gap 检测/去重/丢事件横幅——**骨架与 OC 同构**。缺的精细化：(a) 慢消费者 bufferedAmount 策略与"丢帧也推进 seq"；(b) stateVersion 式状态对账；(c) OC 不维护服务端 replay 队列而 NV 的 sync_resume 是服务端补发——两者取舍不同，NV 的方案在重连后恢复更完整，OC 的方案服务端更省内存，各有合理性。

### 2.4 工具系统与治理（OC 9.5 / NV 7.0）

**OC 的做法**
- 工具契约：TypeBox schema + `execute` + 可选 `outputSchema` + `resultContentSource:"network"` **污染标记**（结果被网络内容污染会被下游包裹脱敏）+ `executionMode`（串/并行）+ `progress` 强制 `visibility:"channel"/privacy:"public"`（进度文本不得含秘密）。
- **每 run 动态装配**（`src/agents/agent-tools.ts`："Assembles core, shell, channel, OpenClaw, plugin, and Tool Search tools, then applies sandbox, profile, provider, sender, group, and sub-agent policy"）→ `applyToolPolicyPipeline` 五层过滤（profile→provider→agent→group→sender），每层留 before/after 诊断快照；四种 profile（minimal/coding/messaging/full）；子代理硬编码 deny 表。
- 执行前统一过 `before_tool_call` hook 管道：可拦截/改参/升级审批，blocked 时发安全事件。
- 约 60+ 平台工具分 12 个 section（`src/agents/tool-catalog.ts`），包括 `sessions_spawn/sessions_history/sessions_search`（会话即工具）、`canvas/show_widget/progress_card/ask_user`（UI 工具）、`nodes/computer/mobile_ui`（设备工具）、`automations`。
- `packages/tool-call-repair`：把模型以纯文本"漏出"的工具调用（Harmony `<|channel|>` 标记、`[END_TOOL_REQUEST]` 尾标、XML-ish `<function>` 标签）在流内扫描修复为结构化 ToolCall，保护 code fence 内用户原文，专救 Ollama/vLLM 类弱端点。

**NV 现状**：工具层有独有纵深（棘轮权重、肌肉记忆、熔断器、声明式权限 fail-closed、工具流水线五段），但工具面小、无 outputSchema/污染标记、无 run 级动态装配、弱 provider 的文本工具调用无修复通道（LLMServiceUnavailableError 归一化已有，但"格式坏"与"服务坏"是两回事）。

### 2.5 安全/沙箱/审批（OC 9.5 / NV 6.0）—— 差距最大的维度

**OC 的做法**
- **沙箱**（`src/agents/sandbox/`，70+ 文件）：默认基线 `readOnlyRoot:true, capDrop:["ALL"], network:"none"` + tmpfs；宿主路径 denylist（/etc /proc docker.sock ~/.ssh ~/.aws…）创建容器时强制校验；显式封禁 `network:"host"` 与容器命名空间共享；config-hash 驱动容器重建；浏览器独立沙箱容器带 noVNC 鉴权；mode（off/non-main/all）× scope（agent/session/shared）× backend（docker/podman/ssh）三维配置，creator-role 可强制 `sandbox:"required"` 且**不可被 elevated 逃逸、后端不可用即 fail-closed**。
- **exec 审批**（`src/infra/exec-approvals-core.ts`）：`security: deny|allowlist|full` × `ask: off|on-miss|always` 五种 mode；**命令分段解析**——shell 命令被解析成 argv/posix-shell/windows-cmd/powershell 四方言的候选段（pipeline、`&&`、inline command 全拆开），逐段匹配白名单或要求人工审批，`trustMode: executable|exact-command|prompt-only`——"白名单命令 + 注入段"无法搭便车；`allow-once/allow-always/deny` 三种裁决，allow-always 落地为持久 standing grant。
- **审批是持久化状态机**：SQLite 存储（kysely），`pending→allowed/denied/expired/cancelled`，first-answer-wins，terminal 记录留 30 天；审批卡**镜像路由到聊天渠道**（幂等去重）+ Web Push + iOS APNs 三路；决定后优先**恢复原 agent 会话续跑**（`exec-approval-followup.ts`，幂等 key + 24h 完成去重），失败降级安全直接投递；拒绝文案明确"Do not mention /approve"（防模型社会工程式恢复）。run 级有 `waiting-approval/approval-resolved` 生命周期事件并累计 `pausedMs`。
- **网络三道闸**：`packages/net-policy`（特殊用途 IP 段封禁 + 约 35 种 query 参数 URL 脱敏）→ `src/infra/net/ssrf.ts`（**固定 DNS 查询防 rebinding** + hostname allowlist）→ 结果侧 `external-content.ts` 包裹脱敏防提示注入。
- **安全工程文档化**：MITRE ATLAS 威胁模型（T-EXEC-003 式威胁 ID、信任边界 ASCII 图、攻击链示例）、TLA+/TLC 形式化验证（授权/会话隔离/工具门控四个最高风险路径，附负向模型）、`src/security/` 运行时安全审计引擎（~100 文件，扫 gateway 暴露面/exec 沙箱/插件信任/Windows ACL/危险 flag，输出带 remediation 的报告）、OpenGrep 精准规则包防回归。

**NV 现状**：`security/governance.py` + 技能声明式权限（fail-closed 四强制面）+ 渠道/知识库三层隔离是真实资产；但**无沙箱**（exec 类操作直跑宿主）、审批流是会话内问答而非持久化状态机、无命令分段解析、SSRF 守卫有但无 DNS pinning、无威胁模型文档。

### 2.6 记忆系统（OC 9.0 / NV 7.5）

**OC 的做法**（`docs/concepts/memory-architecture.md` + `extensions/memory-core/`）
- 五层 tier：Instructions（AGENTS.md，人写）/ Curated core（MEMORY.md+USER.md，巩固写入）/ Episodic（日记+转录，只可检索）/ Prospective（standing intents+cron，触发式）/ Review（DREAMS.md）。**核心边界**：episodic→curated 必须过晋升门。
- **哲学是"写路径才是难点"**："Retrieval over notes files is competitive with far heavier designs; what degrades memory systems is unreliable write-time curation"（引 LongMemEval arXiv:2410.10813）。因此把整理搬离回复路径，进后台 **Dreaming**：light（分拣暂存）→ REM（主题反思）→ deep（评分晋升）三阶段 cron（默认每日 3 点），晋升评分含召回次数/唯一查询数/14 天新近度半衰期，Machine 状态全落 SQLite。
- **来源信任分级防毒化**：每条记忆带 origin（owner/agent/untrusted/system，闭集、SQLite 列、模型无法用文字改写）+ session kind + observed 时间戳 + supersession key（新观察取代旧观察而非并存）。写入时即定信任级——"内容级扫描抓不住毒化记忆，所以按写入路径做结构门控"。
- **失败永不阻塞回复**：记忆路径每步都有超时/兜底；active-memory 升级车道只在"问过去+确定性车道无强命中"时才跑阻塞式召回子 agent。
- 可选 memory-lancedb 向量插件（agentId 列隔离）+ auto-recall（带 15s 熔断）。
- 全部记忆是**人可读可编辑的 Markdown**："No hidden state. The model only remembers what is written to files."

**NV 现状**：17 维情感四层、记忆温度、MoE 检索（三层 WHERE 强制隔离）、agent 级隔离、SQLite 分片索引是真实纵深，且**有 openclaw 没有的**情感维度与检索隔离工程；但晋升路径（哪些短记忆进长期）没有确定性门控+后台巩固流水线，检索优先于整理——恰是 OC 用 LongMemEval 论证过的弱序。

### 2.7 知识库与 RAG（OC 5.5 / NV 8.5）—— Neurova 压倒性优势

**OC**：没有独立知识库子系统。能力=memory 检索（嵌入/memory-core）+ `web_fetch/web_search/x_search` + `document-extract` 附件抽取 + memory-wiki 插件。无分块/重排/溯源/KG/多租户归属。

**NV**：EKB 真库、混合检索（FTS IDF 覆盖评分+向量）、rerank 双模、检索方法四态、实体消歧 resolution、知识图谱（manager+API+冲突墓碑）、可见性模型（public/private/shared+审批）、MoE 质量公式、知识检索链接入记忆链（KnowledgeRetrieverAdapter 补充式合并）、分片索引懒重建。这是两者画像差异最大的一格。

### 2.8 消息渠道（OC 9.0 / NV 6.5）

**OC 的做法**
- 27 渠道全走同一 `ChannelPlugin` 组合式契约（约 30 个可选 adapter 面：config/gateway/outbound/streaming/threading/pairing/security/allowlist/doctor/heartbeat…），缺省面自动降级——**是"面"的组合而非基类继承**。
- **入站是持久化队列**（`src/channels/message/ingress-queue.ts`）：SQLite `channel_ingress_events` 表 + claim 租约 + 按 lane（会话）串行排水 + attempt 计数 + tombstone 幂等去重 + dead-letter + supersede；ack 策略可选 `after_receive_record|after_agent_dispatch|after_durable_send|manual`——**重启不丢消息**。
- turn 管道统一：bot 回环保护、出站回声丢弃、`dispatch|observeOnly|handled|drop` 准入、历史连媒体落库；出站统一 ReplyPayload + MessageReceipt 回执；webhook 与长连接同为插件能力（带 secret 常时比较+限流）。

**NV 现状**：14 适配器走 base_adapter 契约 + manager，但入站是内存态——重启即丢；无回执、无 dead-letter、无回环保护专项（各渠道自查）。

### 2.9 LLM 接入与路由（OC 9.5 / NV 7.5）

**OC 的做法**
- 四层栈：`packages/llm-core`（纯契约：Message/AssistantMessageEvent 流协议/usage-cost 分段计价）→ `packages/ai`（可复用传输库：宿主策略端口注入 fetch 守卫/密钥脱敏）→ `src/llm`（进程门面+per-provider 流包装）→ `src/agents`（路由大脑：fallback 候选链缓存、30s 冷却探活、多凭证轮换、sticky 模型选择）。
- **流协议铁律**："Once invoked, request/model/runtime failures should be encoded in the returned stream, not thrown"（`packages/llm-core/src/types.ts` L202）——错误是 `stopReason:"error"` 的消息，不是异常。
- **声明式兼容开关**：`OpenAICompletionsCompat` 约 30 个字段（`thinkingFormat: openai|openrouter|deepseek|together|zai|qwen|qwen-chat-template`、`supportsUsageInStreaming`…），多数从 baseUrl 自动探测——支撑几十个 OpenAI 兼容 provider 靠开关表而非 if 分支。
- thinking 带 signature 跨轮 replay（anthropic encrypted thinking / openai reasoning item id）。
- **真账单**：`src/infra/provider-usage*.ts`（~20 文件）直连各家后台 API 拉 plan/配额/余额/30 天趋势，与 token 估值分离。
- retry 包：指数退避+full jitter+尊重服务端 Retry-After 的正抖动语义。

**NV 现状**：LLM 路由+80+ 厂商 preset 三元组（能力+ctx+max_output）+能力三层检测+P0-5 错误归一（error_mapping/_RETRYABLE）是真资产；但 compat 靠 per-provider 代码分支、无流内错误编码铁律（流式 chunk 契约曾是 bug 高发区）、账单是 tiktoken 估值+网关实测不回传的困局（sensetime 案）。

### 2.10 语音与媒体（OC 8.5 / NV 4.5）

**OC**：talk 三模式（realtime=OpenAI Realtime/Gemini Live 端到端，带 **barge-in 打断**与回声抑制；stt-tts=本地能量门 VAD→转写→agent→TTS；transcription）；流式 ASR 核心只管 WS 重连/队列、provider 只供协议；**16 个 TTS provider** 按 autoSelectOrder fallback，支持 `[[tts:...]]` 文内指令（白名单策略约束）与 auto 模式（off/always/inbound/tagged），长文本先 LLM 摘要再合成；**语音与聊天共享同一条会话历史**；media-understanding 做**音频预检**（先转录再判断是否需要 @ 提及，群语音消息不漏）；image/video/music 三能力注册表+provider fallback+异步任务轮询；meeting-bot（zoom/meet/teams）。

**NV**：TTS 真截断+5 引擎+流式 fallback 链+空 blob 守卫是修好的；但流式播放链有哑点（liveTtsAudio 无模板元素）、ASR 是 funasr 占位（模型已落盘未编排）、MOSS 推理 5 图级联未编排、无实时语音、无打断。这是差距最悬殊的一格。

### 2.11 工作流与自动化编排（OC 6.5 / NV 8.0）

**NV 优势面**：NeurFlow 画布+259/614 测试、双轨引擎收敛（shared_core 转发 neurflow 优先）、工作流评估器（断言五型不引入 LLM 判分）、执行流式化（run/stream 分离+events SSE，eb5791c0）、MCP 核对+OTel bridge、调度器复活（cron ±1 语义修过）。

**OC**：automations/cron + heartbeat（系统持有的监控回合，归 Automations 调度器）+ flows + webhooks 绑定 TaskFlow。无可视化编排、无评估器——它把"自动化"做成定时回合而非 DAG。WebChat 有 Canvas（`/ __openclaw__/canvas/` 托管 widget 文档）但是 UI 面板不是工作流。

### 2.12 可观测性（OC 9.0 / NV 7.0）

**OC 四线分离**：audit（SQLite 元数据审计+身份假名化+执行决策回执）/ logging（tslog+trace context+密钥脱敏注册表+诊断 support bundle 一键导出且自动脱敏）/ **trajectory**（版本化 JSONL+SQLite 全链路 trace，`traceSchema:"openclaw-trajectory"`，entry 父子树，sessionId/runId 关联）/ transcripts（会议转写，另一码事）。对外 OTel+Prometheus 插件。
**NV**：OTel bridge（P0-5，可选依赖三层降级+root+N 节点 span+状态端点）、错误日志上报链路（前端 SDK→官网 php→SQLite）、/monitor 真 psutil 契约；无全链路 trajectory/假名化审计。

### 2.13 插件与生态（OC 10 / NV 6.0）

**OC**：60+ 注册点（`registerTool/Channel/GatewayMethod/Provider/ContextEngine/CompactionProvider/AgentHarness/SessionSchedulerJob/SecurityAuditCollector/…`）× **42 个 hook**（`src/plugins/hook-types.ts`）× 三件套收紧（package.json 兼容契约 pluginApi range、安装期安全扫描+事务化+来源审计、运行期 capability consent/lease+工具授权白名单）；宿主安全能力经 `src/plugin-sdk/*-runtime.ts` 门面借出而非裸暴露。162 内置扩展 + **ClawHub 市场**（owner 体系/版本/安全裁决 verdicts/commit-pinned 外部源）+ **Claw**（打包整个 agent 应用：多 agent+skills+MCP+cron+tool-policy 清单，带 rollback/provenance）+ Skill Workshop（agent 自己起草技能、受监管评审/回滚）。

**NV**：plugins/ 管理器 + 内置市场（阿里 258/讯飞 1000 源接入）+ 技能提交审核三连 + skill_id 契约修复——框架在，但扩展点数量（~10 个）、hook 面、隔离纪律、市场规模都远小。

### 2.14 工程纪律（OC 10 / NV 6.5）

**OC**：
- 11,500 测试文件；源旁 1:1 配对；`test/` 做 e2e/边界守护（`architecture-smells.test.ts`、`extension-import-boundaries.test.ts`）+ **80+ vitest 分片配置**；e2e 铁律"异步等待必须同步在动作产生的状态上，禁止 sleep 式断言"（`test/AGENTS.md`）。
- CI 95 workflow / 主 ci.yml 35 job；CodeQL+OpenGrep（PR diff 精准扫描）+dependency-guard+security-sensitive-guard。
- **发布证据链**：npm 发布必须携带成功的 Full Release Validation run id+attempt（`release_evidence_mode: full-release-validation`）；逐包 `npm view` 防重复发布+tarball sha256 readback。
- **供应链**：`pnpm-workspace.yaml` `minimumReleaseAge: 10080`（依赖发布 7 天冷却期才可进入）；patches/ 5 个补丁每个写明"上游哪个版本通过哪个回归测试后必须移除"的退场条件。
- **AGENTS.md 修复教义**：根因修复、bug fix 默认净 LOC ≤ 0（不许借修 bug 加功能）、禁止 consumer-only guard 掩盖根因、live-verify 默认化——与本项目 AGENTS.md 的"放大视角找根因"完全同频，但成文更狠。

**NV**：TDD 红绿灯+测试文件纪律+防回归用例文化是真实的（1,018 测试文件，1047 入库）；差距在 CI 门禁矩阵、发布证据链、依赖治理、净 LOC 纪律的成文性。

---

## 3. 启发点清单（按性价比排序）

> 遵守本项目"增量实施约束"：只提升不下降、不碰核心框架、先查"机制已存在缺传动轴"、新扩展点默认关+等价性测试锁定。

### P0（传动轴级，直接可落地）

1. **流内错误编码铁律**（OC：llm-core types.ts L202）——Neurova 的流式 chunk 契约曾是 bug 高发区（test_execute_with_stream 根因）。规则：provider 调用一旦开始，一切失败编码为流内错误消息而非异常。落点：`neurova/llm/` 流式适配层 + 一条契约测试。
2. **声明式 compat 开关替代 per-provider if 分支**（OC：`OpenAICompletionsCompat` 30 开关+baseUrl 自动探测）——Neurova 的 sensetime/model_limits/商汤三层根因这类 bug 的共性就是兼容逻辑散在分支里。落点：`neurova/llm/` 建 `provider_compat` 描述表，preset 三元组里加 compat 字段。
3. **tool-call-repair 式文本工具调用修复**（OC：`packages/tool-call-repair`，Harmony/XML/尾标三形态流内扫描）——本地小模型（Ollama/vLLM 类）漏工具调用是 Neurova 接本地模型时必撞的墙。落点：`tool_executor.py` 解析入口加一层流内提升器。
4. **记忆晋升确定性门控 + 后台巩固**（OC：Dreaming 三阶段+晋升评分召回次数/唯一查询数/14 天半衰期）——Neurova 的记忆温度已有强度信号，缺的是"离线晋升流水线"这根传动轴。原则照抄：**整理离线做，回复路径永不因记忆阻塞**（每步超时+兜底）。落点：`mem_core.py`/memory_layer，cron 式后台任务。
5. **渠道入站持久化队列**（OC：`channel_ingress_events` 表+claim 租约+dead-letter+tombstone）——Neurova 14 渠道入站全内存态，重启丢消息，这是可用性硬伤。落点：channels/manager.py 收口处。
6. **exec 命令分段审批**（OC：四方言候选段解析，pipeline/&&/inline 逐段审，链式注入无法搭便车）——Neurova 已有审批 approvals 端点，补命令解析器即可升级为命令级安全。落点：审批流 + `builtin_tools` exec 面向工具。
7. **慢消费者 seq 策略两条例**（OC：丢帧也推进 seq 暴露丢失；序列化失败不推进 seq 防重连风暴）——Neurova 刚落地的 seq/gap（P0-1）正好差这两条边界纪律。落点：`add_event`/WS 广播处，两行级别改动+防回归测试。
8. **压缩/上下文窗口的 tool 配对保序**（OC：分割点落在工具块内就移动边界；CJK 感知分块）——Neurova 上下文池已做轮次配对（P1-1），把配对语义延伸到溢出裁剪的分割点选择即可。

### P1（需小设计，收益大）

9. **记忆/知识来源信任分级**（OC：origin 闭集 owner/agent/untrusted/system 落 SQLite 列，模型不可用文字改写）——Neurova 的 web_reach/browser_read 会把外部内容写进记忆链路，这正是毒化面。落点：记忆写入咽喉加 origin 列+检索侧按 origin 加权，**fail-safe 于写入时而非事后扫描**。
10. **写入围栏（writer claim fencing）**（OC：`expectedWriterRunId` 事务内双重断言）——Neurova 有会话快照冻结（OpenOcta P2）但无写入权属断言；并行会话/旧 run 恢复后可能写脏历史（历史上发生过 stash/并行覆盖事故三例）。落点：会话历史追加咽喉。
11. **审批持久化状态机+渠道镜像路由**（OC：pending→resolved first-answer-wins+审批卡镜像到聊天渠道+决定后恢复原会话续跑）——Neurova approvals 端点已有底座；REPL/审批中断点在 OpenOcta 对比时已列为"审批可恢复中断点"启发，本条给出参照实现。
12. **TTS/语音缺口的清单化补课**（OC：16 provider autoSelectOrder+`[[tts:]]` 文内指令+音频预检）——Neurova 立即可抄的两件：语音消息先转写再走 @提及 判定（群聊不漏语音）、TTS provider 有序 fallback 表。ASR funasr 编排已有模型权重，差 5 图级联编排这最后一步。
13. **provider 真账单拉取**（OC：`src/infra/provider-usage*.ts` 20 文件直连各家后台）——Neurova token 估值的"sensetime 网关不回传"困局的正解：配额/账单从 provider 后台拉而非从流里抠。落点：usage_history 侧新增 provider-usage 采集器（默认关，逐 provider 开）。
14. **发布证据链 + 依赖冷却期**（OC：validation run id 绑定发布、`minimumReleaseAge` 7 天）——桌面版分发已有 NSIS 红线教训，这条是流程纪律不是代码。

### P2（方向级，长期）

15. **沙箱三态**（OC：mode×scope×backend，默认 `network:none/capDrop ALL/readOnlyRoot`）——Neurova 工具层无沙箱，短期不做，但工具 schema 可先加 `sandboxRequired` 声明位预留。
16. **Claw 式 agent 应用包**（OC：一清单=多 agent+skills+MCP+cron+tool-policy，带 rollback/provenance）——Neurova 的 agent 导入导出/市场提交可向此格式收敛。
17. **MITRE ATLAS 威胁模型文档**（OC：T-XXX 编号+信任边界图+攻击链）——Neurova 安全治理已有 fail-closed 实践，缺成文威胁模型；形式化验证（TLA+）仅供参考。
18. **净 LOC ≤ 0 修复教义成文**（OC：AGENTS.md Repair Doctrine）——把本项目已有的"放大视角找根因、禁止表面抹除"升级为可执行验收标准：bug fix 默认净增行数 ≤ 0。

### 已对齐项（无需动作）

seq/gap/sync_resume（≈OC 双层 seq+gap 探测，NV 的服务端补发在恢复完整性上甚至更强）、spawn 三明治（≈subagent registry+deny 表）、OTel bridge（≈diagnostics-otel）、错误归一五类（≈error 编码进流的另一半）、执行流式化（≈run/stream 分离）、TDD 纪律（≈源旁 1:1 测试的 NV 版）。

---

## 4. 结论

1. **总量级**：OpenClaw 8.9 / Neurova 7.0。差距集中在工程纪律（14 维差 3.5）、安全沙箱（4.0）、插件生态（4.0）、语音（4.0）；Neurova 在知识库/RAG（+3.0）与工作流编排（+1.5）保持优势。
2. **最值得警惕的一条**：OC 的记忆哲学——"检索不难，写路径才是难点；整理离线做、永不阻塞回复、写入时定信任级"。Neurova 现在的投入偏检索侧（MoE/重排/混合检索），晋升与防毒化侧基本空白。
3. **最便宜的一条**：seq 慢消费者两条例（#7）与流内错误编码（#1），都是"咽喉处加两行+一条契约测试"的量级。
4. **最不该抄的一条**：OC 的"trusted operator 单用户边界"——它把多用户隔离列为 out-of-scope（`SECURITY.md`），Neurova 的三层隔离/知识归属/技能权限是多租户平台的核心资产，不可为对齐而放弃。
5. **方法论收获**：OC 的"一职责一文件+文件头自述+同目录 1:1 测试"让 200 万行代码仍然可测——这比任何单个功能更值得学；以及它对 AI 贡献者（AGENTS.md/CLAUDE.md 逐目录宪法）与对供应链（补丁退场条件/依赖冷却期）的治理颗粒度。

---

## 附：主要证据文件索引

| 主题 | 路径 |
|---|---|
| Gateway 准入 | `src/gateway/agent-turn/agent-turn-service.ts`、`agent-admission-controller.ts`、`server-broadcast.ts` |
| Agent 循环 | `packages/agent-core/src/agent-loop.ts`、`src/agents/embedded-agent-runner/run-orchestrator.ts` |
| 写入围栏 | `src/config/sessions/session-accessor.sqlite-transcript-write.ts` |
| steer 语义 | `src/agents/` steering queue；`docs/concepts/queue-steering.md` |
| 入站队列 | `src/channels/message/ingress-queue.ts`、`ingress-drain.ts`、`receive.ts` |
| 渠道契约 | `src/channels/plugins/types.plugin.ts`、`types.adapters.ts` |
| 工具策略 | `src/agents/agent-tools.ts`、`tool-policy-pipeline.ts`、`agent-tools.policy.ts` |
| exec 审批 | `src/infra/exec-approvals-core.ts`、`exec-authorization-plan.ts`、`src/gateway/exec-approval-manager.ts`、`operator-approval-store.ts` |
| 沙箱 | `src/agents/sandbox/config.ts`、`network-mode.ts`、`validate-sandbox-security.ts` |
| 网络策略 | `packages/net-policy/src/*`、`src/infra/net/ssrf.ts` |
| 技能 | `src/skills/loading/*`、`src/skills/security/scanner.ts`、`skills/weather/SKILL.md` |
| 插件 | `src/plugins/api-builder.ts`、`src/plugins/hook-types.ts`、`packages/plugin-package-contract` |
| 记忆 | `extensions/memory-core/src/short-term-promotion.ts`、`dreaming.ts`、`extensions/memory-lancedb/lancedb-schema.ts`、`docs/concepts/memory-architecture.md` |
| LLM 栈 | `packages/llm-core/src/types.ts`、`packages/ai/src/providers/register-builtins.ts`、`src/config/model-provider-config.ts` |
| 工具调用修复 | `packages/tool-call-repair/src/index.ts`、`grammar.ts` |
| 语音 | `src/talk/talk-events.ts`、`session-runtime.ts`、`src/tts/*`、`src/realtime-transcription/provider-types.ts` |
| 可观测 | `src/audit/audit-recorder.ts`、`src/trajectory/types.ts`、`src/logging/redact.ts` |
| 状态迁移 | `src/state/openclaw-state-db.ts`、`openclaw-state-db-contract.ts` |
| 发布/供应链 | `.github/workflows/openclaw-npm-release.yml`、`pnpm-workspace.yaml`、`patches/README.md`、`AGENTS.md` |
| 威胁模型 | `docs/security/THREAT-MODEL-ATLAS.md`、`docs/security/formal-verification.md`、`SECURITY.md` |
