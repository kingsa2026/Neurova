# -*- coding: utf-8 -*-
"""P2-2 收口：memory citation 溯源标记（渲染/抽取/注入行组装）。"""
import pytest

from neurova.memory.citation import (
    extract_citations,
    render_citation,
    render_memory_line,
)


class TestRenderCitation:
    def test_with_memory_id(self):
        marker = render_citation({"memory_id": "m-1", "content": "x", "category": "preference", "score": 0.9})
        assert '<memory_citation memory_id="m-1"' in marker
        assert 'category="preference"' in marker
        assert 'score="0.9"' in marker
        assert marker.endswith("/>")

    def test_fallback_id_fields(self):
        assert 'memory_id="k-7"' in render_citation({"knowledge_id": "k-7"})
        assert 'memory_id="i-2"' in render_citation({"id": "i-2"})

    def test_no_identifier_no_marker(self):
        assert render_citation({"content": "only content"}) == ""
        assert render_citation("plain string") == ""
        assert render_citation(None) == ""

    def test_none_values_omitted(self):
        marker = render_citation({"memory_id": "m", "score": None})
        assert "score" not in marker


class TestRenderMemoryLine:
    def test_with_citation(self):
        line = render_memory_line({"content": "用户偏好深色", "memory_id": "m-9"})
        assert line == "[记忆] 用户偏好深色 <memory_citation memory_id=\"m-9\"/>"

    def test_without_identifier_format_unchanged(self):
        assert render_memory_line({"content": "abc"}) == "[记忆] abc"
        assert render_memory_line("raw") == "[记忆] raw"

    def test_custom_prefix(self):
        line = render_memory_line({"content": "x", "id": "1"}, prefix="[经验]")
        assert line.startswith("[经验] x ")

    def test_citation_not_in_hash_input(self):
        """召回去重 hash 按 content 计算——citation 只在展示行后缀。"""
        from neurova.context_pool import ContextInput, ContextSource

        h1 = ContextInput.compute_hash(ContextSource.MEMORY, "用户偏好深色")
        h2 = ContextInput.compute_hash(
            ContextSource.MEMORY, "用户偏好深色 <memory_citation memory_id=\"m-9\"/>"
        )
        assert h1 != h2  # hash 面不含 citation（组装顺序：hash 先于渲染）


class TestExtractCitations:
    def test_extract_roundtrip(self):
        text = '根据 [记忆] 深色 <memory_citation memory_id="m-9" category="preference"/> 的记录'
        out = extract_citations(text)
        assert out == [{"memory_id": "m-9", "category": "preference"}]

    def test_multiple_and_none(self):
        text = '<memory_citation memory_id="a"/><memory_citation memory_id="b"/>无引用'
        assert [c["memory_id"] for c in extract_citations(text)] == ["a", "b"]
        assert extract_citations("no citations here") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
