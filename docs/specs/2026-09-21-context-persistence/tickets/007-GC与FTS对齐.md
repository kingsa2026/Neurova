# 007 GC 与 FTS 对齐（保留策略生效）

**Blocked by**: 002、003

## 目标

让持久层**不单调增长**：保留策略默认生效，且 FTS 与内容表不脱节。

## 现状（实测，基线脚本 §7）

- 删除 2 万内容行后，FTS 仍残留 **50000 行**（FTS 不随内容表删除而收缩）。
- 全表 `NOT IN` 对齐 338 ms；分批（5000/批）310 ms——量级相当，但分批不长时间持写锁。
- 既有 `gc_stale` 的节流点（`_LEDGER_GC_EVERY=20`）挂在 `_archive_evicted` 上，
  而该路径生产不可达 → **GC 从未触发**。接线时必须同时确认 GC 有真调用方。

## 涉及层

- [x] 逻辑层：保留策略两维（`keep_count` 默认 5000 / `keep_days` 默认 30）**默认生效**。
- [x] 逻辑层：GC 触发点移到真有调用方的位置（随批量提交同批，每 N 次一次），
      节流常量写死在模块（`_LEDGER_GC_EVERY` 现状即为模块常量，沿用不新造）。
- [x] 数据层：FTS 对齐走分批删除；**不依赖 `delete-all`**。
- [x] 测试：`tests/unit/context/test_ledger_gc_retention.py`
- [x] live-verify：`tests/manual/context_ledger_gc_90.py`

## 验收标准

- **A5**：写入超 `keep_count` 后，内容表行数收敛到上限，且 FTS 行数与之相等。
- `keep_days` 过期清理同样生效（注入旧 `evicted_at`）。
- GC 触发有可观测计数（`get_retention_stats` 上报），不静默。
- 对齐清理不长时间持写锁（分批小事务）。

## 不做

- 不做自动 VACUUM 调度（磁盘回收是独立议题，本片只保证行数收敛）。

## 实施结果

- 红灯 → 绿灯：`pytest tests/unit/context/test_ledger_gc_retention.py -q` 改前
  `4 failed, 3 passed` → 改后 `7 passed`。红灯文件在转绿前未进 `protected_tests.txt`。
- 根因：`_LEDGER_GC_EVERY` 的节流计数只被 `_archive_evicted` 递增，而它在生产构造面
  （`resident_limit=None`、`ttl_seconds=0`）永不执行——GC 一次也不触发，库单调增长。
  红灯第一条即断言"批量提交驱动 GC"，改前为空（计数恒 0）。
- 改法：新增 `_maybeGcLedger()`，触发点落在**归档提交**（`_flushBatch` 批量结算后 /
  `_persist_archived` 单条后）；`_archive_evicted` 里的旧 piggyback 删净（不留第二处恒 0 节流）。
- 对齐：`_purge` 的整表 `NOT IN` 换成 `_alignFts()` 分批删除（`_FTS_ALIGN_BATCH=5000`）。
- live-verify（真 `Agent` → 真 `ContextOrchestrator` + 真库）：
  节流计数 3/3 与提交批数一致；N 临时调为 2 时生产面 `gc_runs=1`；
  900 条 + `keep_count=200` 收敛为 200 且 `fts_rows == content_rows == 200`，
  上报 `removed=700` 与实际减少一致；`keep_days=30` 注入 90 天前的 `evicted_at`
  后清理 5 条、两表归零。
- 回归 A/B：`tests/unit/context` + `tests/context` 失败集合改前改后**逐行相同**
  （4 条 `context_pool_bugfix` 顺序断言，与本片无关）；相邻套件零新增失败。
  静态门禁 / `ruff`（全仓）/ `perf_gate` 本地全通过。
- 净 LOC：生产代码 +64 / −24（负向来自旧 piggyback 与整表对齐路径的删除）。
