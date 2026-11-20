# 企业源持续同步可靠性方案：同步历史落账 · 全租户调度 · 单源单飞

> 状态：已实施（2026-11-19 当日完工，执行记录见 §7）。
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

2026-11-19 当日实施完毕，A–D 卡全清，另修复一块实施中暴露的调度器断点。

| 卡 | 提交 | 结果 |
|---|---|---|
| A（v56 + runOnceAsync 落账/单飞 + 读面） | `3c234791d` | `enterprise_sync_history` v56 落地；`runOnceAsync(tenantId, sourceId, triggerKind)` 统一写点，manual/interval/skipped/error 全落账；`GET /enterprise/sources/{id}/sync-history`（admin，倒序+limit） |
| B（全租户注册 + 运行时跟随） | `3c234791d` | `listSyncTenants` 全租户遍历；jobId=`kb_enterprise_sync_<tenant>_<source>`；`setSyncInterval`/`saveConfig` 尾部跟随；`GET/PUT /enterprise/sources/{id}/sync-interval`（admin） |
| C（测试三件套红→绿） | `3c234791d` / `50898bdbc` | 新增 `test_enterpriseSyncHistory.py` 13 用例先红后绿；enterprise 域 202 passed；knowledge 全域 2031 passed 零新增失败 |
| D（live-verify） | — | 9681 真后端 + 临时数据根 + jsonl file 源：PUT interval=2s 后 sync-history 出现 3 条 `trigger=interval` 行（首轮 admitted=3、游标推进 `off=3`，后续轮游标未动拉 0 行），PUT 0s 后 interval 行停止新增；启动日志 `TaskScheduler started`、`[ERROR]` 计数 0 |
| 计划外：调度器断点修复 | `14850e854` | 实施中发现的真断点——`TaskScheduler` 惰性单例全仓无 `start()` 调用，`addSystemJob` 在 `_apscheduler=None` 上必炸且被 fail-soft 吞掉（PUT 返回 success 但 job 从未存在）。根修：`addSystemJob` 面内自保证前置（未跑先 start）+ 启动钩子改 `init_scheduler()` |

前端适配（间隔编辑 + 同步历史抽屉，11 语言 12 键）：`a8f6fe2b9`；同刻写入的叙述行裁决悬置（rowid tie-break，仅叙述行、三元组置信并列仍留人工）：`3c50d25bc`。

**偏离说明**：
1. D3 单飞在 file 源上表现为串行执行而非 `already_running` 跳过——file 适配器 `fetchBatch` 无 await 让出点，单事件循环内两请求天然串行；单飞锁语义由带让出点的 fake adapter 测试覆盖，真实 HTTP/ERP 源（有 IO 让出）防线有效。
2. 验收标准 3 的「已注册 N 个 job」启动日志仅在「启动时已存在启用 interval 的源」场景打印；运行时经 PUT 注册的源走跟随路径，不重打该行。
3. TaskScheduler 启动后，任务台账 `agent_scheduler_tasks.json` 中 enabled+schedule 的 Agent 定时任务将开始按计划执行（此前调度器从未启动、它们从未真正跑过）——这是断点接活的伴生影响，执行走既有 executor/审计链。

---

## 8. 租户共享设计（2026-11-19 用户拍板：复制发布语义）

> 回答「企业连接器有没有按租户隔离，租户自己的数据按私人库处理，再共享至公共库或分享给其他租户」。
> 结论：隔离已完备、跨租户流动无机制；本节按**复制发布**语义细化，复用既有共享机制做最小扩展，不新造平行体系。

### 8.1 现状证据（2026-11-19 逐点核实）

| 层 | 现状 | 出处 |
|---|---|---|
| 连接器配置 | 按 `tenant_id` 隔离；interval jobId 带租户段 | `enterprise_source_configs`、`registry._registerOneJob` |
| 本体/事实层 | v25 起按租户分区，`(tenant_id, id)` 复合主键 | `foundation_schema.py:115`、`knowledge_facts.py` 62 处 tenant 过滤 |
| 条目层 | `tenant_id` 字段（缺省 default）；`visibility` public/private；`shared_with` **用户 id 列表**只读共享；私→公已有完整审批链 `submit_to_public` → admin `review_public_submission` → `unpublish` | `repository.py:765/1021/1311-1400`、`knowledge_sharing.py:272-322` |
| 可见性判定 | **租户先于角色**：`can_view` 首条即跨租户一律不可见（admin 也不穿透）；同租户内 public / 属主 / shared_with | `repository.py:1117-1133` |
| 检索过滤 | FTS 按 `shared_with_json` json_each 精确匹配 uid；scope=public/private/shared | `fts_index.py:225-244` |
| 差距 | `shared_with` 只装用户 id；public 也出不了租户；无跨租户分享/发布通道 | — |

### 8.2 设计原则

1. **复制发布，不做跨租户实时视图**：检索/读面的租户过滤点遍布（can_view、检索快照循环、fts 下推、本体分区），实时视图要把每处改成双租户逻辑，泄露面与复杂度都大；复制发布只在写入侧开受治理的口子，天然可审计、可撤回。
2. **单一事实源**：共享判定仍只看 `shared_with` 一个字段（用户 id + `tenant:<id>` 段同列），不新造第二份共享声明；公开审批仍走既有 `submission` 链。
3. **租户先于角色不破**：`can_view` 的跨租户默认拒绝保持不变，跨租户可见只能来自显式分享段或显式发布的副本。
4. **血缘必留**：跨租户副本带 `origin_tenant_id` / `origin_knowledge_id`；企业源数据继承 `sourceSpan`。

### 8.3 分期设计

**P1 · 条目层跨租户分享与发布副本（本方案实施范围）**

- E1 `shared_with` 租户段（零 schema 迁移）：
  - `shared_with` 列表允许 `tenant:<tenant_id>` 段（用户 id 现为数字/uuid，无前缀冲突）；
  - `can_view` 扩展：跨租户且 `tenant:<user.tenant>` ∈ shared_with → 只读可见（can_modify 仍 false，不属目标租户成员不可改）；
  - 检索扩展：`repository` 快照过滤与 `fts_index.py:234/241` 的 json_each 匹配值同时传 uid 与 `tenant:<tid>`；
  - 端点扩展：既有 `POST /knowledge/sharing/{id}/share|unshare` 的 body 增加 `tenant_ids`（经租户存在性校验），复用同一写路径；
  - 撤回＝unshare 摘段，即时生效。
- E2 跨租户发布副本（复制语义）：
  - 新端点 `POST /knowledge/sharing/{id}/publish-copy`，body `{target_tenant}`：把条目**复制**一条进目标租户（`tenant_id=target`，`origin_tenant_id`/`origin_knowledge_id` 留血缘，`visibility=private`）；
  - 目标租户内公开仍走目标租户 admin 的既有 `submit-public → 审批` 链——副本进公共库必然过人审；
  - 审批模型（双边）：源租户 admin 发起 + 目标租户 admin 审批放行落库；审批记录挂条目 `submission`（扩展 `copy_target` 字段）与审计事件；
  - 副本独立演进：源条目后续修改/撤回不影响已发布副本（复制语义的核心代价与收益）；源侧 `origin_*` 反查可列出所有外发副本；
  - 撤回：目标租户 admin 可 `unpublish`/删除副本；源侧暂不做远程召回（挂 §8.5 待拍板）。
- E3 权限与审计：share/unshare/publish-copy/审批四动作全部落审计事件（复用 `_landActivity` 模式）；publish-copy 仅源租户 admin 可发起，目标租户 admin 可审可拒。
- E4 live-verify：真后端建两个租户的 admin，走「分享段可见 → 发布副本 → 目标审批 → 公共可见 → 撤回」全链。

**P2 · 企业源/事实层共享（挂台账，另行拍板后实施）**

- 源级策略：`enterprise_source_configs` 增 `share_tenants`，同步落账后把批次数据复制写入目标租户分区（每目标租户独立游标与幂等键派生，admission 咽喉不变）；
- 事实层复制：`knowledge_facts` 按 v25 分区复制断言行（保留 `sourceSpan`，qualifier 注记 origin），与目标租户既有事实的冲突交由既有 conflict_judge 阶梯处理；
- 规模较大且涉及增量游标语义，不并入 P1。

### 8.4 测试计划（先红后绿）

1. `can_view`：跨租户无段不可见；有 `tenant:<tid>` 段只读可见；目标租户成员不可改（can_modify false）；
2. 分片：带租户段的条目落 shared 片（`_shardOf`）；
3. 检索：fts scope 过滤按租户段命中/不命中；快照检索同判；
4. publish-copy：复制血缘完整（origin_*）、目标租户内初始 private、目标 admin 审批后才 public、源后续修改副本不变；
5. 权限：非属主/非源 admin 发起 403；非目标 admin 审批 403；租户不存在 400；
6. 撤回：unshare 摘段即时不可见；目标侧 unpublish 回 private；
7. 回归：knowledge 全域 + api 域零新增失败；locale 若新增前端键需 11 语言对齐。

### 8.5 待拍板残留

1. 源侧远程召回（撤回外发副本）要不要做——影响目标租户数据完整性预期；
2. P2 源级 `share_tenants` 自动复制的准入级别（admin 配置即可，还是逐目标审批）；
3. 事实/本体层是否开放条目级之外的发布（当前 P1 仅条目层）。

### 8.6 验收标准

1. 两个租户互不可见对方任何数据（回归确认现状不破）；
2. 显式分享后目标租户成员可读不可写，取消分享即时失效；
3. 发布副本在目标租户 admin 审批前不可见，审批后按目标租户可见性规则流转，血缘可反查；
4. 全程审计事件可查，knowledge/api 域回归零新增失败，live-verify 全链通过。

### 8.7 执行记录（2026-11-19 P1 当日实施完毕）

P1（E1–E4）已落地：提交 `625b994a8`。

- **E1**：`share_segment.py` 为租户段唯一构造/判别入口；`can_view` 对跨租户显式 `tenant:<id>` 段只读放行，`can_modify`/`can_categorize` 加租户守卫（跨租户一律不可写）；`visible_items` 快照过滤与 `fts_index` 下推同步认段；share/unshare body 增 `tenant_ids`（目标租户经部门根组树校验存在性，default 恒在）。
- **E2**：`request_publish_copy`/`decide_publish_copy`/`pending_copy_requests`——请求挂源条目 `copy_requests`，审批前不落副本；批准才经 `_copyItemForTenant` 复制落库（origin 血缘、初始 private、属主=审批人）；条目响应投影带 `origin_*`。
- **E3**：share/unshare/publish-copy/decide 四动作落 `knowledge_activities` 审计（fail-soft 点名）。
- **红绿**：`test_tenantSharing.py` 13 用例先红（12 failed / 1 现状基线）后绿；`test_tenantSharingEndpoints.py` 7/7 绿；knowledge 全域 2044 passed、api 域 3315 passed、enterprise 202 passed 零新增；路由快照随批更新（顺带补登上一批漏登的三条 enterprise sync 端点）。
- **E4 live-verify**：双租户真后端（临时数据根+真实部门根组）13 步全链通过——默认 404 → 分享后 200 → PUT 403 → 发起/待审/批准落副本（origin 血缘、private、owner=审批人）→ 普通用户 404 → unshare 撤回 404 → reject 无副本 → 待审清空；启动 `[ERROR]` 计数 0。
- **实施注记**：live-verify 首轮 dst-user 误见副本，定位为验证脚本 token 缺 `sub` 声明（auth 层 user_id 回退 `sub`，缺省 "unknown" 撞等）——非产品缺陷，修正验证姿势后复跑全绿。
- **P2**（企业源 `share_tenants` 自动复制、事实层复制）维持挂台账待拍板。

### 8.8 执行记录·追记（2026-11-19 同日，用户四项拍板后全部落地）

用户对遗留项逐项拍板：P2 全量实施、做远程召回、agent 域 9 条预存失败清偿、推送双远端。

- **agent 域 9 条预存失败清偿**（`32c199965`）：tkg 桩补 `allowedCategories` 形参；快照按维护协议退役 `Agent.chat_stream`（a334ffb05 假流式收编进 `agent.chat(stream=True)`）与 `Agent.spawn_subagent`（6312384c7 SubAgentManager 并入退役，派单走 SwarmManager）并写明去向；failureLanding 的 chat_stream 守卫随之退役、改版出**现役流式分支失败落点守卫**（`agent.chat(..., stream=True)` 注入 `llm_client.chat_stream` 失败仍落 assistant 终态）；`toolLoopDeadlines.txt` 六行补记 `loop_gates_compiler` 新引用站（3→4 / 5→6，循 88d53deee「改回实状」先例）。agent 全域 2110 passed 全绿。
- **远程召回**（`85fe74baa`）：`recall_published_copy` 仅源租户 admin、仅作用于 `origin_*` 吻合的本源外发副本；副本 lifecycle 置 archived（各检索/读面即刻不可见）并打 `origin_recall` 留证——治理下架而非销毁；端点 `POST /{knowledge_id}/recall-copy` + 审计。
- **P2 全量**（`d10dad497`）：
  - v57：`enterprise_source_configs.share_tenants_json`（saveConfig 显式回填，防 INSERT OR REPLACE 清零）；
  - **投影式复制**（设计决策：连接器凭据属源租户，目标租户不独立拉取——源每轮拉取成功后，同一批断言投影到目标租户分区）：`ingestBatch` 增 `tenantOverride`/`originTenant`；投影行 `qualifier.shared_from` 注记血缘、mediumRef/sourceSpan 与源轮一致、内容键按租户分区各自幂等（重拉零重复）；投影失败点名进 `projection_errors` 不静默，下轮重拉按内容键幂等补齐；
  - `conflict_judge._qualifierKey` 剔除 `shared_from`——血缘注记不是业务限定，参与分组会把同 slot 竞争主张按来源拆散漏判；
  - 端点 `GET/PUT /enterprise/sources/{id}/share-tenants`（admin，部门根组树校验，自身租户 400）；`ensureTenantExists` 下沉 `knowledge_common` 两域共用；
  - 测试：`test_enterpriseShareTenants.py` 13 用例先红（11 红）后绿；fact_store 版本断言 56→57；路由快照 +2。
- **终验回归**：knowledge 2058 / api 3317（metrics 1 条为全局计数器顺序污染，单跑即绿，与本批无关）/ enterprise 215 / agent 2110 全绿。
- **推送**：origin（cnb.cool）已达 §8 细化批；agent 清偿/召回/P2 三批与本追记随批补推（github 当日网络重置，补推见提交后记录）。
