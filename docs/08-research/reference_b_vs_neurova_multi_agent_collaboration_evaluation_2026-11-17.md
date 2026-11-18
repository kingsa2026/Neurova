# AutoSwarm（论文 + 开源实现）与 Neurova 多 Agent 协作综合评测

- 日期：2026-11-17
- 性质：**研究参考**（按 `docs/INDEX.md` 纪律，本文不是架构事实源；架构事实以 `docs/01-architecture/` 权威文档与代码为准）
- 评测对象：本仓 `neurova/` 多 agent 协作面（蜂群 / ACP / Supervisor / 房间 / NeurFlow 工作流）
- 参照系：
  - [1] Zhonghang Li, Zongwei Li, Chao Huang. *AutoSwarm: Automating Agent Swarms*. arXiv:2610.33048v1（2026-10-17 提交）
  - [2] Mercor APEX-Agents: Investment Banking Analyst 榜单（https://www.mercor.com/apex/apex-agents-leaderboard/investment-banking-analyst-agent/）
  - [3] HKUDS/AutoSwarm 开源仓库（GitHub，MIT；本评测克隆件 commit `96f0b026`，2026-11-10，版本 2.0.0.dev0，含 `autoswarm-v1.0.0/` 归档）
  - [4] lizhouai/multi-agent-practice 开源仓库（GitHub，MIT；2026-11-17 二次补充研究，克隆件当日 main 快照，42 个 Python 文件 4886 行）——工程实践教学仓，作为多个改进点的"最小可行实现"参照（见 §6）
- 方法：论文全文逐节提取 + 参照系代码逐文件精读（v2 核心 37 文件 7617 行；v1 归档 245 文件约 20.6 万行抽样）+ 本仓代码级盘点（全链路 file:line 证据，承重结论均经二次亲验）。
- 关联：[ZCode 蜂群对照](reference_w_swarm_orchestration_comparison_2026-11-15.md)（其差距清单 #1–#5 已在本仓落地，本文按当前代码复核）、[多 Agent 协作机制设计](../01-architecture/04-multi-agent-collaboration.md)、[蜂群编排实施文档](../01-architecture/agent-swarm-orchestration.md)。

---

## 1. 摘要（结论先行）

**总分：Neurova 70/110（63.6%），AutoSwarm 参照系 84/110（76.4%）**——七维廿二子项等权求和（§8）。双方形态不同：AutoSwarm 是"论文机制驱动的协作框架"，Neurova 是"产品化的单进程多 Agent 平台"。

**Neurova 的领先项（保持，勿动）**：
1. **治理与安全**（E 维 13/15 vs AutoSwarm 9/15）：子代理工具面收窄 + 执行咽喉强制拦截（`swarm.py:144`、`test_subagent_tool_narrowing.py`）、治理三明治（深度/广度/预算/冷却/错峰 + kill-switch + 结构化拒绝，`swarm.py:265-303`）——AutoSwarm 明确"核心不设数量/轮次/超时限制"，把治理交还原生产品与用户。
2. **跨 agent 记忆与上下文共享**（D 维 10/15 vs 5/15）：结果三通道回流（直传 + 上下文池 EXPERIENCE 归档 `swarm.py:1165` + 终态邮箱 `swarm.py:1220`）、transcript.recall 指针下钻（`swarm.py:1186`）、房间共享转录、记忆作用域过滤——AutoSwarm 明确"不复制原生历史"，无共享记忆层。
3. **可观测性**（F1 4/5）：回合台账（`agent_run_ledger.py:81`）+ trace API + SSE 事件流 + Prometheus 指标 + OTel 桥。

**Neurova 的落后项（改进机会，全部有论文实证背书）**：
1. **协作形成缺结构**（A 维 9/20 vs 20/20）：无"按贡献辩护"的自适应组队、任务派发是自由文本（无预期产物/所有权/输入字段）、**验收条件与评审关系未挂接多 agent 链路**。论文消融实证：去掉贡献规格 −4.27 分、去掉监督评审 **−12.82 分**（Plancraft 74.36%→61.54%，几乎退回单 agent 水平 60.68%）——这是全论文最大的单项增益。
2. **任务单元间无依赖门控**（B3）：蜂群派生无 `dependencies` 声明（`swarm.py:314-330` 签名核实），依赖编排完全靠主 Agent 提示词自觉；NeurFlow DAG 有门控但只服务画布工作流，不服务蜂群。论文的 η 门（依赖全部验收通过才放行）是防"错误级联"的核心机制。
3. **无多 agent 评测 harness**（F2 2/5）：有 rag_eval 与进化 bench_gate，但没有任何多 agent 协作基准任务集与指标体系——本评测只能做静态机制对照，无法给出 Neurova 的实证任务成功率。**这是最优先补齐项**：没有它，后续一切协作改进都无法红绿验证。

**对 APEX 榜单的含义**：APEX 投行分析师（80 任务、专家二元量规、Pass@1）代表"长程工具使用 + 领域产出物正确性"的产品级评测方向。AutoSwarm 在该榜以 46.99 均分 / 41.25 Pass@1 登顶（超其底座 +5.95），证明"协作机制"在产品级基准上有可量化收益。Neurova 若要对标，路径是 §10 的三类基准接入，而非直接刷榜。

**二次补充（2026-11-17）**：应用户要求增补第四参照系——lizhouai/multi-agent-practice 代码级研究（§6）。该仓是教学脚手架而非生产系统，不参与评分，但它是本报告多个改进点（结构化契约、共享黑板、验收-反思环、预算熔断、逐跳归因评测、消融实验、双人审批）的**最小可行实现参照**，直接支撑升级方案的工程可行性判断。

---

## 2. 评测框架与方法

### 2.1 维度体系（7 维 22 子项）

维度取自两条线索的并集：AutoSwarm 论文被消融实验证明有效的机制（协作形成、执行协调），以及多 agent 系统的通用工程维度（通信、记忆、治理、观测、互操作）。

| 维 | 名称 | 子项 |
|---|---|---|
| A | 协作形成 | A1 团队组成与角色分配；A2 任务单元结构化；A3 验收条件；A4 依赖与评审关系 |
| B | 执行协调 | B1 共享执行状态；B2 单元生命周期；B3 依赖门控与前沿并行；B4 事件驱动交互与阻塞升级；B5 结果集成 |
| C | 通信基础设施 | C1 寻址/路由/邮箱；C2 实时性（流式/中断）；C3 可靠性语义 |
| D | 记忆与上下文共享 | D1 跨 agent 上下文共享；D2 共享黑板/工作记忆；D3 历史压缩与成本 |
| E | 治理与安全 | E1 权限/审批（人在环）；E2 工具面收窄；E3 资源治理 |
| F | 可观测与评测 | F1 台账/trace/事件；F2 基准评测 harness |
| G | 异构与互操作 | G1 多模型/多 provider；G2 互操作协议 |

### 2.2 评分锚点（0–5）

| 分 | 含义 |
|---|---|
| 0 | 无实现 |
| 1 | 骨架/占位，无生产消费方 |
| 2 | 部分实现；仅靠提示词或调用方自觉，无机制强制 |
| 3 | 机制化实现，覆盖主链路，有明显边界或未接线面 |
| 4 | 机制化 + 测试守卫 + 治理完备，仅缺横向覆盖或实证数据 |
| 5 | 机制化 + 测试 + 治理 + 实证（基准/实测数据）闭环 |

### 2.3 方法边界（诚实声明）

- 本评测是**静态代码级机制评测**：比对"代码里真实存在且被消费的机制"，不产生任务成功率数据。Neurova 的实证评测需按 §10 的 harness 方案执行后另行落数。
- AutoSwarm 侧分数评的是其论文机制 + 开源实现的综合形态；其基准数字（74.36% 等）是论文报告值，只作参照，不与 Neurova 静态分直接换算。
- v1 归档 20.6 万行仅抽样精读（coordinator / task_graph / adaptive_team / work_item_transition / collaboration_policy 等论文机制对应文件），其余按目录职责归纳。

---

## 3. 参照系 A：AutoSwarm 论文机制与实证结果

### 3.1 形式模型

任务 = (d, ℰ)（描述 + 环境），群体 = agents 𝒜 + 机制 Ω。协作被描述为：
- **组织 𝒪**（执行前固定）：职责分配 + 监督关系；
- **委派图 𝒢t**：节点是任务单元，边 (h,g) 表示 g 需要 h 的已验收结果；
- **共享执行状态 st**：单元生命周期、产出、评审结论、待办、未决请求；
- 转移：**(𝒢_{t+1}, s_{t+1}) = Φ_𝒪(𝒢_t, s_t; e_t)**，e_t 是新委派/结果提交/评审反馈/阻塞事件。

### 3.2 两大机制

**协作形成（Collaboration Formation）**
- 自适应组队：规划模型按任务复杂度/专长/响应要求提团队；**每个角色必须以"去掉或合并它会损失什么贡献"来辩护**；角色指令剔除无关职责、虚构资历、不兼容输出约定、无依据数值假设。
- 结构化任务委派——任务单元三元组：
  1. **贡献边界**：范围、预期产物、产物所有权、所回应的父需求、所需输入；
  2. **验收要求**：任务级的内容/证据/假设与局限标准，同时指导执行、评审与修正；
  3. **依赖与评审**：依赖 = 前置结果；评审关系 = 谁按验收标准把关。交接携带结果 + 证据 + 残余局限 + 预期用途。
- 每单元有**责任 agent**（执行/修正）与**监督 agent**（对父目标负责，默认评审人；可另派专家评审，但集成责任留在监督者）。

**执行协调（Execution Coordination）**
- 单元生命周期：Ready → In progress → In review → Done；修正反馈把单元打回 Ready 且保留先前产出。
- 三个机制化公式：
  - 验收：**a_t(g) = C_g^t(z_g^t) ∧ R_t(g)**（产出/证据达标 **且** 评审通过；失败/取消单元 a 恒 0——"终态关闭"本身不构成可用的输入）；
  - 依赖门：**η_t(g) = ∧_{(h,g)∈𝒟t} a_t(h)**；
  - 前沿：**ℱt = {g | q_t(g)=Ready, η_t(g)=1}**——无依赖矛盾的合格单元天然并行。
- 修正使旧验收失效；集成 = 父结果由已验收子贡献构建 + 结论调和 + 父需求复核后才进自身评审。
- 事件驱动交互：持久化、按角色寻址的消息（发送者/接收者/关联单元/意图/内容/证据引用）；显式应答要求产生等待义务与超时升级；**等待前先查接收方是否依赖请求方（防循环等待）**；超时/失败升级给监督者——监督者可澄清、改派、修订过时依赖；监督激活不豁免依赖门。

### 3.3 实证结果（数字全部来自论文）

| 实验 | 基准 | 结果 |
|---|---|---|
| RQ1 vs 单 agent | LongCLI-Bench（20 任务，F2P/P2P 测试判定） | 同底座多实例：MiniMax-M3 +10.0、DeepSeek-V4-Flash +12.5、GPT-5.6-Luna +15.0（Overall Pass Rate，均值 +12.5） |
| RQ2 vs 多 agent 框架 | Plancraft-small（117 题：97 可解 + 20 不可解） | **AutoSwarm 74.36%** > Teamwork ≈63.25% > Codex(max) 60.68% > Codex(ultra) 58.97%；可解题 69.07% vs Teamwork 55.67%；20 题不可解全部正确识别 |
| RQ3 产品级基准 | APEX-Agents 1.1 投行分析师（80 任务，专家二元量规） | **Mean 46.99 / Pass@1 41.25**，列榜第一；超自身底座（GPT-5.6-Luna Max：40.90/35.30）+6.09/+5.95；超 GLM-5.1（46.80/39.60）+0.19/+1.65 |
| RQ4 架构对照 | Plancraft-small | 独立并行 70.09% > **Codex 单 agent 60.68%** > 混合 52.14% > 中心化 48.72% > 去中心化(3 轮讨论+投票) 39.32%；AutoSwarm 74.36% |
| 消融 | Plancraft-small | 去**贡献规格**（产出/证据/验收标准）：−4.27 → 70.09%；去**监督评审**：**−12.82 → 61.54%**（≈Codex）；两变体不可解题均 100% |

**三条可迁移结论**（Neurova 评测与升级的直接依据）：
1. **"更丰富的通信/更中心化的控制"不保证更好的协作**——去中心化讨论、中心化星型、混合拓扑全部低于单 agent 与独立并行。多轮群聊讨论型协作（Neurova 房间链路若用于任务求解）需警惕此坑。
2. **验收条件与监督评审是最大增益来源**（合计约 +17 分），且都是"机制"而非"提示词"。
3. 评审/验收必须**结构化落状态**（a_t 进共享状态、驱动依赖门），只写不读的评审结论不产生增益。

---

## 4. 参照系 B：AutoSwarm 代码级分析

### 4.1 v1（`autoswarm-v1.0.0/`，即 opc）：论文机制的完整工程化

分层架构（layer0_interaction → layer6_observability，245 个 Python 文件）：

| 论文机制 | v1 代码落点 | 关键实现 |
|---|---|---|
| 自适应组队 | `opc/layer2_organization/adaptive_team.py` | `TEAM_RECRUITER_PROMPT`：一次性决定职责+人员；强制每角色写 `incremental_value`/`merge_alternative`/`artifact ownership`/`deliverables`/`acceptance criteria`/`dependencies`；"从可行单人方案开始，加人必须给出具体互补贡献；头衔与模型副本不自动产生能力；并行不免费" |
| 委派图/依赖门 | `opc/layer2_organization/task_graph.py` | `TaskGraphScheduler`：DAG 依赖管理，无未满足依赖的任务标 RUNNABLE，独立任务并行 |
| 单元生命周期 | `opc/layer2_organization/work_item_transition.py` | `transition_work_item`——**全仓唯一**允许改 WorkItem 相位的入口（相位即唯一事实源）；`refresh_dependents_for_run` 把子项终态传播给父项（依赖门的前沿传播） |
| 持久协调 | `opc/layer0_interaction/coordinator.py` | `InteractionCoordinator`：用户决策的持久化入口，DB 检查点为事实源，claim/consumption/decision 三种回执 + 租约 |
| 软拓扑协作 | `opc/layer2_organization/collaboration_policy.py` | 协作工具面（send_dm/broadcast_issue/start_meeting/ask_peer_and_wait）与写工具面分离治理 |
| 记忆/观测 | `opc/layer5_memory/`、`layer6_observability/` | memory_manager、history_compactor、skill_library、cost_tracker |

### 4.2 v2（`src/autoswarm/`）：极简进程协调运行时 + 声明式 Skill 协议

v2 把"群体智能"从运行时挪进**协议**（`assets/skill-template.md`，安装进宿主 agent 的 Skill），Python 运行时只做四件事：

1. **进程级调用管理**（`engine.py`/`runner.py`）：`run/wait/receive/resume/cancel/inspect`；每次调用一个独立 runner 进程 + 一个记录目录；`wait --any` 支持一轮内并行收集多个子任务。
2. **文件原子记录**（`records.py`）：临时文件 + fsync + 原子替换（Windows 走 POSIX 语义 rename）；OS 锁（flock/字节范围锁）保护会话续跑/投递/决策；**无心跳、无超时、无租约期**——状态从事实推导（有 result.json=returned；持有 runner.lock=running）。
3. **定向邮箱 + 审批/交互代理**（`messages.py`/`approvals.py`/`interactions.py`）：peer 授权由父在派发时声明（`--allow-peer`/`--communication-rules`）；`send --interrupt` 走原生中断；审批请求逐条持久化（request/decision/resolution 三文件 + 幂等），`delegate_to_parent` 默认开，`--by user` 只许转达用户真实答案——**禁止代用户发明同意**。
4. **12 种原生 CLI 适配**（`providers.py`/`native.py`/`acp.py`/`muse.py` 等）：保留各产品原生会话/权限/模型配置，任务经结构化 stdin/本地 API 进入，绝不拼 shell 字符串。

Skill 协议（论文机制的声明式投影）：能力表选 agent → 并行/依赖拆分 → `run --input <file> --background` 派发 → `wait --any` 收集 → 处理中途 questions/approvals → **整合、消解分歧、验证产物后才回答用户**。

### 4.3 工程质量观察（值得本仓借鉴的细节）

- **诚实失败**：投递四态（queued/submitted/delivered/needs_attention）；"native 提交成功 ≠ 模型已答"；`requested_selection` 只记录请求不谎称后端已应用；不确定的原生操作**永不自动重放**，保留 ID 与错误给父 agent 裁决。
- **防重复执行**：已完成结果不被通信回合覆盖（`mailbox.saved` 恢复原结果）；失败/取消/丢失的会话**不自动重跑**；用创建时间而非 PID 判进程身份。
- **验收测试面**：17 个测试文件覆盖协议/运行时/平台/桌面；`doctor --probe` 用真实模型调用验证协作方可达可续跑，"装了 ≠ 能用"。

---

## 5. 参照系 C：APEX-Agents 投行分析师基准

- **形态**：80 个长程任务；agent 在结构化环境（电子表格/文档/沟通材料）中多步工具操作；评测按**专家撰写的二元量规**逐条判定（由高盛/摩根士丹利/JPMorgan/巴克莱专家创建）。
- **指标**：Mean Score（满足的量规条目占比均值）与 Pass@1（一次尝试全条目满足）。
- **榜单头部**：Gemini 4 Carbon 86.9% Pass@1；AutoSwarm 41.25%（以协作框架身份入榜并登顶协作系）；底层模型 effort 档位影响巨大（Sonnet 5.5 Max 77.2% vs Medium 45.6%）。
- **对 Neurova 的含义**：
  1. 产品级 agentic 评测的形态是"**领域任务集 + 结构化环境 + 量规判分 + 轨迹留痕**"，不是对话评测；
  2. Neurova 的 `goal_verifier`（JSON 判据）与 `review.py`（rubric 评审）已经是 APEX 式 judge 的雏形，缺的是**任务集与环境**；
  3. effort 档位敏感性提示：Neurova 的 `effort_inference.py` 与模型路由应在基准中作为变量显式报告。

---

## 6. 参照系 D：multi-agent-practice 代码级研究（2026-11-17 二次补充）

### 6.1 项目定位与性质

lizhouai/multi-agent-practice 自述为"一套从 Mini Agent 到 Production Agent 的多智能体工程实践练习"——**教学脚手架，不是生产系统**（GitHub 1 star、MIT、42 个 Python 文件 4886 行、零第三方框架绑定的 mini 轨 + 自建微内核 production 轨 + LangGraph 1.0 范式轨；业务载体是"智能深度调研与竞品研报系统"）。它不参与本评测打分；其价值在于把 AutoSwarm 论文式的抽象机制落成了**可逐行阅读的最小可行实现**，且机制选型与本报告的改进点高度重合。

### 6.2 核心机制清单（逐文件核实）

| 机制 | 代码落点 | 实现要点 |
|---|---|---|
| 强类型交接契约 | `production_agent/core/schema.py` | `EvidenceCard`（dimension/claim/source/key_metrics/confidence/untrusted_origin/version）、`TaskNode`（id/dimension/assigned_agent/**depends_on**/status/output_evidence_ids）、`HandoffPacket`（**trusted_instructions / structured_payload / untrusted_payload 三槽位物理隔离**，非受信包体 >50KB 直接校验失败）、`HandoffReceipt`（**ACCEPTED / REJECTED / REVISE_REQUIRED** 三态回执）、`ActionRiskLevel` L0 只读 / L1 可逆 / L2 不可逆 |
| 共享黑板（单一事实源） | `core/state.py` `EvidenceBoard` | 集中任务 DAG + 证据池 + 审计流水；`put_evidence` 带**版本乐观锁**（expected_version 不符抛 `OptimisticLockError`，防并发脏写）；`save_checkpoint/load_checkpoint` 快照断点续跑 |
| 四种编排拓扑 | `core/topology.py` | Supervisor（ThreadPoolExecutor fan-out/fan-in）/ Pipeline / Router / Handoff 统一抽象；Handoff 内置 **max_hops 熔断**防对等踢皮球死循环 |
| 三维预算熔断 | `core/budget.py` | Token / 步数 / 挂钟时延三维任一超限即抛 `BudgetExceededException`；按 agent 记 token 明细（`agent_token_breakdown`）；env 可调默认值 |
| 仓壁隔离与自愈 | `core/resilience.py` | `BulkheadExecution.execute_with_fallback`（单点崩溃降级不拖垮全链）；`SelfHealingRetry.retry_with_feedback`（**机检失败把错误文本回传给 LLM 纠错再生成**，上限 3 次）；`CrossValidator.verify_consistency`（**异构模型独立上下文交叉核验**，打破同构幻觉共谋） |
| 双人审批闸门 | `core/security.py` `TwoManRuleGate` | L0/L1 自动放行；**L2 不可逆操作强制阻断**，interactive 模式控制台人工批准 / auto_approve 供 CI；拒绝抛 `SecurityActionDenied` |
| 上下文防火墙 | `core/context.py` | `<<<UNTRUSTED_EXTERNAL_DATA>>>` 物理围栏包裹外部抓取内容 + 注入特征正则探测（ignore previous instructions / rm -rf / curl|bash 等）；`FanInAggregator` 汇总时逐卡保留出处/指标/置信度/未核实标记，防 fan-in 吞证据 |
| 验收与反思环 | `agent/fact_checker_agent.py` + `langgraph_agent/graph.py` | FactChecker 用**第二异构模型**（`REASONING_MODEL_NAME`）独立审计分析结论是否被证据支撑，结果写回黑板；LangGraph 轨 `route_after_fact_check` 条件边：不通过→携 critique **回退 Analyst 重做**，`fact_check_attempts` 计数防死锁 |
| 规划防爆炸 | `agent/planner_agent.py` | 规划输出经 SelfHealingRetry 校验（JSON schema + 字段完整性）；子任务 >4 截断到 3，防子任务爆炸击穿预算 |
| 逐跳归因评测 | `eval/evaluator.py` | 拒绝端到端黑盒打分：切面 1 规划分工正交性 / 切面 2 证据指标填充率 / 切面 3 状态机失败任务 / 切面 4 核查通过率；**失败归因七类**（分工错/拓扑错/契约错/汇总错/状态错/执行错/安全防御错）；支持用例靶向断言（注入穿透检测、must_contain_metrics 硬指标覆盖）；综合分 ≥85 且零归因才判 production_ready |
| 单/多 agent 消融 | `eval/ablation.py` | 同一调研题上跑"单 Agent 全能 Prompt 基线"vs"多 Agent 生产拓扑"，对比耗时 / Token / 成本 / 证据得分 / trace 跳数，双报告归档，并给出**架构决策规则**（得分差 ≥15 分保持多 Agent，否则"若底座模型升级，坚决考虑退回单 Agent"） |
| 最小闭环 | `mini_agent/mini_agent.py`（375 行单文件） | Planner → 线程并发 SubAgent → AggregatorWriter，含 token 计数与 mock 模式——证明"看透 agent loop 与委派本质"只需几百行 |
| LangGraph 范式 | `langgraph_agent/state.py` 等 | `evidence_reducer`（按 id 去重 + 版本自增合并）、`Send` API 动态 fan-out、原生 `interrupt()` 双人审批与 `Command(resume=...)` 续跑 |

测试面：`production_agent/tests/` + `langgraph_agent/tests/` 共 25 个用例（拓扑/韧性/核心/checkpoint/并发/评测器/图流/中断恢复/状态合并）。

### 6.3 与本报告维度的映射（为何它支撑升级方案）

| 本报告改进点 | multi-agent-practice 的对应物 | 增量结论 |
|---|---|---|
| G-1 评测 harness（P0） | `eval/ablation.py` + `eval/evaluator.py` | **消融实验与逐跳归因评测存在可直接套用的形态**：单/多 agent 同题对照 + 耗时/Token/成本/得分四线指标 + "何时退回单 agent"决策规则，与本报告 §10.2 指标设计几乎同构 |
| G-2 任务单元结构化（P1-1） | `TaskNode` + `HandoffPacket`/`HandoffReceipt` | 结构化交接 = "类型化包 + 三态回执"，比自由文本只多一个 Pydantic 模型的成本 |
| G-3 验收门 / G-5 评审相位（P1-2/P1-3） | `FactChecker` + `CrossValidator` + 反思回边 + `SelfHealingRetry` | "验收不通过 → 携 critique 回炉"正是本方案 P1-2 的设计；异构第二模型核验可并入 P1-3 评审相位选项 |
| G-4 依赖门控（P1-4） | `TaskNode.depends_on` + Handoff `max_hops` 熔断 | 依赖字段与防环的最小形态已被验证 |
| G-7 run 状态持久化（P2-1） | `EvidenceBoard.save_checkpoint/load_checkpoint` | 快照语义参照（本仓用 SQLite 台账实现更强的） |
| G-11 审批链（P3-1） | `TwoManRuleGate` + LangGraph `interrupt()` | L0/L1/L2 危险分级 + 不可逆强制人工，是 AutoSwarm approvals.py 之外的第二个参照形态 |
| E2/上下文隔离（本仓已领先） | `ContextFirewall` 三槽位围栏 | 提示：本仓的 `computeSubagentToolAllowlist` 是工具面收窄，该仓补的是**数据面围栏**（非受信数据物理槽位）——两者互补，见 §9 增补项 |

### 6.4 局限与不可照搬项（诚实边界）

- **教学形态**：检索/工具为内置模拟（mock 高保真数据），无真实工具执行面；单机 `threading` 并发；无持久化服务、多租户、权限体系、渠道接入。**不可作为架构事实源**，只引其机制形态。
- 集中式可变黑板 + 锁适合单进程教学演示；本仓已有"台账（SQLite）+ 上下文池 + member 独立会话"的更强形态，无需引入它的黑板实现。
- 其评测判据是启发式打分（维度正交性、指标填充率），不是 APEX 式专家量规——方向对，判据强度不足，本报告 §10 的 T3 轨仍以量规判分为准。
- `CrossValidator` 解析失败时"默认放行"（resilience.py:97）——与本仓"解析失败如实返回 parse_ok=False、绝不静默放行"的纪律相反，**不可借鉴**。

### 6.5 小结

该仓把本报告要求的核心机制（类型化契约、回执三态、乐观锁黑板、反思回炉、三维熔断、逐跳归因、消融对照、双人闸门）用约 5k 行纯 Python + Pydantic 全部跑通并配了 25 个测试——**工程可行性不再是升级方案的假设，而是有先例的事实**。升级方案（姊妹篇）各 P 项已在对应位置标注该参照实现。

## 7. Neurova 多 agent 协作现状（代码级事实基线）

全仓盘点（含逐条 file:line 证据）确认 Neurova 的形态：**单进程多 Agent + 蜂群派生为主干，房间群聊与 NeurFlow 工作流为两翼，ACP/MQTT 为通信底座**。七条链路：

| 链路 | 入口 | 核心机制 |
|---|---|---|
| A 蜂群（主链路） | `/v1/chat` → `spawn_subagent` 工具 | `SwarmManager.spawn`（swarm.py:314）：治理闸 → SubAgentRun → member 会话独立对话 → 三通道回流 |
| B ACP 团队 | `POST /acp/teams/orchestrate`（acp_api.py:169） | `AgentTeam.orchestrate`（team.py:88）按步骤序列 TASK_ASSIGNMENT/TASK_RESULT |
| C Supervisor 扇出 | `POST /acp/supervisor/dispatch`（acp_api.py:237） | 扇出 + 幂等账本 + 重试 + RRF 聚合（orchestrator.py:43） |
| D 协作房间 | `/v1/collaboration/rooms/{id}/messages` | `RoomTurnRouter` @路由逐成员回应 + RoomBus 广播 + 共享转录 |
| E NeurFlow 工作流 | `/v1/neurflow/*`、画布 run | `WorkflowExecutor`（execution_engine.py:381）：DAG 分层并行/真循环/断点续跑 |
| F 定时任务 | `/v1/tasks` | `TaskScheduler`（scheduler.py:666）依赖图 + 重试 |
| G 外部 agent | `/v1/agent-communication/handshake` | 自定义 HTTP 协议 + API key + 内存注册表 |

已核实的关键机制（本评测逐条亲验过代码）：
- **子代理工具面收窄**：`computeSubagentToolAllowlist`（swarm.py:144-171）——general=全量内置工具−递归派生/续跑+可选 MCP 借用面；explore=只读白名单；`ToolExecutor._execute_single_tool`（tool_executor.py:1315）按 member 上下文绑定的白名单强制拦截。
- **治理三明治**：MAX_ACTIVE_CHILDREN=5、MAX_TASK_CHARS=8000、深度上限单源 `agent_limits_settings`、模型并发/429 冷却/错峰、结构化拒绝（code+message+retry_after_ms）、kill-switch（`NEUROVA_SWARM_GOVERNANCE=off`）。
- **卡死看门狗**：`_stallWatchdog`（swarm.py:858）——首报 900s 指数退避封顶 4h，广播 subagent_stalled + 父邮箱，**发现而不裁决**。
- **失败交接/复活**：`resumeFinishedRun`（swarm.py:574）+ `continue_subagent` 工具；`resumed_from` 记录续跑来源；member 会话键复用使历史自动带回。
- **前台自动转后台**：`AUTO_BACKGROUND_ENV`（swarm.py:100、536）。
- **目标验收门（单 agent 级）**：`verifyGoalCompletion`（goal_verifier.py，禁工具判定子会话，输出 achieved/confidence/missing）挂接 loop 出口（loops/base.py:99-154）——抓"假完成"，带续跑预算。
- **评审子会话**：`review.py` rubric 评审（P0–P3 + overall_correctness），服务 `/review` 命令与 console。
- **评测设施**：rag_eval（P/R/F1@K + LLM judge）、进化 bench_gate（benchmark 是 GATE 不是 fitness）、A/B manager、成本账（cost_budget + cost_ledger_integration）。

已知断点/半成品（盘点报告 §10，均经核实）：`MessageType.CAPABILITY_QUERY` 等六类消息无生产消费方（acp_runtime.py:99 注释自认占位）；`neurova/crdt/` 全仓无生产 import；`subagent.py` SubAgentManager 与 SwarmManager 并存（生产面仅 `Agent.spawn_subagent` 委托）；`collaborate/workflow/scheduler.py` 旧调度器与新 `agent/scheduler.py` 并存；外部 agent 握手状态在内存 dict（agent_communication_api.py:103-105）；蜂群 run 状态机不持久（重启丢进行中任务）；MQTT 总线依赖可选 paho-mqtt。

---

## 8. 逐维评测

> 每项给出：Neurova 证据 → 得分 → AutoSwarm 对照。AutoSwarm 得分依据 §3/§4。

### A. 协作形成

**A1 团队组成与角色分配 —— Neurova 2/5，AutoSwarm 5/5**
- Neurova：`spawn(task, agent_id, subagent_type)`（swarm.py:314-330）由调用方指定目标 agent，缺省回退 default；类型仅 general/explore 二值（swarm.py:161）。`AgentTeam.orchestrate`（team.py:88）需调用方显式给 members+steps。**没有"按任务自动设计团队并逐角色辩护贡献"的机制**。
- AutoSwarm：论文协作形成 + v1 `adaptive_team.py` 招聘官（incremental_value/merge_alternative/solo 判据/成本显式入判）。
- 差距实质：Neurova 的"团队"是调用方意图的执行，AutoSwarm 的"团队"是任务分析的产品。

**A2 任务单元结构化 —— Neurova 2/5，AutoSwarm 5/5**
- Neurova：`task` 是自由文本（≤8000 字符，swarm.py:289 硬限）；`SubAgentRun`（swarm.py:175-220）字段里没有预期产物、产物所有权、所需输入。派发质量完全取决于主 Agent 单次提示词写得好不好。
- AutoSwarm：任务单元三元组（贡献边界/验收要求/依赖评审），交接携带证据与残余局限。
- 差距实质：**这是后续一切机制化（验收/依赖门/集成）的数据基础**——没有结构化任务单元，验收条件无处挂靠。

**A3 验收条件 —— Neurova 3/5，AutoSwarm 5/5**
- Neurova：**有真实的 LLM 判据机制**——`goal_verifier.verifyGoalCompletion`（禁工具、强制 JSON、achieved/confidence/missing）+ GoalGate 挂 loop 出口（loops/base.py:118）防"假完成"；`review.py` rubric 评审子会话。**但两者都作用于单 agent 回合/命令面，未挂接蜂群任务单元交接**——子代理 completed 的判定是"原生回合结束"，不是"验收通过"。
- AutoSwarm：a_t(g)=C∧R 进共享状态、驱动依赖门；消融 −4.27/−12.82 实证。
- 差距实质：Neurova 有 judge 零件，缺"判定结果驱动协作状态机"的接线。

**A4 依赖与评审关系 —— Neurova 2/5，AutoSwarm 5/5**
- Neurova：NeurFlow DAG（dag.py:53/142/199）与 `TaskScheduler.TaskDependency`（scheduler.py:235）有依赖建模，但**只服务工作流/定时任务**；蜂群 `spawn` 签名无 dependencies 参数（swarm.py:314-330 亲验）；无评审关系字段。
- AutoSwarm：依赖边 + 评审关系是任务单元的组成部分，评审人默认监督者。

### A 维小结：Neurova 9/20，AutoSwarm 20/20。**最大差距维**，且论文消融证明其收益最大。

### B. 执行协调

**B1 共享执行状态 —— Neurova 3/5，AutoSwarm 4/5**
- Neurova：`SwarmManager._runs` 进程内存（swarm.py:306-307）+ `AgentRunLedger` SQLite 台账（agent_run_ledger.py:81，开行/心跳/park/settle + subagent 行）+ SessionSync 事件流。**run 状态机不持久**——重启后进行中子任务状态丢失（member 会话 json 可部分恢复对话内容，但状态机不恢复）。
- AutoSwarm v2：文件原子记录（结果/交付回执/诊断），状态从事实推导；v1：DB 检查点为事实源。

**B2 单元生命周期 —— Neurova 3/5，AutoSwarm 5/5**
- Neurova：`SUBAGENT_STATUSES = {pending, running, completed, failed}`（swarm.py:81-95 亲验）+ cause 归因（SUBAGENT_CAUSE_*）；NeurFlow 节点级状态 + checkpoint 续跑（execution_engine.py:1440/1477）。**无 in_review 相位**——评审不进状态机。
- AutoSwarm：Ready → In progress → In review → Done，修正打回 Ready 且保留产出。

**B3 依赖门控与前沿并行 —— Neurova 3/5，AutoSwarm 5/5**
- Neurova：并行能力强（NeurFlow 分层 `_compute_layers` execution_engine.py:999、tool_orchestrator.py:320、蜂群后台并发 + MAX_ACTIVE_CHILDREN）；但**蜂群任务间没有 η 门**——依赖放行靠主 Agent 自觉等待/轮询，无机制保证"未验收的前置结果不被下游采用"。
- AutoSwarm：η_t(g)=∧a_t(h) + 前沿并发；失败/取消单元的产出永不作为合格输入。

**B4 事件驱动交互与阻塞升级 —— Neurova 3/5，AutoSwarm 5/5**
- Neurova：`escalate`/`submit_result` 工具 → 父邮箱（builtin_tools.py:1279/1294，tool_executor.py:2450-2503）；stall watchdog 渐进提醒（发现不裁决）；房间 AGENT_ERROR 不静默（room_turn_router.py:168-172）；outbox 死信。**但无"监督者改派/修订依赖/换人"的机制化路径**——升级后怎么处理全靠主 Agent 自由裁量；防循环等待靠深度硬限（天然防环，算部分对齐）。
- AutoSwarm：升级给监督者 → 澄清/改派/修订依赖三选，且监督激活不豁免依赖门。

**B5 结果集成 —— Neurova 2/5，AutoSwarm 4/5**
- Neurova：集成完全由主 Agent 自觉完成（直传报告 + 池归档 + 邮箱回灌是"通知"而非"集成协议"）；无"父结果必须由已验收子贡献构建"的强制。
- AutoSwarm：集成 = 已验收贡献组合 + 结论调和 + 父需求复核后才进自身评审。

### B 维小结：Neurova 14/25，AutoSwarm 23/25。

### C. 通信基础设施

**C1 寻址/路由/邮箱 —— Neurova 4/5，AutoSwarm 4/5**
- Neurova：ACPRuntime（注册/路由/correlation_id 请求-响应/死信，acp_runtime.py:71-277）+ AgentMailbox（mailbox.py:23，loop 轮间隙排空注入 loops/base.py:881-893）+ RoomTurnRouter @路由 + 外部 HTTP handshake。多协议面完整。
- AutoSwarm：定向邮箱 + peer 授权 + reply_to 关联 + `wait --message` 关联收取（messages.py 完整状态机）。

**C2 实时性 —— Neurova 4/5，AutoSwarm 3/5**
- Neurova：SUBAGENT_CHUNK 逐 token 流式广播（聊天页小窗实时渲染）、SSE/WS 多端同步、让位闸中断（turn_coordinator.py）。**Neurova 优势**。
- AutoSwarm：依赖宿主原生 steer/interrupt 能力，不具备时等回合边界（文档明确"从不杀进程送信"）。

**C3 可靠性语义 —— Neurova 3/5，AutoSwarm 4/5**
- Neurova：outbox 投递状态机 + 重试 + 死信（outbox_handler.py:98/130）、ACP DLQ（dead_letter_queue.py:42）、supervisor 幂等账本（ledger.py:26）。**但**外部 agent 握手/注册在内存 dict（agent_communication_api.py:103-105）、蜂群 run 状态不持久——可靠性语义有洞。
- AutoSwarm：四态投递回执 + "不确定操作永不自动重放" + 诚实 diagnostics + 从不谎称 exactly-once（文档明示边界）。

### C 维小结：Neurova 11/15，AutoSwarm 11/15。持平；Neurova 实时性换 AutoSwarm 的可靠性纪律。

### D. 记忆与上下文共享

**D1 跨 agent 上下文共享 —— Neurova 4/5，AutoSwarm 2/5**
- Neurova：三通道回流（直传 + `_archive_to_pool` swarm.py:1165 EXPERIENCE 源 + `_notifyParentMail` swarm.py:1220）；`_uplinkEnvelope`（swarm.py:1186）带 transcript.recall 指针——主 Agent 凭指针下钻 member 会话全程而不搬正文；房间共享转录 `build_room_history`（room_turn_router.py:55-87，多发送者冠名区分）。**Neurova 显著优势**。
- AutoSwarm：明确"不复制原生历史"，子代理上下文靠任务文本携带；无共享记忆层。

**D2 共享黑板/工作记忆 —— Neurova 3/5，AutoSwarm 1/5**
- Neurova：ContextPoolRegistry 一 agent 一池（context_pool_registry.py:40）；memory_scope 作用域过滤（memory_scope.py:126）；MQTT memory/update 跨进程广播（可选依赖）。无跨 agent 实时黑板（CRDT 未接线）。
- AutoSwarm：无。

**D3 历史压缩与成本 —— Neurova 3/5，AutoSwarm 2/5**
- Neurova：记忆温度/固化/睡眠整理体系（CONTEXT.md 记忆系统）+ 上下文池 evict/recall（context_pool.py:1015）；但**多 agent 场景的传输上下文裁剪**（给子代理带多少父上下文、结果回传截断策略）未见专门机制。
- AutoSwarm v2 无压缩（明确不设上下文限制）；v1 有 history_compactor.py。

### D 维小结：Neurova 10/15，AutoSwarm 5/15。**Neurova 最大优势维**。

### E. 治理与安全

**E1 权限/审批（人在环） —— Neurova 3/5，AutoSwarm 5/5**
- Neurova：权限域划分（skills/permissions.py:68）、子代理权限"只收窄不升级"（tool_executor.py:2770-2775 inheritedModeScope）、skill_pool pending-skills 审批流（skill_pool_api.py:662-761）、让位闸超限挂起等人工（turn_coordinator.py 文件头）。**但子代理运行中的权限请求没有"代理给父/用户裁决"的跨 agent 审批链**（子代理直接继承父权限面）。
- AutoSwarm：approvals.py 完整状态机——子代理原生权限请求逐条持久化，父可代理裁决（delegate_to_parent），`--by user` 只许转达真实用户答案，**禁止代用户发明同意**；决策不重放、不越权。这是产品级人在环的标杆。

**E2 工具面收窄 —— Neurova 5/5，AutoSwarm 3/5**
- Neurova：computeSubagentToolAllowlist（swarm.py:144）+ ToolExecutor 强制拦截 + explore 只读型 + MCP 借用面（swarm.py:117，fail-open 收窄）+ 递归派生工具结构性剔除（swarm.py:170）+ 测试守卫（test_subagent_tool_narrowing.py）。**Neurova 显著优势**。
- AutoSwarm：子代理是完整 CLI 产品，工具面不收窄，靠各产品原生权限系统。

**E3 资源治理 —— Neurova 5/5，AutoSwarm 1/5**
- Neurova：治理三明治（深度/广度/预算/冷却/错峰/模型并发槽 + 结构化拒绝 + 配额回显 + kill-switch）+ cost_budget + 台账泳道。**Neurova 显著优势**。
- AutoSwarm：核心明确不设数量/轮次/超时/上下文限制（架构文档原文），治理交还原生产品与用户。

### E 维小结：Neurova 13/15，AutoSwarm 9/15。**Neurova 第二优势维**。

### F. 可观测与评测

**F1 台账/trace/事件 —— Neurova 4/5，AutoSwarm 3/5**
- Neurova：AgentRunLedger（泳道/心跳/park/settle + subagent 专门行）+ `/v1/trace` API（trace.py:155-211）+ SSE 事件流 + Prometheus `/metrics`（metrics.py:783）+ OTel bridge。**蜂群链路未接 span 级分布式 trace**（trace_id 只贯穿 ACP/Team/Supervisor）。
- AutoSwarm：文件记录 + 投递回执 + 诊断；无集中指标面。

**F2 基准评测 harness —— Neurova 2/5，AutoSwarm 4/5**
- Neurova：rag_eval（P/R/F1@K + 可选 LLM judge）、进化 bench_gate/deterministic_judge/exec_suite、A/B manager——评测零件存在，但**没有多 agent 协作基准**：无任务集、无协作指标定义、未接入任何公开 agentic benchmark。
- AutoSwarm：论文三基准实证（LongCLI/Plancraft/APEX）+ 仓库测试套件；基准代码本身未随开源仓发布（扣 1 分）。

### F 维小结：Neurova 6/10，AutoSwarm 7/10。

### G. 异构与互操作

**G1 多模型/多 provider —— Neurova 4/5，AutoSwarm 5/5**
- Neurova：MultiModelLLMClient + LLMRouter（10 类请求）+ ProviderManager（OpenAI/Anthropic/Gemini/Ollama/OpenRouter）+ 按模型并发/冷却治理 + 蜂群 per-run model 字段。
- AutoSwarm：12 种异构 agent CLI 统一适配，模型/effort 原生选择 + `doctor --probe` 实探验证 + 模型目录不建第二份枚举（尊重原生）。

**G2 互操作协议 —— Neurova 3/5，AutoSwarm 4/5**
- Neurova：ACP（进程内）+ MCP（客户端/服务端/OAuth/防火墙/重连）+ 自定义 HTTP handshake + MQTT（可选）。**但**无标准 A2A；CAPABILITY_QUERY/RESPONSE、COLLABORATION_INVITE/ACCEPT/REJECT/END 六类消息零消费方（acp_runtime.py:99 自认占位）；外部 agent 状态在内存。
- AutoSwarm：统一 ACP 客户端适配多产品 + Skill 安装面；同样非标准 A2A（扣 1 分共同）。

### G 维小结：Neurova 7/10，AutoSwarm 9/10。

### 8.x 总分表

| 维 | Neurova | AutoSwarm | 判定 |
|---|---|---|---|
| A 协作形成 | 9/20 | 20/20 | **AutoSwarm 大幅领先**（论文核心） |
| B 执行协调 | 14/25 | 23/25 | AutoSwarm 领先 |
| C 通信 | 11/15 | 11/15 | 持平（形态互异） |
| D 记忆共享 | 10/15 | 5/15 | **Neurova 大幅领先** |
| E 治理安全 | 13/15 | 9/15 | **Neurova 领先** |
| F 观测评测 | 6/10 | 7/10 | 接近；F2 是 Neurova 短板 |
| G 异构互操作 | 7/10 | 9/10 | AutoSwarm 小幅领先 |
| **合计** | **70/110（63.6%）** | **84/110（76.4%）** | |

> 读法说明：AutoSwarm 的 80% 是"研究框架在其自选维度上的完备度"；Neurova 的 66.7% 是"产品平台在含治理/观测等工程维度上的完备度"。差距集中在 A/B（协作机制本身），而这恰是论文消融证明收益最大的部分——**补 A3/A4/B3/B5 的机制化接线是收益最高方向**。

---

## 9. 差距与改进点清单

按"论文实证收益 × 本仓落地成本"排序。编号 G-x 供升级方案引用。

| # | 改进点 | 证据（评测依据） | 论文实证收益 | 优先级 |
|---|---|---|---|---|
| G-1 | **多 agent 评测 harness 缺失** | F2 2/5；无任务集/指标/判定闭环 | 无它则以下一切无法红绿验证 | **P0** |
| G-2 | **任务单元非结构化** | A2 2/5；spawn 自由文本，SubAgentRun 无预期产物/所有权/输入字段 | 消融"去贡献规格"−4.27；是验收/依赖门的数据基础 | **P1** |
| G-3 | **验收门未挂接蜂群终态** | A3 3/5；goal_verifier 只在单 agent loop 出口；子代理 completed=回合结束非验收通过 | 消融"去监督评审"−12.82（最大单项） | **P1** |
| G-4 | **蜂群无依赖门控** | A4/B3；spawn 无 dependencies；未验收前置结果可被下游采用 | η 门是防错误级联核心机制 | **P1** |
| G-5 | **无监督评审相位** | B2 无 in_review 态；review.py 只服务 /review 命令 | 同 G-3，−12.82 的载体 | **P1** |
| G-6 | **集成无协议** | B5 2/5；集成靠主 Agent 自觉 | 论文：父结果须由已验收子贡献构建 | P2 |
| G-7 | **蜂群 run 状态不持久** | B1；重启丢进行中任务 | 可靠性（v1 DB 检查点 / v2 文件事实源） | P2 |
| G-8 | **升级后处置无机制化路径** | B4；escalate 只投递，无改派/修订依赖的结构化闭环 | 监督者三选动作 | P2 |
| G-9 | **外部 agent 状态在内存** | C3；agent_communication_api.py:103-105 | 可靠性 | P2 |
| G-10 | **死码/双实现卫生** | CAPABILITY_QUERY 六类零消费；CRDT 零消费；SubAgentManager 与 SwarmManager 并存；新旧两调度器并存 | 违反协作红线断点条款/教义第 6、7 条 | P2 |
| G-11 | **子代理运行中审批无跨 agent 代理链** | E1 3/5；无 approvals.py 式请求-裁决状态机 | 人在环产品化 | P3 |
| G-12 | **蜂群未接 span 级 trace** | F1；trace_id 不贯穿蜂群 | 归因能力 | P3 |
| G-13 | **子代理数据面无非受信数据隔离**（二次补充，见 §6.3） | 蜂群把外部抓取内容与任务指令混排进同一 task 文本；无 trusted/untrusted 槽位围栏与注入探测。参照 multi-agent-practice `ContextFirewall` 三槽位 + `HandoffPacket` 物理隔离 | 提示词注入防御（工具面收窄 G 已有，数据面是互补的另一半） | P3 |

**Neurova 独有、应保持不动的优势**（勿在升级中破坏）：member 独立会话（可查询/审计/跨轮恢复）、上下文池 EXPERIENCE 归档 + recall 指针下钻、治理三明治 + kill-switch、工具面收窄与 explore 型、台账/trace/SSE/metrics 观测面、让位闸的"发现而不裁决"哲学（与 AutoSwarm 监督升级哲学不谋而合）。

---

## 10. 经验证评测执行方案（把静态评测变成可复现实验）

> 本节是 G-1 的设计草案：不改也能看懂，改完即可跑。

### 10.1 任务集（三类，对应论文三基准的形态）

| 类 | 形态 | 种子规模 | 判定方式 | 对标 |
|---|---|---|---|---|
| T1 确定性模拟 | 本仓可控的模拟环境（如：文件树重构任务、多步骤数据管线搭建），状态可程序化校验 | 20 题（16 可解 + 4 不可解，测"能否正确说不可行"） | 环境终态断言（测试即判据，零 LLM 成本） | Plancraft |
| T2 长程工具任务 | 真实仓库子任务（bug 修复/小特性），带 F2P/P2P 测试 | 10–20 题 | pytest 通过即判据 | LongCLI-Bench |
| T3 领域产出物 | 财务/分析类文档任务 + 专家式二元量规（先自建 5–10 题打样） | 5–10 题 | goal_verifier + rubric judge（双判据，分歧仲裁） | APEX |

### 10.2 指标定义（写入 harness 输出，逐任务 + 聚合）

- **任务成功率**（T1/T2：判据全过；T3：量规全满足）与 **Mean Score**（T3 量规满足率均值）——对应 Pass@1 / Mean Score。
- **不可解题识别率**（对"正确说不可行"单独计分，防"永远尝试"刷分）。
- **协作开销**：多 agent 相对单 agent 基线的 token 增量、时延增量、调用次数增量（论文未报成本，本仓补上——这是相对 AutoSwarm 的评测增量）。
- **协作过程指标**：派生次数、验收一次通过率、评审打回率、升级次数、依赖等待时长、卡死提醒次数（全部可从台账/事件流直接取数）。
- **稳健性**：同一任务 × 3 种子重复，报均值与最差值（论文 RQ1 跑两遍取均值的做法）。

### 10.3 接入点（全部复用现有设施，不新建平行体系）

- 判定器：复用 `goal_verifier.verifyGoalCompletion`（achieved/missing）与 `review.py` rubric 通道；确定性任务用 pytest/环境断言。
- 成本与台账：复用 `models/cost_budget.py` + `AgentRunLedger` + usage 记账。
- 运行面：harness 以**普通用户身份**走 `/v1/chat` + 蜂群工具（不绕过治理闸），或以 workflow origin 走 NeurFlow——两条链路都测。
- CI 分层：mock LLM 跑 harness 自身正确性（进 tests/）；真模型跑作为发布前手动门（`NEUROVA_BENCH_*` 配置），成本受 cost_budget 约束。

### 10.4 验收标准

- harness 落 `neurova/benchmark/multi_agent/` + `tests/unit/benchmark/`；一条命令出 JSON+Markdown 报告（逐任务 + 聚合 + 成本）。
- 首个基线报告落 `docs/05-reports/`：单 agent vs 蜂群在 T1 上的成功率与开销对照——这一张表就是本评测 §8 全部推断的实证检验。

---

## 11. 结论

1. **总评**：Neurova 70/110 vs AutoSwarm 84/110。Neurova 是"治理强、记忆强、观测强、协作机制弱"的产品化平台；AutoSwarm 是"协作机制完备、治理有意留白"的研究框架。两者差距不在工程品质，而在**协作机制是否被结构化、状态化、机制强制**。
2. **最值钱的三个改进**（论文消融直接背书）：任务单元结构化（G-2）→ 子代理终态验收门（G-3）→ 监督评审相位（G-5），辅以依赖门控（G-4）。这四项共同把 Neurova 的蜂群从"派生-汇报"升级为"派生-验收-评审-集成"的闭环。
3. **最紧迫的一项**是 G-1 评测 harness：本评测已经把维度、指标、判据、接入点设计完毕（§10；multi-agent-practice 的 `eval/ablation.py`+`eval/evaluator.py` 提供了同构的参照实现，见 §6.3），落地后 Neurova 将拥有同类产品极少具备的"多 agent 协作可量化回归"能力——这本身也是对 AutoSwarm"无成本数据"短板的超越。
4. **不要做的**：不要引入中心化调度常驻服务（违背本仓进程内架构与 AutoSwarm v2 的极简教训）；不要做多轮自由讨论式群聊解题（论文实证 −21~−35 分）；不要为对齐 AutoSwarm 而削弱治理三明治与工具面收窄——那是 Neurova 的护城河。

可执行升级方案见姊妹篇：[2026-11-17 多 Agent 协作升级实施方案](../04-plans/2026-11-17-multi-agent-collaboration-upgrade-plan.md)。
