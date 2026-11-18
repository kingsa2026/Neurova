# 超越 CoworkOS 实施方案（完整实施版：S1–S12）

- 日期：2026-11-17（v4 修订：附录 D 四项可选前端适配**转必改**，并把它需要的后端支撑设计进对应批次——S1 报告读面端点、S2 邮箱运维计数入系统状态读面、S6 压缩事件随会话事件流下发+参数读面暴露、S10 团队来源字段与 run/WS 载荷增 team_id。v3 曾纳入项目管理整合与 agent 发起面，v2 统一 S1–S12，初版 S1–S9）
- 依据：
  - [CoworkOS 与 Neurova 多 Agent 协作对照评测](../08-research/coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)（下称"COS 评测"；§6 逐维评分、§6.x 总分表、§7 H 系清单是本方案直接输入）
  - [deepagents 与 Neurova 对照评测](../08-research/deepagents_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)（下称"DA 评测"；其 §8「按本仓代码现状逐条对照的学习落点」是 S5/S6/S7 的规格来源）
  - 真模型基线报告 [multi_agent_bench_baseline_2026-11-17.md](../08-research/multi_agent_bench_baseline_2026-11-17.md)（S1 的输入：T1 不可用、记忆串扰、usage 缺失三条实证）
- 目标：同框评测总分从当前 **84/110** 越过 CoworkOS 的 **95/110**（判定线 ≥96），且不损失既有领先维（A 协作形成 14、E 治理安全 13）。
- 范围：`neurova/agent/`（swarm.py、mailbox.py、swarm_event_log.py、team.py、candidate_merge.py 新增、memory_admission.py 新增、loops/base.py、chat_pipeline.py、goal_verifier.py）、`neurova/builtin_tools.py`、`neurova/tool_executor.py`、`neurova/session_manager.py`、`neurova/context_pool.py`、`neurova/mem_core.py`、`neurova/collaboration/`（room_*、memory_scope）、`neurova/api/endpoints/`（teams_api.py、collaboration_room_api.py）、`neurova/benchmark/multi_agent/`、`tests/unit/`、`docs/08-research/`。
- 执行者须知：本方案按批次（S1–S14）组织，**每批独立可交付、可红绿验证、可单独提交**。开工任何一批前，先读本方案附录 A（共享避坑清单）并对目标文件做撞车复核（`git log --oneline -5 -- <file>` + `git status`）；文中所有 `file:line` 均以**开工当日现场复核为准**（行号会漂移，符号名是锚）。
- 纪律：每项先红后绿（红灯测试实证期望行为，附实测输出）；净新增 LOC 尽量为负或逐条列明去向；live-verify 真链路自证；同根因全命中点扫荡；不建第二套平行体系。

---

## 0. 总路线

### 0.1 批次总览与依赖

```
S1  评测地基（usage/轨迹判据/记忆隔离/T1 重设计）
S2  邮箱可靠性语义（幂等/优先级/死主回收）
S3  run 生命周期迁移表 + 状态事件归档 ──┐
S4  结果候选制（candidate→CAS 合入→冲突保留）─┤
S5  会话存储追加式（JSONL+快照）→ S6 压缩纪律
S7  记忆准入轻量先行
S8  审批审计持久化
S9  团队/房间能力接入蜂群（人在环回灌+群主权限/候选房间呈现/动态组队/共享黑板/AgentTeam 边界）
S10 固定团队开放（list_teams/dispatch_team/临时团队沉淀）
S11 多 agent 协作双入口（主 agent 编排发起 + 用户经项目房间直发）
S12 项目协作档案（留底+可观测：run→project 归属标签 + 聚合读面 + 收尾封卷）
S13 项目/团队/群聊的 agent 工具面（用户和 agent 都可发起项目）
S14 同框重评分与超越判定
```

依赖与并行：
- S1、S2、S7、S8 互不碰文件域，**可四会话并行**；
- S3→S4 **串行**（同在 swarm.py 状态/回流面，建议同会话连做）；S5→S6 **串行**（S6 依赖 S5 的事件落盘面）；
- S9 依赖 S4（候选房间呈现）与 S8（审批回灌）；S10 依赖 S9（团队接缝）与 S4；S11 依赖 S9/S10；
- S12 依赖 S3/S4/S8/S11（聚合既有事件面与房间发起链，不建新账本）；S13 依赖 S9/S10（房间/团队语义）并依赖 S12（档案可见）；
- S14 收尾：S1–S13 全部落地后执行。

### 0.2 涨分预算（诚实口径）

| 批次 | 对应子项（COS 评测现分） | 保守 | 满额 |
|---|---|---|---|
| 已落地未重评（H-1/H-2/H-4 三段闭环/H-7/父侧叫停改需求） | C3、B1、B4、F1、F2 | +2 | +4 |
| S1 | F2 3→5 | +1 | +2 |
| S2 | C1 4→5、C3 4→5 | +1 | +2 |
| S3 | B1 4→5、B2 4→5 | +1 | +2 |
| S4 | B5 3→5 | +1 | +2 |
| S5+S6 | D3 3→5 | +1 | +2 |
| S7 | D2 4→5 | 0 | +1 |
| S8 | E1 4→5 | +1 | +1 |
| S9 | B4 4→5（人在环房间闭环） | +1 | +1 |
| S10 | A1 2→4（名册选人+沉淀闭环） | +1 | +2 |
| S11 | A1/B4 支撑（产品入口，机制经 S9/S10 计分） | 0 | +1 |
| S12 | F1 4→5（项目留底+可观测聚合） | +1 | +1 |
| S13 | A1/E1 支撑（agent 发起面+分级治理） | 0 | +1 |
| **合计** | | **+11 → 95** | **+22 → 锚点封顶内按证据计** |

> 读法：判定线 **≥96**。保守路径（95）仍差一步——S4（B5）、S5+S6（D3）、S10（A1）必须做实方可越过；满额路径超锚点上限时按实际证据计，不硬凑。评分是每子项 0–5 锚点制，涨分必须以证据支撑（S14 给出逐子项证据清单要求）。

### 0.3 明确不做（防过度工程与违反裁定）

- 不把 `_runs` 全量搬 SQLite/不引入中心化调度常驻服务（进程内架构不变）；
- 不动 MemCore 内部结构（S7 只做写入前拦截；3-Task 候选转正另立项）；
- 不引入 LangGraph/LangChain 等图运行时（DA 评测"不学清单"）；
- 不做 MCP 深度集成与长程目标 park/恢复（G2/H-8 维持登记，另行立项；S10 的"MCP 第二阶段"仅指团队能力的外部暴露，非 G2 本体）；
- 不以削弱治理三明治/工具面收窄换"灵活性"（E 维领先是本仓资产）；
- 不新建第二套压缩/记忆/验收/编排体系（复用 context_pool、goal_verifier、review、审批链、SwarmManager 单源）；
- **不做群聊解题**（AutoSwarm 方案不做清单：论文实证去中心化讨论 39.32% < 单 agent 60.68%）——房间只做人的监督面/发起面/共享产物面。

---

## S1 评测地基补全（F2：3→5）

**动机**：H-7 真基线（140 次真实调用）暴露三处 harness 断点——token usage 未进结果、无轨迹效率判据、跨任务记忆串扰污染对照；T1 虚构来源任务对真模型不可用。没有这批，后续所有改进都无法红绿验证、也无法在 S12 重评分。

**现状**：harness 在 `neurova/benchmark/multi_agent/`（runner.py、tasks.py、metrics.py、report.py、suites/）；结果对象 `TaskOutcome` 字段以现场为准；真模型驱动方式见基线报告（临时驱动 + `NEUROVA_DATA_DIR` 隔离 + 清代理 env）。

**改动文件**：`neurova/benchmark/multi_agent/runner.py`、`tasks.py`、`metrics.py`、`report.py`、`tests/unit/benchmark/` 既有测试文件。

**实现要点**
- 1A usage 回传：`TaskOutcome` 增加 `usage` 字段（promptTokens/completionTokens/totalTokens/elapsedSeconds/steps/toolCalls）；solo 从轮次态与 loop 回传取，swarm 从台账行与 trace span 聚合取。mock 桩填 0，真模型读真实 usage。Token 倍数列（报告里现空缺）据此恢复。
- 1B 轨迹效率判据（DA 评测 I-1）：判据 DSL 增加 `expect_trajectory(maxSteps=None, maxToolCalls=None, allowedTools=None)`；数据源**优先复用 P3-2 的 span trace 与 agent_runs 台账计数**，禁止往 H-4 事件账本新增工具级事件（账本纪律：正文与高频细节不进账本）。
- 1C 记忆隔离：runner 增 `taskIsolatedMemory` 模式（每任务独立 agent 实例或独立记忆命名空间，二选一以现场结构定），正式对比默认开启；跑基线时在报告里注明是否隔离。
- 1D T1 重设计：虚构来源标记任务两条路任选其一落地——(a) 提示词内给出真实来源材料，任务改为"依据给定材料归纳"；(b) 判定翻转，"诚实说明无法引用不存在来源"计为得分行为。改 `tasks.py` T1 族任务与判据，mock 测试同步更新。
- 1E 报告读面（前端 BenchmarkPage 展示的后端支撑）：runner 报告落盘后，`neurova/api/endpoints/benchmark.py` 增**只读端点**列出/取回多 agent 基线报告（含 usage/轨迹列）；注意该文件是多会话热区，动手前撞车复核（附录 A5），新增路由同步路由快照（附录 A3）。
- 1F 真模型复跑：v2 报告产出后归档替换首版基线报告（旧版保留作对照）。

**红灯**：先写 `test_outcome_carries_usage_and_trajectory`（断言 TaskOutcome 含 usage/轨迹字段且 `expect_trajectory` 可约束超步数任务）——当前必红。
**绿灯验收**：mock LLM 下全任务集报告含 usage 与轨迹列；`pytest tests/unit/benchmark -q` 全绿；用真模型重跑一次基线产出 v2 报告（**密钥只进进程，脚本即用即删**，见附录 A11）。
**避坑**：benchmark 相关文件曾有并行会话在途改动（`neurova/api/endpoints/benchmark.py` 先例）——动手前 `git status` 复核；真模型跑必须清代理 env（附录 A12）。

---

## S2 邮箱可靠性语义补全（C1/C3：各 4→5）

**动机**：COS 评测 C3 给 CoworkOS 5 分依据是"两阶段确认+幂等 id+死主检测"三件套；H-1 已落两阶段确认（`mailbox.py:58 lease`、`:76 acknowledge`），还差幂等与死主回收两件；C1 的 5 分还含优先级队列。

**改动文件**：`neurova/agent/mailbox.py`、`neurova/agent/loops/base.py`（消费点）、`tests/unit/agent/test_mailbox_two_phase.py`。

**实现要点**
- 幂等：消息体带 `messageId`（uuid，投递点生成）；`pushParentMail` 对同 id 重复投递直接去重；`acknowledge` 对已 ack 的 id 重复调用幂等（计数不重复扣减）。
- 优先级：消息带 `priority`（normal/high/urgent，缺省 normal）；`lease` 返回按优先级降序、同级按时间升序；审批/升级类投递默认 high。
- 死主回收：现 TTL 只清 ready 态；扩展为 **leased 超时未 ack 也回收回 ready**（回收计数进运维读数），配合幂等 id 保证"宁重不丢"不升级成"重复生效"。
- 运维读数暴露（前端监控页的后端支撑）：mailbox 增加 `stats()` 快照（在途租约数/ack 计数/回收计数/优先级分布），**并入既有系统状态读面响应**（console 域 `/debug/status` 或 MonitorPage 现用端点，以现场为准；不新增路由，避免路由快照 churn），MonitorPage 据此展示邮箱健康卡。

**红灯**：`test_mailbox_two_phase.py` 增三例——重复 messageId 只生效一次；高优先级先出；leased 超 TTL 被回收且回收后可再 lease。
**绿灯验收**：上述测试全绿；trio 全量 A/B 零新增失败（附录 A1）。
**避坑**：邮箱唯一写点是 `SwarmManager.pushParentMail`（附录 A4）；TTL/优先级排序不得破坏"至少一次、宁重不丢"。

---

## S3 run 生命周期迁移表 + 状态事件归档（B1/B2：各 4→5）

**动机**：COS 的 B2 5 分来自"9 态+迁移表强校验"（非法迁移在类型层面不可能）；B1 5 分来自"全持久化+事件溯源"。本仓 6 态单源已对，但迁移合法性散在各个赋值点、状态变更没有归档轨迹。

**改动文件**：`neurova/agent/swarm.py`、`tests/unit/agent/`（swarm 既有状态测试 + 新增迁移表测试）。

**实现要点**
- 迁移表：swarm.py 模块级常量 `RUN_STATUS_TRANSITIONS: dict[str, frozenset[str]]`，枚举现役全部状态（以 `SubAgentRun.status` 现场为准）与合法迁移；新增唯一收口函数 `transitionRun(run, newStatus, cause)`，所有状态赋值点改走它，非法迁移**显式抛错**（不静默、不吞）。
- 状态事件：`transitionRun` 内调用 `swarm_event_log.appendRunEvent(subagentId, "status_changed", {"from":…, "to":…, "cause":…})`——复用 H-4 账本，**不新造第二本日志**。
- 启动收敛增强：启动时除既有台账收敛外，可从事件账本重放各 run 末态做一致性校正（账本是台账的补强事实源，不替代台账）。

**红灯**：新增 `test_run_status_transitions.py`——断言非法迁移（如 completed→running）抛错、合法迁移（running→in_review→completed）通过且每次迁移落一条 status_changed 事件。
**绿灯验收**：swarm 既有状态类测试全绿（A/B 比对）；模拟"进程重启后从账本重放"的测试通过。
**避坑**：状态枚举/字段的改动会撞两类钉子——后端 schema 钉子（`test_swarm_integration_escalation.py` 的 view/enum 断言）与前端 `SubAgentPanel.vue` 的 status 联合类型——**必须同批同步**（附录 A7）；swarm.py 动手前撞车复核（附录 A5）。

---

## S4 结果候选制（B5：3→5）

**动机**：COS 的 B5 5 分机制是"Subagent 私有 candidate → Main CAS 合入，人工可拦截，冲突保留重议"。本仓现状是报告直传即成结果、integrationReport 只做核对——缺"候选→合并"这道闸。

**改动文件**：新增 `neurova/agent/candidate_merge.py`；改 `neurova/agent/swarm.py`（结果回流点）、`neurova/agent/goal_verifier.py` 或 review 相位（拦截点，以现场为准）、对应测试。

**实现要点**
- 新增 `CandidateReport`：`candidateId`、`runId`、`content`（报告正文）、`artifactKeys`（该结果主张触碰的产物/记忆键，来自 TaskUnit.artifactOwnership）、`baseRevision`（合并基准版本）、`status`（submitted/accepted/rejected/reviseRequired）。
- member 结果回传 → 先落 candidate（submitted），**不直接定案**；既有验收门通过 → 主侧 `mergeCandidate`（CAS：候选.baseRevision 与当前 integrationReport.revision 一致才合入，不一致判冲突）；驳回 → 走既有回炉链（reviseRequired）。
- 冲突保留：两个 candidate 声明同一 artifactKey 且 baseRevision 相同 → 都保留、标记 conflict、经 escalate/审批链升级人工裁决，**绝不静默覆盖**。
- 人工可拦截：merge 动作纳入既有审批链分级（L0 自动/L1 提示/L2 必审，以 approval_chain 现场口径为准）。

**红灯**：新增 `test_candidate_merge.py`——直传结果不再直接定案（先 submitted）；CAS 冲突保留双方并升级；验收驳回走 reviseRequired。
**绿灯验收**：swarm 回流/续跑/验收门既有测试 A/B 零新增失败；integrationReport 含 candidates 与 conflicts 字段。
**避坑**：不新造第二套验收判定器（复用 goal_verifier/review，附录 A14）；integrationReport 字段变化会撞契约断言——同批更新；本批与 S3 同在 swarm.py，**同一会话连做**，避免两会话改同一文件。

---

## S5 会话存储追加式改造（D3 前置地基）

**动机**：DA 评测 §8.1 实查——`neurova/session_manager.py` 的 `add_message` 对每会话文件做**read-modify-write 全量重写**，长会话单文件无界增长，每条消息写成本 O(全文长度)。这是 D3 压缩纪律的地基：压缩事件要落会话盘，先得让会话盘可追加。

**改动文件**：`neurova/session_manager.py`（读写路径单点）、`tests/unit/core/` 会话存储既有测试 + 新增测试。

**实现要点**
- 两段式：每会话新消息**追加**进 `session_*.jsonl`；每 `SESSION_SNAPSHOT_EVERY`（具名常量，建议 50）条或字节阈值滚动一份 snapshot；读侧 = 快照 + 重放其后增量。
- 兼容：读路径按首行格式判别旧（全量 JSON）与新（两段式）文件，旧文件在**首次写入时懒迁移**；迁移失败回退旧读法（fail-open，但错误日志可见）。
- 开关：`NEUROVA_SESSION_JSONL` 环境门控，默认 off 起步→真链路验证通过后翻默认 on；旧写路径保留一个版本周期，确认无消费方后退役（同批删净，不留双实现）。
- 单点纪律：只改 `session_manager` 这一处实现——`mem_core.save_to_session`、控制台历史/时间线/搜索等全部消费方经它受益，**不另起第二存储类**。

**红灯**：新增 `test_session_store_append_only.py`——追加 200 条消息后文件写放大呈 O(1)（对比全量重写）；断电模拟（写一半的 JSONL 行）读取不炸、跳过坏行；旧格式文件懒迁移后读数一致。
**绿灯验收**：会话相关全量测试（core+api 的 history/timeline/搜索）A/B 零新增失败；live-verify：起真后端对话数轮后检查会话文件确为 JSONL+snapshot 形态。
**避坑**：本批是全方案**风险最高**的一项——务必独立会话专做、先设计后动手；线程锁语义保持既有；截断/阈值一律具名常量（附录 A2）。

---

## S6 压缩纪律（D3：3→5，依赖 S5）

**动机**：COS 的 D3 5 分机制：工具结果有界投影、摘要策略与守卫、失败冷却、子代理软目标。本仓有 `/compact` 手动命令与 context_pool 折叠语义（非破坏意识已在），缺自动触发、事件化持久与"严格变小"守卫。

**改动文件**：`neurova/agent/chat_pipeline.py`（上下文装配/出口）、`neurova/context_pool.py`、`neurova/tool_executor.py`（折叠面合流）、对应测试。

**实现要点**
- 自动触发：输入预算阈值触发摘要——`CONTEXT_COMPACT_TRIGGER_RATIO`（具名常量，建议 0.85）×上下文预算；provider 溢出异常兜底（识别溢出错误族→压缩→重试一次）。
- 事件化：压缩以 `CompressionEvent`（cutoffIndex/cutoffMessageId/摘要指纹）经 S5 的会话追加面落盘；视图可重建，**原始消息永不删除**（非破坏，D3 锚点核心）。
- 严格变小：溢出重试前校验新上下文 token 数**严格小于**原值，否则显式报错拒绝重发（防"越压越大"循环）。
- 工具结果有界投影：与既有折叠/UUID 句柄机制**合流**（句柄指向投影），投影上限 `TOOL_RESULT_PROJECTION_CHARS` 具名常量；保持"失败结果不折叠"既有纪律。
- 与手动 `/compact` 共存：手动命令优先级高，自动触发不抢已手动压缩的会话。
- 前端支撑（可选项转正）：①压缩事件**随会话事件流下发**（复用既有 SSE/会话事件通道加一类压缩通知事件，含 cutoff 摘要），ChatPage 据此展示"已自动压缩"轻提示；②压缩参数（`CONTEXT_COMPACT_TRIGGER_RATIO` 等）经**既有 context 统计/设置读面**扩展返回（不新建端点），设置页展示。

**红灯**：新增 `test_context_compact_discipline.py`——超阈值自动触发；溢出异常兜底重试；重试内容不变时（不严格变小）显式报错；压缩事件落盘后视图可重建且原消息仍在。
**绿灯验收**：chat_pipeline/context_pool 既有测试 A/B 零新增失败；live-verify 长对话压一次后检查会话文件中的压缩事件与可读性。
**避坑**：**"正文不得按字面量砍长度"常驻钉子**（`testSwarmNoLongerSlicesBodyByLiteralLength` 一族）——所有截断/阈值/上限必须具名常量，字面量数字上界一律红（附录 A2）；本批不碰 MemCore 内部（附录 A14）；摘要只是压缩视图，不是删除——判定器若发现"压完原消息没了"即设计错误。

---

## S7 记忆准入轻量先行（D2：4→5 机会）

**动机**：COS 的 D2 强在准入纪律（敏感拦截/审阅/世代失效）；DA 评测 §8.6 给出更轻的第一步——显式清单提示词 + 敏感信息拦截，零结构改动。H-7 实测的"跨任务记忆串扰"也从侧面暴露写入面无纪律。

**改动文件**：新增 `neurova/memory_admission.py`；改 `neurova/mem_core.py` 写入入口（单点包一层）；对应测试。

**实现要点**
- 两道闸（写入前，单点）：①敏感信息正则拦截（api key/token/password/私钥模式族）——命中即拒收 + 审计日志；②准入清单提示词（模型可见守则：用户明确偏好/事实该记，一次性感想/中间过程/密钥凭据绝不记）注入记忆写入链路的提示面。
- 拦截必须**可解释**：拒收时记录命中规则与原文摘要（摘要本身脱敏），供人工复核误杀。
- 3-Task 候选转正等重纪律**不在本批**（MemCore 主干另立项）。

**红灯**：新增 `test_memory_admission.py`——含 key 样式的写入被拒且有审计记录；普通偏好照常写入；清单提示词出现在写入链路提示面。
**绿灯验收**：mem_core 既有测试 A/B 零新增失败；live-verify 对话中塞一段含假 key 的消息，确认未入记忆且日志可查。
**避坑**：只做写入前拦截增量，不改记忆内部结构（附录 A14）；正则误杀要有日志与放行通道（宁可拒收可查，不可静默放行）。

---

## S8 审批审计持久化（E1：4→5，反超点）

**动机**：COS 的授权"持久化生产面缺失"（其 E1 只给 4 的原因），DA 评测确认其审批留痕只有 trace；本仓审批链（L0/L1/L2）+ 台账体系天然适合做出**审批审计持久化**——把领先维继续拉大。

**改动文件**：`neurova/agent/approval_chain.py`、审批治理面（`tool_executor.py` 的 ASK/决定点，以现场为准）、对应测试。

**实现要点**
- `requestRunApproval` 与 `decideSwarmApproval` 的每次请求/决定落**审计事件**（复用仓内既有审计单源，以现场复核为准）：级别、动作、path_values、发起 run、决策人、决策、时延。
- 查询面：挂现有管理/运维查询端点域，**不新开平行端点域**。
- fail-open：审计写失败不阻断审批主流程，但错误必须可见（日志 + 计数），不许静默吞。

**红灯**：新增 `test_approval_audit_persistence.py`——一次 L2 审批从请求到决定产生两条可查审计事件（请求+决定），字段齐全；审计写失败时审批仍可用且错误可见。
**绿灯验收**：审批链既有 18 例全绿；管理查询端点能按 runId 拉出完整审批轨迹。
**避坑**：审计单源——发现第二处审计写点时按教义第 6/7 条收口，不并存。

---

## S9 团队/房间能力接入蜂群（B4：4→5；A1/D1/D2 联动）

**动机**：COS 的 B4 5 分含 askhuman 人在环面、B5 含"人工可拦截"、A1 含动态组队——本仓已有现成接缝（协作房间/团队名册/记忆作用域/群主制度），接入后这些子项的机制缺口直接补上，且给 S4 候选制、S8 审批审计提供产品呈现面。

**现状接缝（开工前现场复核符号与行号）**
- 协作房间：`neurova/collaboration/room_store.py`（room_id = 协作 project_id 的既有等式，复用 SessionRepository 零新表）、`room_bus.py`（广播）、`room_turn_router.py`（@路由 + 默认应答者，人→agent 已通）。
- 群主制度（已生效，非仅展示）：房间发消息/编辑/成员增删均按 **admin/owner/成员**三级鉴权（`neurova/api/endpoints/collaboration_room_api.py`，owner 永不被移除）；团队亦有 `owner_id`（`teams_api.py`）。
- 团队名册：`neurova/api/endpoints/teams_api.py`（团队 + 成员 + 每成员职责 prompt + team prompt-context，JSON 落盘 `NEUROVA_TEAMS_PATH`）。
- 记忆作用域：`neurova/collaboration/memory_scope.py`（`direct` / `room:<room_id>` / `chgrp:` 三作用域，群群隔离，读写侧共用单源）。
- ACP 多角色编排：`neurova/agent/team.py`（AgentTeam.add_member/orchestrate，task_assignment→task_result，共享 trace_id）。

**范围钉死**：本批「群」**仅指协作房间**（room_id = 协作 project_id，听众是同批登录用户+成员 agent）。渠道群聊（飞书/QQ/Discord 等，`chgrp:` 作用域，听众是外部第三方身份，群主/管理员是平台侧概念）**不在整合范围**——两类群在 memory_scope 里本就是并列不同职的两个作用域，渠道群不参与蜂群审批链与候选拦截。

**实现要点**
1. **升级/审批 × 房间 = 人在环闭环**：SwarmManager 的 escalate 与审批链 L1/L2 的 ASK 投递到协作房间（sender_type=system/agent 的房间消息）；人在房间回复 → 经新桥接（approval_chain ↔ room_bus 的 pending-approval 匹配）回灌 `decideSwarmApproval`。**决策权限复用房间既有群主制度**：L2 必审的决策人限**群主（project.owner_id）或平台 admin**，普通成员的房间回复只记为议见不判定；审批审计（S8）记录决策人的房间身份。红线：房间只做"呈现 + 应答回灌"，判定权仍在审批链单源。
2. **候选 × 房间 = 人工可拦截的产品面**：CandidateReport 的 submitted/merged/conflict 事件投递到所属房间，人在房间里可直接拦截合并；artifactKeys 优先指向协作 project 的既有产物空间。
3. **团队名册 × spawn = 动态组队**：spawn 支持从团队名册按成员职责 prompt 选人（list_agents 辅助选人已有），角色复用 `collaboration_template.AgentRole`——补"按任务动态组队"缺口；不引入角色辩护等重机制。
4. **memory_scope × 蜂群 = 共享黑板**：蜂群 run 的跨成员共享记忆复用 `room:<room_id>` 作用域语义（或并列新增 `run:<run_id>` 作用域，与 room/chgrp 同构），群群隔离与"读单聊基线"语义直接继承，不新造作用域体系。
5. **AgentTeam 与 Swarm 的双实现取舍（教义第 7 条）**：两者定位不同——AgentTeam 是 ACP 面向外部 agent 的步骤编排，Swarm 是进程内子代理治理（评测评分对象）。初步裁定**双轨保留、边界写清**，但本批落地时必须复核两者是否出现同功能重复点；出现即按"先比后合"收口，不并存各调各的。

**红灯**：新增 `test_swarm_room_integration.py`——升级与审批消息在房间可见；群主回复回灌判定成功、普通成员回复只记议见；候选合并事件在房间可查；按名册选人 spawn 生效。
**绿灯验收**：room/collaboration 既有测试 A/B 零新增失败；live-verify 真房间走一次 升级→群主拍板→回灌判定。
**避坑**：房间消息走既有 RoomBus/RoomStore，**零新表零新协议**；房间持久层复用 SessionRepository，勿另写存储；权限判定复用 collaboration_room_api 既有三级鉴权谓词，不新造第二套权限体系。

---

## S10 固定团队开放给主 agent（A1：2→4）

**动机**：用户拍板：把现有固定团队作为可调用资源开放给主 agent——主 agent 既能通过任务编排调用满足需求的固定团队，也能在固定团队不满足需求时发起临时团队。COS 的 A1（团队组成与角色分配）现分 2vs3，本批连同 S9 的名册选人把它补上。

**形态选型（已裁定）**：**原生 builtin 工具优先，MCP 仅作外部开放的第二阶段**。主 agent 是进程内调用方，原生工具直接进既有治理面（工具面收窄/审批链/台账/成本闸）；本仓 MCP server（`mcp_ontology_server.py`，双鉴权）定位是给外部消费者开放能力——内部能力绕 MCP 是多一跳无收益。第二阶段若外部 agent 需要用团队，再按该 server 既有模式加 MCP tools（工具壳两层、机制单源）。

**改动文件**：`neurova/builtin_tools.py`（新工具 schema）、`neurova/tool_executor.py`（执行点）、`neurova/agent/swarm.py`（多路 spawn 编排）、`tests/unit/agent/`。

**实现要点**
1. `list_teams()`：列固定团队（id/名称/成员与职责摘要）。数据单源=teams_api 的 JSON 落盘，**不另建团队存储**。
2. `dispatch_team(teamId, task|taskUnit)`：把固定团队整体派活——按名册生成多路 spawn（成员职责 prompt 注入任务书角色段），TaskUnit.dependencies 做步间编排；run 带 teamId 溯源标（origin="team_dispatch"）；验收门/评审相位/候选制照走；治理三明治按主 agent 现有预算执行。
3. **临时团队不新增工具**：现有 `spawn_subagent` 自由选人+依赖编排本就是临时组队。补两件增量——`spawn_subagent` 增可选 `teamId`（固定团队骨干+临时外援混编）；**临时团队沉淀**：run 成功收尾后主 agent 可经治理 ASK（审批链 L1）提议把本次组合（成员+职责快照）沉淀为固定团队，**人批准后才写 teams_api**——团队是用户资产，agent 不得自行立队。此沉淀闭环是 CoworkOS 没有的产品循环。
4. 三个工具均为**主 agent 专属**：加入成员工具面剔除集（先例=spawn/cancel_subagent 的 allowlist 排除）。
5. 前端支撑（可选项转正）：①teams_api 团队记录增 `origin`（manual/agent_proposed）、`approved_by`、`promoted_from_run` 字段（JSON 落盘 .get 缺省回退，旧数据兼容）；②SubAgentRun.to_dict、台账行与 WS 同步载荷增 `team_id`，useSubAgentWindows 映射进窗口态，SubAgentPanel 显示团队徽标。

**红灯**：新增 `test_team_dispatch.py`——list_teams 返回名册；dispatch_team 按名册生成多路 spawn 且职责入任务书；无 teamId 的 dispatch 报错；沉淀提议未经批准不写 teams_api、批准后写入；三工具对成员不可见。
**绿灯验收**：swarm 既有测试 A/B 零新增失败；live-verify 用真团队走一次 派团→验收→候选合并。
**避坑**：dispatch_team 是多路 spawn 的编排糖，**不得绕过治理三明治**（广度/预算/冷却照算）；成员职责 prompt 来自团队名册（用户资产），注入前过 context_firewall；工具 schema 变更同步前端类型与路由快照（附录 A3/A7）。

---

## S11 多 agent 协作双入口（A1/B4 支撑）

**动机**：用户拍板：多 agent 协作要有两个入口——主 agent 按情况经任务编排主动发起（已有），以及**用户经项目直接发起**多 agent 协作。双入口让蜂群既可被 agent 自主驱动，也可被人直接驱动。

**改动文件**：`neurova/collaboration/room_turn_router.py`、`neurova/agent/swarm.py`（入口适配）、`neurova/api/endpoints/collaboration_room_api.py`（如需动作端点）、对应测试。

**实现要点**
1. **入口一（已有）**：主 agent 经任务编排主动发起——`spawn_subagent` / `dispatch_team`，一切照旧。
2. **入口二（新增）：用户经项目房间直发**——用户在协作房间发协作指令（@全部成员消息或房间"发起协作"动作）。`room_turn_router` 识别协作模式后**不再逐个独立应答**（现状是逐个调 `Agent.chat`），而是把房间成员交给 SwarmManager 编排（按成员职责定主从/依赖，TaskUnit 统一拼装）。
3. **观测与产出**：执行事件回房间广播（H-4 事件时间线可复用到房间视图）；终态报告以 candidate 落房间，用户按群主/成员权限拦截或采纳（S9 的呈现面）。
4. **关键裁定**：入口二只是**发起面+观测面**换到房间，执行机制与入口一共用同一套 SwarmManager——**不建第二套编排引擎**（教义第 6 条；AgentTeam/Swarm 双实现错误不得再演）。
5. **鉴权与治理**：发起人须为房间成员（三级鉴权已有）；L2 拦截权=群主/admin；预算由发起人显式给或沿用房间所属 agent 治理参数，治理三明治照常生效。

**红灯**：新增 `test_room_collab_entry.py`——房间协作消息触发 swarm 编排（mock agent 成员）而非逐个独立应答；进度事件回房间广播；非成员发起被 403；预算参数生效。
**绿灯验收**：room 既有测试 A/B 零新增失败；live-verify 真房间发起一次双人协作并看到事件流与终态报告。
**避坑**：房间协作的共享历史注入沿用 `turn_origin=collaboration` 既有语义；成员间记忆仍按 memory_scope 作用域隔离；不要把房间消息当 TaskUnit 正文直通——经统一任务书拼装（正文截断守具名常量纪律，附录 A2）。

---

## S12 项目协作档案：留底 + 可观测（F1：4→5）

**动机**：用户拍板：项目管理与多 agent 协作整合，做到**留底、可观测**。COS 的 F1 5 分=事件溯源+因果链+请求级归档+脱敏；本仓 H-4 账本、S8 审计、房间存储已各自成面，缺的是**按项目聚合的观测读面**——项目是协作的一等容器（room_id = 协作 project_id 既有等式），把散落账本聚到项目视角。

**现状**：`collaboration_isolation.py` 的 Project 已聚合 teams/tasks/workflows/files（单源落盘）；`projects_api.py` 的 stats 只数团队/任务/工作流——协作运行态（runs/事件/候选/审批）不在项目视野内。

**改动文件**：`neurova/agent/swarm.py`（spawn 打 project 标）、`neurova/api/endpoints/projects_api.py`（档案读面）、`tests/unit/api/` 或 `tests/unit/collaboration/` 新增测试。

**实现要点**
1. run→project 归属标签：经房间发起的协作（S11 入口二）spawn 时把 project_id 写入 run 台账行（agent_run_store 加列走 db_migration 注册表，附录 A6）；主 agent 直发（入口一）带项目上下文时同样打标。
2. 档案读面：`GET /projects/{id}/collaboration`（挂既有 projects 域，不新开端点域）——聚合返回：房间消息（RoomStore）、run 列表（台账按 project 标）、事件时间线（H-4 账本按 run 归属拉取）、候选记录（S4）、审批审计（S8）。**全部读既有持久面，不建第二本账**（教义第 6 条）。
3. 收尾封卷：项目 status 转 closed 时自动从账本生成协作总结（参与 run 数/候选收驳/审批记录/关键事件链），作为"留底"的封卷动作落项目档案。
4. 脱敏沿用账本纪律：正文不进账本，档案展示摘要与句柄，不搬运大正文。

**红灯**：新增 `test_project_collab_dossier.py`——房间发起的 run 带项目标；档案端点聚合 run/事件/候选/审批四类记录；封卷生成总结；无 project 标的 run 不串入档案。
**绿灯验收**：projects_api 既有测试 A/B 零新增失败；live-verify 房间发起一次协作后从档案端点看到完整轨迹。
**避坑**：聚合是**读时 join**，不改各账本写格式；跨账本查询走既有单源 API（readRunEvents/台账查询/审计查询），不直接翻文件；统计口径进 `get_project_stats` 时保持向后兼容字段。

---

## S13 项目/团队/群聊的 agent 工具面（用户和 agent 都可发起）

**动机**：用户拍板：用户和 agent 都可以发起项目；项目管理、团队管理、群聊开放给 agent 作为工具。至此发起面三合一：用户经项目直发（S11）、主 agent 编排发起（S10/S11 入口一）、agent 直接建项目/群聊（本批）。

**改动文件**：`neurova/builtin_tools.py`、`neurova/tool_executor.py`、对应测试。

**实现要点**
1. 新增主 agent 工具（成员工具面剔除，先例同 S10）：
   - `project_create(name, description, visibility, memberAgentIds?)`：agent 发起项目——**直接可建但强制审计 + 预算入账**；owner 记为发起 agent 的属主用户；**新增人类成员/改可见性 → 审批链 L1 ASK**（影响人必须过人）；对外分享 → L2。
   - `project_list()` / `project_detail(projectId)`：读面（复用 projects_api 与 collaboration_isolation 数据单源）。
   - `room_post(projectId, message, kind)`：agent 向自己所在房间发消息（kind=report/question/note），经治理限频；escalate/候选/审批走 S9 既有通道，本工具是通用发言面。
   - 团队管理**不加新工具**：固定团队开放在 S10（list/dispatch/沉淀 ASK），项目内团队（ProjectTeam）暂不开放给 agent——防工具面膨胀（DA 评测点名的反面教材），有真实需求再立项。
2. 创建即建房间：project_id = room_id 等式自动成立，零额外接线。
3. 治理：全部工具进治理三明治与台账；agent 发起的项目在档案（S12）中带 initiator=agent 标，便于用户区分来源。

**红灯**：新增 `test_agent_project_tools.py`——agent 建项目成功且审计可查；加人类成员触发 ASK、未批准不生效；非成员 room_post 被拒；三工具对成员不可见。
**绿灯验收**：builtin_tools/tool_executor 既有测试 A/B 零新增失败；live-verify agent 真实发起一个项目并从档案（S12）看到留底。
**避坑**：每加一个工具先问"能否并进既有工具"；agent 建项目的名称/描述过 context_firewall；`project_create` 不允许 agent 直接把 visibility 设为对外（L2 保留给人）；room_post 限频参数进治理三明治，防刷屏消耗他人 token。

---

## S14 同框重评分与超越判定

**动机**："超越"必须以同框口径的数据宣告。

**步骤**
1. 逐子项重评（对照 COS 评测 §6 的锚点与证据格式），每子项给**证据**：file:line、测试名、实测数据（报告字段/日志）——无证据不涨分。
2. 更新 COS 评测文档 §6.x 总分表（保留历轮分数列作走势），补执行记录段（各批次 commit 号）。
3. 判定：合计 **≥96** 即超越成立；未达则列剩余差距与下一轮清单，不降低口径硬凑。
4. 报告更新后按惯例推双远端（origin + github）。

**避坑**：评分锚点看的是"机制是否存在且被消费"（写入→读取→反馈闭环），只落库没人读的机制不涨分——S14 评审时逐项核闭环。

---

## S15 D3 收尾：压缩失败冷却 + 子代理软目标（会话P）

**动机**：S14 重评后 D3 的诚实边界——CoworkOS 的**失败冷却（5-15-30s）**与**子代理软目标（20k）**两件对标件缺位。用户拍板补齐。

**改动文件**：`neurova/agent/chat_pipeline.py`、`neurova/context_pool.py`、`neurova/agent/swarm.py`（member 会话软目标）、对应测试。

**实现要点**
- 失败冷却：压缩/摘要失败或溢出兜底重试仍失败后，进入**递增冷却**（`COMPACTION_FAILURE_COOLDOWN_STEPS = (5, 15, 30)` 秒，具名常量）；冷却期内跳过自动触发（手动 /compact 不受限）；冷却状态随会话持久（复用 S5/S6 事件面），进程重启不丢。
- 子代理软目标：swarm member 会话上下文逼近 `SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS`（具名常量）时**先于硬预算**触发压缩，保留近期原文（与 S6 投影/折叠合流，不新造第二套）。
- 冷却与软目标事件均随会话事件面可见（复用 S6 的 context_compacted 通知通道形态）。

**红灯**：连续失败后冷却期内不自动压缩、冷却按 5/15/30 递增；member 上下文过软目标即提前压缩且近期原文保留。
**验收**：chat_pipeline/context_pool/swarm 既有测试 A/B 零新增；live-verify 真后端压一次失败进入冷却的实测。
**避坑**：与 S6 机制合流不并立（教义第 6 条）；全部阈值具名常量（附录 A2）。

---

## S16 D2 收尾：记忆重纪律（3-Task 候选转正/世代失效/人工审阅接通）（会话Q）

**动机**：S14 重评后 D2 维持 4 的原因——3-Task 独立佐证转正、人工审阅、世代失效缺位。用户拍板补齐（原"不动 MemCore 内部结构"裁定由用户本轮解除，仍须独立方案先行、主干敬畏）。

**改动文件**：`neurova/mem_core.py` / memory_manager（增量层）、`neurova/memory_admission.py` 或新增 `neurova/memory_discipline.py`、pending_memories 待审队列消费点、对应测试。

**实现要点**
- **独立方案先行**：动手前先在现场勘察 MemCore 存储结构与记忆生命周期，把设计（候选/世代字段落哪、消费方是谁、转正判定在哪个单点）写进提交说明，再实现。
- **3-Task 候选转正**：新记忆带来源任务/会话标入候选；跨 **≥3 个独立任务**再观测才转正为持久记忆（`MEMORY_PROMOTION_MIN_TASKS = 3` 具名常量）；转正前可见性按候选语义，不影响既有读路径。
- **世代失效**：新事实与旧记忆矛盾时使旧代失效（标记 superseded，保留可追溯，不物理删）。
- **人工审阅接通**：S7 移交项——`screenMemoryContent` 接入 pending_memories 的 propose/confirm 两点，敏感候选人工放行/拒收留痕。
- **门控**：`NEUROVA_MEMORY_DISCIPLINE` 环境门控默认 off（MemCore 主干风险高，先 live-verify 再议翻默认）；门控关闭时行为与现状完全一致。

**红灯**：跨 3 任务第 3 次观测才转正、前两次不转；矛盾事实使旧代失效且可追溯；待审候选经 screenMemoryContent 拦截敏感内容；门控关闭时行为不变。
**验收**：mem_core 既有测试 A/B 零新增（门控关闭态）；门控开启态新测试全绿；live-verify 真后端走一次 候选→3 任务→转正 与 矛盾→失效。
**避坑**：附录 A14 主干敬畏——只做增量层；SQLite 变更走 db_migration 注册表（附录 A6）；具名常量。

---

## S17 F1 收尾：模型请求级归档（会话R）

**动机**：S14 重评后 F1 的诚实边界——CoworkOS 的模型请求级 JSONL 归档（\*-requests.jsonl 形态）缺位。用户拍板补齐（H-4 账本脱敏纪律不破坏，归档是独立 trace 面）。

**改动文件**：新增 `neurova/core/request_archive.py`（或按现场落 `neurova/llm/`）；`neurova/llm/multi_model_client.py`（chat/chat_stream 边界挂点）；`neurova/api/endpoints/projects_api.py`（档案聚合增请求归档摘要——消费面）；对应测试。

**实现要点**
- 每 run/会话一份 JSONL（`<数据根>/request_archives/`），记录：时间戳、model/provider、消息角色与字符数、usage、时延、成败/错误族；**默认不落全文**，落脱敏摘要（复用 S7 的 SENSITIVE_KEY_PATTERNS 做脱敏；全文归档留 `NEUROVA_REQUEST_ARCHIVE_FULL` 门控另议）。
- 写入 fail-soft 不阻断主链路（错误日志+计数可见，不静默吞）；尺寸上限具名常量（附录 A2）。
- **消费面**：S12 档案聚合（GET /projects/{id}/collaboration）增请求归档摘要（次数/token/时延分布/最近错误），形成写入→读取→反馈闭环。

**红灯**：一次 LLM 调用产生一条归档（含 usage/时延/角色计数）；含 key 样式内容被脱敏；档案聚合能读到归档摘要；写失败不阻断调用。
**验收**：multi_model_client 既有测试 A/B 零新增；live-verify 真后端调用后归档文件与档案摘要一致。
**避坑**：归档独立于 H-4 事件账本（不往账本加请求级事件，账本纪律不变）；异步/延迟写避免拖慢调用路径。

---

## S18 G2 收尾：MCP 深度集成——团队能力外部暴露（会话S）

**动机**：S14 重评后 G2 4 分的剩余件——MCP 深度集成（方案 §0.3 原裁定另立项，用户本轮拍板纳入）。形态沿用已裁定原则：**工具壳两层、机制单源**——MCP server 只做协议壳，执行复用既有单源。

**改动文件**：`neurova/mcp_ontology_server.py`（增协作工具壳）、既有 tool_executor 执行体（只复用不改动；如需抽出可调用面以最小增量进行）、对应测试。

**实现要点**
1. MCP 工具壳新增：`team_list`、`team_dispatch`（映射 list_teams/dispatch_team 既有执行体）、`project_list`、`project_detail`（映射 S13 读面）——外部 agent 经 MCP 获得与主 agent 同源的团队能力。
2. 双鉴权照旧（server 既有鉴权谓词）；治理照走（dispatch 经同一治理三明治与审批链，MCP 调用方身份按 server 既有身份语义传递）。
3. 不新建第二套执行逻辑——MCP 壳只做参数适配与协议封装（教义第 6 条）；工具描述与 schema 与原生工具同源（不复制粘贴两份）。

**红灯**：经 MCP 调用 team_dispatch 与原生 dispatch_team 同结果（同一 run 溯源标/治理计数）；未通过鉴权的调用被拒；成员面剔除语义在 MCP 侧同样生效（不可经 MCP 绕过成员限制）。
**验收**：mcp server 既有测试 A/B 零新增；live-verify 真 MCP 握手后走一次 team_list→team_dispatch。
**避坑**：server 是外部暴露面——任何新工具先过鉴权与治理再谈便利；不把内部工具面全量搬上 MCP（防工具面膨胀，附录 A14 精神）。

---

## 附录 A：共享避坑清单（每批开工前必读）

1. **A/B 必须串行**：pytest 并行曾致全仓 AST 扫描档（`test_theTakeoverTableMatchesTheSharedEntry` 一族）超时假红。涉及共享文件的批次，提交前 `git stash push -- <本批文件>` → 跑套件 → `git stash pop`，失败清单逐条比对，**新增失败才算回归**。trio（agent+collaboration+benchmark）约 4 分钟，api 约 8.5 分钟。
2. **"正文不得按字面量砍长度"常驻钉子**：`testSwarmNoLongerSlicesBodyByLiteralLength` 扫源码 ast.Slice+Constant 上界。任何截断/阈值/上限必须具名常量（先例：`EVENT_TASK_SUMMARY_CHARS`、`EVENT_ERROR_SUMMARY_CHARS`），字面量数字上界一律红。
3. **新增 HTTP 路由必须重生成路由快照**：`tests/unit/api/console_split_routes.json`（console 域）。用测试模块的 `route_snapshot()` 重生成，格式 indent=1、ensure_ascii=False、尾部换行；重生成本地 diff 必须纯增量——出现无关行变化说明动了别的路由，停下来查。
4. **邮箱唯一写点**：所有向邮箱投递的代码只许走 `SwarmManager.pushParentMail`；直连 `get_agent_mailbox` 写入是已知回归（生产引用钉死在 swarm.py 与 loops/base.py）。
5. **热区撞车复核**：`swarm.py`、`session_manager.py`、`mem_core.py`、`benchmark/` 是多会话常改文件。动手前 `git log --oneline -5 -- <file>` + `git status`；发现他人在途改动（未提交的 M 状态）→ 换文件或等收口，绝不覆盖。
6. **SQLite 纪律**：schema 变更走 `core/db_migration.py` 注册表（PRAGMA user_version），只写 `IF NOT EXISTS` 不算迁移；多线程访问持 `threading.RLock`（WAL 已在连接池开）。
7. **契约钉子同批同步**：改状态枚举/工具 schema/路由表时，后端钉子（如 `test_swarm_integration_escalation.py::test_schema_exposes_view`）与前端类型（`SubAgentPanel.vue` 的 status 联合类型、console.ts 接口）必须同一批更新——先例：view 枚举扩容漏改钉子致 trio 36 failed（fd2e5937f 修复）。
8. **提交纪律**：Conventional Commits；正文含动机与根因、红绿实测证据、`净 LOC：生产池 +N/−M`（同一行）与字面词「去向」；`git commit --only -- <paths>` **逐文件点名，严禁 `git add -A`**（会暂存他人在途文件）；新文件先 `git add` 再 --only；提交不推远端（推远端须用户明示，先例"推双远端"=origin+github 两处）。
9. **前端两道门**：`npm run test`（vitest）与 `npx vue-tsc --noEmit` 必须全绿；`NeurUI` 的 lint 脚本当前无 eslint 配置，**不作为验收项**。i18n 文案 11 locale 与 zh-CN 严格对齐（`locale-consistency.test.ts` 会拦）；前端禁硬编码色值（themes 契约），用 `src/styles/variables.css` 令牌。
10. **测试落位**：正式测试进 `tests/unit/<模块>/`，临时验证脚本即用即删；`.venv/Scripts/python.exe -m pytest` 跑测（Windows）。
11. **密钥安全**：模型 key/凭据只进运行进程内存，绝不入仓库、文档、报告；含密钥临时脚本用后即删（H-7 先例：跑完 140 次调用后脚本已删、仓库零命中）。
12. **live-verify 起后端**：解释器只用项目 `.venv`（系统 Python 缺 prometheus-client/jwt 会静默降级）；起前清 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY`（含小写，CIDR/方括号 IPv6 会让 httpx 抛 InvalidURL）。健康判据：启动日志 `[ERROR]` 计数 0 且注册行含 `/v1/providers`。
13. **深模块模式**：模块经 `agent_ref` 依赖注入访问 Agent，禁止直接 import Agent；可选重依赖惰性 import + fail-soft；懒创建单例走 DCL+RLock。
14. **主干敬畏**：MemCore、chat_pipeline、context_pool 是全仓主干——只做方案内点名的增量，发现"必须动主干内部结构才能做完"时**停下来登记**，不硬改。
15. **命名与身份**：camelCase 函数/PascalCase 类型/全大写常量；禁用 data/info/temp/handler/manager/util/helper/process 等模糊词；身份只有 `neurova_request_user_id` 一条通道，新增第二装 user_id 的 ContextVar 即复活旧病（常驻判据测试会拦）。

## 附录 B：交付定义（每批相同）

每批完成 = ①红灯测试先行的实现转绿；②目标套件全绿 + trio/api A/B 零新增失败（按涉及面选）；③live-verify 真链路证据（命令+输出原文）写入提交说明；④`git commit --only` 逐文件点名入库；⑤本方案文档的执行记录段补一行（commit 号 + 一句话结果 + 偏差说明）。执行中发现方案与现场冲突：以现场为准修方案（改文档），不硬凑。

## 附录 C：多会话并行推进方案（非子代理，独立 ZCode 会话）

> 先例：2026-11-16 审计修复批以 8 个独立会话并行推进 147 条修复。本方案 14 批**不能全并行**——所有会话共享同一工作树，文件域重叠的批次硬性串行。按文件域不相交切分，最多 **4 路并行**，共约 6 个波次：

| 波次 | 会话分工 | 独占文件域 | 依赖 |
|---|---|---|---|
| 波1（4 路并行） | A:S1 · B:S2 · C:S5 · D:S7 | benchmark/multi_agent · mailbox+loops/base · session_manager · mem_core | 无，随时开工 |
| 波2（3 路并行） | E:S3+S4 连做 · F:S6 · G:S8 | swarm.py+goal_verifier/review · chat_pipeline+context_pool+tool_executor · approval_chain（tool_executor 小触点） | 波1 不阻塞本波，但 G 的 tool_executor 触点**等 F 收口后再落**（同文件禁双改） |
| 波3（1 路） | H:S9 | swarm 房间桥接+room_bus/teams_api 读 | E（S4 候选）、G（S8 审计）落地后 |
| 波4（1 路） | H 续:S10+S11 连做 | builtin_tools+tool_executor+room_turn_router+collaboration_room_api | S9 落地后；S10/S11 同碰 swarm.py 与工具面，**同会话连做** |
| 波5（2 路并行） | I:S12 · J:S13 | projects_api+swarm 打标 · builtin_tools+tool_executor | 波4 落地后；I/J 文件域不相交可并行 |
| 波6（1 路） | K:S14 重评分 | docs/08-research | S1–S13 全部落地后 |

**并行协调规则（附录 A 之上追加）**
1. **同文件禁双改**：共享同一工作树，开工前 `git status` + `git log --oneline -5 -- <file>` 撞车复核；发现他人在途改动（未提交的 M）→ 换批或等待，绝不覆盖。
2. **提交一律 `git commit --only` 逐文件点名**，新文件先 `git add` 再 --only，**严禁 `git add -A`**（会暂存他人在途文件，审计批实证）。
3. **全量 A/B 错峰跑**：trio/api 全量套件不得两会话同时跑（CPU 争用→超时假红，P3 实证）；文件级测试随时可跑；并行期间全量跑排队或错峰。
4. **基线随 main 漂移**：每会话 A/B 的基线以"当时 stash 后的 main"现场重跑为准，不用陈旧失败清单；比对比的是失败**集合**而非数量（各批会新增通过测试）。
5. **契约钉子同批同步**（A7）：改枚举/路由/schema 的会话在提交说明里显式列出"动了哪些钉子"，供其他会话感知。
6. **共享文档并发编辑**：0-index/本方案/记忆文件改前必须重读（已有两次并发修改冲突实证）。
7. **执行记录台账**：仿审计批 SUMMARY.md，各会话完成一批即登记（批次/commit 号/一句话结果/移交项），波6 收尾会话据此汇总并更新本方案执行记录。

## 附录 D：前端 UI 适配清单（NeurUI，按批挂靠）

> 现有落点（2026-11-17 实查）：房间页 `pages/CollaborationRoomPage.vue`、协作页 `pages/CollaborationPage.vue`、团队页 `pages/TeamPage.vue`、审计页 `pages/AuditPage.vue`、聊天页 `pages/ChatPage.vue`（经 `components/chat/SubAgentWindowStack.vue` + `composables/useSubAgentWindows.ts` 挂 SubAgentPanel）、基准页 `pages/BenchmarkPage.vue`；API 模块 `api/modules/{collaboration,collaborationRoom,audit,benchmark,console}.ts`。横切纪律：新文案 11 locale 对齐（locale-consistency 测试拦）、禁硬编码色值（themes 契约）、`npm run test` + `npx vue-tsc --noEmit` 两道门全绿、API 模块补契约测试。

| 批次 | 适配要求 | 涉及文件 |
|---|---|---|
| S1 | **必改**：BenchmarkPage 增多 agent 基线报告视图（usage/轨迹列）。后端支撑=S1 1E 报告只读端点 | BenchmarkPage.vue、api/modules/benchmark.ts |
| S2 | **必改**：监控页邮箱健康卡（在途租约/ack/回收计数）。后端支撑=S2 stats 快照并入既有系统状态读面（不新增路由） | MonitorPage.vue |
| S3 | **必改**：`SubAgentWindowState.status` 联合类型与 `status-*` 样式、statusIcon 映射覆盖迁移表正式化后的全部状态（blocked/cancelled 等）；useSubAgentWindows 状态同步；状态文案 i18n | SubAgentPanel.vue、useSubAgentWindows.ts、SubAgentPanel.test.ts |
| S4 | **必改**：候选状态徽标（submitted/accepted/rejected/reviseRequired）与冲突列表+"重议"入口——呈现位置随 S9 房间（首选）或 ChatPage 蜂群汇总区 | CollaborationRoomPage.vue、SubAgentPanel.vue |
| S5 | 无（读写数据形态不变） | — |
| S6 | **必改**：自动压缩会话内轻提示（压缩事件随会话事件流下发）+ 设置页压缩参数展示。后端支撑=S6 事件流通知 + 既有 context 读面扩展参数 | ChatPage.vue、context 设置页 |
| S7 | 无直接 UI（拒收记录经 S8 审计面可见） | — |
| S8 | **必改**：AuditPage 增审批审计查询视图（按 runId/时间/级别筛选，请求+决定成对展示）；audit.ts 模块扩展 | AuditPage.vue、api/modules/audit.ts |
| S9 | **必改**：房间页①升级/审批消息卡片（群主专属 批准/拒绝/改议 按钮，普通成员只读+议见入口）；②候选事件徽标与拦截入口；③成员列表 owner 群主徽标；API 模块扩展 | CollaborationRoomPage.vue、api/modules/collaborationRoom.ts |
| S10 | **必改**：TeamPage 团队来源标（人工/agent 沉淀+批准人）+ SubAgentPanel teamId 徽标。后端支撑=S10 teams_api 增 origin/approved_by/promoted_from_run、run 台账与 WS 同步载荷增 team_id | TeamPage.vue、SubAgentPanel.vue、useSubAgentWindows.ts |
| S11 | **必改（最大新 UI）**：房间页"发起协作"入口（选成员/预算/任务书表单）→ 触发 swarm；房间内协作进度区（复用 H-4 时间线形态）；终态报告卡片（采纳/拦截） | CollaborationRoomPage.vue、api/modules/collaborationRoom.ts |
| S12 | **必改**：项目详情增"协作档案"视图——五类记录聚合时间线（消息/run/事件/候选/审批）+ 封卷总结 + initiator=agent 来源标；api 增 getProjectCollaboration | CollaborationPage.vue（项目详情）、api/modules/collaboration.ts |
| S13 | 无新 UI（工具为模型面）；治理 ASK 卡片复用 ChatPage/房间既有审批组件；initiator 标随 S12 | — |
| S14 | 无 | — |

**工作量集中点**：S9/S11/S12 三个房间与项目页面的改造是前端主战场；S3/S4/S8 与转正后的 S1/S2/S6/S10 为小改（各 1–2 个组件/页面 + api 模块扩展）；无适配=S5/S7/S13/S14。每项适配随对应后端批次同批交付（含契约测试与 i18n），不单独拖尾。

## 执行记录（统筹者汇总，按波次补记）

| 批次 | commit | 结果 | 偏差 / 移交 |
|---|---|---|---|
| S1 评测地基 | a79c10ba7 | 完成：usage 回传、expect_trajectory 判据、taskIsolatedMemory（默认开）、T1 改材料归纳、/baseline-reports 只读端点；benchmark 69 passed + 受影响 api 17 passed | 1F 真模型复跑待用户提供密钥；swarm 轨迹生产者未接线（tool_executor/loops 不产 span 工具事件，swarm 轨迹暂读 0）→ 移交波2 F 接线；BenchmarkPage 报告视图 → 前端专项 |
| S2 邮箱语义 | 763abece7 | 完成：messageId 幂等、priority 队列、leased 超时回收、stats() 并入 /monitor/resources（未新增路由）；A/B 181→185 零新增 | 审批投递 priority=high → 移交 S8（approval_chain.py 审批投递点）；MonitorPage 邮箱健康卡 → 前端专项 |
| S5 会话追加式 | 1444143c1 | 完成：JSONL+快照两段式（追加/撕裂封口/坏行跳过/懒迁移 fail-open），NEUROVA_SESSION_JSONL 默认 off；core 全量基线 23 预存失败逐行一致；live-verify 真后端 4 轮对话文件形态实拍 | 偏差：保留 .json 扩展名按内容判别格式（换 .jsonl 扩大爆炸半径）；翻 on 前必须先收口 shutdown_guard.py:268 与 memory_ingest/intake.py:108 两处绕过 manager 的直读；_get_file_lock 非重入 Lock 与注释不符（既有问题，另立批） |
| S7 记忆准入 | 90a2fb84d | 完成：写入前敏感拦截（SENSITIVE_KEY_PATTERNS）+ 准入清单提示词，审计走 security/audit_logger 单源；live-verify 假 key 拒收入审计、记忆库零命中、正常偏好照常落库 | pending_memories.propose 待审队列未过闸（建议接 screenMemoryContent）；清单提示词可接 rules_sections 记忆规则段 |
| 波1 收口 | e3fab73ed | trio 35 failed=基线（2592 passed，净增 19 新通过）；api 17 failed=基线（3213 passed）——零新增失败 | 唯一漂移=身份读方台账缺 memory_admission 审计读点，按"钉子随契约扩容同步"登记（fd2e5937f 先例），断言不放宽 |
| S3 迁移表（会话E） | 73d05aa63 | 完成：RUN_STATUS_TRANSITIONS 全量出边表 + transitionRun 唯一收口（swarm 7 处 + review_gate 6 处赋值点改道），非法迁移抛 IllegalRunStatusTransition，每次迁移落 status_changed 入 H-4 账本；replayRunTailStatus/reconcileRunFromEvents 启动校正；21 用例；swarm 域 177→198 零新增；live-verify 9631 迁移序列与账本逐条对上 | 状态枚举未扩容（仍 5 态），前后端契约钉子零变化 |
| S4 候选制（会话E） | ee6be8c2e | 完成：candidate_merge.py（CandidateReport/CandidateMergeBoard：提交即互标冲突双方保留、CAS 合入、驳回/回炉重提）+ swarm 回流接线（先落候选不直传定案）+ 合入经审批链分级（默认 L0，NEUROVA_SWARM_MERGE_APPROVAL_LEVEL 可调）+ integrationReport 增 revision/candidates/conflicts；40 用例；swarm 域 217 passed 零新增 | 冲突 run 如实判失败（cause=merge_conflict）并升级人工裁决；留痕走 H-4 账本不落盘；验收判定复用 goal_verifier/review 不设第二套 |
| S6 压缩纪律（会话F） | c340f5e80 | 完成：CONTEXT_COMPACT_TRIGGER_RATIO=0.85 自动触发、溢出错误族兜底压缩重试一次、assertCompactionShrinks 严格变小守卫、CompressionEvent 经 append_timeline_event 落时间线（原消息永不删）、工具结果有界投影（TOOL_RESULT_PROJECTION_CHARS，句柄可回取、失败不折叠）、压缩通知随事件流下发（upstream_status 透传）；**含波1 移交的轨迹生产者接线**（tool_call_start/end/error span，swarm 轨迹不再读 0）；23 用例；A/B 零新增 | ChatPage 轻提示与设置页参数展示→前端专项；与手动 /compact 共存（命令轮短路不重复压） |
| S8 审批审计（会话G） | cd695139d | 完成：requestRunApproval/decideSwarmApproval 请求+决定成对落审计单源（security/audit_logger，增 APPROVAL 类型与 resource_id 过滤）+ GET /v1/audit/approvals?run_id= 成对轨迹查询（admin 门、纯增量）+ 审批邮件补 priority=high（S2 移交闭环）；9 新 + 审批链既有 18 全绿；审计面 41 passed 零新增；净 LOC +238/−2 | tool_executor 触点经现场复核**无需改动**（request_approval/decide_subagent_approval 工具经 approval_chain 单源已全覆盖，治理 ASK 另有 _audit_governance，不设第二写点——教义第 6/7 条）；AuditPage 审批审计视图→前端专项 |
| 波2 收口 | — | trio 35 failed=基线（2664 passed，较波1 再增 72 新通过）；api 17 failed=基线（3213 passed）——零新增失败 | 三会话（真独立 ZCode 会话）文件域互斥零撞车；会话E 曾中途停摆，统筹者经会话消息催办后恢复收口 |
| S9 团队/房间接入·后端（会话H） | 79551406e | 完成：审批/升级/候选事件投递协作房间（零新表零新协议）+ handleRoomSwarmReply 回灌 decideSwarmApproval（L2 判定限群主/admin、普通成员只记议见、审计增 decided_by_channel、重启从房间历史补建 pending 索引）+ 名册选人 spawn（team_id/team_role，职责段具名上限 TEAM_DUTY_PROMPT_MAX_CHARS）+ memory_scope 注入 chat_scope=room:<id> 并同构扩 run: 前缀 + AgentTeam/Swarm 边界复核无重复（有钉子）；新端点 GET swarm/pending、POST approvals/{rid}/decide、POST candidates/{cid}/{intercept\|merge} 全部复用三级鉴权谓词；14 用例；A/B 41==41 逐行一致零新增；live-verify 9641 群主回复→桥接匹配→判定成功→裁决卡上墙全程实测；净 LOC +771/−24 | 房间只做呈现+应答回灌，判定权仍在审批链/候选板单源；渠道群 chgrp: 不参与（范围钉死） |
| S9 前端适配（会话H） | ebf0cb284 | 完成：CollaborationRoomPage 蜂群系统消息专用卡片（审批/升级/候选，级别/状态徽标）+ 群主专属批准/拒绝与拦截/采纳按钮（canDecideSwarm 与后端同口径）+ 普通成员议见提示 + 成员列表群主徽标；collaborationRoom.ts 增 swarm 载荷归一与 3 个 API；i18n 11 键×11 locale；vitest 全量 2560 用例 0 失败 + vue-tsc 0 错 | 卡片样式走 --nr-* 令牌，无硬编码色值 |
| 波3 收口 | — | trio 35 failed=基线（2678 passed，+14）；api 17 failed=基线（3213 passed）——零新增失败 | 单会话波次（S9 为最大集成批），后端+前端同会话交付 |
| S10 固定团队开放（会话I） | 305f47c8d | 完成：list_teams/dispatch_team/propose_team 三工具进 builtin 工具面（主 agent 专属，成员工具面 general/explore 双路剔除，入不可重现名单）；dispatch_team 按名册逐成员多路 spawn（职责 prompt 唯一拼装进任务书角色段、步间依赖按名册声明并映射 subagent_id、origin=team_dispatch+team_id 溯源标），治理三明治（深度/广度/预算/冷却/并发）全程照算；propose_team 经审批链 L1 治理 ASK、人批准才经 teams_api.createAgentProposedTeam 写入（origin/approved_by/promoted_from_run）；WS subagent_* 载荷增 team_id/team_role；17 用例；A/B 35=35 零新增；净 LOC +513/−28 | 移交：台账行 team_id 落库需 agent_run_store 迁移注册表变更→并入 S12 打标批同通道；本轮以 to_dict+WS 载荷+前端映射承载 |
| S11 双入口（会话I） | 68e65982a | 完成：@全部成员识别（isCollaborationTrigger）+ POST /rooms/{id}/collaboration 动作端点（三级鉴权、非成员 403、空任务 400）→ orchestrateRoomCollaboration 把房间可解析成员交 SwarmManager 统一编排（默认应答者为主执行者先行、其余支援按依赖接力，人类成员 skipped 不派 run）；composeRoomCollabBrief 统一任务书（不把房间消息直通 TaskUnit，截断具名常量 ROOM_COLLAB_TASK_MAX_CHARS/ROOM_COLLAB_HISTORY_DIGEST_CHARS）；subagent_started/chunk/completed 事件回房间广播（复用 H-4 时间线与 S9 投递通道，零新协议）；终态报告走 S4 候选板按权限采纳/拦截；member 记忆按 room:<id> 作用域；发起人预算透传每路 run；31 用例；A/B 35=35 零新增；净 LOC +246/−1 | 执行机制与入口一共用同一套 SwarmManager，不建第二套编排引擎；顺带修复房间裁决端点回灌团队沉淀（与 decide 工具同源 applyTeamProposalDecision） |
| S10/S11 前端适配（会话I） | 1eccf8aa0 | 完成：TeamPage「Agent 沉淀」来源标（tooltip 带批准人）+ SubAgentPanel 团队徽标 + useSubAgentWindows started/台账回填双路映射 team_id + 房间页「发起协作」表单（任务书/预算/支援上限）与协作进度区 + swarm_collab 系统卡 + teams.ts/collaborationRoom.ts 扩展 + i18n 10 键×11 locale；vitest 全量 2560 用例 0 失败 + vue-tsc 0 错 | 两道门抓出 CollaborationRoomPage 模板多根节点与 kind 联合类型缺 swarm_collab，同批修复；样式全走 --nr-* 令牌 |
| 波4 收口 | — | trio 35 failed=基线（2709 passed，+31）；api 17 failed=基线（3213 passed）——零新增失败 | 单会话连做波次（S10/S11 同碰 swarm.py 与工具面） |
| S13 agent 工具面（会话K） | f10f448f3 | 完成：project_create（直接可建+强制审计+预算入账；人类成员/可见性放宽走 L1 ASK 未批准不生效；visibility=public 对 agent 拒绝——L2 保留给人；名称/描述过 context_firewall）/project_list/project_detail（复用 isolation 可见性判据）/room_post（成员判据 fail-closed、滑动窗口限频具名常量防刷屏、复用 AGENT_REPLY 通道零新协议）四工具；创建即建房间（project_id=room_id 等式自动成立）；initiator=agent 标落项目 metadata；成员面剔除=声明集 MAIN_AGENT_ONLY_TOOLS+执行咽喉结构化拒绝双保险；13 红→14 绿；A/B 3=3 零新增；live-verify 9663 真实 Agent 发起项目、public 被拒、审计库按 resource_id 查到台账两行；净 LOC +540/−0 | 移交收尾波：①MAIN_AGENT_ONLY_TOOLS 与 swarm.MEMBER_EXCLUDED_TOOLS 并集收口（swarm.py 当时在途）；②项目治理 ASK 的房间裁决回灌接线（需 collaboration_room_api 配合）；③memberUserIds 为方案外增设的可选参数（人类成员显式通道，避免按 id 形态猜身份） |
| S12 项目协作档案·后端（会话J） | 1e829d308 | 完成：agent_run_store v5 迁移（project_id/team_id 列+项目索引，PRAGMA user_version 通道，锁升级 RLock）；agent_run_ledger openSubagentRun 透传（唯一写点不裂第二处 INSERT）；swarm spawn 打 project 标（显式优先、room_id 等式缺省；续跑随行 project、team_id 不随行避免重走选人变义）+ candidateRecordsForRuns 只读面；GET /projects/{id}/collaboration 五类记录聚合（正文只出摘要与句柄、截断具名常量）+ 项目归档封卷自动生成协作总结 + stats.runs_count 向后兼容；9 红→10 绿；A/B 84→94 零新增；蜂群域点跑 95 passed；live-verify 9661 档案端点见 spawned→started→terminal 完整因果链与封卷留底；净 LOC +414/−5 | S10 移交的 team_id 落库同通道闭环；读时 join 既有持久面不建第二本账；空标 run 不归属任何项目（不串档案判据落点） |
| S12 前端档案视图（会话J） | 0338a5823 | 完成：CollaborationPage 项目档案面板（计数徽标/封卷总结含关键事件链/Run 台账表/事件时间线/候选/审批/房间消息摘要）+ collaboration.ts getProjectCollaboration 与七类类型 + 契约测试锁 URL 形态与信封解包 + i18n 17 键×11 locale 全实译；vitest 全量 2562 用例 0 失败 + locale-consistency 41 passed + vue-tsc 0 错 | 样式全走 --nr-* 令牌 |
| 波5 收口 | — | trio 35 failed=基线（2723 passed，+14）；api 17 failed=基线（3223 passed，+10）——零新增失败 | 两路真独立会话并行，文件域互斥零撞车 |
| 收尾波·后端（会话M） | 458ae1e8d + f7f346694 + 9702d8cd9 | 完成：①成员工具面剔除集并集收口单一事实源——MAIN_AGENT_ONLY_TOOLS 扩为 11 项唯一声明、swarm.MEMBER_EXCLUDED_TOOLS 退役、白名单派生期即剔除+执行咽喉门降为纵深防御（2 红→61 passed，净 LOC +20/−22）；②房间裁决回灌项目治理 ASK——decide_room_approval 批准分支复用 applyProjectGovernanceDecision 单源、审计记 decided_by_channel（2 红→104 passed）；③教义第 5 条 docstring 残引扫荡；A/B 166→170 零新增 | S13 两条移交项全部清偿；与团队沉淀同一裁决出口，不建第二实现 |
| 收尾波·前端（会话L） | da7a70ffd + 19bc07376 + d2209118c + e1944819f + 7e0c3b953 | 完成：S1 BenchmarkPage 基线报告视图（报告清单+逐任务 usage/轨迹列，getBaselineReports 双端点封装）+ S2 MonitorPage 邮箱健康卡（消费 /monitor/resources 的 mailbox 快照）+ S6 ChatPage 自动压缩轻提示（认领 context_compacted 相位+cutoff 摘要）+ S8 AuditPage 审批审计成对查询面板（getApprovalTrajectory）+ S3 状态类型复核；各带契约测试，i18n 16/11/1/18 键×11 locale | 附录 D 前端适配全部清零；S3 枚举未扩容、类型已覆盖，按复核结论不做无用改动 |
| 收尾波 收口 | — | 四道门全绿：trio 35 failed=基线（2727 passed，+4）；api 17 failed=基线（3223 passed）；vitest 2618 passed/0 失败；vue-tsc 0 错——统筹者复跑前端两道门复核会话报告 | 至此 S1–S13 全部落地、附录 D 清零、移交项清零；仅剩 S14 重评分 |
| S14 同框重评分（会话N） | ffd6ab779 | 完成：七维廿二子项逐项重评（锚点不变；逐项证据=机制落点 file:line+消费闭环+测试/实测，无证据不涨分；引证 30+ commit 号逐一 git log 核验）——**Neurova 98/110（上轮 84，净 +14）越过判定线 96，对 CoworkOS（95）超越成立**；A16(+2)/B24(+5)/C14(+2)/D13(+2)/E14(+1)/F9(+2)/G8(0)；11 项不涨逐一写明原因；敏感性核验：F2/D3 按最严口径守旧分总分仍 96~97，判定不变；剩余差距清单已列（D 压缩失败冷却/记忆重纪律、F 请求级归档与 v2 复跑、G MCP 深度集成、A1 角色辩护） | 统筹者终复核：抽查全部关键 file:line 证据（swarm/candidate_merge/mailbox/context_pool/builtin_tools/approval_chain/swarm_event_log）与引证 commit 全部属实；1F 真模型复跑仍待密钥（F2 已按诚实口径计 4，未给满分） |
| S15 D3 收尾（会话P） | 51302e080 | 完成：压缩失败递增冷却（COMPACTION_FAILURE_COOLDOWN_STEPS=(5,15,30) 状态机+随会话事件面持久+重启不丢+手动 /compact 不受限+冷却通知复用 upstream_status）+ 子代理软目标（SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS=20000，先于硬预算 min 语义触发、reason=soft_target 可区分、近期原文保留与 S6 投影合流） | 与 S6 机制合流不并立；阈值全部具名常量 |
| S16 D2 收尾（会话Q） | 3df4fa355 + c75c307e0（lineage 读面为 DCPM 会话接续） | 完成：3-Task 候选转正（MEMORY_PROMOTION_MIN_TASKS=3，任务键单源 task_id>run_id>session_id，无任务上下文写入不进候选）+ 世代失效（复用 judgeClauseConflict 全仓唯一确定性冲突判据，零模型调用；旧代 status=superseded 可追溯）+ 人工审阅接通（screenMemoryContent 接 pending propose/confirm 两点，清偿 S7 移交项）；**零 schema 变更**——候选/世代字段落主记忆行 metadata["memoryDiscipline"]，lifecycle 恒 ACTIVE 保持既有读路径；NEUROVA_MEMORY_DISCIPLINE 门控默认 off，关闭态行为与现状一致 | MemCore 主干敬畏达成：不动 MemoryManager 内部结构、不动 LifecycleStage 枚举；转正判定与 S7 准入闸同一装配点；翻默认建议见会话报告 |
| S17 F1 收尾（会话R） | cf1df7e0c | 完成：模型请求级归档——新增 core/request_archive.py 单源（每会话 JSONL <数据根>/request_archives/，默认脱敏摘要不落全文、NEUROVA_REQUEST_ARCHIVE_FULL 门控钩子先落位；后台单写线程 DCL+RLock+有界队列不阻塞调用；写失败 WARNING+计数可见；尺寸上限具名常量）+ multi_model_client chat 三出口/chat_stream 两出口挂点（429 重试与 failover 各自留痕）+ S12 档案聚合增请求归档摘要（写入→读取→反馈闭环） | 独立 trace 面，不往 H-4 事件账本加请求级事件（账本纪律不变）；脱敏复用 S7 SENSITIVE_KEY_PATTERNS 单源 |
| S18 G2 收尾（会话S） | c3dbdaa23 | 完成：MCP 工具壳四件 team_list/team_dispatch/project_list/project_detail——工具壳两层机制单源（转交 ToolExecutor.execute 单管道，治理三明治/审批链/审计/run 溯源与主 agent 原生调用同一条路）；描述与必填参数取自原生 builtin schema 同源不复制；双鉴权照旧；成员面剔除在 MCP 侧同样生效（不可绕过）；红灯 MCP 面缺工具壳→11 用例全绿；A/B 510 passed 零新增；live-verify 9677 真 MCP 握手 team_list→team_dispatch | 原计划 mcp_ontology_server.py 与现场 mcp_surface.py 双落点均属该域；不把内部工具面全量搬上 MCP |
| 追加批 收口（统筹者） | ed43a3b29 + e182c0eba | 四道门核验：trio 35 failed=基线（2747 passed，+20）、api 17 failed=基线（3225 passed，+2）；vitest/vue-tsc 由各前端含批会话自证全绿 | 两笔身份读方台账同步（memory_discipline/request_archive 新合法读点，钉子随契约扩容同步）；全量验证在干净 worktree 完成（主工作树另有会话大规模记忆层重构在途，避免归因污染）；test_loop_manager 偶发 ERROR 经基线 worktree 复现确认=预存顺序依赖偶发，非追加批引入 |
