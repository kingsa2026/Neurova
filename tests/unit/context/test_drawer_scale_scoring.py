# -*- coding: utf-8 -*-
"""B5 规模：调取路径的打分成本与候选集上界（Issue #90 审计 P1-4 / D3）。

红灯依据（改前实证）：

- `SemanticMatchDrawer.draw` 对**同一个 need** 反复编码：`_relevant()` 与
  `_calculate_score()` 各自调一次 `_calculate_match_score`，非 CONVERSATION 条目
  每条被编码 2 次以上；实测 40 条池内、need 编码 **55 次**（真值应为 1）。
- 归档文本同样重复编码：单条文本在一轮 draw 内最多被编码 55 次。
- 候选集无上界：池规模多大就逐条打分多少条，`RELEVANCE_FLOOR` 之前没有任何
  廉价粗筛（审计 P1-4「对 RELEVANCE_FLOOR 前置廉价词法粗筛」）。

契约（修复后）：

1. 单次 draw 内 need 只编码一次；
2. 单次 draw 内任一文本编码至多一次（去重语义）；
3. 池规模超过候选集上限时，先用零编码的词法粗筛收敛候选，**未入选条目留在池中**
   （归档无损语义不变），进入语义打分的条目数 ≤ 上限；
4. 打分不得逐条做 python 级余弦（批量矩阵路径）。

本文件只锁可观察事实（编码次数 / 选中集合），不锁实现形状。
"""

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


class CountingVectorStore:
    """真契约替身：确定性向量 + 编码次数计数（非 MagicMock，不用恒真断言）。

    模拟真后端的两条性质：
    - 同文本重复编码在本层被缓存（真实现走内容寻址缓存）；
    - 批量入口 `encodeMany` 与本层缓存同源。
    """

    def __init__(self, dim: int = 8):
        self._dim = dim
        self.encode_calls = {}
        self.cache = {}
        self.batch_calls = 0

    def _vector(self, text: str):
        digest = 0
        for ch in text:
            digest = (digest * 131 + ord(ch)) % 100003
        return [float((digest >> (i * 3)) & 7) for i in range(self._dim)]

    def encode(self, text: str):
        self.encode_calls[text] = self.encode_calls.get(text, 0) + 1
        if text not in self.cache:
            self.cache[text] = self._vector(text)
        return self.cache[text]

    def encodeMany(self, texts):
        self.batch_calls += 1
        return [self.encode(t) for t in texts]

    @property
    def distinct_encoded(self) -> int:
        return len(self.encode_calls)

    @property
    def max_repeat(self) -> int:
        return max(self.encode_calls.values()) if self.encode_calls else 0


def _pool_entries(count: int, source=ContextSource.CONVERSATION, offset: int = 0):
    """池条目构造：内容**逐条唯一**（同内容重复条目是另一条契约，不混在本文件）。"""
    return [
        ContextInput(
            source=source,
            content=f"归档条目 {source.value}-{offset + i}：固件升级失败回滚记录",
            priority=60,
            tokens=10,
        )
        for i in range(count)
    ]


class TestSinglePassEncoding:
    def test_need_encoded_once_per_draw(self):
        """need 是同一串文本：一轮 draw 内只允许一次语义编码。"""
        entries = _pool_entries(20) + _pool_entries(20, ContextSource.MEMORY, offset=100)
        drawer = SemanticMatchDrawer(max_tokens=100000)
        store = CountingVectorStore()
        drawer._vector_store = store

        drawer.draw(entries, need="固件升级失败了怎么办")

        assert store.encode_calls.get("固件升级失败了怎么办", 0) == 1, (
            f"need 被编码 {store.encode_calls.get('固件升级失败了怎么办', 0)} 次，"
            "契约要求单轮至多一次"
        )

    def test_each_archive_text_encoded_at_most_once(self):
        """同一条归档文本在一轮 draw 内不得被重复编码。"""
        entries = _pool_entries(20) + _pool_entries(20, ContextSource.MEMORY, offset=100)
        drawer = SemanticMatchDrawer(max_tokens=100000)
        store = CountingVectorStore()
        drawer._vector_store = store

        drawer.draw(entries, need="固件升级失败了怎么办")

        assert store.max_repeat <= 1, f"单文本最高重复编码 {store.max_repeat} 次，契约要求 ≤ 1"


class TestCandidateCeiling:
    def test_candidate_ceiling_bounds_encoding(self):
        """池规模超过候选上限：进入语义打分的条目数受上限约束。"""
        ceiling = 50
        entries = _pool_entries(600)
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9, max_candidates=ceiling)
        store = CountingVectorStore()
        drawer._vector_store = store

        drawer.draw(entries, need="固件升级失败了怎么办")

        # need 1 次 + 候选 ≤ ceiling 次
        assert store.distinct_encoded <= ceiling + 1, (
            f"进入语义打分的文本数 {store.distinct_encoded} 超过候选上限 {ceiling} + need"
        )

    def test_prefiltered_entries_stay_in_archive(self):
        """粗筛只收敛候选集，不改变归档：未被选中的条目仍在池中。"""
        ceiling = 10
        entries = _pool_entries(200)
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9, max_candidates=ceiling)
        store = CountingVectorStore()
        drawer._vector_store = store

        selected = drawer.draw(entries, need="固件升级失败了怎么办")

        assert set(map(id, selected)) <= set(map(id, entries))
        assert len(entries) == 200

    def test_under_ceiling_no_prefilter(self):
        """池规模在上限以内时不得触发任何粗筛（零行为变化）。"""
        ceiling = 500
        entries = _pool_entries(30)
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9, max_candidates=ceiling)
        store = CountingVectorStore()
        drawer._vector_store = store

        drawer.draw(entries, need="固件升级失败了怎么办")

        # 30 条全部进入打分：need + 30
        assert store.distinct_encoded == 31


class TestRankingUnchanged:
    def test_draw_is_deterministic_for_same_input(self):
        """收敛编码路径必须对同输入同输出（前缀缓存契约，跨轮稳定）。"""
        entries = _pool_entries(40) + _pool_entries(40, ContextSource.MEMORY, offset=100)
        need = "固件升级失败了怎么办"

        first = SemanticMatchDrawer(max_tokens=100000)
        first._vector_store = CountingVectorStore()
        second = SemanticMatchDrawer(max_tokens=100000)
        second._vector_store = CountingVectorStore()

        left = first.draw(entries, need=need)
        right = second.draw(entries, need=need)

        assert [c.content for c in left] == [c.content for c in right]

    def test_floor_still_applies_after_batching(self):
        """批量打分不得削弱相关性门槛：入选的非对话条目必须过门槛。"""
        entries = _pool_entries(40, ContextSource.MEMORY)
        need = "固件升级失败了怎么办"
        drawer = SemanticMatchDrawer(max_tokens=100000)
        store = CountingVectorStore()
        drawer._vector_store = store

        selected = drawer.draw(entries, need=need)

        assert selected, "门槛内应有条目入选（同语种相关内容）"
        for entry in selected:
            assert drawer._calculate_match_score(entry, need) >= SemanticMatchDrawer.RELEVANCE_FLOOR
