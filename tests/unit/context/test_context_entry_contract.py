"""
上下文条目契约（内容指纹按来源分域 / 入池即估 token）单元测试。

来源沿革（B6-10 批次 C）：本文件原锁 `context.compressor.ContextCompressor`
的按预算压缩，而该类**整模块退役**——池没有压缩通路（真通路是
`orchestrator` 的信封+历史确定性淘汰，判据见 `test_envelope.py`），
它唯一的外部消费点 `ContextPool.compress_context` 也零消费，属同契约第二份实现。
按修复教义第 1 条「契约搬到真面、断言不删」：本文件改为锁**仍然存活**的那部分
契约——`ContextInput` 的内容指纹分域与入池代估 token，这两条生产者侧行为
（`ContextPool.add_context` → `ContextCollector.add_context`）仍在主链上。
原「按预算裁剪」的等价契约由 `SemanticMatchDrawer` 的视图层选取承担，
判据在 `test_envelope.py` 与 `test_drawer_scale_scoring.py`。
"""

import pytest

from neurova.context.pool_models import ContextInput
from neurova.context.pool_models import ContextSource
from neurova.context_pool import ContextPool


def _ctx(content: str, priority: int = 1, source: ContextSource = ContextSource.CONVERSATION) -> ContextInput:
    return ContextInput(source=source, content=content, priority=priority)


class TestEntryJoinsArchiveWithTokens:
    """入池即代估 token：池的归档条目必须带可用的 token 数（读路径按它取用）。"""

    def test_tokens_auto_estimated_on_add(self):
        pool = ContextPool(user_id="u", agent_id="a")
        entry = _ctx("需要估算 token 的内容")
        assert entry.tokens == 0
        pool.add_context(entry)
        assert entry.tokens > 0

    def test_all_entries_carry_tokens(self):
        pool = ContextPool(user_id="u", agent_id="a")
        for i in range(3):
            pool.add_context(_ctx("短内容" * 10 + str(i)))
        assert all(c.tokens > 0 for c in pool.get_contexts())


class TestArchiveIsLossless:
    """池是永久归档：入池条目不被按预算裁掉（裁剪只发生在视图层）。"""

    def test_small_budget_does_not_drop_entries(self):
        pool = ContextPool(user_id="u", agent_id="a", max_tokens=50)
        pool.add_context(_ctx("低优先级填充" * 30, priority=0))
        pool.add_context(_ctx("高优先级关键信息", priority=100))
        contents = [c.content for c in pool.get_contexts()]
        assert "高优先级关键信息" in contents
        assert len(contents) == 2, (
            "归档层不得按预算裁剪——池的容量控制发生在视图层（draw 整条选取）"
        )

    def test_empty_pool_has_no_entries(self):
        assert ContextPool(user_id="u", agent_id="a").get_contexts() == []

    def test_view_layer_selects_within_budget(self):
        """按预算取用是**视图层**（draw）的职责，不是归档层的。"""
        pool = ContextPool(user_id="u", agent_id="a", max_tokens=60)
        pool.add_context(_ctx("P3 内容" * 20, priority=3))
        pool.add_context(_ctx("P9 内容" * 5, priority=9))
        pool.add_context(_ctx("P1 内容" * 20, priority=1))
        drawn = pool.draw(budget_tokens=60)
        assert drawn, "视图层必须在预算内选出条目"
        assert sum(c.tokens for c in drawn) <= 60
        assert ("P9 内容" * 5) in [c.content for c in drawn], (
            "预算紧张时高优先级条目必须先被选中"
        )


class TestSourceEnum:
    def test_memory_source_exists(self):
        assert ContextSource.MEMORY.value == "memory"

    def test_hash_scoped_by_source(self):
        c1 = ContextInput(source=ContextSource.MEMORY, content="同文")
        c2 = ContextInput(source=ContextSource.CONVERSATION, content="同文")
        # source 域限定指纹：不同来源的相同内容哈希不同
        assert c1.hash != c2.hash
