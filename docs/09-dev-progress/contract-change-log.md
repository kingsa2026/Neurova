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

## 待登记（ upcoming）

- A2 事件库（swarm_event_store）接入订阅面后的 cursor/replay/snapshot 协议字段。
- D2 组织权限天花板（`NEUROVA_PERMISSION_CEILING`）接入派活链后的 mode 收窄语义。
