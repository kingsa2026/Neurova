# ADR 0015: ContextPool 回收契约（归档无损 + 显式常驻上限 + 读路径索引）

- **Status**: Accepted
- **Date**: 2026-09-18
- **Decision Maker**: Issue #65（实测基线暴露后定调）

## Context

`neurova/context_pool.py` 在「无损归档（活水）」改造后，容量语义出现了三处
**只有注释知道、代码与 API 都不知道**的漂移。Issue #65 的实测基线把它们摆上台面：

| 现象 | 实测（Python 3.12 / requirements-ci.txt） |
|------|------------------------------------------|
| `max_size` 完全失效 | `max_size=200` 时池内仍保留 10000 条，`pool_len` 纹丝不动；占用严格线性 0.76 KB/条 |
| 读路径是瓶颈 | 20 次 `query()`：1000 条 0.044s → 10000 条 0.438s（≈2.2ms → 22ms/次，严格线性）；而 `add_context` 已 O(1) |
| `reset_execution_engine()` 是空操作 | 只清模块级缓存，类级 `_instance` 未清 → 重置后 `e2 is e1`，`_executions` 里上一测试的标记原样存活 |
| 守卫测不出上述任何一项 | 压测上限只有 100 轮、阈值 `< 10s`、完全不查内存 |

其中 `max_size` 的失效**不是 bug 而是刻意设计**（"永不丢失上下文"是硬约束，
容量控制被转移到视图层 Drawer）。但它留下了三个真实缺陷：

1. **契约不可见**：参数仍在 API（`GET /pool-settings` 返回 `max_size: 100`）和
   构造函数签名里，调用方以为设了有效；代码里只有一行注释说明失效。
2. **池自身没有任何上限**：缺少外部回收策略时，进程内存随会话时长只增不减。
3. **静默降级风险**：池已有持久驱逐台账（`EvictionLedgerDB`，WAL+FTS5，
   `recall_evicted()` 可召回全文）与仅 500 条的内存台账——两者混用会让"回收"
   变成"静默丢全文"。

同时 `query()` 是唯一的读入口（`ContextPoolRegistry.query_agent` 与
`ContextOrchestrator` 都经它取数），却仍是全池线性扫 + 逐条 `content.lower()`。

## Decision

### 1. 三分层的回收契约（显式写进类文档与 `get_retention_stats()`）

| 层 | 语义 | 参数 |
|----|------|------|
| **归档层（池）** | 永不丢失：不按容量驱逐 | `max_size` **已失效**（保留兼容），首次越界 WARNING 一次 + 统计显式上报 `max_size_effective=False` |
| **常驻上限（可选）** | 显式启用后，超限最旧条目**先落盘再从常驻移除** | `resident_limit`（默认 `None`=不限制，零行为变化）；**必须**注入 `ledger_db`，否则自动禁用并告警 |
| **视图预算** | 决定"这次取多少"，与常驻规模解耦 | `max_tokens` / `Drawer.max_tokens` |
| TTL | `>0` 时过期条目经 `cleanup_expired()` / 查询过滤剔除（先归档再剔除） | `ttl_seconds`；`0`=永不过期（生产 orchestrator 走此档） |

关键取舍：**没有持久台账时，`resident_limit` 一律禁用**。宁可不上限，也不接受
"回收把全文丢进只保留 500 条的内存台账"——那会把硬约束悄悄降级成尽力而为。

### 2. 读路径走分区索引（`neurova/context/pool_index.py`）

- `PoolReadIndex` 维护 `source` / `session_id` 两个分区（插入序），`query()` 按
  分区直取，不再「全池遍历 + 逐条比较」；
- 关键字匹配对**无大小写差异**的 needle（中文/数字/符号——本仓主要语料）直接
  `needle in content`，省掉逐条 `lower()` 分配（实测这才是读路径主成本）；
  含大小写差异时仍走精确小写比较，语义**逐字不变**；
- TTL 判定改整数时间戳比较（`created_at >= now - ttl`），`ttl_seconds<=0` 零开销；
- 「当前 session 优先」在当侧已够填满 `limit` 时**短路**，跳过其余 session 组装；
- 索引是加速件不是事实源：`_contexts` 被绕过公开 API 直接增删时按计数漂移自愈重建。

顺带修正一处契约漂移：显式 `session_id` 路径此前**静默忽略 `tags`**，现按文档契约
在所有路径生效。

### 3. 重置契约必须挂在真实调用点

`reset_execution_engine()` 改为三层清（模块缓存 + 类级 `_instance` + `_executions`），
并在 `tests/conftest.py` 加 autouse 隔离 fixture 真实调用它——否则它又会回到
"零调用方、从未被验证"的状态。

### 4. 契约可观测（无观测不可运维）

新增 `neurova_context_pool_*` 指标：常驻条数、各原因回收计数、`query()` 分阶段耗时
直方图（`partition` / `ttl` / `keyword`）；`/metrics` 抓取时经
`observe_context_pools()` 刷新。池经**弱引用**登记表枚举，"抓指标绝不懒建池、
也绝不延长池生命周期"。

## Consequences

**正向**

- `max_size` 失效从"一行注释"变成 WARNING + 统计数据（"设了没生效"不再只能靠压测发现）；
- 需要常驻上限的场景（长驻多会话 Agent）有了显式、无损的开关；
- `query()` 10k 条 20 次：0.438s → **0.033s**（≈13×），且候选集与池总量解耦
  （40k 条时关键字取数仍只扫目标分区）；
- 读路径/内存/回收三件事第一次可被 CI 与 `/metrics` 观测。

**负向 / 风险**

- 分区索引引入"必须与 `_contexts` 同步"的维护面（clear/dedup/compress/cleanup/
  替换/回收六处重排点 + 计数自愈防线）。防线是"计数漂移即重建"，最坏退化成旧的
  全池扫，不会算错。
- 快路径的等价性依赖 Unicode 事实（无大小写差异字符的等价类退化为自身）。
  已用全码位 + 随机串的可证伪安全网钉住（`test_context_pool_query_index.py`）。
- `resident_limit` 与 `max_size` 并存会造成困惑，故在签名/文档里把前者标为唯一有效上限。

**验证**

- `tests/unit/context/test_context_pool_query_index.py`：随机化等价性（对旧实现 oracle）
  + Unicode 快路径安全网 + 规模契约 + 埋点；
- `tests/unit/context/test_context_pool_retention_contract.py`：失效可见性 / 上限回收无损 /
  无台账禁用 / TTL 与替换计数；
- `tests/unit/execution/test_execution_engine_reset.py`：三层清 + 并发一致性 + conftest 接线；
- `tests/performance/test_context_pool_load.py`：规模守卫 + 内存守卫 + 回收契约守卫。

## References

- Issue #65（实测基线与四条整改要求）
- 实现：`neurova/context/pool_index.py`、`neurova/context_pool.py`、
  `neurova/shared_core/execution_engine.py`、`neurova/core/metrics.py`
- 相关：`neurova/context/eviction_ledger_db.py`（持久台账，回收无损性的承载）
- 前置：ADR 0014（连接池只管短连接——同为"池的语义边界必须写清"的定调）
