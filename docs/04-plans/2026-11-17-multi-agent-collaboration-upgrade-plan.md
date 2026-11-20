# 多 Agent 协作升级实施方案（依据 AutoSwarm 对照评测）

- 日期：2026-11-17
- 依据：[AutoSwarm 与 Neurova 多 Agent 协作综合评测](../08-research/reference_b_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)（下称"评测报告"；其 §9 改进点 G-1…G-13 与 §10 评测方案是本方案直接输入；2026-11-17 二次补充的参照系 D——lizhouai/multi-agent-practice 代码级研究（评测报告 §6）为多个 P 项提供了最小可行实现参照，下文以"参照 MAP"标注）
- 范围：`neurova/agent/swarm.py`、`neurova/agent/goal_verifier.py`、`neurova/agent/review.py`、`neurova/agent/mailbox.py`、`neurova/builtin_tools.py`、`neurova/tool_executor.py`、`neurova/benchmark/`、`tests/unit/agent/`、`tests/unit/benchmark/`
- 纪律：每项先红后绿（红灯测试实证缺陷/期望行为）、净新增 LOC 尽量为负或列明去向、live-verify 真链路自证、同根因全命中点扫荡、不建第二套平行体系（复用 goal_verifier/review/台账/邮箱/治理闸，不另起炉灶）。

---

## 0. 总路线

```
P0 评测地基        G-1  多 agent 评测 harness（无它则一切改进无法红绿验证）
P1 协作机制闭环    G-2 任务单元结构化 → G-3 终态验收门 → G-5 监督评审相位 → G-4 依赖门控
P2 可靠性与卫生    G-7 run 状态持久化 / G-9 外部 agent 持久化 / G-10 死码与双实现清偿 / G-6 集成协议 / G-8 升级闭环
P3 产品化增强      G-11 跨 agent 审批链 / G-12 蜂群 span 级 trace / G-13 子代理数据面围栏
```

依赖关系：P1 各项依赖 G-2 的结构化任务单元；G-3 是 G-5/G-4 的前置（先有"验收通过"这个状态，才有"评审""依赖门"可挂）。P0 与 P1-2 可并行开工。

**明确不做**（防过度工程，评测报告 §10.4）：
- 不建中心化调度常驻服务/全局任务队列（进程内架构不变）；
- 不做多轮自由讨论式群聊解题机制（论文实证去中心化讨论 39.32% < 单 agent 60.68%）;
- 不削弱治理三明治/工具面收窄换取"灵活性";
- 不引入第二个判定器体系（复用 goal_verifier/review 单源）。

---

## P0-1 多 agent 协作评测 harness（G-1）

**动机**：当前无法对任何协作改进做红绿验证；评测报告 F2 仅 2/5。论文三基准（Plancraft 确定性模拟 / LongCLI 测试判定 / APEX 量规判分）提供了三类任务形态模板。**参照 MAP**：multi-agent-practice `eval/ablation.py`（单/多 agent 同题对照：耗时/Token/成本/得分/trace 跳数四线指标 + "何时退回单 agent"决策规则）与 `eval/evaluator.py`（逐跳切面评测 + 七类失败归因 + 靶向断言）是本 harness 的同构最小实现，直接照抄其报告字段结构。

**改动文件**
- 新增 `neurova/benchmark/multi_agent/__init__.py`、`tasks.py`（任务集注册表）、`runner.py`（逐任务执行：单 agent 基线 + 蜂群两配置）、`metrics.py`（成功率/Mean Score/不可解题识别率/协作开销/过程指标）、`report.py`（JSON+Markdown 报告）。
- 新增 `neurova/benchmark/multi_agent/suites/t1_sim/`（3–5 个确定性模拟任务打样：任务描述 + 环境断言函数）、`suites/t3_rubric/`（2–3 个带量规的分析任务样例）。
- 新增 `tests/unit/benchmark/test_multi_agent_bench.py`（mock LLM 驱动 runner 全流程）。

**实现要点**
- runner 以普通调用方身份走 `SwarmManager.spawn`（origin="benchmark"），不绕过治理闸；成本经 `cost_budget` 与 usage 记账自然入账。
- 判定器单源复用：确定性任务用断言函数；rubric 任务复用 `goal_verifier.verifyGoalCompletion`（achieved/confidence/missing）。
- 指标按评测报告 §9.2 定义：任务成功率、Mean Score、不可解题识别率、协作开销（token/时延/调用次数 vs 单 agent 基线）、过程指标（派生数/验收通过率/打回率/升级数，从 `AgentRunLedger` 与事件流取数）。
- 真模型跑用 `NEUROVA_BENCH_LIVE=1` 门控，默认 CI 只跑 mock。

**红灯**：`test_multi_agent_bench.py` 先行——断言"注册一个假任务集后 runner 能产出含成功率与开销字段的报告"，当前无该模块必红。
**绿灯验收**：mock LLM 下 runner 出具 3 任务 × 2 配置（solo/swarm）报告，字段齐全；`pytest tests/unit/benchmark/` 全绿。
**产出物**：首个基线报告 `docs/05-reports/multi-agent-bench-baseline-2026-11-xx.md`（真模型，手动门）。

---

## P1-1 结构化任务单元（G-2）

**动机**：spawn 的 task 是自由文本（仅 MAX_TASK_CHARS=8000 硬限，swarm.py:289），SubAgentRun 无预期产物/所有权/输入字段——验收、评审、依赖门都无处挂靠。AutoSwarm 论文消融"去贡献规格"−4.27 分。**参照 MAP**：multi-agent-practice `core/schema.py` 的 `HandoffPacket`/`HandoffReceipt`（类型化交接包 + ACCEPTED/REJECTED/REVISE_REQUIRED 三态回执）与 `TaskNode`（`depends_on` 依赖字段）——证明结构化交接只需一个 Pydantic 模型的成本。

**改动文件**：`neurova/agent/swarm.py`、`neurova/builtin_tools.py`（spawn_subagent schema）、`neurova/tool_executor.py`（`_execute_spawn_subagent`）、`tests/unit/agent/test_swarm_manager.py`。

**实现要点**
- 新增 `TaskUnit` dataclass（camelCase 字段）：`goal`（必需）、`expectedResult`、`acceptanceCriteria: list[str]`、`requiredInputs: list[str]`、`artifactOwnership`、`dependencies: list[str]`（subagent_id）、`reviewMode: none|supervisor`。
- `spawn()` 新增可选 `task_unit: dict|TaskUnit`；自由文本 `task` 继续可用（向后兼容）——两者都缺才拒绝；`task_unit.goal` 缺省时回退 `task` 文本。
- `SubAgentRun` 增加 `task_unit` 字段并落 `to_dict()`；member 任务上下文注入时把结构化字段渲染为任务书（goal/expected/acceptance/inputs 分节），取代纯文本拼接。
- `spawn_subagent` 工具 schema 增加同名可选参数（LLM 可逐步采用；提示词层面鼓励填写 acceptanceCriteria）。

**红灯**：`test_swarm_manager.py` 新增用例——"spawn 携带 task_unit 时 SubAgentRun.task_unit 保留结构化字段且 member 任务上下文含验收条目"；当前必红。
**绿灯验收**：上述用例绿；自由文本路径行为不变（既有 12 个 spawn 用例不红）；`to_dict()` 含 task_unit 摘要。

---

## P1-2 子代理终态验收门（G-3，本方案最高收益项）

**动机**：子代理 `completed` 目前 = "原生回合结束"（swarm.py:1027-1044 收尾逻辑），不是"验收通过"。goal_verifier 已存在但只挂单 agent loop 出口（loops/base.py:118）。论文消融：监督评审/验收机制合计贡献约 +17 分；错误级联（未验证结果被下游采用）是论文点名的第一失败模式。**参照 MAP**：multi-agent-practice `core/resilience.py` `SelfHealingRetry.retry_with_feedback`——机检失败把错误文本回传给 LLM 纠错再生成（上限 3 次），是"验收不通过带 missing 回炉"的同构先例；`agent/fact_checker_agent.py` 示范了"独立上下文审计 + 结论写回共享状态"。

**改动文件**：`neurova/agent/swarm.py`、`neurova/agent/goal_verifier.py`（如需适配任务单元输入）、`neurova/agent/tool_coordinator.py`（超时表）、`tests/unit/agent/test_swarm_acceptance_gate.py`（新）、`tests/unit/agent/test_swarm_manager.py`。

**实现要点**
- `SwarmManager._execute` 收尾处、置 completed 之前插入**验收门**：若 run 带 `acceptanceCriteria`（或全局开关 `NEUROVA_SWARM_ACCEPTANCE=on` 对所有蜂群任务生效，默认 off 灰度），调用 `verifyGoalCompletion`（禁工具子会话，与 loop 出口同一单源）判定。
- **不通过** → 不置 completed：把 `verdict.missing`（逐条缺什么）作为修正指令，经 `resumeFinishedRun` 同通道续跑一次（复用 member 会话，上一段 report 作衔接上下文——该机制已存在 swarm.py:574，**不新建续跑管线**）；续跑后再次验收，仍不过则置 failed（cause=acceptance_failed）并在 report 附 verdict。
- 验收结论（achieved/confidence/missing）写入 `AgentRunLedger` subagent 行 + 终态邮箱信封，供主 Agent 与依赖门（P1-4）消费。
- 预算纪律：验收调用计入 `cost_budget`；每 run 最多 1 次自动回炉（上限常量，防 judge-续跑死循环）。
- 判定子会话沿用 goal_verifier 的"禁工具、强制 JSON、解析失败如实返回"纪律；judge 不可用（LLM 故障）时**诚实降级**：run 照常 completed 但信封标注 `acceptance: {skipped: reason}`，不静默放行也不阻塞。

**红灯**：新文件 `test_swarm_acceptance_gate.py`——(a) 带验收条件且 judge 判未达成的 run，终态不是 completed 而是"自动续跑一次后依结果定态"；(b) verdict.missing 出现在续跑任务文本中；(c) judge 连续两次不通过 → failed(acceptance_failed)。mock judge 可控红绿。
**绿灯验收**：三用例全绿；不带验收条件的存量路径行为不变（既有蜂群测试不红）；台账出现 acceptance 字段。
**live-verify**：本地 9527 起后端，构造一个必然首答不全的任务（如"列出仓库 tests/unit/agent 下文件名并核对数量"带数量验收条件），观察续跑与终态信封（命令+输出进提交说明）。

---

## P1-3 监督评审相位（G-5）

**动机**：论文消融最大单项（−12.82）来自去掉"集成前监督评审"。Neurova 的 `review.py` rubric 子会话已存在但只服务 `/review` 命令；蜂群结果无评审相位。**参照 MAP**：multi-agent-practice `CrossValidator.verify_consistency`——用 `REASONING_MODEL_NAME` 第二异构模型独立上下文核验，可作本相位的可选形态；但其"解析失败默认放行"（resilience.py:97）违反本仓诚实纪律，**不可借鉴**（本仓 goal_verifier/review 均如实返回 parse_ok=False）。

**改动文件**：`neurova/agent/swarm.py`（SUBAGENT_STATUSES 扩展）、`neurova/agent/review.py`（适配任意产出物评审目标）、`tests/unit/agent/test_swarm_review_phase.py`（新）。

**实现要点**
- `SUBAGENT_STATUSES` 增加 `in_review`（swarm.py:85 常量组扩展，**全仓唯一取值出处不变**）；`SUBAGENT_ACTIVE_STATUSES` 纳入 in_review（占派生槽）。
- 验收门通过后（P1-2），若 run.task_unit.reviewMode=supervisor（或全局灰度开关 `NEUROVA_SWARM_REVIEW=on`）：run → in_review，用 review.py rubric 子会话对 report 做结构化评审（P0-P3 findings + overall_correctness）。
- 评审通过 → completed（信封附评审摘要）；不通过 → findings 作为修正指令走与 P1-2 相同的续跑通道（计一次回炉额度，与验收共享上限），run 回 pending。
- 评审失败（LLM 故障）诚实降级：标注 `review: {skipped: reason}` 直接 completed，不静默。
- 评审结论全部落台账与信封——**只写不读的评审不产生价值**（论文教训），故信封/台账/前端小窗三处都可读。

**红灯**：`test_swarm_review_phase.py`——(a) reviewMode=supervisor 的 run 在验收后进入 in_review 且派生槽仍占用；(b) 评审不通过 → findings 进续跑任务文本且 run 回 pending；(c) 评审通过 → completed 且信封含评审摘要；(d) 评审异常 → completed + review.skipped。
**绿灯验收**：四用例绿；默认关闭时存量行为不变。
**风险与回滚**：开关默认 off；in_review 是新增态，消费方（前端小窗状态色、`subagent_status` 工具、台账）需同步认识该态——全命中点 grep `SUBAGENT_STATUSES` 一并处理（教义第 5 条）。

---

## P1-4 蜂群依赖门控（G-4）

**动机**：spawn 无 dependencies 参数（swarm.py:314-330 亲验），"未验收前置结果被下游采用"无机制防护。论文 η 门：η_t(g)=∧a_t(h)，失败/取消单元的产出永不作为合格输入。

**改动文件**：`neurova/agent/swarm.py`、`neurova/builtin_tools.py`（spawn_subagent schema）、`tests/unit/agent/test_swarm_dependency_gate.py`（新）。

**实现要点**
- `spawn()`/`spawn_subagent` 新增可选 `dependencies: list[str]`（subagent_id 列表）。
- 派生时校验：依赖 id 必须是同发起者下已知 run（不存在→结构化拒绝 `dependency_unknown`；依赖环→`dependency_cycle`，沿 resumed_from 链与依赖边做 DFS 判环）。
- 未满足依赖的 spawn 请求进入**待放行队列**（不占 MAX_ACTIVE_CHILDREN 槽——槽语义是"运行中"）；每当某依赖 run 达到"验收通过终态"（P1-2 后的 completed）时释放；**依赖 failed/cancelled → 依赖它的任务直接 failed（cause=dependency_failed），其 report 里的产出不回流发起者上下文池**（对齐"终态关闭≠合格输入"）。
- 前沿并发：队列释放用现有 `asyncio.create_task` 路径，天然并行；等待中的任务对 `subagent_status` 可见（status=blocked，新增只读态，不占槽）。
- 无 P1-2 时（灰度关闭），"验收通过"退化为"completed"——门控仍有效，只是判据弱化，两档共存。

**红灯**：`test_swarm_dependency_gate.py`——(a) 依赖未完成时任务处于 blocked 且不执行；(b) 依赖 completed 后自动放行执行；(c) 依赖 failed → 下游直接 failed(dependency_failed) 且不归档池；(d) 环依赖被拒。
**绿灯验收**：四用例绿；无依赖的存量 spawn 行为不变。
**坑位预判**：释放时机在 `_execute` 的 finally/收尾路径内，注意不可在锁内 await 长操作（沿用 dispatch.lock 既有纪律，swarm.py:451-470 原子复核模式）。

---

## P2 批（可靠性与卫生，可按需拆批）

**P2-1 蜂群 run 状态持久化（G-7）**：`SwarmManager._runs` 的状态迁移同步写 `AgentRunLedger`/`agent_run_store`（已有 SQLite 底座）；启动时扫描未闭合台账行标 interrupted（诚实暴露而非假装没发生）；member 会话 json 已持久，恢复对话内容不重造。**参照 MAP**：multi-agent-practice `EvidenceBoard.save_checkpoint/load_checkpoint`（快照语义参照，本仓以 SQLite 实现更强形态）。红灯：重启模拟（重建 SwarmManager）后 blocked/running 任务可被正确标记与查询。
**P2-2 外部 agent 注册持久化（G-9）**：`agent_communication_api.py` 的 `_handshakes/_external_agents` 落 SQLite 表（迁移注册进 `core/db_migration.py`，PRAGMA user_version）；接口行为不变。红灯：进程重建后注册仍在。
**P2-3 死码与双实现清偿（G-10，按教义第 6/7 条与协作红线断点条款）**：
- `subagent.py` SubAgentManager vs `swarm.py`：对比结论（评测报告 §6）——生产面仅 `Agent.spawn_subagent` 委托 SubAgentManager；**取 SwarmManager 为唯一实现**，把 SubAgentManager 不可替代的用法（若有）并入，退役 subagent.py 及其专属测试（先 grep 全部消费方再动）。
- CAPABILITY_QUERY 等 6 类零消费消息：与 `tool_layers/capability_graph.py` 接线（agent 注册时发布能力）**或**删除枚举值——拍板后二选一，不留占位。
- `neurova/crdt/`：零生产消费。若协同编辑无排期，按教义第 6 条退役（移除包+测试）；若保留，必须给出接线计划与消费者。
- `collaborate/workflow/scheduler.py` 旧调度器：与新 `agent/scheduler.py` 先比后合，弱者退役。
**P2-4 集成协议（G-6）**：SwarmManager 提供 integration summary 结构（各子贡献验收状态 + 结论冲突点），主 Agent 工具面可查（`swarm_integration_report` 或并入 subagent_status 聚合视图）；**验收未通过的贡献不得进入集成清单**（机制强制，不靠提示词）。
**P2-5 升级处置闭环（G-8）**：escalate 信封增加 `suggested_action`（clarify/reassign/revise_dependency），主 Agent 可用 `spawn`/`continue_subagent`/取消结构化响应；处置结果回写台账。

---

## P3 批（产品化增强，已执行 2026-11-17 第二批，见执行记录）

- **P3-1 跨 agent 审批链（G-11）**：参照 AutoSwarm approvals.py 状态机（request/decision/resolution 三文件 + 幂等 + `--by user` 只许转达真实答案）与 multi-agent-practice `TwoManRuleGate` 的 L0/L1/L2 危险分级（L2 不可逆强制人工，interactive/auto_approve 双模式），为子代理运行中权限请求建"代理给父/用户"通道；与 skill_pool 审批流、权限域收窄整合，不建第二套审批。
- **P3-2 蜂群 span 级 trace（G-12）**：trace_id 贯穿 spawn→member 会话→回流全程，接 OTel bridge；台账行与 span 关联。
- **P3-3 APEX 式 T3 任务集扩充**：财务/分析量规任务扩到 10+，接入 effort_inference 变量报告。
- **P3-4 子代理数据面围栏（G-13，二次补充）**：参照 multi-agent-practice `ContextFirewall`（`<<<UNTRUSTED_EXTERNAL_DATA>>>` 物理槽位 + 注入特征正则探测）与 `HandoffPacket` 三槽位（trusted_instructions / structured_payload / untrusted_payload）：spawn 任务书渲染时把外部检索类内容隔离进显式不可信槽位段，并对任务文本做注入特征扫描（命中只标记与告警，不静默改写、不阻断主链路——与本仓"发现而不裁决"哲学一致）。与既有 E2 工具面收窄（`computeSubagentToolAllowlist`）互补：那边管"能用什么工具"，这边管"数据以什么身份进上下文"。

---

## 批次依赖与拍板点

> **四项已裁（2026-11-17，用户交互拍板），进入无人值守执行**：
> 1. **验收门启用策略**＝做成**系统设置项**（用户可在**前端 UI 设置面板**自由开关；后端持久化 + API 读写；默认关，env `NEUROVA_SWARM_ACCEPTANCE` 保留为部署级覆盖；带 acceptanceCriteria 的任务仍可单独生效）；
> 2. **P2-3 清偿范围**＝四项全做：CAPABILITY_* 接线 capability_graph、CRDT 模块退役、SubAgentManager 并入 SwarmManager、旧调度器（collaborate/workflow/scheduler.py）退役；
> 3. **P1-3 评审形态**＝rubric 子会话（复用 review.py 单源，不引入异构第二模型）；
> 4. **提交策略**＝每批完成即 `git commit --only`（逐文件点名，绝不 add -A），不推远端。

| 拍板点 | 选项 | 影响 |
|---|---|---|
| 验收门灰度策略 | (a) 仅带 acceptanceCriteria 的 run 生效；(b) 全局开关默认 off；(c) 默认 on | **已裁：设置项+前端 UI 开关（默认关）**，(a)(c) 不采纳 |
| CAPABILITY_* 消息 | 接线 capability_graph / 删除 | **已裁：接线** |
| CRDT 模块 | 退役 / 保留待接线 | **已裁：退役** |
| SubAgentManager 去留 | 并入 SwarmManager / 保留分工 | **已裁：并入** |
| 旧调度器（collaborate/workflow/scheduler.py） | 退役 / 保留 | **已裁：退役** |

**建议实施顺序**：P0-1 → P1-1 → P1-2 → P1-3 → P1-4 →（P2 按卫生巡检节奏）→ P3。P0-1 与 P1-1 可并行。
**总验收**：P1 四项全落地后，重跑 P0-1 基线（同任务集、同模型），对比指标：T1 成功率提升、不可解题识别率不降、协作开销增幅 < 验收/评审带来的 token 增量上限（在 harness 报告中直接可读）。

---

## 执行记录（2026-11-17 无人值守批次，全部已提交本地 main）

| 批 | 提交 | 内容 | 验证 |
|---|---|---|---|
| P0-1 | `c05bf9aee` | 多 agent 评测 harness（neurova/benchmark/multi_agent：任务注册表/BenchRunner 双模式/指标聚合/JSON+MD 报告 + 种子任务集） | 红：ModuleNotFoundError；绿：tests/unit/benchmark 24 passed |
| P1-1 | `02a8eee49` | TaskUnit（neurova/agent/task_unit.py）+ spawn task_unit 入参 + member 任务书拼装 + 工具 schema/透传 | 红：stash 后 collection error；绿：37 passed |
| P1-2 | `43bcfb19d` | 验收门（neurova/agent/acceptance_gate.py）+ 设置项 advanced.swarm_acceptance_enabled（默认关）+ 前端设置面板开关（11 语言 i18n）+ 不达标回炉一次/诚实降级 | 红：stash 后 8 errors；绿：8 passed + agent 全目录与基线同失败集；locale-consistency 41 passed；vue-tsc 0 错 |
| P1-3 | `1cdce540f` | 监督评审相位（neurova/agent/review_gate.py）+ in_review 相位（占槽，状态域不变量保持）+ findings 回炉一次 + 前端 SubAgentPanel 纳管 in_review | 红：stash 后 7 failed；绿：67 passed；vue-tsc 0 错 |
| P1-4 | `8e2e537ae` | 依赖门控：task_unit.dependencies + DEPENDENCY_UNKNOWN/DUPLICATED/FAILED 校验 + blocked 等待（不占槽）+ 终态结算放行/判失败 | 红：stash 后 7 failed；绿：7 passed + agent 全目录与基线同失败集 |
| P2-3a | `6312384c7` | CRDT 退役（零消费证实）+ SubAgentManager 并入退役（subagent.py/Agent.spawn_subagent 死方法/两个专属测试同批退役） | refactor 免红绿；agent 全目录回归同基线 |
| P2-3b | `450fceff1` | CAPABILITY_* 接线：注册即发布能力 + CAPABILITY_QUERY 中枢直答 CAPABILITY_RESPONSE + COLLABORATION_INVITE 显式拒绝 | 红：stash 后 6 failed；绿：33 passed |
| P2-1 | `b227b3585` | 子任务 run 启动收敛钉子（机制已现役：agent_runs 表 + reconcile_at_startup；崩溃遗留 running→failed(process_died) 且可溯源） | 绿：2 passed |
| P2-2 | `ef69c0982` | 外部 Agent 握手/注册持久化（JSON 原子落盘 data/external_agents_state.json，启动恢复，损坏按空态起步） | 红：用例先行必红；绿：4 passed |
| P2-4/5 | `c72d3fb35` | integrationReport 集成核对面（subagent_status view=integration）+ escalate 带 suggested_action/action_note 闭环 + to_dict 补 escalation/submitted_result 投影 | 红：stash 后 8 failed；绿：8 passed + 蜂群七套件 67 passed |
| P3-1 | `6273c9f45` | 跨 agent 审批链（neurova/agent/approval_chain.py）：L0/L1/L2 分级（声明只升不降，危险命令检测强制升档）、L2 任何模式强制人工、interactive/auto_approve 双模式（NEUROVA_SWARM_APPROVAL_MODE）；request_approval / decide_subagent_approval 双工具，member 面剔除裁决权；审批单只落既有 ApprovalManager（不建第二套），等待/唤醒复用 approval_relay；run.approvals 进 to_dict | 红：ModuleNotFoundError；绿：18 passed |
| P3-3 | `21c266a14` | APEX 式 T3 任务集扩到 11 条（DCF/可比/并购/授信/LBO/财报/IPO/尽调/董事会备忘录 + 不可解题）+ effort_inference 变量报告（逐任务 effort/effort_source + by_effort 分档聚合 + Markdown 档位节）+ registerBuiltinSuites 幂等收口（修掉 registerSeedTasks 零调用方断点，死入口同批退役） | 红：collection error；绿：tests/unit/benchmark 50 passed |
| P3-2/4 | `6a9e054ff` | **P3-2 span 级 trace**：spawn 捕获 parent_trace_id + member 经 TrajectoryRecorder 开轨迹/swarm_member_run span（挂根成树，OTel bridge 既有 observer 投影）+ agent_runs v4 迁移列 trace_id（台账行↔span 关联）+ 事件/信封带 trace_id + NEUROVA_SWARM_TRACE 开关（fail-open）。**P3-4 数据面围栏**（neurova/agent/context_firewall.py）：中英文注入特征扫描 + untrustedPayload 不可信槽位（警示前缀+BEGIN/END 物理标记，原文不改写）+ spawn 命中只标记（run.data_fence）与告警、不阻断。**审批邮箱写点收口**（P3-1 回归修复）：SwarmManager.pushParentMail 唯一写点收拢五处邮箱投递 | 红：span trace 8 failed + firewall collection error + 邮箱单源钉子多出引用面；绿：8+15+12 passed；core 串行 22 失败与基线一致；agent+collaboration+benchmark 终跑 35 failed=基线、2527 passed |

**P3 批终验（2026-11-17 第二批）**：tests/unit/core 串行 A/B——22 条预存失败与基线**逐条一致（零新增）**；首跑曾现 1 条全仓 AST 扫描档（test_theTakeoverTableMatchesTheSharedEntry）失败，经单跑（31s 通过）与串行复跑证实为两套件并行争抢 CPU 的超时假红，非回归。tests/unit/agent+collaboration+benchmark 终跑 35 failed 与基线一致、2527 passed（+67 全为本轮与并行批次新用例）。期间终验抓到并当场修复 1 条 P3-1 回归：审批信封直连邮箱撞"邮箱写点单源"钉子（testOnlySwarmWritesParentMailbox），按教义第 5/6 条收口为 `SwarmManager.pushParentMail` 唯一写点（swarm 内五处投递同批收拢）。P3-1..P3-4 至此全部落地，本方案 P0–P3 四批闭环。

**终验（A/B）**：tests/unit/agent + collaboration + benchmark 全量三连跑——基线 35 条预存失败与终跑**逐条一致（零新增）**，通过数 2395→2460（+65 全为本轮新用例）。
**live-verify**：真后端起 9541（`/v1/providers` 注册行在位；5 条 ERROR 均为环境内 MCP filesystem 不可达重连噪声，与本轮无关）；签发管理员令牌走真实设置链：GET 默认 False → 管理员 PUT True → 后端 `acceptanceEnabled()` 读数 True → 恢复 False；普通用户 PUT 被 403 拒——设置面板保存链、后端判据读数、越权面全部符合预期。

**偏差记录（1 项，已结案）**：P2-3 之"旧调度器退役"经专项实测**改为双轨保留结案**。过程：先做了门面迁移实验（把 `collaborate/workflow/scheduler.py` 重写为 TaskScheduler 的兼容门面），实测撞上 §6-312 乙案常驻钉子 6 处失败——旧契约被逐字段钉住：`ScheduledTask` 全字段经真落盘—重载等值（含 status/last_result/last_error，存储为 list-of-dict 形状）、抛异常 handler 的 failed+last_error+run_count+task_started/task_failed 事件面、`_check_and_execute_tasks` 真入口、schedule_task 工具的属主校验与 bootstrap 语义。这些钉子正是为瘦身迁移设的关卡；强行迁移需改写钉子并承担在役 agent cron 功能回归风险。**结论：旧调度器（Agent 自建 cron：一次性定时/暂停恢复/画布与技能动作/通知桥，7+ 消费位点）与新 TaskScheduler（平台 /v1/tasks 自动化 API：重试/依赖/webhook/script）是"定时执行"下的两个不同产品面，非同功能重复**——门面实验已完整回退（`git checkout` 还原两个 scheduler.py），回退后 14/14 钉子绿、agent+collaboration 失败集与基线逐条一致。若未来要统一，应作为独立立项（更新 §6-312 钉子 + AutomationTask 承载旧字段 + 消费方逐点迁移），不作为卫生清偿顺手做。
