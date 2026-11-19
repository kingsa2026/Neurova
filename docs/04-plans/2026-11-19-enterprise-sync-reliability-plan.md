# 企业源持续同步可靠性方案：同步历史落账 · 全租户调度 · 单源单飞

> 状态：待实施（本文档为实施依据，完成后在 §7 回填执行记录）。
> 来源：2026-11-19 企业连接器主动取数机制分析（结论：拉取是「显式触发 + 游标增量 +
> 咽喉幂等」模型；定时已接统一调度器但仅 default 租户、无单飞与退避、结果不落账）。
> 关联：`docs/04-plans/2026-11-19-enterprise-datasource-mcp-plan.md`（企业数据源接入总案）。

---

## 1. 背景与三个缺口（现状证据）

企业源「接上」后不会自动开始拉数；主动取数走四条链路（手动 REST
`POST /enterprise/sources/{id}/ingest`、interval 定时、webhook 推送、chat 条目链），
全部汇入 `registry.runOnceAsync` → `ingestBatch` → admission 咽喉。本轮分析确认三处缺口：

1. **同步结果不落账**：每轮拉取的 `admitted/rejected/skipped/batches/truncated/cursor`
   只在 HTTP 响应里返回（`registry.py:392-394` 现读数），interval job 的结果只有日志
   （`scheduler.py` 事件监听）。问不出「上次同步何时、拉了多少、为何失败」。
2. **interval 调度只覆盖 default 租户**：启动钩子 `app.py:1838-1849` 调
   `registerIntervalSyncs(scheduler, store=...)` 未传 `tenantId`（缺省 `"default"`，
   `registry.py:419`），非 default 租户的启用源不会被挂定时 job——租户隔离缺口。
3. **无 per-source 单飞**：调度器 `job_defaults max_instances=3`（`scheduler.py:950`），
   同一源最多 3 个 job 实例并发；手动触发与 interval 触发也可同时进入
   `runOnceAsync`——同源并发拉取会重复拉、游标推进存在竞态（写入安全仅靠 store 锁）。

## 2. 目标与非目标

**目标**：
- 每一轮拉取（手动/interval，成功/失败/跳过）落一行可查询的同步历史；
- interval 调度覆盖**全部租户**的启用源，且运行中变更间隔/启停能跟随注册与摘除；
- 同一源同一时刻最多一个拉取在跑（非阻塞单飞，拿不到锁如实报 `already_running`）。

**非目标**：
- 跨进程分布式锁（当前部署为单体单进程；多 worker 部署的互斥另立卡）；
- 同步历史的数据保留/清理 job（只追加，量级 = 源数 × 频率，SQLite 可承受）；
- webhook 推送链的历史（推送不走 `runOnceAsync`，另有去重台账读面）；
- 拉取失败的重试退避策略（现状：游标不推进 + 下轮自然重试 + 内容键幂等，维持不变）。

## 3. 设计

### 3.1 D1 同步历史落账（v56 迁移 + 统一写点 + 读面）

**表**（v56，SQL 由 `registry.py` 持有，注册进 `foundation_schema.py`，与 v34 同法）：

```sql
CREATE TABLE IF NOT EXISTS enterprise_sync_history (
    history_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL DEFAULT 'manual',  -- manual | interval
    status TEXT NOT NULL DEFAULT 'ok',            -- ok | error | skipped
    reason TEXT NOT NULL DEFAULT '',              -- skipped/error 原话（关闸/未启用/already_running/异常）
    batches INTEGER NOT NULL DEFAULT 0,
    admitted INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0,      -- mapping skip 策略跳过的行
    entries_written INTEGER NOT NULL DEFAULT 0,   -- chat 条目链落条数
    truncated INTEGER NOT NULL DEFAULT 0,
    cursor_before TEXT NOT NULL DEFAULT '',
    cursor_after TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_enterprise_sync_history
    ON enterprise_sync_history(tenant_id, source_id, started_at);
```

**写入单点 = `runOnceAsync`**（三条拉取链的公共必经路，单一事实源）：
- 签名改为 `runOnceAsync(tenantId, sourceId, *, triggerKind="manual")`；
- 入口记 `started_at/cursor_before`；出口（含 `skipped` 分支）落一行；
- 异常路径：`try/except` 捕获后落 `status="error"`、`reason=异常原话`，再 re-raise
  （调用方语义不变：REST 仍 5xx、调度器仍记 EVENT_JOB_ERROR）；
- 落账本身 fail-soft（失败仅 `logger.warning`，绝不影响同步主流程）；
- `registerIntervalSyncs` 的 job 闭包改传 `triggerKind="interval"`。

**读面**：`GET /api/v1/knowledge/enterprise/sources/{id}/sync-history?limit=50`（管理员）
→ 按 `started_at` 倒序返回该源历史；源详情读面不改动。

### 3.2 D2 全租户 interval 注册 + 运行时跟随

- `registry.py` 新增 `listSyncTenants() -> List[str]`：
  `SELECT DISTINCT tenant_id FROM enterprise_source_configs WHERE enabled = 1 AND sync_interval_seconds > 0`。
- `registerIntervalSyncs(scheduler, store=None, tenantId=None)`：`tenantId=None`（缺省）=
  遍历 `listSyncTenants()` 全租户注册；显式传租户则只注册该租户（既有测试语义不变）。
- **jobId 加租户段**：`kb_enterprise_sync_<tenantId>_<sourceId>`（跨租户同 sourceId 不互顶，
  `replace_existing=True` 幂等不变）。
- **运行时跟随**：新增 `syncSourceJob(scheduler, tenantId, sourceId)`（按当前配置注册或
  摘除单源 job：`enabled 且 seconds>0` → 注册，否则 `removeJob`）；`setSyncInterval` 与
  `saveConfig`（启用态变化时）在调度器已启动的前提下调用它——配置改完即生效，不必重启。
- 启动钩子（`app.py:1838-1849`）不改调用形状（缺省即全租户）。

### 3.3 D3 per-source 单飞（非阻塞）

- `registry.py` 模块级：`_syncLocks: Dict[tuple, threading.Lock]` + `_syncLocksGuard`
  （`threading.Lock`）——按 `(tenantId, sourceId)` 取锁，字典条目不回收（源数有限）。
- `runOnceAsync` 入口 `acquire(blocking=False)`：拿不到 → 返回
  `{"skipped": True, "reason": "already_running"}`（并按 D1 落 `status="skipped"`）——
  interval 的重复触发语义是「跳过本轮」而非排队；`finally` 释放。
- 显式说明：进程内锁，覆盖单体单进程部署；多 worker 互斥不在本批（非目标）。

## 4. 测试计划（先红后绿）

- 新增 `tests/unit/knowledge/enterprise/test_enterpriseSyncHistory.py`：
  1. 手动轮成功 → 历史一行（trigger=manual、admitted/batches/cursor_after 断言）；
  2. interval 触发 → `trigger_kind="interval"`；
  3. 未启用/配置不存在 → `status="skipped"` + reason；
  4. fetchBatch 抛错 → `status="error"` + 原话，且异常仍冒泡；
  5. 读面端点：admin 可读、按时间倒序、limit 生效；非 admin 403；
  6. 单飞：占锁期间第二次 `runOnceAsync` → `skipped + already_running`，且不产生第二行
     admitted 计数；
  7. already_running 的 skipped 也落历史。
- 扩展 `tests/unit/knowledge/enterprise/test_enterpriseIntervalSync.py`：
  1. 两个租户的启用源 → 各注册一个 job（jobId 含租户段）；
  2. `setSyncInterval(0)` / 禁用 → job 摘除；改间隔 → job 更新；
  3. 未启用源不注册。
- 既有用例回归：`test_enterpriseIngestAdmission.py`（ingest 端点现走新签名）、
  `test_enterpriseSourceProtocol.py`。

## 5. 实施拆卡

| 卡 | 内容 | 规模 |
|---|---|---|
| A | v56 迁移 + `runOnceAsync` triggerKind/落账/单飞 + 读面端点 | 中 |
| B | `listSyncTenants` + 全租户注册 + jobId 租户段 + 运行时单源跟随 | 小 |
| C | 测试三件套红→绿 + 全量回归 A/B | 中 |
| D | live-verify：起真后端，启用一个 sqlite 源 + setSyncInterval(2s)，等 ≥2 轮 job，查 sync-history 读面与游标推进 | 小 |

## 6. 验收标准

1. 单测：新增/扩展用例全绿，knowledge/enterprise 域回归零新增失败；
2. live-verify：真后端上看到 interval job 周期触发、`sync-history` 逐轮落行
   （trigger=interval、admitted 计数、cursor 推进），手动 ingest 与 interval 并发时
   出现 `already_running` 跳过而非并发双拉；
3. 非.default 租户源在启动日志出现「企业源 interval 同步已注册 N 个 job」且 N 覆盖多租户。

## 7. 执行记录

（实施完成后回填：逐卡提交号、红绿证据、live-verify 输出、偏离说明。）
