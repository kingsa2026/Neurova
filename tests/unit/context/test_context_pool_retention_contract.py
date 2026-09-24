# -*- coding: utf-8 -*-
"""Issue #65：ContextPool 回收契约显式化（max_size 失效 / resident_limit / TTL）。

基线问题（实测）：``max_size=200`` 时池内仍保留 10000 条，``pool_len`` 纹丝不动
——「无损归档」改造后 ``max_size`` 已不再约束常驻内存，占用严格线性
0.76 KB/条，长会话单调累积。代码只有一行注释说明，**参数本身仍默默存在**
（API 的 GET /pool-settings 还在返回它），属误导。

本套件钉四件事：

1. ``max_size`` 失效必须**可见**：统计里显式上报 ``max_size_effective=False``，
   首次越界有一次 WARNING（"设了没生效"不再只能靠压测发现）；
2. ``resident_limit`` 是**显式**常驻上限：超限最旧条目移出常驻（全文随入池即已
   写穿持久台账，落盘不由回收触发，见 B4/001），``recall_evicted()`` 仍可召回全文；
3. 无持久台账时 ``resident_limit`` 自动禁用并告警——绝不静默丢全文；
4. TTL 回收有计数（常驻规模的另一条出口此前无观测）。
"""
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


class _FakeLedgerDB:
    """最小台账替身：只记 record 调用（含内容），供"无损"断言。"""

    def __init__(self):
        self.rows = []
        self.gc_calls = 0

    def record(
        self, *, content, turn_id=None, session_id=None, source=None, metadata=None,
        chat_scope=None, created_at=None,
    ):
        self.rows.append({"content": content, "turn_id": turn_id, "source": source})

    def gc_stale(self):
        self.gc_calls += 1
        return 0

    def count(self):
        """B4/005：启动登记读一次库内条数（替身同样承载契约，不是可选方法）。"""
        return len(self.rows)


def _pool(**kwargs):
    return ContextPool(user_id="u", agent_id="a", session_id="s1", **kwargs)


def _fill(pool, n, prefix="m"):
    for i in range(n):
        pool.add_context(
            ContextInput(source=ContextSource.CONVERSATION, content=f"{prefix}{i}", priority=i % 50)
        )


class TestMaxSizeIsExplicitlyIneffective:
    def test_max_size_does_not_evict(self):
        """无损归档：max_size 不再驱逐（既有硬约束，回归不得破坏）。"""
        pool = _pool(max_size=10)
        _fill(pool, 50)
        assert len(pool.get_contexts()) == 50
        assert any(c.content == "m0" for c in pool.get_contexts()), "最旧条目被驱逐"

    def test_retention_stats_report_max_size_ineffective(self):
        """失效必须可见：统计显式上报 max_size_effective=False（不再只能读注释）。"""
        pool = _pool(max_size=10)
        _fill(pool, 12)
        stats = pool.get_retention_stats()
        assert stats["max_size"] == 10
        assert stats["max_size_effective"] is False
        assert stats["resident_count"] == 12

    def test_first_overflow_logs_once(self, caplog):
        """越界首次告警，且只告一次（避免每轮刷日志）。"""
        import logging

        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            pool = _pool(max_size=5)
            _fill(pool, 20)
        warnings = [r for r in caplog.records if "max_size" in r.getMessage()]
        assert len(warnings) == 1, f"越界告警次数异常: {len(warnings)}"
        assert "已失效" in warnings[0].getMessage()

    def test_no_warning_when_unbounded_and_never_exceeded(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            pool = _pool(max_size=1000)
            _fill(pool, 5)
        assert not [r for r in caplog.records if "max_size" in r.getMessage()]


class TestResidentLimitContract:
    def test_disabled_without_ledger_db(self, caplog):
        """无持久台账 → resident_limit 禁用并告警（绝不静默丢全文）。"""
        import logging

        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            pool = _pool(resident_limit=10)  # 未注入 ledger_db
        _fill(pool, 40)
        assert pool.resident_limit is None
        assert len(pool.get_contexts()) == 40, "无台账时不得回收"
        assert any("ledger_db" in r.getMessage() for r in caplog.records)

    def test_capacity_recycles_oldest_beyond_limit(self):
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=10, ledger_db=ledger)
        _fill(pool, 25)

        assert pool.resident_count() == 10, "常驻未收敛到 resident_limit"
        # 插入序（_contexts）必须保留最新 10 条——get_contexts() 会按优先级重排，
        # 故这里断言插入序本体
        assert [c.content for c in pool._collector._contexts] == [
            f"m{i}" for i in range(15, 25)
        ], "回收的不是最旧条目"
        stats = pool.get_retention_stats()
        assert stats["resident_limit"] == 10
        assert stats["archived_by_reason"]["capacity"] == 15
        assert stats["archived_total"] == 15

    def test_recycled_entries_are_persisted_not_lost(self):
        """回收 = 移出常驻，全文已在台账（B4/001：写穿点在入池，不在驱逐）。

        判据从"台账里只有被回收的条目"改为"**全部**条目都在台账"——B4/001 把
        写穿点前移到 `add_context`（驱逐路径在生产构造面不可达），所以持久台账
        是"入池即落库"的超集，回收只影响常驻集。无丢失语义一字未减。
        """
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=5, ledger_db=ledger)
        _fill(pool, 12)

        assert [r["content"] for r in ledger.rows] == [f"m{i}" for i in range(12)]
        # 常驻保留的是最新 5 条
        assert {c.content for c in pool.get_contexts()} == {f"m{i}" for i in range(7, 12)}

    def test_indexes_stay_consistent_after_recycling(self):
        """回收后 hash/read 两索引须与常驻列表一致（否则后续 add/query 走偏）。"""
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=5, ledger_db=ledger)
        for i in range(12):
            pool.add_context(
                ContextInput(
                    source=ContextSource.CONVERSATION,
                    content=f"m{i}",
                    metadata={"turn_id": f"t{i}"},
                )
            )
        assert len(pool._by_hash) == 5
        assert pool.get_retention_stats()["read_index"]["indexed_entries"] == 5
        # 回收掉的条目不得再被 ack 标记（turn 索引已随 mark_turn_seen 一并退役，
        # 判据收敛到存活的 hash 通路）
        recycled = {c.hash for c in pool._collector._contexts if c.content == "m6"}
        resident = {c.hash for c in pool._collector._contexts if c.content == "m11"}
        assert pool.mark_hashes_seen(recycled) == 0
        assert pool.mark_hashes_seen(resident) == 1

    def test_query_does_not_see_recycled_entries(self):
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=3, ledger_db=ledger)
        for i in range(6):
            pool.add_context(ContextInput(source=ContextSource.MEMORY, content=f"needle {i}"))
        hit = pool.query(query="needle")
        assert [c.content for c in hit] == ["needle 3", "needle 4", "needle 5"]

    def test_resident_limit_within_bounds_is_noop(self):
        """未超限 = 不发生回收（常驻不缩、回收计数为 0）；与"是否落盘"无关——
        落盘是入池动作（B4/001），不再由回收触发。"""
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=100, ledger_db=ledger)
        _fill(pool, 40)
        assert pool.resident_count() == 40
        assert pool.get_retention_stats()["archived_by_reason"]["capacity"] == 0
        assert [r["content"] for r in ledger.rows] == [f"m{i}" for i in range(40)]

    def test_zero_or_negative_limit_means_unbounded(self):
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=0, ledger_db=ledger)
        assert pool.resident_limit is None
        _fill(pool, 30)
        assert pool.resident_count() == 30


class TestTtlRecyclingIsCounted:
    def test_cleanup_expired_counts_removed(self):
        """TTL 回收的真调用点是写入咽喉（B6-10 批次 D），此处锁它的可观测面。

        改前本用例锁的是"显式调 `cleanup_expired()` 才回收"，而那条路径在生产
        零调用点 —— 契约等于挂在一个没人走的门上。现在回收发生在**每一次写入
        之前**（`add_context` → `_reclaimExpiredOnWrite`），故：过期条目在下一次
        写入时即被回收，随后显式调用返回 0（没有可回收的了）。断言一条未删，
        只是把"谁触发"这一句搬到真面。
        """
        import datetime as _dt

        pool = _pool(ttl_seconds=60)
        stale = ContextInput(source=ContextSource.MEMORY, content="stale")
        stale.created_at = _dt.datetime.now() - _dt.timedelta(seconds=3600)
        pool.add_context(stale)
        # 写入咽喉触发回收：过期条目在本行之前已被归档剔除
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="fresh"))

        assert pool.cleanup_expired() == 0, "回收已由写入路径完成，此处无残留过期条目"
        stats = pool.get_retention_stats()
        assert stats["archived_by_reason"]["ttl"] == 1
        assert stats["resident_count"] == 1
        assert stats["eviction_ledger"]["total"] == 1

    def test_explicit_call_still_reclaims_directly(self):
        """显式调用仍是可用通路（运维/诊断与"某一刻全量对账"）。"""
        import datetime as _dt

        pool = _pool(ttl_seconds=60)
        stale = ContextInput(source=ContextSource.MEMORY, content="stale")
        stale.created_at = _dt.datetime.now() - _dt.timedelta(seconds=3600)
        # 绕过写入咽喉直插（历史/测试写法），过期条目留在常驻
        pool._collector.add_context(stale)
        pool._cache_version += 1

        assert pool.cleanup_expired() == 1
        assert pool.get_retention_stats()["archived_by_reason"]["ttl"] == 1

    def test_ttl_disabled_keeps_everything(self):
        pool = _pool(ttl_seconds=0)
        _fill(pool, 5)
        assert pool.cleanup_expired() == 0
        assert pool.resident_count() == 5


class TestReplacementIsCounted:
    def test_higher_priority_replacement_counted(self):
        pool = _pool()
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="same", priority=10))
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="same", priority=99))
        assert pool.get_retention_stats()["archived_by_reason"]["replaced"] == 1
        assert pool.resident_count() == 1


class TestRecyclingCostDoesNotScaleWithResident:
    """回收发生在 add 热路径上：单次 add 的成本不得随池规模增长。"""

    def test_add_cost_stays_flat_with_recycling_enabled(self):
        """逐条摘除（非整表重建）：第 N 条 add 的耗时不应随 N 增长。

        用"候选/索引结构规模"做结构断言 + 一次粗粒度耗时对比：
        旧写法每回收一条就 rebuild 全表（O(常驻数/条)），1k→20k 会劣化 20×。
        """
        import time

        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=100, ledger_db=ledger)

        def fill(n, measure_tail=False):
            start = time.perf_counter()
            for i in range(n):
                pool.add_context(
                    ContextInput(source=ContextSource.CONVERSATION, content=f"m{i}")
                )
                if measure_tail and i == n - 1001:
                    start = time.perf_counter()  # 只量尾部 1000 条
            return time.perf_counter() - start

        fill(1_000)
        early = fill(1_000, measure_tail=True)      # 池尚小
        fill(18_000)
        late = fill(1_000, measure_tail=True)       # 池已大（回收一直在跑）

        assert pool.resident_count() == 100
        assert pool.get_retention_stats()["archived_by_reason"]["capacity"] == 20_900
        # 尾段耗时不得出现数量级劣化（阈值宽松：只抓 O(N/条) 的整表重建）
        assert late < early * 8, f"回收成本随常驻规模劣化：early={early:.4f}s late={late:.4f}s"

    def test_partition_order_preserved_after_recycling(self):
        """逐条摘除后分区内其余条目保持插入序（分区直取的顺序契约）。"""
        ledger = _FakeLedgerDB()
        pool = _pool(resident_limit=3, ledger_db=ledger)
        for i in range(8):
            pool.add_context(ContextInput(source=ContextSource.MEMORY, content=f"m{i}"))
        assert [c.content for c in pool._read_index.session_entries("s1")] == ["m5", "m6", "m7"]
        assert [c.content for c in pool._read_index.source_entries(ContextSource.MEMORY)] == [
            "m5", "m6", "m7"
        ]


class TestApiReportsEffectiveCapacity:
    """Issue #65：API 也不得继续谎报 max_size 有效。"""

    def test_pool_settings_reports_max_size_ineffective(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context_pool_settings

        app = FastAPI()
        app.include_router(context_pool_settings.router, prefix="/v1/context-pool")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}

        data = TestClient(app).get("/v1/context-pool/pool-settings").json()["data"]
        assert data["max_size"] == 100  # 兼容保留（前端仍在读）
        assert data["max_size_effective"] is False, "API 又谎报 max_size 有效"
        assert data["resident_limit"] is None
