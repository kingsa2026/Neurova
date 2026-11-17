# CoworkOS vs Neurova 多 Agent 协作对照评测（2026-11-17 第二轮）

> 参照系：CoworkOS（arXiv:2611.03178，RUC-NLPIR，代码 github.com/RUC-NLPIR/CoworkOS，克隆件 `~/.zcode/tmp/coworkos-src` @ baf03c3）。
> 被评方：Neurova 本仓**当前态**（P1–P3 升级批全部落地后，含 3d018e601/f05e88b3c/c8bbde9b9）。
> 上轮同框评测见 [autoswarm_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md](autoswarm_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)——维度体系与评分锚点**原样复用**，两轮分数可直接对比。

---

## 1. 摘要（结论先行）

**总分：Neurova 84/110（76.4%），CoworkOS 参照系 95/110（86.4%）**——七维廿二子项等权求和（§6 总分表）。与上轮相比，Neurova 从 70 → 84（+14，全部来自 P1–P3 升级批的机制化落地）；CoworkOS 是迄今评测过的最强参照系（AutoSwarm 84、ZCode 对照另计）。

双方形态不同：CoworkOS 是"**本机单用户长程工作 harness**"（Electron/CLI 双入口，任务策略与执行管理分离，Main/Coordinator/Subagent 三层，共享应用层人机共编，RSI 后训练闭环）；Neurova 是"**产品化的多渠道多 Agent 平台**"（蜂群派生 + ACP 团队 + 协作房间 + 工作流 + 定时任务）。

关键结论：
1. **CoworkOS 的强项在"执行可靠性工程"**：持久化协调控制平面（队列/租约/两阶段确认/崩溃恢复/机械完成闸门）与上下文压缩纪律都做到机制级+测试钉死，B/C/D/F 四维领先。
2. **Neurova 的相对优势已收窄到 E 治理安全（13 vs 12）**：治理三明治（广度/深度/预算/冷却/错峰硬闸）仍是 CoworkOS 没有的——它把并发约束完全交给 Main 自律。
3. **CoworkOS 无依赖门控（η 门）与验收门**：任务质量把关靠"Main 验收 + 候选人工审阅"，没有自动验收判定器；其完成判定是**机械闸门**（有意不判质量）。这与 AutoSwarm 形成互补参照：AutoSwarm 证明验收/评审的收益（−12.82），CoworkOS 证明"策略与执行分离 + 持久化协调"的收益。
4. **CoworkOS 的"语义记忆"实为有界结构化档案**：全量扫描 + 6000 字符预算注入，无向量/关键词检索；但其**准入纪律**（直接证据正则 + 3 个不同 Task 候选转正 + 敏感信息拦截 + 世代失效防旧覆盖新）值得借鉴。
5. 本轮最大可借鉴点（非照搬，按本仓哲学改造）：**机械完成闸门与质量验收分离**、**邮箱两阶段确认（进入持久上下文才 consume）**、**Subagent 产出候选制**。

---

## 2. 评测框架与方法

### 2.1 维度体系（与上轮完全同框）

| 维 | 名称 | 子项 |
|---|---|---|
| A | 协作形成 | A1 团队组成与角色分配；A2 任务单元结构化；A3 验收条件；A4 依赖与评审关系 |
| B | 执行协调 | B1 共享执行状态；B2 单元生命周期；B3 依赖门控与前沿并行；B4 事件驱动交互与阻塞升级；B5 结果集成 |
| C | 通信基础设施 | C1 寻址/路由/邮箱；C2 实时性（流式/中断）；C3 可靠性语义 |
| D | 记忆与上下文共享 | D1 跨 agent 上下文共享；D2 共享黑板/工作记忆；D3 历史压缩与成本 |
| E | 治理与安全 | E1 权限/审批（人在环）；E2 工具面收窄；E3 资源治理 |
| F | 可观测与评测 | F1 台账/trace/事件；F2 基准评测 harness |
| G | 异构与互操作 | G1 多模型/多 provider；G2 互操作协议 |

### 2.2 评分锚点（0–5，与上轮一致）

0=无实现；1=骨架/占位无消费方；2=部分实现仅靠自觉；3=机制化覆盖主链路有明显边界；4=机制化+测试守卫+治理完备；5=机制化+测试+治理+实证闭环。

### 2.3 方法边界（诚实声明）

- 仍是**静态代码级机制评测**，不产生任务成功率数据。CoworkOS 的 12 个 benchmark 分数是论文报告值（GLM-5.3 High thinking/256K），只作参照，不与静态分换算。
- CoworkOS 代码量约 6.8 万行 TS/JS（src/+.pi），本次经三路分区精读（runtime / workspace·storage·domain / applications·security·tools·software）+ 官方架构文档交叉核对；行号均指克隆件 baf03c3。
- Neurova 侧分数按 **2026-11-17 P3 批落地后**的现状重评；上轮分数保留在对照表中以显示升级收益。

---

## 3. 参照系 A：CoworkOS 论文机制与实证结果

### 3.1 核心命题：任务策略与执行管理分离

模型只负责决策（做什么、委派给谁、是否验收）；运行时负责维持状态、反馈与连续性。形式化：Main 决策 $a_t^M \sim \pi_M(\cdot \mid g, h_t^M, \mathcal{F}_t)$；Coordinator 维护持久程序状态 $\xi_{k+1}=F_C(\xi_k, e_{k+1})$。

### 3.2 三层架构与委派协议

- **Main Agent**：全局问责点，拥有完整工具集与按需技能；委派本质是一份 **evidence contract**——指定目标、约束、可用能力、期望在边界处返回的证据形式。
- **Subagents**：每个 assignment 独立工作上下文（不把中间过程灌回 Main）；初始上下文 $c_{i,0}=\Phi_S(d_i, b(h^M), \Gamma_i, \mathcal{S}_i)$（任务+有界背景+授权能力+技能目录）；返回 $r_i=(y_i, \mathcal{P}_i, \sigma_i)$——报告+证据引用+执行状态。
- **Coordinator Runtime**：上下文之间的**控制平面边界**——委派时组装 worker context，返回时只向 Main 暴露报告/证据引用/精简状态，完整轨迹单独存档可下钻。
- **通信三路径**：Main→Sub（下发+中途修正+取消）、Sub→Sub（最小化同辈通道，仅文本/工件引用，经 Coordinator 持久化到接收方 Inbox）、Sub→Main（ack 后投递终态到 Inbox）。消息携带"最小有用协调单元"并指向可单独检查的证据。

### 3.3 共享应用层与人在环

- 资源 $r=(\iota,\kappa,x,v)$，提交用乐观并发控制：baseRevision 一致才应用并 v+1，否则 conflict、提案保留重议——人与 agent 编辑走同一规则，混合编辑成为可审计修订序列。
- 人的直接修改即任务输入：agent 上下文只注入"他人未确认的增量变更"（Δ 项），不重复加载自己已知的编辑。
- Subagent 默认只读或准备**私有候选**，由 Main 决定合入；合入前重新校验基线。

### 3.4 层次化工作区与持久语义记忆

- 任务状态 $z_k=(W_k,P_k,R_k)$：工作对象/进度决策证据/进行中执行与待处理反馈。长计算作为后台 Job 持久化（身份/进程记录/日志），跨对话轮与 Main 重启存活；"泊车"前记录进度、等待条件与下一步意图。
- 检查点含消息轨迹、压缩摘要与"已摘要/未摘要"分界；反馈**进入 Main 已存上下文后才确认**，重启不丢未处理观测。
- 决策上下文重建受 token 上限约束：语义记忆 + 运行时/目标状态投影 + 实验摘要 + 近期历史。

### 3.5 RSI 后训练闭环（论文特色）

CoworkOS 组织实验：GLM-5.3 当控制器与数据教师，Qwen3.6-35B-A3B 被训练。1,345 条种子轨迹 SFT 得 R0 → 5 轮"评估→诊断→改数据管线→生成/验证/过滤→SFT→再评估"；BM25 相似度过滤防评测污染；R4 起"约束遵守"纳入验收。8 benchmark 均分 **33.19 → 42.95（+9.76）**。

### 3.6 实证结果（12 benchmark，四套 harness 对照：OpenHands/Codex/DeepSeek Harness/CoworkOS）

| 领域 | 代表分数（OH/Codex/DSH/CoworkOS） |
|---|---|
| 工具使用 | SkillsBench 63.30/53.48/56.75/**64.34**；AutomationBench 50.50/30.33/**53.50**/51.83 |
| 生产力 | JobBench 55.02/23.42/56.15/**59.88**；GDPVal(Elo) 1122/925/1157/**1164**；WorkspaceBench-Lite 64.54/58.81/**68.76**/67.14 |
| 搜索 | WideSearch 81.43/82.05/72.48/**82.47**；BrowseComp **83.00**/75.50/80.80/81.80 |
| ML 编码 | MLE-Bench-Lite 60.40/67.28/76.70/**76.90**；MLS-Bench 28.91/29.05/35.57/**35.62** |

四领域平均均进前二，生产力与 ML 编码平均第一。论文**无传统消融**（与 AutoSwarm 相反），分析集中在 RSI 归因与失败模式驱动的数据修订。

---

## 4. 参照系 B：CoworkOS 代码级分析

### 4.1 runtime 协作核心（src/runtime/，约 2.1 万行）

- **三层落点**：Main=`run-service.ts:98`（Task/Run 边界）+ `.pi/runtime/extension.ts:141`（工具装配/turn 生命周期/Inbox 轮询 1500-1531/心跳）；Coordinator=`coordinator-runtime.ts:263`（类注释自述"never makes planning decisions…owns the durable call lifecycle"），核心方法 dispatch:657 / waitForSubagents:268 / sendMessage:417 / sendPeerMessage:465 / cancelSubagent:545 / recoverRun:583；Subagent=非驻留对象，每次 dispatch 现造独立 PiSession（:847-912）+ 独立工作目录/checkpoint/inbox + `ask_main`/`send_peer_message` 工具（:815-839）。身份经 `agent-identity.ts:7` 原子 mkdir 抢占 `agents/subagents/subagent_N`，防复用。
- **委派**：`call_subagent` 工具（coordination.ts:306）mode 仅 sync|async；auto 解析规则在 `domain/types.ts:240-248`（有依赖→sync、critical 且 5 分钟内到期→sync、否则 async）。同步=Main turn 阻塞在工具内（且不装 ask_main——sync 调用里的提问永远到不了 Main，coordinator-runtime.ts:824-827 注释）；异步=落盘后立即 `onQueued` 返回 `{accepted, callId}`（:737），完成后 `writeMainCallback`（:1472）写 Main Inbox。
- **生命周期状态机**：`CallState = created|accepted|running|waiting|succeeded|partial|failed|timed_out|cancelled`（types.ts:11-20）+ **合法迁移表**（:189-199，`transitionCall` 强制校验）；队列 WorkItem 与 checkpoint 各有独立状态，三套互相印证。
- **Inbox**：单 JSON 文件 + 原子写 + 文件锁（scheduler.ts:267-492）；消息带 `priority/state: ready|leased|consumed/lease{consumerId,expiresAt}`（types.ts:87-100）；投递按优先级（subagent_question=50 > job.finished=10 > callback=1）；**两阶段确认**——deliver 只租约，`acknowledge`（main-inbox-delivery.ts:231-291）在消息确实进入 Main 持久 context 后才 consume，注释点题"Queuing is not acknowledgement"。崩溃恢复检查租约 owner 的 pid 存活性（scheduler.ts:359-371, 508-525）。
- **checkpoint/恢复**：Subagent 每 turn_end/compaction/run 结束回调落盘（pi-session.ts:315-321,426）；Main 另有 `context/{messages,memory,state}.json`（contextEpoch 随 compaction 递增）；恢复只重驱 queued 项、已 succeeded 的 checkpoint 拒绝重跑（coordinator-runtime.ts:676-678）；MainSupervisor 仅在"有未消费 Inbox + 无心跳 + 无 pending askhuman"才重启，退避 0/1/5/15/60 分钟（main-supervisor.ts:75,104-223）。
- **完成判定（机械闸门）**：`task-completion.ts:24-41` 依次查 `pendingJobs→pendingCalls→pendingCallbacks→pendingHumanRequests→pendingSubagentQuestions→parkedForWake→hasFinalAnswer`，注释自述"deliberately does not judge result quality…never an extra finish tool"；`hasFinalAnswer` 要求 assistant 停止响应且不含 toolCall（工具截断不算完成）。`finish_task` 工具同样先过此闸。
- **并发**：**无全局上限**——async 委派 fire-and-forget，队列只做持久化/重试不做节流（dispatch 即刻认领自己的 step）；间接约束仅 maxAttempts=3、Main 2000 turn/Subagent 200 turn。
- **长程三件套**：Job（独立进程组，pid 判活计入完成闸门）、Watch（确定性探针+事件入 Inbox）、Goal（`finish_task` 遇 active goal 直接拒绝，Main 结束可 park 成 waiting）。

### 4.2 工作区 / 存储 / 记忆（src/workspace|storage|domain/）

- **层次化工作区**：`<root>/<taskId>/` 固定子布局（artifacts/agents/{main,coordinator,subagents}/sessions/runs/watch/experiments/virtual-agents + task.json + task_events.jsonl），`layoutVersion: 3` 带显式迁移程序；产物发布走 staging→fsync→rename→更新索引，产物 id=内容+路径 sha256，防符号链接/越界检查严密（artifact-store.ts:85-157,441-507）。
- **持久化语义记忆（两套）**：①用户记忆——zod strict schema，单条 ≤2000 字符强制携带 Task/Run 溯源与原句引语；写入三通道（显式工具须引用用户原句、设置面板、后台学习每 15s 一 tick 且只在任务空闲时跑、每小时请求预算）；**准入纪律**是核心：非直接证据须 3 个不同 Task 独立支持才转正（admission.ts:56-92）、候选 30 天 TTL、敏感信息正则拦截、用户 opt-out 立即生效、人工修改 generation++ 使在途学习结果作废；检索=全量扫描+项目过滤+6000 字符预算截断注入 system prompt（**无向量/关键词索引**）。②项目经验——candidates 需 supportCount≥3 且 3 个已验证源（host 观察到的工具成功，模型自述不算）才可自动激活，否则留候选区等人工审阅；带 8 版历史与回滚。
- **事件与 trace**：JSONL 追加账本（run_events.jsonl / task_events.jsonl），事件强制绑 taskId/runId 且支持 causationId 因果链；trace recorder 覆盖 model_request/response/tool_start/end/runtime 并脱敏；模型请求级完整归档另存 `*-requests.jsonl`。
- **并发一致性**：跨进程 mkdir 目录锁（file-lock.ts）+ 死主 PID 探测恢复 + 可选心跳；所有 JSON 状态"临时文件+rename"原子替换；项目目录搬迁用两阶段提交（先写 intent 再逐个改 task.json，重启幂等续做）。

### 4.3 应用层 / 安全 / 工具（src/applications|security|tools|software/）

- **共享应用层**：Adapter 接口（text/pptist/cad/blender + 4 个外部 MCP harness 插件）；`ResourceStore` 是**唯一写路径**（"Both a person's keystroke batch and an Agent's tool call arrive here"），applyOperation 顺序=崩溃恢复→外部修改对账→幂等 operationId→revision CAS（409 可重试）→内容哈希防 ABA→追加式 undo；资源是"引用而非所有权"（mapping-store），多会话可共编同一文档；上下文注入只带"自上次确认 revision 以来的他人变更"。
- **MCP**：Supervisor 归 Dashboard 所有（"if the Agent owned the server, the window would still be open with its server already dead"），每应用一进程多窗口共享、引用计数、SIGTERM 宽限；工具调用把资源/任务放 `_meta` 防伪造；**服务器只返回 operations 不落盘**，写入仍走平台 CAS。
- **安全**：5 能力模型（software.read/edit、gui.observe/control、process.execute），授权必须 `authorizedBy:"human"`+decisionId，授权**刻意不设 HTTP 端点**（只走可信桌面 IPC）；Computer Use 三按钮分别申请 OS 权限、策略撤销先于磁盘 I/O；`askhuman` 问题落盘四态+60s 超时按 recommended 兜底；`grant_capabilities` 先经用户同意再记录（"records a decision, it does not make one"）；保护路径在文件工具层代码强制（对 Main 同样生效）。**弱点**：src/security 仅 36 行，授权的创建/撤销/审计持久化在生产代码中未发现完整实现；`process.execute` 声明了但无执行点校验。
- **工具面**：能力组开关（CORE+GROUPS）；CUA 脚本跑在 QuickJS 沙箱（64KiB 代码/64MiB 内存/64 次 host 调用/50ms CPU 切片）；科学工具版本化目录（v1-v7，独立 RDKit venv）。

### 4.4 工程质量观察

- **测试规模**：test/ 405 个文件（约 2577 用例）+ e2e/ 136 个 Playwright spec；恢复/竞态专项多（file-lock-recovery-race、subagent-failure-handoff、watch-supervisor-recovery、main-restart-recovery 等）。
- **纪律**：ESLint 钉架构依赖方向（runtime/applications 不得反向 import Dashboard）+ 架构回归测试；strict TS（runtime+.pi 仅 1 处 any、0 处 ts-ignore）；每个棘手决定都有"为什么"注释。
- **弱点**：巨型文件（coordinator-runtime.ts 1682 行、extension.ts 1585 行，dispatch 单函数约 510 行）；JSON 文件全量重写、Inbox consume 后永不删除（只增不减）；waitForSubagents/agent_end 靠 25-250ms 轮询非事件驱动；Subagent 并发无上限；`.pi/runtime` 依赖 dist/ 编译产物。

---

## 5. Neurova 现状基线（P3 批落地后）

与上轮 §7 基准的差异 = P1–P3 升级批已全部落地（提交 301a6290f…c8bbde9b9，详见方案执行记录）：

| 上轮断点/缺口 | 现状（证据） |
|---|---|
| 任务单元非结构化（A2 2/5） | `TaskUnit`（task_unit.py:19）goal/expectedResult/acceptanceCriteria/requiredInputs/artifactOwnership/reviewMode/dependencies + spawn 校验 |
| 验收门未挂蜂群终态（A3 3/5） | `runAcceptanceLoop` 挂 `_run_member` 终态前（swarm.py:1287 附近），不达标带 missing 回炉一次，设置项 `advanced.swarm_acceptance_enabled` 默认关+前端开关 |
| 无监督评审相位（B2） | `in_review` 相位占槽（swarm.py:89）+ `runReviewLoop` rubric 子会话 |
| 无依赖门控（B3） | `dependencies` + DEPENDENCY_UNKNOWN/DUPLICATED/FAILED + blocked 不占槽、终态结算放行（swarm.py:749 `_settleDependencies`） |
| 集成无协议（B5） | `integrationReport`（swarm.py:692）验收未过不得进集成清单 |
| run 状态不持久（B1） | 台账 SQLite（openSubagentRun/closeSubagentRun）+ 启动收敛 reconcile_at_startup |
| 升级无结构化闭环（B4） | escalate 带 suggested_action/action_note（P2-5） |
| 外部 agent 状态在内存（C3） | external_agents_state.json 原子落盘（P2-2） |
| 死码/双实现（G-10） | CRDT 退役、SubAgentManager 并入、CAPABILITY_* 接线 capability_graph（P2-3） |
| **新落地 P3-1** | 审批链 approval_chain.py:148 `requestRunApproval`——L0 自动/L1 代理给父/L2 强制人工，声明档只升不降；审批单落既有 ApprovalManager，等待/唤醒复用 approval_relay；member 面剔除裁决权 |
| **新落地 P3-2** | span 级 trace：parent_trace_id 捕获 + member 轨迹/span（swarm.py:1178 `_startMemberTrace`）+ agent_runs v4 迁移列 trace_id + NEUROVA_SWARM_TRACE 开关 |
| **新落地 P3-4** | 数据面围栏 context_firewall.py:65 注入特征扫描 + untrustedPayload 不可信槽位隔离渲染 + run.data_fence 命中只标记告警 |
| **新落地 P3-3** | 评测 harness 扩充：T3 量规任务 11 条 + by_effort 变量聚合 |

---

## 6. 逐维评测

> 每子项：CoworkOS 证据 → 得分；Neurova 现证据 → 得分（括号内为上轮分）。

### A. 协作形成

- **A1 团队组成与角色分配**：CoworkOS 三层角色固定、Subagent 身份原子预留防复用，但不按任务动态组队、无贡献辩护 → **3**。Neurova 单层 spawn+list_agents 辅助选人，无角色辩护（上轮 2，未变）→ **2**。
- **A2 任务单元结构化**：CoworkOS 委派=evidence contract（目标/约束/能力/期望证据，types.ts assignment 结构）→ **4**。Neurova TaskUnit 七字段+snake 别名容忍+任务书拼装（上轮 2→）**4**。
- **A3 验收条件**：CoworkOS 完成判定有意不判质量，验收=Main 评估+候选合入前复核，无自动验收判定器 → **3**。Neurova 验收门挂终态+回炉+诚实降级（上轮 3→）**4**。
- **A4 依赖与评审关系**：CoworkOS 无依赖声明/门控；评审=Main 验收+候选人工审阅 → **3**。Neurova 依赖门控+in_review 评审相位（上轮 2→）**4**。

**A 维：CoworkOS 13/20，Neurova 14/20（上轮 9）。** Neurova 首次在协作形成维反超——P1 三件套补的正是上轮最大差距。

### B. 执行协调

- **B1 共享执行状态**：CoworkOS 队列/Inbox/checkpoint 全持久化+事件溯源 → **5**。Neurova 内存 _runs+SQLite 台账+启动收敛（上轮 2→）**4**。
- **B2 单元生命周期**：CoworkOS 9 态+迁移表强校验 → **5**。Neurova 6 态单源+占槽语义（上轮 3→）**4**。
- **B3 依赖门控与前沿并行**：CoworkOS 无 η 门；并行无上限 → **2**。Neurova 依赖门控+blocked 不占槽+结算放行（上轮 1→）**4**。
- **B4 事件驱动交互与阻塞升级**：CoworkOS Inbox 优先级+askhuman+steer 安全边界注入 → **5**。Neurova 邮箱回灌+escalate 建议动作+卡死看门狗+审批链（上轮 3→）**4**。
- **B5 结果集成**：CoworkOS 候选制（Subagent 私有 candidate→Main CAS 合入，人工可拦截）→ **5**。Neurova integrationReport 机制化核对面（上轮 2→）**3**。

**B 维：CoworkOS 22/25，Neurova 19/25（上轮 14）。**

### C. 通信基础设施

- **C1 寻址/路由/邮箱**：CoworkOS 按代理寻址+租约+优先级+崩溃恢复 → **5**。Neurova AgentMailbox+SessionSyncManager 广播+ACP 总线 → **4**（持平上轮）。
- **C2 实时性**：CoworkOS SSE 流式+turn 边界注入，但等待靠轮询 → **4**。Neurova SSE/WS 流式+广播 → **4**（持平）。
- **C3 可靠性语义**：CoworkOS 两阶段确认（进持久 context 才 consume）+幂等 id+死主检测 → **5**。Neurova 邮箱单源写点+台账终态闭合+外部状态持久化（上轮 3→）**4**。

**C 维：CoworkOS 14/15，Neurova 12/15（上轮 11）。**

### D. 记忆与上下文共享

- **D1 跨 agent 上下文共享**：CoworkOS 共享应用层（引用不复制+增量 Δ 注入）→ **5**。Neurova 三通道回流+member 会话持久 → **4**（持平）。
- **D2 共享黑板/工作记忆**：CoworkOS 双记忆系统+准入/审阅/世代失效，但无检索 → **4**。Neurova 上下文池+MemCore 记忆体系 → **4**（上轮 3→，承认 Neurova 记忆面更宽但 CoworkOS 纪律更强，持平）。
- **D3 历史压缩与成本**：CoworkOS 压缩体系（2000 字符工具投影/摘要策略与守卫/失败冷却/子代理 20k 软目标）→ **5**。Neurova 有压缩与池化但无同等级纪律 → **3**（持平）。

**D 维：CoworkOS 14/15，Neurova 11/15（上轮 10）。** 上轮 Neurova 最大优势维，本轮被 CoworkOS 反超——其记忆纪律与压缩工程是全仓最强部分。

### E. 治理与安全

- **E1 权限/审批（人在环）**：CoworkOS askhuman+grant_capabilities+Computer Use 策略+human-only 授权（但授权持久化生产面缺失）→ **4**。Neurova 审批链 L0/L1/L2+governance ASK+权限模式（上轮 3→）**4**。持平。
- **E2 工具面收窄**：CoworkOS 能力组+保护路径代码强制+CUA 沙箱 → **5**。Neurova 白名单+执行咽喉拦截+explore 只读 → **4**（持平）。
- **E3 资源治理**：CoworkOS 无并发上限/预算闸 → **2**。Neurova 治理三明治+kill-switch → **5**（持平）。**Neurova 明确优势**。

**E 维：CoworkOS 11/15，Neurova 13/15（持平上轮）。** Neurova 仅存的两处领先维之一。

### F. 可观测与评测

- **F1 台账/trace/事件**：CoworkOS 事件溯源+因果链+请求级归档+脱敏 → **5**。Neurova 台账+trace_id span+OTel bridge（上轮 3→）**4**。
- **F2 基准评测 harness**：CoworkOS 12 benchmark 实测+RSI 闭环 → **5**。Neurova harness 已建成但无真模型基线数据（上轮 2→）**3**。

**F 维：CoworkOS 10/10，Neurova 7/10（上轮 6）。**

### G. 异构与互操作

- **G1 多模型/多 provider**：CoworkOS 任意 OpenAI 兼容+双协议+多连接档案 → **4**。Neurova 多 provider+渠道 → **4**（持平）。
- **G2 互操作协议**：CoworkOS MCP 深度集成（声明式接入+操作回传）→ **5**。Neurova ACP+MQTT+外部 agent 握手+MCP 客户端 → **4**（持平）。

**G 维：CoworkOS 9/10，Neurova 8/10（上轮 7）。**

### 6.x 总分表与两轮走势

| 维 | Neurova（上轮） | Neurova（本轮） | CoworkOS | 上轮 AutoSwarm |
|---|---|---|---|---|
| A 协作形成 | 9 | **14** | 13 | 20 |
| B 执行协调 | 14 | **19** | 22 | 23 |
| C 通信 | 11 | **12** | 14 | 11 |
| D 记忆共享 | 10 | **11** | 14 | 5 |
| E 治理安全 | 13 | **13** | 11 | 9 |
| F 观测评测 | 6 | **7** | 10 | 7 |
| G 异构互操作 | 7 | **8** | 9 | 9 |
| **合计** | **70（63.6%）** | **84（76.4%）** | **95（86.4%）** | 84（76.4%） |

> 读法：Neurova 已追平上轮 AutoSwarm 的分数，但在更强的 CoworkOS 面前仍差 11 分；差距集中在 **B1/B5（持久化协调与候选制集成）、C1/C3（邮箱可靠性语义）、D3（压缩纪律）、F1/F2（事件溯源与实测基准）**。E 治理安全是 Neurova 仅存的明确领先维（B3 依赖门控是 CoworkOS 没有的机制，已计入 A4/B3）。

---

## 7. 差距与改进点清单（新一轮，编号 H-x 供后续方案引用）

按"参照系实证收益 × 本仓落地成本"排序：

| # | 改进点 | 证据（评测依据） | 参照系做法 | 优先级 |
|---|---|---|---|---|
| H-1 | **邮箱两阶段确认** | C3 4/5；Neurova 邮箱 push 即算送达，崩溃窗口内消息可丢 | CoworkOS：租约→注入持久上下文→才 consume；幂等 messageId；死主 PID 探测回收 | **P1** |
| H-2 | **机械完成闸门与质量验收分离** | B2 4/5；Neurova 终态判定分散在异常分支 | CoworkOS：assessTaskCompletion 依次清点 pendingJobs/Calls/Callbacks/Questions，任一未清即 waiting；"闸门不管质量" | **P1** |
| H-3 | **Subagent 产出候选制** | B5 3/5；Neurova 报告直传即成结果 | CoworkOS：Subagent 只产私有候选，Main CAS 合入，冲突保留重议 | P2 |
| H-4 | **蜂群 span/事件溯源补因果链** | F1 4/5；trace_id 已通但事件无 causationId/无 JSONL 归档 | CoworkOS：事件强制绑 taskId/runId+causationId，模型请求级 JSONL 归档+脱敏 | P2 |
| H-5 | **记忆准入纪律** | D2 4/5；Neurova 记忆写入缺"多任务独立佐证才转正"类门槛 | CoworkOS：直接证据正则+3 Task 候选转正+敏感拦截+世代失效 | P2 |
| H-6 | **上下文压缩纪律** | D3 3/5 | CoworkOS：工具结果有界投影、摘要策略/守卫、失败冷却、子代理近期原文软目标 | P2 |
| H-7 | **真模型基线实测** | F2 3/5；harness 已有 11 条 T3 但未跑真模型出基线报告 | CoworkOS：12 benchmark 常态实测 | P2 |
| H-8 | **长程监控/目标持久化** | B4/B1 部分覆盖；Neurova 有定时任务但无"目标 park/恢复"语义 | CoworkOS：Goal/Watch/Supervisor 三件套，泊车记录等待条件与下一步意图 | P3 |

**不可照搬项（诚实边界）**：CoworkOS 的纯 JSON 文件存储在多任务规模下有性能天花板（其自认 listTasks 需遍历校验每个目录），Neurova 的 SQLite 台账方向更对；其"无并发上限+靠 Main 自律"不可学（本仓治理三明治是正确取舍）；其 macOS-only 的 GUI 驱动与 Electron 形态与 Neurova 产品定位不同；其 RSI 后训练依赖特定模型供给（GLM-5.3 控制器），属基础设施级投入，非协作机制本身。

---

## 8. 结论

1. P1–P3 升级批使 Neurova 从 70 → 84 分，**已追平上轮 AutoSwarm 参照系**；协作形成维（A）从最大差距维变为反超项，验证了 TaskUnit/验收门/评审相位/依赖门控的落地价值。
2. CoworkOS 代表当前最强的"执行可靠性工程"形态（95/110）：其价值不在协作形成（反而无依赖门控、无自动验收），而在**持久化协调、崩溃一致性、上下文压缩纪律与事件溯源**——这恰是 Neurova 下一步（H-1/H-2/H-4/H-6）的镜子。
3. 两轮对照的元结论：AutoSwarm 教"怎么组织协作"，CoworkOS 教"怎么让协作在真实长程环境中不死不丢不糊"；Neurova 的下一步升级应从前者转向后者。
