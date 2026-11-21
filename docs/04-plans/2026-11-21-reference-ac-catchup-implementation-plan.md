# 参照系 ac（T3 Code）追平与超越实施方案

> **来源**：[reference_ac 对照评测报告](../08-research/reference_ac_vs_neurova_coding_agent_control_plane_evaluation_2026-11-21.md)（2026-11-21，Neurova 72.0 vs T3 Code 92.0，20 子项）。
> **性质**：实施计划（任务卡制），非准则文档。目标=20 个子项**全部平手或超越** T3 Code。
> 行号均为 2026-11-21 现场读数，**每张卡开工前须按当时代码现场复核**；执行一律遵循 AGENTS.md
> 修复教义：先红后绿、A/B 零新增失败、live-verify 真链路自证、`git commit --only` 逐文件点名。
> **命名约定**：卡号直接沿用评测报告子项编号（A1…E3），与评分卡一一对应，便于逐卡复评对账。

---

## 0. 差距速查（2026-11-21 评分）

| 子项 | 本仓 | T3 | 差距 | 批次 |
|---|---|---|---|---|
| A1 生命周期状态机 | 8.0 | 9.5 | −1.5 | 三 |
| A2 事件溯源与审计 | 7.5 | 9.5 | −2.0 | 二 |
| A3 幂等与恢复 | 6.5 | 9.5 | −3.0 | **一** |
| A4 并发治理 | 8.0 | 7.0 | **+1.0 已领先** | 守住 |
| A5 结算与收敛 | 5.5 | 9.0 | −3.5 | 二 |
| B1 子代理建模 | 8.0 | 9.5 | −1.5 | 三 |
| B2 上下文传递 | 4.5 | 9.5 | **−5.0** | **一** |
| B3 checkpoint 回滚 | 7.0 | 9.5 | −2.5 | 二 |
| B4 依赖与队列 | 7.5 | 8.5 | −1.0 | 三 |
| C1 协议覆盖 | 7.5 | 9.5 | −2.0 | 二 |
| C2 能力声明与降级 | 8.5 | 9.5 | −1.0 | 三 |
| C3 进程治理 | 8.0 | 9.5 | −1.5 | 三 |
| C4 认证与凭据 | 8.0 | 9.0 | −1.0 | 三 |
| C5 切换与接续 | 4.5 | 9.5 | **−5.0** | **一** |
| D1 审批链 | 8.5 | 9.0 | −0.5 | 三 |
| D2 权限天花板 | 7.5 | 9.5 | −2.0 | 二 |
| D3 多端与远程 | 8.0 | 9.5 | −1.5 | 三 |
| E1 评测体系 | 7.5 | 8.5 | −1.0 | 三 |
| E2 契约与兼容 | 7.0 | 9.5 | −2.5 | 二 |
| E3 性能与资源治理 | 7.0 | 9.0 | −2.0 | 三 |

预计里程碑：第一批完成 ≈79 分；第二批 ≈88 分；第三批完成 ≈93 分（全项 ≥，且 A4/D1 反超扩大）。

---

## 1. 批次总览与依赖

| 批次 | 卡 | 主题 | 量级 | 依赖 | 需拍板 |
|---|---|---|---|---|---|
| 一 | B2 | 上下文传递工件化 | L | 无 | 是（预算默认值/恢复 API 形态） |
| 一 | C5 | provider 切换五结果决策 | M-L | B2（handoff 工件） | 是（非 admin 是否可切） |
| 一 | A3 | 命令回执幂等 | M | 无 | 否 |
| 二 | A5 | run 自动结算服务 | M | A3（回执） | 是（默认开关/阈值） |
| 二 | B3 | 隐藏 ref 检查点+协同回滚 | M-L | 既有检查点域 | 是（ref 命名/保留数） |
| 二 | A2 | 事件溯源升级 | L | 无 | 是（保留窗口天数） |
| 二 | E2 | 契约单源+兼容纪律 | M | 无 | 否 |
| 二 | D2 | 权限天花板 rank 序 | M | 无 | 是（档位口径统一） |
| 二 | C1 | 协议覆盖补齐 | M | 无 | 是（registry 形态取舍） |
| 三 | C3 | 进程治理强化 | M | 无 | 否 |
| 三 | E3 | 性能与资源治理 | M | 无 | 否 |
| 三 | D3 | 多端订阅自适应 | M | A2 | 否 |
| 三 | B1 | 子代理完成投递 cohort | S-M | 无 | 否 |
| 三 | A1 | 终态质量分级 | S | 无 | 否 |
| 三 | C4 | 凭据闸门+探测无副作用 | S | 无 | 否 |
| 三 | E1 | evals 先 case 后修 | S-M | 无 | 是（付费成本归属） |
| 三 | B4 | 队列治理 | S | 无 | 否 |
| 三 | C2 | 能力维度扩展 | S | C5 | 否 |
| 三 | D1 | 审批记忆式批准+持久化投影 | S-M | 无 | 否 |

并行建议：第一批三卡分属不同文件域（B2/swarm 上下文、C5/neuacp、A3/账本），可三会话并行；
第二批 A2/E2/D2/C1 互不碰域可并行；A5 依赖 A3 合并后开工；第三批除 D3 依赖 A2 外均可并行。

---

## 2. 任务卡

### B2 · 上下文传递工件化（P0，差距 −5.0，最大单项）

- **现状**：跨 run/跨 agent 的上下文交接靠自由文本——`composeTeamDutyTask`（swarm.py:239）拼任务书、
  继续轮提示、`updateSubagent`（swarm.py:1602）steer 注入；无工件、无预算、无省略记录、无投递状态。
  长任务换手/结果回传时上下文丢失或超窗不可控。
- **方案**（对齐 T3 `ContextTransfer`/`ContextHandoff`/`handoffBudget` 三件套）：
  1. 新模块 `neurova/agent/context_transfer.py`：`ContextTransfer`（廉价登记：transferId/type/
     sourcePoint{threadId,runId,checkpointId}/resolution/status=pending）与 `ContextHandoff`
     （物化：strategy ∈ delta_since_last_seen|full_summary|checkpoint_summary|manual_context、
     summaryText、history、omittedItemIds、delivery{status: pending|injected|inline}）。
  2. 触发点接入：`updateSubagent` steer/restart、子代理结果回传（pushParentMail 链路）、
     neuacp 成员二次 chat 会话复用、失败重派。
  3. 预算：`handoffBudget = min(tokenCap, byteCap, window − 既有占用 − 本轮输入 − 预留)`；
     默认 tokenCap=16000（`NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP` 可配，夹 [1024, 64000]）；
     超限**报错不静默截断**。
  4. 省略不丢弃：放不下的条目记 `omittedItemIds`，恢复走既有请求级归档/会话时间线读取协议。
  5. 投递三态：native inject（外部 agent 会话支持时）/ inline 前缀（拼进下一条 prompt，标注
     为交接上下文非用户输入）/ uncertain（结果不可证时换新会话重投，绝不重复投递）。
- **红绿判据**：`tests/unit/agent/test_context_handoff_budget.py`（预算计算：多语言字节成本/
  图片预留/窗口变化；超限抛 `ContextHandoffBudgetError` 不截断）+ `test_context_handoff_delivery.py`
  （三态投递、uncertain 换会话、重试不重复投递、omitted 可恢复）。
- **验收**：swarm 派活→子代理→结果回传→父代理续跑全链 live-verify；中途换 provider 成员时
  下一个 run 能收到带 coverage 标注的交接摘要。
- **量级** L；**依赖** 无；**需拍板**：预算默认值、恢复 API 形态（走既有归档读面还是新端点）。

### C5 · provider 切换五结果决策（P0，差距 −5.0）

- **现状**：仅有模型切换记账（`agent_run_ledger.adoptsModelSwitchForEntry`）；成员中途换
  executor/换模型无决策函数，跨 provider 会话接续缺失——换家即丢会话上下文。
- **方案**：`neuacp/catalog.py` 增加 `decideProviderTransition(current, target) ->`
  `reuse | switch_model_in_session | restart_and_resume | create_with_handoff | reject`：
  1. 同 executor 同会话换模型 → `switch_model_in_session`（能力声明支持时）；
  2. 同 executor 进程可复用且 session_reuse → `reuse`；
  3. 同 executor 但会话不可复用 → `restart_and_resume`（resume 能力声明支持时）；
  4. 跨 executor → `create_with_handoff`（必须能产出 B2 的 handoff 工件，否则 `reject`）；
  5. 目标能力缺失（installed=false / 保守档）→ `reject`（fail-closed，报 422 级结构化原因）。
  判定输入全部来自 catalog 既有能力声明（transports/streaming/resume/session_reuse），
  不新增第二份能力口径（教义第 6 条）。
- **红绿判据**：`tests/unit/agent/test_provider_transition_decision.py`——五结果逐表断言 +
  能力缺失拒绝 + 与 catalog 声明一致性（改声明不改决策即红）。
- **验收**：live-verify 同一 team 成员从 OpenCode 切到 ZCode（plugin），下一条消息带上一段
  handoff 摘要继续执行；切到未安装 provider 时打开前被拒。
- **量级** M-L；**依赖** B2；**需拍板**：非 admin 是否允许中途切换（对齐 auto 模式 admin 专属先例）。

### A3 · 命令回执幂等（P0，差距 −3.0）

- **现状**：swarm 派活/审批应答/候选合并等写路径无命令级幂等：网络重试或 WS 重连可能重复
  派活、重复应答。候选合并已有 CAS（baseRevision==revision），但仅覆盖候选一域。
- **方案**：新模块 `neurova/core/command_receipt.py`：SQLite 表
  `command_receipt(command_id PK, command_type, thread_id, status accepted|rejected,
  result_sequence, created_at)`。写路径入口先 `insertIfAbsent`（事务内，冲突即取既有回执），
  命中回执直接返回上次结果（附 `replayed: true`），不重跑副作用；拒绝也落回执（防同 ID 反复
  打穿），仅"模式/参数类可修正错误"豁免不落回执。接入点：`dispatchTeam`（swarm.py:718）、
  `updateSubagent`、`cancelRun`（swarm.py:1484）、审批应答 `decideSwarmApproval`、候选合并。
  command_id 由调用方生成（前端/工具调用 UUID），服务端做 thread_id 一致性校验（不一致报
  conflict）。
- **红绿判据**：`tests/unit/core/test_command_receipt_idempotency.py`——同 ID 重放返回同结果
  且副作用计数为 1；并发同 ID 仅一条生效；跨 thread 同 ID 报 conflict；拒绝回执阻断重试。
- **验收**：live-verify 对同一 dispatchTeam 请求重发两次，仅产生一个 run；审批应答重发不重复记账。
- **量级** M；**依赖** 无；**需拍板** 否。

### A5 · run 自动结算服务（P1，差距 −3.5）

- **现状**：run 终态依赖显式推进；无 idle/合并触发的自动收敛，长期挂起的 run 占用并发与台账。
- **方案**：新模块 `neurova/agent/run_settlement.py`：定时 sweep（走既有 TaskScheduler，注意
  惰性单例必须显式 start 的历史坑）+ 事件触发双驱动。触发条件：run 完成后 N 天无活动，或
  关联产物已合并。**护栏一票否决**：活跃 run、pending 审批、置顶、显式豁免、排队中任务、
  2 分钟排队宽限期内不结算；结算动作 = 关终端/释放进程池占用/台账落 `settled`（走
  `transitionRun` 状态机，不绕过 `RUN_STATUS_TRANSITIONS`）；提交前 live 二次校验
  （快照后状态已变即放弃）。
- **红绿判据**：`tests/unit/agent/test_run_settlement_guards.py`——九类护栏逐条断言 + live
  复核竞态（结算前状态变化即弃）+ 幂等（重复 sweep 不重复落账）。
- **验收**：真后端造一个完成后的 idle run，sweep 后进 `settled` 且进程池释放；pending 审批的
  run 不被结算。
- **量级** M；**依赖** A3；**需拍板**：默认开关（建议默认关、admin 可开）与 idle 阈值天数。

### B3 · 隐藏 ref 检查点 + 协同回滚（P1，差距 −2.5）

- **现状**：检查点回滚域已有基础实现（四域修复 K 系落地），但检查点形态与 provider 会话
  回退协同、共享工作区隔离检查尚缺。
- **方案**：
  1. 检查点落隐藏 ref `refs/neurova/checkpoints/<base64url(sha256(scopeId))[:32]>/ordinal/<N>`
     ——不占分支名、不进工作树；按 scope+ordinal 命名支持增量 diff。
  2. 回滚协调：先探外部 agent 会话是否支持对话回退（能力声明 `resume`/会话回退项，无则
     **拒绝回滚**再动文件系统——T3 纪律：不能回退会话的 provider 不得先改文件）；再恢复
     文件、回写台账、清理 stale ref。
  3. 隔离检查：恢复前校验 cwd 归属——与其他 run/成员共享同一工作区时只允许"会话级回退"，
     不动文件（防误伤并行工作）。
- **红绿判据**：`tests/unit/agent/test_checkpoint_hidden_ref.py`（ref 命名/增量/stale 清理）+
  `test_checkpoint_rollback_coordination.py`（会话不可回退即拒、隔离检查、ordinal 回退后台账
  状态同步）。
- **验收**：live-verify 对真 git 仓库做 capture→改文件→rollback，工作区与台账一致、用户分支
  无多余提交。
- **量级** M-L；**依赖** 既有检查点域；**需拍板**：ref 命名空间与每 scope 保留数量（建议 20）。

### A2 · 事件溯源升级（P1，差距 −2.0）

- **现状**：H-4 账本（`swarm_event_log.py`，逐 run JSONL，appendRunEvent/readRunEvents）+
  span trace + 请求级归档已可用；但事件分散、无全局 sequence、投影不可从事件重建、断线
  重连无"重放 or 快照"协议。
- **方案**：
  1. `swarm_event_log.py` 增加**全局单调 sequence**（SQLite `event_store(seq AUTOINCREMENT,
     stream_id, type, payload_json, command_id, created_at)`），逐 run JSONL 保留为投影；
  2. 投影可重建：`rebuildProjection(streamId)` 从事件重放；ProjectionMaintenance 定期清理
     超窗事件（默认保留 1 天，**先发布 pruned-through 边界再删**，保护流头与 prompt 锚点）；
  3. 订阅协议：WS/轮询消费方带 `afterSequence`；cursor 有效→增量重放，过旧/超预算→
     全量快照降级（绝无部分重放）。
- **红绿判据**：`tests/unit/agent/test_event_store_replay.py`（全局序、按流重放、去重）+
  `test_event_prune_boundary.py`（边界先发布、锚点保留、cursor 过旧降级快照）。
- **验收**：杀进程重启后，消费方凭 cursor 重放不丢事件；超窗 cursor 明确收到快照降级信号。
- **量级** L；**依赖** 无；**需拍板**：保留窗口天数（建议 1 天对齐 T3）与是否 immediate 全量切换
  （建议灰度双写）。

### E2 · 契约单源 + 兼容纪律（P1，差距 −2.5）

- **现状**：API 契约靠 OpenAPI/对齐测试；缺"改 schema 必须同时照顾存量客户端与存量数据"
  的显式纪律与回放兼容测试。
- **方案**：契约 schema 单源化盘点（前后端共享字段清单收口到一份）；新增"wire 兼容守卫"
  测试——对历史归档样例（请求级归档 JSONL 抽样）做新代码解码回归；破坏性变更必须在
  PR 说明中列迁移路径。落点：`tests/unit/` 契约守卫目录 + `docs/` 契约变更记录。
- **红绿判据**：`tests/unit/api/test_wire_backward_compat.py`——历史样例解码不丟字段；
  删字段/改类型未登记迁移路径即红。
- **量级** M；**依赖** 无；**需拍板** 否。

### D2 · 权限天花板 rank 序（P1，差距 −2.0）

- **现状**：有成员门、MAIN_AGENT_ONLY_TOOLS、租户隔离红线；但权限档位无"天花板只能收窄"
  的全链路判定（父任务授权不能被子任务放大）。
- **方案**：`approval_chain.py` 增加 `RuntimeMode` 序（如 supervised < auto_edits < auto <
  full_access 的 rank），`isModeAbove(mode, ceiling)`；派活链路上子任务 mode 不得超过父任务
  ceiling，组织策略可再封顶；provider 不支持的档位自动降为 supervised（诚实降档，不静默放大）。
  与既有 `NEUROVA_SWARM_APPROVAL_MODE`（interactive/auto_approve）统一口径——旧模式映射进
  新 rank（避免双套口径，教义第 6 条）。
- **红绿判据**：`tests/unit/agent/test_permission_ceiling.py`——子任务越顶被拒；managed 封顶
  生效；不支持档位降档；旧模式映射兼容。
- **量级** M；**依赖** 无；**需拍板**：是（档位口径如何与既有 approval mode 合并，影响配置面）。

### C1 · 协议覆盖补齐（P1，差距 −2.0）

- **现状**：ACP v1 stdio+SSH+plugin(ZCode)；P0 四家（OpenCode/Qoder/CodeBuddy/ZCode）已通，
  P1 三家（Gemini/Claude/Codex）预设已入库但真 CLI 握手待启用。
- **方案**：启用三家真 CLI 握手与 live-verify（各家官方 ACP/适配器口径）；评估 ACP registry
  形态——若生态成熟，新增"registry 通用接入"（按 agent 目录自动发现+风味差异），新 agent
  接入成本从"写一个包"降到"写一份声明"。
- **红绿判据**：`tests/unit/agent/test_neuacp_catalog_probes.py` 扩三家探测；真握手走
  live-verify（不入 CI，marker 隔离）。
- **量级** M；**依赖** 无；**需拍板**：是（registry 形态是否立项，涉及依赖与安装策略）。

### C3 · 进程治理强化（P2，差距 −1.5）

- **现状**：`acp_client.py` 有 terminate/kill、fail-closed、stderr 尾、单帧上限；进程池有租户键
  复用。缺：进程组级回收（子进程孵化孙进程的孤儿问题）、统一超时矩阵、重试总预算、OOM 失败
  诚实改写。
- **方案**：terminate 升级为进程组/作业对象回收（Windows `taskkill /T /F`、POSIX
  `killpg`+grace+SIGKILL）；超时矩阵常量单源（握手/请求/取消/退出宽限）；重试加总预算
  （超预算即 fail，不只数次数）；OOM 识别改写失败原因（诚实标注）。
- **红绿判据**：`tests/unit/agent/test_process_group_termination.py`（孙进程回收）+
  `test_retry_budget.py`（总预算封顶）。
- **量级** M；**依赖** 无；**需拍板** 否。

### E3 · 性能与资源治理（P2，差距 −2.0）

- **现状**：前端有 bundle 预算棘轮（真构建标定）；WS 推送无压缩协商、订阅无预算约束。
- **方案**：WS 消息 gzip 压缩协商 + 订阅回放字节预算（超预算降快照，与 A2 协同）；前端建立
  "关键列表渲染回归门"（大列表分页/虚拟化抽查）；后端单事件编码字节上限。
- **红绿判据**：`tests/unit/api/test_ws_stream_budget.py`（回放超预算降级、压缩协商）。
- **量级** M；**依赖** A2（订阅协议）；**需拍板** 否。

### D3 · 多端订阅自适应（P2，差距 −1.5）

- **现状**：PC/鸿蒙/安卓三端已通；断线重连缺统一 cursor 语义，弱端（移动网络）无稳态降级。
- **方案**：三端统一"afterSequence cursor + 服务端 replay/snapshot 自适应"（依赖 A2）；
  移动端 steady 化（列表行保持已显示状态直到新快照到达）；断线重连指数退避+jitter 单源。
- **红绿判据**：`tests/unit/api/test_subscription_resume.py`（cursor 有效重放/过旧快照/去重）。
- **量级** M；**依赖** A2；**需拍板** 否。

### B1 · 子代理完成投递 cohort（P2，差距 −1.5）

- **现状**：子代理结果经 `pushParentMail`（swarm.py:2744）投父邮箱；父 run 已结束时投递可能
  静默丢失（信箱无 ack/重投语义）。
- **方案**：投递状态机 `pending→claimed→acknowledged|disposed`：结果先落投递单（含目标父
  run/generation），父侧确认（acknowledge）才销账；父 run 结束时的 catch-up 补投一次；
  dispose 显式弃投并留痕。
- **红绿判据**：`tests/unit/agent/test_delegated_completion_delivery.py`（父忙挂起/父闲补投/
  重复投递去重/dispose 留痕）。
- **量级** S-M；**依赖** 无；**需拍板** 否。

### A1 · 终态质量分级（P2，差距 −1.5）

- **现状**：`RUN_STATUS_TRANSITIONS`（swarm_support.py:54）十态内收敛；缺"终态可信度"分级
  （正常完成 vs 超时兜底 vs 推断），导致上层把弱终态当强终态消费。
- **方案**：run 终态增加 `terminalQuality: strong|weak|none` 标注（strong=provider 明确完成；
  weak=超时/崩溃兜底推断；none=无依据），由 `transitionRun` 写入；验收门/评审门按质量分级
  决定是否需要复核。
- **红绿判据**：`tests/unit/agent/test_terminal_quality.py`（各终态来源→质量分级断言）。
- **量级** S；**依赖** 无；**需拍板** 否。

### C4 · 凭据闸门 + 探测无副作用（P2，差距 −1.0）

- **现状**：keyring 按数据根派生、凭据后缀展开已落地；探测（catalog installed 检查、管理面
  /test 握手）与真实启用未显式分离，存在探测触发重型副作用的风险。
- **方案**：catalog 探测仅做 `shutil.which` 级存在性检查（现状态确认）；新增纪律测试——
  探测/状态轮询路径禁止触发 spawn、登录、MCP 启动（AST 或调用图断言）；凭据变更期间
  新会话启动被闸（withAccess 语义）排队或拒绝。
- **红绿判据**：`tests/unit/agent/test_probe_no_side_effects.py`（探测路径零 spawn 断言）+
  `test_credential_change_gate.py`。
- **量级** S；**依赖** 无；**需拍板** 否。

### E1 · evals 先 case 后修（P2，差距 −1.0）

- **现状**：suite_eval 执行器 + APEX 任务集已可用；"改模型所见文本必须先加会失败的 case"
  未成纪律。
- **方案**：把纪律写进 AGENTS.md 测试节（三落点同步）；suite_eval 增加"case 先行"检查项——
  影响工具描述/任务书/验收 rubric 的 PR 须附对应 eval case（旧文本红、新文本绿）；case 带
  来源标注（Issue/事故/评审）。
- **红绿判据**：`tests/unit/evals/test_eval_case_discipline.py`（case 注册与红绿自检）。
- **量级** S-M；**依赖** 无；**需拍板**：是（付费模型评测的成本归属与默认开关）。

### B4 · 队列治理（P2，差距 −1.0）

- **现状**：run 有排队语义；缺 reorder/cancel/edit 等队列管理面。
- **方案**：排队 run 支持优先级调整、取消、任务书修订（修订走 steer 或重排，能力不支持时
  诚实排队）；管理面透出队列位置。
- **红绿判据**：`tests/unit/agent/test_run_queue_management.py`（reorder/cancel/edit 三操作
  + 不支持 steer 时的排队行为）。
- **量级** S；**依赖** 无；**需拍板** 否。

### C2 · 能力维度扩展（P2，差距 −1.0）

- **现状**：catalog 能力目录五维（transports/permission_modes/streaming/resume/session_reuse）
  + 保守缺省 + 打开前双闸。
- **方案**：扩展 C5/B2/B3 所需维度：`model_switch_in_session`、`conversation_rollback`、
  `handoff_inject`、`steer`、`fork`；保守缺省同步扩展；打开前双闸按新维度校验。
- **红绿判据**：`tests/unit/agent/test_capability_profile_expansion.py`（新维度缺省保守、
  决策函数消费一致性）。
- **量级** S；**依赖** C5；**需拍板** 否。

### D1 · 审批记忆式批准 + 持久化投影（P2，差距 −0.5，反超候选）

- **现状**：L0/L1/L2 分级 + 房间多人回灌 + ApprovalManager 单源已领先；缺同会话/同团队
  "免再批"（每次同类操作都重新弹批）与审批请求的投影化读面。
- **方案**：`acceptForSession`（本 run 内同类放行）/`acceptAlways`（本团队配置化放行，可撤销）
  两档决策加入审批链；放行范围**只降不升**（L2 永不记忆式放行）；审批单投影化读面
  （列表/详情/撤销）供前端与房间复用。
- **红绿判据**：`tests/unit/agent/test_approval_memory_grants.py`（记忆放行范围、L2 不适用、
  撤销即失效、房间回灌兼容）。
- **量级** S-M；**依赖** 无；**需拍板** 否（L2 永不记忆为红线，无需求拍板）。

---

## 3. 明确不做 / 防扩 scope

1. **不引入 Effect-TS 或重写编排技术栈**——本仓 Python/SQLite 基座不动，只借鉴语义。
2. **不做万行巨石文件**——新逻辑一律落独立模块（`context_transfer.py`/`command_receipt.py`/
   `run_settlement.py` 等），守住 `agent_core.py` 尺寸棘轮。
3. **不做云中继推送依赖**——手机审批推送走既有 relay 自托管路线，不引入 T3 Connect 式云服务。
4. **不造第二套 ACP 协议层**——registry 形态若立项也复用 `neuacp` 既有客户端。
5. **不引入 full-access 默认档**——保持 fail-closed 保守缺省；T3 的 full-access 取向不学。
6. **不为追分做表面工程**——每张卡的红绿判据咬合行为，不写"为评分而评分"的展示性改动。

## 4. 交付定义（每张卡相同）

- 先红后绿：红灯测试实证失败 → 最小实现转绿 → 重构；提交说明附红/绿实测输出与净 LOC 去向。
- A/B 自证：`git stash push <涉改共享文件> && pytest <套件> && git stash pop`，失败集合逐行
  比对零新增（共享树在途改动多，用 patch 法防 stash 竞态）。
- live-verify：真后端（`.venv` 解释器、清代理变量、`[ERROR]=0` + `/v1/providers` 注册行判据）
  走通本卡验收链路，证据进提交说明。
- 提交：Conventional Commits，`git commit --only` 逐文件点名，严禁 `git add -A`。

## 5. 待拍板项汇总

| # | 卡 | 问题 | 选项与影响面 | 建议 |
|---|---|---|---|---|
| D-A | B2 | handoff 预算默认值与恢复 API 形态 | 16k token 起步 vs 更大；恢复走既有归档读面 vs 新端点 | 16k + 复用归档读面（零新表） |
| D-B | C5 | 非 admin 是否可中途切换 provider | 开放→灵活但有成本失控面；仅 admin→保守 | 仅 admin（对齐 auto 模式先例），后续再放开 |
| D-C | A5 | 自动结算默认开关与 idle 阈值 | 默认开（省资源但有误收风险）vs 默认关 | 默认关+admin 可开，阈值 3 天可配 |
| D-D | B3 | 检查点 ref 命名与保留数量 | 每 scope 保留 20 vs 全量 | 20，超序淘汰最旧 |
| D-E | A2 | 事件保留窗口与切换方式 | 1 天+灰度双写 vs 一次切换 | 1 天+灰度双写 |
| D-F | D2 | 权限档位与既有 approval mode 合并口径 | 新旧并行（两套）vs 旧模式映射进新 rank | 映射进新 rank（单一事实源） |
| D-G | C1 | ACP registry 形态是否立项 | 立项（接入成本降）vs 维持逐家预设 | 先启用三家真握手，registry 另评估 |
| D-H | E1 | evals 付费成本归属与默认开关 | CI 跑 vs 手动跑 | 手动跑+成本标注，CI 只跑 grader 单测 |

**拍板结果（2026-11-21，用户交互确认）**：D-A=**预算提高到 32k token**（已落地，env 覆盖不变）；D-B=**放开非 admin 切换 provider，但必须按租户隔离**（派生时能力档快照+续跑五结果决策+跨租户拒绝/admin 豁免留审计）；D-C=维持默认关+3 天；D-D=维持每 scope 20；D-E=维持 1 天+灰度双写；D-F=维持映射单源；D-G=**探测本机装了哪家就验哪家**（已执行：opencode 1.2.27 与 claude-code/codex 适配器（npx 缓存）三家真握手 live-verify——首跑暴露真互操作缺陷（protocolVersion 应为整数，本仓发字符串被真 CLI -32602 拒绝）已根修，复跑三家全 PASS；gemini-cli 未装如实登记）；D-H=维持手动跑+成本标注。

## 6. 复评机制

每完成一批，用评测报告同一评分卡（20 子项）对照 T3 Code **当期主干**复评一次（T3 仍在活跃
迭代，分数是移动目标）；复评结果补记进评测报告"复评记录"节。全部子项 ≥ T3 当期读数即宣告
目标达成，转入常态跟踪（每季度或 T3 大版本时复评）。

---

## 执行记录（按卡补记）

| 卡 | 状态 | commit | 备注 |
|---|---|---|---|
| B2 | **已实施（本笔）** | 本笔提交 | 模块 `neurova/agent/context_transfer.py`（285 行：ContextTransfer/ContextHandoff/预算/三态投递）+ 34 测试；接线点=`resumeFinishedRun`（旧 `report[:4000]` 裸截断升级为工件化交接：登记/预算/inline 投递/`context_transfer` 事件留痕；预算失败诚实降级不静默截断）；待拍板 D-A 按建议值落地（16k token 上限，`NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP` 可配） |
| C5 | **已实施（本笔）** | 本笔提交 | `catalog.decideProviderTransition` 五结果决策（+46 行，纯追加）+ 19 测试；接线点=`resumeFinishedRun` 续跑能力门（外部成员无 session_reuse/resume 诚实拒绝，本仓 agent 不设限）；D-B 按建议值落地（本轮未开放非 admin 切换，跨 executor 因 `handoff_inject` 未声明暂 reject——保守正确，待 C2 补声明） |
| A3 | **已实施（本笔）** | 本笔提交 | `neurova/core/command_receipt.py`（running/accepted/rejected 三态回执 + 同步/async 双入口 + db_migration v1 独立域）+ 13 测试；接线点=`dispatchTeam`/`updateSubagent`/`cancelRun` 可选 `command_id`（缺省原行为零破坏）+ `dispatch_team`/`continue_subagent`/`cancel_subagent` 工具面透传 |
| 集成 | **已验证（本笔）** | 本笔提交 | 接线集成测试 8 用例全绿；agent 域全量回归 2390 passed（2 失败经 A/B stash 证实为预存、与本批无关：turnIdentity 守卫系其他在途域新增读方未登记、acp_client 帧钩子系顺序污染 flaky）；live-verify 真 create_app+uvicorn 14/14 PASS（health/providers/建队 REST/回执三态/续跑交接/能力门两态） |
| A5 | **已实施（本笔·批二）** | 本笔提交 | `neurova/agent/run_settlement.py`（148 行：九护栏纯函数+settings 解析+sweep 编排）+ 44 测试；接线=SwarmManager.settleIdleRuns（结算=逐出内存台账+auto_settled 留痕，**不新增状态词**——本仓终态无出边，T3 的 settled 语义以归档收敛落地）+ TaskScheduler 每小时 job（仅开关开启时注册，默认关零污染）；待拍板 D-C 按建议值（默认关/3 天） |
| B3 | **已实施（本笔·批二）** | 本笔提交 | `checkpoints/service.py` +158（scopeRefFor 确定性命名/captureScope/restoreScope/listScopeOrdinals/pruneScope(保留 20)/rollbackScope 隔离回滚）+ repository.py +13（updateRefRaw，六段 ref 过既有四段白名单）+ 22 测试（真 git plumbing）；隔离检查=共享工作区只许会话级回退；待拍板 D-D 按建议值（保留 20） |
| A2 | **已实施（本笔·批二）** | 本笔提交 | `neurova/agent/swarm_event_store.py`（334 行：全局单调 seq SQLite 库+after_seq 重放+预算降级快照+pruned-through 先发布再删+每流流头保护+mirrorFromLedger 幂等镜像）+ 31 测试；接线=_logRunEvent 统一写点双写镜像（fail-open，JSONL 仍是一手事实源）；待拍板 D-E 按建议值（保留 1 天） |
| E2 | **已实施（本笔·批二）** | 本笔提交 | `tests/unit/api/test_wire_backward_compat.py` 14 守卫（SubAgentRun.to_dict 历史键集/runEvents 结构/蜂群三工具 schema required 不缩水/command_id 增量可选）+ 红灯实证（注入假历史键守卫变红）；配套 `docs/09-dev-progress/contract-change-log.md` 登记表（批一/批二 4 条变更全向后兼容） |
| D2 | **已实施（本笔·批二）** | 本笔提交 | `permission_mode.py` +76（orgCeiling/applyOrgCeiling/delegateMode/approvalModeToPermission/neuacpPermissionToPermission，序复用既有 _STRICTNESS 单源，AUTO 预留档永不启用）+ 77 测试；接线=tool_executor.delegatedModeScope（三处派活入口统一走"生效模式→组织天花板封顶→继承链"，`NEUROVA_PERMISSION_CEILING` 注入）；待拍板 D-F 按建议值（旧档映射不并存） |
| C1 | **已实施（本笔·批二）** | 本笔提交 | `catalog.py` +128（probeToolHealth 无副作用探测 which+--version/超时杀/presetHandshakeProfiles 三家档案，unknown 字段不臆造）+ 16 测试；待拍板 D-G 按建议值（三家真握手 live-verify 视本机安装情况另做，registry 形态另行评估） |
| 批二验证 | **已验证（本笔）** | 本笔提交 | 批二相关套件 1434 passed；agent 域全量回归见本表集成行之后补记；live-verify 真 create_app+uvicorn 12/12 PASS（health/建队/D2 天花板压制/派活/A2 镜像/A5 结算三断言/B3 文件回滚+隔离回退/C1 探测诚实结构） |
| C3 | **已实施（本笔·批三）** | 本笔提交 | `neurova/agent/neuacp/process_governance.py`（221 行：TIMEOUT_MATRIX 超时单源/terminateProcessGroup 进程组回收〔Win taskkill /T /F、POSIX killpg+宽限+SIGKILL〕/RetryBudget 总预算/classifyFailure OOM 诚实分类）+ acp_client 接线（terminate 走进程组杀、超时读矩阵、fail-closed 前 OOM 改写、request 重试预算默认 1 次行为不变、start_new_session 进程组安全前提）+ 21 测试（含真子+孙进程活体回收）；顺带收口 plugin_executor/external_agents_api 两份重复退出宽限常量归 TIMEOUT_MATRIX（教义第 6 条） |
| C2 | **已实施（本笔·批三）** | 本笔提交 | catalog 能力维度扩展：model_switch_in_session/conversation_rollback/steer/fork 四新维（保守缺省 False，三家预设全部诚实缺省不臆造）+ refuseExecutorSpec 按 BOOLEAN_CAPABILITY_DIMS 单源逐维双闸 + decideProviderTransition 消费（缺声明→保守 reject，switch_model_in_session 需显式声明）；能力出口真值才透出（既有五键契约不被稀释） |
| C4 | **已实施（本笔·批三）** | 本笔提交 | `neurova/agent/neuacp/credential_gate.py`（81 行：凭据旋转闸门 begin/end/isRotationActive/assertNoRotation，RLock）+ probeToolHealth 浅/深分级（默认 which 级零子进程，deep=True 管理面 /test 专用）+ acp_member.chat 顶部闸门接线（轮换期新会话诚实拒绝）；test_probe_no_side_effects 行为+AST 双断言 |
| E3 | **已实施（本笔·批三）+深化** | 本笔提交 | `neurova/api/ws_stream_budget.py`（164 行：negotiateCompression gzip 协商/enforceEventCap 单事件 64KiB 上限诚实占位/ReplayByteBudget 回放字节预算）接 ssePushStream（默认参数零行为差异；超预算发 snapshot_downgrade 通告转快照，与 A2 replayThrough 预算语义协同）；修真问题=降级通告游标只按已外发帧推进（防客户端续传漏帧）；**深化：前端「关键列表渲染回归门」落地——AgentListPage/LogPage/KnowledgePage 三门（大数据集断言渲染有界+分页参数），变异法红→绿实证；勘察登记两项无界渲染遗留（ChatSessionSidebar 会话列表全量 v-for/API limit 未传、SubAgentPanel 事件时间线全量 v-for）留待单独立卡** |
| D3 | **已实施（本笔·批三）** | 本笔提交 | `neurova/api/subscription_resume.py`（159 行：resolveResumeMode cursor 续传决策〔pruned/ahead/budget→snapshot，无缝衔接→replay〕/reconnectBackoff 三端退避单源〔0.5×2^n 封顶 30s ±20% 抖动〕/dedupBySequence 去重保序）+ mobile_ws_ledger.oldestSeq/resolveResume + mobile_pairing sync_resume 接线（快照必要时诚实下发 sync_snapshot_required，不做会漏帧的部分重放） |
| B1 | **已实施（本笔·批三）** | 本笔提交 | `neurova/agent/delegated_delivery.py`（221 行：投递单状态机 pending→claimed→acknowledged\|disposed + catchUp 每单限一次 + 逐单 audit trail + messageId 幂等）接 pushParentMail 唯一写点（嵌套派生入箱即 claimed/失败 dispose 留痕/父已终态即时补投）+ _execute finally 终态补扫（父收工时子结果不再静默丢失） |
| B4 | **已实施（本笔·批三）+深化** | 本笔提交 | `neurova/agent/run_queue.py`（158 行：优先级档位复用 mailbox.PRIORITY_RANK 单源/位次读数/取消留痕/任务书修订三态 requeued\|steered\|rejected）+ SwarmManager 管理面（runQueueSnapshot/setRunQueuePriority/cancelQueuedRun 落诚实终态/editRunTask 在跑走 steer 队列）+ spawn 两处入队点与 member_started/终态出队；**深化：管理面 REST `/v1/swarm-queue`（GET 快照/PATCH 优先级/DELETE 取消/POST 任务书修订，admin 门，未知 404，在跑 steer 不可达 200+rejected）+ status 投影透出 queue_position** |
| A1 | **已实施（本笔·批三）+深化** | 本笔提交 | swarm_support 终态质量分级：classifyTerminalQuality（strong=正常完成〔STRONG_COMPLETION_CAUSES 含主链路完成仪式 candidate_merged〕/weak=超时取消兜底或可疑成因/none=无成因）由 transitionRun 终态写入 + requiresReviewConfirmation 复核判定；消费=terminal 事件留痕 + _uplinkEnvelope 信封投影 + status 投影；**深化：依赖门（_depSatisfied）消费质量分级——weak/none 前置不再自动放行下游（须复核），历史空值向后兼容；顺带根修「依赖全部已满足时 spawn 崩溃（blockedId 未赋值 UnboundLocalError）」预存 bug** |
| D1 | **已实施（本笔·批三）** | 本笔提交 | approval_chain 记忆式批准（acceptForSession 会话档/acceptAlways 团队档/revokeGrant/matchGrant + projectRunApprovals/projectTeamGrants 投影读面，+418 行）——**L2 永不记忆双层红线**（创建入口拒绝+匹配面不命中）、只降不升（L1 覆盖 L0）、通配按冒号边界；团队档持久化数据根 JSON（.tmp+os.replace 原子写，损坏 fail-closed）；决策集成 requestRunApproval 弹批前，decision_source=memory_grant 审计留痕 |
| E1 | **已实施（本笔·批三）** | 本笔提交 | suite_eval「先 case 后修」机制：EvalCase（subject_id/source 必填/cost_hint）+ registerEvalCase/validateCaseFirst 覆盖检查/assertCaseRedGreen 红绿自检 + runSuite costNote 成本标注；纪律句三落点同步（AGENTS.md §4/.cnb settings 六角色 prompt/CONTRIBUTING.md）；待拍板 D-H 按建议值落地（评测手动跑+成本标注，CI 只跑判据单测，不接付费跑） |
| 批三验证 | **已验证（本笔）** | 本笔提交 | 批三 13 个新测试文件 217 passed；agent 域全量 2652 passed（唯一失败=预存 turnIdentity，批二已甄别）；api 域 3516 passed；neuacp/benchmark/approval/evals/collaboration 276 passed（唯一失败=预存 acp_client 帧钩子时序 flaky，单跑 2 败 1 过实证竞态非回归）；live-verify 真后端+真数据根 11/11 PASS（B1 真邮箱全链/B4 队列/A1 分级/C3 真进程组回收+OOM 分类/C4 零副作用探测+闸门/D1 L2 红线+撤销/E1 红绿自检/E3+D3 预算续传/两端点活体） |
| 其余 | 未开工 | — | 无——19 卡全部实施完毕；下一步=对照 T3 当期主干复评（评分卡 20 子项） |
| 复评 | **已复评（部分达成）** | — | 对照 T3 当期主干 `6f94a063`（2026-11-20 20:42 -0800）完成 20 子项客观复评：Neurova 72.0→**84.5**，T3 92.0→91.8（D/E 类合计按子项和口径修正）；16 项仍落后（尾差 −0.5~−1.5）、B4/D1/E1 拉平、A4 反超保持（+1.0）——「全部 ≥」目标未达成；剩余差距=接线广度（B2 多触发点/C5 活体 handoff/C1 三家真握手）+体系深度（A2 单写事件溯源/A3 effect outbox/E2 契约单源/E3 性能回归门/C3 cgroup）；逐项证据与判定详见评测报告「## 复评记录（2026-11-21，对照 T3 当期主干 6f94a063）」节 |
| 拍板执行 | **已执行（用户交互确认八项）** | 本笔提交 | D-A=交接预算 16k→**32k**（红→绿 34 例）；D-B=**放开非 admin 切换 provider+租户隔离红线**（spawn 快照三字段/续跑五结果决策首次全可达/跨租户与「未找到」同形拒绝/admin 豁免留 `resume_cross_tenant_admin` 审计，18 例新测试，agent 域 2683 passed 零新增）；D-C/D-D/D-E/D-F/D-H=维持建议值零改动；D-G=本机探测+三家真握手 live-verify——**抓出并根修真互操作缺陷**（ACP protocolVersion 线上须为整数，本仓发字符串被真 CLI 全拒 -32602；根修后 opencode 1.2.27/claude-code 适配器/codex 适配器三家真握手全 PASS，gemini-cli 未装如实登记）；同批清偿：帧钩子 flaky（因果序断言+20 连跑+7 类注入防弱化）、E3 两处无界渲染列表（会话侧栏/子代理时间线窗口化+拖拽最小提交）、前端三增强消费面（审批徽标/质量徽标/成本标注列+cost_note 端点透传） |
| 复评二 | **已复评（部分达成，差距收窄）** | — | 对照 T3 当期主干 `80871270`（2026-11-20 21:42 -0800；较首轮 `6f94a063` 前进一笔 provider 版本探测 perf 提交，20 子项能力面无变化，T3 维持原分）完成第二轮 20 子项复评：Neurova 84.5→**85.25**，净差 7.3→**6.5**。调分三项：C1 8.0→8.5（三家真机握手 live-verify 全 PASS+protocolVersion 线上类型互操作根修）、C5 8.0→8.5（D-B 落地——非 admin 切换放开、五结果决策全可达、租户隔离红线+admin 审计）、E3 8.0→8.5（前端列表渲染回归门+两处无界渲染收口）；其余 17 项维持（A1/B4 深化核实为巩固既有分位、D-A 预算 16k→32k 属参数变化、前端徽标/cost_note 属消费面补链，均不调分）。16 落后（净尾差 13.0）/3 平（B4/D1/E1）/1 反超（A4 +1.0）——「全部 ≥」目标仍未达成；逐项证据与判定详见评测报告「## 复评记录二（2026-11-21，第二轮，T3 主干 80871270）」节 |
| 复评三 | **已复评（部分达成，差距继续收窄）** | — | 对照 T3 当期主干 `2af43518`（2026-11-20 23:35 -0800；较二轮前进 25 笔，以修复/projects 特性/perf 为主，20 子项能力面无变化，T3 维持 91.8）完成第三轮 20 子项复评（IDE 接入计划 G1-G6 六卡落地后）：Neurova 85.25→**86.0**，净差 6.5→**5.8**。调分三项：C1 8.5→9.0（ACP registry 零代码接入+ACP v2 全量适配+真机回放契约）、D3 8.5→9.0（连接运行时单源+按需订阅）、E2 8.0→8.5（真实 transcript 回放兼容纪律）；其余 17 项维持（G3 适配器方法面按接线广度口径强化 C2 不调分、G5 系既有覆盖确认）。16 落后（净尾差 11.5）/3 平（B4/D1/E1）/1 反超（A4 +1.0）——「全部 ≥」目标仍未达成；逐项证据与判定详见评测报告「## 复评记录三（2026-11-21，第三轮，T3 主干 2af43518）」节 |
