# Wire 契约变更登记表

> 纪律来源：E2 契约兼容守卫（参照系 ac 借鉴，2026-11-21）。任何跨进程 wire 契约
> （REST/WS payload、工具 schema、事件账本 record、台账投影）的**破坏性变更**
> （删字段/改类型/收紧 required）必须先在本表登记迁移路径，再动代码；
> `tests/unit/api/test_wire_backward_compat.py` 是机器守卫。
> 新增**可选**字段属于向后兼容增量，登记即可，无需迁移。

## 登记

| 日期 | 面 | 变更 | 兼容性 | 迁移路径 |
|---|---|---|---|---|
| 2026-11-21 | 工具 schema：dispatch_team / continue_subagent / cancel_subagent | 新增可选参数 `command_id`（幂等命令 ID） | 向后兼容（可选增量，不传行为不变） | 无需迁移；调用方按需透传 |
| 2026-11-21 | 工具结果信封 | dispatchTeam/updateSubagent/cancelRun 回执重放时结果新增 `replayed: true` 键 | 向后兼容（新增可选键） | 无需迁移；消费方按需读取 |
| 2026-11-21 | 事件账本 record | 新增事件类型 `context_transfer` / `context_transfer_failed` / `resume_decision`（批一 B2/C5 留痕） | 向后兼容（新增枚举值；消费方按 type 分派，未知类型应跳过） | 消费方对未知 type 保持跳过语义 |
| 2026-11-21 | 续跑返回 | resumeFinishedRun 能力门拒绝时返回 `{"success": false, "error": "...不支持续跑..."}`（新拒绝形态） | 行为收紧：此前无能力声明的外部成员也会硬续跑，现在诚实拒绝 | 调用方按 success=false 呈现；报错文案含处置指引 |
| 2026-11-21 | 事件账本 record | 新增事件类型 `auto_settled` / `context_transfer_failed` / `resume_decision`（批二 A5/B3/C5 留痕；`context_transfer` 见上行） | 向后兼容（新增枚举值） | 消费方对未知 type 保持跳过语义 |
| 2026-11-21 | 权限模式 | 新增组织天花板环境变量 `NEUROVA_PERMISSION_CEILING`（值=PermissionMode value；未设不封顶） | 向后兼容（未设时行为不变；设置后只收紧不放宽） | 部署方按需注入；AUTO 值按既定语义落 BUILD |
| 2026-11-21 | swarm 内部 | `.gitignore` 临时脚本规则锚定仓库根（`run_*.py`→`/run_*.py` 等 8 条） | 仓库行为修正（原规则会误吞子目录正式模块） | 无消费方影响 |
| 2026-11-21 | run 投影/事件 | `SubAgentRun.to_dict()`、terminal 事件 payload、`_uplinkEnvelope` 信封新增 `terminal_quality`（strong/weak/none；A1 终态质量分级） | 向后兼容（新增可选键） | 消费方按需读取；验收/评审门据 `requiresReviewConfirmation` 决定复核 |
| 2026-11-21 | 审批审计 | 命中记忆式批准的裁决记录新增 `decision_source="memory_grant"` 与 `grant_id`（D1）；审计 details 落 `grant_id` | 向后兼容（新增可选键；未命中 grant 行为不变） | 消费方按需读取；团队档 grant 持久化数据根 `team_approval_grants.json`（进程内状态，非跨进程 wire） |
| 2026-11-21 | SSE 推送 | `ssePushStream` 新增可选 `byte_budget`/`event_cap`：超单事件上限发诚实占位帧；累计超预算发 `event: snapshot_downgrade` 通告（含已外发最大游标）后转快照（E3） | 向后兼容（默认不传参数行为逐字不变） | 客户端收到 snapshot_downgrade 应丢弃游标、按退避重连取首屏快照 |
| 2026-11-21 | 移动 WS sync_resume | 快照必要（cursor 过旧/非法/预算尽）时下发 `sync_snapshot_required {reason, note, head_seq}`（D3，决策单源 `subscription_resume.resolveResumeMode`；三端重连退避按 `reconnectBackoff` 语义实现） | 行为澄清：此前游标过旧无明确语义 | 客户端收到后丢弃游标、退避重连、以首屏快照恢复；绝不部分重放 |
| 2026-11-21 | 评测运行记录 | suite_eval `/run` 记录新增可选 `cost_note`（E1，手动跑成本标注；不传不含该键） | 向后兼容（新增可选键） | 消费方按需读取 |
| 2026-11-21 | neuacp 失败文案 | 外部代理失败原因经 classifyFailure 诚实改写：OOM 类标注「内存资源耗尽」并保留原始证据（C3） | 文案变化（结构不变，error 仍为字符串） | 消费方如按旧文案匹配需改为含「资源耗尽」关键词判定 |
| 2026-11-21 | run 状态投影 | `subagent_status`/`SwarmManager.status()` 结果新增 `queue_position`（排队位次，从 1 起；0=不在队列；B4 管理面） | 向后兼容（新增可选键） | 消费方按需读取 |
| 2026-11-21 | REST 新增 | `GET/PATCH/DELETE/POST /api/v1/swarm-queue[...]`（B4 管理面：队列快照/优先级/取消/任务书修订；admin 门；未知 id 404；在跑 steer 不可达 200+`mode=rejected`） | 向后兼容（纯新增端点） | 前端/运维面按需接入 |
| 2026-11-21 | spawn 依赖门 | `DEPENDENCY_FAILED` 拒绝范围扩大：前置为 weak/none 终态（超时/取消兜底、来路不明）的 completion 也不再自动放行下游，须复核（A1）；历史空质量（未经迁移收口的直接构造）行为不变；另根修「依赖全部已满足时 spawn 崩溃（blockedId 未赋值）」的预存 bug | 行为收紧（弱终态不再被当强终态消费）+ 崩溃修复 | 依赖弱终态前端的下游任务需先复核/重派前置 |

## 待登记（ upcoming）

- C2 能力维度扩展（model_switch_in_session/conversation_rollback/steer/fork）在能力出口真值透出后的消费面（决策矩阵已按保守缺省工作）。
- B4 队列管理面（runQueueSnapshot/setRunQueuePriority/cancelQueuedRun/editRunTask）接入工具/API 面时的 schema 增量。
