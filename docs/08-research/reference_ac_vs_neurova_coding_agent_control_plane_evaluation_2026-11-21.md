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

---

## 复评记录（2026-11-21，对照 T3 当期主干 6f94a063）

> 复评时点：追平计划三批 19 卡实施完毕后（本仓 b224e856b 批一 → 9d826dc98 批二 → 13facd9c2 批三，
> 另有 d00e0e836 投递销账闭环、f1a9a2dc9 接线覆盖补强两笔收口）。T3 浅克隆已更新至当期主干：
> `6f94a063845021634c35d8f2d97db558290fdb1d`（2026-11-20 20:42 -0800，"fix(vcs): explain checkout
> failures caused by local changes (#23346)"；原报告快照为 e19193db，2026-11-20 16:17 -0800）。
> 评分口径沿用原卡（每子项 0-10、五大类 A-E 同权重），证据全部按当期代码重取，行号为复评现场读数。
> 口径修正一处：原表 T3 D 类合计 27.5、E 类合计 26.0 与子项和（28.0、27.0）不符，本次按子项和计，
> T3 总分相应由 92.0 修正为 91.8——属笔误修正，非 T3 退步。

### 20 子项对照（原分 → 新分）

| 子项 | Neurova | T3 Code | 关键证据（本次现场读数） | 变化原因 |
|---|---|---|---|---|
| A1 生命周期状态机 | 8.0 → **9.0** | 9.5 → 9.5 | 本仓 `swarm_support.py:60`（RUN_STATUS_TRANSITIONS）、`:122` classifyTerminalQuality、`:147` requiresReviewConfirmation、`:183` transitionRun 写 terminal_quality；T3 `orchestrationV2.ts:682-691`（run 十态）、`:866-880`（节点 11 kind） | 本方新能力：终态质量分级（strong/weak/none）入状态机+复核判定，补齐原判据；T3 十态+attempt 代际+节点图无实质漂移，仍略深 |
| A2 事件溯源与审计 | 7.5 → **8.5** | 9.5 → 9.5 | 本仓 `swarm_event_store.py:181-198`（after_seq 重放/预算降级）、`:78` pruned-through、`swarm.py:348` 双写镜像；T3 `EventSink.ts:788` 单事务提交 | 本方新能力：全局单调 seq 事件库+重放协议+先发布后清理+流头保护；差距：本方事件库是 JSONL 账本的 fail-open 镜像，非 T3 式单写路径事件溯源 |
| A3 幂等与恢复 | 6.5 → **8.5** | 9.5 → 9.5 | 本仓 `core/command_receipt.py`（running/accepted/rejected 三态）、`swarm.py:860-887`（dispatchTeam 接线）、`:1736-1742`（cancelRun 接线）；T3 `CommandReceiptStore.ts:43-68`、`Orchestrator.ts:16022/:16164/:15994` | 本方新能力：命令回执+同 ID 重放不重跑副作用+跨 thread conflict+拒绝落回执；差距：T3 另有 effect outbox 租约/退避/崩溃对账（本方 P2 未立项） |
| A4 并发治理 | 8.0 → 8.0 | 7.0 → 7.0 | 本仓 `agent_run_ledger.py:64-77`（turn 准入/park）；T3 `EffectWorker.ts:802/:1054`（maxAttempts=5、effect 并发上限，全仓无全局配额） | 双方无漂移：本方 turn 准入治理保持领先；T3 仍无全局并发配额 |
| A5 结算与收敛 | 5.5 → **8.0** | 9.0 → 9.0 | 本仓 `run_settlement.py`（九护栏纯函数）、`swarm.py:442-450`（TaskScheduler 每小时）、`:1194` settleIdleRuns；T3 `ThreadSettlementService.ts:346` sweep、`:165/:223` 护栏 | 本方新能力：idle sweep+九护栏一票否决+提交前 live 复核+幂等；差距：T3 四驱动（含 PR merge 事件流）且常开，本方默认关、仅 idle 驱动 |
| B1 子代理建模 | 8.0 → **9.0** | 9.5 → 9.5 | 本仓 `delegated_delivery.py`（投递状态机+审计+messageId 幂等）、`swarm.py:359-360`（pushParentMail 唯一写点）、`:3351` catchUp；T3 `orchestrationV2.ts:890` countsForRun、DelegatedCompletionDelivery（Orchestrator/ProviderContinuationService/ProviderSessionManager） | 本方新能力：完成投递 cohort pending→claimed→acknowledged\|disposed+父闲补投+ack 镜像生产闭环；T3 执行图节点树+确定性派生 id 仍领先 |
| B2 上下文传递 | 4.5 → **8.0** | 9.5 → 9.5 | 本仓 `context_transfer.py:21-23`（16k/64KiB 预算常量）、`:101` computeHandoffBudget、`:148` selectHistory、`swarm.py:2036-2044/:2095-2132`（续跑接线+事件留痕）；T3 `orchestrationV2.ts:181-187`（五类型）、`ContextHandoffService.ts`、`handoffBudget.ts:100-140`（活窗口预算） | 本方新能力：交接工件+双预算（超限报错不静默截断）+omitted 留痕+三态投递；差距：本方接线仅续跑路径、静态预算；T3 五类型贯通 fork/切换/spawn/result 全链路且预算按活窗口动态计算+图片预留 |
| B3 checkpoint 回滚 | 7.0 → **8.5** | 9.5 → 9.5 | 本仓 `checkpoints/service.py:44` scopeRefFor、`:347` captureScope、`:364` restoreScope、`:388` pruneScope(保留 20)；T3 `CheckpointService.ts:28`（refs/t3 隐藏 ref）、`CheckpointRestoreSafety.ts` | 本方新能力：隐藏 ref scope 检查点+ordinal 增量+共享工作区隔离回退+诚实拒绝；差距：T3 的 provider 会话协同回退真执行+worktree 重建，本方 conversation_rollback 维度保守缺省、协同回退未活 |
| B4 依赖与队列 | 7.5 → **8.5** | 8.5 → 8.5 | 本仓 `run_queue.py`（优先级/位次/取消/修订三态）、`swarm.py:3220-3251`（管理面）；T3 `Orchestrator.ts:681-686`（queued-run start/reorder/cancel/edit、promote-to-steer、queue.resume） | 本方新能力：队列管理面落地；与 T3 queued-run 治理拉平（T3 另有 promote-to-steer 细分，本方以 edit 走 steer/重排三态覆盖） |
| C1 协议覆盖 | 7.5 → **8.0** | 9.5 → 9.5 | 本仓 `catalog.py:400` probeToolHealth、`:494` presetHandshakeProfiles（Gemini/Claude/Codex 档案）；T3 provider-* 10 包+effect-codex-app-server+provider-acp-registry+`contracts/acpRegistry.ts` | 本方新能力：三家握手预设+无副作用健康探测；三家真 CLI 握手 live 未启用（计划登记另做），T3 十一家原生适配+registry 任意 agent 仍代差 |
| C2 能力声明与降级 | 8.5 → **9.0** | 9.5 → 9.5 | 本仓 `catalog.py:33-39`（BOOLEAN_CAPABILITY_DIMS 九维单源）、`:225/:276` refuseExecutorSpec 逐维双闸、`:325` 决策消费；T3 `orchestrationV2.ts:405-422`（12 维能力组） | 本方新能力：能力维度扩至九维+保守缺省+打开前逐维校验+决策消费一致；T3 12 维按域嵌套分组结构仍略深 |
| C3 进程治理 | 8.0 → **9.0** | 9.5 → 9.5 | 本仓 `process_governance.py`（TIMEOUT_MATRIX/terminateProcessGroup/RetryBudget/classifyFailure OOM 改写）+真子孙进程活体测试；T3 `AcpSessionRuntime.ts:255-429`（cgroup lease）、`:996-1009`（SIGTERM→SIGKILL）、`:1042-1069`（taskkill /T /F） | 本方新能力：进程组级回收（含孙进程）+超时矩阵单源+重试总预算+OOM 诚实改写；差距：T3 另有 cgroup lease+POSIX 所有权台账 |
| C4 认证与凭据 | 8.0 → **8.5** | 9.0 → 9.0 | 本仓 `credential_gate.py`（轮换闸门 RLock）、`acp_member.py:303` assertNoRotation 接线、`catalog.py:400`（探测浅/深分级）；T3 `provider-core/server/auth.ts`、`providerAuthFlow.ts`、`apps/server/src/provider/ProviderAuthService.ts`（withAccess） | 本方新能力：凭据轮换闸门（变更期拒绝新会话）+探测默认零子进程；差距：T3 auth 全生命周期控制器+实例间 binding 隔离 |
| C5 provider 切换与接续 | 4.5 → **8.0** | 9.5 → 9.5 | 本仓 `catalog.py:328` decideProviderTransition（五结果）+resumeFinishedRun 续跑能力门；T3 `ProviderSessionTransitionPolicy.ts:15-20`（五结果）、`:37` decideProviderSessionTransition | 本方新能力：五结果决策函数+能力声明驱动的续跑门（缺声明诚实拒绝）；差距：跨 executor handoff 因 handoff_inject 无声明保守 reject（保守正确），实际跨家接续未活；T3 活体交割+选择迁移计划仍领先 |
| D1 审批链 | 8.5 → **9.0** | 9.0 → 9.0 | 本仓 `approval_chain.py:411` acceptForSession、`:446` acceptAlways、`:481` revokeGrant、`:555` matchGrant、`:731`（L2 永不记忆红线）；T3 `providerPolicy.ts:45-63`（请求 kind+五档决策）、`orchestrationV2.ts:1355` responseCapability | 本方新能力：记忆式批准两档（只降不升、L2 红线、可撤销、团队档原子持久化）+投影读面+decision_source 审计；与 T3 五档+持久化拉平（本方房间多人在环占优，T3 手机推送占优） |
| D2 权限天花板 | 7.5 → **8.5** | 9.5 → 9.5 | 本仓 `security/permission_mode.py:164` orgCeiling、`:180` applyOrgCeiling、`:199-200` delegateMode、`tool_executor.py:553-566` delegatedModeScope（三入口 `:3132/:3209/:3651`）；T3 `DispatchModeLimit.ts:49-71`（ceiling 收窄）+T3-Mode-Limit 头三处 | 本方新能力：rank 天花板+组织封顶+派活链单入口（只降不升、不支持档位诚实降档）；差距：T3 四层收窄另含跨环境请求头与 MCP 子任务不得宽于父 |
| D3 多端与远程 | 8.0 → **8.5** | 9.5 → 9.5 | 本仓 `api/subscription_resume.py`（resolveResumeMode 三态/reconnectBackoff/dedupBySequence）、`mobile_ws_ledger.py:219` oldestSeq、`:237-247` sync_resume；T3 `docs/internals/t3-connect.md:48-69`（DPoP）、`remote.md`、`connection-runtime.md` | 本方新能力：cursor 续传三态决策+三端退避单源+去重保序+诚实 sync_snapshot_required（不做部分重放）；差距：T3 三路由热切换+learned routes+DPoP 云中继是完整远程产品面 |
| E1 评测体系 | 7.5 → **8.5** | 8.5 → 8.5 | 本仓 `benchmark/suite_eval.py:138` EvalCase、`:175` registerEvalCase+validateCaseFirst+assertCaseRedGreen+costNote；T3 `evals/README.md`（"Add the case before the fix"+成本标注+CI 只跑 grader 单测） | 本方新能力：先 case 后修机制+来源/成本标注+纪律三落点同步；与 T3 evals 纪律拉平（T3 真模型套件更多） |
| E2 契约与兼容 | 7.0 → **8.0** | 9.5 → 9.5 | 本仓 `tests/unit/api/test_wire_backward_compat.py`（14 守卫+红灯实证）、`docs/09-dev-progress/contract-change-log.md`；T3 `packages/contracts` 34,497 行、`orchestrationV2.ts:419-421`（replay 解码缺省） | 本方新能力：wire 向后兼容守卫+历史样例回归+契约变更登记表；差距：T3 契约单源包被服务端+三端共同消费、双向兼容纪律成体系 |
| E3 性能与资源治理 | 7.0 → **8.0** | 9.0 → 9.0 | 本仓 `api/ws_stream_budget.py`（gzip 协商/单帧 64KiB 上限/ReplayByteBudget）、`realtime_push.py:33/:107-169`（ssePushStream 接线+snapshot_downgrade 通告）；T3 `docs/internals/performance-regressions.md`（v2-wire 字节预算回归门） | 本方新能力：WS 压缩协商+回放字节预算+快照降级通告（游标只按已外发帧推进防漏帧）；差距：T3 有真构建性能回归审计门，本方无同级回归套件 |

### 总分对照

| | Neurova | T3 Code（reference_ac） |
|---|---|---|
| A 编排模型 | 35.5 → **42.0** / 50 | 44.5 → 44.5 / 50 |
| B 执行图与上下文 | 27.0 → **34.0** / 40 | 37.0 → 37.0 / 40 |
| C 外部 agent 接入 | 36.5 → **42.5** / 50 | 47.0 → 47.0 / 50 |
| D 协作与人在环 | 24.0 → **26.0** / 30 | 27.5 → **28.0** / 30（口径修正：按子项和） |
| E 工程方法 | 21.5 → **24.5** / 30 | 26.0 → **27.0** / 30（同上） |
| **合计（百分制）** | **72.0 → 84.5** | **92.0 → 91.8**（口径修正） |

T3 当期主干与原快照相隔约四小时（e19193db → 6f94a063），20 子项逐项重读无实质漂移
（节点 kind 由 9 种增至 11 种等属增量演化），T3 各项维持原分。

### 仍未达标子项（16 项，按差距排序）

| 子项 | 差距 | 剩余差距原因 |
|---|---|---|
| B2 上下文传递 | −1.5 | 接线仅续跑单路径；T3 五类型贯通 fork/provider 切换/spawn/result 全链路，预算按活窗口动态计算+图片预留 |
| C1 协议覆盖 | −1.5 | Gemini/Claude/Codex 仅预设+探测，真 CLI 握手 live 未启用；T3 十一家原生+ACP registry 任意 agent |
| C5 切换与接续 | −1.5 | 决策函数已建并作续跑门，但跨 executor handoff 因 handoff_inject 无声明保守 reject，实际跨家接续未活；T3 活体交割 |
| E2 契约与兼容 | −1.5 | 本方为守卫测试+变更登记；T3 是 3.4 万行契约单源包+服务端三端共同消费+双向兼容纪律 |
| A2 事件溯源 | −1.0 | 本方事件库为 JSONL 账本 fail-open 双写镜像，非单写路径事件溯源；无全量投影重建 |
| A3 幂等与恢复 | −1.0 | 回执已覆盖派活/续跑/取消三写路径；effect outbox（租约/退避/崩溃对账）属 P2 未立项 |
| A5 结算与收敛 | −1.0 | 仅 idle sweep 且默认关；T3 为 PR merge 事件流等四驱动且常开 |
| B3 checkpoint 回滚 | −1.0 | 隐藏 ref+隔离回退已落地；provider 会话协同回退依赖能力声明（保守缺省 False），未真执行 |
| D2 权限天花板 | −1.0 | 派活链封顶已落地；T3 另覆盖跨环境请求头与 MCP 子任务两层收窄 |
| D3 多端与远程 | −1.0 | cursor 续传已落地；T3 三路由热切换+DPoP 云中继为完整远程面 |
| E3 性能治理 | −1.0 | WS 预算/压缩已落地；T3 有真构建性能回归审计门 |
| A1 状态机 | −0.5 | 终态质量分级已补齐；T3 另有 attempt 代际+执行图节点状态 |
| B1 子代理建模 | −0.5 | 投递 cohort 已补齐；T3 执行图节点树+确定性派生 id 更深 |
| C2 能力声明 | −0.5 | 九维单源已落地；T3 12 维按域嵌套分组 |
| C3 进程治理 | −0.5 | 进程组回收+超时矩阵+重试预算已落地；T3 另有 cgroup lease+所有权台账 |
| C4 认证与凭据 | −0.5 | 轮换闸门+探测分级已落地；T3 auth 生命周期+binding 隔离更深 |

### 达成判定

- **未全面达标（部分达成）**。追平目标口径「20 子项全部 ≥ T3 当期读数」不成立：
  16 项落后（子项分合计尾差 14.5，折百分制约 7.3 分）、3 项拉平（B4/D1/E1）、
  1 项反超保持（A4，+1.0）。
- 总分：Neurova **72.0 → 84.5**，T3 **92.0 → 91.8**（口径修正后），净差由 20.0 收窄至 **7.3**。
- 追平计划预计「第三批完成 ≈93 分」系按全部子项追平的乐观口径；本次客观复评为 **84.5**。
  机制面（命令回执、上下文工件、切换决策、权限天花板、投递账本、流预算、终态分级、
  记忆式批准、evals 纪律）已系统性补齐；剩余差距集中在两类：
  **接线广度**（B2 多触发点、C5 活体 handoff、C1 三家真握手）与
  **体系深度**（A2 单写事件溯源、A3 effect outbox、E2 契约单源、E3 性能回归门、C3 cgroup），
  均为可继续立项的明确后续，不是机制缺失。
- 复评纪律说明：本次不为追分放水——B2/C1/C5 虽已实施，因接线广度/活体启用未达
  「生产可用无短板」档位，未给 9 分档；T3 侧逐项重读无退步证据，各项维持原分；
  唯一分数变动是 D/E 类合计的笔误修正（27.5→28.0、26.0→27.0）。

---

## 复评记录二（2026-11-21，第二轮，T3 主干 80871270）

> 复评时点：第一轮复评（提交 17e8f04ba 回填）之后的新工作——A1 深化（依赖门消费终态质量）
> +B4 深化（/v1/swarm-queue 管理面 REST+queue_position 投影）（d6e519460，先于首轮复评提交
> 约 1 分钟落树、首轮未及计入，本轮补核）、harmony WS 订阅稳态化（ee14cddef）、前端三增强
> （f2bb26be1）+benchmark cost_note 端点透传（2a23b398f）、E3 列表渲染回归门（36c35fc86）
> 与两处无界列表收口（58d0c9061）、D-G 三家真握手 live-verify+ACP protocolVersion 线上类型
> 根修+帧钩子 flaky 清偿（6d81d55e3）、D-A 交接预算 16k→32k（5ce25df94）、D-B 非 admin
> 中途切换 provider+租户隔离红线（b344b8e96）。
> T3 浅克隆再 fetch 确认漂移：主干前进一笔——`80871270f9a13955a25ac5513aab8ac255065878`
> （2026-11-20 21:42 -0800，"perf(server): ask npm once per global prefix for provider latest
> versions (#40109)"），改动仅 `packages/provider-core/src/server/maintenanceResolver.ts`
> 及其测试（provider 版本探测去重，纯性能优化），与 20 子项能力面无交集——T3 逐项维持原分。
> 评分口径沿用原卡（每子项 0-10、五大类同权重）；本仓证据全部按当前树（c7ada5e6d）现场读数。

### 调分项（3 项，原分 → 新分）

| 子项 | Neurova | T3 Code | 关键证据（本次现场读数） | 变化原因 |
|---|---|---|---|---|
| C1 协议覆盖 | 8.0 → **8.5** | 9.5 → 9.5 | 本仓 `neurova/agent/neuacp/acp_client.py:179-198`（protocolVersion 线上整数类型根修+宽松服务端兼容）、`tests/unit/agent/neuacp/strict_initialize_agent.py`（按 ACP schema 复刻真 CLI 严格校验）；真机三家握手 live-verify 全 PASS（opencode 1.2.27 / claude-code 适配器 / codex 适配器；gemini-cli 未装如实登记） | 第一轮「三家真 CLI 握手 live 未启用」差距消解：由预设+探测升级为真机握手 PASS，且 live 首跑抓出并根修线上类型互操作缺陷（本仓发字符串 "1" 被真 CLI 以 -32602 拒绝）；剩余差距=T3 十一家原生适配+ACP registry 任意 agent 的接入广度 |
| C5 provider 切换与接续 | 8.0 → **8.5** | 9.5 → 9.5 | 本仓 `neurova/agent/swarm.py:2046`（resumeFinishedRun 重写）、`:2078-2112`（租户红线先于终态判定、跨租户与「未找到」同形拒绝）、`:2093`（resume_cross_tenant_admin 审计事件）、`:2118-2146`（spawn 时刻执行体快照 vs 名册现值→五结果决策）、`:2192`（按决策分流复用/重开会话）、`swarm_support.py:383-385`（executor_caps_snapshot/executor_tool/executor_model 快照三字段）；`tests/unit/agent/test_provider_switch_tenant.py:250-257`（create_with_handoff 可达用例） | 第一轮「切换路径不可达」差距消解：非 admin 中途切换放开，五结果决策（reuse/switch_model_in_session/restart_and_resume/create_with_handoff/reject）全可达（18 例测试），租户隔离红线+admin 豁免审计落地；剩余差距=三家预设能力档 `handoff_inject` 仍保守缺省 False（`catalog.py:71-80` _CONSERVATIVE_CAPABILITIES），真跨家 handoff 须显式声明，T3 物化交割+活窗口动态预算仍深 |
| E3 性能与资源治理 | 8.0 → **8.5** | 9.0 → 9.0 | 本仓 `NeurUI/src/pages/__tests__/AgentListPage.listRenderGate.test.ts`、`KnowledgePage.listRenderGate.test.ts`、`LogPage.listRenderGate.test.ts`（三处关键列表渲染回归门，变异法红→绿实证）、`NeurUI/src/composables/useRenderWindow.ts`（渲染窗口化单源）；`NeurUI/src/components/chat/ChatSessionSidebar.vue`、`SubAgentPanel.vue`（首轮登记的两处无界渲染列表收口+配套回归门） | 第一轮「本方无性能回归门」差距消解：前端关键列表渲染回归门落地（大列表分页/截断有界性钉死），登记的两处无界渲染同批收口；剩余差距=T3 性能审计面更广（steady shells、内存限额自停等） |

### 维持项（17 项，逐项说明）

| 子项 | 维持分（本仓/T3） | 维持原因 |
|---|---|---|
| A1 生命周期状态机 | 9.0 / 9.5 | 深化（d6e519460）补上首轮「分级就绪但门未消费」断点：依赖门真消费终态质量（`swarm.py:1618` _depSatisfied、`:1629` requiresReviewConfirmation——weak/none 终态不再自动放行下游）并根修依赖全满足时 blockedId 未赋值崩溃（`swarm.py:712-714`）——属巩固 9.0 的消费闭环；T3 的 attempt 代际+执行图节点状态差距未变，不调分 |
| A2 事件溯源与审计 | 8.5 / 9.5 | 单写路径事件溯源/全量投影重建未动（事件库仍为 JSONL 账本的 fail-open 双写镜像） |
| A3 幂等与恢复 | 8.5 / 9.5 | effect outbox（租约认领/退避/崩溃对账）仍未立项 |
| A4 并发治理 | 8.0 / 7.0 | 双方均无新工作；本方 turn 准入治理继续反超 +1.0 |
| A5 结算与收敛 | 8.0 / 9.0 | 仍仅 idle sweep 且默认关；T3 为 PR merge 事件流等四驱动且常开 |
| B1 子代理建模 | 9.0 / 9.5 | 投递账本销账闭环首轮已计入；T3 执行图节点树+确定性派生 id 的建模深度差距未动 |
| B2 上下文传递 | 8.0 / 9.5 | D-A 仅提高预算常量（`context_transfer.py:23` DEFAULT_TOKEN_CAP=32000），属参数变化非机制变化；fork/provider 切换/spawn/result 多触发点接线未动、预算仍非活窗口动态 |
| B3 checkpoint 回滚 | 8.5 / 9.5 | provider 会话协同回退仍依赖能力声明保守缺省（False），未真执行 |
| B4 依赖与队列 | 8.5 / 8.5 | 深化补管理面 REST（`neurova/api/endpoints/swarm_queue_api.py:44-71`，GET/PATCH/DELETE/POST+admin 门）与 queue_position 状态投影（`swarm.py:1120`），管理面出口补齐后与 T3 维持拉平；T3 promote-to-steer 细分仍由本方 edit 三态覆盖，不构成反超 |
| C2 能力声明与降级 | 9.0 / 9.5 | T3 12 维按域嵌套分组结构差距未动（本方为扁平布尔维单源） |
| C3 进程治理 | 9.0 / 9.5 | cgroup lease+POSIX 所有权台账差距未动 |
| C4 认证与凭据 | 8.5 / 9.0 | T3 auth 全生命周期控制器+实例间 binding 隔离差距未动 |
| D1 审批链 | 9.0 / 9.0 | 前端审批 memory_grant 徽标（`NeurUI/src/utils/approvalGrant.ts`、`NeurUI/src/api/modules/audit.ts:73-75`）为既有记忆式批准补消费读面，机制面已拉平 |
| D2 权限天花板 | 8.5 / 9.5 | D-B 将租户隔离红线延伸至切换/续跑路径，但 T3 另有的跨环境请求头与 MCP 子任务两层收窄未动 |
| D3 多端与远程 | 8.5 / 9.5 | harmony WS 稳态化落地（`Mobile/harmony/entry/src/main/ets/libs/adapters/WebSocketAdapter.ets:44-46` 退避单源、`:390/:492` sync_snapshot_required 快照通告处理；`ChatPage.ets:130` 起列表稳态记账）——客户端稳态补齐；T3 三路由热切换+learned routes+DPoP 云中继的完整远程面差距未动 |
| E1 评测体系 | 8.5 / 8.5 | cost_note 端点透传（`neurova/api/endpoints/benchmark.py:42/119/134-135/198/230/238`）补齐成本标注消费链，前端评测成本列可读——与 T3 evals 纪律维持拉平 |
| E2 契约与兼容 | 8.0 / 9.5 | 契约单源包（服务端+三端共同消费、双向兼容纪律）未动；本方仍为守卫测试+变更登记 |

### 总分对照

| | Neurova | T3 Code（reference_ac） |
|---|---|---|
| A 编排模型 | 42.0 / 50 | 44.5 / 50 |
| B 执行图与上下文 | 34.0 / 40 | 37.0 / 40 |
| C 外部 agent 接入 | 42.5 → **43.5** / 50 | 47.0 / 50 |
| D 协作与人在环 | 26.0 / 30 | 28.0 / 30 |
| E 工程方法 | 24.5 → **25.0** / 30 | 27.0 / 30 |
| **合计（百分制）** | **84.5 → 85.25** | **91.8**（精确 91.75，维持） |

### 仍未达标子项（16 项，按差距排序）

| 子项 | 差距 | 剩余差距原因 |
|---|---|---|
| B2 上下文传递 | −1.5 | 接线仍以续跑单路径为主；fork/provider 切换/spawn/result 多触发点未贯通，预算非活窗口动态 |
| E2 契约与兼容 | −1.5 | 守卫测试+变更登记 vs T3 3.4 万行契约单源包被服务端+三端共同消费 |
| A2 事件溯源 | −1.0 | 事件库仍为 JSONL 账本 fail-open 双写镜像，非单写路径事件溯源，无全量投影重建 |
| A3 幂等与恢复 | −1.0 | effect outbox（租约/退避/崩溃对账）未立项 |
| A5 结算与收敛 | −1.0 | 仅 idle sweep 且默认关；T3 四驱动（含 PR merge 事件流）常开 |
| B3 checkpoint 回滚 | −1.0 | provider 会话协同回退依赖能力声明（保守缺省 False），未真执行 |
| C1 协议覆盖 | −1.0 | 三家真握手已 PASS，但 T3 十一家原生适配+ACP registry 任意 agent 的广度仍领先 |
| C5 切换与接续 | −1.0 | 五结果决策全可达，但预设 handoff_inject 保守缺省、真跨家活体交割未开；T3 动态预算+物化交割更深 |
| D2 权限天花板 | −1.0 | 跨环境请求头与 MCP 子任务两层收窄未覆盖 |
| D3 多端与远程 | −1.0 | 三路由热切换+learned routes+DPoP 云中继的完整远程产品面未覆盖 |
| A1 状态机 | −0.5 | attempt 代际+执行图节点状态未建 |
| B1 子代理建模 | −0.5 | 执行图节点树+确定性派生 id 建模未建 |
| C2 能力声明 | −0.5 | T3 12 维按域嵌套分组 vs 本方扁平布尔维 |
| C3 进程治理 | −0.5 | cgroup lease+所有权台账未建 |
| C4 认证与凭据 | −0.5 | auth 生命周期控制器+binding 隔离未建 |
| E3 性能治理 | −0.5 | 列表渲染回归门已建；T3 审计面更广（steady shells/内存限额自停） |

### 达成判定

- **未全面达标（部分达成，差距继续收窄）**。16 项落后（净尾差 13.0，折百分制 6.5 分）、
  3 项拉平（B4/D1/E1）、1 项反超保持（A4，+1.0）。
- 总分：Neurova **84.5 → 85.25**，T3 **91.8**（当期主干较首轮前进一笔 perf 提交，能力面无
  变化），净差由 7.3 收窄至 **6.5**。
- 本轮实质消解第一轮指出的三个差距：C1 三家真机握手 live PASS（并根修 protocolVersion
  线上类型互操作缺陷——live 验证直接抓出真缺陷的实例）、C5 非 admin 切换放开+五结果决策
  全可达+租户隔离红线、E3 前端列表渲染回归门+两处无界渲染收口。
- 剩余差距仍集中在两类：**接线广度**（B2 多触发点、C1 十一家原生+registry、C5 预设
  handoff_inject 保守缺省）与**体系深度**（A2 单写事件溯源、A3 effect outbox、E2 契约单源、
  C3 cgroup、C4 auth binding、B3 协同回退、A5 多驱动、D2/D3 远程治理面）——均为可继续
  立项的明确后续，不是机制缺失。
- 复评纪律说明：本次不为追分放水——A1/B4 深化经现场核实属「巩固既有分位」而非新档位
  （结构差距未变），维持原分；D-A 预算 16k→32k 是参数变化非机制变化，B2 不调分；前端
  徽标/cost_note 透传属既有机制消费面补链，D1/E1 不调分；T3 侧漂移为 provider 版本探测
  性能优化单点，20 项维持原分。本轮调分仅 C1/C5/E3 三项各 +0.5。

---

## 复评记录三（2026-11-21，第三轮，T3 主干 2af43518）

> 复评时点：IDE 接入计划六卡实施完毕后——G1 ACP registry 零代码接入（2a12d1fcb）、
> 握手能力字段 agentCapabilities 规范名扫荡（50b980a5c）、G2 真实 transcript 回放契约
> （01f8fd72e）、G6 ACP v2 全量适配（e5642a0b3）、G4 多端连接运行时单源（453884bd4）、
> G5 权限两小项（01c809b49）、G3 适配器方法面收敛（e31417d31，另 1823b8465 cwd 回报
> 替身入库）。本仓基线为第二轮复评读数（c7ada5e6d，85.25）。
> T3 浅克隆再 fetch 确认漂移：主干自 `80871270` 前进 25 笔至
> `2af435185ea82065e2d0ca69a6765e2ba7aad001`（2026-11-20 23:35 -0800，"perf(server):
> branch PR lookups start 9 git processes instead of 14 (#40153)"），313 files
> +21309/−2020；构成以 web/mobile/server 缺陷修复为主，另有一笔 projects 多仓特性
> （60863edc）与两笔 perf——orchestration-v2 / provider-core / provider-acp 仅被修复类
> 提交触及（provider 运行时退出通知线程、antigravity/claude/opencode 修复、PR watch
> 诊断文案），无新增能力维度、适配器包或编排原语，20 子项能力面无实质漂移——T3 逐项
> 维持原分。评分口径沿用原卡（每子项 0-10、五大类同权重）；本仓证据全部按当前树
> （1823b8465）现场读数。

### 调分项（3 项，原分 → 新分）

| 子项 | Neurova | T3 Code | 关键证据（本次现场读数） | 变化原因 |
|---|---|---|---|---|
| C1 协议覆盖 | 8.5 → **9.0** | 9.5 → 9.5 | 本仓 `neurova/agent/neuacp/registry.py:31`（官方 registry CDN 源）/:34（15s 超时）/:37（5MiB 载荷上限）+ `catalog.py:195` mergedCatalog（预设>registry 合并视图，defaultCommand/capabilitiesFor/refuseExecutorSpec/probeTool/listCatalog/probeToolHealth 全读取口改走）/:223 protocolVersionFor、`external_agents_api.py:124/:263-275`（/test 按条目声明版本协商，admin 刷新默认关+非 admin 403）；`codec_v2.py:27/:107/:155/:177/:211`（v2 编解码：initialize 必填 info/prompt 内容块数组/cancel 按 requestId/update 流 24 分支映射）+ `acp_client.py:210-248`（整数版本协商选 codec，v1 字面量逐字保持）；`replay_fixtures/` 10 份真机 transcript + `test_replay_contract.py:145`（30 变异注入全红）；真拉官方 registry 46 agents 归一入册，catalog 8→52 条。T3 `provider-*` 10 包+provider-acp-registry+effect-acp v1/v2 双代协商 | 第二轮点名的两项 T3 C1 优势面本轮补齐：registry 任意 ACP agent 零代码入册（新增规范内 agent 不改代码即被发现/派活）、ACP v1/v2 双代协商（v2 全量编解码+v1 逐字节保持）；剩余差距=T3 十一家**原生专有协议**适配（Cursor/Grok/Antigravity 等非 ACP agent）与 update 流背压队列等工程深度，本方仍以 ACP 单协议栈+registry 覆盖 |
| D3 多端与远程 | 8.5 → **9.0** | 9.5 → 9.5 | 本仓 `neurova/api/connection_runtime.py:58`（HEARTBEAT_INTERVAL_S=15 单源）/:61（REPLAY_WINDOW_S=86400，与 A2 事件库 1 天保留窗同口径）/:72（SUBSCRIPTION_SCOPES=session·thread·global）/:130 parseSubscriptionScope/:151 inScope（解析失败帧 fail-closed 扣下，宁可少发不越权）/:178 describeForClients 三端契约下发；`realtime_push.py:33/:122-123`（心跳改从单源取，缺省值与改前一致零行为差异）；`mobile_ws_ledger.py:259/:272/:277/:282-303`（订阅登记/查询/注销+replaySince 按 scope 过滤，pairing 归属校验恒在）；32 例新测试。T3 `docs/internals/connection-runtime.md`（shell/thread 订阅分层）+`remote.md`/`t3-connect.md`（三路由+DPoP） | 第二轮点名的「心跳/重放窗口/订阅范围语义分散、无按需订阅」差距消解：三端连接语义收口单源（心跳/重放窗口/退避常量同源可覆盖），按需订阅（"看一个线程不付全部线程的账"）服务端语义在账本层落地（scope 解析+归属判定+按需过滤，只收紧不放宽）；剩余差距=T3 三路由热切换+learned routes+DPoP 云中继的完整远程产品面，另本方 scope 的端点级接线（mobile_pairing sync_resume 传 scope、neurflow_api 心跳显式传参收口）已登记为后续卡 |
| E2 契约与兼容 | 8.0 → **8.5** | 9.5 → 9.5 | 本仓 `scripts/neuacp_record_fixture.py`（常驻录制：真 CLI 子进程按共享场景脚本驱动，帧经真 frame_log 脱敏落盘）+ `tests/unit/agent/neuacp/replay_harness.py`（真 NeuacpClient 管线回放，ScriptedTransport 以 flush 时点供帧保因果序）+ `replay_fixtures/` 10 份真机 fixture（opencode 4/claude-code 3/codex 3 场景；gemini-cli 未装如实缺失）+ `test_replay_contract.py`（51 用例=10 契约回放+30 变异注入全红防恒真+10 脱敏卫生+1 覆盖登记）+ `replay_fixtures/README.md` 9 条协议陷阱清单。T3 contracts 单源包+回放兼容纪律 | 「真实进程录制 transcript → 经真编排管线回放断言」的回放兼容纪律落地（此前协议细节回归只靠活体抽查）——T3 E2 优势三成分（单源包/wire 双向兼容/回放兼容纪律）中的回放纪律分量补齐，且以变异注入防「回放器恒真」；剩余差距=契约单源包（服务端+三端共同消费、双向兼容纪律成体系）仍未动，本方 API 契约面仍为守卫测试+变更登记 |

### 维持项（17 项，逐项说明）

| 子项 | 维持分（本仓/T3） | 维持原因 |
|---|---|---|
| A1 生命周期状态机 | 9.0 / 9.5 | 无新工作；T3 的 attempt 代际+执行图节点状态差距未动 |
| A2 事件溯源与审计 | 8.5 / 9.5 | 单写路径事件溯源/全量投影重建未动（事件库仍为 JSONL 账本的 fail-open 双写镜像） |
| A3 幂等与恢复 | 8.5 / 9.5 | effect outbox（租约认领/退避/崩溃对账）仍未立项 |
| A4 并发治理 | 8.0 / 7.0 | 双方均无新工作；本方 turn 准入治理继续反超 +1.0 |
| A5 结算与收敛 | 8.0 / 9.0 | 仍仅 idle sweep 且默认关；T3 为 PR merge 事件流等四驱动且常开 |
| B1 子代理建模 | 9.0 / 9.5 | 无新工作；T3 执行图节点树+确定性派生 id 的建模深度差距未动 |
| B2 上下文传递 | 8.0 / 9.5 | G3 将 steer 注入与交接工件改经收敛面（`swarm.py:2033`/`:2183`）属**既有接线换道**（steer 队列与 `_buildResumeHandoff` 机制、跨 executor `handoff_inject` 判定口径均未变），非新触发点；预算仍静态 32k（`context_transfer.py:23` DEFAULT_TOKEN_CAP=32000）；fork/provider 切换/spawn/result 多触发点未贯通、预算非活窗口动态 |
| B3 checkpoint 回滚 | 8.5 / 9.5 | G3 rollback 方法（`adapter_surface.py:184`）闸于 `conversation_rollback` 维度且映射 K1 恢复面（member 会话检查点恢复），非 provider 会话协同回退；预设该维度仍保守 False（`catalog.py` _P1_ACP_CAPABILITIES），协同回退未活 |
| B4 依赖与队列 | 8.5 / 8.5 | 无新工作，维持拉平（T3 promote-to-steer 细分仍由本方 edit 三态覆盖） |
| C2 能力声明与降级 | 9.0 / 9.5 | G3 方法级能力面落地（`adapter_surface.py:69` requireCapability 单点——dim 不在 BOOLEAN_CAPABILITY_DIMS 单源即 ValueError 防拼错、caps None 放行/其余 fail-closed；`:107` forRun 名册读不到回落 spawn 快照档，外部成员不被静默放权；`:129` steer 无闸防既有插话路径被保守档闸死）——能力驱动降级机制加强；但 rollback/fork/switchModel/snapshot 四方法尚无编排侧调用方（本卡遗留登记），编排层能力分支未全量收敛，且声明结构仍为扁平布尔维 vs T3 12 维按域嵌套——按「接线广度未达不给下一档」口径维持 9.0 |
| C3 进程治理 | 9.0 / 9.5 | G5 为路径守卫（文件访问安全域），cgroup lease+POSIX 所有权台账差距未动 |
| C4 认证与凭据 | 8.5 / 9.0 | G6 对 v2 authMethods 做诚实透传（需要 auth 而未实现→显式 not_supported），属协议面边际补齐；T3 auth 全生命周期控制器+实例间 binding 隔离差距未动 |
| C5 provider 切换与接续 | 8.5 / 9.5 | 预设 `handoff_inject` 仍保守缺省 False（`catalog.py:80` _CONSERVATIVE_CAPABILITIES、`:386` _handoffCapable）；G3 handoffArtifact 沿用同一判定（跨 executor 双方声明才放行），真跨家活体交割未开；T3 活体交割+活窗口动态预算仍领先 |
| D1 审批链 | 9.0 / 9.0 | 无新工作，维持拉平 |
| D2 权限天花板 | 8.5 / 9.5 | G5 的「只暴露原生支持模式」经提交自证系既有 refuseExecutorSpec 矩阵钉子已覆盖（确认性钉子，未新增机制）；path_guard（`neurova/security/path_guard.py` symlink 感知逐级 realpath fail-closed+外部代理 cwd 规约）属文件访问安全强化，非档位天花板；T3 另有的跨环境 `T3-Mode-Limit` 请求头与 MCP 子任务两层收窄未动 |
| E1 评测体系 | 8.5 / 8.5 | 无新工作，维持拉平 |
| E3 性能治理 | 8.5 / 9.0 | 无新工作（G4 的心跳/重放窗口属连接语义单源，计入 D3）；前端列表渲染回归门已建，T3 审计面更广（steady shells/内存限额自停） |

### 总分对照

| | Neurova | T3 Code（reference_ac） |
|---|---|---|
| A 编排模型 | 42.0 / 50 | 44.5 / 50 |
| B 执行图与上下文 | 34.0 / 40 | 37.0 / 40 |
| C 外部 agent 接入 | 43.5 → **44.0** / 50 | 47.0 / 50 |
| D 协作与人在环 | 26.0 → **26.5** / 30 | 28.0 / 30 |
| E 工程方法 | 25.0 → **25.5** / 30 | 27.0 / 30 |
| **合计（百分制）** | **85.25 → 86.0** | **91.8**（当期主干前进 25 笔，能力面无变化，维持） |

### 仍未达标子项（16 项，按差距排序）

| 子项 | 差距 | 剩余差距原因 |
|---|---|---|
| B2 上下文传递 | −1.5 | 接线仍以续跑单路径为主；fork/provider 切换/spawn/result 多触发点未贯通，预算静态非活窗口动态 |
| A2 事件溯源 | −1.0 | 事件库仍为 JSONL 账本 fail-open 双写镜像，非单写路径事件溯源，无全量投影重建 |
| A3 幂等与恢复 | −1.0 | effect outbox（租约/退避/崩溃对账）未立项 |
| A5 结算与收敛 | −1.0 | 仅 idle sweep 且默认关；T3 四驱动（含 PR merge 事件流）常开 |
| B3 checkpoint 回滚 | −1.0 | provider 会话协同回退依赖能力声明（保守缺省 False），未真执行 |
| C5 切换与接续 | −1.0 | 预设 handoff_inject 保守缺省，真跨家活体交割未开；T3 动态预算+物化交割更深 |
| D2 权限天花板 | −1.0 | 跨环境请求头与 MCP 子任务两层收窄未覆盖 |
| E2 契约与兼容 | −1.0 | 回放兼容纪律已补齐；契约单源包（服务端+三端共同消费）仍未建 |
| A1 状态机 | −0.5 | attempt 代际+执行图节点状态未建 |
| B1 子代理建模 | −0.5 | 执行图节点树+确定性派生 id 建模未建 |
| C1 协议覆盖 | −0.5 | registry+v1/v2 双代已补齐；T3 十一家原生专有协议适配（非 ACP agent）的广度仍领先 |
| C2 能力声明 | −0.5 | 方法面四方法待编排接线；扁平布尔维 vs T3 12 维按域嵌套分组 |
| C3 进程治理 | −0.5 | cgroup lease+所有权台账未建 |
| C4 认证与凭据 | −0.5 | auth 生命周期控制器+binding 隔离未建 |
| D3 多端与远程 | −0.5 | 连接语义单源+按需订阅已落地（scope 端点接线待续）；T3 三路由热切换+DPoP 云中继的完整远程面未覆盖 |
| E3 性能治理 | −0.5 | 列表渲染回归门已建；T3 审计面更广（steady shells/内存限额自停） |

### 达成判定

- **未全面达标（部分达成，差距继续收窄）**。16 项落后（净尾差 11.5，折百分制 5.8 分）、
  3 项拉平（B4/D1/E1）、1 项反超保持（A4，+1.0）。
- 总分：Neurova **85.25 → 86.0**，T3 **91.8**（当期主干 25 笔提交以修复/特性/perf 为主，
  20 子项能力面无变化），净差由 6.5 收窄至 **5.8**。
- 本轮实质消解 IDE 接入专项点名的三项差距：C1 的「ACP registry 任意 agent 零代码接入」
  与「v1/v2 双代协商」、D3 的「心跳/重放窗口/订阅范围单源+按需订阅语义」、E2 的「真实
  transcript 回放兼容纪律」；G3/G5 落地了适配器方法面与路径安全，但按接线广度口径分别
  计入 C2/B3 维持与 D2 确认，不调分。
- 剩余差距仍集中在两类：**接线广度**（B2 多触发点、C5 预设 handoff_inject 保守缺省、
  C2 四方法编排侧调用方、D3 scope 端点级接线）与**体系深度**（A2 单写事件溯源、
  A3 effect outbox、E2 契约单源包、C1 原生专有协议适配、C3 cgroup、C4 auth binding、
  B3 协同回退、A5 多驱动、D2/D3 远程路由面）——均为可继续立项的明确后续，不是机制缺失。
- 复评纪律说明：本次不为追分放水——C2 方法面四方法尚无编排侧调用方，按「接线广度未达
  不给下一档」口径维持 9.0；B2 收敛面换道非新触发点不调分；D2 原生模式纪律经提交自证
  系既有覆盖确认不调分；T3 侧 25 笔漂移逐项核对无能力面变化，各项维持原分。
  本轮调分仅 C1/D3/E2 三项各 +0.5。
