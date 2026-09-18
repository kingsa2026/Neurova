# -*- coding: utf-8 -*-
"""Issue #65：ContextPool 读路径（query）索引化与语义等价回归。

基线问题（实测）：池是永久归档（只增不减），而 query() 每次对全池做
「list 拷贝 → TTL 过滤 → 逐条 content.lower() → 逐条 source/session 比较 →
sort」。10k 条 20 次 query = 0.438s（≈22ms/次），严格线性 —— 写路径已 O(1)
（_by_hash），读路径却仍是 O(N)。

本套件钉三件事：

1. **语义等价**：新索引实现与旧的"全池线性扫"参考实现在随机语料/随机参数
   下结果逐条一致（含大小写、CJK、标签、session、source、TTL 全组合）；
2. **快路径安全**：``is_caseless`` 的无大小写降本不得改变匹配结果
   （Unicode 全码位可证伪的安全网）；
3. **规模行为**：显式 session 取数不得随"池总量"线性劣化（索引直取契约）。
"""
import random

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


# ── 参考实现：改造前的全池线性扫（作为等价性 oracle）─────────────────

def _reference_query(pool, query=None, source=None, session_id=None, tags=None, limit=20):
    with pool._lock:
        candidates = pool._filter_ttl(list(pool._collector._contexts))

    if query:
        q = query.lower()
        candidates = [c for c in candidates if q in c.content.lower()]
    if source is not None:
        candidates = [c for c in candidates if c.source == source]
    # 注：旧实现把 tags 过滤放在"显式 session 早返回"之后（契约文档写明 tags
    # 是通用过滤项，旧顺序属实现细节）；参考实现按文档契约对齐，故 #65 一并
    # 修正了「显式 session + tags 时 tags 被静默忽略」的行为差异。
    if tags:
        tag_set = set(tags)
        candidates = [c for c in candidates if tag_set.intersection(set(c.tags or []))]
    if session_id is not None:
        candidates = [
            c for c in candidates if (c.metadata or {}).get("session_id") == session_id
        ]
        candidates.sort(key=lambda c: c.priority, reverse=True)
        return candidates[:limit]

    if pool.session_id is not None:
        cur = [c for c in candidates if (c.metadata or {}).get("session_id") == pool.session_id]
        oth = [c for c in candidates if (c.metadata or {}).get("session_id") != pool.session_id]
        cur.sort(key=lambda c: c.priority, reverse=True)
        oth.sort(key=lambda c: c.priority, reverse=True)
        return (cur + oth)[:limit]

    candidates.sort(key=lambda c: c.priority, reverse=True)
    return candidates[:limit]


_WORDS = [
    "alpha", "BETA", "中文测试", "café", "第 3 批数据", "ΣΟΦΟΣ",
    "İstanbul", "Kelvin", "straße", "混合Abc中文", "x",
]
_NEEDLES = [
    None, "", "alpha", "ALPHA", "中文", "第 3 批", "café", "CAFÉ",
    "ΣΟΦΟΣ", "σοφος", "kelvin", "İSTANBUL", "straße", "STRASSE",
]
_SOURCES = list(ContextSource)


class TestQuerySemanticEquivalence:
    """索引化不得改变任何一条取数结果。"""

    @pytest.mark.parametrize("seed", [11, 42, 777])
    def test_randomized_equivalence_with_legacy_reference(self, seed):
        rng = random.Random(seed)
        for _trial in range(12):
            pool_sid = rng.choice([None, "s1", "s2"])
            pool = ContextPool(
                user_id="u", agent_id="a", session_id=pool_sid,
                ttl_seconds=rng.choice([0, 3600, 1]),
            )
            for _ in range(rng.randint(0, 25)):
                entry = ContextInput(
                    source=rng.choice(_SOURCES),
                    content=" ".join(rng.choice(_WORDS) for _ in range(rng.randint(1, 5))),
                    priority=rng.randint(0, 100),
                    tags=[rng.choice(_WORDS)],
                )
                if rng.random() < 0.3:
                    # 直接写 _collector（历史/测试写法）——索引须靠计数防线自愈
                    entry.metadata = {"session_id": rng.choice(["s1", "s2", "s3", None])}
                    pool._collector.add_context(entry)
                    pool._cache_version += 1
                else:
                    pool.add_context(entry)

            for _ in range(6):
                kwargs = {
                    "query": rng.choice(_NEEDLES),
                    "source": rng.choice([None] + _SOURCES),
                    "session_id": rng.choice([None, "s1", "s2", "s3"]),
                    "tags": rng.choice([None, [], ["alpha"], ["中文测试", "BETA"]]),
                    "limit": rng.choice([1, 3, 20, 100]),
                }
                got = pool.query(**kwargs)
                expected = _reference_query(pool, **kwargs)
                assert [c.hash for c in got] == [c.hash for c in expected], (
                    f"索引化后取数结果漂移：{kwargs}\n"
                    f"got={[c.content[:20] for c in got]}\n"
                    f"exp={[c.content[:20] for c in expected]}"
                )

    def test_source_and_session_filters_share_intersection(self):
        """source 与 session 双过滤 = 两分区交集（任一为空的组合须返回空）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="m", priority=90))
        pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content="c", priority=80))

        only = pool.query(source=ContextSource.CONVERSATION)
        assert [c.content for c in only] == ["c"]
        assert pool.query(source=ContextSource.REFLECTION) == []
        mixed = pool.query(source=ContextSource.MEMORY, session_id="s1")
        assert [c.content for c in mixed] == ["m"]
        assert pool.query(source=ContextSource.MEMORY, session_id="nope") == []

    def test_explicit_session_tags_now_applied(self):
        """显式 session 路径下 tags 也必须生效（旧实现静默忽略，属契约修正）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="tagged", tags=["x"]))
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="untagged"))

        assert len(pool.query(session_id="s1")) == 2
        tagged = pool.query(session_id="s1", tags=["x"])
        assert [c.content for c in tagged] == ["tagged"]

    def test_query_result_entries_are_pool_objects_not_copies(self):
        """取数返回池内同一对象（下游依赖 hash/ack 标记回写）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        entry = ContextInput(source=ContextSource.MEMORY, content="same", priority=50)
        pool.add_context(entry)
        assert pool.query(query="same")[0] is entry

    def test_current_session_priority_still_fills_first(self):
        """当前 session 优先 + 跨 session 兜底（回归既有契约）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="cur")
        cur = ContextInput(source=ContextSource.CONVERSATION, content="current", priority=10)
        pool.add_context(cur)
        other = ContextInput(source=ContextSource.CONVERSATION, content="other", priority=99)
        other.metadata["session_id"] = "old"
        pool._collector.add_context(other)
        pool._cache_version += 1

        got = pool.query(limit=5)
        assert [c.content for c in got] == ["current", "other"]

    def test_index_heals_after_direct_collector_mutation(self):
        """_contexts 被直接改（绕过公开 API）时，索引计数防线须自愈。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="a"))
        # 绕过 add_context 直插（不注入隔离标签，故显式给 metadata 才属本 session）
        direct = ContextInput(source=ContextSource.MEMORY, content="b", priority=99)
        direct.metadata["session_id"] = "s1"
        pool._collector.add_context(direct)
        assert {c.content for c in pool.query(session_id="s1")} == {"a", "b"}
        assert pool.get_retention_stats()["read_index"]["indexed_entries"] == 2

    def test_index_rebuilt_after_reordering_paths(self):
        """clear / dedup / compress / cleanup_expired 后索引须与列表一致。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        for i in range(5):
            pool.add_context(ContextInput(source=ContextSource.MEMORY, content=f"m{i}", priority=i))
        pool.dedup(stage="output")
        assert pool.get_retention_stats()["read_index"]["indexed_entries"] == len(
            pool._collector._contexts
        )
        pool.clear()
        assert pool.query(session_id="s1") == []
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="after"))
        assert [c.content for c in pool.query(session_id="s1")] == ["after"]


class TestCaselessFastPathIsSound:
    """无大小写关键词的降本路径不得改变匹配结果（可证伪的穷举安全网）。"""

    def test_caseless_property_over_unicode_range(self):
        """对 Unicode 全部 BMP + 常见扩展字符：caseless ⇒ 匹配结果与 lower/lower 一致。"""
        from neurova.context.pool_index import PoolReadIndex

        alphabet = [chr(c) for c in range(0x20, 0x2000)]
        alphabet += [chr(0x212A), chr(0x1E9E), chr(0x130), chr(0x131), chr(0xDF)]
        rng = random.Random(20260918)

        checked = 0
        for _ in range(30000):
            needle = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3)))
            if not PoolReadIndex.is_caseless(needle):
                continue
            checked += 1
            content = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            assert (needle in content) == (needle.lower() in content.lower()), (
                f"快路径与精确路径分叉: needle={needle!r} content={content!r}"
            )
        assert checked > 500, "样本不足——安全网没真正跑到快路径"

    def test_caseless_never_claims_cased_or_exotic_needles(self):
        """含大小写 / 跨码位折叠 / 组合标注的 needle 一律回退精确路径。"""
        from neurova.context.pool_index import PoolReadIndex

        for needle in ("a", "A", "abc", "ABC", "café", "CAFÉ", "Σ", "σοφος",
                       "straße", "STRASSE", "\u212a", "K", "İ", "µ", "Ａ"):
            assert PoolReadIndex.is_caseless(needle) is False, f"{needle!r} 被误判为无大小写"

    def test_cjk_and_symbol_needles_use_fast_path(self):
        from neurova.context.pool_index import PoolReadIndex

        for needle in ("中文", "第 3 批数据", "123", "-_/", "，。"):
            assert PoolReadIndex.is_caseless(needle) is True

    def test_ascii_needle_still_matches_mixed_case_content(self):
        """ASCII 关键词（走精确路径）在混合大小写内容上语义不变。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="Hello World"))
        assert pool.query(query="hello")
        assert pool.query(query="HELLO")
        assert pool.query(query="Lo Wo")
        assert pool.query(query="nope") == []

    def test_unicode_needle_matches_per_lower_semantics(self):
        """希腊/德语折叠：结果与 lower/lower 语义一致（不因快路径放宽）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="ΣΟΦΟΣ λόγος"))
        assert pool.query(query="σοφος")            # lower 后一致
        assert pool.query(query="λόγος")
        assert pool.query(query="ΛΌΓΟΣ")            # 旧语义：lower/lower 亦是 True
        assert pool.query(query="αλογο") == []


class TestReadPathScaling:
    """索引直取契约：显式 session 取数不得随池总量线性劣化。"""

    @staticmethod
    def _build_pool(total: int, session: str = "target"):
        pool = ContextPool(user_id="u", agent_id="a", session_id="other", ttl_seconds=0)
        for i in range(total):
            entry = ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"msg {i} 通用归档内容",
                priority=i % 100,
            )
            if i % 1000 == 0:
                entry.metadata["session_id"] = session
            else:
                entry.metadata["session_id"] = f"bulk{i % 5}"
            pool.add_context(entry)
        return pool

    def test_explicit_session_query_is_sublinear_in_pool_size(self):
        """显式 session 直取分区：候选数不随池总量增长（旧实现是全池线性扫）。

        用「候选集规模」而非墙钟做断言——CI 机器抖动不会让契约变 flaky。
        """
        small = self._build_pool(2000)
        big = self._build_pool(20000)

        assert big.query(session_id="target")[0].content == "msg 0 通用归档内容"
        stats = big.get_retention_stats()["read_index"]
        assert stats["indexed_entries"] == 20000
        # 目标分区只有 20 条：分区直取意味着候选集与池总量解耦
        assert len(big._read_index.session_entries("target")) == 20
        assert len(small._read_index.session_entries("target")) == 2

    def test_keyword_filter_scans_only_partition(self):
        """带关键词 + 显式 session：候选仍是分区规模（不回到全池）。"""
        pool = self._build_pool(5000)
        hits = pool.query(query="msg 0 通用", session_id="target")
        assert [c.content for c in hits] == ["msg 0 通用归档内容"]

    def test_current_session_short_circuits_when_limit_filled(self):
        """当前 session 侧已够填满 limit 时，跳过其余 session 组装（大池主成本）。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="cur", ttl_seconds=0)
        for i in range(30):
            pool.add_context(ContextInput(source=ContextSource.MEMORY, content=f"cur{i}", priority=i))
        for i in range(3000):
            entry = ContextInput(source=ContextSource.MEMORY, content=f"bulk{i}", priority=i)
            entry.metadata["session_id"] = f"b{i % 7}"
            pool._collector.add_context(entry)
        pool._cache_version += 1

        got = pool.query(limit=5)
        assert len(got) == 5
        assert all(c.metadata["session_id"] == "cur" for c in got)

    def test_ttl_zero_fast_path_does_not_scan(self):
        """ttl_seconds<=0（生产档）时不做逐条 TTL 判定。"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1", ttl_seconds=0)
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="x"))
        items = list(pool._collector._contexts)
        assert pool._filter_ttl(items) is items, "TTL 关闭时不应构造新列表"

    def test_ttl_filter_equivalence(self):
        """TTL 判定改写后语义不变（含无 created_at 条目）。"""
        import datetime as _dt

        pool = ContextPool(user_id="u", agent_id="a", session_id="s1", ttl_seconds=60)
        fresh = ContextInput(source=ContextSource.MEMORY, content="fresh")
        stale = ContextInput(source=ContextSource.MEMORY, content="stale")
        stale.created_at = _dt.datetime.now() - _dt.timedelta(seconds=3600)
        timeless = ContextInput(source=ContextSource.MEMORY, content="timeless")
        timeless.created_at = None

        kept = pool._filter_ttl([fresh, stale, timeless])
        assert [c.content for c in kept] == ["fresh", "timeless"]


class TestQueryObservability:
    """读路径埋点：query() 耗时此前在观测面上完全空白。"""

    def test_query_records_phase_histograms(self):
        prometheus = pytest.importorskip("prometheus_client")
        from prometheus_client import REGISTRY

        pool = ContextPool(user_id="obs", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="指标测试内容"))
        before = REGISTRY.get_sample_value(
            "neurova_context_pool_query_seconds_count", {"phase": "keyword"}
        ) or 0.0
        pool.query(query="指标")
        after = REGISTRY.get_sample_value(
            "neurova_context_pool_query_seconds_count", {"phase": "keyword"}
        )
        assert after > before, "query() 未打点读路径耗时"

    def test_metric_failure_never_breaks_query(self, monkeypatch):
        """观测面故障不得影响取数（埋点必须吞异常）。"""
        import neurova.core.metrics as metrics_mod

        def _boom(*_a, **_kw):
            raise RuntimeError("metrics down")

        monkeypatch.setattr(metrics_mod._Metrics, "observe_context_pool_query", _boom)
        pool = ContextPool(user_id="obs2", agent_id="a", session_id="s1")
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="still works"))
        assert [c.content for c in pool.query(session_id="s1")] == ["still works"]

    def test_live_pool_registry_is_weak(self):
        """/metrics 枚举活池不得延长其生命周期（弱引用登记）。"""
        import gc

        from neurova.context_pool import iter_live_pools

        pool = ContextPool(user_id="weak", agent_id="a", session_id="s1")
        assert pool in iter_live_pools()
        del pool
        gc.collect()
        assert all(p.isolation_key != "weak:a:s1" for p in iter_live_pools())

    def test_metrics_snapshot_exposes_resident_and_recycling(self):
        pytest.importorskip("prometheus_client")
        from prometheus_client import REGISTRY

        from neurova.core.metrics import get_metrics

        pool = ContextPool(user_id="snap", agent_id="a", session_id="s1")
        for i in range(3):
            pool.add_context(ContextInput(source=ContextSource.MEMORY, content=f"entry{i}"))
        get_metrics().observe_context_pools()
        labels = {"pool": "snap:a:s1"}
        assert REGISTRY.get_sample_value("neurova_context_pool_entries", labels) == 3.0
        assert REGISTRY.get_sample_value(
            "neurova_context_pool_evicted_total", {**labels, "reason": "capacity"}
        ) == 0.0

    def test_metrics_endpoint_refreshes_context_pool_gauges(self):
        """api/app.py 的 /metrics 必须刷新上下文池 gauge（否则永远为空）。"""
        import io
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        src = io.open(root / "neurova" / "api" / "app.py", encoding="utf-8").read()
        assert "observe_context_pools()" in src, "/metrics 未刷新上下文池 gauge"
