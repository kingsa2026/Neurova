# -*- coding: utf-8 -*-
"""P1-8 命令面：/review 聊天命令（extract/format/build_history_target + 管线接线）。"""
import json
from types import SimpleNamespace
from typing import Any

import pytest

from neurova.agent.review_command import (
    build_history_target,
    extract_review_target,
    format_review_reply,
)


class TestExtractReviewTarget:
    def test_with_args(self):
        assert extract_review_target("/review diff 内容") == "diff 内容"

    def test_no_args_empty_string(self):
        assert extract_review_target("/review") == ""
        assert extract_review_target("/review   ") == ""

    def test_non_command_returns_none(self):
        assert extract_review_target("普通消息") is None
        assert extract_review_target("") is None
        assert extract_review_target("/compact") is None

    def test_case_insensitive(self):
        assert extract_review_target("/REVIEW xxx") == "xxx"


class TestFormatReviewReply:
    def test_structured_findings_sorted_by_priority(self):
        reply = format_review_reply({
            "parse_ok": True,
            "findings": [
                {"title": "小问题", "body": "细节", "priority": "P2", "code_location": "a.py:3"},
                {"title": "致命", "body": "会崩", "priority": "P0", "code_location": "b.py:1"},
            ],
            "overall_correctness": "issues_found",
            "overall_explanation": "有一个 P0",
        })
        assert reply.index("致命") < reply.index("小问题")  # P0 在前
        assert "b.py:1" in reply
        assert "⚠️ 发现问题" in reply

    def test_no_findings(self):
        reply = format_review_reply({
            "parse_ok": True, "findings": [], "overall_correctness": "correct",
            "overall_explanation": "干净",
        })
        assert "未发现" in reply and "✅" in reply

    def test_parse_failure_shows_raw(self):
        reply = format_review_reply({"parse_ok": False, "raw": "模型自由文本"})
        assert "模型自由文本" in reply


class TestBuildHistoryTarget:
    def test_role_annotated(self):
        target = build_history_target([
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ])
        assert "[user] 问题" in target and "[assistant] 回答" in target

    def test_budget_truncates(self):
        target = build_history_target([{"role": "user", "content": "x" * 30000}])
        assert len(target) <= 24000


class TestPipelineWiring:
    def _pipeline(self, llm_reply: Any):
        from unittest.mock import MagicMock

        from neurova.agent.chat_pipeline import ChatPipeline

        agent = MagicMock()
        agent.llm_client.chat = lambda messages: SimpleNamespace(content=llm_reply, model="m")
        agent.config.agent_id = "a1"
        agent.session_manager.get_recent_context.return_value = [
            {"role": "user", "content": "旧消息"}
        ]
        pipe = ChatPipeline.__new__(ChatPipeline)
        pipe._agent = agent
        # config/session_manager 均为只读 property（委托 _agent），只设 _agent
        return pipe

    @pytest.mark.asyncio
    async def test_review_command_short_circuits(self):
        pipe = self._pipeline(json.dumps({
            "findings": [{"title": "t", "body": "b", "priority": "P1", "code_location": "x.py:1"}],
            "overall_correctness": "issues_found", "overall_explanation": "e",
        }))
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="/review 检查这段")
        await pipe._check_review_command(ctx)
        assert ctx.metadata.get("command_dispatched") is True
        assert "P1" in ctx.reply and "t" in ctx.reply

    @pytest.mark.asyncio
    async def test_review_without_args_uses_history(self):
        captured = {}

        def fake_chat(messages):
            captured["target"] = messages[1]["content"]
            return SimpleNamespace(content=json.dumps({
                "findings": [], "overall_correctness": "correct",
            }), model="m")

        pipe = self._pipeline(None)
        pipe._agent.llm_client.chat = fake_chat
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="/review", session_id="s1")
        await pipe._check_review_command(ctx)
        assert "旧消息" in captured["target"]
        assert "✅" in ctx.reply

    @pytest.mark.asyncio
    async def test_non_review_untouched(self):
        pipe = self._pipeline("{}")
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="普通问题")
        await pipe._check_review_command(ctx)
        assert ctx.reply is None
        assert not (ctx.metadata or {}).get("command_dispatched")

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        pipe = self._pipeline(None)

        def boom(messages):
            raise RuntimeError("llm down")

        pipe._agent.llm_client.chat = boom
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="/review 内容")
        await pipe._check_review_command(ctx)
        # 异常回落：不短路、不设置回复
        assert ctx.reply is None
        assert not (ctx.metadata or {}).get("command_dispatched")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestWordBoundary:
    def test_reviews_not_matched(self):
        """/reviews、/reviewxyz 不是 /review 命令（词边界防误短路 LLM）。"""
        assert extract_review_target("/reviews something") is None
        assert extract_review_target("/reviewxyz") is None

    def test_trailing_space_still_matches(self):
        assert extract_review_target("/review ") == ""
        assert extract_review_target("/review 检查") == "检查"
