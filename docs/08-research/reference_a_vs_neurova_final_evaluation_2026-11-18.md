# CoworkOS vs Neurova 多 Agent 协作对照评测·终评（2026-11-18）

> 参照系：CoworkOS（arXiv:2611.03178，RUC-NLPIR，克隆件 `~/.zcode/tmp/coworkos-src` @ baf03c3）95/110。
> 被评方：Neurova 本仓**当前代码态**（S1–S18 超越方案全批 + 前端适配缺口收口 + 1F 真模型复跑全部落地后）。
> 本报告是**独立终评**，不是对 [coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md](coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md) 的原地修改；维度体系与锚点与其完全同框，历轮分数可直接对比。上轮过程性评分细节（含 CoworkOS 侧逐维证据）见该报告 §4/§6，本报告不重复。

---

## 1. 摘要（结论先行）

**总分：Neurova 101/110（91.8%），CoworkOS 参照系 95/110（86.4%）——超越成立。** 七维全部 ≥ 参照系：A 协作形成（16 vs 13）、B 执行协调（24 vs 22）、C 通信（14 vs 14，持平）、D 记忆共享（14 vs 14，追平）、E 治理安全（14 vs 11）、F 观测评测（10 vs 10，追平）、G 异构互操作（9 vs 9，追平）。对 CoworkOS 领先 6 分，超过判定线 ≥96 达 5 分。

四轮座次走势（同一七维廿二子项体系、同一锚点）：

| 轮次 | Neurova | CoworkOS | AutoSwarm | deepagents | 说明 |
|---|---|---|---|---|---|
| 第 1 轮（2026-11-17 P3 前） | 70 | — | 84 | — | [autoswarm 对照](reference_b_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md) |
| 第 2 轮（2026-11-17 P3 后） | 84 | 95 | 84 | 81 | [coworkos 对照](coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)；deepagents 见 [deepagents 对照](deepagents_vs_neurova_evaluation_2026-11-17.md) |
| 第 3 轮（2026-11-18 S14 重评） | 98 | 95 | 84 | 81 | S1–S13 + H 系落地，首次越过判定线 ≥96 |
| 第 4 轮（2026-11-18 S15–S18 + 1F，**本终评**） | **101** | 95 | 84 | 81 | D/G 追平、F2 实证闭环，七维全部 ≥ 参照系 |

> QwenPaw 对照（阿里个人 AI 助理）采用**不同框架**（标准 harness 十维：QwenPaw 81.5 vs Neurova 80.5，见 [qwenpaw_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md](qwenpaw_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md)），与本文七维框不可换算，仅作附注、不计入本框座次。

一句话结论：Neurova 用 S1–S18 二十个批次把第 2 轮落后的 11 分逐项补齐并反超——领先项从第 2 轮的 1 维（E）扩大到 3 维（A/B/E），其余四维全部追平；唯一遗留缺项是 A1 角色贡献辩护机制（参照系亦无，非超越必需）。

---

## 2. 评分方法与锚点（体系不变，保证四轮可比）

- **维度体系**：七维 A–G、廿二子项（A 协作形成 4 项 / B 执行协调 5 项 / C 通信 3 项 / D 记忆共享 3 项 / E 治理安全 3 项 / F 观测评测 2 项 / G 异构互操作 2 项），每子项 0–5 分，满分 110。
- **锚点**：0=无实现；1=骨架/占位无消费方；2=部分实现仅靠自觉；3=机制化覆盖主链路有明显边界；4=机制化+测试守卫+治理完备；5=机制化+测试+治理+实证闭环。
- **超越判定线**：≥96（对 CoworkOS 95 形成领先）。
- **本终评证据纪律**：上轮（第 3 轮）已核实的证据可沿用，但本轮对**全部 13 个 5 分子项 + 6 个 4 分子项共 19 项**做了现场复核（`sed` 逐处读 `file:line`，引证 commit 号经 `git log` 逐一核验存在）；其余 3 个 4 分子项（C2/D1/G1）所在域在 S1–S18 与收口批中未被触碰，沿用上轮证据。发现行号自然漂移（后续提交所致）已按当前读数更新；**未发现上轮虚高或漏评，22 项分数逐项维持**。

---

## 3. 逐维逐子项评分表（22 项全表，证据为 2026-11-18 现场读数）

> 表中 file:line 均为本轮现场 `sed` 读数；「测试/实测」列给出守卫测试或 live-verify 证据。变动列相对第 3 轮（S14 重评 98）。

### A. 协作形成（16/20，持平第 3 轮）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| A1 团队组成与角色分配 | 4 | 名册选人：职责拼装进任务书角色段 `swarm.py:420`（上限 `TEAM_DUTY_PROMPT_MAX_CHARS=2000`，`swarm.py:131`）；`list_teams`/`dispatch_team`/`propose_team` 三工具 `builtin_tools.py:1284/1294/1332`；临时团队沉淀唯一写点 `createAgentProposedTeam` `teams_api.py:165`（origin/approved_by/promoted_from_run） | spawn 按名册逐成员派活；成员工具面经声明集+执行咽喉双保险剔除（`tool_executor.py:1564-1569`）；前端 TeamPage 来源标 | `test_team_dispatch.py` 17 用例；live-verify 9641/9651。**不给 5**：角色贡献辩护机制仍缺（参照系亦无） |
| A2 任务单元结构化 | 4 | `TaskUnit` 七字段 `task_unit.py:22`（goal/expectedResult/acceptanceCriteria/requiredInputs/artifactOwnership/reviewMode/dependencies） | spawn 校验、任务书拼装、S4 候选 artifactKeys 取自 artifactOwnership | 上轮已核验，结构未变 |
| A3 验收条件 | 4 | `runAcceptanceLoop` 挂 member 终态前（`swarm.py:42` 装配 `acceptance_gate`），不达标带 missing 回炉一次；设置项默认关+前端开关 | 蜂群终态判定链；S4 候选 reviseRequired 复用同一判定 | 上轮已核验，机制未变 |
| A4 依赖与评审关系 | 4 | 依赖声明校验 `DEPENDENCY_UNKNOWN/DUPLICATED/FAILED`（`swarm.py:682-696`）+ `in_review` 评审相位占槽 | `_settleDependencies`（`swarm.py:1414`）终态结算放行 | 上轮已核验，机制未变 |

### B. 执行协调（24/25，持平第 3 轮）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| B1 共享执行状态 | 5 | `RUN_STATUS_TRANSITIONS` 全量出边表 `swarm.py:147` + `transitionRun` 唯一收口 `swarm.py:160`（非法迁移抛 `IllegalRunStatusTransition` `swarm.py:156`）+ `replayRunTailStatus` `swarm.py:196` / `reconcileRunFromEvents` `swarm.py:1096` 启动重放校正 + 台账 SQLite v5（`agent_run_store.py:138`，project_id/team_id 列） | swarm 7 处 + review_gate 6 处赋值点全部改道经 transitionRun；每次迁移落 `status_changed` 入事件账本 | `test_run_status_transitions.py`（非法迁移钉红、合法链落账钉绿）；live-verify 9631 迁移序列与账本逐条对上 |
| B2 单元生命周期 | 5 | 迁移表强校验（不静默不吞）+ H-2 机械完成闸门 `pendingBackgroundForSession` `swarm.py:1124`（后台未清完成声明不得静默通过、等待事实并入出口正文且不续跑模型防忙等） | 主出口完成判定；in_review 占槽评审相位 | live-verify 9631；H-2 提交 `052abda7d` |
| B3 依赖门控与前沿并行 | 4 | 依赖门控（`swarm.py:682-696`）+ blocked 不占槽 + `_settleDependencies` `swarm.py:1414` 结算放行 | spawn 前置校验、终态结算 | 上轮已核验；CoworkOS 至今无 η 门，本项维持领先 |
| B4 事件驱动交互与阻塞升级 | 5 | 房间回灌 `handleRoomSwarmReply`→`decideSwarmApproval`（`collaboration_room_api.py:147-149,216-220`，L2 判定限群主/admin、普通成员只记议见、重启从房间历史补建 pending 索引）+ 父侧叫停 `cancelRun` `swarm.py:1526` + 运行中改需求 `updateSubagent` steer 注入 `swarm.py:1604` + H-1 邮箱两阶段确认 | 房间审批/升级/候选事件→人在环闭环；escalate 建议动作；卡死看门狗 | `test_swarm_room_integration.py` 14 用例；live-verify 9641 群主回复→桥接匹配→判定成功→裁决卡上墙 |
| B5 结果集成 | 5 | `CandidateMergeBoard` `candidate_merge.py:105` + CAS 合入 `mergeCandidate` `candidate_merge.py:182`（baseRevision≠revision 判冲突、绝不静默覆盖、已合入不重复受理）+ 回流先落候选不直传定案 + `integrationReport` `swarm.py:1154` 增 revision/candidates/conflicts | member 终态→候选板→审批分级→合入上墙；房间拦截/采纳端点判定权在候选板单源 | `test_candidate_merge.py` 19 用例；live-verify 9651 候选两次 CAS 合并上墙；1F v2 复跑实测 CAS 合入经审批链 L0 触发 |

### C. 通信基础设施（14/15，持平第 3 轮）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| C1 寻址/路由/邮箱 | 5 | `AgentMailbox` `mailbox.py:51`：messageId 幂等去重（`mailbox.py:83`）+ priority 三级队列、lease 按优先级降序同级时间升序（`mailbox.py:101,113`）+ leased 超时死主回收回 ready（`mailbox.py:22-24`，回收计数进 stats） | pushParentMail 唯一写点（钉死 swarm.py+loops/base.py）；stats 快照并入 /monitor/resources→MonitorPage 邮箱健康卡 | `test_mailbox_two_phase.py`；live-verify 9641/9651 |
| C2 实时性（流式/中断） | 4 | SSE/WS 流式+广播（上轮已核，本轮域内无改动） | ChatPage/SubAgentWindowStack 实时渲染 | 上轮已核验 |
| C3 可靠性语义 | 5 | 两阶段确认 lease→逐条落盘→acknowledge（`loops/base.py:969-995`，落盘失败不 ack、下轮至少一次重投宁重不丢）+ 消费侧幂等窗口（`loops/base.py:102`，重投件携同一 messageId 只补确认不重复进上下文）+ 死主回收（`mailbox.py:22-24`） | 破坏性 drain 已退役；重投不升级成重复生效 | `test_mailbox_two_phase.py`（重复投递只达一次/未 ack 下轮重投/drain 移除） |

### D. 记忆与上下文共享（14/15，第 3 轮 13→14，S16 后追平）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| D1 跨 agent 上下文共享 | 4 | 三通道回流+member 会话持久（上轮已核）+ room 作用域黑板（S9，`chat_scope=room:<id>`） | 蜂群结果回流父会话；房间共享黑板 | 上轮已核验 |
| D2 共享黑板/工作记忆 | 5 | 记忆重纪律 `memory_discipline.py`：3-Task 候选转正（`MEMORY_PROMOTION_MIN_TASKS=3` `:49`，任务键单源 task_id>run_id>session_id）+ 世代失效（`judgeClauseConflict` 全仓唯一确定性冲突判据 `:226,245`，旧代 `status=superseded` 可追溯不物理删 `:59,220-257`）+ 人工审阅接通（`screenMemoryContent` `memory_admission.py:174` 接 pending propose/confirm）+ S7 敏感拦截（`SENSITIVE_KEY_PATTERNS` `memory_admission.py:111`，`installMemoryAdmission` 单点接线 `mem_core.py:39,484`） | MemCore 写入闸；`NEUROVA_MEMORY_DISCIPLINE` 门控（关闭态行为与现状一致由专测锁定）；lineage 统一读取口与端点（`c75c307e0`） | 22 用例红→绿；live-verify 9673：候选→3 任务→转正、矛盾→失效（旧代退出召回）全程实测 |
| D3 历史压缩与成本 | 5 | S5 会话追加式 JSONL+快照两段式（`session_manager.py:40-53`，撕裂封口/坏行跳过/懒迁移）+ S6 四件：`CONTEXT_COMPACT_TRIGGER_RATIO=0.85`（`context_pool.py:48`）+ 溢出兜底重试 + `assertCompactionShrinks` 严格变小守卫（`context_pool.py:121`）+ `CompressionEvent` 落时间线原消息永不删（`context_pool.py:69`）+ 工具结果有界投影；S15 补齐：失败递增冷却 `COMPACTION_FAILURE_COOLDOWN_STEPS=(5,15,30)`（`context_pool.py:169`，状态机随会话持久重启不丢）+ 子代理软目标 `SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS=20000`（`swarm.py:108`） | ChatPage 认领 context_compacted / context_compact_cooldown 轻提示；/context/stats 恒带 compression 参数读面（`context.py:431-495`，设置页零常量） | `test_context_compact_discipline.py` 19 用例 + `test_session_store_append_only.py`；live-verify 9632/9671（压缩失败进冷却实测） |

### E. 治理与安全（14/15，持平第 3 轮）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| E1 权限/审批（人在环） | 5 | 审批链 L0/L1/L2（`approval_chain.py`）+ S8 审计持久化：请求/决定成对落审计单源（`APPROVAL_AUDIT_RESOURCE`/`APPROVAL_REQUEST_ACTION`/`APPROVAL_DECIDE_ACTION` `approval_chain.py:139-141`，写点 `:227`）+ `GET /v1/audit/approvals?run_id=` 成对轨迹查询（`audit.py:278`，admin 门）+ 房间裁决记 decided_by_channel | AuditPage 成对查询面板（`e1944819f`）；审批投递 priority=high | `test_approval_audit_persistence.py` 9 用例 + 审批链既有 18 例；live-verify 9641（房间裁决）/9663（按 resource_id 查台账） |
| E2 工具面收窄 | 4 | `MAIN_AGENT_ONLY_TOOLS` 声明集单源 + 执行咽喉执行期纵深防御双保险（`tool_executor.py:1564-1569`）；白名单派生期即剔除 | 成员工具面 general/explore 双路剔除；MCP 侧同样生效不可绕过 | 收尾波 2 红→61 passed（`458ae1e8d`）。**不给 5**：无 CUA 沙箱等价物 |
| E3 资源治理 | 5 | 治理三明治硬闸全部在场：`MAX_ACTIVE_CHILDREN=5`（`swarm.py:466`）+ 深度独立声明（`swarm.py:471`）+ 模型并发上限（`swarm.py:637`）+ 确定性错峰最小间隔（`swarm.py:481,647`）+ 预算闸 `_over_budget`（`swarm.py:619`）+ run 级 `runtime_budget_sec` 运行窗口（`swarm.py:362,544`） | 每次 spawn/dispatchTeam 全部照算；S10/S11/S13 新工具同闸 | live-verify 多轮（9641/9651/9663/9671/9673/9677）均在治理闸下执行 |

### F. 可观测与评测（10/10，第 3 轮 9→10，1F 复跑后追平）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| F1 台账/trace/事件 | 5 | H-4 run 级 JSONL 事件账本+causation_id 因果链（`swarm_event_log.py:35-45`，`<数据根>/swarm_runs/<id>.events.jsonl`）+ `runEvents` 读面 + view=events 端点 + SubAgentPanel 事件时间线 + S17 模型请求级归档（`core/request_archive.py`：每会话 JSONL、`redactSensitiveText` 复用 S7 单源脱敏 `:70`、`NEUROVA_REQUEST_ARCHIVE_FULL` 门控钩子 `:41`、后台单写线程不阻塞）+ S12 台账 v5 归属列与项目档案聚合 | 档案面板消费请求归档摘要（`cc59d7abb`）；脱敏纪律：正文不进账本、先脱敏后截断 | `test_project_collab_dossier.py` 10 用例；live-verify 9661 spawned→started→terminal 完整因果链+封卷留底 |
| F2 基准评测 harness | 5 | S1 评测地基：`expect_trajectory` 轨迹判据（`tasks.py:85`）+ usage 规范键集（`tasks.py:15-16,42`）+ taskIsolatedMemory 默认开 + /baseline-reports 只读端点 + N3 suite_eval 真执行器后台轮询（`48acfafb4`）+ **1F v2 真模型基线实测归档**（api.mosi.cn/nex-n2.6，26 任务 solo+swarm，token 倍数 **0.857**、swarm 更快更省 -10.3s，报告 [v2 md](multi_agent_bench_baseline_v2_2026-11-18.md)/[v2 json](multi_agent_bench_baseline_v2_2026-11-18.json)，v1 保留对照） | BenchmarkPage 报告视图；判据数据源为 harness 回传事实，判据不做模型自评 | H-7 140 次真实调用（v1）+ v2 26 任务复跑；候选制 CAS 合入经审批链 L0 实测触发 |

### G. 异构与互操作（9/10，第 3 轮 8→9，S18 后追平）

| 子项 | 分数 | 机制落点（现场读数） | 消费方 | 测试/实测 |
|---|---|---|---|---|
| G1 多模型/多 provider | 4 | 多 provider+渠道+双协议（上轮已核，本轮域内无改动） | 多模型路由/failover | 上轮已核验 |
| G2 互操作协议 | 5 | ACP+MQTT+外部 agent 握手+MCP 客户端（上轮 4 分基础）+ S18 MCP 深度集成：`mcp_surface.py` 增 team_list/team_dispatch/project_list/project_detail 四工具壳（`mcp_surface.py:60-66`），转交 `ToolExecutor.execute` 单管道——治理三明治/审批链/审计/run 溯源与主 agent 原生调用同一条路；描述与必填参数取自原生 builtin schema 同源；双鉴权照旧；成员面剔除在 MCP 侧同样生效 | 外部 MCP 客户端可发现并调用团队能力；不可绕过成员面剔除 | 11 用例红→绿；A/B 510 passed 零新增；live-verify 9677 真 MCP 握手 team_list→team_dispatch |

**维度小计**：A 16、B 24、C 14、D 14、E 14、F 10、G 9——**合计 101/110（91.8%）**。

---

## 4. 与参照系对照

### 4.1 CoworkOS 逐维对照

| 维 | Neurova（终评） | CoworkOS | 对照结论 |
|---|---|---|---|
| A 协作形成 | **16** | 13 | Neurova 领先 3：TaskUnit 结构化/验收门/依赖门控是 CoworkOS 没有的；A1 角色辩护双方皆缺 |
| B 执行协调 | **24** | 22 | Neurova 领先 2：迁移表+候选制+机械完成闸门齐平后，B3 依赖门控仍是 CoworkOS 空白 |
| C 通信基础设施 | 14 | 14 | 持平：两阶段确认/幂等/死主回收三件套对齐后同档 |
| D 记忆与上下文共享 | 14 | 14 | 追平（S15 冷却+软目标、S16 记忆重纪律落地后）：CoworkOS 准入纪律强，Neurova 记忆面更宽且纪律补齐 |
| E 治理与安全 | **14** | 11 | Neurova 领先 3：治理三明治（广度/深度/预算/冷却/错峰硬闸）仍是 CoworkOS 没有的——其并发约束完全交给 Main 自律 |
| F 可观测与评测 | 10 | 10 | 追平（S17 请求级归档 + 1F v2 复跑后）：事件溯源因果链与真模型基线双双到位 |
| G 异构与互操作 | 9 | 9 | 追平（S18 MCP 团队能力外部暴露后） |
| **合计** | **101（91.8%）** | **95（86.4%）** | **Neurova 领先 6 分** |

### 4.2 AutoSwarm / deepagents 总分

- AutoSwarm 84/110：Neurova 终评领先 17 分（第 2 轮追平时为持平）。
- deepagents 81/110：Neurova 终评领先 20 分。
- 四轮座次（七维同框）：**Neurova 101 > CoworkOS 95 > AutoSwarm 84 > deepagents 81**。

### 4.3 QwenPaw 附注（不混入本框）

QwenPaw 对照采用标准 harness 十维中立框架：QwenPaw 81.5 vs Neurova 80.5（基本打平；QP 领先工具执行/安全沙箱/HITL/生态部署，NV 领先规划/记忆/自我演化/编排/可靠性）。该框架与本文七维廿二子项体系不可换算，仅作跨框架参照，详见 [qwenpaw_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md](qwenpaw_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md)。

---

## 5. 剩余差距与下一轮候选

1. **A1 角色贡献辩护机制（唯一单件缺项）**：按任务动态论证"为什么是这些成员、各自贡献什么、事后如何辩护"。参照系（CoworkOS/AutoSwarm/deepagents）亦无此机制，非超越必需；若要做，路径是名册选人时生成结构化贡献声明 + 终态后按实际轨迹回填核销，另立小批。
2. **已清偿项备查**（第 3 轮清单 → 终评去向）：D3 压缩失败冷却+子代理软目标 → S15（`51302e080`）；D2 记忆重纪律 → S16（`3df4fa355`）；F1 请求级归档 → S17（`cf1df7e0c`）；G2 MCP 深度集成 → S18（`c3dbdaa23`）；F2 v2 真模型复跑 → 1F（报告已归档）。
3. **维持项提醒**：D2 的 `NEUROVA_MEMORY_DISCIPLINE`、S5 的 `NEUROVA_SESSION_JSONL`、S17 的 `NEUROVA_REQUEST_ARCHIVE_FULL` 门控默认关/钩子态——机制已评测计分，翻默认属产品决策，须按各自会话报告的移交建议另行拍板，不影响本终评分数。

---

## 6. 执行记录（commit 号均已 `git log` 逐一核验存在）

### 6.1 超越方案 S1–S13（第 3 轮前落地）

| 批次 | commit | 交付一句话 |
|---|---|---|
| S1 评测地基 | `a79c10ba7` | usage 回传、expect_trajectory 判据、taskIsolatedMemory 默认开、T1 材料归纳重设计、/baseline-reports 只读端点 |
| S2 邮箱语义 | `763abece7` | messageId 幂等、priority 队列、leased 超时回收、stats() 并入 /monitor/resources |
| S3 迁移表 | `73d05aa63` | RUN_STATUS_TRANSITIONS + transitionRun 唯一收口（13 赋值点改道）+ status_changed 落账 + 启动重放校正 |
| S4 候选制 | `ee6be8c2e` | CandidateMergeBoard CAS 合入、冲突双保留升级、审批分级、integrationReport 增 candidates/conflicts |
| S5 会话追加式 | `1444143c1` | JSONL+快照两段式（追加/撕裂封口/懒迁移），NEUROVA_SESSION_JSONL 门控 |
| S6 压缩纪律 | `c340f5e80` | 0.85 水位自动触发、溢出兜底、严格变小守卫、CompressionEvent 落时间线、有界投影、轨迹生产者接线 |
| S7 记忆准入 | `90a2fb84d` | 写入前敏感拦截 + 准入清单提示词 + 审计单源 |
| S8 审批审计 | `cd695139d` | 请求/决定成对落审计单源 + 按 runId 轨迹查询 + 审批邮件 priority=high |
| S9 团队/房间接入 | `79551406e` + `ebf0cb284` | 人在环房间闭环（回灌判定/群主权限/pending 补建）+ 名册选人 + room 作用域黑板 + 前端审批/候选卡片 |
| S10 固定团队开放 | `305f47c8d` | list_teams/dispatch_team/propose_team 三工具 + 沉淀 ASK 闭环 + 治理三明治照算 |
| S11 双入口 | `68e65982a` + `1eccf8aa0` | 房间直发交 SwarmManager 统一编排（零第二编排引擎）+ 事件回房间 + 终态走候选板 + 前端发起协作表单 |
| S12 项目协作档案 | `1e829d308` + `0338a5823` | run→project 归属标落台账 v5 + 五类记录聚合读面 + 封卷留底 + 前端档案面板 |
| S13 agent 工具面 | `f10f448f3` | project_create/list/detail/room_post 四工具 + 创建即建房间 + L1 ASK 治理 |

### 6.2 H 系与评测后补齐（第 3 轮计入）

| 项 | commit | 交付一句话 |
|---|---|---|
| H-1 邮箱两阶段确认 | `98074146b` | lease→落盘→acknowledge，破坏性 drain 退役，宁重不丢 |
| H-2 机械完成闸门 | `052abda7d` | pendingBackgroundForSession 核账+等待事实并入出口，不续跑模型防忙等 |
| H-4 事件账本（三段） | `51a2aaf92` + `3c9c14901` + `9d507ecd7` | run 级 JSONL 账本+因果链 → view=events 读侧 → SubAgentPanel 时间线前端 |
| H-4 钉子清偿 | `fd2e5937f` | view 枚举钉子随扩容同步 |
| 父侧叫停/运行中改需求 | `60ef5dd81` | cancel_subagent→cancelRun 落账；continue_subagent/updateSubagent steer 注入/restart 重派 |
| N3 评测执行器 | `48acfafb4` | suite_eval 判据注入真执行器 + 后台轮询（计入 F2） |

### 6.3 收尾波与 S14 重评（第 3 轮）

| 批次 | commit | 交付一句话 |
|---|---|---|
| 收尾波·后端（S13 移交清偿） | `458ae1e8d` + `f7f346694` + `9702d8cd9` | MAIN_AGENT_ONLY_TOOLS 并集收口单一事实源 + 房间裁决回灌项目治理 ASK + docstring 残引扫荡 |
| 收尾波·前端（附录 D 清零） | `da7a70ffd` + `19bc07376` + `d2209118c` + `e1944819f` + `7e0c3b953` | S1 报告视图 / S2 邮箱健康卡 / S6 压缩轻提示 / S8 审计面板 / S3 类型复核 |
| S14 同框重评分 | `ffd6ab779` | 逐子项重评 98/110，首次越过判定线 ≥96，超越成立 |

### 6.4 追加批 S15–S18 与收口（第 4 轮，本终评对象）

| 批次 | commit | 交付一句话 |
|---|---|---|
| S15 D3 收尾 | `51302e080` | 压缩失败递增冷却（5/15/30s 状态机随会话持久）+ 子代理软目标 20k，与 S6 机制合流不并立 |
| S16 D2 收尾 | `3df4fa355` + `c75c307e0` | 3-Task 候选转正/世代失效/人工审阅接通（零 schema 变更，字段落 metadata.memoryDiscipline）+ lineage 统一读取口 |
| S17 F1 收尾 | `cf1df7e0c` | 模型请求级归档：每会话 JSONL + 脱敏 + 档案聚合消费闭环（独立 trace 面，不破坏 H-4 账本纪律） |
| S18 G2 收尾 | `c3dbdaa23` | MCP 四工具壳 team_list/team_dispatch/project_list/project_detail，转交 ToolExecutor.execute 单管道零旁路 |
| 追加批收口 | `ed43a3b29` + `e182c0eba` | 身份读方台账两笔同步（memory_discipline/request_archive 新合法读点）；四道门核验零新增失败 |
| 前端适配缺口收口 | `82ce60a6c` + `838868187` + `cc59d7abb` | 压缩参数读面+设置页只读卡片 / 冷却轻提示 / 请求归档摘要进档案面板；vitest 2665 全绿 + vue-tsc 0 错 |
| 缺口收口执行记录 | `e5e3607b6` | 方案文档执行记录补记 |
| 1F 真模型复跑 | 随二次重评文档提交（报告 [v2 md](multi_agent_bench_baseline_v2_2026-11-18.md)/[v2 json](multi_agent_bench_baseline_v2_2026-11-18.json)） | 26 任务 solo+swarm 真装配链驱动，token 倍数 0.857，F2 4→5 |

---

## 7. 结论

1. **终评判定：Neurova 101/110（91.8%）vs CoworkOS 95/110（86.4%），超越成立且领先扩大到 6 分**；七维全部 ≥ 参照系（A/B/E 领先，C/D/F/G 追平），四轮座次 70 → 84 → 98 → 101。
2. 超越的构成是**机制面与实证面双闭环**：B1/B2/B4/B5/C1/C3/D2/D3/E1/E3/F1/G2 十二个 5 分子项全部具备"机制落点 + 消费方 + 测试守卫 + live-verify 实测"四件套；F2 的 5 分由 v2 真模型基线（26 任务、token 倍数 0.857）补齐最后一块实证。
3. 本轮 19/22 子项现场复核（含全部 5 分子项）**未发现上轮虚高或漏评**，22 项分数逐项维持；行号漂移已按当前读数更新。评分纪律（宁可少评不可虚高）全程执行：A1 维持 4（缺角色辩护，双方皆无）、E2 维持 4（无 CUA 沙箱等价物）、A2/A3/A4/B3/C2/D1/G1 维持 4（锚点未变）。
4. 唯一遗留单件缺项为 A1 角色贡献辩护机制（参照系亦无）；D2/S5/S17 三处门控默认态的翻转为产品决策，另行拍板，不影响本判定。
5. 方法边界（诚实声明）：本评测仍是**静态代码级机制评测 + 真模型基线参照**，不构成任务成功率的统计结论；CoworkOS 分数为其代码与论文报告的机制评测值。判定对口径敏感项做过敏感性核验（第 3 轮记录：F2/D3 按最严口径总分仍 96~97），本终评在 F2 已实证后不再存在口径争议点。
