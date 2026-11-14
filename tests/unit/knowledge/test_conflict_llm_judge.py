# -*- coding: utf-8 -*-
"""C2（graphiti 对照批）：冲突裁决 LLM 参考意见——prompt/解析/编排纯函数面。

纪律：意见只读辅助，不落账不改状态；解析不合法/winner 越权一律 ValueError。
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.knowledge.foundation.conflict_llm_judge import (
    buildConflictAdvicePrompt,
    llmConflictAdvice,
    parseLlmConflictAdvice,
)

MEMBERS = [
    {"fact_id": "f1", "predicate_term_id": "status", "object_term": "在线",
     "content": "A1 status 在线", "evidence_state": "evidenced", "recorded_at": "2026-11-14T10:00:00"},
    {"fact_id": "f2", "predicate_term_id": "status", "object_term": "离线",
     "content": "A1 status 离线", "evidence_state": "evidenced", "recorded_at": "2026-11-14T10:00:00"},
]


class TestBuildPrompt:
    def test_carriesMemberFields(self):
        messages = buildConflictAdvicePrompt(MEMBERS)
        assert messages[0]["role"] == "system"
        assert "winner_fact_id" in messages[0]["content"]
        body = messages[1]["content"]
        assert "f1" in body and "f2" in body
        assert "在线" in body and "离线" in body

    def test_truncatesLongContent(self):
        long_member = dict(MEMBERS[0], content="x" * 500)
        body = buildConflictAdvicePrompt([long_member])[1]["content"]
        assert "x" * 201 not in body


class TestParseAdvice:
    def test_plainJson(self):
        advice = parseLlmConflictAdvice(
            '{"contradicts": true, "winner_fact_id": "f1", "reason": "证据更足"}',
            ["f1", "f2"])
        assert advice == {"contradicts": True, "winner_fact_id": "f1",
                          "reason": "证据更足"}

    def test_codeFenceStripped(self):
        text = '```json\n{"contradicts": false, "winner_fact_id": "", "reason": "同一说法"}\n```'
        advice = parseLlmConflictAdvice(text, ["f1", "f2"])
        assert advice["contradicts"] is False
        assert advice["winner_fact_id"] == ""

    def test_badJsonRaises(self):
        with pytest.raises(ValueError):
            parseLlmConflictAdvice("不是 JSON", ["f1", "f2"])

    def test_winnerOutsideMembersRaises(self):
        with pytest.raises(ValueError):
            parseLlmConflictAdvice(
                '{"contradicts": true, "winner_fact_id": "f9", "reason": "x"}',
                ["f1", "f2"])

    def test_emptyWinnerAllowed(self):
        advice = parseLlmConflictAdvice(
            '{"contradicts": true, "winner_fact_id": null, "reason": "都存疑"}',
            ["f1", "f2"])
        assert advice["winner_fact_id"] == ""


class TestOrchestration:
    def test_llmAdviceEndToEnd(self):
        class _FakeLlm:
            def __init__(self):
                self.seen = None

            async def chat(self, messages, **kwargs):
                self.seen = messages
                return SimpleNamespace(content=json.dumps(
                    {"contradicts": True, "winner_fact_id": "f2", "reason": "离线更可信"}))

        fake = _FakeLlm()
        advice = asyncio.run(llmConflictAdvice(fake, MEMBERS))
        assert advice["winner_fact_id"] == "f2"
        assert advice["contradicts"] is True
        assert advice["members"] == ["f1", "f2"]
        assert fake.seen is not None

    def test_llmFailurePropagates(self):
        class _BrokenLlm:
            async def chat(self, messages, **kwargs):
                raise ConnectionError("网关不可达")

        with pytest.raises(ConnectionError):
            asyncio.run(llmConflictAdvice(_BrokenLlm(), MEMBERS))

    def test_badLlmOutputRaisesValueError(self):
        class _BadLlm:
            async def chat(self, messages, **kwargs):
                return SimpleNamespace(content="我不同意")

        with pytest.raises(ValueError):
            asyncio.run(llmConflictAdvice(_BadLlm(), MEMBERS))
