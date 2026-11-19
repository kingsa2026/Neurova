# reference_z vs Neurova：多代理编码团队编排 harness 机制对照（2026-11-19）

> **性质**：外部参照项目机制研读与借鉴分析（研究参考，仅作背景，不可作事实源）。
> **参照项目**：代号 `reference_z`——一个开源（Apache-2.0）的「把多家终端编码 agent 编成一支持久团队」的本地编排 harness：YAML 定义团队拓扑，常驻 daemon 持久化状态，终端复用器里驾驶未改装的编码 agent，配 CLI/终端 UI/MCP server 三个入口。TypeScript 约 5.46 万 KB 源码、4986 文件，2026-04 立项，8.9k stars / 764 forks，发版极勤（研究当日仍在提交；最新 tag v0.7.19，浅克隆 @ `9d80a24`，2026-11-19）。
> **本文纪律**：全文不出现参照项目及其作者、所封装编码 agent 产品的实名；两家被封装的主流终端编码 agent 以下称 **harness-A / harness-B**，其余基础设施（tmux/SQLite/Node/MCP/ACP/A2A 等通用件）按原名指代。

---

## 1. 结论摘要

1. **形态判断**：reference_z 是「单机单用户、daemon 中心、终端驾驶」的**多代理编码团队编排 harness**——它不改装 agent，而是在 tmux 会话里启动 harness-A/B 的交互式 CLI，用 `send-keys`/`paste-buffer` 投递消息、抓取 pane 观测状态，把「一堆终端会话」变成有拓扑、有队列、有恢复、有审批路由的持久团队。与本仓库的「服务端多租户平台 + 进程内 swarm」不是同一形态，但**与 neuacp 计划（把外部编码 agent 编入团队）正面撞题**：它就是这件事最完整的公开实现。
2. **对本仓最有价值的不是它的驾驶层，而是它围绕「不可信外部 agent」做的工程包裹**：外部代理运行的**诚实结局五态**（completed/stopped/cancelled/failed/unknown）、**权限请求→审批行**的报价-应答契约、**进程清算**（环境标记继承 + settled/incomplete/unknown）、**占用者代际**防幽灵认领、**终态 closure_reason 封闭集强制**——五件事全部命中本仓 neuacp A 卡与任务台账的在途设计，可直接当对照基准。
3. **本仓领先面**：多租户强制隔离（对方完全无租户概念）、治理审批链与成本记账、知识/记忆/本体域、服务端多入口（HTTP/WS/渠道/移动端）。**对方领先面**：外部 agent 生命周期工程（resume/fork/restore 三档恢复策略 + 补偿式恢复编排）、持久任务队列的接力棒语义、投递打字防护、以及**场景化 CI**（stub 运行时 + 缺陷种子成对验收：健康跑绿 + 植入缺陷跑红才算交付）。
4. **驾驶路线差异是根本分岔**：reference_z 选交互式 TUI + 屏幕抓取 + 按键注入，为此付出了巨大的复杂度代价（进程谱系证明、就绪探测十种 attention 码、打字防护、活动 hook 桥）；本仓 neuacp 选 ACP/stdio 结构化协议，链路更干净。**对方的教训恰恰证明本仓路线选对了**；但其驾驶层兜出的 Ancillary 契约（结局诚实、清算、防护）任何路线都需要。
5. 借鉴清单：**P0×2**（外部代理结局五态契约、权限审批行报价-应答契约）+ **P1×5**（进程清算、打字防护、占用者代际、closure_reason 封闭集、场景化 e2e 种子验收）+ **P2×4**；不照搬×5（§6）。

---

## 2. 参照项目画像

### 2.1 定位与总体架构

```
 rig CLI（93 命令）      终端 TUI（可寻址屏幕 socket）      MCP server（39 工具，stdio/HTTP）
        \                     |                          /
         +---------- daemon 本地 HTTP（默认端口 7433）------+
                            |
         packages/daemon：Hono 路由(77 文件) → domain 服务/仓储/编排器 → 事件总线
              |                    |                        |
        SQLite(WAL,177 迁移)   tmux 适配器            6 个 RuntimeAdapter
        （rigs/nodes/edges/     （会话=pane，           harness-A / harness-B /
         sessions/queue/        load-buffer+           pi 系×2 / terminal / stub
         events/transitions）   paste-buffer）                |
                                                              ▼
                                            未改装的编码 agent 交互式进程（团队座位）
```

关键特征：

- **agent 不被改装**：编码 agent 仍是自己habitat 里的交互式会话；编排层只做「发射（launch）—投递（deliver）—观测（observe）—恢复（restore）」。
- **一切状态落 SQLite**：rig/座位/绑定/队列/事件/转换全部持久化，daemon 重启后可恢复整支团队（`queue-baton-survives-restart` 是其旗舰场景）。
- **三个消费入口共享同一 HTTP 面**：CLI 给人、TUI 给沉浸操作、MCP server 给外部 agent（含团队自己的座位 agent）。
- **分发形态**：npm 单包 `@openrig/cli`（daemon/TUI/UI 构建产物全部打进包里），要求 Node 22/24 + tmux，macOS/Linux/WSL2。

### 2.2 关键数字（浅克隆 @ 9d80a24 实测）

| 维度 | 读数 |
|---|---|
| CLI 顶层命令 | 93 |
| daemon 路由文件 / 挂载点 | 77 个文件 / 69 `app.route`（0.6.6 读数） |
| SQLite 迁移 | 177 个 |
| MCP 工具 | 39（0.6.6 时 18，半年翻倍） |
| 内置技能 | 36（core 18 / pm 7 / pods 4 / process 7）+ 1 个人侧入口技能 |
| 运行时适配器 | 6（harness-A、harness-B、pi、omp、terminal、stub） |
| context packs | 5 个静态包 |
| 测试场景 YAML | 28 个（含 7 个 stub 拓扑） |

### 2.3 工程纪律亮点（值得单独看）

- **文档守护**：`docs/` 下只允许四个白名单子目录入库，其余 gitignore；`docs/reference/` 随 npm 包分发给用户与 agent。
- **技能三副本镜像**：技能有唯一「可编辑之家」，另两份生成副本靠哈希清单守卫（`mirror-skills:check` 进 `npm test`），防漂移。
- **内部泄漏扫描**：上下文包、公开技能、打包产物三层扫内部术语/路径，发布门强制。
- **可移植性报告**：每个 PR 自动列出新增行里的机器特定值（凭据/家目录/网络地址/邮箱），只报告不拦截，人来裁量。
- **面向 agent 的 CHANGELOG**：升级说明写到「先停 daemon、备份数据库、确认 clean stop 才继续」的步骤级，明确「降级未经验证」。

---

## 3. 核心机制研读

### 3.1 团队拓扑：rig spec（YAML）

顶层字段（`packages/daemon/src/domain/rigspec-schema.ts:69-79`）：`version/name/summary/culture_file/permission_policy/managed_blocks/docs/startup/services/workspace/pods/edges/non_interruptive/env`。Pod 下是成员（座位）：`id/agent_ref/profile/runtime/model/effort/role/permission_policy/restore_policy/cwd/env/...`；边五类：`delegates_to / spawned_by / can_observe / collaborates_with / escalates_to`。`restore_policy` 三档：`resume_if_possible | relaunch_fresh | checkpoint_only`。未知键直接拒收。运行时白名单 = 六内置 + 社区 harness preset（`rigspec-preflight.ts:169`），preflight 还会跑 `--version` 探针确认本机装了对应 CLI。

最小示例（`demo/rig.yaml` 节选）：

```yaml
version: "0.2"
name: demo-rig
pods:
  - id: orch
    members: [{ id: lead, runtime: harness-A, cwd: . }]
  - id: dev
    members: [{ id: impl, runtime: harness-A, cwd: . },
              { id: qa,   runtime: harness-B, cwd: . }]
edges:
  - { kind: delegates_to, from: orch.lead, to: dev.impl }
```

### 3.2 座位生命周期与恢复（对方最深的护城河）

- **状态机**：会话 `running/idle/unknown/exited/detached/superseded`（`session-registry.ts:143`）；启动态 `pending/ready/attention_required/failed`；节点级 `running/detached/recoverable/attention_required`，rig 级折叠出 `degraded` 混合态（`ps-projection.ts:93`）。
- **启动编排五段**（`startup-orchestrator.ts:272-291`）：标 pending → 投影资源/投递 pre-launch 文件 → `adapter.launchHarness` → 等就绪 → 注入身份锚点 + after_ready 动作 + 持久化 resume token。
- **三种连续性来源**（`StartupInput:170`）：`resumeToken`（续旧会话）、`forkSource`（从父会话派生新会话，只支持原生 session id，且必须捕获新 token）、`rebuildArtifacts`（重建）。结果 `continuityOutcome: resumed|fresh|forked|rebuilt`。
- **恢复编排**（`restore-orchestrator.ts:387`）：载入快照 → 发现有活会话则拒 → per-rig 锁 → 计划 → **逐节点带补偿执行**（`restoreNodeWithCompensation:1275`），节点级结果九态（含 `awaiting-decision`、`operator_recovered` 这类「不确定就交给人」的诚实态）。
- **占用者代际**：每个座位实例有 `OccupantKind = initial|handover|adopt|fresh` 与代际 UUID；换人（handover/收养）后旧代际的队列认领按代际释放，**同名继任者不会误继承旧认领**（GHOST-STAGE 设计，`queue-repository.ts` 的 `claimed_by_generation_uuid`）。

### 3.3 驾驶外部 agent：tmux 交互式路线的代价与兜底

- **发射**：把 `claude`/`codex` 交互式命令敲进 pane（如 harness-A fresh：`--permission-mode acceptEdits|--dangerously-skip-permissions` + `--settings <json>` 一次性注入 hooks/权限/statusline；harness-B：`-s workspace-write|-s danger-full-access -a never|-p <profile>` + `--add-dir` 挂工作目录与队列状态目录）。
- **投递**：`tmux load-buffer` + `paste-buffer`（bracketed paste）+ `send-keys Enter`；启动命令走临时脚本 `sendShellCommand`。
- **观测**：`capture-pane` 40 行 + 进程谱系证明（`native-process-lineage.ts` 验证 pane 里跑的确实是刚发射的进程），就绪探测失败分类成十种 attention 码（trust gate/login required/mcp gate/auth refusal...，`runtime-adapter.ts:113-130`）。
- **活动回传**：给 harness-A 挂 SessionStart/Stop/UserPromptSubmit hook 桥、给 harness-B 往其 config.toml 写四事件 hook，把 agent 侧活动汇成 SSE 活动流。
- **代价**：为了「屏幕即接口」，它必须做打字防护（§3.5）、渲染器锁定（禁 alternate screen 保 scrollback）、statusline 节流采集、非打断模式——这一整套都是交互式路线的税。

### 3.4 持久任务队列与接力棒（baton）

- 状态机 `pending|in-progress|done|blocked|failed|denied|canceled|handed-off`（`queue-repository.ts:127`），优先级 `routine|urgent|critical`。
- **认领即接力**：`claim` 写 `claimed_at` + `claimed_by_generation_uuid` + 按 tier 算 `closure_required_at`，追加 append-only `queue_transitions`；**交接** `handoff/handoffAndComplete` 把老行闭成 `handed_off_to`、新行落到接手座位——「谁在干」永远是一条可审计的接力链。
- **热土豆强制**（`hot-potato-enforcer.ts`）：任何到 `done` 的迁移必须带合法 `closure_reason`（`handed_off_to|denied|canceled|no-follow-on|escalation|superseded`），**在 domain 层强制而非路由层**。
- **认领后活性**：不做「认领者自报回执」，而是从 `claimed_at`/转换日志/心跳**推导** `working|needs-input|stalled-after-claim|parked`（`queue-pickup.ts`）——防止「没人唤醒的持久行」与「进行中工作」不可区分。
- **唤醒**：outbox + wake ladder/backoff，nudge 失败三分类（permanent-topology/transient/unknown）。

### 3.5 消息投递与打字防护（typing guard）

- 所有投递收口 `SessionTransport`（`session-transport.ts:2377`，六层 send 管道），先 `classifyPaneActivity` 判定目标 pane 状态（在打字？在权限提问？在任务面板？），可等 idle。
- **SeatDeliveryGuard**（`seat-delivery-guard.ts:144`）：三档模式 `off/draft-aware/hold` + 四档中断级别（`openrig-urgent/urgent-only/sends-only/queue-only`）；检测到 tmux client 活动或输入框草稿时**hold 进 outbox，从不丢弃**，人离开后重试。
- 人工插话、agent 互发（座位内 `rig send`/`rig queue create`）、网关回信，全部汇入同一条投递管道。

### 3.6 技能与上下文投影

- 技能源于 `skills/_canonical/` 四类 36 个；agent spec 用 `uses.skills` 选择；投影时按运行时落位：harness-A → `.claude/skills/`，harness-B → `.agents/skills`，并登记写入哈希（`rig down` 只删自己写入的、restore 可复原，拒穿透符号链接）。
- **受管块合并**：团队指导不覆盖用户的 `CLAUDE.md`/`AGENTS.md`，而是合并「受管块」；harness-B 的指导走启动参数 developer instructions，不落文件。
- **context packs**：manifest 含 `files[]`（role: orientation|convention|boundaries|claims|verifier）与 `atoms[]`（situations: fresh|handover|post-compaction；purpose: width|depth；带 probe{prompt,expect}），`rig context get <pack>/<file>#<h2>` 按地址取段、超 48k 截断——「上下文按场景配方组装」的思路与本仓 context 注入同题。

### 3.7 权限治理

- 策略文件五档（`policies/builtin/`：`auto/locked/open/standard/yolo .policy.md`），frontmatter 声明 `default_posture/allow/ask/destructive_class`；FLOOR 翻译成各 harness 参数（harness-A `acceptEdits`、harness-B `workspace-write`），「翻译是技能的活」——策略语义与 harness 方言分离。
- daemon 鉴权：bearer token 常时比较（长度不等也与零缓冲比，防时序侧信道，`auth-bearer-token.ts:36-51`）；**非 loopback 绑定 + 空 token 拒绝启动**。
- 每 seat 还可加 Linux systemd 内存限额（`process_limits.memory_max`），且「验证不了就报不确定，不静默声称生效」。

### 3.8 人的入口：mission-control 与注意力面

- **mission-control**：手机友好的操作员读面，7 个视图（my-queue/human-gate/fleet/active-work/...）统一投影成 9 字段行（阶段/状态/下一动作/待人决策/读取成本/置信度/证据链接），配套 append-only 操作审计（7 动词：approve|deny|route|annotate|hold|drop|handoff）与 ntfy/webhook 通知。
- **attention surface**：被动投影 `AttentionItem`（kind/summary/unblocks/urgency/recipient + 应答通道），带读取 watermark 续播——让人只看「现在需要人的地方」。
- **gateway**：人的消息经 loopback HTTP relay 进出（出站 DispatchBuffer at-least-once 重放，入站强制 loopback + bearer），外部平台只留适配器；**托管成员**（无 pane 的 bot）以 `<member>@<rig>` 地址经 MCP 工具入队干活，webhook ring 唤醒，实验性默认关。

### 3.9 ACP/A2A：外部代理接入（与本仓 neuacp 直接同题）

- **双向都有**：
  - `rig acp serve`：把整支团队包装成一个 **ACP agent** 供编辑器类宿主调用——`session/prompt` 落成一条队列行投给 `--to <member@rig>`，回复 = 行的 resolution，权限提问转 ACP 权限请求。
  - `rig acp run <qitemId> -- <agent ACP 命令>`：把一条队列行的任务交给外部 ACP agent（含两家被封装 harness 的官方 ACP 适配器），**座位是行保管人，agent 被记录为执行者**。
- **权限请求→审批行**：外部 agent 的每个权限请求变成一条发给人/座位的队列行，列明动作、目标、agent 报价的选项与所属 run；**应答必须是报价选项之一的 id**，答非所问则记录并重问；turn 取消则审批行闭为 stale。reference_z 自己不持权限政策——agent 自持设置决定问不问，人决定答不答。
- **诚实结局**：行 notes 依次记录 binding（agent 名/版本/协议版本/会话）、每分钟进度、每次权限请求与应答、**结局五态** `completed/stopped/cancelled/failed/unknown`——`unknown` 明确覆盖「turn 结束但没有任何证据表明干了活」（含 end_turn 零输出零 usage、provider 拒绝、连接早断）；usage/cost 标注来源，没有就写 unknown。
- **进程清算**：run 结束报告带 RUN_MARKER 环境标记的残留进程 `settled|incomplete(带 pid)|unknown`；只清自己启动的（标记继承），agent 经 service manager 起的进程不算，也绝不碰。
- **清醒话术**：文档明说「completed turn ≠ finished work」「cancel 后 provider 是否停了、花了多少钱 unknown」「A2A 状态映射非一一对应、HTTP 200≠成功」——外部代理边界的不可控处全部用诚实态暴露而不是兜底掩盖。

### 3.10 测试体系：stub 运行时 + 缺陷种子成对验收

- 座位可用 `runtime: stub`：stub 只实现四种行为（compaction/slow_output/mid_turn_death/restore），由 per-seat 脚本触发——**零模型成本跑真 daemon+真 tmux+真 SQLite**。
- 场景 YAML 动词白名单（up/down/send/restart/restore/emit/mutate/policy/seed_regression/daemon + expect），断言只准读 shipped 观测面（ps/queue/stream/scope/pane/transcript/tui_socket），**禁止戳内部 DB**。
- **种子契约**：每个历史场景必须成对验收——真实代码上 GREEN + 植入缺陷的 seeded run 上 RED；RED 不了的场景不算交付。
- CI 在无网络、非特权容器里装 npm 包跑真场景（健康 → 植入故障必须红 → 再来一个健康容器）。

---

## 4. 与本仓库逐域对照

| 域 | reference_z | Neurova | 判读 |
|---|---|---|---|
| 团队模型 | rig → pods → seats，YAML 拓扑 + 五类边 | swarm/teams/rooms，成员=本仓 agent 记录 + 外部成员（neuacp） | 同题；对方拓扑声明式更强（边类型/restore_policy），本仓成员治理与租户更强 |
| 外部编码 agent | 6 适配器驾驶 harness-A/B/pi 系；ACP 双向 | neuacp：ACP client 派活（OpenCode/Qoder/CodeBuddy 原生 + 插件形态），executor/child_env/租户键 | **正面撞题**。对方生命周期工程（resume/fork/restore/代际）深；本仓协议路线更干净、有租户与审批 |
| 任务账本 | queue_items + queue_transitions（append-only）+ baton/代际/closure_reason 封闭集 | agent_runs 台账 + H-4 事件账本 + RUN_STATUS_TRANSITIONS 收口 | 本仓已有状态机收口与事件重放；缺「终态强制带 closure_reason」与「代际防幽灵」 |
| 审批 | 权限请求→队列行（报价-应答，一次一问）+ human-gate | ASK 挂起 + 审批链 L0/L1/L2 + 房间/项目治理回灌 | 本仓审批层级更全；对方「应答必须咬合报价选项 id、答非所问重问、取消即 stale」是可抄的咬合细节 |
| 事件 | 事件总线：事务内持久化 + 提交后按序扇出 + SSE Last-Event-ID 续播 + watermark | H-4 账本 + status_changed 入账 + replayRunTailStatus | 语义同构；对方「同事务事件提交后保序扇出、防漏发重发」的纪律值得对照 |
| 技能/上下文 | 36 技能三副本镜像 + 按运行时投影 + context packs（atoms/profiles/probe） | 技能目录 + workspace_docs + context 注入/压缩 | 本仓压缩/温度机制更深；对方「技能投影落位 + 写入登记可逆」与「上下文按场景配方」可借鉴 |
| 权限治理 | 五档策略文件 + posture 方言翻译 + 每 seat 限额 + 非 loopback 强制 token | 工具治理四级裁决 + 审批链 + 租户隔离 + JWT | 本仓治理面宽得多（多租户/成本/审计）；对方「策略语义与 harness 方言分离」「验证不了就报不确定」是好看细节 |
| 人的入口 | TUI + mission-control 九字段读面 + attention surface + gateway relay | 前端控制台 + 移动端 + 渠道 + WS 推送 | 本仓入口更全；对方「只看需要人的地方 + 读取成本/置信度字段」对 dashboards 有参考价值 |
| 成本 | 无（外部 agent usage 只如实转抄并标来源） | cost_tracking 单源 + cost_source=external | 本仓明显领先；对方「usage 标注来源、没有就 unknown」的诚实形态可借 |
| 测试 | stub 场景 28 个 + 种子成对验收 + 容器无网 CI + 文档/技能/泄漏三守护 | pytest 分层 + A/B 自证 + live-verify 真链路 + 前端 vitest/vue-tsc | 本仓 live-verify 更真；对方「seeded regression 成对验收」是 e2e 批可直接借的判据 |
| 租户 | 无（单机单用户，loopback/Tailscale 假设） | JWT 租户强制红线 + 外部代理全生命周期按租户隔离 | 本仓独有，不可被对方反向带偏 |

---

## 5. 可借鉴点（按建议优先级）

**P0——对 neuacp 在途批直接可用：**

- **Z1 外部代理运行结局五态契约**：neuacp executor 的结果上报按 `completed/stopped/cancelled/failed/unknown` 五态收敛，「turn 结束但无证据表明干了活」必须落 `unknown` 而不是 `completed`；usage/cost 标注来源、缺源标 unknown。对照本仓 `agent_runs` 终态与 S3 状态机，把「外部执行者的诚实结局」钉成契约测试。
- **Z2 权限审批行的报价-应答咬合**：外部 agent 权限请求落本仓审批行时，记录 agent 报价的选项集，**应答必须是选项 id 之一**，答非所问记录并重问，所属 run 取消则审批行闭 stale——补进 A9b 审批链租户校验之后的咬合细节。

**P1——本仓任务台账与 e2e 批：**

- **Z3 进程清算**：外部 agent run 结束做残留进程清算，环境标记（run 专属 env）继承识别 + `settled/incomplete(pid 列表)/unknown` 三态上报，只清自己启动的进程。
- **Z4 投递打字防护**：向交互式/流式外部代理投递前检测「正在输入/草稿未提交」，命中即 hold 进 outbox 重试而非丢弃——对插件形态（stdin 驾驶）与渠道并发投递都有用。
- **Z5 占用者代际**：座位/成员换人后，旧认领按代际释放，防同名继任者误继承在途任务——可加固本仓 subagent 重派与队列认领的竞态面。
- **Z6 终态 closure_reason 封闭集**：`agent_runs`/队列终态迁移强制携带封闭枚举的 closure_reason（domain 层守卫），消灭「莫名 done」。
- **Z7 场景化 e2e 种子验收**：本仓 e2e 批引入「缺陷种子成对验收」——每个场景配一个 seeded run，健康绿 + 植入红才算交付；stub 化外部代理即可零成本跑全链路。

**P2——治理与工程纪律：**

- **Z8** 事件总线「同事务持久化 + 提交后按序扇出 + 断点 Last-Event-ID/watermark 续播」对照 H-4 回放补强。
- **Z9** 运维读面学 mission-control：每行带「下一动作/待人决策/读取成本/置信度」，attention 面只列「现在需要人的地方」。
- **Z10** 仓库纪律件：文档目录白名单守护、多副本技能/文档哈希镜像、PR 机器特定值（凭据/内网地址）扫描报告。
- **Z11** 资源限额诚实上报：per-member 进程/内存限额，「验证不了就报不确定，不静默声称生效」。

---

## 6. 不照搬清单

1. **交互式 tmux 驾驶路线**：屏幕抓取 + 按键注入 + 进程谱系证明 + 十种就绪 attention 码——为「不改装 agent」付出的整架复杂度；本仓 neuacp 坚持结构化协议（ACP/stdio/插件），审计与测试面都更干净。
2. **单机单用户假设**：loopback/Tailscale、`~/.openrig` 单家目录、无租户无配额——与本仓多租户红线冲突，凡涉及接入面一律按本仓租户/鉴权收口。
3. **「编排层不持权限政策」的放任姿态**：外部 agent 自持权限设置、编排层只转交人——本仓治理必须收口（审批链 + 租户 + 审计），不能学这层「宽松」。
4. **平台栈绑定**：Node 22/24 + tmux + macOS/Linux/WSL2；Windows 原生不可用——本仓是跨平台服务端，勿把终端复用器假设带进核心设计。
5. **「completed 即完成」的乐观关行**：对方文档自己承认 completed turn 可能没干活、需要人复核后才关行；本仓应以**验收门/评审相位**自动化这个复核（P1-2 验收门已在途），而不是学它把复核全推给人。

---

## 7. 一句话总评

reference_z 是「把外部编码 agent 编成持久团队」这件事目前最完整的公开工程答案：它的驾驶层（tmux 交互式）本仓不应跟，但它围绕**不可信外部代理**修的一圈契约——诚实结局、审批咬合、进程清算、代际防幽灵、closure 强制、种子化场景验收——恰好是本仓 neuacp 与任务台账在途批次最该逐条对照的验收基准。
