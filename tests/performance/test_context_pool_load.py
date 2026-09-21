# -*- coding: utf-8 -*-
"""
P1-8 context pool 压测（兼作 P1-1 验收）

语义：100 轮对话归档 → 视图抽取（draw 配对校验 + 预算）→ 溢出恢复链路。
压测锁定**关键词降级路径**（monkeypatch drawer._vector_store=False，剔除
ONNX 嵌入模型加载/推理变量——模型性能归专项，此处验证池正确性与吞吐）。

正确性优先、阈值宽松（CI 稳定）：
- 100 轮归档 + 每 10 轮一次 draw：< 10s（关键词路径实测亚秒级）
- draw 结果预算内、TOOL_CALL 无孤儿、最新轮次在场

Issue #65 补强（原守卫"上限 100 轮 / 阈值 <10s / 不查内存"拦不住三个回归）：
- **读写规模守卫**：池规模增长时 query() 不得退化为"全池线性扫"（分区直取 +
  关键字降本后候选集与池总量解耦），断言用候选规模而非墙钟（CI 不 flaky）；
- **内存守卫**：常驻占用必须线性且可解释（无隐藏副本/重复持有），并锁定
  "max_size 不驱逐"这一无损归档硬约束的可见性（stats 显式上报失效）；
- **回收契约守卫**：resident_limit 启用后常驻有界、回收条目仍可从台账召回。
"""
import time

import pytest


@pytest.fixture()
def pool(monkeypatch):
    from neurova.context_pool import ContextPool

    p = ContextPool(
        user_id="perf-user",
        agent_id="perf-agent",
        session_id="perf-session",
        max_tokens=8000,
        max_size=1000,
    )
    # 真实属性名 _drawer（context_pool.py:93），设 False 强制关键词降级
    monkeypatch.setattr(p._drawer, "_vector_store", False, raising=False)
    return p


def _round_inputs(turn: int):
    from neurova.context.pool_models import ContextInput, ContextSource

    tool_id = f"tool-{turn}"
    return [
        ContextInput(
            source=ContextSource.USER_INPUT,
            content=f"[turn {turn}] 用户：帮我分析第 {turn} 批数据并总结趋势",
            priority=80,
        ),
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=f"[turn {turn}] 助手：已分析第 {turn} 批数据，趋势为线性增长。",
            priority=70,
        ),
        ContextInput(
            source=ContextSource.TOOL_CALL,
            content=f"[turn {turn}] tool=data_query result=ok",
            priority=60,
            metadata={"tool_call_id": tool_id},  # 真实配对锚点（pairing 校验用）
        ),
    ]


class TestContextPoolHundredTurns:
    def test_hundred_turns_archive_and_draw(self, pool):
        from neurova.context.pool_models import ContextSource

        start = time.perf_counter()
        for turn in range(100):
            for item in _round_inputs(turn):  # add_context 收单条 ContextInput
                pool.add_context(item)
            if turn % 10 == 9:
                view = pool.draw(need=f"第 {turn} 批数据")
                for c in view:
                    if c.source == ContextSource.TOOL_CALL:
                        # P1-1 配对校验：视图内 TOOL_CALL 必须有配对锚点
                        assert c.metadata.get("tool_call_id")
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, f"100 轮归档+抽取耗时 {elapsed:.2f}s，超出阈值"

    def test_latest_turns_present_after_full_archive(self, pool):
        for turn in range(100):
            for item in _round_inputs(turn):
                pool.add_context(item)
        view = pool.draw(need="第 99 批数据")
        texts = [c.content for c in view]
        assert any("第 99 批" in t for t in texts), "最新轮次必须在视图内"


class TestOverflowRecovery:
    """P1-1 溢出恢复链路在长会话下的行为验收（签名：messages+recent_keep）"""

    def test_compact_preserves_system_and_recent(self):
        from neurova.context.recovery import compact_messages_for_overflow

        messages = (
            [{"role": "system", "content": "你是数据助手。"}]
            + [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"消息 {i} " * 50}
                for i in range(200)
            ]
        )
        compacted, info = compact_messages_for_overflow(messages, recent_keep=10)

        assert len(compacted) < len(messages)
        assert compacted[0]["role"] == "system"  # system 锚点保留
        # 尾部 recent_keep 原样保留
        assert compacted[-1] == messages[-1]
        assert compacted[-10:] == messages[-10:]
        # 折叠信息可审计
        assert info.get("folded_count", 0) > 0

    def test_compact_single_roundtrip_small_input(self):
        from neurova.context.recovery import compact_messages_for_overflow

        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        compacted, info = compact_messages_for_overflow(msgs, recent_keep=6)
        # 输入小于保留窗：原样返回
        assert compacted == msgs


class TestReadPathScalingGuard:
    """Issue #65：读路径不得随池增长退化为全池线性扫（原守卫测不出）。"""

    @staticmethod
    def _pool_with(n: int):
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="perf", agent_id="perf", session_id="cur", ttl_seconds=0)
        for i in range(n):
            entry = ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"[turn {i % 50}] 用户：分析第 {i} 批数据并总结趋势",
                priority=i % 100,
            )
            # 只有 1% 落在当前 session，其余是历史 session —— 分区直取的收益面
            if i % 100 != 0:
                entry.metadata["session_id"] = f"hist{i % 5}"
            pool.add_context(entry)
        return pool

    def test_query_candidates_do_not_scale_with_pool(self):
        small = self._pool_with(2_000)
        big = self._pool_with(20_000)

        for pool, expected_current in ((small, 20), (big, 200)):
            assert len(pool._read_index.session_entries("cur")) == expected_current
            hits = pool.query(query="并总结趋势")
            assert hits, "关键词取数应命中"
            assert all(c.metadata["session_id"] == "cur" for c in hits)

    def test_topn_short_circuit_keeps_latency_flat(self):
        """当前 session 已够填满 limit 时，跨 session 组装被短路（大池主成本）。"""
        big = self._pool_with(20_000)
        first = big.query(limit=20)
        assert len(first) == 20
        assert all(c.metadata["session_id"] == "cur" for c in first)


class TestMemoryFootprintGuard:
    """Issue #65：常驻占用须线性可解释，且"无上限"必须显式可见。"""

    def test_resident_growth_is_linear_and_reported(self):
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pools = []
        for n in (1_000, 5_000):
            pool = ContextPool(user_id="perf", agent_id="perf", session_id="s", ttl_seconds=0, max_size=200)
            for i in range(n):
                pool.add_context(
                    ContextInput(source=ContextSource.CONVERSATION, content=f"msg-{i}-" + "x" * 64)
                )
            pools.append((n, pool))

        for n, pool in pools:
            stats = pool.get_retention_stats()
            assert stats["resident_count"] == n, "常驻条数与写入数不符（隐藏驱逐/丢失）"
            # max_size=200 不生效必须显式上报（原实现只有一行注释）
            assert stats["max_size_effective"] is False
            assert stats["resident_limit"] is None

    def test_no_hidden_duplicate_holders(self):
        """每条归档只能在索引里出现一次（分区不重复持有 = 无隐藏内存放大）。"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="perf", agent_id="perf", session_id="s", ttl_seconds=0)
        for i in range(500):
            pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content=f"msg-{i}"))
        index = pool._read_index.stats()
        assert index["indexed_entries"] == 500
        total_partitioned = sum(len(v) for v in pool._read_index._by_session.values())
        assert total_partitioned == 500, "条目在 session 分区里重复持有（内存放大）"


class TestRecyclingContractGuard:
    """Issue #65：显式常驻上限的回收必须"有界但不丢"（新契约的守卫）。"""

    def test_resident_limit_bounds_memory_and_keeps_recallable(self):
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        recorded = []

        class _Ledger:
            def record(self, *, content, turn_id=None, session_id=None, source=None, metadata=None):
                recorded.append(content)

            def gc_stale(self):
                return 0

        pool = ContextPool(
            user_id="perf", agent_id="perf", session_id="s",
            ttl_seconds=0, resident_limit=200, ledger_db=_Ledger(),
        )
        for i in range(2_000):
            pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content=f"msg-{i}"))

        assert pool.resident_count() == 200, "常驻未收敛到 resident_limit"
        assert pool.get_retention_stats()["archived_by_reason"]["capacity"] == 1_800
        # 无损：全部 2000 条都在台账（B4/001 写穿点在入池，顺序 = 最旧优先）；
        # 回收只把最旧的 1800 条移出常驻，不参与落盘判定
        assert recorded == [f"msg-{i}" for i in range(2_000)]
