# 参照系 O（botiverse/oar，Open Agent Runtime）与本仓 neuacp 接入方式对比

> 调研日期：2026-11-20。对象：github.com/botiverse/oar @ main（1,219 commits / 663 stars / Apache-2.0，TypeScript pnpm monorepo，ESM-only、Node 24+）。
> 对照面：本仓刚落地的 ACP 外部编码代理接入（`neurova/agent/neuacp/`，P0+P1+P2，见
> `docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md`）。
> 定位说明：OAR 是**面向工作台开发者的接入层库**（provider-independent programming
> interface for coding-agent runtimes）；本仓 neuacp 是**平台运行时内的治理型接入模块**。
> 两者同题（多编码 agent 统一接入）异构（库 vs 服务端治理），对比按此口径校准。

---

## 1. OAR 机制画像

### 1.1 接入方式：自研 record-stream，不用 ACP

- README 未提及 ACP，不声称兼容。其 `docs/prior-arts/feature-comparison.md` 调研了
  Paseo/Lody/Synara/One Works/Orca/Herdr/Multica 七个宿主项目——**ACP 在这些项目里
  只是"共享协议层"**（Paseo "direct SDK/app-server 与共享 ACP"、Lody "Launch → 共享
  ACP Client"、Multica "ACP 默认选择允许选项"），未被当作独立对照行，Zed 全文未提及。
- 核心规范 `docs/spec/record-stream.md`：**单一全序记录流**，三种记录
  `frame`（runtime 原话，append-only，"oar never synthesizes a frame"）/ `request`
  （动作）/ `response`（仅观测 runtime 自己不会说出的结果，如进程退出码；
  "Backfilling a guessed response is forbidden"）。每条记录带
  `seq`（"total order per stream"）与 `agentPath`（子代理谱系，`[]`=root）。
- 归一分两层：`records()` 保留原始记录（`body.native` 保存 wire 原文，凭据
  `[redacted]`）；`events()` 是纯投影（`text_delta`/`tool_call_started`/`turn_ended`/
  `usage` 等），"Lossy by design, never lossy in the stream"。
- 控制与事实**同流**："Control never prunes facts"——abort/steer/withdraw 与
  tool_result 在同一 seq 空间，先后可判定；关联靠显式 id（`responseTo`），
  "Correlation never comes from timing or order"。

### 1.2 能力声明：不支持即提前拒绝

"What differs by runtime is declared on the Runtime, not guessed"（runtime-matrix）；
"An option a runtime cannot honor is refused before anything opens, never silently
dropped."

### 1.3 覆盖面与会话外 API

- 14 个 runtime：Antigravity、Claude Code、CodeBuddy、Codex、Cursor、DeepSeek
  Harness、Devin、Factory Droid、Grok Build、Kimi Code、OpenCode、Pi、Qoder、Qwen Code
  （"One API drives every runtime"）。
- 会话内：事件流、prompt/steer/queue/withdraw/abort（均返回 accepted/rejected 与
  类型化错误码）、`serveMcpTools`（宿主工具以 MCP 挂给 runtime）、子 agent 调度、
  `observe`（UI 折叠视图）、`testing`（无二进制测试运行时）。
- 会话外：安装检测/安装/更新、登录与账号状态、用量与配额、可用模型、skills/
  commands/MCP 清单、可渲染设置表单、一次性 Orientation。
- 部署：本地为主；跨进程恢复（`resume: session.id`，"even from another process"）；
  浏览器形态（Pi Durable）；生态 Raft 提供托管算力。安全边界："OAR never handles
  the tokens"。

## 2. 与本仓 neuacp 逐维对比

| 维度 | OAR | 本仓 neuacp | 优方 |
|------|-----|-------------|------|
| 接入协议 | 自研 record-stream（归一层） | ACP v1 标准（JSON-RPC over stdio）+ 插件行协议 | **本仓**（标准生态互认：Zed/JetBrains/VS Code 同协议；"被编辑器当 agent"唯一路） |
| runtime 覆盖 | 14 家全经归一层，换 runtime 不改代码 | P0 落 4 家（OpenCode/Qoder/CodeBuddy 原生 + ZCode 插件），Gemini/Claude/Codex 预设钉死待启用 | **OAR**（覆盖广；归一层薄是覆盖广的原因） |
| 事件保真/审计 | 单流全序 seq；frame 原文永久留痕；绝不合成、绝不推断结果；控制与事实同流 | 多通道：emitter→WS、H-4 事件账本（JSONL）、span 轨迹、SQLite 台账；chunk 不落账本 | **OAR**（审计/回放/测试可判定"abort 是否先于 tool_result"这类时序问题） |
| 能力声明 | runtime-matrix 显式声明；不支持选项打开前拒绝 | catalog 只有 installed/origin/requires_node 探测 | **OAR** |
| 会话外管理面 | 安装/登录/用量/模型/skills/MCP 清单/设置表单/Orientation | catalog/test/status 三端点 | **OAR** |
| 多 agent 编排 | child 会话记录与归因（session_linked/agentPath）；"任务分配、mailbox、worktree 归宿主；可观察 child ≠ 拥有控制权" | TaskUnit 任务书、验收门、评审相位、审批链 L0/L1/L2、房间人在环、依赖门控、结果候选 CAS 合入 | **本仓**（OAR 是记录/归因层，无验收/治理） |
| 治理与多租户 | 无（开发库；"OAR never handles the tokens"） | JWT 租户（部门根）全链隔离、审批链、数据围栏、台账 owner 栅栏、admin 管理面 | **本仓**（OAR 无此维度） |
| 恢复/续跑 | 跨进程 resume 同一会话 | `--resume` 透传 + member 会话落盘 | **OAR**（跨进程语义更完整） |
| 测试证据 | testing 包（replay/live 分层、无二进制）；对自身覆盖被 prior-arts 自我设限 | 假 CLI 桩（真 stdio 子进程）+ live-verify 真后端 | 平手（各有侧重） |
| 生态位/形态 | npm 库 + CLI + 浏览器 observe + Raft 托管；嵌入宿主应用 | 平台服务端内嵌模块 + HTTP 管理面 | 各自贴合自身场景（不计分） |

**评分卡（接入层专项十分制）**：OAR 76 / 本仓 neuacp 73。
OAR 强在接入层本职（覆盖 10、事件保真 10、能力声明 9、会话外面 9、恢复 8、
测试证据 9——v2 代码级走读后由 7 上调，见 §6.8/§6.11）；
本仓强在治理与编排（多 agent 9、租户治理 9、协议标准化 9），弱在事件保真（7）、
能力声明（5）、覆盖面（7）。

## 3. 优劣结论

1. **同题异构**：OAR 用"自研归一层 + 事件流契约"把 14 个 runtime 压成一套可编程
   接口，卖点是一次接入全覆盖与审计级事件保真；本仓 neuacp 用"ACP 标准协议 +
   平台治理"把外部代理编入受治理的 swarm 团队，卖点是标准生态互认与全链治理。
2. **纯接入层维度 OAR 更优**（覆盖、保真、能力声明、会话外面）；**平台维度本仓
   更优**（治理、多租户、多 agent 编排、验收）。总分接近（74 vs 73），差异主要
   来自定位：库 vs 平台模块。
3. **对 OAR 的定位警示同样适用于本仓**：其 prior-arts 自我设限"provider 数量与
   统一方法名本身不足以证明增量价值"——覆盖广必须伴随可复现的跨 runtime 行为
   证据，这正是本仓 A6/A7 用真/桩 CLI 做 live-verify 的意义。

## 4. 可借鉴清单（建议 P1 级，待拍板）

1. **能力显式声明 + 打开前拒绝**：catalog 增 per-runtime capability 声明（支持
   的 transport、是否流式、权限交互形态），派活前校验，不支持的组合在 spawn 前
   结构化拒绝——对齐"refused before anything opens"。
2. **控制与事实同流全序**：外部成员的 abort/steer 与 chunk/tool 事件进同一
   全序账本（H-4 已有 seq 雏形），使"取消是否先于某 tool_result"可判定。
3. **事件保真纪律**：tool 结果只在 runtime 明确报告时落账，不从退出码/输出
   推断补造（对齐 "never infers it from output, exit codes, or timing"）；
   native 原文留痕（凭据脱敏）供审计回放。

## 5. 不照搬清单

1. **SDK 库形态**：OAR 是给工作台开发者嵌入的 npm 库；本仓是服务平台，接入层
   内嵌于后端并有治理面——形态由场景决定，不迁移。
2. **自研协议替代 ACP**：OAR 弃 ACP 自研有其库生态理由；本仓已押 ACP 标准
   （互操作 + 潜在"被编辑器当 agent"的反向接入），不改道。
3. **ESM-only / Node 24+ 的运行时要求**：与本仓 Python 服务端无关。

---

## 6. 代码级对照（v2，2026-11-20 源码走读；克隆 @ main，2884 文件）

> 以下 file:line 均相对 oar 源码根。本节把 §1–§4 的 README 级结论逐条落到代码，
> 并修正评分卡（测试证据 7→9，OAR 总分 74→76）。

### 6.1 规模与工程纪律

| 目录 | 文件 | 行数 | 职责 |
|------|------|------|------|
| packages/oar | 578 | 53,933 | 核心库：record-stream 内核、14 家 runtime 适配器、observe 投影、agents 子代理、MCP 宿主工具、testing |
| packages/cli | 17 | 1,907 | `oar` 命令（run/install/login/usage/models/mcp） |
| apps/arena·harbor·pi-durable | 17 | 2,280 | 对打擂台 / 长 soak 宿主 / durable-harness 演示 |
| tests/ | 635 | 67,508 | 测试比源码多 |
| experiments/ + sea-trial/ | 565 | 53,384 | 供应商行为取证 + 契约级 trial（`pnpm check` 一环） |

源码文件普遍钉在 ≤300 行（`contracts/records.ts` 296、`shared/acp/session.ts` 297）；
最大文件是 claude 限流驱动 `runtimes/claude/limit-reset/driver.ts`（1,040 行）。
14 家适配器规模：claude 39 文件/5,026 行、codex 35/3,929、pi 37/3,140、cursor 24/2,809、
opencode 31/2,462……codebuddy 13/590。默认注册 13 家（`src/index.ts:51-65`），
cursor 因 SDK 需宿主自装单独 `createCursorRuntime`（:47-49）。

### 6.2 record-stream 的代码实现（对照 neuacp 的 emitter/台账）

- 三记录 `frame|request|response`：`contracts/records.ts:44-65`；信封
  `RecordEnvelope`（:32-43）= sessionId/agentPath/spanId?/seq/receivedAt。
- seq 全序：内核 `shared/session-kernel.ts:121` `createSessionKernel`，`append()`
  （:152-183）单线程 `seq += 1`（:165-167）；观察者扇出同步不 await（:112-118），
  重入记录先入队保证按 seq 送达（:127-141）。`open` 钉在 seq 0/1（:199-205）。
- `native` 逐字留痕（`contracts/records.ts:84-85`），脱敏两道：结构级
  `shared/credential-redaction.ts:60-68`（grok/codebuddy 凭证字段→`[redacted]`，
  规则版本 `REDACTION_RULES:43-47` v2）+ 值级 redact 回调在 retention 与观察者
  投递**之前**执行（`session-kernel.ts:168-169`）。
- `events()` 投影：`observe/events.ts:39-80`——frame→`body.events`、toApp
  request→`app_request`、prompt request→`turn_started`、response→`exited/
  released/app_answered/control_rejected/input_withdrawn`；folds（model/usage/
  status）全是 `records()` 的 fold（`seal-session.ts:119-124`），非适配器快照。
- "never synthesizes / never infers" 的代码同构：进程退出记独立 `exited` 响应
  （`session-kernel.ts:240-242`），从不伪造 `turn_ended`；scripted runtime 也只在
  脚本自己报 `turn_ended` 时结束（`testing/scripted-runtime.ts:184-187`）。
- **对照 neuacp**：neuacp 的 update→emitter 映射（acp_executor.py）与 tool_call
  镜像（acp_member.py）只把事件送进 WS/账本，缺一条可离线重放的一手事实流；
  oar 的 records/native/cursor 重放（`session-kernel.ts:244-265`）是审计与测试
  共用的同一份事实源。

### 6.3 适配层组织（14 家如何归一）

- 每家一个目录 `runtimes/<id>/`（index/session/projection/installation/login…），
  共享机制下沉 `shared/`：stream-json 行协议（claude/qwen/qoder/factory 共用，
  `shared/stream-json/session.ts:23-300`）、ACP 驱动（kimi/grok/opencode/
  antigravity/codebuddy/devin 共用，`shared/acp/session.ts:50-88`）、进程池、中止回退。
  适配器只留厂商特有部分——内核注释（`session-kernel.ts:57-63`）："内核不管事实
  闸门，适配器只做泵与控制裁决（busy/no_active_turn）"。
- claude 路径：`claude/session.ts:12-45` → `streamJsonSession` →
  `foldStreamJsonStdout`（`shared/stream-json/projection.ts:55-165`）拆
  text_delta/reasoning/tool_call_*；`result`→`turn_ended`（:90-98，outcome 判定在
  `claude/projection.ts:66-97`）；子代理归属由 `parent_tool_use_id` 折成 `agentPath`
  （:16-22）。
- codex 路径：app-server JSON-RPC `initialize → thread/start|resume|fork`（线程 id
  即会话身份，`codex/session.ts:74-83`）→ `foldCodexNotification`（:107-128）；
  控制面 `turn/start|steer|interrupt` 带 `expectedTurnId`（:183-258）。
- **对照 neuacp**：neuacp 用"ACP 标准协议 + 两类执行体"覆盖四家；oar 用"共享
  驱动 + 纯投影"覆盖 14 家。oar 的投影是**纯函数可离线重放**（同一 profile 服务
  live 与 replay，`claude/projection.ts:178-181`），neuacp 的映射目前只活在执行期。

### 6.4 能力声明与"打开前拒绝"的代码形态

- `contracts/runtime.ts:140-239` Runtime 契约：`refusedSessionOptions`（:163）、
  `resumedSessionOptions`（:171）、`sessionCapabilities(installation)`（:192，开前可查
  steer/images/mcpTransports/stopTask/contextUsage）、`manualCompaction`（:177）。
- 静态声明表 `RefusedSessionOptions`（:28-36）open 前可被宿主读取；`session()`
  检查同一张表，声明即必拒；`UnsupportedOptionError` 带 option 名
  （`contracts/errors.ts:14-22`）。实例：claude 拒 goals/endTurnProcessesOnAbort/
  nativeMemoryDefault（`claude/options.ts:4-8`）；codex 在构建 open 参数时
  "refuses what it cannot build before anything starts"（`codex/session.ts:43-45`）。
- **对照 neuacp**：catalog 只回答"装没装/怎么起"，未回答"这个选项这家接不接受"。

### 6.5 会话生命周期与持久化

- resume：claude `options.resume ?? randomUUID()`（`claude/session.ts:17`）+
  `confirmSessionId` 防按标题误解析（:34-35）+ usage baseline 读回（:37）；codex
  `thread/resume`（线程 id 即身份）；ACP 系 `openAcpSession` 失败即 kill 并附脱敏
  stderr 尾巴（`shared/acp/session.ts:72-84`）。
- dispose/可达性：dispose 是流上记录（`session-kernel.ts:215-239`）；可达性完全
  "read off the stream"（:185-191）——出现 `exited/released/dispose` 后，后续控制
  一律内核层拒绝（`runtime_exited/session_released/disposed`），适配器无私活标志。
- 持久化：JSONL `oar-voyage/3`（`voyage.ts:15`），同步 fd 写（:58-75，"崩溃也不丢
  已写顺序"）；cursor 校验 sessionId（:252-254）；进程内 retention 只裁剪内存
  （`elided: true`），不动已落盘日志。
- **对照 neuacp**：member 会话落 `sessions/<agent_id>/`（可查/可续），但外部代理
  的一手事件流没有等价的 voyage 级留痕。

### 6.6 子代理双轨

- 流内原生子会话：`session_linked {parent, child, via:"tool_call"}`
  （`contracts/records.ts:134`）只由 runtime 自己点名的帧产生（codex collab item
  `codex/projection.ts:169-173`、dsh `subagent/catalog:195`、opencode v2 `_meta`）；
  去重进帧 events（`shared/session-links.ts:6-14`）；图累积 `observe/graph.ts:35-57`
  （"Foreign session ids establish nodes, never edges"）；folds 默认只算根会话。
- 宿主编排：`agents/crew.ts:25 createSubagents`（maxRunning=4/maxDepth=1，:27-28；
  深度经 `OAR_SUBAGENT_DEPTH` 传递，`helpers.ts:8-12`；越限返回类型化 refusal
  而非抛错，`crew.ts:154-158`）；`agents/subagent.ts:49-230` 订阅子会话 events
  （`agentPath.length>0` 跳过，:115），每轮 `turn_ended` 折成 SubagentReport
  （:66-93），进程退出也保证出报告（:103-127）。
- **对照 neuacp**：本仓 swarm 的派活治理（深度/预算/审批）比 oar 的 crew 完整；
  oar 值得借的是"子会话归因进事件流（agentPath/graph）"这一层，neuacp 的
  subagent 事件目前不带可归图的谱系字段。

### 6.7 permission 流转

- ACP 系：`session/request_permission` → `shared/acp/client-app.ts:115` handler；
  裁决 `allowPermission`（:37-43）="最宽允许"（allow_always > allow_once >
  cancelled）；进入即 `hooks.requested` 记 toApp 请求（:102），答出记 `answered`
  （:107，失败也记 :110）。
- stream-json 系：`control_request/can_use_tool` → `shared/stream-json/
  permission.ts:6-15` 记 toApp 请求；仅当 profile 提供 `permissionResponse` 才回写
  （claude 的选择是**只记录不代答**，`claude/session.ts:43` "permissions are
  recorded, not answered"）。
- 取消：runtime 撤回 → `app_request_cancelled`（`shared/stream-json/projection.ts:157-159`）。
- **对照 neuacp**：neuacp 的裁决接 bindRun 审批链（租户策略可插，业务面更强）；
  oar 的"请求/应答都成记录"值得照抄——裁决过程本身也应留在事实流里。

### 6.8 serveMcpTools 与 testing

- `mcp/serve-tools.ts:264-294`：宿主进程内起**只听 127.0.0.1** 的 HTTP MCP
  server，bearer token 随机生成（:267-271），把 `ServedMcpTools.server`
  （`{type:"http", url, headers:{Authorization}}`，:282）塞进任意 runtime 的
  `SessionOptions.mcpServers`——一个实现喂所有 runtime（:8-13）。协议子集
  initialize/ping/tools/list/tools/call（:171-191），每 initialize 独立会话（:230），
  `setTools` 换工具并广播 list_changed（:145-148）。
- testing：`scripted-runtime.ts:81-296` 无二进制/无登录/无 provider，但直接建在
  公开内核 SPI `createSessionKernel` 上（:84-93），产出与真 runtime 完全同构的
  记录流（`scripted/*` 帧，:97-99）；turn 在控制被接受后才开跑（:159-165），
  abort/exit 后脚本再多产也不记录（:139-142）。replay 不在 testing 包而在内核
  （cursor 重放 :244-265）+ 纯投影离线重算。
- **对照 neuacp**：本仓的假 CLI 桩是"黑盒协议桩"；oar 的 scripted runtime 是
  "内核级同构桩"——后者让宿主/投影/控制语义全部可在无二进制下回归，是测试
  证据 7→9 的依据。

### 6.9 acp-shared-connection（机制就绪、准入证据驱动）

`docs/spec/acp-shared-connection.md`：一个进程+一条 SDK 连接被多会话租用。池键
覆盖可执行文件/参数/全量环境/cwd/initialize 元数据（`shared/process-pool.ts:38-42`）；
按显式拥有的原生 session id 路由，未证明的 id 绝不因共享连接变成子会话；256 帧/
1MiB/1s 缓冲上界与 `pre_reservation/retired/conflict/expired/capacity` 诊断；凭证
按所有租约并集最长优先脱敏（`shared/acp/routing.ts:62-74`）。代码完整实现：
`shared/acp/routing.ts:34-289`（bind/reserve 所有权裁决，resume 撞占用抛
`SessionUnavailableError("in_use")`）、`shared/acp/shared-session.ts:57-90`、
`shared/acp/shared-wire.ts`。**但当前没有任何原生 runtime 被准入共享**（OpenCode/
Grok/Kimi 准入均关闭或拒绝）——"机制就绪、准入证据驱动"的形态，与本仓
process_pool 的"建好待接入"异曲同工。

### 6.10 代码级对照素材总表

| 维度 | oar（file:line） | neuacp | 更严格/完整方 |
|------|------------------|--------|---------------|
| 线协议 | ACP 用官方 SDK，oar 只加 deadline/exit（shared/acp/process.ts:82-133,136-209） | acp_client.py 自研泵+id 配对+fail-closed | oar 省力借 SDK；neuacp 可控自担回归 |
| 事件流 | 三记录流+native 留痕+投影+cursor 重放（records.ts:44-89、session-kernel.ts:244-265） | update→emitter+账本镜像 | oar（可回放一手事实流） |
| 能力声明 | refusedSessionOptions/sessionCapabilities 开前可查、声明即必拒（runtime.ts:28-36,163,192） | catalog 仅 installed | oar |
| 子代理 | 流内归因（agentPath/graph）+宿主编排 crew 双轨（agents/crew.ts:27-28,154-158） | swarm 派活治理完整，但事件无谱系归因 | 各有侧重（编排本仓强、归因 oar 强） |
| 权限 | 自动裁决+请求/应答全留痕+按 runtime"只记录不代答"（client-app.ts:37-43,115、claude/session.ts:43） | bindRun 审批链桥接（租户策略可插） | neuacp 贴业务；oar 的留痕做法值得照抄 |
| 进程管理 | 池按全量配置 sha256 键控+retiring 防关停中加入+退出广播（process-pool.ts:38-42,102-134） | process_pool.py 租户段键/上限排队/空闲回收 | 取舍不同（共享连接 vs 多租户吞吐） |
| 测试 | scriptedRuntime 建在内核 SPI 上、与真 runtime 同构（testing/scripted-runtime.ts:81-296） | pytest 假 CLI 桩 | oar（内核级同构桩） |
| 管理面 | serveMcpTools 把宿主工具反挂给 runtime（mcp/serve-tools.ts:264-294） | neuacp 管理面管控 runtime | 方向互补（喂能力 vs 管控） |

### 6.11 评分卡修订与借鉴清单（v2）

测试证据 7→9（内核级同构桩+统一 cursor 重放），OAR 总分 74→**76**；本仓 73。
结论不变：纯接入层 OAR 优，治理编排本仓优。

借鉴清单（v2 修订，待拍板）：
1. capability 声明+打开前拒绝（§6.4）——落 neuacp catalog/派活前校验。
2. 控制与事实同流全序 + 一手事件流留痕（§6.2）——外部成员事件可回放。
3. 事件保真纪律：结果只在 runtime 明确报告时落账、native 留痕脱敏（§6.2）。
4. **（v2 新增）scripted 桩建在内核 SPI 上**：neuacp 的假 CLI 桩升级为与真
   executor 同构的内核级桩，宿主/投影/控制语义全部无二进制可回归。
5. **（v2 新增）租户/归属归因进事件流**：子代理事件带 agentPath 式谱系，
   支撑跨会话归因与图查询。
4. **登录令牌经手面**：OAR "never handles the tokens" 的边界与本仓凭据面
   （env_keys 只录键名、值走凭据面）同向，已对齐，无需再学。
