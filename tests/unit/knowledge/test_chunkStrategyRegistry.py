# -*- coding: utf-8 -*-
"""W8 切块策略注册表（specs/2026-11-12 §9）：十三 kind 闭集、非法参数拒、
缺省策略产物与既有 chunk_text 逐字一致（存量零漂移——preview 与摄取两入口）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.chunk_dispatch import (
    CHUNK_KINDS,
    ChunkStrategyRegistry,
    dispatchChunk,
)


SAMPLE = """# 标题一

这是第一段的正文，长度足够被切开。

```python
def fixed():
    return 1
```

第二段正文。这里有一句很长的话，用于验证句子边界与滑动窗口行为是否稳定可靠。

| 列A | 列B |
| --- | --- |
| 1   | 2   |
"""


class TestRegistry:
    def test_thirteenKindsClosed(self):
        assert len(CHUNK_KINDS) == 13
        for kind in ("fixed", "sentence", "paragraph", "recursive", "markdown",
                     "code", "table", "semantic", "sliding", "proposition",
                     "parentChild", "late", "document"):
            assert kind in CHUNK_KINDS

    def test_unknownKindRejectedAtRegistration(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        reg = ChunkStrategyRegistry(s)
        with pytest.raises(ValueError, match="闭集"):
            reg.register(strategyId="bad", tenantId="default", kind="ghost_kind")
        s.close()

    def test_roundTrip(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        reg = ChunkStrategyRegistry(s)
        row = reg.register(strategyId="para", tenantId="default", kind="paragraph",
                           params={"minChars": 20})
        assert row["kind"] == "paragraph"
        assert len(reg.list(tenantId="default")) == 1
        s.close()


class TestDispatch:
    def test_defaultMatchesChunkTextVerbatim(self):
        """缺省 structure 策略产物与既有 chunk_text 逐字一致（存量零漂移）。"""
        from neurova.knowledge.splitter import chunk_text

        legacy = chunk_text(SAMPLE)
        viaDispatch = dispatchChunk(None, SAMPLE, strategy=None)
        assert viaDispatch == legacy, "缺省分派产物逐字一致"

    def test_fixedKind(self):
        chunks = dispatchChunk(None, "abcdefghij" * 5, strategy={"kind": "fixed",
                                                                 "params": {"maxChars": 20}})
        assert all(len(c) <= 21 for c in chunks)
        assert len(chunks) >= 2

    def test_documentKind(self):
        chunks = dispatchChunk(None, SAMPLE, strategy={"kind": "document"})
        assert chunks == [SAMPLE]

    def test_parentChildDelegates(self):
        from neurova.knowledge.splitter import build_entry_chunks

        chunks = dispatchChunk(None, SAMPLE, strategy={"kind": "parentChild"})
        children, parents = build_entry_chunks(SAMPLE)
        assert chunks == children, "parentChild 分派到既有 build_entry_chunks（单源族不动）"

    def test_unknownStrategyKindFailsFast(self):
        with pytest.raises(ValueError):
            dispatchChunk(None, SAMPLE, strategy={"kind": "ghost"})
