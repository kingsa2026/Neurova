# -*- coding: utf-8 -*-
"""JSON 旁路存储隔离面 fail-closed（审计 3.3-6，2026-11-17）：

`MemoryStorage._passesIsolation` 原对 `isolation_context=None` 直接放行——
三层隔离过滤（agent/neuser/user）在"调用方忘了传上下文"时整个失效，
JSON 旁路存储退化为全量可见。None 语义改 fail-closed：没有身份上下文
就不给看（主检索不经它、上游 query/list_by_tags 无生产调用方，影响面
限于旁路面与测试）。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage


@pytest.fixture
def store(tmp_path) -> MemoryStorage:
    return MemoryStorage(str(tmp_path / "records"))


_CTX = IsolationContext(agent_id="agt-1", neuser_id="nu-1", user_id="u-1")


class TestIsolationFailClosed:
    def test_none_context_passes_nothing(self, store):
        """None 上下文 = 无身份 = 不可见（fail-closed，原实现全量放行=红）。"""
        store.save(content="s", memory_type="episodic", isolation_context=_CTX)
        assert store.query() == [], "无隔离上下文的查询必须返回空（fail-closed）"

    def test_with_context_still_visible(self, store):
        """传了正确上下文，读写契约不变。"""
        store.save(content="s1", memory_type="episodic", isolation_context=_CTX)
        rows = store.query(isolation_context=_CTX)
        assert [r["content"] for r in rows] == ["s1"]

    def test_list_by_tags_none_context_empty(self, store):
        store.save(content="tagged", memory_type="episodic", tags=["t"], isolation_context=_CTX)
        assert store.list_by_tags(["t"]) == [], "list_by_tags 同口径 fail-closed"

    def test_other_agent_context_cannot_see(self, store):
        store.save(content="s", memory_type="episodic", isolation_context=_CTX)
        other = IsolationContext(agent_id="agt-2", neuser_id="nu-1", user_id="u-1")
        assert store.query(isolation_context=other) == [], "跨 agent 隔离语义保持拒绝"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
