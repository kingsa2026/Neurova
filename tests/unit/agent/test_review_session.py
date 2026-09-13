# -*- coding: utf-8 -*-
"""P1-8 /review 受限子会话：rubric/容错解析/受限执行。"""
import json
from types import SimpleNamespace

import pytest

from neurova.agent.review import (
    REVIEW_SYSTEM_PROMPT,
    build_review_messages,
    parse_review_output,
    run_review,
)


class TestParseReviewOutput:
    def test_bare_json(self):
        raw = json.dumps({
            "findings": [{"title": "越界", "body": "index 越界", "priority": "P0",
                          "code_location": "a.py:10"}],
            "overall_correctness": "issues_found",
            "overall_explanation": "有一个 P0",
            "overall_confidence_score": 0.9,
        })
        out = parse_review_output(raw)
        assert out["parse_ok"] is True
        assert out["findings"][0]["priority"] == "P0"
        assert out["overall_correctness"] == "issues_found"

    def test_fenced_json_with_prose(self):
        raw = "评审结果如下：\n```json\n" + json.dumps({
            "findings": [{"title": "t", "body": "b", "priority": "p3"}],
            "overall_correctness": "correct",
        }) + "\n```\n以上。"
        out = parse_review_output(raw)
        assert out["parse_ok"] is True
        assert out["findings"][0]["priority"] == "P3"  # 小写归一

    def test_unknown_priority_defaults_p2(self):
        raw = json.dumps({"findings": [{"title": "t", "priority": "urgent"}],
                          "overall_correctness": "correct"})
        assert parse_review_output(raw)["findings"][0]["priority"] == "P2"

    def test_malformed_returns_raw(self):
        out = parse_review_output("我觉得代码还行，没有 JSON")
        assert out["parse_ok"] is False
        assert "还行" in out["raw"]
        assert out["findings"] == []

    def test_non_list_findings_dropped(self):
        raw = json.dumps({"findings": "oops", "overall_correctness": "correct"})
        out = parse_review_output(raw)
        assert out["parse_ok"] is True and out["findings"] == []


class TestBuildMessages:
    def test_rubric_and_target(self):
        msgs = build_review_messages("diff 内容", focus="并发")
        assert msgs[0]["role"] == "system"
        assert "P0" in msgs[0]["content"] and "findings" in msgs[0]["content"]
        assert "diff 内容" in msgs[1]["content"]
        assert "并发" in msgs[1]["content"]


class TestRunReview:
    @pytest.mark.asyncio
    async def test_structured_result(self):
        def fake_chat(messages):
            assert messages[0]["role"] == "system"
            return SimpleNamespace(content=json.dumps({
                "findings": [], "overall_correctness": "correct",
                "overall_explanation": "ok", "overall_confidence_score": 0.8,
            }), model="test-model")

        out = await run_review(fake_chat, "some diff")
        assert out["parse_ok"] is True
        assert out["model"] == "test-model"
        assert out["overall_correctness"] == "correct"

    @pytest.mark.asyncio
    async def test_no_tools_contract(self):
        """review 调用不携带 tools（受限子会话契约）。"""
        captured = {}

        def fake_chat(messages, **kwargs):
            captured["kwargs"] = kwargs
            return SimpleNamespace(content="not json", model="m")

        out = await run_review(fake_chat, "diff")
        assert out["parse_ok"] is False
        assert captured["kwargs"].get("tools") is None


class TestRubricContract:
    def test_rubric_mentions_priorities_and_schema(self):
        for token in ("P0", "P1", "P2", "P3", "overall_correctness", "code_location"):
            assert token in REVIEW_SYSTEM_PROMPT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
