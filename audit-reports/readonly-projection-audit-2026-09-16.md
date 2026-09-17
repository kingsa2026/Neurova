# 只读投影数据断链巡检报告（2026-09-16）

**触发**：元认知页条目卡片恒空事故。根因：`meta_records kind='thought'` 读投影存在，但全系统唯一写入方是页面"创建"按钮（2026-09-16 已修复：洞察现镜像为 thought 条目，见 `self_model._mirror_lesson_as_thought` 与 `tests/unit/cognitive/test_lesson_thought_mirror.py`）。

**目的**：按修复教义第 5 条（放大视角），排查全仓是否存在同类"读投影按 kind/type 枚举过滤、但该枚举值无写入方"或"字段名错位"的断链。

## 巡检方法

1. 全仓扫描读侧过滤点：`kind=`、`record_type=`、`process_type=`（后端），`.kind ===` / `.type ===`（前端）；
2. 对每个读投影定位写入方，核对枚举值、字段名、读写归属域（同库同表才有效）；
3. 扫描模块级内存 stub 容器（`_*: dict/list = {}/[]`），核对读写同源；
4. 以"恒空/零调用/僵尸/永不触发/幽灵"关键词反向扫描历史断链修复痕迹，甄别现存 vs 已修。

## 检查面清单与结论

| # | 检查面 | 读投影 | 写入方 | 结论 |
|---|--------|--------|--------|------|
| 1 | MetaLedger `meta_records.kind`（thought/lesson/reflection） | metacognition_api 三端点、injector、skill_attribution（SQL 层 kind 过滤） | API 手动创建（thought）、`self_model.reflect`（lesson/reflection）、**镜像（thought，本次新增）** | ✅ 已闭环（thought 曾为唯一断链，本次修复） |
| 2 | `meta_events.process_type='tool'` | `tool_success_rates`（技能归因/反思基线数据源） | tool_executor 咽喉 `record_tool_event` 写字面量 `"tool"`；meta_cognition_module 写枚举值（不匹配读取过滤，无碍） | ✅ 同表同源，枚举对齐 |
| 3 | `meta_states`（认知负荷快照） | `latest_state` / `state_history`（负荷指标卡） | B 状态机 `_persist_state_throttled` 写穿透 | ✅ 生产库 54 行实证有数据 |
| 4 | AIGC 生成任务账本（kind=image/audio/video） | `/generation/tasks`（kind 过滤）、`unfinished()`→重启恢复循环 | generation.py 三个提交点 + recovery `settle_video_record` 写同一 JSON 账本 | ✅ 读写同文件、枚举对齐 |
| 5 | AIGC 用量统计（kind/status） | `/generation/usage` → UsageStatsPage `aigcUsage.totals` | generation.py `get_aigc_usage().record()` | ✅ 同 SQLite 表，image/video/audio × success/failed 对齐 |
| 6 | FirewallPage `record.kind === 'ip'/'path'` | 前端 blocked 页签 tag 渲染 | **前端本地合成字段**（`blockedRows` 由 blocked_ips/blocked_paths 响应拼装），非后端字段 | ✅ 误报；后端 `rule_type` 契约已于 2026-09-12 收口（firewall.ts 注释） |
| 7 | SkillPoolPage `tr.kind === 'upgrade'` | 流转记录 tag | marketplace.py:661 写 `"kind": "upgrade"` | ✅ 同域 |
| 8 | task_tracker `kind="chat"` | console 快照消费 | chat.py/console.py `register_async_task` | ✅ 同 tracker 单例 |
| 9 | 模块级内存 stub 容器 | `_VECTOR_CACHES`（context/orchestrator）、`_FREE_DEFAULT_MODELS`（opencode_provider） | 均有同函数内/导入期写入（缓存/种子） | ✅ 非僵尸 |
| 10 | 历史断链关键词 81 处命中 | sleep 四页签、conflicts 端点、trace、rules、monitor、media、image、experience-knowledge、skill_pool `_public_skills` 等 | 逐一抽查均为已修根因注释（带修复日期与接线说明），且有对应测试锁定（如 sleep `_PHASE_CAPS` 2026-09-15） | ✅ 均为历史，无现存开放断链 |

## 结论

- **现存开放断链：0 处。** 本次元认知 thought 镜像是该类故障的最后一个实例。
- 前端 `.kind ===` / `.type ===` 消费绝大多数是 UI 变体分支（图标/配色/文案），属展示层路由而非数据过滤；对其中带枚举语义的 4 处（firewall/skillPool/usage/aigcHistory）逐一核对后端写侧，全部对齐或本地同源。
- 契约错位类（字段名不一致）在 firewall 域曾真实发生过（`kind` vs `rule_type`，2026-09-12 已修），本次巡检未发现新的同类错位。

## 后续建议

1. 前端条目过滤下拉暂未包含新增 `insight:*` 类型（有 `formatType` 原值回退，不致显示破损）；如需中文标签与配色，补 i18n 键与 `typeColorMap`。
2. 若后续新增 kind/type 枚举读取投影，建议在该存储模块 docstring 中登记"写入方清单"（MetaLedger 已按此惯例），让写入方缺失在评审时即可见。
