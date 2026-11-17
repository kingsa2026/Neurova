# 超越 CoworkOS 实施方案（对照评测 H 批后续，细化到可直接执行）

- 日期：2026-11-17
- 依据：
  - [CoworkOS 与 Neurova 多 Agent 协作对照评测](../08-research/coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)（下称"COS 评测"；§6 逐维评分、§6.x 总分表、§7 H 系清单是本方案直接输入）
  - [deepagents 与 Neurova 对照评测](../08-research/deepagents_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)（下称"DA 评测"；其 §8「按本仓代码现状逐条对照的学习落点」是 S5/S6/S7 的规格来源）
  - 真模型基线报告 [multi_agent_bench_baseline_2026-11-17.md](../08-research/multi_agent_bench_baseline_2026-11-17.md)（S1 的输入：T1 不可用、记忆串扰、usage 缺失三条实证）
- 目标：同框评测总分从当前 **84/110** 越过 CoworkOS 的 **95/110**（判定线 ≥96），且不损失既有领先维（A 协作形成 14、E 治理安全 13）。
- 范围：`neurova/agent/`（swarm.py、mailbox.py、swarm_event_log.py、candidate_merge.py 新增、memory_admission.py 新增、loops/base.py、chat_pipeline.py、goal_verifier.py）、`neurova/session_manager.py`、`neurova/context_pool.py`、`neurova/tool_executor.py`、`neurova/mem_core.py`、`neurova/benchmark/multi_agent/`、`tests/unit/`、`docs/08-research/`。
- 执行者须知：本方案按批次（S1–S9）组织，**每批独立可交付、可红绿验证、可单独提交**。开工任何一批前，先读本方案附录 A（共享避坑清单）并对目标文件做撞车复核（`git log --oneline -5 -- <file>` + `git status`）；文中所有 `file:line` 均以**开工当日现场复核为准**（行号会漂移，符号名是锚）。
- 纪律：每项先红后绿（红灯测试实证期望行为，附实测输出）；净新增 LOC 尽量为负或逐条列明去向；live-verify 真链路自证；同根因全命中点扫荡；不建第二套平行体系。

---

## 0. 评估结论与总路线

### 0.1 对初版路线的评估调整（为什么这样排）

初版路线（口述版）提了 8 项。逐项评估后做如下调整：

| 初版项 | 评估结论 | 调整 |
|---|---|---|
| F2 评测体系补全 | 一切改进的红绿验证前提；H-7 已实证三处断点（T1 不可用/记忆串扰/usage 缺失） | **提到最前（S1）**，拆成判据记账（1A/1B）、记忆隔离（1C）、T1 重设计（1D） |
| H-6 压缩纪律 | 最大单点缺口（D3 3vs5），但动会话存储与上下文装配主干，风险最高 | **拆成 S5（会话存储追加式，前置地基）+ S6（压缩纪律）两批**，S5 先行 |
| H-3 候选制 | B5 是最大单子项差距（3vs5）；但"共享应用层 CAS"在本仓的对应物是结果回流面而非文件系统 | **范围收窄为"结果候选制"（S4）**：candidate 对象 + 主侧合并 + 冲突保留，不碰工作区文件 CAS |
| 邮箱语义补全 | mailbox.py 刚完成两阶段改造（H-1），补幂等/优先级/死主回收是顺势小批 | **S2，趁热做** |
| B1/B2 持久化协调 | 把 `_runs` 全量搬库是大手术且 swarm.py 是多会话热区 | **范围收窄（S3）**：生命周期迁移表显式化 + 状态变更复用 H-4 账本归档 + 启动重放收敛，不做全量搬库 |
| H-5 记忆准入 | 动 MemCore 主干须独立方案（H 批已有裁定） | **只做轻量先行（S7）**：写入前拦截，不改记忆内部结构；3-Task 转正另立项 |
| G2 MCP 深度集成 | 产品面大、与协作机制分无关 | **移出本方案**，另立项 |
| H-8 长程目标 park/恢复 | 依赖目标/监督者产品面 | **移出本方案**（维持 P3 登记不变） |
| （新增）S8 审批审计持久化 | E 维是本仓领先维（13vs11），CoworkOS 授权持久化生产面缺失、DA 评测确认其审批也不落审计——这是最能拉开差距的反超点 | **新增 S8** |
| （新增）S9 重评分 | "超越"必须用同框数据宣告，不许凭感觉 | **新增 S9 收尾批** |

### 0.2 批次依赖与并行建议

```
S1 评测地基 ──┬─→ S2 邮箱语义（独立，可并行）
              ├─→ S3 生命周期迁移表/状态归档 ──→ S4 结果候选制（同文件域，建议同会话连做）
              └─→（S1 产出判据供 S9 复用）
S5 会话存储追加式 ──→ S6 压缩纪律（严格依赖 S5 的事件落盘面）
S7 记忆准入（独立，随时可插）
S8 审批审计（独立，随时可插）
S1–S8 全部落地 ──→ S9 重评分与超越判定
```

- 可并行开工会话：S1、S2、S7、S8 互不碰文件域（S2 碰 mailbox/loops，S7 碰 mem_core 写入口，S8 碰审批/审计面）。
- 必须串行：S3→S4（同在 swarm.py 结果/状态面）；S5→S6（同在会话存储与上下文装配面）。
- 规模预估（按一个专注会话计）：S1 中、S2 小、S3 中、S4 中大、S5 大、S6 大、S7 小、S8 小中、S9 小。

### 0.3 涨分预算（诚实口径）

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
| **合计** | | **+8 → 92** | **+16 → 100（封顶前留诚实折扣，按 ≥96 判超越）** |

> 读法：满额路径需要 S1–S8 全部到位且重评时逐子项证据充分。若只做 S1–S4，保守落在 92–94，**尚不足以超越**——S5/S6（D3）与 S4（B5）是绕不开的两座山。评分是每子项 0–5 锚点制，涨分必须以证据支撑（S9 给出逐子项证据清单要求）。

### 0.4 明确不做（防过度工程与违反裁定）

- 不把 `_runs` 全量搬 SQLite/不引入中心化调度常驻服务（进程内架构不变）；
- 不动 MemCore 内部结构（S7 只做写入前拦截；3-Task 候选转正另立项）；
- 不引入 LangGraph/LangChain 等图运行时（DA 评测"不学清单"）；
- 不做 MCP 深度集成与长程目标 park/恢复（已移出，另行立项）；
- 不以削弱治理三明治/工具面收窄换"灵活性"（E 维领先是本仓资产）；
- 不新建第二套压缩/记忆/验收判定体系（复用 context_pool、goal_verifier、review、审批链单源）。

---

## S1 评测地基补全（F2：3→5）

**动机**：H-7 真基线（140 次真实调用）暴露三处 harness 断点——token usage 未进结果、无轨迹效率判据、跨任务记忆串扰污染对照；T1 虚构来源任务对真模型不可用。没有这批，后续所有改进都无法红绿验证、也无法在 S9 重评分。

**现状**：harness 在 `neurova/benchmark/multi_agent/`（runner.py、tasks.py、metrics.py、report.py、suites/）；结果对象 `TaskOutcome` 字段以现场为准；真模型驱动方式见基线报告（临时驱动 + `NEUROVA_DATA_DIR` 隔离 + 清代理 env）。

**改动文件**：`neurova/benchmark/multi_agent/runner.py`、`tasks.py`、`metrics.py`、`report.py`、`tests/unit/benchmark/` 既有测试文件。

**实现要点**
- 1A usage 回传：`TaskOutcome` 增加 `usage` 字段（promptTokens/completionTokens/totalTokens/elapsedSeconds/steps/toolCalls）；solo 从轮次态与 loop 回传取，swarm 从台账行与 trace span 聚合取。mock 桩填 0，真模型读真实 usage。Token 倍数列（报告里现空缺）据此恢复。
- 1B 轨迹效率判据（DA 评测 I-1）：判据 DSL 增加 `expect_trajectory(maxSteps=None, maxToolCalls=None, allowedTools=None)`；数据源**优先复用 P3-2 的 span trace 与 agent_runs 台账计数**，禁止往 H-4 事件账本新增工具级事件（账本纪律：正文与高频细节不进账本）。
- 1C 记忆隔离：runner 增 `taskIsolatedMemory` 模式（每任务独立 agent 实例或独立记忆命名空间，二选一以现场结构定），正式对比默认开启；跑基线时在报告里注明是否隔离。
- 1D T1 重设计：虚构来源标记任务两条路任选其一落地——(a) 提示词内给出真实来源材料，任务改为"依据给定材料归纳"；(b) 判定翻转，"诚实说明无法引用不存在来源"计为得分行为。改 `tasks.py` T1 族任务与判据，mock 测试同步更新。

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
**避坑**：不新造第二套验收判定器（复用 goal_verifier/review，附录 A14）；integrationReport 字段变化会撞契约断言——同批更新；本批与 S3 同在 swarm.py，**同一会话连做**，避免两 会话改同一文件。

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
**避坑**：本批是全方案**风险最高**的一项——务必独立会话专做、先设计后动手；线程锁语义保持既有（附录 A6 的 SQLite 锁纪律不适用于文件，但并发写同一会话文件的锁必须保住）；截断/阈值一律具名常量（附录 A2）。

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
- `requestRunApproval` 与 `decideSwarmApproval` 的每次请求/决定落**审计事件**（复用仓内既有审计单源，以现场复核为准；U1 批已验证审计事件机制可用）：级别、动作、path_values、发起 run、决策人、决策、时延。
- 查询面：挂现有管理/运维查询端点域，**不新开平行端点域**。
- fail-open：审计写失败不阻断审批主流程，但错误必须可见（日志 + 计数），不许静默吞。

**红灯**：新增 `test_approval_audit_persistence.py`——一次 L2 审批从请求到决定产生两条可查审计事件（请求+决定），字段齐全；审计写失败时审批仍可用且错误可见。
**绿灯验收**：审批链既有 18 例全绿；管理查询端点能按 runId 拉出完整审批轨迹。
**避坑**：审计单源——发现第二处审计写点时按教义第 6/7 条收口，不并存。

---

## S9 重评分与超越判定

**动机**："超越"必须以同框口径的数据宣告。

**步骤**
1. 逐子项重评（对照 COS 评测 §6 的锚点与证据格式），每子项给**证据**：file:line、测试名、实测数据（报告字段/日志）——无证据不涨分。
2. 更新 COS 评测文档 §6.x 总分表（保留历轮分数列作走势），补执行记录段（各批次 commit 号）。
3. 判定：合计 **≥96** 即超越成立；未达则列剩余差距与下一轮清单，不降低口径硬凑。
4. 报告更新后按惯例推双远端（origin + github）。

**避坑**：评分锚点看的是"机制是否存在且被消费"（写入→读取→反馈闭环），只落库没人读的机制不涨分——S9 评审时逐项核闭环。

---

## 整合扩展：既有团队/群聊能力接入蜂群（响应用户追加问询，挂靠 S3/S4/S8 执行）

> 结论：**可以整合，且有现成接缝**——但要按「人的监督面 + 共享产物面」整合，**不是**把群聊当多 agent 讨论解题器（AutoSwarm 方案"不做清单"明令禁止：论文实证去中心化讨论 39.32% < 单 agent 60.68%）。

**仓内既有能力（开工前现场复核符号与行号）**
- 协作房间：`neurova/collaboration/room_store.py`（room_id = 协作 project_id 的既有等式，复用 SessionRepository 零新表）、`room_bus.py`（广播）、`room_turn_router.py`（@路由 + 默认应答者，人→agent 已通）。
- 团队名册：`neurova/api/endpoints/teams_api.py`（团队 + 成员 + 每成员职责 prompt + team prompt-context，JSON 落盘）。
- 记忆作用域：`neurova/collaboration/memory_scope.py`（`direct` / `room:<room_id>` / `chgrp:` 三作用域，群群隔离，读写侧共用单源）。
- ACP 多角色编排：`neurova/agent/team.py`（AgentTeam.add_member/orchestrate，task_assignment→task_result，共享 trace_id）。

**接入点（按批挂靠，不另立批次）**
1. **S3/S8 × 房间 = 人在环闭环（B4/E1 受益）**：SwarmManager 的 escalate 与审批链 L1/L2 的 ASK 投递到协作房间（sender_type=system/agent 的房间消息）；人在房间回复 → 经新桥接（approval_chain ↔ room_bus 的 pending-approval 匹配）回灌 `decideSwarmApproval`。审批审计（S8）天然多了一个人类可读的呈现面。红线：房间只做"呈现 + 应答回灌"，判定权仍在审批链单源。
2. **S4 × 房间/项目 = 候选制的产品面（B5 受益）**：CandidateReport 的 submitted/merged/conflict 事件投递到所属房间，人在房间里可直接拦截合并（COS 的 B5 锚点"人工可拦截"由此落地）；artifactKeys 优先指向协作 project 的既有产物空间。
3. **团队名册 × spawn = 动态组队（A1 受益，现分 2vs3）**：spawn 支持从团队名册按成员职责 prompt 选人（list_agents 辅助选人已有），角色复用 `collaboration_template.AgentRole`——补"按任务动态组队"缺口；不引入角色辩护等重机制。
4. **memory_scope × 蜂群 = 共享黑板（D1/D2 受益）**：蜂群 run 的跨成员共享记忆复用 `room:<room_id>` 作用域语义（或并列新增 `run:<run_id>` 作用域，与 room/chgrp 同构），群群隔离与"读单聊基线"语义直接继承，不新造作用域体系。
5. **AgentTeam 与 Swarm 的双实现取舍（教义第 7 条）**：两者定位不同——AgentTeam 是 ACP 面向外部 agent 的步骤编排，Swarm 是进程内子代理治理（评测评分对象）。初步裁定**双轨保留、边界写清**（外部协作 vs 内部蜂群），但 S3/S4 落地时必须复核两者是否出现同功能重复点；出现即按"先比后合"收口，不并存各调各的。

**红灯/验收（随挂靠批走）**：升级与审批消息在房间可见且回复能回灌判定（S3/S8 测试内）；候选合并事件在房间可查、人工拦截生效（S4 测试内）；团队选人 spawn 的测试（S4 或独立小测试）。
**避坑**：房间消息走既有 RoomBus/RoomStore，**零新表零新协议**；不要在房间里做自由讨论式多 agent 解题（违反 AutoSwarm 方案不做清单）；房间持久层复用 SessionRepository，勿另写存储。

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
