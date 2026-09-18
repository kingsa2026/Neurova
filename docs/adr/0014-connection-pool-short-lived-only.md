# ADR 0014: 连接池只管短连接（常驻连接不进池）

- **Status**: Accepted
- **Date**: 2026-09-18
- **Decision Maker**: Issue #57（P1-4 裸连接迁移前的定调，用户明确裁定）

## Context

`neurova/core/connection_pool.py` 已实现且质量尚可（WAL、`foreign_keys=ON`、
非阻塞取连接、归还前 `rollback` + `SELECT 1` 校验），但全仓生产代码几乎没用它：

- 引用 `core.database` 的生产代码只有 1 处（健康检查，已于 Issue #57 P0-2 改造）；
- 其余 **55 处 / 41 文件** 仍是裸 `sqlite3.connect()`。

P1-4 要求"让 `get_db_connection()` 真正被采用"，但直接把 55 处全量迁移会撞上一个
语义冲突：这 55 处里 **有两类性质完全不同的连接**。

### 两类连接

| 类别 | 生命周期 | 例子 | 典型配置 |
|------|---------|------|---------|
| **短连接** | 借出 → 一次操作 → 归还 | `audit_logger.log()`（每事件一次写）、`approval_manager._upsert_request_sqlite()`、`rbac._get_conn()` | 无需自持 PRAGMA，连上即用 |
| **常驻连接** | 与对象同生命周期（`__init__` 建、`close()` 释放） | `memory_layer/manager.py:_persist_conn`、`mem_core.PersistDbStore._conn`、`cognitive_storage_engine._db`、`desktop_audit._conn`、`aigc_usage._conn`、`usage_history._conn`、`annotation_store._conn`、`run_store`、各队列 `_conn` | 自持 `WAL` / `synchronous=NORMAL` / `busy_timeout` / `isolation_level=None` / `check_same_thread=False` |

常驻连接不是"忘了迁移"，而是**为写放大做的刻意优化**：
`manager.py:_persist_conn` 的注释写明"原每条记忆一次 connect→INSERT→commit→close
（DELETE journal 每次 commit fsync），写放大是数量级瓶颈"；`mem_core.PersistDbStore`
同理（审计 P1-D8）。把它们塞进池会同时破坏三件事：

1. **事务边界**：池的归还会强制 `rollback()`（P0-2 的行为）——常驻连接的调用方
   依赖"同一个连接上做多步 + 自己 commit"的语义，归还即被回滚；
2. **PRAGMA 语义**：池统一 `journal_mode=WAL` + `foreign_keys=ON`，而常驻连接
   各自还需要 `synchronous=NORMAL` / `busy_timeout` / `isolation_level=None`；
   且池是共享的，某调用方改 PRAGMA 会污染其他借用者；
3. **连接数**：常驻连接的存活期 = 对象存活期，池的 `max_connections` 是"并发借用
   上限"而非"对象数上限"，收编后限流语义失真。

### 还有第三类：动态路径的偶发访问

`api/endpoints/home.py:_count_persist_rows()`（按 `agent_workspaces/*/memory/*.db` 的
glob 逐库计数）、`context/eviction_ledger_db.py`（每个 user+agent 一个库文件）
走的是**随数据增长的动态路径**。池按 `db_path` 注册且**不回收**
（`_pools: dict`，只有 `close_all_pools()` 全清）。把它们池化会让
"池注册表 + 空闲连接数"随路径数无界增长——比"每次 connect/close"更差。

## Decision

**池只管短连接。** 具体三条：

1. **短连接迁移入池**：满足"单次操作内借出并归还、库路径固定、高频调用"三条件的
   裸连接，改走 `core.database.database_connection()`（池的上下文管理器）。
   本轮首批见 §迁移清单。
2. **常驻连接明确不动**：自持连接的类保持现状，**不得**改为池借用。
   守护测试把它们列成清单，任何"顺手迁移"都会红灯。
3. **动态路径 / 探针 / 只读 URI 不进池**：
   - 动态路径（per-workspace、per-user 库文件）保持裸连接，避免池注册表无界增长；
   - 健康探针（`app._make_database_health_check`、`endpoints/monitor._db_connection`）
     刻意不走池——探测要轻量独立、不与业务争连接（原注释已写明）；
   - `file:...?mode=ro` URI 连接（`llm/generators/retention.py`）保持裸连接。

配套：迁移前必须先补可观测（Issue #57 P0-2 已加池 gauge / 建销 counter），
否则"省了多少"无法验证。

## 迁移清单（本轮首批，P1-4 第一批）

| 文件 | 调用面 | 依据 |
|------|-------|------|
| `neurova/security/audit_logger.py` | 每事件一次写（实测 5.22ms → 池 2.06ms） | 最高频，收益最大 |
| `neurova/security/approval_manager.py` | 审批 upsert / load | 固定路径短连接 |
| `neurova/security/rbac.py` | `_get_conn()` 每次角色查询 | 固定路径短连接 |
| `neurova/security/compliance_reporter.py` | `_get_conn()`/`_close_conn()` 成对 | 固定路径短连接 |
| `neurova/planning/planning_tool.py` | `with self._get_conn() as conn` | 同时修**连接泄漏**：`with conn` 只提交不关闭 |
| `neurova/core/provider_usage.py` | `_connect()` 上下文用法 | 固定路径短连接 |
| `neurova/api/endpoints/files_api.py` | 写穿 / 删除 / 水合 | 固定路径短连接 |
| `neurova/auth/user_model.py` | `_get_conn()` + `close()` 成对 | 固定路径短连接 |
| `neurova/auth/qclaw_binding_model.py` | `_get_conn()` + `close()` 成对 | 固定路径短连接 |
| `neurova/cognitive_layers/memory_layer/manager.py` | `_persist_conn is None` 时的降级连接 | 常驻连接缺席时的**兜底**仍属短连接 |

**不进池（明示排除，守护测试钉住）**：

- 常驻连接类：`mem_core._PersistDbStore`、`memory_layer/manager._persist_conn`、
  `cognitive_storage_engine._db`、`temporal_knowledge_graph`、`emotion_module`、
  `attachment_manager`、`meta_cognition_layer/ledger`、`channels/channel_ingress_queue`、
  `knowledge/ingest_queue`、`evolution/job_queue`、`core/agent_run_store`、
  `core/aigc_usage`、`core/annotation_store`、`core/usage_history`、`memory/pending_memory`、
  `security/desktop_audit`、`skills/experience_knowledge_base`、`collaboration/neurflow/storage`、
  `aigc_studio/store`、`auth/invitation_code`、`auth/verification_code`；
- 动态路径：`api/endpoints/home.py`、`context/eviction_ledger_db.py`、
  `cognitive_layers/memory_layer/dependency_graph.py`（后续单批再评估，需先定路径基数上限）；
- 探针：`api/app.py:_make_database_health_check`、`api/endpoints/monitor.py:_db_connection`；
- 只读 URI：`llm/generators/retention.py`；
- 独立脚本：`memory/scripts/*`（run-on-import，导入巡检刻意排除）。

## Consequences

**正向**

- 高频短连接拿到实测约 60% 的单次开销下降（审计写 5.22ms → 2.06ms）。
- 事务泄漏面收窄：池归还强制 rollback + `foreign_keys=ON`（裸连接默认关闭外键，
  实测能写进脏外键引用）。
- 常驻连接的写放大优化被明确保护，不会被"统一入口"的洁癖吃掉。

**负向 / 代价**

- 池的 `max_connections` 成为新的并发上限：迁移点若存在嵌套借用且超过上限，
  会走阻塞分支等 timeout。迁移点均无嵌套借用（单层 with），实测无阻塞。
- 两套连接的共存需要文档与守护测试兜住，否则后人会再次混淆。

**降级策略**

- 池不可用时（`get_connection_pool` 抛错）保留裸连接降级路径的模块（如
  `manager.py`）继续可用；池化点为新增依赖，不引入新的失败模式。

## References

- Issue #57（P0-1/P0-2/P0-3/P1-4/P1-5/P1-6/P2-7）
- PR #58（`auto/metrics-pool-9c58`）：P0-1/P0-2 观测底座 + 本 ADR + P0-3/P1-4/P1-6/P2-7
- 实现：`neurova/core/connection_pool.py`、`neurova/core/database.py`、
  `neurova/core/db_indexes.py`、`neurova/api/metrics_access.py`
- 相邻决策：ADR 0004（CognitiveStorageEngine LSM，自持长连接）、
  ADR 0008（SessionRepository）
