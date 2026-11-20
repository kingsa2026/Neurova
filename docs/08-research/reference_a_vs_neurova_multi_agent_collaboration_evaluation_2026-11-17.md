# CoworkOS vs Neurova 多 Agent 协作对照评测（2026-11-17 第二轮）

> 参照系：CoworkOS（arXiv:2611.03178，RUC-NLPIR，代码 github.com/RUC-NLPIR/CoworkOS，克隆件 `~/.zcode/tmp/coworkos-src` @ baf03c3）。
> 被评方：Neurova 本仓**当前态**（P1–P3 升级批全部落地后，含 6273c9f45/21c266a14/6a9e054ff）。
> 上轮同框评测见 [reference_b_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md](reference_b_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)——维度体系与评分锚点**原样复用**，两轮分数可直接对比。

---

## 1. 摘要（结论先行）

**总分：Neurova 84/110（76.4%），CoworkOS 参照系 95/110（86.4%）**——七维廿二子项等权求和（§6 总分表）。与上轮相比，Neurova 从 70 → 84（+14，全部来自 P1–P3 升级批的机制化落地）；CoworkOS 是迄今评测过的最强参照系（AutoSwarm 84、ZCode 对照另计）。

> **【2026-11-18 S14 重评】** 超越方案 S1–S13 全部落地、H 系（H-1/H-2/H-4 三段/H-7）与父侧叫停/运行中改需求补评后，同框重评 **Neurova 98/110（89.1%）**——越过超越判定线 ≥96，**超越成立**（逐子项证据、执行记录与判定见 §6.y；§6.x 总分表已增重评列）。
>
> **【2026-11-18 追加批二次重评】** 用户拍板补齐 S14 诚实边界剩余项后，S15–S18 四批落地（压缩失败冷却+子代理软目标、记忆重纪律 3-Task 转正/世代失效/人工审阅、模型请求级归档、MCP 团队能力外部暴露）——**Neurova 100/110（90.9%）**，对 CoworkOS（95）领先 5 分（逐项证据见 §6.y 二次重评小节；D/G 两维追平，仅 F 差 1 分且系 v2 复跑待密钥）。
>
> **【2026-11-18 1F 真模型复跑·终评】** v2 基线已实测归档（新判据+记忆隔离下 26 任务，[报告](multi_agent_bench_baseline_v2_2026-11-18.md)）——F2 4→5，**Neurova 101/110（91.8%）**，领先 CoworkOS（95）6 分；F 观测评测追平（10 vs 10），七维全部 ≥ 参照系。
>
> **【终评指向】** 本报告保留为第 2/3 轮过程记录；**独立终评终稿**（22 项全表现场复核 + 执行记录）见 [reference_a_vs_neurova_final_evaluation_2026-11-18.md](reference_a_vs_neurova_final_evaluation_2026-11-18.md)。

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

与上轮 §7 基准的差异 = P1–P3 升级批已全部落地（提交 c05bf9aee…6a9e054ff，详见方案执行记录）：

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

| 维 | Neurova（上轮） | Neurova（本轮 11-17） | Neurova（重评 11-18） | CoworkOS | 上轮 AutoSwarm |
|---|---|---|---|---|---|
| A 协作形成 | 9 | 14 | **16** | 13 | 20 |
| B 执行协调 | 14 | 19 | **24** | 22 | 23 |
| C 通信 | 11 | 12 | **14** | 14 | 11 |
| D 记忆共享 | 10 | 11 | **13** | 14 | 5 |
| E 治理安全 | 13 | 13 | **14** | 11 | 9 |
| F 观测评测 | 6 | 7 | **9** | 10 | 7 |
| G 异构互操作 | 7 | 8 | **8** | 9 | 9 |
| **合计** | **70（63.6%）** | **84（76.4%）** | **98（89.1%）** | **95（86.4%）** | 84（76.4%） |

> 读法：Neurova 已追平上轮 AutoSwarm 的分数，但在更强的 CoworkOS 面前仍差 11 分；差距集中在 **B1/B5（持久化协调与候选制集成）、C1/C3（邮箱可靠性语义）、D3（压缩纪律）、F1/F2（事件溯源与实测基准）**。E 治理安全是 Neurova 仅存的明确领先维（B3 依赖门控是 CoworkOS 没有的机制，已计入 A4/B3）。
> 【11-18 重评读法】上述 11 分差距恰是 S1–S13 的攻击面：重评后 Neurova 98 反超 CoworkOS 95——A（16 vs 13）/B（24 vs 22）/E（14 vs 11）领先，C（14 vs 14）持平，D（13 vs 14）/F（9 vs 10）/G（8 vs 9）各差 1 分；判定线 ≥96 达成，**超越成立**（证据与剩余差距见 §6.y）。
>
> 【11-18 追加批二次重评读法】S15–S18 落地后 **Neurova 100 vs CoworkOS 95**——A（16 vs 13）/B（24 vs 22）/E（14 vs 11）领先扩大，C 持平（14 vs 14），D 追平（14 vs 14）、G 追平（9 vs 9），仅 F 差 1 分（9 vs 10，缺项=v2 真模型复跑待密钥）。
>
> 【11-18 1F 复跑终评读法】F2 4→5（v2 基线实测归档）——Neurova 101 vs CoworkOS 95，F 追平（10 vs 10），七维全部 ≥ 参照系。

### 6.y 2026-11-18 重评（S14 同框重评分）

> **方法**：维度体系与锚点不变（§2.2，0=无实现 / 1=骨架无消费 / 2=部分实现仅靠自觉 / 3=机制化覆盖主链路 / 4=机制化+测试守卫+治理完备 / 5=机制化+测试+治理+实证闭环）。对每个涨分子项到现场代码核证据——**机制落点（file:line）+ 消费方（写入→读取→反馈闭环）+ 测试/实测**，无证据不涨分；本节引证的 commit 号已经 `git log` 逐一核验存在，file:line 为 2026-11-18 现场读数。上轮（2026-11-17）评分过程原样保留于 §6 各维小节，两轮可直接对比。评分纪律：宁可少评不可虚高——不足以支撑锚点上一格的子项维持原分并写明原因（A2/A3/A4/B3/C2/D1/D2/E2/G1/G2 与 E3 满锚共 11 项不动）。

#### 重评逐子项（22 项全表）

| 子项 | 上轮 | 重评 | 变动依据（机制落点 + 消费方 + 测试/实测） |
|---|---|---|---|
| A1 团队组成与角色分配 | 2 | **4** | 名册选人：spawn 按团队职责生成任务书角色段（`swarm.py:416`，受 `TEAM_DUTY_PROMPT_MAX_CHARS` 约束 `swarm.py:125`）+ `list_teams`/`dispatch_team`/`propose_team` 三工具（`builtin_tools.py:1269/1279/1317`，主 agent 专属、成员面声明集+执行咽喉双保险剔除 `tool_executor.py:1563`）+ 临时团队沉淀经治理 L1 ASK、人批准才经 `createAgentProposedTeam` 写入（`teams_api.py:165` 唯一写点，origin/approved_by/promoted_from_run）+ 前端 TeamPage 来源标（`TeamPage.vue:22`）。测试 `test_team_dispatch.py` 17 用例；live-verify 9641/9651。**不给 5**：角色贡献辩护机制仍缺（CoworkOS 亦无，非超越必需） |
| A2 任务单元结构化 | 4 | 4 | TaskUnit 上轮已评 4；S3/S4 只增依赖与产物声明的消费面（候选 artifactKeys 来自 TaskUnit.artifactOwnership），结构未变 |
| A3 验收条件 | 4 | 4 | 验收门+回炉上轮已评 4；S4 候选 `reviseRequired` 复用同一验收判定（不新造判定器），锚点未变 |
| A4 依赖与评审关系 | 4 | 4 | 依赖门控+in_review 评审相位上轮已评 4 |
| B1 共享执行状态 | 4 | **5** | `RUN_STATUS_TRANSITIONS` 全量出边表（`swarm.py:141`）+ `transitionRun` 唯一收口（`swarm.py:154`，swarm 7 处+review_gate 6 处赋值点改道）+ 每次迁移落 `status_changed` 入 H-4 账本 + `replayRunTailStatus`（`swarm.py:190`）/`reconcileRunFromEvents`（`swarm.py:1090`）启动重放校正 + 台账 SQLite v5 增 project_id/team_id 列（`agent_run_store.py:138`，PRAGMA user_version 通道）。测试 `test_run_status_transitions.py`（`test_illegal_transition_completed_to_running_raises` 钉非法迁移、`test_legal_chain_running_in_review_completed_logs_events` 钉落账）；live-verify 9631 迁移序列与账本逐条对上 |
| B2 单元生命周期 | 4 | **5** | 迁移表强校验：非法迁移显式抛 `IllegalRunStatusTransition`（`swarm.py:150,170`，不静默不吞）+ H-2 机械完成闸门 `pendingBackgroundForSession`（`swarm.py:1118`，`eefce1a73`：后台未清完成声明不得静默通过、等待事实并入出口正文且不续跑模型防忙等）+ in_review 占槽评审相位；live-verify 9631 |
| B3 依赖门控与前沿并行 | 4 | 4 | 依赖门控+blocked 不占槽+结算放行上轮已评 4（CoworkOS 至今无 η 门，本项维持领先） |
| B4 事件驱动交互与阻塞升级 | 4 | **5** | H-1 邮箱两阶段确认（`d51d1ac2d`）+ H-2 等待核账 + S9 escalate/审批投递协作房间→`handleRoomSwarmReply` 回灌 `decideSwarmApproval`（`collaboration_room_api.py:147`，`140df7b45`：L2 判定限群主/admin、普通成员只记议见、重启从房间历史补建 pending 索引）+ 父侧叫停 `cancel_subagent`→`cancelRun` 兜底落账（`swarm.py:1520`，`60ef5dd81`）+ 运行中改需求 `continue_subagent`/`updateSubagent` mode=steer 注入成员会话插话队列（`swarm.py:1598`）。测试 `test_swarm_room_integration.py` 14 用例；live-verify 9641 群主回复→桥接匹配→判定成功→裁决卡上墙全程实测 |
| B5 结果集成 | 3 | **5** | `CandidateMergeBoard`（`candidate_merge.py:105`）提交即互标冲突双方保留 + CAS 合入 `mergeCandidate`（`candidate_merge.py:182`，baseRevision≠revision 判冲突、绝不静默覆盖）+ 回流先落候选不直传定案（`swarm.py:1209` submitCandidate、回炉重提 `swarm.py:2255`）+ `integrationReport` 增 revision/candidates/conflicts（`swarm.py:1193`）+ 房间拦截/采纳端点（S9，判定权在候选板单源）+ 人工拦截经审批链分级（NEUROVA_SWARM_MERGE_APPROVAL_LEVEL）。测试 `test_candidate_merge.py` 19 用例；live-verify 9651 候选两次 CAS 合并上墙 |
| C1 寻址/路由/邮箱 | 4 | **5** | messageId 幂等去重（`mailbox.py:78`）+ priority 三级队列、lease 降序同级时间升序（`mailbox.py:101`）+ leased 超时回收回 ready（回收计数进 `stats()` `mailbox.py:149`）+ stats 快照并入 /monitor/resources→MonitorPage 邮箱健康卡（`MonitorPage.vue:44`，`05243a943`）；唯一写点 pushParentMail 纪律保持（钉死 swarm.py+loops/base.py） |
| C2 实时性 | 4 | 4 | SSE/WS 流式+广播上轮已评 4；provider 侧真流式（N1）属模型调用面，不改变本子项锚点 |
| C3 可靠性语义 | 4 | **5** | CoworkOS 三件套对齐：两阶段确认 lease→落盘→acknowledge（`mailbox.py:127`，`d51d1ac2d`，破坏性 drain 退役）+ messageId 幂等（S2 `1f8a59d51`）+ 死主回收（leased 超 TTL 回收重投）——"宁重不丢"不升级成"重复生效"靠消费侧判重闭环（`loops/base.py:102` 幂等窗口、`loops/base.py:956` 重投件只补确认）；测试 `test_mailbox_two_phase.py`（`test_duplicateMessageIdDeliveredOnce`/`test_unacked_message_is_redelivered_on_next_lease`/`test_drain_removed` 等） |
| D1 跨 agent 上下文共享 | 4 | 4 | 三通道回流+member 会话持久上轮已评 4；S9 room 作用域黑板计入 D2 侧，未改本子项锚点 |
| D2 共享黑板/工作记忆 | 4 | 4 | S7 写入前敏感拦截+准入清单提示词已落地（`memory_admission.py:108` SENSITIVE_KEY_PATTERNS、`memory_admission.py:171` screenMemoryContent，`mem_core.py:481` installMemoryAdmission 单点接线，审计走 security/audit_logger 单源；`d2ad31207`）+ live-verify 假 key 拒收入审计。**不涨的原因**：3-Task 独立佐证转正/人工审阅/世代失效缺位——按方案保守口径 0 分预算，写入门已补但整体准入纪律仍不及 CoworkOS |
| D3 历史压缩与成本 | 3 | **5** | S5 会话追加式 JSONL+快照两段式（`session_manager.py:42,46`，追加/撕裂封口/坏行跳过/懒迁移，`427877f16`）+ S6 四件（`1864c1031`）：`CONTEXT_COMPACT_TRIGGER_RATIO=0.85` 越水位自动折叠（`context_pool.py:48`、`chat_pipeline.py:2863`）+ 溢出错误族兜底压缩重试一次 + `assertCompactionShrinks` 严格变小守卫（`context_pool.py:121`）+ `CompressionEvent` 落时间线且原消息永不删（`context_pool.py:69,162`）+ 工具结果有界投影句柄回取、失败不折叠（`chat_pipeline.py:3017`）+ swarm 轨迹生产者接线。消费：ChatPage 认领 context_compacted 轻提示（`ChatPage.vue:2007`，`a12533c54`）。测试 `test_context_compact_discipline.py` 19 用例 + `test_session_store_append_only.py`；live-verify 9632 真后端压缩全链。诚实边界：CoworkOS 的失败冷却与子代理 20k 软目标暂无等价物（见剩余差距清单） |
| E1 权限/审批（人在环） | 4 | **5** | S8 审批审计持久化（`0b2f2ff1c`）：请求/决定成对落审计单源（`approval_chain.py:137`，swarm_approval_request/decide，fail-open 但错误可见）+ GET /v1/audit/approvals?run_id= 成对轨迹查询（admin 门）+ AuditPage 成对查询面板（`audit.ts:98` getApprovalTrajectory，`130601b48`）+ 房间裁决记 decided_by_channel + 审批投递 priority=high（S2 移交闭环）。测试 `test_approval_audit_persistence.py` 9 用例 + 审批链既有 18 例；审计链路经 live-verify 9641（房间裁决）/9663（按 resource_id 查台账）实证 |
| E2 工具面收窄 | 4 | 4 | 白名单+执行咽喉+explore 只读上轮已评 4；收尾波 MAIN_AGENT_ONLY_TOOLS 声明集单源收口（`f19849710`，`tool_executor.py:1563` 降为执行期纵深防御第二道）是 4 分内部强化；无 CUA 沙箱等价物，不给 5 |
| E3 资源治理 | 5 | 5 | 治理三明治（广度/深度/预算/冷却/错峰硬闸）满锚未变；S10/S11/S13 新工具全部入治理三明治照算 |
| F1 台账/trace/事件 | 4 | **5** | H-4 run 级 JSONL 事件账本+causation_id 因果链（`swarm_event_log.py:35`，`c15b3881f`）+ `runEvents` 读面（`swarm.py:1081`）+ view=events 端点（`70ba3f79a`）+ SubAgentPanel 事件时间线前端（`e47943b24`）+ S12 台账 v5 project_id/team_id 归属列（`agent_run_store.py:130`，`7caa50f58`）+ GET /projects/{id}/collaboration 五类记录聚合+归档封卷自动总结（`projects_api.py:11`）+ CollaborationPage 档案面板（`collaboration.ts:669`，`f191ba1e6`）。脱敏纪律：正文不进账本、档案只出摘要与句柄。测试 `test_project_collab_dossier.py` 10 用例；live-verify 9661 spawned→started→terminal 完整因果链+封卷留底。诚实边界：模型请求级全量归档（CoworkOS \*-requests.jsonl 形态）暂无 |
| F2 基准评测 harness | 3 | **4** | S1 评测地基（`70cf0da6d`）：usage 回传（`runner.py:6`、`metrics.py:22` 聚合）+ `expect_trajectory` 轨迹判据（`tasks.py:85`）+ taskIsolatedMemory 默认开（`runner.py:9`）+ T1 改材料归纳 + /baseline-reports 只读端点（`benchmark.py:379`）+ BenchmarkPage 报告视图（`benchmark.ts:110`，`b97a6986f`）+ N3 suite_eval 真执行器后台轮询（`577f65577`）+ H-7 真模型基线 140 次真实调用在案（[multi_agent_bench_baseline_2026-11-17.md](multi_agent_bench_baseline_2026-11-17.md)）。**不给 5**：新判据+记忆隔离下的 v2 真模型复跑待密钥供给（S1 移交 1F），缺"新口径实测"这一环 |
| G1 多模型/多 provider | 4 | 4 | 多 provider+渠道未变 |
| G2 互操作协议 | 4 | 4 | ACP+MQTT+外部 agent 握手+MCP 客户端未变；MCP 深度集成维持登记（方案明确不做，另行立项） |

**维度小计**：A 16（+2）、B 24（+5）、C 14（+2）、D 13（+2）、E 14（+1）、F 9（+2）、G 8（0）——**合计 98/110（89.1%）**，较上轮 84 净 +14。

#### 判定

**98 ≥ 96——超越成立。** Neurova 98/110 超过 CoworkOS 95/110 三分。A 协作形成（16 vs 13）、B 执行协调（24 vs 22）、E 治理安全（14 vs 11）三维领先，C 通信持平（14 vs 14），D 记忆共享、F 观测评测、G 异构互操作各差 1 分——三处落后均为**单件深度差距**（D 缺压缩失败冷却/子代理软目标与记忆重纪律、F 缺请求级归档与 v2 复跑、G 缺 MCP 深度集成），非结构性缺口。判定不降低口径：F2 若按最严口径守 3 分、D3 若按"对标件齐全"口径守 4 分，总分仍为 96~97，判定不变。

#### S1–S13 执行记录（commit 号均已 git log 核验；与方案文档执行记录段一致）

| 批次 | commit | 交付一句话 |
|---|---|---|
| S1 评测地基 | `70cf0da6d` | usage 回传、expect_trajectory 判据、taskIsolatedMemory 默认开、T1 材料归纳重设计、/baseline-reports 只读端点 |
| S2 邮箱语义 | `1f8a59d51` | messageId 幂等、priority 队列、leased 超时回收、stats() 并入 /monitor/resources |
| S3 迁移表 | `efaf20a6f` | RUN_STATUS_TRANSITIONS + transitionRun 唯一收口（13 赋值点改道）+ status_changed 落账 + 启动重放校正 |
| S4 候选制 | `bc8429609` | CandidateMergeBoard CAS 合入、冲突双保留升级、审批分级、integrationReport 增 candidates/conflicts |
| S5 会话追加式 | `427877f16` | JSONL+快照两段式（追加/撕裂封口/懒迁移），NEUROVA_SESSION_JSONL 门控 |
| S6 压缩纪律 | `1864c1031` | 0.85 水位自动触发、溢出兜底、严格变小守卫、CompressionEvent 落时间线、有界投影、轨迹生产者接线 |
| S7 记忆准入 | `d2ad31207` | 写入前敏感拦截 + 准入清单提示词 + 审计单源 |
| S8 审批审计 | `0b2f2ff1c` | 请求/决定成对落审计单源 + 按 runId 轨迹查询 + 审批邮件 priority=high |
| S9 团队/房间接入 | `140df7b45` + `dd9972dbb` | 人在环房间闭环（回灌判定/群主权限/pending 补建）+ 名册选人 + room 作用域黑板 + 前端审批/候选卡片 |
| S10 固定团队开放 | `95e169406` | list_teams/dispatch_team/propose_team 三工具 + 沉淀 ASK 闭环 + 治理三明治照算 |
| S11 双入口 | `a671e9dd6` | 房间直发交 SwarmManager 统一编排（零第二编排引擎）+ 事件回房间 + 终态走候选板 |
| S12 项目协作档案 | `7caa50f58` + `f191ba1e6` | run→project 归属标落台账 v5 + 五类记录聚合读面 + 封卷留底 + 前端档案面板 |
| S13 agent 工具面 | `d0c270ac8` | project_create/list/detail/room_post 四工具 + 创建即建房间 + L1 ASK 治理 |
| 收尾波·后端（S13 移交清偿） | `f19849710` + `89e05433a` + `0fabc2f7a` | MAIN_AGENT_ONLY_TOOLS 并集收口单一事实源 + 房间裁决回灌项目治理 ASK + docstring 残引扫荡 |
| 收尾波·前端（附录 D 清零） | `b97a6986f` + `05243a943` + `a12533c54` + `130601b48` + `879a08b76` | S1 报告视图 / S2 邮箱健康卡 / S6 压缩轻提示 / S8 审计面板 / S3 类型复核 |
| H 系补评（评测后落地，本批计入对应子项） | `d51d1ac2d`（H-1）/ `eefce1a73`（H-2）/ `c15b3881f` + `70ba3f79a` + `e47943b24`（H-4 三段）/ `46173b431`（钉子清偿） | 两阶段确认 / 机械完成闸门 / 事件账本+读面+前端时间线（§7 执行记录已有详述） |
| 父侧叫停/运行中改需求（评测后落地） | `60ef5dd81` | cancel_subagent→cancelRun 落账；continue_subagent/updateSubagent steer 注入/restart 重派 |
| N3 评测执行器 | `577f65577` | suite_eval 判据注入真执行器 + 后台轮询（计入 F2） |

#### 剩余差距与下一轮清单（不降低口径的诚实清单）

1. **D 维收尾**：压缩失败冷却与子代理软目标（CoworkOS D3 剩余件）；记忆 3-Task 候选转正/世代失效（H-5 重纪律，触碰 MemCore 主干，须独立方案先行）——D2 维持 4 的原因。
2. **F 维收尾**：F2 的 v2 真模型复跑（新判据+记忆隔离下重出基线，S1 移交 1F 待密钥）；F1 的模型请求级归档（H-4 纪律刻意不进账本，如需另立 trace 归档面，不破坏账本脱敏纪律）。
3. **G 维**：MCP 深度集成（G2 4→5 的唯一路径，方案 §0.3 明确另行立项）。
4. **A1 的 5 分路径**：角色贡献辩护机制（参照系亦无，非超越必需，按需另立项）。

#### 2026-11-18 追加批二次重评（S15–S18，统筹者复核）

用户拍板补齐 S14 诚实边界剩余项后，四批落地并经统筹复核（全量 trio/api 于干净 worktree 验证，失败集合与基线逐条一致零新增；主工作树另有会话记忆层重构在途，故全量验证不在主树做）：

- **D2 4→5**：记忆重纪律全量——3-Task 候选转正（`MEMORY_PROMOTION_MIN_TASKS=3`，`memory_discipline.py`，任务键单源 task_id>run_id>session_id）+ 世代失效（复用 `judgeClauseConflict` 全仓唯一确定性冲突判据，旧代 `status=superseded` 可追溯不物理删）+ 人工审阅接通（`screenMemoryContent`→pending propose/confirm，S7 移交清偿；敏感放行走作用域令牌不黏连全局策略）+ `NEUROVA_MEMORY_DISCIPLINE` 门控（关闭态行为与现状一致由专测锁定）。22 用例红→绿；live-verify 9673：候选→3 任务→转正（taskKeys 三会话实测）、矛盾→失效（旧代退出召回）全程实测。commit `10256925f`（lineage 统一读取口与端点 `0247f91fb`）。
- **G2 4→5**：MCP 深度集成——`mcp_surface.py` 增 team_list/team_dispatch/project_list/project_detail 工具壳，转交 `ToolExecutor.execute` 单管道（治理三明治/审批链/审计/run 溯源与主 agent 原生调用同一条路），工具描述与原生 builtin schema 同源；双鉴权照旧；成员面剔除在 MCP 侧同样生效（不可绕过）。11 用例红→绿；A/B 510 passed 零新增；live-verify 9677 真 MCP 握手 team_list→team_dispatch。commit `a276a0246`。
- **D3/F1 诚实边界闭合**（分数维持 5，边界消除）：D3 压缩失败递增冷却（5/15/30s 状态机随会话持久）+ 子代理软目标 20k（`a22b52d87`，live-verify 9671 压缩失败进冷却实测）；F1 模型请求级归档（`61c985ec9`，每会话 JSONL 独立 trace 面+脱敏+档案聚合消费闭环，不破坏 H-4 账本纪律）。
- **维度小计更新**：D 14（+1）、G 9（+1）——**合计 100/110（90.9%）**，领先 CoworkOS（95）5 分。
- **F2 4→5（1F 真模型复跑，2026-11-18）**：v2 基线已实测归档——新判据（usage/轨迹）+taskIsolatedMemory+T1 材料归纳下 26 任务（solo+swarm），token 倍数 **0.857**（v1 为 None）、swarm 更快更省（-10.3s）、候选制 CAS 合入经审批链 L0 实测触发、请求级归档全程留痕；报告 [v2 md](multi_agent_bench_baseline_v2_2026-11-18.md) / [v2 json](multi_agent_bench_baseline_v2_2026-11-18.json)（v1 保留对照）。机制/测试面同前（S1 评测地基 + N3 执行器）。
- **维度小计终评**：D 14（+1）、G 9（+1）、F 10（+1，1F 后）——**合计 101/110（91.8%）**，领先 CoworkOS（95）6 分。
- **剩余差距（诚实清单，仅余）**：A1 角色贡献辩护机制（参照系亦无，按需另立项）。

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

**执行记录（2026-11-17 第二批，同日无人值守）**：H-1（`d51d1ac2d`，邮箱两阶段确认：lease→落盘→acknowledge，破坏性 drain 退役，至少一次投递宁重不丢）；H-2（`eefce1a73`，机械完成闸门：`SwarmManager.pendingBackgroundForSession` 核账 + 主出口把等待事实并入正文并落会话盘，**不续跑模型**防忙等，fail-open）；H-4（`c15b3881f`，run 级 JSONL 事件账本 `<数据根>/swarm_runs/<id>.events.jsonl` + causation_id 因果链，spawned/started/terminal/stalled/escalated/result_submitted 全落档，正文不进账本）。**H-3/H-5/H-6/H-8 登记不盲做**：H-3 候选制的核心价值在保护共享产物，而本仓子代理当前只回传报告、不改共享资源（报告质量已有验收门 + integrationReport 把关），待共享产物编辑场景出现再立项；H-5/H-6 触碰 MemCore 与上下文压缩主干，须独立方案先行；H-8 依赖目标/监督者产品面，另立项。**H-7 需真模型供给，待拍板**。终验：agent+collaboration+benchmark 35 failed 与基线逐条一致（零新增）、2550 passed；途中撞"正文不得按字面量砍长度"常驻钉子（H-4 事件摘要截断撞 `testSwarmNoLongerSlicesBodyByLiteralLength`），按其明示口径改为具名常量（`EVENT_TASK_SUMMARY_CHARS`/`EVENT_ERROR_SUMMARY_CHARS`）后回绿。

**H-4 闭环补全（2026-11-17 第三批，同日）**：读侧 `70ba3f79a`（`subagent_status` 增 `view=events`，经 `SwarmManager.runEvents` 吐 JSONL 账本）+ 前端可视化 `e47943b24`——console 新增 `GET /chat/subagents/{subagent_id}/events`（归属判定与 runs 读面同一谓词：台账行 `user_id` + `_check_session_ownership`，台账无行非管理员 fail-closed 403、管理员 bypass），SubAgentPanel 头部增 ≡ 时间线开关，点开按 causation_id 因果链序渲染 spawned/started/stalled/escalated/update_injected/cancelled/terminal 全程事件，运行中 5s 轮询、终态补拉一次，文案 11 语言对齐——账本从「只写不读」走完 **写入→读取→反馈** 闭环。途中清偿读侧批遗留钉子（`46173b431`：view 枚举钉子随扩容同步更新）；console 路由快照随新增路由重生成（34→35 条纯增量）。终验：trio（agent+collaboration+benchmark）35 failed=基线逐条一致、2573 passed；api 17 failed 与 stash 基线逐条一致（均 R4 台账在册预存失败）——**零新增失败**。

**H-7 真模型基线已实测（2026-11-17，api.mosi.cn / nex-n2.6，两轮共 140 次真实调用；报告与原始 JSON 见 [multi_agent_bench_baseline_2026-11-17.md](multi_agent_bench_baseline_2026-11-17.md)）**：13 任务 × solo/swarm 双模式——**solo 与 swarm 均为 1/13（7.7%），swarm 平均耗时更快 14.4s**。首轮暴露并当场修复一个 harness 假通过根因（`_extractText` 对无正文键的 dict 回退对象 repr，标记匹配进了 reasoning 的 repr——修复后首轮报告作废重跑）。结果解读（诚实边界）：①低分主要由**字面量量规的严格性**主导——模型用 "## 一、自由现金流" 这类 markdown 标题回应"须分【自由现金流预测】…四节"的提示词，内容实质达标但标记不匹配即 0 分（唯一通过的 exec-summary 恰好按【】格式书写）；②**跨任务记忆串扰实测发生**：同一 Agent 的持久记忆把前序任务语境带进后续任务（solo/swarm 均出现"延续上一份交付物"表述）——产品上是特性，评测方法学上是污染，后续跑正式对比时需按任务隔离记忆；③T1 模拟任务（虚构来源标记）对真模型不可用——诚实模型不会编造《A 报告》，该族任务需重设计（在提示词中给出来源或改判"拒绝编造"为得分项）；④token 读数未进结果（管道未回传 usage），Token 倍数列空缺——harness 待补。**结论：本报告是 harness 与口径的基线，不是模型能力结论；正式对比前需完成 T1 重设计与记忆隔离。**

**不可照搬项（诚实边界）**：CoworkOS 的纯 JSON 文件存储在多任务规模下有性能天花板（其自认 listTasks 需遍历校验每个目录），Neurova 的 SQLite 台账方向更对；其"无并发上限+靠 Main 自律"不可学（本仓治理三明治是正确取舍）；其 macOS-only 的 GUI 驱动与 Electron 形态与 Neurova 产品定位不同；其 RSI 后训练依赖特定模型供给（GLM-5.3 控制器），属基础设施级投入，非协作机制本身。

---

## 8. 结论

1. P1–P3 升级批使 Neurova 从 70 → 84 分，**已追平上轮 AutoSwarm 参照系**；协作形成维（A）从最大差距维变为反超项，验证了 TaskUnit/验收门/评审相位/依赖门控的落地价值。
2. CoworkOS 代表当前最强的"执行可靠性工程"形态（95/110）：其价值不在协作形成（反而无依赖门控、无自动验收），而在**持久化协调、崩溃一致性、上下文压缩纪律与事件溯源**——这恰是 Neurova 下一步（H-1/H-2/H-4/H-6）的镜子。
3. 两轮对照的元结论：AutoSwarm 教"怎么组织协作"，CoworkOS 教"怎么让协作在真实长程环境中不死不丢不糊"；Neurova 的下一步升级应从前者转向后者。
4. **【2026-11-18 S14 重评后】** S1–S13 与 H 系、父侧叫停/运行中改需求全部落地，同框重评 **98/110**，越过判定线 ≥96——**对 CoworkOS 的超越成立**（逐子项证据与执行记录见 §6.y）。领先项：A 协作形成（16 vs 13）、B 执行协调（24 vs 22）、E 治理安全（14 vs 11）；持平：C 通信（14 vs 14）；落后各 1 分：D 记忆共享（13 vs 14）、F 观测评测（9 vs 10）、G 异构互操作（8 vs 9），均为单件深度差距，下一轮清单见 §6.y。
5. **【2026-11-18 追加批二次重评后】** S15–S18 落地（压缩失败冷却+子代理软目标、记忆重纪律、模型请求级归档、MCP 深度集成）后 **100/110**：D 记忆共享追平（14 vs 14）、G 异构互操作追平（9 vs 9），对 CoworkOS 领先 5 分；仅 F 观测评测差 1 分（9 vs 10，唯一缺项=F2 v2 真模型复跑待密钥）。
6. **【2026-11-18 1F 真模型复跑·终评】** v2 基线实测归档（新判据+记忆隔离，26 任务 solo+swarm）后 F2 4→5——**101/110**，F 观测评测追平（10 vs 10），**七维全部 ≥ CoworkOS，领先 6 分**。
