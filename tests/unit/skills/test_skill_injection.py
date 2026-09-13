# -*- coding: utf-8 -*-
"""P1-6 技能注入：$mention 全文注入 + 清单预算（Codex skills 对齐）。"""
import pytest

from neurova.skills.skill_injection import (
    collect_skill_mention_docs,
    inject_skill_mentions,
    parse_skill_mentions,
    render_skill_catalog,
)


class _FakeSkill:
    def __init__(self, name, description="", doc_text=None):
        self.name = name
        self.description = description
        self.doc_text = doc_text


class _FakeRegistry:
    def __init__(self, skills: dict):
        self.skills = skills


class TestParseSkillMentions:
    def test_dollar_and_at_mentions(self):
        assert parse_skill_mentions("用 $web-search 查一下，或 @pdf_reader 处理") == [
            "web-search",
            "pdf_reader",
        ]

    def test_dedupe_preserve_order(self):
        assert parse_skill_mentions("$a $b $a") == ["a", "b"]

    def test_no_mention(self):
        assert parse_skill_mentions("普通消息 $ 无技能") == []
        assert parse_skill_mentions("") == []


class TestCollectMentionDocs:
    def test_exact_mention_returns_doc(self):
        reg = _FakeRegistry({"web-search": _FakeSkill("web-search", "搜索", "# 用法\n先搜后引")})
        block = collect_skill_mention_docs(reg, ["web-search"])
        assert "[技能说明 web-search]" in block
        assert "# 用法" in block

    def test_prefix_match(self):
        reg = _FakeRegistry({"web-search": _FakeSkill("web-search", "搜索", "DOC")})
        assert "DOC" in collect_skill_mention_docs(reg, ["web"])

    def test_unknown_mention_empty(self):
        reg = _FakeRegistry({"a": _FakeSkill("a", "x", "doc")})
        assert collect_skill_mention_docs(reg, ["nope"]) == ""

    def test_budget_truncates(self):
        reg = _FakeRegistry({
            "big": _FakeSkill("big", "d", "B" * 8000),
            "small": _FakeSkill("small", "d", "S" * 100),
        })
        block = collect_skill_mention_docs(reg, ["big", "small"], max_chars=4000)
        assert "small" in block and "B" * 100 not in block


class TestRenderCatalog:
    def test_lines_with_description(self):
        reg = _FakeRegistry({
            "a": _FakeSkill("a", "技能A"),
            "b": _FakeSkill("b", "技能B"),
        })
        text = render_skill_catalog(reg)
        assert "- a — 技能A" in text and "- b — 技能B" in text

    def test_over_budget_degrades_to_alias_only(self):
        reg = _FakeRegistry({
            f"skill_{i}": _FakeSkill(f"skill_{i}", "很长的描述" * 100) for i in range(50)
        })
        text = render_skill_catalog(reg, max_chars=1000)
        assert "skill_49" in text
        assert "很长的描述" not in text  # 别名压缩：描述丢弃
        assert len(text) <= 1000

    def test_empty_registry(self):
        assert render_skill_catalog(_FakeRegistry({})) == ""
        assert render_skill_catalog(None) == ""


class TestInjectSkillMentions:
    def test_no_mention_passthrough(self):
        assert inject_skill_mentions("普通消息", _FakeRegistry({"a": _FakeSkill("a")})) == "普通消息"
        assert inject_skill_mentions("$a", None) == "$a"

    def test_mention_appends_doc_block(self):
        reg = _FakeRegistry({"pdf": _FakeSkill("pdf", "PDF 处理", "# PDF 指南")})
        out = inject_skill_mentions("帮我 $pdf 处理文件", reg)
        assert out.startswith("帮我 $pdf 处理文件")
        assert "# PDF 指南" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
