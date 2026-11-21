# reference_ac（T3 Code）vs Neurova —— 编码 Agent 控制平面对照评测

> 评测日期：2026-11-21。对象：`pingdotgg/t3code`（GitHub，67.8k stars，MIT，TypeScript monorepo，
> 主干约 20 万行 TS；服务端非测试源码 62,794 行、共享包 117,427 行、前端 2,602 个文件）。
> 方法：浅克隆源码 + 三路代码级深读（编排核心 / provider 接入层 / 协作与上下文传递）+
> 本仓 `neurova/agent/swarm*`、`neurova/agent/neuacp/` 现状盘点对照。全部结论附 file:line 证据。
> 本报告为竞品/外部对标研究参考；评分是「编码 agent 控制平面」专项视角，
> 不覆盖本仓记忆/知识/RSI/多渠道/移动端等域。

---

## 1. 执行摘要

T3 Code 是当前开源世界里「外部编码 agent 控制平面」完成度最高的实现：把 Claude Code、Codex、
Cursor、OpenCode、Grok、Antigravity、Kiro、Pi、Muse Code、fx 及任意 ACP agent 收敛到一套
事件溯源编排之上，桌面/Web/手机三端同构，手机可远程审批。**专项评分卡：T3 Code 92.0 vs
Neurova 72.0（20 子项百分制）**——在它的主场（编码 agent 编排与接入）大幅领先，尤其在
上下文传递、命令幂等、checkpoint 回滚、provider 治理四个面形成代差。

本仓的真实优势不在编排深度，而在**治理面**：多人房间审批回灌、租户隔离强制红线、
turn 准入治理、审批分级（L0/L1/L2）——这些恰是 T3 Code 的弱项（无全局并发治理、
无多人协作语义、默认 full-access 的权限取向）。

最值得本仓借鉴的五件事：**命令回执幂等、上下文传递工件化（含预算与可恢复省略）、
能力驱动的 provider 切换决策、审批请求持久化 + 记忆式批准、raw 诊断"记摘要不记值"**。
不建议照搬：Effect-TS 技术栈、万行巨石文件、云中继推送依赖、默认 full-access 取向。

---

## 2. 对象概况与成熟度信号

| 项 | T3 Code | 说明 |
|---|---|---|
| 定位 | "The open-source control plane for coding agents" | 驱动用户已登录的 agent，不倒卖 token |
| 形态 | pnpm monorepo：apps/server（含 orchestration-v2）+ apps/web/desktop/mobile + 19 个 packages | `packages/provider-*` 每家 agent 一个适配器包 |
| 规模 | 服务端 6.3 万行 + 共享包 11.7 万行（不含生成代码） | 契约包 34,356 行（orchestrationV2.ts 4,745 行） |
| 架构基座 | Effect-TS + SQLite + WebSocket RPC | 单进程单写者；发布走进程内 PubSub |
| 工程纪律 | AGENTS.md「Hit every surface」清单 + evals 真模型评测 + 性能回归审计 | 「dropped frame is a bug」 |
| 生态 | 67.8k stars / 11.7k forks，iOS+Android 商店上架，t3.codes 官网 | 成熟商业级开源产品 |

术语对照：T3 的 **thread/run/turn** ≈ 本仓会话/运行/轮；**provider** ≈ 本仓外部编码 agent
（neuacp 成员）；**environment** ≈ 一台运行 T3 server 的机器（本仓的节点/数据根概念）。

---

## 3. T3 Code 架构全景（代码级）

### 3.1 控制平面分层

```
Native provider protocol（stdio JSON-RPC / 专有 SDK）
  → 原始诊断流（双 ndjson，记摘要不记值）
  → Provider 适配器 / 归一化（ProviderEventIngestor）
  → V2 事件存储（EventStore，全局单调 sequence）
  → EventSink 单事务提交（事件+投影+回执+outbox）
  → 运行时执行图（AppThread→Run→ExecutionNode→ProviderThread）
  → 会话投影（projection）→ UI/API 视图
```

执行与控制分离：provider 进程、终端、Git、项目文件归属 server；三端客户端只经认证 RPC
订阅投影（`docs/internals/overview.md`；RPC 契约 `packages/contracts/src/rpc.ts`）。

### 3.2 命令-事件-幂等核心（编排引擎）

- 命令入口链：WS `dispatchCommand`（`apps/server/src/ws.ts:1999`）→ `ThreadMessageIntake` →
  `OrchestratorV2.dispatchWithReceipt`（`Orchestrator.ts:16884`，选锁：线程锁/fork 源锁/
  删除级联锁/父先子后锁序 `Orchestrator.ts:16303-16366`）→ `dispatchOnce` 大 switch 累积
  事件与副作用 → `eventSink.commitCommand` 单事务提交。
- **单事务一致性**：回执预留（`insertIfAbsent`）→ 事件追加 → 投影更新 → outbox 入队 →
  取消旧 effect，全部在一个 SQLite 事务；发布在提交后经信号量车道串行
  （`EventSink.ts:330-355, 788-897`）。
- **命令回执幂等**：`CommandReceiptV2 {commandId, status: accepted|rejected, resultSequence}`
  （`CommandReceiptStore.ts:43-52`）；重试先查回执，命中即用 `readByCommandId` 重放原事件流，
  不重跑副作用（`Orchestrator.ts:15972-16018`）；零事件命令与拒绝也落回执，语义闭环。
- **效果 outbox**：租约认领（`lease_owner` + 同线程串行谓词）、指数退避（maxAttempts=5，
  `EffectWorker.ts:985`）、进程崩溃对账双清单（process-bound 取消 / replay-safe 重置 pending，
  `EffectOutbox.ts:547-579`）、7 天保留失败行。
- **事件保留与重放**：投影覆盖后事件只留 1 天尾（`ProjectionMaintenance.ts:42`）；先发布
  pruned-through 边界再删除，保留 prompt 锚点与流头；客户端 cursor 过旧或回放超预算时
  明确降级 snapshotThenLive，绝不部分回放（`ws.ts:1060-1122`）。

### 3.3 执行图与上下文传递（多 agent 编排的灵魂）

- 图模型：`AppThread → Run(+RunAttempt) → ExecutionNode(kind: root_turn|tool_call|
  approval_request|subagent|... 九种) → ProviderThread/ProviderSession/ProviderTurn`
  （`contracts/orchestrationV2.ts:776-1313`）。子代理 = `kind:"subagent"` 节点
  （`countsForRun:false`）+ 独立子线程（`lineage.relationshipToParent:"subagent"`），
  commandId 确定性派生子 id 保证重放幂等（`Orchestrator.ts:9876-9985`）。
- **上下文传递五类型工件化**：`fork | provider_handoff | merge_back | subagent_spawn |
  subagent_result`（`contracts/orchestrationV2.ts:181-187`）。`ContextTransfer`（廉价、pending、
  惰性）与 `ContextHandoff`（昂贵、物化、含 coverage/omittedItems/delivery）分离
  （`ContextHandoffService.ts:48-102`）。
- **预算工程**：handoff 预算 = min(token 上限 16k, 64KiB, 窗口−原生占用−本轮输入−预留)，
  图片每张预留 8192 token（`packages/provider-core/src/server/handoffBudget.ts:105-133`）；
  放不下的消息**不丢弃**，记入 `omittedItemIds` 并给出 `t3_thread_read` 恢复协议。
- **三态投递**：native inject / inline 前缀 / uncertain——注入结果不确定时强制换新
  native thread，杜绝重复投递（`ContextHandoffDelivery.ts:113-155`）。
- **fork 惰性解析**：fork 时只记 pending transfer；首 run 才判定 native_fork（同 provider +
  strong native id + 完成态等）或 portable_context（全量摘要 handoff）
  （`ThreadForkService.ts:77-176`、`CommandPolicy.ts:418-441`）。
- **provider 中途切换**：`decideProviderSessionTransition` 五结果
  `reuse | switch_model_in_session | restart_and_resume | create_with_handoff | reject`
  （`ProviderSessionTransitionPolicy.ts:32-87`），上下文以 handoff 工件交割，预算超限
  「宁可失败不悄悄截断」（`failure.ts:20-27`）。

### 3.4 Checkpoint、结算与审批

- **隐藏 git ref 检查点**：`refs/t3/orchestration-v2/checkpoints/<sha>/ordinal/<N>`
  （`CheckpointService.ts:156-167`），不污染用户分支；回滚 = provider 会话回退 + 文件恢复 +
  投影回写 + worktree 重建，且有共享工作区隔离检查（不隔离只许会话级回退，
  `CheckpointRestoreSafety.ts:22-208`）。
- **线程自动结算**：PR merge 事件流 + 每分钟 sweep + 设置变更 + 领域事件四驱动
  （`ThreadSettlementService.ts:311+`）；九重护栏（pending 审批/活跃 run/PR watch/排队宽限/
  置顶/snooze 等一票否决）+ 提交时 live 二次校验（`Orchestrator.ts:15548-15566`）。
- **审批**：provider 请求归一为 `RuntimeRequest`（8 类 kind，`responseCapability:
  live|message|not_resumable`）持久化进投影，重启不丢；决策五档
  `accept | acceptForSession | acceptAlways | decline | cancel`（`providerPolicy.ts:58-65`），
  记忆式批准减少重复弹窗；经 AgentAwarenessRelay 推送到手机（走 T3 Connect 云通道）。

### 3.5 Provider 接入层（外部 IDE 智能体接入）

- **driver/adapter 分界**：driver 管实例存在性（安装/版本/配置/目录/登录控制器，
  `provider-core/src/server/driver.ts:117-128`），adapter 管单会话编排生命周期
  （`ProviderAdapterV2.openSession → SessionRuntime`：ensureThread/startTurn/steerTurn/
  respondToRuntimeRequest/rollbackThread/forkThread/injectHistory 等，
  `provider-core/src/server/ProviderAdapter.ts:700-836`）。
- **能力系统**：12 维 `OrchestrationV2ProviderCapabilities`（sessions/threads/turns/streaming/
  tools/approvals/planning/subagents/context/checkpointing/identity/runtimePolicy，
  `contracts/orchestrationV2.ts:405-422`）；切换策略、handoff 校验、会话复用全部由能力数据
  驱动，编排层不写 `if (driver === ...)`。
- **ACP 接入**：`effect-acp` 严格 NDJSON JSON-RPC（坏帧即断，不静默跳过）+ v1/v2 双代协商
  + `session/update` 背压队列（32 条/16Mi 字符）；`AcpSessionRuntime` 管进程全生命周期：
  Linux cgroup lease、POSIX 所有权台账、Windows `taskkill /T /F`、SIGTERM→grace→SIGKILL、
  uninterruptible finalizer 强杀兜底（`AcpSessionRuntime.ts:1438-1695`）。
- **registry 风味化复用**：Claude/Copilot/Devin 等 ACP agent 复用同一适配器，agent 差异压缩为
  声明式 `AcpAdapterV2Flavor`（claudeAcp.ts 仅 119 行）；新 agent 接入成本极低。
- **失败文案策展**：只透出白名单错误与固定指引，URL/Bearer/token 一律 redact，4096 截断
  （`provider-core/src/server/failure.ts:101-299`）；raw 诊断「never log payload values」，
  只记 valueType/byteLength/fieldCount/method（`nativeProtocolLogging.ts:10-31`）。
- **探测无副作用纪律**：健康检查/状态刷新不得触发登录浏览器、MCP 启动、hooks
  （`docs/internals/providers.md`「Setup must not happen as a health-check side effect」）。
- **凭据边界**：`ProviderAuthController` 统一 start/complete/cancel/logout + `withAccess`
  （凭据变更期间闸住会话启动）；实例间凭据按 binding 隔离；Anthropic/ChatGPT profile 迁移
  有专门 handoff 协议（`CodexChatGptHandoff.ts`）。

### 3.6 多端与远程

- 三端共享 `packages/client-runtime`（每环境一个连接 owner + 共享 reducer），订阅分 shell/
  thread detail 两层，cursor replay ↔ snapshot 自适应降级 + bounded/compact wire 协商
  （`docs/internals/connection-runtime.md`）。
- 远程三路由（direct LAN / Tailscale / T3 Connect）有序尝试 + supervisor 预检热切换 +
  learned routes；T3 Connect 中继只管凭证与隧道分配、不代理应用流量，DPoP 绑定设备
  （`docs/internals/remote.md`、`docs/internals/t3-connect.md`）。
- 权限天花板全链路收窄：composer → dispatch（DispatchModeLimit）→ MCP 子任务（不得宽于父）→
  跨环境 `T3-Mode-Limit` 头（只收窄不放大）→ 组织 managed policy ceiling；`RuntimeMode`
  四档带 rank 序，provider 不支持的档位自动降为 Supervised（`RuntimePolicy.ts:92-99`）。

### 3.7 主要弱点（代码级）

1. `Orchestrator.ts` 17,137 行、`ClaudeAdapterV2.ts` 14,900 行、`provider-acp/adapter.ts`
   10,659 行——巨石文件，评审/回归成本高，与本仓「尺寸棘轮」哲学相悖。
2. 单进程单写者假设：发布是进程内 PubSub，effect 取消信号是进程内 Map，无水平扩展路径。
3. 无全局并发配额/准入：并行 thread 数只受机器资源约束，负载均衡仅是客户端偏好。
4. portable handoff 是有损摘要（240 字符压缩），跨 provider 长任务细节可能只存在于被省略项。
5. 效果失败处理沉默：无死信队列/告警/管理端重放入口。
6. 审批推送、outside-agent OAuth、webhook 离线持有强依赖 T3 Connect 云；自托管/离线场景
   体验退化（直连/Tailscale 无后台推送）。
7. 默认 `full-access` 的权限取向，面向个人开发者而非企业多租户。

---

## 4. 评分卡（20 子项，每项 5 分，百分制）

> 打分口径：0-2 缺失/玩具级，3-4 有实现但有断点，5-6 可用但单薄，7-8 生产可用有短板，
> 9-10 该维度业界标杆。证据均为本仓代码或 T3 Code 源码 file:line（见 §3 与文末索引）。

### A. 编排模型（25 分）

| 子项 | Neurova | T3 Code | 依据（一句话） |
|---|---|---|---|
| A1 生命周期状态机 | 8.0 | 9.5 | 本仓 `RUN_STATUS_TRANSITIONS` 迁移表+`transitionRun` 收口 13 处+`reconcileRunFromEvents` 重放收敛（swarm_support.py:54）；T3 十态 run+attempt 代际+节点九态+终态质量分级 |
| A2 事件溯源与审计 | 7.5 | 9.5 | 本仓 H-4 七事件账本+span trace+请求级 JSONL 归档，但非全量事件溯源、无投影重放；T3 event store+投影+回执+raw 诊断双流 |
| A3 幂等与恢复 | 6.5 | 9.5 | 本仓候选 CAS 合并/审批单幂等，无命令级回执；T3 command receipt+`insertIfAbsent`+按命令重放+outbox 租约对账 |
| A4 并发治理 | 8.0 | 7.0 | 本仓 turn 准入（requestTurnAdmission/park）+子代理深度限制+token 保证金；T3 无全局配额，仅单线程串行+effect 并发 4 |
| A5 结算与收敛 | 5.5 | 9.0 | 本仓有验收门/评审门，无线程自动结算；T3 四驱动 sweep+PR merge 事件+九重护栏+live 二次校验 |

### B. 执行图与上下文（20 分）

| 子项 | Neurova | T3 Code | 依据 |
|---|---|---|---|
| B1 子代理建模 | 8.0 | 9.5 | 本仓 SubAgentRun+cancel/continue/steer+台账租户行+谱系；T3 ExecutionNode 树（countsForRun:false）+delegated_task 幂等派生+完成投递 cohort+原生/app_owned 双轨 |
| B2 上下文传递 | 4.5 | 9.5 | 本仓仅任务书组合+继续轮提示，无跨 run/跨 agent 上下文工件；T3 五类型工件+三重预算+三态投递+omitted 可恢复 |
| B3 checkpoint 回滚 | 7.0 | 9.5 | 本仓检查点回滚域已建（四域审计修复）；T3 隐藏 git ref+增量快照+provider 会话协同回退+共享工作区隔离检查 |
| B4 依赖与队列 | 7.5 | 8.5 | 本仓依赖门控+任务拆解；T3 queued-run reorder/cancel/edit+dispatch intent 四态（start/steer/restart/queue） |

### C. 外部 agent 接入（25 分）

| 子项 | Neurova | T3 Code | 依据 |
|---|---|---|---|
| C1 协议覆盖 | 7.5 | 9.5 | 本仓 ACP v1 stdio+SSH+plugin(ZCode)+七家预设；T3 十一家原生适配+ACP registry 任意 agent |
| C2 能力声明与降级 | 8.5 | 9.5 | 本仓能力目录五维+保守缺省 fail-closed+打开前双闸（catalog.py）；T3 12 维 struct+降级路径全由能力数据驱动 |
| C3 进程治理 | 8.0 | 9.5 | 本仓进程池租户键+帧账本+fail-closed+stderr 尾+超时（acp_client.py）；T3 cgroup/进程组/所有权台账/taskkill+超时矩阵+重试预算+OOM 改写 |
| C4 认证与凭据 | 8.0 | 9.0 | 本仓 keyring 按数据根派生+后缀展开+API-key 禁配外部成员；T3 ProviderAuthController+binding+withAccess+探测无副作用 |
| C5 provider 切换与接续 | 4.5 | 9.5 | 本仓仅模型切换记账，无跨 provider 会话接续；T3 五结果决策+handoff 工件+预算硬校验（宁败不截） |

### D. 协作与人在环（15 分）

| 子项 | Neurova | T3 Code | 依据 |
|---|---|---|---|
| D1 审批链 | 8.5 | 9.0 | 本仓 L0/L1/L2 分级+房间多人回灌+ApprovalManager 单源+neuacp `session/request_permission` 同步映射（approval_chain.py、acp_executor.py:228-243）；T3 八类请求+五档记忆式决策+持久化+手机推送 |
| D2 权限天花板 | 7.5 | 9.5 | 本仓成员门+MAIN_AGENT_ONLY_TOOLS+租户隔离红线；T3 rank ceiling 四层收窄+managed policy+自动降档 Supervised |
| D3 多端与远程 | 8.0 | 9.5 | 本仓 PC/鸿蒙/安卓三端+relay 自托管+配对三档+SSH 代部署；T3 三路由热切换+learned routes+DPoP+中继不碰流量 |

### E. 工程方法（15 分）

| 子项 | Neurova | T3 Code | 依据 |
|---|---|---|---|
| E1 评测体系 | 7.5 | 8.5 | 本仓 suite_eval 执行器+APEX 任务集+benchmark 基线；T3 evals 包「先 case 后修」+真实模型+成本标注+grader 自测 |
| E2 契约与兼容 | 7.0 | 9.5 | 本仓 OpenAPI+契约对齐测试；T3 contracts 单源 3.4 万行+wire 双向兼容+回放兼容纪律 |
| E3 性能与资源治理 | 7.0 | 9.0 | 本仓 bundle 预算棘轮+真构建标定；T3 性能回归审计+wire 压缩协商+steady shells+内存限额自停 |

### 总分

| | Neurova | T3 Code（reference_ac） |
|---|---|---|
| A 编排模型 | 35.5 / 50 | 44.5 / 50 |
| B 执行图与上下文 | 27.0 / 40 | 37.0 / 40 |
| C 外部 agent 接入 | 36.5 / 50 | 47.0 / 50 |
| D 协作与人在环 | 24.0 / 30 | 27.5 / 30 |
| E 工程方法 | 21.5 / 30 | 26.0 / 30 |
| **合计（百分制）** | **72.0** | **92.0** |

解读：这是「编码 agent 控制平面」**专项**对照——T3 Code 整个产品就是这件事，20 万行全部
砸在这一个面上；本仓是全栈 agent 平台，编排只是其中一域。专项落后 20 分主要来自四个
代差：上下文传递（B2，−5）、provider 切换接续（C5，−5）、命令幂等（A3，−3）、
checkpoint 协同回滚（B3，−2.5）。本仓反超的两个半子项：并发准入治理（A4）、
审批多人协作（D1 房间回灌）、租户隔离（D2 的一部分）——这些是 T3 Code 没有或更弱的
企业向能力。

---

## 5. 值得本仓借鉴的清单

### P0（高价值、低耦合，建议优先立项）

1. **命令回执幂等**（T3 `CommandReceiptStore`）。给 swarm 派活/审批应答/候选合并等写路径
   加 `command_id → receipt(status, resultSequence)`，事务内 `insertIfAbsent`，重试按
   commandId 重放结果而不重跑副作用。落点：`neurova/agent/swarm.py` dispatch 入口与
   `neurova/core/agent_run_ledger.py`。直接收益：消除「网络重试→重复派活/重复合并」类故障，
   也是 WebSocket 断线重连语义的地基。
2. **上下文传递工件化**（T3 `ContextTransfer`/`ContextHandoff`/`handoffBudget`）。把「继续
   轮/换人接手/子代理结果回传」从自由文本升级为结构化工件：source point（run/checkpoint
   粒度）+ 策略（delta/full summary）+ 预算（token/字节双上限）+ omitted 清单与按需恢复。
   落点：`swarm.py` 的 `composeTeamDutyTask`/`updateSubagent`（steer/restart）与
   `neuacp` 二次 chat 会话复用。这是本仓评分最低而收益最大的单点。
3. **能力驱动的切换/接续决策**（T3 `decideProviderSessionTransition` 五结果）。本仓
   neuacp 能力目录（catalog.py）已有 transports/streaming/session_reuse 等声明，补一个
   「换模型/换 agent/续跑」决策函数：复用会话 / 会话内换模型 / 重启续跑 / 建 handoff /
   拒绝——让 OpenCode↔ZCode 等跨家交接有判据，而不是每处 if-else。
4. **raw 诊断「记摘要不记值」**（T3 `nativeProtocolLogging.ts`）。本仓 `frame_log.py` 帧账本
   目前整帧落盘；改为 64KiB 编码预算 + 结构摘要（类型/字节长/字段数/方法名）+ 值脱敏，
   防 prompt/密钥/超大输出进日志，同时保留排障路由信息。

### P1（体系补强）

5. **隐藏 git ref 检查点**（T3 `refs/t3/orchestration-v2/checkpoints/<sha>/ordinal/N`）。
   本仓检查点域若基于工作区提交，可改为隐藏 ref+增量快照：不污染用户分支、支持按 run
   序号回滚，并补「回滚前 provider 会话协同回退 + 共享工作区隔离检查」两道护栏。
6. **审批请求持久化 + responseCapability**（T3 `RuntimeRequest`）。本仓审批单已在
   ApprovalManager 持久化，补齐两件事：请求分类（command/file-change/mcp-elicitation/
   permission/user_input）与 `live | message` 双通道（同步裁决 vs 轮次结束后仍可回答），
   并保证「审批先 resolve 再投递，投递失败可观测」。
7. **记忆式批准**（T3 `acceptForSession/acceptAlways`）。审批链 L1 档增加「本会话内/
   本团队内同类操作免再批」，减少长任务中重复弹批；过期与撤销走既有审批单生命周期。
8. **探测无副作用纪律**（T3 providers.md）。catalog 的 `installed` 探测、管理面 `/test`
   握手、状态轮询不得触发登录、MCP 启动、hooks——探测与「真正启用」分离。落点：
   `neuacp/catalog.py` 探测与 teams 管理面测试连接。
9. **evals「先 case 后修」**（T3 `evals/README.md`）。凡改动影响模型所见（工具描述、
   提示词、任务书、验收 rubric），先在 `suite_eval` 加一个会失败的 case（附来源），再改
   实现；case 必须旧文本红、新文本绿。与本仓「先红后绿」教义同源，把它延伸到 LLM 输出面。
10. **子代理完成投递 cohort**（T3 `DelegatedCompletionDelivery` acknowledge/dispose）。
    父代理忙时子代理结果先规划投递（pending→claimed→acknowledged/delivered/disposed），
    父 run 空闲或 steering 时注入。落点：`swarm.py` `pushParentMail` 链路，防「结果邮件
    在父会话结束后静默丢失」。

### P2（视产品节奏）

11. **事件保留窗口 + pruned-through 边界 + 快照降级**：H-4 账本与 span 数据设定保留窗口，
    超窗订阅端明确降级为快照，不提供部分重放。
12. **effect outbox 租约/退避/崩溃对账**：异步副作用（通知、投影、回执外发）统一 outbox
    表 + 租约认领 + 指数退避 + 进程重启对账（进程绑定类取消、可重放类重排）。
13. **线程自动结算护栏组**：长期空闲/已合并的 swarm run 自动 settle，配 T3 式九重护栏
    （活跃 run/pending 审批/置顶等一票否决 + 提交时 live 二次校验）。
14. **安装器所有权证明**（T3 `providerMaintenanceRunner`）：provider 升级只经「可证明拥有
    该二进制」的安装器执行，否则 manual-only。落点：neuacp catalog 的 install_hint。
15. **订阅 cursor replay/snapshot 自适应**：WS 订阅带 `afterSequence`，服务端按回放量
    预算决定重放或快照，先订阅后读库防漏事件。落点：`neurova/api` WS 推送面。

### 不建议照搬

- **Effect-TS 技术栈与 17k 行 Orchestrator/14.9k 行适配器**：与本仓尺寸棘轮、深模块模式
  相悖；T3 自己的弱点清单也承认评审成本失控。
- **默认 full-access 权限取向**：面向个人开发者的产品选择；本仓企业多租户场景应保持
  保守缺省（fail-closed）。
- **云中继推送依赖**：T3 的手机推送/OAuth/webhook 强绑定 T3 Connect 云；本仓 relay
  自托管 + SSH 代部署路线保持独立，勿为推送引入云依赖。
- **双协议栈并行**（effect-acp 与 effect-codex-app-server 高度同构）：本仓坚持单一 ACP
  事实源，不为个别 agent 再造第二套协议层。

---

## 6. 证据索引与方法说明

- 对象版本：github.com/pingdotgg/t3code 主干（克隆于 2026-11-21，浅克隆 605MB，
  树含 37,501 项）。分析范围：apps/server/src/orchestration-v2（456 文件）、
  packages/provider-*、packages/contracts、packages/client-runtime、docs/（internals +
  orchestration-v2 全套）。
- 本仓对照面：`neurova/agent/swarm.py`、`neurova/agent/swarm_support.py:54`
  （RUN_STATUS_TRANSITIONS）、`neurova/agent/approval_chain.py`（L0/L1/L2）、
  `neurova/agent/neuacp/`（acp_client.py 422 行、catalog.py、process_pool.py、frame_log.py、
  ssh_transport.py）、`neurova/core/agent_run_ledger.py`（turn admission）。
- T3 Code 关键证据（相对其仓库根）：`apps/server/src/orchestration-v2/Orchestrator.ts`
  （17,137 行；dispatchWithReceipt 16884、锁序 16303-16366、幂等重放 15972-16018）、
  `EventSink.ts`（单事务 330-355/788-897）、`EffectOutbox.ts`（租约 581-633、崩溃对账
  547-579）、`ContextHandoffService.ts`（48-102）、`handoffBudget.ts`（packages/provider-core/
  src/server/，105-133）、`CheckpointService.ts`（156-167）、`CheckpointRollbackService.ts`
  （143-420）、`ThreadSettlementService.ts`、`ProviderSessionTransitionPolicy.ts`（32-87）、
  `packages/provider-acp/src/server/AcpSessionRuntime.ts`（进程治理 1438-1695）、
  `packages/contracts/src/orchestrationV2.ts`（4,745 行契约）、`docs/orchestration-v2/*`
  （九篇目标架构文档）、`docs/internals/providers.md`（协议陷阱与所有权纪律）。
- 评分为主观校准的专家评分（20 子项，逐项列证据），非基准测试跑分；子代理三路深读
  交叉验证了编排核心、provider 层、协作面的关键结论。
